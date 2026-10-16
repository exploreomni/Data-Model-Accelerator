"""Bounded LookML declarations and API 4 dashboard snapshots; never compile or run.

The original file is authoritative. lkml's dictionaries retain declarations but
are not Looker's effective model, inherited behavior, or a permissions engine.
"""
import json
import re
from pathlib import PurePosixPath

from .base import MAX_DEPTH, MAX_NODES, Report, bounded, read_json


CAPABILITY = {
    'formats': ['LookML project .lkml/.model/.view/.explore files',
                'Looker API 4 dashboard JSON and schema-1 looker_dashboard_export'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'No live acquisition, LookML compilation, query execution or native validation.',
        'Includes match supplied paths only; imported projects and export completeness remain unverified.',
        'Extends, refinements, Liquid, parameters and user attributes are preserved without evaluation.',
        'Connection names do not establish SQL dialect; field references are unbound candidates.',
        'Effective permissions, PDT behavior and native LookML dashboard YAML are not interpreted.',
    ],
}

_BLOCKS = {
    'views': 'view', 'explores': 'explore', 'dimensions': 'dimension',
    'dimension_groups': 'dimension_group', 'measures': 'measure',
    'parameters': 'parameter', 'filters': 'filter', 'joins': 'join',
    'access_grants': 'access_grant', 'access_filters': 'access_filter',
    'derived_table': 'derived_table',
}
_FIELD_KINDS = {'dimension', 'dimension_group', 'measure', 'parameter', 'filter'}
_REF = re.compile(r'\$\{([^{}]+)\}')
_NAME = re.compile(r'[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*\Z')


def _load_lookml(text):
    """Reuse lkml's grammar with limits before recursive parsing and conversion."""
    from lkml.lexer import Lexer
    from lkml.parser import Parser
    from lkml.simple import DictVisitor
    from lkml.keys import PLURAL_KEYS
    from lkml.tokens import BlockStartToken, BlockEndToken, ListStartToken, ListEndToken

    if '\0' in text:
        raise ValueError('looker.nul_in_source')

    class BoundedLexer(Lexer):
        last_index, stalled = -1, 0

        def peek(self):
            # lkml 1.3.7 does not advance on a lone semicolon outside an
            # expression. Bound lack of progress without changing its grammar.
            self.stalled = self.stalled + 1 if self.index == self.last_index else 0
            self.last_index = self.index
            if self.stalled > 100 or len(self.tokens) > MAX_NODES:
                raise ValueError('looker.lexical_limit')
            return super().peek()

    class StrictVisitor(DictVisitor):
        def update_tree(self, target, update):
            if any(k in target and k not in PLURAL_KEYS for k in update):
                # Upstream overwrites repeated top-level scalar keys.
                raise ValueError('looker.duplicate_parameter')
            return super().update_tree(target, update)

    tokens = BoundedLexer(text).scan()
    depth = 0
    for token in tokens:
        if isinstance(token, (BlockStartToken, ListStartToken)):
            depth += 1
        elif isinstance(token, (BlockEndToken, ListEndToken)):
            depth -= 1
        if depth > MAX_DEPTH // 2 or depth < 0:
            raise ValueError('looker.structure_limit')
    return bounded(StrictVisitor().visit(Parser(tokens).parse()))


def _reference(report, path, loc, owner, target, kind='lookml_reference'):
    report.dependency(path, loc, owner, target, kind=kind, resolution='unbound')


def _strings(report, path, value, owner, loc, key=''):
    """Retain native expressions and candidate substitutions without evaluation."""
    if isinstance(value, dict):
        for name, child in value.items():
            _strings(report, path, child, owner, loc + '.' + name, name)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _strings(report, path, child, owner, loc + '[%d]' % i, key)
    elif isinstance(value, str):
        dynamic = '{{' in value or '{%' in value
        if key.startswith('sql') or key in ('expression', 'html') or dynamic:
            language = 'lookml_sql' if key.startswith('sql') else 'lookml_expression'
            report.expression(path, loc, language, value, owner,
                              interpretation='native_declaration', parameter=key)
            if key.startswith('sql') and key != 'sql_table_name':
                report.gap(path, 'looker.sql_dialect_unknown',
                           'SQL bodies are retained; a connection name does not establish dialect or compiled SQL.')
        if dynamic:
            report.gap(path, 'looker.dynamic_expression',
                       'Liquid and user-dependent expressions require version-bound native compilation evidence.', loc)
        matches = list(_REF.finditer(value))
        if value.count('${') != len(matches):
            report.gap(path, 'looker.dynamic_reference',
                       'An incomplete or nested substitution cannot be bound statically.', loc)
        for match in matches:
            target = match.group(1)
            if target == 'TABLE':
                continue
            if not _NAME.fullmatch(target):
                report.gap(path, 'looker.dynamic_reference',
                           'A substitution is not a plain declared LookML name.', loc)
            _reference(report, path, loc, owner, target)


def _include_matches(path, pattern, files):
    # All resolution is against the in-memory mapping, never the filesystem.
    if not isinstance(pattern, str) or not pattern or pattern.startswith('//'):
        return None
    if any(v in pattern for v in ('{{', '{%', '${', '?', '[', ']', '\\', ':')):
        return None
    parts = [] if pattern.startswith('/') else list(PurePosixPath(path).parent.parts)
    for part in pattern.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    value, regex, i = '/'.join(parts), '', 0
    while i < len(value):
        if value[i:i + 3] == '**/':
            regex += '(?:.*/)?'; i += 3
        elif value[i:i + 2] == '**':
            regex += '.*'; i += 2
        elif value[i] == '*':
            regex += '[^/]*'; i += 1
        else:
            regex += re.escape(value[i]); i += 1
    matcher = re.compile(regex + r'\Z')
    return [p for p in sorted(files) if matcher.fullmatch(p)
            or (p.endswith('.lkml') and matcher.fullmatch(p[:-5]))]


def _includes(report, path, properties, owner, loc):
    includes = properties.get('includes', [])
    if not isinstance(includes, list):
        report.gap(path, 'looker.invalid_includes', 'Expected repeated include strings.', loc)
        return
    for index, pattern in enumerate(includes):
        location = loc + '.includes[%d]' % index
        matches = _include_matches(path, pattern, report.files)
        if matches is None:
            report.gap(path, 'looker.external_or_dynamic_include',
                       'Imported, dynamic or unsupported include path requires separate source evidence.', location)
        elif not matches:
            report.gap(path, 'looker.missing_include',
                       'No supplied file matches this include; project dependency coverage is incomplete.', location)
        for target in matches or [str(pattern)]:
            report.dependency(path, location, owner, target, kind='includes',
                              resolution='supplied_file' if matches else 'unresolved',
                              native_pattern=pattern, include_order=index)


def _block(report, path, kind, declaration, parent, loc, namespace=None):
    if not isinstance(declaration, dict):
        report.gap(path, 'looker.invalid_block', 'A LookML block was not a mapping.', loc)
        return
    name = declaration.get('name')
    if kind in ('access_filter', 'derived_table'):
        name = declaration.get('field', kind)
    if not isinstance(name, str) or not name:
        report.gap(path, 'looker.missing_name', 'Named LookML declaration has no name.', loc)
        name = kind
    refinement = name.startswith('+') and kind in ('view', 'explore')
    native_id = (namespace + '.' + name) if namespace and kind in _FIELD_KINDS else name
    properties = {k: v for k, v in declaration.items() if k not in _BLOCKS}
    owner = report.object(path, loc, 'lookml_' + kind, name, native_id,
                          parent_id=parent, native_properties=properties, refinement=refinement)
    _strings(report, path, properties, owner, loc)
    _includes(report, path, properties, owner, loc)
    if refinement:
        _reference(report, path, loc, owner, name[1:], 'refines')
        report.gap(path, 'looker.refinement_not_applied',
                   'Refinement and include order are preserved; effective overrides are not computed.', loc)
    extensions = properties.get('extends__all', [])
    if extensions:
        report.gap(path, 'looker.extends_not_applied',
                   'Extends lists are preserved; inherited definitions and defaults are not computed.', loc)
        for group in extensions:
            for target in group if isinstance(group, list) else [group]:
                _reference(report, path, loc + '.extends__all', owner, target, 'extends')
    if kind in ('explore', 'join') and not refinement:
        _reference(report, path, loc, owner,
                   properties.get('from', properties.get('view_name', name)), 'view_binding')
    if 'sql_table_name' in properties:
        table = properties['sql_table_name']
        if isinstance(table, str) and not any(s in table for s in ('${', '{{', '{%')):
            _reference(report, path, loc + '.sql_table_name', owner, table, 'declared_relation')
    if kind in ('access_grant', 'access_filter') or 'required_access_grants' in properties:
        report.gap(path, 'looker.effective_access_unverified',
                   'Access declarations do not establish roles, model sets, user-attribute values or effective access.', loc)
    if kind == 'access_filter':
        for prop in ('field', 'user_attribute'):
            if prop in properties:
                _reference(report, path, loc + '.' + prop, owner, properties[prop], prop)
    if kind == 'derived_table':
        report.gap(path, 'looker.derived_table_behavior_unverified',
                   'SQL/native derived-table declarations are preserved; build, persistence and runtime behavior are unverified.', loc)
        if isinstance(properties.get('explore_source'), dict):
            report.gap(path, 'looker.native_derived_table_uncompiled',
                       'Native derived-table fields, filters and bindings require Looker compilation.', loc)
    child_namespace = name.lstrip('+') if kind == 'view' else namespace
    for key, child_kind in _BLOCKS.items():
        if key not in declaration:
            continue
        rows = declaration[key] if isinstance(declaration[key], list) else [declaration[key]]
        for index, child in enumerate(rows):
            _block(report, path, child_kind, child, owner, loc + '.' + key + '[%d]' % index, child_namespace)


def _lookml(report, path, text):
    report.expression(path, '$source', 'lookml', text, interpretation='preserved_original')
    try:
        data = _load_lookml(text)
    except ImportError:
        report.gap(path, 'looker.parser_dependency_missing', 'Install the pinned lkml dependency for structural extraction.')
        report.cover(path, 'partial')
        return
    except (ValueError, KeyError, SyntaxError, IndexError, RecursionError, TypeError):
        report.gap(path, 'looker.invalid_lookml', 'LookML could not be parsed safely; original text retained without declarations.')
        report.cover(path, 'partial')
        return
    properties = {k: v for k, v in data.items() if k not in _BLOCKS}
    kind = 'lookml_model' if path.endswith(('.model.lkml', '.model')) else 'lookml_file'
    name = PurePosixPath(path).name.removesuffix('.lkml').removesuffix('.model')
    owner = report.object(path, '$', kind, name, name if kind == 'lookml_model' else None,
                          native_properties=properties)
    _includes(report, path, properties, owner, '$')
    _strings(report, path, properties, owner, '$')
    for key, value in properties.items():
        if isinstance(value, (list, dict)) and key not in ('includes',):
            report.gap(path, 'looker.unmodeled_project_construct',
                       'Additional project constructs are preserved without semantic interpretation.', '$.' + key)
    for key, child_kind in _BLOCKS.items():
        if key not in data:
            continue
        rows = data[key] if isinstance(data[key], list) else [data[key]]
        for index, child in enumerate(rows):
            _block(report, path, child_kind, child, owner, '$.' + key + '[%d]' % index)
    report.cover(path, 'parsed', 'LookML declarations only; no effective model or SQL compilation.')


def _dashboard(report, path, text):
    from looker_source import is_looker_dashboard, parse_dashboard
    try:
        payload = read_json(text)
        if not is_looker_dashboard(payload):
            report.cover(path, 'unsupported', 'Not a supported API 4 dashboard export.')
            return
        canonical = parse_dashboard(payload)
    except (ValueError, TypeError, RecursionError):
        report.gap(path, 'looker.invalid_dashboard', 'Dashboard JSON failed bounded source validation.')
        report.cover(path, 'partial')
        return
    report.expression(path, '$source', 'json', text, interpretation='preserved_original')
    source = canonical['source']
    owner = report.object(path, source['source_path'], 'dashboard', source['dashboard_id'],
                          source['dashboard_id'], source_contract=source)
    queries, calculations = {}, set()
    for tile in canonical['tiles']:
        loc = tile['source_path']
        tile_id = report.object(path, loc, 'dashboard_element', tile['id'] or loc, tile['id'],
                                parent_id=owner, native_payload=tile['source_payload'],
                                tile_kind=tile['kind'], filter_listeners=tile['filter_listeners'])
        query = tile['query']
        if isinstance(query, dict):
            qloc = tile['query_source_path']
            if qloc not in queries:
                qid = report.object(path, qloc, 'query', query.get('id', qloc), query.get('id'),
                                    parent_id=owner, native_payload=query)
                queries[qloc] = qid
                for field in query.get('fields', []) if isinstance(query.get('fields'), list) else []:
                    _reference(report, path, qloc + '/fields', qid, field, 'query_field')
                for key in ('filters', 'filter_expression', 'dynamic_fields'):
                    if key in query:
                        value = query[key]
                        report.expression(path, qloc + '/' + key, 'looker_' + key,
                                          value if isinstance(value, str) else json.dumps(value, sort_keys=True),
                                          qid, interpretation='native_declaration')
            report.dependency(path, loc, tile_id, queries[qloc], kind='uses_query', resolution='embedded')
        for calc in tile['calculations']:
            for index, item in enumerate(calc.get('parsed') or []):
                if isinstance(item.get('expression'), str):
                    cloc = calc['source_path'] + '/%d/expression' % index
                    if cloc not in calculations:
                        calculations.add(cloc)
                        calc_owner = queries.get(calc['source_path'].rsplit('/', 1)[0], tile_id)
                        report.expression(path, cloc, 'looker_expression', item['expression'], calc_owner,
                                          interpretation='preserved_original')
    for collection, kind in (('filters', 'dashboard_filter'), ('layouts', 'dashboard_layout')):
        for row in canonical[collection]:
            report.object(path, row['source_path'], kind, row['id'] or row['source_path'], row['id'],
                          parent_id=owner, native_payload=row['source_payload'])
    for dependency in canonical['dependencies']:
        report.dependency(path, dependency['source_path'], owner,
                          json.dumps(dependency['id'], sort_keys=True), kind=dependency['kind'],
                          resolution=dependency['status'])
    for gap in canonical['gaps']:
        report.gap(path, gap['code'], 'Inherited dashboard parser gap; source behavior requires review.', gap['source_path'])
    report.cover(path, 'parsed', 'Reused bounded API 4 dashboard parser; no native execution.')


def parse(files):
    report = Report('looker', files)
    for path, text in sorted(files.items()):
        if path.endswith('.json'):
            _dashboard(report, path, text)
        elif path.endswith(('.dashboard.lkml', '.dashboard', '.dashboard.lookml')):
            report.cover(path, 'unsupported', 'Native LookML dashboard YAML is outside this adapter subset.')
        elif path.endswith(('.lkml', '.model', '.view', '.explore')):
            _lookml(report, path, text)
    return report.finish()
