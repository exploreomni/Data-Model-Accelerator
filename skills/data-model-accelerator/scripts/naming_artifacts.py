"""Read-only naming checks against the selected identity registry.

No SQL/Jinja execution or rename. Unsupported syntax stays unsupported. A clean
local name check is not physical binding, business acceptance or deployment.
"""
import ast
import copy
import csv
import io
import json
from pathlib import Path

from ae_common import _path, hash_json, require, safe_relative
from authoring_evidence import finding, summarize as summarize_findings
from deployment_workflow import _stable_bytes
from dbt_references import extract_references, scan_templates

KINDS = {'dbt_model', 'dbt_properties', 'dbt_sources', 'omni_view', 'omni_topic',
         'native_sql', 'identity_json', 'identity_csv'}


def _read(root, path):
    resolved = _path(root / safe_relative(path))
    require(root in resolved.parents, 'Naming artifact escapes its root')
    raw = _stable_bytes(resolved)
    require(len(raw) <= 16 * 1024 * 1024, 'Naming artifact exceeds the 16 MiB bound')
    return raw


def _pins(state, resource_ids):
    from naming_governance import records, scope_bindings
    wanted = set(resource_ids)
    pins = scope_bindings(state)
    return hash_json({r['id']: pins[r['entity_id']] for r in records(state) if r['id'] in wanted})


def audit(state, root, artifacts, expected_paths=None):
    from naming_governance import records, stage_requirements, folder_requirement
    import hashlib
    root = _path(root)
    require(type(artifacts) is list and len(artifacts) <= 20000, 'Expected bounded artifact associations')
    resources = {r['id']: r for r in records(state)}
    names = {r['target_name'] for r in resources.values()}
    findings, hashes, associations, seen = [], {}, [], set()
    for supplied in artifacts:
        require(type(supplied) is dict and {'path', 'kind', 'resource_ids'} <= set(supplied)
                <= {'path', 'kind', 'resource_ids', 'semantic_name'}, 'Invalid naming artifact association')
        row = copy.deepcopy(supplied)
        path, kind, selected = row['path'], row['kind'], row['resource_ids']
        safe_relative(path)
        require(kind in KINDS and type(selected) is list and selected and len(set(selected)) == len(selected)
                and all(r in resources for r in selected), 'Naming association requires known resource IDs and format')
        require(path not in seen, 'Duplicate naming artifact path')
        seen.add(path)
        if 'semantic_name' in row:
            require(kind in {'omni_view', 'omni_topic'} and type(row['semantic_name']) is str
                    and row['semantic_name'].strip(), 'Semantic name needs an explicit literal label')
        raw = _read(root, path); hashes[path] = hashlib.sha256(raw).hexdigest()
        text = raw.decode('utf-8')
        associations.append(row)
        bound = [resources[r] for r in selected]
        def emit(code, status, resource=None, field=None):
            findings.append(finding('naming.' + code, status,
                model_id=resource['entity_id'] if resource else None, path=path, field=field))
        for resource in bound:
            for gap in stage_requirements(state, [resource['entity_id']]):
                emit('policy_or_identity_unresolved', 'not_run', resource)
            if kind in {'dbt_model', 'native_sql'}:
                folder = folder_requirement(state, resource)
                if folder is not None:
                    emit('model_folder', 'passed' if Path(path).parent.as_posix() == folder else 'failed', resource)
        if kind == 'dbt_model':
            require(len(bound) == 1, 'A dbt model file needs one resource identity')
            resource = bound[0]
            emit('model_filename', 'passed' if Path(path).stem == resource['target_name'] else 'failed', resource)
            parsed = extract_references(text)
            expected = {r['target_name'] for r in resources.values() if r['role'] != 'source'}
            for ref in parsed['references']:
                if ref['kind'] == 'ref':
                    # Package and version semantics need native manifest evidence.
                    if ref.get('package') or ref.get('version') is not None:
                        emit('qualified_ref_unverified', 'unsupported', resource)
                    else:
                        emit('ref_identity', 'passed' if ref['name'] in expected else 'failed', resource, ref['name'])
                else:
                    emit('source_binding_native_unverified', 'unsupported', resource)
            explicit_alias = None
            for token in scan_templates(text):
                if token['kind'] in {'comment'}:
                    continue
                content = token.get('content', '')
                if token['kind'] == 'expression' and content.startswith('config(') and not token.get('context'):
                    try:
                        call = ast.parse(content, mode='eval').body
                        require(isinstance(call, ast.Call) and not call.args, 'Unsupported config syntax')
                        for kw in call.keywords:
                            if kw.arg in {'alias', 'schema', 'database'}:
                                if not isinstance(kw.value, ast.Constant) or not isinstance(kw.value.value, str):
                                    emit('dynamic_relation_unverified', 'unsupported', resource, kw.arg)
                                elif kw.arg == 'alias':
                                    explicit_alias = kw.value.value
                                else:
                                    emit('environment_namespace_unverified', 'unsupported', resource, kw.arg)
                    except (SyntaxError, ValueError):
                        emit('config_unverified', 'unsupported', resource)
                elif token['kind'] not in {'comment'} and not any(r['span'] == token['span'] for r in parsed['references']):
                    emit('template_unverified', 'unsupported', resource)
            alias = resource.get('physical_alias') or resource['target_name']
            if explicit_alias is not None:
                emit('physical_alias', 'passed' if explicit_alias == alias else 'failed', resource)
            elif resource.get('physical_alias'):
                emit('inherited_alias_unverified', 'unsupported', resource)
        elif kind in {'dbt_properties', 'dbt_sources', 'omni_view', 'omni_topic'}:
            try:
                from source_adapters.base import read_yaml
                data = read_yaml(text)
            except ImportError:
                emit('yaml_reader_unavailable', 'unsupported'); continue
            except Exception as error:
                emit('yaml_invalid', 'failed'); continue
            if not isinstance(data, dict):
                emit('yaml_object_required', 'failed'); continue
            if kind == 'dbt_properties':
                rows = data.get('models')
                if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get('name'), str) for r in rows):
                    emit('properties_schema_invalid', 'failed'); continue
                actual = [r['name'] for r in rows]
                emit('properties_identities', 'passed' if len(actual) == len(set(actual))
                     and set(actual) == {r['target_name'] for r in bound} else 'failed')
            elif kind == 'dbt_sources':
                # Physical source identity cannot be invented from a renamed dbt source key.
                sources = data.get('sources')
                if not isinstance(sources, list) or not all(isinstance(s, dict) and isinstance(s.get('tables'), list)
                        and all(isinstance(t, dict) and isinstance(t.get('identifier', t.get('name')), str) for t in s['tables']) for s in sources):
                    emit('sources_schema_invalid', 'failed'); continue
                actual = [(s.get('database'), s.get('schema'), t.get('identifier', t.get('name')))
                          for s in sources for t in s['tables']]
                for resource in bound:
                    source = resource.get('source_relation')
                    if not source or len(source['namespace']) != 2:
                        emit('source_identity_unverified', 'unsupported', resource)
                    else:
                        expected = tuple(source['namespace'] + [source['name']])
                        emit('source_identity', 'passed' if expected in actual else 'failed', resource)
            elif kind == 'omni_view':
                require(len(bound) == 1, 'An Omni view needs one physical resource identity')
                resource = bound[0]
                expected = resource.get('physical_alias') or resource['target_name']
                if 'table_name' in data:
                    emit('omni_table_binding', 'passed' if data['table_name'] == expected else 'failed', resource)
                else:
                    emit('omni_derived_binding_unverified', 'unsupported', resource)
                for attr, position in [('schema', -1), ('catalog', -2)]:
                    if attr in data and len(resource['namespace']) >= abs(position):
                        emit('omni_' + attr, 'passed' if data[attr] == resource['namespace'][position] else 'failed', resource)
                if row.get('semantic_name'):
                    stem = Path(path).name
                    for suffix in ('.view.yaml', '.view.yml', '.view'):
                        if stem.endswith(suffix): stem = stem[:-len(suffix)]; break
                    emit('omni_view_name', 'passed' if stem == row['semantic_name'] else 'failed', resource)
            else:
                if not row.get('semantic_name'):
                    emit('topic_view_binding_unverified', 'unsupported')
                else:
                    # semantic_name is the explicitly bound base view, not an inferred warehouse alias.
                    emit('topic_base_view', 'passed' if data.get('base_view') == row['semantic_name'] else 'failed')
                if data.get('joins'):
                    emit('topic_join_bindings_unverified', 'unsupported')
        elif kind in {'identity_json', 'identity_csv'}:
            from source_adapters.base import read_json
            rows = read_json(text) if kind == 'identity_json' else list(csv.DictReader(io.StringIO(text)))
            require(type(rows) is list and all(isinstance(r, dict) for r in rows), 'Identity artifact must be a row list')
            actual = {r.get('resource_id'): r for r in rows}
            emit('identity_scope', 'passed' if len(actual) == len(rows) and set(actual) == set(selected) else 'failed')
            for resource in bound:
                observed = actual.get(resource['id'], {})
                for key in ('target_name', 'original_name', 'source_id'):
                    emit('identity_' + key, 'passed' if observed.get(key) == resource[key] else 'failed', resource)
        else:
            # Dialect-specific compiled DDL is checked without connecting to a warehouse.
            try:
                import sqlglot
                from sqlglot import exp
                dialect = state.get('answers', {}).get('warehouse')
                dialect = {'motherduck': 'duckdb', 'fabric': 'tsql'}.get(dialect, dialect)
                trees = sqlglot.parse(text, read=dialect)
                actual = []
                for tree in trees:
                    if not isinstance(tree, exp.Create): continue
                    table = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this
                    if isinstance(table, exp.Table): actual.append(table.name)
                expected = [r.get('physical_alias') or r['target_name'] for r in bound]
                emit('native_object_names', 'passed' if sorted(actual) == sorted(expected) else 'failed')
                emit('native_namespace_unverified', 'unsupported')
            except ImportError:
                emit('sql_reader_unavailable', 'unsupported')
            except Exception:
                emit('native_sql_unverified', 'unsupported')
    expected_paths = set(expected_paths if expected_paths is not None else seen)
    for path in sorted(expected_paths - seen):
        findings.append(finding('naming.artifact_unbound', 'not_run', path=path))
    return {'schema_version': 1, 'kind': 'naming_artifact_check', 'artifacts': associations,
            'expected_paths': sorted(expected_paths), 'outputs': hashes,
            'scope_sha256': _pins(state, [r for a in associations for r in a['resource_ids']]),
            'findings': findings, **summarize_findings(findings),
            'qualification': 'Static identity checks; unbound/unsupported artifacts and native resolution remain unverified.'}


def record(state, request, root):
    from engagement_stages import fields
    fields(request, {'schema_version', 'artifacts'}, {'expected_paths', 'entity_ids'})
    require(request['schema_version'] == 1, 'Unsupported naming check version')
    require(state.get('workflow', {}).get('naming_governance'), 'Configure naming before checking artifacts')
    report = audit(state, root, request['artifacts'], request.get('expected_paths'))
    entity_ids = request.get('entity_ids', [])
    from engagement_stages import ids
    ids(entity_ids, {e['id'] for e in state['workflow']['design']['entities']})
    entry = dict(report, artifact_root=str(_path(root)), entity_ids=entity_ids)
    history = state['workflow'].setdefault('naming_artifact_checks', [])
    if not history or history[-1] != entry: history.append(entry)
    return report


def summary(state, selected=None):
    if not state.get('workflow', {}).get('naming_governance'):
        return {'status': 'not_adopted', 'findings': []}
    from naming_governance import records
    allowed = {r['id'] for r in records(state, selected)}
    latest = {}
    for entry in state['workflow'].get('naming_artifact_checks', []):
        for association in entry['artifacts']:
            if set(association['resource_ids']) <= allowed:
                latest[association['path']] = (entry, association)
    findings = []
    for path, (entry, association) in sorted(latest.items()):
        try:
            fresh = audit(state, Path(entry['artifact_root']), [association])
            if fresh['outputs'].get(path) != entry['outputs'].get(path) or fresh['scope_sha256'] != _pins_for_entry(entry, association, state):
                findings.append(finding('naming.artifact_changed', 'not_run', path=path))
            findings += fresh['findings']
        except (ValueError, OSError, KeyError, UnicodeError):
            findings.append(finding('naming.artifact_unavailable', 'not_run', path=path))
    # Missing associations remain visible; a later scoped check cannot erase them.
    for entry in state['workflow'].get('naming_artifact_checks', []):
        if selected is not None:
            associated = {r for a in entry['artifacts'] for r in a['resource_ids']}
            owned = set(entry.get('entity_ids', []))
            if not ((associated and associated <= allowed) or (owned and owned <= set(selected))): continue
        for path in set(entry['expected_paths']) - set(latest):
            findings.append(finding('naming.artifact_unbound', 'not_run', path=path))
    result = summarize_findings(findings)
    if not latest and not findings: result['status'] = 'not_run'
    return {**result, 'artifacts_checked': len(latest), 'findings': findings,
            'qualification': 'Static names only; physical existence, business meaning and deployment are separate.'}


def _pins_for_entry(entry, association, state):
    # A multi-file record binds the complete participating registry. Recheck the
    # full pin before projecting a file, so policy changes cannot reuse old checks.
    current = _pins(state, [r for a in entry['artifacts'] for r in a['resource_ids']])
    return _pins(state, association['resource_ids']) if current == entry['scope_sha256'] else None


def observe_task(state, root, task, contract):
    """Check explicitly associated SQL now; other formats need check-naming bindings."""
    from naming_governance import records
    if not state.get('workflow', {}).get('naming_governance'):
        return None
    identities = {r['entity_id']: r for r in records(state)}
    associations = []
    for model in contract['models']:
        path = model.get('path')
        resource = identities.get(model['id'])
        if path in task['outputs'] and resource and Path(path).suffix.lower() == '.sql':
            associations.append({'path': path, 'kind': 'dbt_model' if state['answers'].get('framework') == 'dbt'
                                 else 'native_sql', 'resource_ids': [resource['id']]})
    return record(state, {'schema_version': 1, 'artifacts': associations,
                         'expected_paths': task['outputs'], 'entity_ids': task['entity_ids']}, root)
