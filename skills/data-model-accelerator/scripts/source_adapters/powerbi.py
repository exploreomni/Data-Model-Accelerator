"""Offline Power BI inventory: pinned PBIP/PBIR checks plus bounded model extraction.

No supplied source code is imported, and no M, DAX, SQL or remote model is run.
TMDL is deliberately a declaration subset, not an implementation of TOM.
"""
from pathlib import Path, PurePosixPath
import re
import tempfile
import unicodedata

from .base import Report, read_json


CAPABILITY = {
    'formats': ['PBIP 1.0 / enhanced PBIR pinned Microsoft schemas',
                'TMSL model.bim database metadata (compatibilityLevel >= 1200)',
                'TMDL declaration subset (tables, fields, partitions, relationships, roles)'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'No API calls, PBIX decoding, TOM validation or M/DAX/SQL execution.',
        'TMDL partial declarations and unsupported grammar require TOM review.',
        'Remote models, service role membership and effective access are not resolved.',
        'Supplied files and API visibility do not establish export completeness.',
    ],
}

_NAME = r"(?:'(?:[^']|'')+'|[^\s'.:=]+)"
_DECL = re.compile(r'^(database|model|table|column|measure|partition|relationship|role|tablePermission|expression) (' + _NAME + r')(?:\s*=\s*(.*))?$')
_REF = re.compile(r'^(' + _NAME + r')\.(' + _NAME + r')$')
_ORDER = re.compile(r'^ref (table|role|expression) (' + _NAME + r')$')
_PARENTS = {'database': {None}, 'model': {None, 'database'},
            'table': {None, 'model'}, 'relationship': {None, 'model'},
            'role': {None, 'model'}, 'expression': {None, 'model'},
            'column': {'table'}, 'measure': {'table'}, 'partition': {'table'},
            'tablePermission': {'role'}}
_PROPS = set('compatibilityLevel culture defaultPowerBIDataSourceVersion lineageTag '
             'description dataType sourceColumn formatString displayFolder isHidden '
             'isKey isAvailableInMdx summarizeBy sortByColumn mode modelPermission '
             'fromColumn toColumn fromCardinality toCardinality isActive '
             'crossFilteringBehavior securityFilteringBehavior joinOnDateBehavior'.split())


def _name(value):
    return value[1:-1].replace("''", "'") if value.startswith("'") else value


def _value(value):
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('""', '"')
    if value in ('true', 'false'):
        return value == 'true'
    return value


class _Parser:
    def __init__(self, files):
        self.r = Report('powerbi', files)
        self.names, self.refs = {}, []
        self.model_ids = {}
        self.legacy_ids = {}

    def add(self, path, loc, kind, name, native, scope, table=None, parent=None):
        if not isinstance(name, str) or not name:
            self.r.gap(path, 'missing_identity', 'Object name is missing or malformed.', loc)
            return None
        key = (scope, kind, table, name.casefold())
        if key in self.names:
            self.r.gap(path, 'duplicate_identity', 'Duplicate or split object declaration requires review: ' + name, loc)
        native_id = native.get('lineageTag') if 'lineageTag' in native else native.get('id')
        if native_id is not None and (not isinstance(native_id, str) or not native_id.strip()):
            self.r.gap(path, 'invalid_native_identity', 'Native identity must be a nonempty string; original value retained without normalization.', loc)
            native_id = None
        oid = self.r.object(path, loc, kind, name, native_id=native_id,
                            native=native, model_scope=scope, table=table, parent_id=parent)
        self.names.setdefault(key, []).append(oid)
        return oid

    def ref(self, path, loc, oid, scope, kind, name, table=None, relationship=None):
        self.refs.append((path, loc, oid, scope, kind, name, table, relationship))

    def expr(self, path, loc, language, value, oid, **details):
        if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
            value = '\n'.join(value)
        if not isinstance(value, str) or not value.strip():
            self.r.gap(path, 'invalid_expression', 'Expression must be nonempty text or an array of lines.', loc)
            return
        self.r.expression(path, loc, language, value, oid, evaluation='not_run', **details)

    def items(self, path, loc, value):
        if not isinstance(value, list):
            self.r.gap(path, 'invalid_collection', 'Expected an array of named objects.', loc)
            return []
        result = []
        for i, item in enumerate(value):
            at = loc + '/' + str(i)
            if not isinstance(item, dict):
                self.r.gap(path, 'invalid_object', 'Expected an object.', at)
            else:
                result.append((at, item))
        return result

    def tmsl(self, path, value):
        self.r.cover(path)
        if not isinstance(value, dict) or not isinstance(value.get('model'), dict):
            self.r.gap(path, 'unsupported_tmsl', 'Expected database metadata with model; TMSL commands are not executed.')
            return
        level = value.get('compatibilityLevel')
        if type(level) is not int or level < 1200:
            self.r.gap(path, 'unsupported_compatibility', 'An explicit tabular compatibilityLevel >= 1200 is required.')
        model = value['model']
        mid = self.add(path, '$/model', 'model', value.get('name'), value, path)
        self.model_ids[path] = mid
        for loc, table in self.items(path, '$/model/tables', model.get('tables', [])):
            name = table.get('name')
            tid = self.add(path, loc, 'table', name, table, path, parent=mid)
            if tid is None:
                continue
            self.legacy_ids[path + '/table:' + name] = tid
            for collection, kind in [('columns', 'column'), ('measures', 'measure'), ('partitions', 'partition')]:
                for at, item in self.items(path, loc + '/' + collection, table.get(collection, [])):
                    oid = self.add(path, at, kind, item.get('name'), item, path, table=name, parent=tid)
                    if oid is None:
                        continue
                    self.legacy_ids[path + '/table:' + name + '/' + kind + ':' + item['name']] = oid
                    if 'expression' in item:
                        self.expr(path, at + '/expression', 'dax', item['expression'], oid)
                    if kind == 'partition':
                        source = item.get('source')
                        if not isinstance(source, dict):
                            self.r.gap(path, 'invalid_partition', 'Partition source is missing or malformed.', at)
                            continue
                        source_type = source.get('type')
                        if not isinstance(source_type, str):
                            self.r.gap(path, 'invalid_partition', 'Partition source type must be a native string; original metadata retained.', at)
                            continue
                        language = {'m': 'm', 'calculated': 'dax', 'query': 'sql'}.get(source_type)
                        if language:
                            key = 'query' if language == 'sql' else 'expression'
                            self.expr(path, at + '/source/' + key, language, source.get(key), oid)
                        else:
                            self.r.gap(path, 'unsupported_partition', 'Partition source retained without interpretation.', at)
        for loc, item in self.items(path, '$/model/relationships', model.get('relationships', [])):
            oid = self.add(path, loc, 'relationship', item.get('name'), item, path, parent=mid)
            if oid is None:
                continue
            self.legacy_ids[path + '/relationship:' + item['name']] = oid
            for side in ('from', 'to'):
                self.ref(path, loc, oid, path, 'column', item.get(side + 'Column'), item.get(side + 'Table'), side)
        for loc, role in self.items(path, '$/model/roles', model.get('roles', [])):
            oid = self.add(path, loc, 'role', role.get('name'), role, path, parent=mid)
            if oid is None:
                continue
            self.legacy_ids[path + '/role:' + role['name']] = oid
            for at, permission in self.items(path, loc + '/tablePermissions', role.get('tablePermissions', [])):
                pid = self.add(path, at, 'tablePermission', permission.get('name'), permission, path, table=role.get('name'), parent=oid)
                if pid is None:
                    continue
                self.ref(path, at, pid, path, 'table', permission.get('name'))
                if 'filterExpression' in permission:
                    self.expr(path, at + '/filterExpression', 'dax', permission['filterExpression'], pid, purpose='row_level_security')
        for loc, item in self.items(path, '$/model/expressions', model.get('expressions', [])):
            oid = self.add(path, loc, 'expression', item.get('name'), item, path, parent=mid)
            if oid is None:
                continue
            language = {'m': 'm', 'dax': 'dax'}.get(str(item.get('kind', '')).lower())
            self.expr(path, loc + '/expression', language or 'unknown', item.get('expression'), oid)
        self.r.gap(path, 'bounded_tmsl', 'Metadata and raw expressions retained; TOM validity, expression dependencies, and effective security are not established.')

    def tmdl(self, path, text):
        self.r.cover(path, 'partial', 'Bounded TMDL declaration grammar; no TOM validation.')
        self.r.gap(path, 'bounded_tmdl', 'Only documented declaration subset is inventoried; partial declarations, omitted defaults and expression dependencies require TOM review.')
        parts = PurePosixPath(path).parts
        scope = ('/'.join(parts[:parts.index('definition')]) or '.') if 'definition' in parts else str(PurePosixPath(path).parent)
        lines = text.splitlines(keepends=True)
        nodes, stack, i = [], [], 0

        def indentation(raw):
            prefix = raw[:len(raw) - len(raw.lstrip(' \t'))]
            if (' ' in prefix and '\t' in prefix) or (' ' in prefix and len(prefix) % 4):
                raise ValueError('Only tab or four-space indentation is supported.')
            return len(prefix) if '\t' in prefix else len(prefix) // 4

        def read_expression(at, depth, initial, default=False):
            start = at
            if initial == '```':
                end = at + 1
                while end < len(lines) and lines[end].strip() != '```':
                    end += 1
                if end == len(lines):
                    raise ValueError('Unterminated fenced expression.')
                # Exact payload and whole source slice retained; no whitespace reconstruction.
                return ''.join(lines[at + 1:end]), ''.join(lines[start:end + 1]), end + 1
            if initial:
                return initial, lines[at], at + 1
            end = at + 1
            minimum = depth + (2 if default else 1)
            while end < len(lines):
                # Once inside an expression, whitespace belongs to M/DAX; mixed
                # indentation in its payload is not structural TMDL indentation.
                prefix = lines[end][:len(lines[end]) - len(lines[end].lstrip(' \t'))]
                if lines[end].strip() and len(prefix.expandtabs(4)) < minimum * 4:
                    break
                end += 1
            raw = ''.join(lines[at + 1:end])
            if not raw.strip():
                raise ValueError('Empty or incorrectly indented expression.')
            return raw, ''.join(lines[start:end]), end

        try:
            while i < len(lines):
                raw, line = lines[i], lines[i].strip()
                loc = 'line:' + str(i + 1)
                if not line or line.startswith('///'):
                    i += 1
                    continue
                depth = indentation(raw)
                if depth > 48:
                    raise ValueError('TMDL nesting limit exceeded.')
                while stack and stack[-1]['depth'] >= depth:
                    stack.pop()
                parent = stack[-1] if stack else None
                match = _DECL.fullmatch(line)
                order = _ORDER.fullmatch(line)
                if order:
                    if parent and parent['kind'] == 'model' and depth == parent['depth'] + 1:
                        parent['refs'].append((order[1], _name(order[2]), loc))
                    else:
                        self.r.gap(path, 'unsupported_tmdl_fragment', 'Ordering reference outside model retained only in source.', loc)
                    i += 1
                    continue
                if match:
                    kind, name, default = match.groups()
                    if (parent['kind'] if parent else None) not in _PARENTS[kind] or (parent and depth != parent['depth'] + 1) or (not parent and depth != 0):
                        raise ValueError('Unsupported declaration parent or indentation.')
                    node = {'kind': kind, 'name': _name(name), 'depth': depth, 'loc': loc,
                            'parent': parent, 'native': {}, 'expressions': [], 'refs': []}
                    nodes.append(node)
                    stack.append(node)
                    if default is not None and kind == 'partition':
                        node['native']['sourceType'] = default
                        i += 1
                    elif default is not None and kind in ('measure', 'column', 'expression', 'tablePermission'):
                        value, raw_expr, i = read_expression(i, depth, default, default=True)
                        node['expressions'].append(('m' if kind == 'expression' else 'dax', value, loc, raw_expr))
                    elif default is not None:
                        raise ValueError('Unsupported default property.')
                    else:
                        i += 1
                    continue
                if not parent or depth != parent['depth'] + 1:
                    raise ValueError('Unsupported object or property indentation.')
                expr = re.fullmatch(r'(source|filterExpression|expression)\s*=\s*(.*)', line)
                if expr:
                    language = ({'m': 'm', 'calculated': 'dax'}.get(parent['native'].get('sourceType'), 'unknown')
                                if parent['kind'] == 'partition' else 'dax')
                    if language == 'unknown':
                        self.r.gap(path, 'unsupported_partition', 'Uninterpreted partition source language.', loc)
                    value, raw_expr, i = read_expression(i, depth, expr[2])
                    parent['expressions'].append((language, value, loc, raw_expr))
                    continue
                prop = re.fullmatch(r'([A-Za-z][A-Za-z0-9]*)(?::\s*(.*))?', line)
                if prop and prop[1] in _PROPS:
                    if prop[1] in parent['native']:
                        raise ValueError('Duplicate property.')
                    parent['native'][prop[1]] = True if prop[2] is None else _value(prop[2])
                else:
                    self.r.gap(path, 'unsupported_tmdl_fragment', 'Uninterpreted TMDL fragment: ' + line[:120], loc)
                    # Unknown nested structures must not become children of a recognized object.
                    i += 1
                    while i < len(lines) and (not lines[i].strip() or indentation(lines[i]) > depth):
                        i += 1
                    continue
                i += 1
        except ValueError as error:
            self.r.gap(path, 'malformed_or_unsupported_tmdl', str(error), 'line:' + str(i + 1))
            self.r.object(path, '$', 'unparsed_tmdl', PurePosixPath(path).name, raw_text=text)
            return
        for node in nodes:
            parent = node['parent']
            table = parent['name'] if parent and parent['kind'] in ('table', 'role') else None
            oid = self.add(path, node['loc'], node['kind'], node['name'], node['native'], scope,
                           table=table, parent=parent.get('oid') if parent else None)
            node['oid'] = oid
            for language, value, loc, raw_expr in node['expressions']:
                self.expr(path, loc, language, value, oid, raw_tmdl=raw_expr,
                          purpose='row_level_security' if node['kind'] == 'tablePermission' else 'calculation')
            for kind, name, loc in node['refs']:
                self.ref(path, loc, oid, scope, kind, name)
            if node['kind'] == 'tablePermission':
                self.ref(path, node['loc'], oid, scope, 'table', node['name'])
            if node['kind'] == 'relationship':
                for side in ('from', 'to'):
                    ref = node['native'].get(side + 'Column')
                    parsed = _REF.fullmatch(ref) if isinstance(ref, str) else None
                    if parsed:
                        self.ref(path, node['loc'], oid, scope, 'column', _name(parsed[2]), _name(parsed[1]), side)
                    else:
                        self.r.gap(path, 'unresolved_reference', 'Missing or unsupported relationship endpoint.', node['loc'])

    def legacy(self, files):
        """Reuse existing pinned-schema PBIP/PBIR inventory on inert approved files."""
        pbips = [p for p in files if p.lower().endswith('.pbip')]
        if not pbips:
            return
        from powerbi_source import inspect_repo, MAX_FILES, MAX_TOTAL_BYTES, MAX_FILE_BYTES
        if len(files) > MAX_FILES or sum(len(x.encode()) for x in files.values()) > MAX_TOTAL_BYTES or any(len(x.encode()) > MAX_FILE_BYTES for x in files.values()):
            for path in pbips:
                self.r.gap(path, 'legacy_inventory_limit', 'PBIP schema profile has stricter 200-file/10-MB-total/2-MB-file bounds.')
            return
        with tempfile.TemporaryDirectory(prefix='dma-powerbi-') as folder:
            for path, content in files.items():
                target = Path(folder) / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
            inventory = inspect_repo(folder)
        for path in files:
            if path.lower().endswith(('.json', '.pbip', '.pbir', '.pbism')):
                self.r.cover(path)
        for gap in inventory['gaps']:
            path = gap.get('path') if gap.get('path') in files else sorted(pbips)[0]
            # The new TMDL extractor claims this file with its own narrower evidence.
            if path.endswith('.tmdl') and gap['kind'] == 'unsupported_asset':
                continue
            self.r.gap(path, 'legacy_' + gap['kind'], gap['message'])
        for collection, kind in [('projects', 'project'), ('pages', 'page'), ('visuals', 'visual'), ('filters', 'filter')]:
            for index, item in enumerate(inventory[collection]):
                path = item['path']
                oid = self.r.object(path, 'legacy:' + collection + ':' + str(index), kind,
                                    item.get('name') or item.get('id'), native_id=item.get('id'), native=item,
                                    interpretation='legacy_bounded_profile')
                self.legacy_ids[item.get('scoped_id') or item['id']] = oid
        # Keep legacy edges as candidates; the legacy lexical DAX matcher is not a language parser.
        for index, edge in enumerate(inventory['edges']):
            path = edge.get('evidence_path') or inventory.get('model_path')
            if path in files:
                consumer = self.legacy_ids.get(edge['to'])
                if consumer is None:
                    self.r.gap(path, 'legacy_unresolved_edge', 'Legacy edge consumer was not normalized: ' + edge['to'])
                    continue
                self.r.dependency(path, 'legacy:edges:' + str(index), consumer,
                                  self.legacy_ids.get(edge['from'], edge['from']),
                                  kind=edge['kind'], resolution='candidate',
                                  basis='legacy_static_inventory')

    def finish(self):
        for path, loc, oid, scope, kind, name, table, side in self.refs:
            valid = isinstance(name, str) and bool(name.strip()) and (table is None or (isinstance(table, str) and bool(table.strip())))
            targets = self.names.get((scope, kind, table, name.casefold()), []) if valid else []
            resolved = len(targets) == 1
            self.r.dependency(path, loc, oid, targets[0] if resolved else str((table, name)),
                              kind='declared_' + kind, endpoint=side,
                              resolution='resolved' if resolved else 'unresolved')
            if not resolved:
                self.r.gap(path, 'unresolved_reference', 'Missing or ambiguous declared ' + kind + ' reference: ' + str((table, name)), loc)
        return self.r.finish()


def parse(files):
    parser = _Parser(files)
    seen, valid = set(), {}
    for path in sorted(files):
        folded = unicodedata.normalize('NFC', path).casefold()
        if folded in seen:
            raise ValueError('source.path_collision')
        seen.add(folded)
        content = files[path]
        if path.lower().endswith('.tmdl'):
            parser.tmdl(path, content)
            valid[path] = content
        elif path.lower().endswith(('.json', '.pbip', '.pbir', '.pbism', '.bim')):
            try:
                value = read_json(content)
            except ValueError as error:
                parser.r.cover(path, 'unsupported', 'Malformed or unbounded JSON.')
                parser.r.gap(path, 'invalid_json', str(error))
                continue
            if path.lower().endswith('.bim'):
                parser.tmsl(path, value)
            valid[path] = content
        else:
            parser.r.cover(path, 'unsupported', 'Opaque asset; no source code or binary execution.')
    if any(str(parent) in files for path in files for parent in PurePosixPath(path).parents if str(parent) != '.'):
        raise ValueError('source.file_directory_collision')
    parser.legacy(valid)
    return parser.finish()
