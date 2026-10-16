"""Bounded native Fabric Git/API evidence; no authentication, workloads or SDKs.

Decoded parts stay in memory. Every imported record binds both the original
snapshot bytes and the decoded part bytes; a logicalId is never a service ID.
"""
import base64
import binascii
import copy
import json
from pathlib import PurePosixPath
import re

from .base import Report, read_json, sha, validate_files, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES

ADAPTER_DEPENDENCIES = ('powerbi',)
CAPABILITY = {
    'formats': ['Fabric .platform v2 Git item metadata',
                'Native getDefinition definition.parts with UTF-8 InlineBase64',
                'Notebook FabricGitSource / ipynb 4; DataPipeline top-level declarations',
                'LakehouseDefinitionV1 metadata, shortcuts and security declarations',
                'SemanticModel TMDL / TMSL via bounded Power BI extraction'],
    'interpretation': 'bounded_static_extraction', 'acquisition': 'supplied_exports',
    'limitations': [
        'No live API, SDK, workload, Python, Spark, SQL, M or DAX execution.',
        'Only Notebook, DataPipeline, Lakehouse and SemanticModel bodies have bounded readers.',
        'Git logical IDs are not workspace item IDs; no runtime identity is inferred.',
        'No complete orchestration, effective security, native validation or export-completeness claim.',
        'Fabric is a source evidence adapter, not a new deployment target.',
    ],
}
PLATFORM_SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json'
# The Git source-format article also documents this older URI/root-version shape.
DOCUMENTED_PLATFORM_SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/platform/platformProperties.json'
_TYPES = {'Notebook', 'DataPipeline', 'Lakehouse', 'SemanticModel'}
_FORMATS = {'Notebook': {None, 'FabricGitSource', 'fabricGitSource', 'ipynb'},
            'DataPipeline': {None}, 'Lakehouse': {None, 'LakehouseDefinitionV1'},
            'SemanticModel': {None, 'TMDL', 'TMSL'}}
_NOTEBOOK_SOURCE = {'notebook-content.py': 'fabric-notebook:python',
                    'notebook-content.sql': 'fabric-notebook:sparksql',
                    'notebook-content.scala': 'fabric-notebook:scala',
                    'notebook-content.r': 'fabric-notebook:r'}
_GUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _loc(parent, key):
    return parent + '[' + json.dumps(key, ensure_ascii=True) + ']'


def _gap(r, path, code, message, loc='$'):
    r.gap(path, 'fabric.' + code, message, loc)


def _json(r, path):
    try:
        return read_json(r.files[path])
    except ValueError as error:
        _gap(r, path, 'invalid_json', str(error))
        r.cover(path, 'unsupported', 'Malformed or unbounded native JSON.')
        return None


def _platform(r):
    if '.platform' not in r.files:
        _gap(r, sorted(r.files)[0], 'missing_item_identity', 'Native .platform metadata is required; folder names and API response filenames do not establish item identity.')
        return None, None
    value = _json(r, '.platform')
    if not isinstance(value, dict):
        _gap(r, '.platform', 'invalid_platform', 'Expected a native .platform JSON object.')
        return None, None
    metadata, config = value.get('metadata'), value.get('config')
    if not isinstance(metadata, dict) or not isinstance(config, dict):
        _gap(r, '.platform', 'invalid_platform', 'Native metadata and config objects are required.')
        return None, None
    schema = value.get('$schema')
    version = config.get('version') if schema == PLATFORM_SCHEMA else value.get('version')
    if schema not in (PLATFORM_SCHEMA, DOCUMENTED_PLATFORM_SCHEMA) or version != '2.0' or any(v != '2.0' for v in (value.get('version', '2.0'), config.get('version', '2.0'))):
        _gap(r, '.platform', 'unsupported_platform_version', 'Only the documented v2 metadata profiles are recognized; schema URLs are never fetched.')
        return None, None
    identity, name, kind = config.get('logicalId'), metadata.get('displayName'), metadata.get('type')
    if not isinstance(identity, str) or not _GUID.fullmatch(identity) or not _text(name) or not _text(kind):
        _gap(r, '.platform', 'missing_item_identity', 'A GUID logicalId and explicit displayName/type are required; no identity is inferred.')
        return None, None
    oid = r.object('.platform', '$', 'fabric_item', name, native_id=identity,
                   item_type=kind, identity_kind='git_logical_id', service_item_id=None,
                   raw_metadata=value)
    r.cover('.platform', 'parsed', 'Bounded .platform metadata profile, not full schema validation.')
    if set(value) - {'$schema', 'metadata', 'config', 'version'} or set(metadata) - {'type', 'displayName', 'description'} or set(config) - {'version', 'logicalId'}:
        _gap(r, '.platform', 'unknown_platform_fields', 'Unrecognized metadata fields are retained without interpretation.')
    if schema == DOCUMENTED_PLATFORM_SCHEMA:
        _gap(r, '.platform', 'documented_legacy_profile', 'Root-version shape follows the Git article; the older schema URI was unavailable at research time. No schema-validation claim.')
    _gap(r, '.platform', 'security_and_visibility_unverified', 'Definition metadata omits sensitivity labels and does not establish permissions, credentials, service role membership or complete workspace visibility.')
    if kind not in _TYPES:
        _gap(r, '.platform', 'unsupported_item_type', 'The item type has no body parser in this adapter: ' + kind)
    return oid, kind


def _dynamic(r, path, value, owner, loc='$'):
    """Retain native dynamic expressions, never evaluate or infer dependencies."""
    if isinstance(value, dict):
        if value.get('type') == 'Expression':
            text = value.get('value')
            if isinstance(text, str):
                r.expression(path, loc + '["value"]', 'fabric:expression', text, owner,
                             interpretation='preserved_unexecuted')
            _gap(r, path, 'dynamic_content', 'Dynamic expression requires runtime bindings; no computed dependency is inferred.', loc)
            return
        for key, item in value.items():
            _dynamic(r, path, item, owner, _loc(loc, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _dynamic(r, path, item, owner, loc + '[%d]' % index)
    elif isinstance(value, str) and (value.startswith('@') or '{{' in value or '{%' in value):
        r.expression(path, loc, 'fabric:expression', value, owner, interpretation='preserved_unexecuted')
        _gap(r, path, 'dynamic_content', 'Template or expression-like content remains unbound and unexecuted.', loc)


def _notebook(r, owner, format_name):
    paths = [p for p in r.files if p in _NOTEBOOK_SOURCE or (PurePosixPath(p).parent == PurePosixPath('.') and p.endswith('.ipynb'))]
    if len(paths) != 1:
        _gap(r, '.platform', 'missing_or_ambiguous_notebook', 'Exactly one native notebook source part is required.')
        return
    path = paths[0]
    if (format_name == 'ipynb' and not path.endswith('.ipynb')) or (format_name in ('FabricGitSource', 'fabricGitSource') and path.endswith('.ipynb')):
        _gap(r, path, 'definition_format_mismatch', 'Notebook part disagrees with the explicit format.')
        return
    r.cover(path, 'partial', 'Source preservation only; runtime, environment, magics and data dependencies are unresolved.')
    _gap(r, path, 'notebook_runtime_unresolved', 'Notebook source is retained without execution or runtime/lineage/security claims; outputs are untrusted historical content.')
    if path in _NOTEBOOK_SOURCE:
        r.expression(path, '$source', _NOTEBOOK_SOURCE[path], r.files[path], owner, interpretation='preserved_unexecuted')
        return
    value = _json(r, path)
    if not isinstance(value, dict) or type(value.get('nbformat')) is not int or value['nbformat'] != 4 or type(value.get('nbformat_minor')) is not int or not 0 <= value['nbformat_minor'] <= 5 or not isinstance(value.get('cells'), list):
        _gap(r, path, 'unsupported_notebook_version', 'Only nbformat 4 minor 0 through 5 with an explicit cells array is inventoried.')
        return
    metadata = value.get('metadata', {})
    language_info = metadata.get('language_info', {}) if isinstance(metadata, dict) else {}
    language = language_info.get('name') if isinstance(language_info, dict) else None
    for index, cell in enumerate(value['cells']):
        loc = '$["cells"][%d]' % index
        if not isinstance(cell, dict) or cell.get('cell_type') not in ('code', 'markdown', 'raw'):
            _gap(r, path, 'malformed_notebook_cell', 'Unsupported or malformed notebook cell.', loc)
            continue
        cid = cell.get('id')
        if cid is not None and not _text(cid):
            _gap(r, path, 'malformed_notebook_cell', 'Cell ID must be a nonempty string when present.', loc)
            continue
        source = cell.get('source')
        text = ''.join(source) if isinstance(source, list) and all(isinstance(x, str) for x in source) else source
        if not isinstance(text, str):
            _gap(r, path, 'malformed_notebook_cell', 'Cell source must be text or a list of text fragments.', loc)
            continue
        oid = r.object(path, loc, 'fabric_notebook_cell', cid or 'cell[%d]' % index,
                       native_id=cid, parent_id=owner, cell_type=cell['cell_type'], raw_metadata=cell)
        r.expression(path, loc + '["source"]', (language if _text(language) else 'unknown') if cell['cell_type'] == 'code' else cell['cell_type'],
                     text, oid, interpretation='preserved_unexecuted', original_fragments=source)


def _pipeline(r, owner):
    path = 'pipeline-content.json'
    if path not in r.files:
        _gap(r, '.platform', 'missing_required_part', 'DataPipeline requires pipeline-content.json.')
        return
    value = _json(r, path)
    properties = value.get('properties') if isinstance(value, dict) else None
    if not isinstance(properties, dict) or not isinstance(properties.get('activities', []), list):
        _gap(r, path, 'malformed_pipeline', 'Expected native properties with an optional activities array.')
        return
    r.cover(path, 'partial', 'Top-level activity and dependency declarations only.')
    _gap(r, path, 'pipeline_behavior_unresolved', 'Nested activities, connections, scripts, datasets, retries and runtime effects require native review; no data lineage is inferred.')
    entries, names = [], {}
    for index, activity in enumerate(properties.get('activities', [])):
        loc = '$["properties"]["activities"][%d]' % index
        if not isinstance(activity, dict) or not _text(activity.get('name')) or not _text(activity.get('type')) or not isinstance(activity.get('typeProperties'), dict):
            _gap(r, path, 'malformed_activity', 'Activity requires name, type and typeProperties object.', loc)
            continue
        oid = r.object(path, loc, 'fabric_pipeline_activity', activity['name'], parent_id=owner,
                       activity_type=activity['type'], raw_metadata=activity)
        names.setdefault(activity['name'], []).append(oid)
        entries.append((loc, activity, oid))
        _dynamic(r, path, activity, oid, loc)
        if activity['type'] == 'TridentNotebook':
            props = activity['typeProperties']
            notebook, workspace = props.get('notebookId'), props.get('workspaceId')
            if all(isinstance(x, str) and _GUID.fullmatch(x) for x in (notebook, workspace)):
                r.dependency(path, loc + '["typeProperties"]', oid, notebook,
                             kind='notebook_item_reference', workspace_id=workspace,
                             resolution='unresolved', identity_kind='service_item_id')
            else:
                _gap(r, path, 'unresolved_item_reference', 'Notebook/workspace ID is missing, malformed or dynamic; Git logicalId cannot substitute.', loc)
    for loc, activity, oid in entries:
        if len(names[activity['name']]) > 1:
            _gap(r, path, 'duplicate_activity_identity', 'Repeated top-level activity name prevents unique binding.', loc)
        deps = activity.get('dependsOn', [])
        if not isinstance(deps, list):
            _gap(r, path, 'malformed_activity_dependency', 'dependsOn must be an array.', loc)
            continue
        for index, dep in enumerate(deps):
            at = loc + '["dependsOn"][%d]' % index
            if not isinstance(dep, dict) or not _text(dep.get('activity')) or not isinstance(dep.get('dependencyConditions'), list) or not all(c in ('Succeeded', 'Failed', 'Skipped', 'Completed') for c in dep['dependencyConditions']):
                _gap(r, path, 'malformed_activity_dependency', 'Dependency requires an activity name and supported conditions.', at)
                continue
            targets = names.get(dep['activity'], [])
            r.dependency(path, at, oid, dep['activity'], kind='activity_control_dependency',
                         resolution='bound_in_supplied_item' if len(targets) == 1 else 'unresolved',
                         target_object_id=targets[0] if len(targets) == 1 else None,
                         raw_metadata=dep)
            if len(targets) != 1:
                _gap(r, path, 'unresolved_activity_dependency', 'Missing or ambiguous activity name.', at)


def _lakehouse(r, owner):
    path = 'lakehouse.metadata.json'
    if path not in r.files:
        _gap(r, '.platform', 'missing_required_part', 'LakehouseDefinitionV1 requires lakehouse.metadata.json.')
    else:
        value = _json(r, path)
        if not isinstance(value, dict) or ('defaultSchema' in value and not _text(value['defaultSchema'])):
            _gap(r, path, 'malformed_lakehouse', 'Lakehouse metadata must be an object with optional string defaultSchema.')
        else:
            r.object(path, '$', 'fabric_lakehouse_metadata', path, parent_id=owner, raw_metadata=value)
            r.cover(path)
            if set(value) - {'defaultSchema'}:
                _gap(r, path, 'unknown_lakehouse_fields', 'Additional lakehouse fields are preserved without interpretation.')
    for path in ('shortcuts.metadata.json', 'data-access-roles.json', 'alm.settings.json'):
        if path not in r.files:
            continue
        value = _json(r, path)
        r.cover(path, 'partial', 'Native declarations only; no external resource reads or security enforcement validation.')
        if path == 'alm.settings.json':
            if not isinstance(value, dict) or value.get('version') != '1.0.1' or not isinstance(value.get('objectTypes'), list):
                _gap(r, path, 'unsupported_alm_settings', 'Only native ALM settings version 1.0.1 with objectTypes is recognized.')
            else:
                r.object(path, '$', 'fabric_alm_settings', path, parent_id=owner, raw_metadata=value)
            _gap(r, path, 'alm_behavior_unverified', 'ALM settings do not establish actual Git/deployment inclusion or effective access.')
            continue
        if not isinstance(value, list):
            _gap(r, path, 'malformed_lakehouse_collection', 'Expected a native array of declarations.')
            continue
        for index, row in enumerate(value):
            loc = '$[%d]' % index
            if not isinstance(row, dict) or not _text(row.get('name')):
                _gap(r, path, 'malformed_lakehouse_declaration', 'Declaration requires a name.', loc)
                continue
            if path == 'data-access-roles.json':
                if row.get('id') is not None and not _text(row['id']):
                    _gap(r, path, 'malformed_lakehouse_declaration', 'Role ID must be text when present.', loc)
                    continue
                r.object(path, loc, 'fabric_data_access_role', row['name'], native_id=row.get('id'),
                         parent_id=owner, raw_metadata=row, enforcement='not_verified')
                _gap(r, path, 'effective_security_unverified', 'Role inclusion depends on ALM settings; Entra membership is omitted/unsupported by this definition API. Rules do not prove access enforcement.', loc)
            else:
                if not _text(row.get('path')) or not isinstance(row.get('target'), dict):
                    _gap(r, path, 'malformed_shortcut', 'Shortcut requires a path and target object.', loc)
                    continue
                oid = r.object(path, loc, 'fabric_shortcut', row['name'], parent_id=owner, raw_metadata=row)
                target = row['target']
                one = target.get('oneLake')
                if target.get('type') == 'OneLake' and isinstance(one, dict) and all(isinstance(one.get(k), str) and _GUID.fullmatch(one[k]) for k in ('itemId', 'workspaceId')) and _text(one.get('path')):
                    r.dependency(path, loc + '["target"]["oneLake"]', oid, one['itemId'],
                                 kind='shortcut_target', resolution='unresolved', workspace_id=one['workspaceId'],
                                 target_path=one['path'], identity_kind='service_item_id')
                _gap(r, path, 'shortcut_target_unresolved', 'Shortcut target remains external/unresolved, including empty-GUID substitutions; no URL/path is fetched or read.', loc)


def _remap_details(value, ids):
    # Native metadata/code is authoritative: rewrite only contract link fields.
    result = copy.deepcopy(value)
    for key in ('parent_id', 'target_object_id', 'original_expression_id'):
        if isinstance(result.get(key), str):
            result[key] = ids.get(result[key], result[key])
    return result


def _merge(report, child, bindings):
    """Import a report without synthetic source_files or unbound derived hashes."""
    def evidence(old):
        original, prefix, provenance = bindings[old['path']]
        loc = prefix + old['locator']
        return report.evidence(original, loc), provenance
    ids = {}
    for category in ('objects', 'expressions'):
        for row in child[category]:
            ev, _ = evidence(row['evidence'])
            key = (row.get('native_id') if row.get('native_id') is not None else row['name']) if category == 'objects' else row['text']
            ids[row['id']] = report._id('object' if category == 'objects' else 'expression', ev['path'], ev['locator'], key)
    for category in ('objects', 'expressions', 'dependencies', 'gaps'):
        for row in child[category]:
            new = copy.deepcopy(row)
            new['evidence'], provenance = evidence(row['evidence'])
            for field in ('id', 'object_id', 'source_id'):
                if new.get(field) in ids:
                    new[field] = ids[new[field]]
            if category == 'dependencies' and new.get('target') in ids:
                new['target'] = ids[new['target']]
            if 'details' in new:
                new['details'] = _remap_details(new['details'], ids)
                if provenance:
                    new['details']['decoded_provenance'] = provenance
            if category == 'gaps' and provenance:
                new['decoded_provenance'] = provenance
            getattr(report, category).append(new)
            if category == 'objects':
                report._ids.add(new['id'])
    for source in child['source_files']:
        original, _, _ = bindings[source['path']]
        prior = report.coverage.get(original, {}).get('status', 'parsed')
        # One encoded response may carry several parts: any unsupported part
        # makes that source partial, not an apparently unsupported whole item.
        status = source['status']
        if len([b for b in bindings.values() if b[0] == original]) > 1 and status == 'unsupported':
            status = 'partial'
        if prior == 'partial' or status == 'partial':
            status = 'partial'
        report.cover(original, status, 'Bounded native item inventory; inspect per-part gaps and provenance.')


def _semantic(r, owner, format_name):
    tmdl = {p: s for p, s in r.files.items() if p.startswith('definition/') and p.endswith('.tmdl')}
    bim = {'model.bim': r.files['model.bim']} if 'model.bim' in r.files else {}
    if bool(tmdl) == bool(bim) or (format_name == 'TMDL' and not tmdl) or (format_name == 'TMSL' and not bim):
        _gap(r, '.platform', 'missing_or_conflicting_semantic_format', 'Exactly one TMDL definition or TMSL model.bim is required, matching explicit format.')
        return
    if 'definition.pbism' not in r.files:
        _gap(r, '.platform', 'missing_required_part', 'SemanticModel definition.pbism is missing.')
        return
    settings = _json(r, 'definition.pbism')
    if not isinstance(settings, dict) or settings.get('version') not in ('1.0', '4.0', '5.0'):
        _gap(r, 'definition.pbism', 'unsupported_semantic_version', 'Only definition.pbism versions 1.0, 4.0 and 5.0 are recognized.')
        return
    if settings['version'] == '1.0' and tmdl:
        _gap(r, 'definition.pbism', 'semantic_version_format_mismatch', 'definition.pbism 1.0 permits TMSL only; TMDL remains unparsed.')
        return
    r.cover('definition.pbism', 'partial', 'Settings preserved; full native settings validation is not performed.')
    _gap(r, 'definition.pbism', 'semantic_settings_unverified', 'Native settings/defaults, TOM validity and effective access require separate validation.')
    try:
        from .powerbi import parse as parse_powerbi
        selected = dict(tmdl, **bim)
        child = parse_powerbi(selected)
    except ImportError:
        _gap(r, '.platform', 'parser_dependency_missing', 'Power BI parser dependency is unavailable; semantic parts are retained without interpretation.')
        return
    _merge(r, child, {p: (p, '', None) for p in selected})
    for obj in r.objects:
        if obj['kind'] != 'fabric_item' and 'parent_id' in obj['details'] and obj['details']['parent_id'] is None:
            obj['details']['parent_id'] = owner


def _item(files, format_name=None):
    r = Report('fabric', files)
    owner, kind = _platform(r)
    for path, raw in files.items():
        r.object(path, '$raw', 'fabric_definition_part', path, parent_id=owner, raw_text=raw,
                 part_sha256=sha(raw), interpretation='original_text')
    if owner is None:
        return r.finish()
    if any(p in files for p in ('item.metadata.json', 'item.config.json')):
        _gap(r, '.platform', 'conflicting_system_files', 'Native v1 system files and .platform cannot coexist; item bodies remain unparsed.')
        return r.finish()
    if kind not in _TYPES:
        return r.finish()
    if (format_name is not None and not isinstance(format_name, str)) or format_name not in _FORMATS[kind]:
        _gap(r, '.platform', 'unsupported_definition_format', 'Unsupported explicit definition format for this item type.')
        return r.finish()
    if kind == 'Notebook':
        _notebook(r, owner, format_name)
    elif kind == 'DataPipeline':
        _pipeline(r, owner)
    elif kind == 'Lakehouse':
        _lakehouse(r, owner)
    elif kind == 'SemanticModel':
        _semantic(r, owner, format_name)
    for path in files:
        if path not in r.coverage:
            _gap(r, path, 'unsupported_item_part', 'This item part is retained but has no supported body parser.')
    return r.finish()


def _decode(report, path, value, budget):
    definition = value.get('definition')
    if set(value) != {'definition'} or not isinstance(definition, dict) or set(definition) - {'parts', 'format'} or not isinstance(definition.get('parts'), list):
        _gap(report, path, 'unsupported_definition_envelope', 'Expected the native getDefinition response containing only definition.parts and optional definition.format.')
        return
    parts, bindings = {}, {}
    # Reject an entire ambiguous/unsafe part bundle before interpreting any part.
    try:
        if not definition['parts'] or len(definition['parts']) > MAX_FILES or budget[0] + len(definition['parts']) > MAX_FILES:
            raise ValueError('fabric.decoded_file_limit')
        total = 0
        for index, part in enumerate(definition['parts']):
            if not isinstance(part, dict) or set(part) != {'path', 'payload', 'payloadType'} or part.get('payloadType') != 'InlineBase64' or not isinstance(part.get('path'), str) or not isinstance(part.get('payload'), str):
                raise ValueError('fabric.unsupported_part_encoding')
            native_path = part['path']
            validate_files({native_path: ''})
            if native_path in parts:
                raise ValueError('fabric.duplicate_part_path')
            payload = part['payload']
            if len(payload) > ((MAX_FILE_BYTES + 2) // 3) * 4:
                raise ValueError('fabric.decoded_byte_limit')
            raw = base64.b64decode(payload, validate=True)
            if base64.b64encode(raw).decode('ascii') != payload:
                raise ValueError('fabric.noncanonical_base64')
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError('fabric.decoded_byte_limit')
            total += len(raw)
            if budget[1] + total > MAX_TOTAL_BYTES:
                raise ValueError('fabric.decoded_byte_limit')
            text = raw.decode('utf-8')
            parts[native_path] = text
            prefix = '$["definition"]["parts"][%d]["payload"]::decoded:' % index
            bindings[native_path] = (path, prefix, {'parent_path': path, 'parent_sha256': sha(report.files[path]),
                'part_index': index, 'part_path': native_path, 'decoded_sha256': sha(text), 'payload_type': 'InlineBase64'})
        validate_files(parts)
    except (ValueError, UnicodeError, binascii.Error) as error:
        report.cover(path, 'unsupported', 'Unsafe, malformed, unsupported or unbounded part bundle.')
        _gap(report, path, 'invalid_definition_parts', str(error))
        return
    budget[0] += len(parts)
    budget[1] += total
    report.cover(path)
    _merge(report, _item(parts, definition.get('format')), bindings)


def parse(files):
    report = Report('fabric', files)
    claimed, groups = set(), {}
    platforms = [p for p in sorted(files) if PurePosixPath(p).name == '.platform']
    for path in platforms:
        root = str(PurePosixPath(path).parent)
        groups[root] = {}
    # Nearest explicit .platform owns its descendants; never infer from suffix.
    for path in sorted(files):
        roots = [root for root in groups if root == '.' or path.startswith(root + '/')]
        if roots:
            root = max(roots, key=lambda root: 0 if root == '.' else len(PurePosixPath(root).parts))
            local = path if root == '.' else path[len(root) + 1:]
            groups[root][local] = files[path]
            claimed.add(path)
    for root, parts in groups.items():
        if not parts:
            continue
        _merge(report, _item(parts), {p: (p if root == '.' else root + '/' + p, '', None) for p in parts})
    budget = [0, 0]
    for path in sorted(files):
        if path in claimed:
            continue
        report.object(path, '$raw', 'fabric_source_snapshot', path, raw_text=files[path], interpretation='original_text')
        if PurePosixPath(path).name in ('item.metadata.json', 'item.config.json'):
            _gap(report, path, 'unsupported_legacy_system_files', 'Version 1 Git metadata is retained; supply native .platform v2 for item interpretation.')
        elif path.lower().endswith('.json'):
            value = _json(report, path)
            if isinstance(value, dict) and 'definition' in value:
                _decode(report, path, value, budget)
            elif value is not None:
                _gap(report, path, 'unsupported_json_contract', 'Not a native getDefinition response; item lists, LRO states and arbitrary definitions do not establish an item body.')
        else:
            _gap(report, path, 'missing_item_identity', 'Source has no native .platform item identity; it remains unparsed.')
    # Logical IDs identify source-control items, and may legitimately repeat
    # across independent branches/workspaces; retain ambiguity without binding.
    seen = {}
    for item in report.objects:
        if item['kind'] != 'fabric_item':
            continue
        seen.setdefault(item['native_id'].casefold(), []).append(item)
    for items in seen.values():
        if len(items) > 1:
            for item in items:
                ev = item['evidence']
                _gap(report, ev['path'], 'repeated_logical_identity', 'Repeated logicalId is retained as separate snapshots; branch/workspace correspondence is unverified.', ev['locator'])
    return report.finish()
