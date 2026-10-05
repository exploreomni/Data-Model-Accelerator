"""Preview dictionary-v2 projections and apply a reviewed preview to a new copy.

This module never runs dbt, Jinja, macros, SQL, or source project programs.
Static persistence findings require a separately authorized native manifest and
warehouse readback. A generation manifest is an ownership baseline, not approval.
"""
import argparse
from collections import Counter
import copy
import difflib
import hashlib
from importlib import metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

from data_dictionary_v2 import validate_dictionary
from ae_common import load_json
from metadata_descriptions import relation_description, column_description, meaningful_description


YAML_VERSION = '0.18.16'
MANIFEST_NAME = '.dma-docs-ownership.json'
KINDS = {'model': 'models', 'seed': 'seeds', 'snapshot': 'snapshots', 'source': 'sources'}
IGNORED = {'.git', '.venv', 'venv', '__pycache__', 'target', 'logs', 'dbt_packages'}
SECRET_NAMES = {'profiles.yml', 'profiles.yaml', '.env', 'id_rsa', 'id_ed25519'}
TEMPLATE = re.compile(r'\{\{|\{%|\{#')
MISSING = object()


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _path(value, exists=True):
    path = Path(value).expanduser().absolute()
    _need('..' not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)), 'Symlink/traversal path refused')
    _need(not exists or path.exists(), 'Input path does not exist')
    return path


def _relative(value):
    _need(_text(value) and '\\' not in value and not any(ord(c) < 32 for c in value), 'Invalid binding path')
    _need(not TEMPLATE.search(value), 'Binding paths must be literal, never Jinja')
    path = PurePosixPath(value)
    _need(not path.is_absolute() and all(p not in ('', '.', '..') for p in value.split('/'))
          and str(path) == value, 'Binding path must be exact and project-relative')
    _need(not any(part in IGNORED or part in SECRET_NAMES or part.startswith('.env.') for part in path.parts), 'Binding targets an excluded path')
    return value


def _tree(root):
    files, total = {}, 0
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            _need(not (Path(parent) / name).is_symlink(), 'Project contains a symlink; use a bounded regular-file copy')
        directories[:] = sorted(name for name in directories if name not in IGNORED)
        for name in sorted(names):
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            _need(name not in SECRET_NAMES and not name.startswith('.env.'), 'Credential-like project file must be kept outside the generation input')
            info = path.stat()
            _need(stat.S_ISREG(info.st_mode) and info.st_size <= 10 * 1024 * 1024, 'Project file is not a bounded regular file')
            data = path.read_bytes()
            after = path.stat()
            _need((info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                  == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Project changed while being read')
            total += len(data)
            _need(len(files) < 5000 and total <= 100 * 1024 * 1024, 'Project generation limit exceeded')
            files[relative] = data
    _need('dbt_project.yml' in files, 'A dbt_project.yml input is required')
    return files


def _snapshot(files):
    return _hash([{'path': path, 'sha256': hashlib.sha256(data).hexdigest()} for path, data in sorted(files.items())])


def _yaml():
    try:
        from ruamel.yaml import YAML
    except ImportError as error:
        raise ValueError('Install scripts/requirements-metadata.txt before YAML generation') from error
    _need(metadata.version('ruamel.yaml') == YAML_VERSION, 'Unqualified YAML runtime; install pinned requirements-metadata.txt')
    yaml = YAML(typ='rt', pure=True)
    yaml.preserve_quotes = True
    yaml.allow_duplicate_keys = False
    yaml.width = 1000000
    return yaml


def _plain(value, stack=None):
    """Convert safe round-trip values without executing tags or expanding cycles."""
    stack = set() if stack is None else stack
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    _need(isinstance(value, (dict, list)), 'Unsupported YAML tag/scalar requires manual review')
    _need(id(value) not in stack, 'Recursive YAML aliases require manual review')
    stack.add(id(value))
    if isinstance(value, dict):
        _need(all(isinstance(key, str) for key in value), 'Non-text YAML mapping keys require manual review')
        result = {str(key): _plain(item, stack) for key, item in value.items()}
    else:
        result = [_plain(item, stack) for item in value]
    stack.remove(id(value))
    return result


def _counts(value):
    result = Counter()
    def visit(item):
        if isinstance(item, (dict, list)):
            result[id(item)] += 1
            if result[id(item)] > 1:
                return
            children = item.values() if isinstance(item, dict) else item
            for child in children:
                visit(child)
    visit(value)
    return result


def _read_yaml(data):
    yaml = _yaml()
    try:
        text = data.decode('utf-8')
        from ruamel.yaml.util import load_yaml_guess_indent
        value, indent, offset = load_yaml_guess_indent(text, yaml=yaml)
        if indent is not None:
            yaml.indent(mapping=indent - (offset or 0), sequence=indent, offset=offset or 0)
        if '\r\n' in text and '\n' not in text.replace('\r\n', ''):
            yaml.line_break = '\r\n'
        _need(isinstance(value, dict), 'YAML document must be a mapping')
        _plain(value)
        # Refuse directives/custom tags even if their constructors are inert.
        from ruamel.yaml.tokens import TagToken, DirectiveToken, DocumentStartToken, DocumentEndToken
        tokens = list(yaml.scan(text))
        _need(not any(isinstance(token, (TagToken, DirectiveToken)) for token in tokens),
              'YAML directives/tags require a review patch')
        yaml.explicit_start = any(isinstance(token, DocumentStartToken) for token in tokens)
        yaml.explicit_end = any(isinstance(token, DocumentEndToken) for token in tokens)
        return yaml, value
    except (ValueError, UnicodeError) as error:
        raise ValueError('Unsafe or unsupported YAML; use the proposed field patch for review') from error
    except Exception as error:
        # Parser messages may contain customer metadata; preserve only the class.
        raise ValueError('YAML cannot be safely round-tripped: ' + type(error).__name__) from error


def _bindings(document, dictionary):
    _need(type(document) is dict and set(document) == {'schema_version', 'kind', 'project_name', 'resources'}, 'Invalid dbt binding fields')
    _need(type(document['schema_version']) is int and document['schema_version'] == 1
          and document['kind'] == 'dbt_metadata_bindings' and _text(document['project_name']), 'Unsupported dbt binding contract')
    _need(type(document['resources']) is list and document['resources'], 'Explicit resource bindings required')
    lookup = {('model', row['model_id']): row for row in dictionary['models']}
    lookup.update({('source', row['source_id']): row for row in dictionary.get('sources', [])})
    seen, targets, result = set(), set(), []
    for item in document['resources']:
        _need(type(item) is dict, 'Resource binding must be an object')
        kind = item.get('resource_type')
        _need(kind in KINDS, 'Unknown dbt resource type')
        id_key = 'source_id' if kind == 'source' else 'model_id'
        required = {id_key, 'resource_type', 'name', 'property_path', 'columns'}
        required |= {'source_name'} if kind == 'source' else {'config_path'}
        _need(required <= set(item) <= required | {'version', 'description_policy'}, 'Missing or unknown resource binding fields')
        _need(_text(item.get(id_key)) and _text(item.get('name')), 'Explicit resource identity and dbt name are required')
        _need(not _contains_template(item['name']), 'Resource names must be literal, never Jinja')
        key = ('source' if kind == 'source' else 'model', item[id_key])
        _need(key in lookup and key not in seen, 'Missing or duplicate dictionary resource binding')
        seen.add(key)
        path = _relative(item['property_path'])
        _need(PurePosixPath(path).suffix in ('.yml', '.yaml') and path != 'dbt_project.yml', 'Properties require a separate YAML path')
        _need(item.get('description_policy', 'dictionary') in ('dictionary', 'preserve'), 'Unknown description authority policy')
        if kind == 'source':
            _need(_text(item['source_name']) and 'version' not in item, 'Source bindings require a source_name and cannot declare model versions')
            _need(not _contains_template(item['source_name']), 'Source names must be literal, never Jinja')
        else:
            _need(type(item['config_path']) is list and all(_text(p) for p in item['config_path']), 'Explicit project config_path components required')
            _need(not _contains_template(item['config_path']), 'Config paths must be literal, never Jinja')
        if 'version' in item:
            _need(kind == 'model' and (type(item['version']) is int or _text(item['version'])), 'Only model bindings support integer/string versions')
        target = (kind, item.get('source_name'), item['name'], str(item.get('version')) if 'version' in item else None)
        _need(target not in targets, 'Duplicate dbt resource patch binding')
        targets.add(target)
        columns = item['columns']
        _need(type(columns) is list and columns, 'Explicit column bindings required')
        col_lookup = {c['column_id']: c for c in lookup[key]['columns']}
        col_ids, names = set(), set()
        for column in columns:
            _need(type(column) is dict and {'column_id', 'name'} <= set(column) <= {'column_id', 'name', 'description_policy'}, 'Invalid column binding fields')
            _need(_text(column.get('column_id')) and _text(column.get('name')), 'Exact column identity/name required')
            _need(not _contains_template(column['name']), 'Column names must be literal, never Jinja')
            _need(column['column_id'] in col_lookup and column['column_id'] not in col_ids and column['name'] not in names, 'Missing or duplicate exact column binding')
            _need(column.get('description_policy', 'dictionary') in ('dictionary', 'preserve'), 'Unknown column description policy')
            col_ids.add(column['column_id'])
            names.add(column['name'])
        _need(col_ids == set(col_lookup), 'Column binding denominator differs from dictionary')
        result.append((copy.deepcopy(item), lookup[key], col_lookup))
    _need(seen == set(lookup), 'Resource binding denominator differs from dictionary models and sources')
    return sorted(result, key=lambda row: _bytes(row[0]))


def _baseline(value):
    if value is None:
        return {}
    _need(type(value) is dict and value.get('kind') == 'dbt_docs_ownership' and type(value.get('schema_version')) is int
          and value['schema_version'] == 1, 'Unsupported ownership baseline')
    unsigned = {k: v for k, v in value.items() if k != 'manifest_sha256'}
    _need(value.get('manifest_sha256') == _hash(unsigned), 'Ownership baseline digest mismatch')
    fields = value.get('fields')
    _need(type(fields) is list, 'Ownership baseline fields required')
    indexed = {}
    for field in fields:
        _need(type(field) is dict and set(field) == {'id', 'file', 'value'} and _text(field['id']), 'Invalid ownership field')
        _relative(field['file'])
        _need(field['id'] not in indexed, 'Duplicate ownership field')
        indexed[field['id']] = field
    return indexed


def generate_project(project, dictionary, bindings, *, previous_manifest=None, output=None,
                     apply=False, reviewed_preview_sha256=None):
    """Build a preview; apply only that digest to an exclusive new project copy."""
    errors = validate_dictionary(dictionary)
    _need(not errors, 'Dictionary v2 is invalid: ' + '; '.join(errors))
    rows = _bindings(bindings, dictionary)
    baseline = _baseline(previous_manifest)
    root = _path(project)
    _need(root.is_dir(), 'Project must be a directory')
    files = _tree(root)
    source_sha = _snapshot(files)
    dictionary_sha = _hash(dictionary)
    report = {'schema_version': 1, 'kind': 'dbt_docs_preview', 'status': 'ready',
              'source_sha256': source_sha, 'dictionary_sha256': dictionary_sha,
              'bindings_sha256': _hash(bindings), 'previous_manifest_sha256': _hash(previous_manifest),
              'runtime': {'ruamel.yaml': YAML_VERSION}, 'changes': [], 'conflicts': [], 'exceptions': [],
              'field_patch': [], 'limitations': ['Static generation only; no macros or dbt execution.',
                  'Effective SQL/Jinja configuration, adapter persistence and complete physical coverage require native verification.']}
    documents, owned = {}, {}

    def conflict(path, reason):
        report['conflicts'].append({'path': path, 'reason': reason})

    def document(path):
        if path in documents:
            return documents[path]
        raw = files.get(path)
        if raw is None:
            yaml = _yaml()
            from ruamel.yaml.comments import CommentedMap
            value = CommentedMap(version=2)
        else:
            try:
                yaml, value = _read_yaml(raw)
            except ValueError as error:
                conflict(path, str(error))
                documents[path] = None
                return None
        documents[path] = {'yaml': yaml, 'value': value, 'original': copy.deepcopy(_plain(value)),
                           'counts': _counts(value), 'changed': False}
        return documents[path]

    project_doc = document('dbt_project.yml')
    _need(project_doc is not None, 'dbt_project.yml requires safe manual review before projection')
    config = project_doc['value']
    _need(config.get('name') == bindings['project_name'], 'Binding project name differs from dbt_project.yml')
    scopes = []
    for key, default in (('model-paths', ['models']), ('seed-paths', ['seeds']), ('snapshot-paths', ['snapshots'])):
        paths = config.get(key, default)
        # The round-trip YAML loader returns CommentedSeq (a list subclass).
        # Preserve ordinary authored YAML sequences while still rejecting maps,
        # nested values and templated paths below.
        _need(isinstance(paths, list) and paths and all(_text(path) for path in paths), 'Templated/nonliteral resource paths require manual review')
        scopes.extend(_relative(path) for path in paths)
    for item, _, _ in rows:
        _need(any(item['property_path'].startswith(scope + '/') for scope in scopes), 'Property binding is outside declared resource paths')
    for path in sorted(files):
        if PurePosixPath(path).suffix in ('.yml', '.yaml') and any(path.startswith(scope + '/') for scope in scopes):
            document(path)

    def mapping(parent, key, doc, path):
        if key not in parent:
            from ruamel.yaml.comments import CommentedMap
            parent[key] = CommentedMap()
            doc['changed'] = True
        _need(isinstance(parent[key], dict), path + ': expected YAML mapping; manual review required')
        _need(doc['counts'][id(parent)] <= 1 and doc['counts'][id(parent[key])] <= 1,
              path + ': shared YAML alias cannot be safely mutated; use a review patch')
        return parent[key]

    def merge(doc, path, node, keys, desired, field_id, preserve=False):
        identity = json.dumps(field_id, separators=(',', ':'), ensure_ascii=True)
        report['field_patch'].append({'file': path, 'id': identity, 'value': desired, 'preserve': preserve})
        if doc is None:
            return
        try:
            _need(doc['counts'][id(node)] <= 1, 'Shared YAML alias requires manual review')
            parent = node
            for key in keys[:-1]:
                parent = mapping(parent, key, doc, path)
            current = parent.get(keys[-1], MISSING)
            old = baseline.get(identity)
            _need(old is None or old['file'] == path, 'Owned field moved to another property file; review its relocation')
            if preserve:
                _need(current is not MISSING and _text(current), 'Preserve-description policy requires existing nonempty text')
                report['exceptions'].append({'resource': field_id[0], 'field': '.'.join(keys), 'reason': 'Existing authoritative description preserved; native docs resolution/comparison remains required.'})
                return
            _need(not _contains_template(desired), 'Imported template-bearing metadata is inert input; review explicitly before it enters dbt rendering')
            if current is not MISSING and _plain(current) != desired:
                _need(old is not None and _plain(current) == old['value'], 'Existing/human-edited field conflicts with the dictionary; input preserved')
            elif current is MISSING and old is not None:
                raise ValueError('Previously owned field was removed; resolve the deletion explicitly')
            if current is MISSING or _plain(current) != desired:
                _need(doc['counts'][id(parent)] <= 1, 'Shared YAML alias requires manual review')
                parent[keys[-1]] = copy.deepcopy(desired)
                doc['changed'] = True
            owned[identity] = {'id': identity, 'file': path, 'value': copy.deepcopy(desired)}
        except ValueError as error:
            conflict(path, str(error) + ' [' + identity + ']')

    # Detect resource patches across the entire declared property-file scope.
    inventory = {}
    for path, doc in documents.items():
        if doc is None or path == 'dbt_project.yml':
            continue
        try:
            for kind, group in KINDS.items():
                entries = doc['value'].get(group, [])
                _need(isinstance(entries, list), 'Resource properties must be lists')
                for entry in entries:
                    _need(isinstance(entry, dict) and _text(entry.get('name')), 'Invalid resource patch entry')
                    if kind == 'source':
                        for table in entry.get('tables', []):
                            _need(isinstance(table, dict) and _text(table.get('name')), 'Invalid source table patch')
                            key = (kind, entry['name'], table['name'])
                            inventory.setdefault(key, []).append((path, table))
                    else:
                        key = (kind, None, entry['name'])
                        inventory.setdefault(key, []).append((path, entry))
            for key, patches in inventory.items():
                if len(patches) > 1:
                    conflict(path, 'Duplicate resource patches across property files: ' + repr(key))
        except (ValueError, TypeError) as error:
            conflict(path, str(error))

    def resource(item, doc):
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
        kind, name, path = item['resource_type'], item['name'], item['property_path']
        key = (kind, item.get('source_name'), name)
        patches = inventory.get(key, [])
        _need(len(patches) <= 1, 'Duplicate resource patch; cannot choose one')
        if patches:
            _need(patches[0][0] == path, 'An existing property patch owns this resource in a different file')
            node = patches[0][1]
        else:
            parent = doc['value']
            group = KINDS[kind]
            parent.setdefault(group, CommentedSeq())
            _need(isinstance(parent[group], list), 'Resource property group must be a list')
            if kind == 'source':
                sources = [entry for entry in parent[group] if entry.get('name') == item['source_name']]
                _need(len(sources) <= 1, 'Duplicate source definitions')
                if sources:
                    source = sources[0]
                else:
                    source = CommentedMap(name=item['source_name'], tables=CommentedSeq())
                    parent[group].append(source)
                source.setdefault('tables', CommentedSeq())
                parent, group = source, 'tables'
            _need(doc['counts'][id(parent[group])] <= 1, 'Shared YAML list requires manual review')
            node = CommentedMap(name=name)
            parent[group].append(node)
            doc['changed'] = True
            inventory[key] = [(path, node)]
        if 'version' in item:
            node.setdefault('versions', CommentedSeq())
            _need(isinstance(node['versions'], list), 'Model versions must be a list')
            versions = [v for v in node['versions'] if isinstance(v, dict) and str(v.get('v')) == str(item['version'])]
            _need(len(versions) <= 1, 'Duplicate model version definitions')
            if versions:
                node = versions[0]
            else:
                version = CommentedMap(v=item['version'])
                node['versions'].append(version)
                node = version
                doc['changed'] = True
        elif kind == 'model':
            _need('versions' not in node, 'Versioned model requires an explicit version binding')
        return node

    # Only these project defaults are owned. Existing false values are policy exceptions.
    for kind in sorted({'model'} | {row[0]['resource_type'] for row in rows if row[0]['resource_type'] in ('seed', 'snapshot')}):
        try:
            group = mapping(config, KINDS[kind], project_doc, 'dbt_project.yml')
            project_config = mapping(group, bindings['project_name'], project_doc, 'dbt_project.yml')
            existing = project_config.get('+persist_docs', {})
            _need(isinstance(existing, dict), 'Non-mapping persist_docs requires manual review')
            for field in ('relation', 'columns'):
                if existing.get(field) is False:
                    report['exceptions'].append({'resource': kind, 'field': field, 'reason': 'Existing project persist_docs false preserved.'})
                    continue
                merge(project_doc, 'dbt_project.yml', project_config, ['+persist_docs', field], True,
                      ['$project', kind, 'persist_docs', field])
        except ValueError as error:
            conflict('dbt_project.yml', str(error))

    for item, record, columns in rows:
        path, kind = item['property_path'], item['resource_type']
        identity = record['source_id'] if kind == 'source' else record['model_id']
        doc = document(path)
        try:
            node = resource(item, doc) if doc is not None else None
            _need(record['review_status'] == 'approved', 'Resource description is not approved')
            _need(meaningful_description(record), 'Resource description is a placeholder')
            description = relation_description(record)
            merge(doc, path, node, ['description'], description, [identity, 'description'], item.get('description_policy') == 'preserve')
            for key, value in {'resource_id': identity, 'dictionary_sha256': dictionary_sha,
                               'model_role': record['model_role'], 'source_systems': record['source_systems'],
                               'review_status': record['review_status']}.items():
                merge(doc, path, node, ['config', 'meta', 'dma', key], value, [identity, 'config.meta.dma.' + key])
            if node is not None:
                from ruamel.yaml.comments import CommentedMap, CommentedSeq
                node.setdefault('columns', CommentedSeq())
                _need(isinstance(node['columns'], list), 'Columns must be a list')
                names = [c.get('name') for c in node['columns'] if isinstance(c, dict) and 'name' in c]
                _need(len(names) == len(set(names)), 'Duplicate column property patches')
            for binding in sorted(item['columns'], key=lambda col: col['name']):
                column = columns[binding['column_id']]
                _need(column['review_status'] == 'approved', 'Column description is not approved: ' + binding['column_id'])
                _need(meaningful_description(column), 'Column description is a placeholder: ' + binding['column_id'])
                current = None
                if node is not None:
                    matches = [c for c in node['columns'] if isinstance(c, dict) and c.get('name') == binding['name']]
                    if matches:
                        current = matches[0]
                    else:
                        _need(doc['counts'][id(node['columns'])] <= 1, 'Shared column list requires manual review')
                        current = CommentedMap(name=binding['name'])
                        node['columns'].append(current)
                        doc['changed'] = True
                text = column_description(column)
                merge(doc, path, current, ['description'], text, [identity, binding['column_id'], 'description'], binding.get('description_policy') == 'preserve')
                for key, value in {'column_id': binding['column_id'], 'source_refs': column['source_refs'],
                                   'source_text': column['source'], 'sensitivity': column['sensitivity'],
                                   'key_roles': column['key_roles'], 'review_status': column['review_status']}.items():
                    merge(doc, path, current, ['config', 'meta', 'dma', key], value, [identity, binding['column_id'], 'config.meta.dma.' + key])
            if kind == 'source':
                report['exceptions'].append({'resource': identity, 'reason': 'Source YAML documents only; persist_docs does not write source metadata.'})
            else:
                effective = {}
                branch = config.get(KINDS[kind], {}).get(bindings['project_name'], {})
                for part in [None] + item['config_path']:
                    branch = branch if part is None else branch.get(part, {}) if isinstance(branch, dict) else {}
                    setting = branch.get('+persist_docs', {}) if isinstance(branch, dict) else {}
                    if isinstance(setting, dict):
                        effective.update(_plain(setting))
                if node is not None:
                    if 'version' in item:
                        base = inventory[(kind, None, item['name'])][0][1]
                        effective.update(_plain(base.get('config', {}).get('persist_docs', {})))
                    effective.update(_plain(node.get('config', {}).get('persist_docs', {})))
                report['exceptions'].append({'resource': identity, 'effective_static_persist_docs': effective,
                    'reason': 'Native manifest confirmation pending.' if effective.get('relation') is True and effective.get('columns') is True else 'Persistence override/coverage exception; preserved without claiming native coverage.'})
        except (ValueError, TypeError, AttributeError) as error:
            conflict(path, str(error))

    projected = dict(files)
    for path, doc in sorted(documents.items()):
        if doc is None or not doc['changed']:
            continue
        try:
            stream = io.StringIO()
            doc['yaml'].dump(doc['value'], stream)
            proposed = stream.getvalue().encode('utf-8')
            _, parsed = _read_yaml(proposed)
            _need(_plain(parsed) == _plain(doc['value']), 'YAML round-trip changed semantics')
            projected[path] = proposed
            before = files.get(path, b'')
            if before != proposed:
                report['changes'].append({'path': path, 'before_sha256': hashlib.sha256(before).hexdigest() if path in files else None,
                    'after_sha256': hashlib.sha256(proposed).hexdigest(), 'content': proposed.decode(),
                    'diff': ''.join(difflib.unified_diff(before.decode().splitlines(True), proposed.decode().splitlines(True),
                                                      fromfile='before/' + path, tofile='after/' + path))})
        except ValueError as error:
            conflict(path, str(error))
    # Removed bindings/fields require an explicit cleanup plan; never silently erase metadata.
    removed = set(baseline) - set(owned)
    if removed:
        report['exceptions'].append({'resource': '$ownership', 'reason': 'Previously owned fields not projected; retained for review, never automatically deleted.', 'fields': sorted(removed)})
        owned.update({key: baseline[key] for key in removed})
    ownership = {'schema_version': 1, 'kind': 'dbt_docs_ownership', 'project_name': bindings['project_name'],
                 'dictionary_sha256': dictionary_sha, 'bindings_sha256': _hash(bindings),
                 'fields': [owned[key] for key in sorted(owned)]}
    ownership['manifest_sha256'] = _hash(ownership)
    report['ownership_manifest'] = ownership
    report['status'] = 'conflicted' if report['conflicts'] else 'no_op' if not report['changes'] else 'ready'
    report['preview_sha256'] = _hash(report)
    if apply:
        _need(not report['conflicts'], 'Generation conflicts require review; no output written')
        _need(reviewed_preview_sha256 == report['preview_sha256'], 'Apply requires the exact reviewed preview_sha256')
        _need(output is not None, 'Apply requires a new output directory')
        destination = _path(output, exists=False)
        _need(not destination.exists() and destination != root and root not in destination.parents, 'Output must be a new directory outside the input project')
        _need(destination.parent.is_dir(), 'Output parent must exist')
        _need(_snapshot(_tree(root)) == source_sha, 'Project drift after preview')
        destination.mkdir(mode=0o700)
        for path, data in sorted(projected.items()):
            if path == MANIFEST_NAME:
                continue
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
        with (destination / MANIFEST_NAME).open('x', encoding='utf-8') as stream:
            json.dump(ownership, stream, indent=2, ensure_ascii=True)
            stream.write('\n')
        report['applied_to'] = str(destination)
    return report


def _contains_template(value):
    if isinstance(value, str):
        return bool(TEMPLATE.search(value))
    if isinstance(value, dict):
        return any(_contains_template(k) or _contains_template(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_template(item) for item in value)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('project', 'dictionary', 'bindings', 'report'):
        parser.add_argument('--' + field, type=Path, required=True)
    parser.add_argument('--previous-manifest', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reviewed-preview-sha256')
    args = parser.parse_args(argv)
    try:
        report_path = _path(args.report, exists=False)
        _need(not report_path.exists() and report_path.parent.is_dir(), 'Report requires a new path with an existing parent')
        project = _path(args.project)
        _need(project not in report_path.parents, 'Report must stay outside the input project')
        result = generate_project(project, load_json(args.dictionary), load_json(args.bindings),
            previous_manifest=load_json(args.previous_manifest) if args.previous_manifest else None,
            output=args.output, apply=args.apply, reviewed_preview_sha256=args.reviewed_preview_sha256)
        with report_path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=True)
            stream.write('\n')
        print(json.dumps({'status': result['status'], 'preview_sha256': result['preview_sha256'],
                          'conflicts': len(result['conflicts']), 'report': str(report_path)}))
        return 1 if result['conflicts'] else 0
    except (OSError, ValueError, TypeError) as error:
        print('dbt metadata generation refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
