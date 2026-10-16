"""Bounded Coalesce Git evidence; never render templates or invoke coa/API/SQL."""
import json
import re
from pathlib import PurePosixPath

from .base import Report, read_yaml

CAPABILITY = {
    'formats': ['Coalesce Git Node/NodeType/Environment/Macro YAML fileVersion 1',
                'data.yml fileVersion 3 and locations.yml fileVersion 1',
                'SQL Nodes and SQL/Jinja templates (preservation only)'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'Git YAML is not the REST or hydrated-metadata contract; API JSON is not interpreted.',
        'No Coalesce CLI/API calls, SQL execution, Jinja rendering or template installation.',
        'SQL Nodes, custom config, tests, macros, overrides and runtime behavior remain unqualified.',
        'Storage mappings are environment declarations, not authenticated physical bindings.',
        'Declared security, native IDs and supplied file coverage do not prove effective access or completeness.',
    ],
}

_CONTAINERS = {'Node': 'nodes', 'NodeType': 'nodeTypes', 'Environment': 'environments', 'Macro': 'macros'}
_SQL_KEYS = {'transform', 'customSQL', 'joinCondition', 'cteString', 'preSQL', 'postSQL',
             'templateString', 'script', 'createSQL', 'runSQL', 'macroString', 'nodeMetadataSpec'}
_SECURITY_KEYS = {'grants', 'grant', 'cpygrants', 'copygrants', 'role', 'roles', 'masking',
                  'maskingpolicy', 'rowaccesspolicy', 'rowlevelsecurity', 'accesscontrol',
                  'permissions', 'security', 'policytags'}
_SECURITY_SQL = re.compile(r'\b(GRANT|REVOKE|MASKING\s+POLICY|ROW\s+ACCESS\s+POLICY)\b', re.I)
_OP_KEYS = {'config', 'database', 'dataset', 'deployEnabled', 'description', 'isMultisource',
            'locationName', 'materializationType', 'metadata', 'name', 'overrideSQL', 'schema',
            'sqlType', 'table', 'type', 'version', 'override'}
_COLUMN_KEYS = {'acceptedValues', 'appliedColumnTests', 'columnReference', 'config', 'dataType',
                'defaultValue', 'description', 'name', 'nullable', 'primaryKey', 'uniqueKey',
                'sourceColumnReferences', 'transform', 'hashDetails', 'hashedColumns',
                'isBusinessKey', 'isChangeTracking', 'isSurrogateKey', 'keyColumnType',
                'systemColumnType', 'isSystemCreateDate', 'isSystemUpdateDate',
                'isSystemStartDate', 'isSystemEndDate', 'isSystemVersion', 'isSystemCurrentFlag'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _loc(parent, key):
    return parent + '[' + json.dumps(str(key), ensure_ascii=True) + ']'


class _Parser:
    def __init__(self, files):
        self.r = Report('coalesce', files)
        self.index, self.pending = {}, []
        self.declaration_owners = {}

    def gap(self, path, code, message, loc='$'):
        self.r.gap(path, 'coalesce.' + code, message, loc)

    def unknown(self, path, value, known, loc):
        if set(value) - known:
            self.gap(path, 'unknown_fields', 'Unrecognized fields are retained without assigning native behavior.', loc)

    def scope(self, path, kind):
        parts = PurePosixPath(path).parts
        positions = [i for i, part in enumerate(parts[:-1]) if part == _CONTAINERS[kind]]
        if len(positions) != 1:
            self.gap(path, 'project_scope_unresolved', 'A unique native Git container is required for cross-file binding.')
            return None
        return '/'.join(parts[:positions[0]]) or '.'

    def register(self, path, loc, key, oid):
        entries = self.index.setdefault(key, [])
        entries.append((path, loc, oid))
        if len(entries) > 1:
            for old_path, old_loc, _ in entries:
                self.gap(old_path, 'duplicate_native_identity', 'Repeated native identity in one project makes binding ambiguous.', old_loc)

    def reference(self, path, loc, oid, target, key, kind, **details):
        self.pending.append((path, loc, oid, target, key, kind, details))

    def declarations(self, path, loc, value, owner):
        """Preserve exact decoded strings; whole-file evidence retains YAML spelling."""
        owner = self.declaration_owners.get((path, loc), owner)
        if isinstance(value, dict):
            for key, item in value.items():
                child = _loc(loc, key)
                if re.sub(r'[_\-\s]', '', key).lower() in _SECURITY_KEYS:
                    self.r.object(path, child, 'coalesce_security_declaration', key,
                                  parent_id=owner, declaration=item, enforcement='not_verified')
                    self.gap(path, 'effective_security_unverified', 'Security-related declarations require independent effective-access evidence.', child)
                if key in _SQL_KEYS and isinstance(item, str):
                    self.r.expression(path, child, 'coalesce:yaml-definition' if key == 'nodeMetadataSpec' else 'coalesce:sql+jinja',
                                      item, owner, interpretation='preserved_unexecuted')
                    if any(marker in item for marker in ('{{', '{%', '{#')):
                        self.gap(path, 'template_context_unresolved', 'Template text is unrendered; no ref/macro dependency is inferred from text.', child)
                    if _SECURITY_SQL.search(item):
                        self.gap(path, 'security_sql_unverified', 'Security-related SQL text is retained; textual detection is a review hint, not access validation.', child)
                elif key in _SQL_KEYS and not isinstance(item, dict):
                    self.gap(path, 'invalid_expression', 'Native expression fields must be strings, or documented nested objects.', child)
                self.declarations(path, child, item, owner)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                self.declarations(path, loc + '[%d]' % i, item, owner)

    def columns(self, path, metadata, owner, node_id, scope, mapping_count):
        rows = metadata.get('columns')
        if not isinstance(rows, list):
            self.gap(path, 'invalid_columns', 'Node metadata.columns must be an array.', '$.operation.metadata.columns')
            return
        for i, row in enumerate(rows):
            loc = '$.operation.metadata.columns[%d]' % i
            if not isinstance(row, dict) or not _text(row.get('name')):
                self.gap(path, 'invalid_column', 'Column metadata requires an explicit name.', loc)
                continue
            ref = row.get('columnReference')
            valid_ref = (isinstance(ref, dict) and _text(ref.get('columnCounter')) and
                         _text(ref.get('stepCounter')) and ref['stepCounter'] == node_id)
            column_id = ref.get('columnCounter') if isinstance(ref, dict) and _text(ref.get('columnCounter')) else None
            cid = self.r.object(path, loc, 'coalesce_column', row['name'], native_id=column_id,
                                parent_id=owner, node_id=node_id, raw_metadata=row,
                                identity_binding='declared' if valid_ref else 'unresolved',
                                physical_presence='not_verified')
            self.declaration_owners[(path, '$["operation"]["metadata"]["columns"][%d]' % i)] = cid
            if valid_ref and scope is not None:
                self.register(path, loc, (scope, 'column', node_id, column_id), cid)
            elif not valid_ref:
                self.gap(path, 'invalid_column_identity', 'Column counter and matching owning stepCounter are required; no identity is invented.', loc)
            if not _text(row.get('dataType')) or type(row.get('nullable')) is not bool:
                self.gap(path, 'invalid_column_shape', 'Expected a native dataType string and boolean nullable declaration.', loc)
            self.unknown(path, row, _COLUMN_KEYS, loc)
            if row.get('hashDetails') or row.get('hashedColumns'):
                self.gap(path, 'hash_lineage_unmodeled', 'Hash configuration is retained; its additional column inputs and native hashing semantics are not resolved.', loc)
            sources = row.get('sourceColumnReferences', [])
            if not isinstance(sources, list):
                self.gap(path, 'invalid_column_sources', 'sourceColumnReferences must be an array.', loc)
                continue
            if mapping_count and len(sources) != mapping_count:
                self.gap(path, 'mapping_alignment_unresolved', 'Column source-array count differs from sourceMapping count; no source position is repaired.', loc)
            for si, source in enumerate(sources):
                sloc = loc + '.sourceColumnReferences[%d]' % si
                refs = source.get('columnReferences') if isinstance(source, dict) else None
                if not isinstance(refs, list):
                    self.gap(path, 'invalid_column_sources', 'Each source requires a columnReferences array.', sloc)
                    continue
                self.unknown(path, source, {'columnReferences', 'transform'}, sloc)
                for ri, upstream in enumerate(refs):
                    rloc = sloc + '.columnReferences[%d]' % ri
                    if (not isinstance(upstream, dict) or not _text(upstream.get('stepCounter')) or
                            not _text(upstream.get('columnCounter'))):
                        self.gap(path, 'invalid_column_dependency', 'Upstream references need exact stepCounter and columnCounter strings.', rloc)
                        continue
                    nid, col = upstream['stepCounter'], upstream['columnCounter']
                    self.reference(path, rloc, cid, col, (scope, 'column', nid, col), 'column_reference',
                                   node_id=nid, column_id=col, source_mapping_index=si, raw_reference=upstream)

    def mappings(self, path, rows, owner, scope):
        if not isinstance(rows, list):
            self.gap(path, 'invalid_source_mapping', 'sourceMapping must be an array.', '$.operation.metadata.sourceMapping')
            return
        for i, row in enumerate(rows):
            loc = '$.operation.metadata.sourceMapping[%d]' % i
            if not isinstance(row, dict):
                self.gap(path, 'invalid_source_mapping', 'Each source mapping must be an object.', loc)
                continue
            has_name = _text(row.get('name'))
            mid = self.r.object(path, loc, 'coalesce_source_mapping',
                                row['name'] if has_name else 'Unbound source mapping [%d]' % i,
                                parent_id=owner, source_mapping_index=i, raw_metadata=row,
                                native_name=row.get('name'), name_binding='declared' if has_name else 'unresolved')
            self.declaration_owners[(path, '$["operation"]["metadata"]["sourceMapping"][%d]' % i)] = mid
            if not has_name:
                self.gap(path, 'invalid_mapping_name', 'Mapping name must be a non-empty string; the display label is unbound and the original value is retained.', loc)
            self.unknown(path, row, {'aliases', 'customSQL', 'dependencies', 'join', 'name', 'noLinkRefs'}, loc)
            aliases = row.get('aliases', {})
            if not isinstance(aliases, dict):
                self.gap(path, 'invalid_aliases', 'aliases must map native alias strings to node IDs.', loc)
            else:
                for alias, node_id in aliases.items():
                    if not _text(node_id):
                        self.gap(path, 'invalid_aliases', 'Alias target must be a native node ID string.', _loc(loc + '.aliases', alias))
                        continue
                    self.reference(path, _loc(loc + '.aliases', alias), mid, node_id,
                                   (scope, 'node', node_id), 'mapping_alias', alias=alias)
            for field in ('dependencies', 'noLinkRefs'):
                dependencies = row.get(field, [])
                if not isinstance(dependencies, list):
                    self.gap(path, 'invalid_mapping_dependencies', 'Mapping dependencies and noLinkRefs must be arrays.', _loc(loc, field))
                    continue
                for di, dep in enumerate(dependencies):
                    dloc = _loc(loc, field) + '[%d]' % di
                    if not isinstance(dep, dict) or not all(_text(dep.get(k)) for k in ('locationName', 'nodeName')):
                        self.gap(path, 'invalid_mapping_dependency', 'Both locationName and nodeName are required; names are not guessed.', dloc)
                        continue
                    location, name = dep['locationName'], dep['nodeName']
                    self.reference(path, dloc, mid, json.dumps([location, name], ensure_ascii=True),
                                   (scope, 'named_node', location, name), 'declared_dependency' if field == 'dependencies' else 'no_link_reference',
                                   location_name=location, node_name=name, raw_reference=dep)
                    if field == 'noLinkRefs':
                        self.gap(path, 'no_link_runtime_unverified', 'noLinkRefs is retained separately; it does not establish execution ordering.', dloc)

    def node(self, path, value, scope):
        op = value.get('operation')
        if not isinstance(op, dict) or type(op.get('version')) is not int or op['version'] != 1:
            self.gap(path, 'unsupported_operation_version', 'Only operation.version 1 mappings are interpreted.')
            return
        self.unknown(path, value, {'fileVersion', 'id', 'name', 'operation', 'type'}, '$')
        self.unknown(path, op, _OP_KEYS, '$.operation')
        owner = self.r.object(path, '$', 'coalesce_node', value['name'], native_id=value['id'],
                              project_scope=scope, raw_metadata=value, node_type=op.get('sqlType'),
                              storage_location=op.get('locationName'), physical_binding='not_verified')
        if scope is not None:
            self.register(path, '$', (scope, 'node', value['id']), owner)
            if _text(op.get('locationName')) and op.get('name') == value['name']:
                self.register(path, '$', (scope, 'named_node', op['locationName'], value['name']), owner)
        if op.get('name') != value['name']:
            self.gap(path, 'node_name_mismatch', 'Top-level name and operation.name must agree; both values are preserved.')
        if not _text(op.get('locationName')):
            self.gap(path, 'storage_location_unresolved', 'Native storage location is absent or malformed.')
        if _text(op.get('sqlType')):
            self.reference(path, '$.operation.sqlType', owner, op['sqlType'],
                           (scope, 'node_type', op['sqlType']), 'node_type_reference')
        else:
            self.gap(path, 'node_type_unresolved', 'Native sqlType is missing or malformed.')
        metadata = op.get('metadata')
        if not isinstance(metadata, dict):
            self.gap(path, 'invalid_metadata', 'Node operation.metadata must be an object.')
        else:
            self.unknown(path, metadata, {'columns', 'sourceMapping', 'join', 'cteString', 'appliedNodeTests', 'enabledColumnTestIDs'}, '$.operation.metadata')
            mappings = metadata.get('sourceMapping', [])
            self.columns(path, metadata, owner, value['id'], scope, len(mappings) if isinstance(mappings, list) else 0)
            self.mappings(path, mappings, owner, scope)
        self.declarations(path, '$', value, owner)
        self.gap(path, 'runtime_unverified', 'Node types, config, materialization, keys, tests, overrides and history behavior require native validation.')
        self.gap(path, 'physical_mapping_unverified', 'Environment mappings and warehouse catalogue must separately establish the actual physical destination.')
        self.r.cover(path, 'parsed')

    def metadata(self, path, value, kind, scope):
        owner = self.r.object(path, '$', 'coalesce_' + {'NodeType': 'node_type', 'Environment': 'environment', 'Macro': 'macro'}[kind],
                              value['name'], native_id=value['id'], project_scope=scope, raw_metadata=value)
        self.declarations(path, '$', value, owner)
        if kind == 'NodeType':
            if scope is not None:
                self.register(path, '$', (scope, 'node_type', value['id']), owner)
            self.gap(path, 'node_type_behavior_unverified', 'Node definition and create/run templates are retained; defaults, annotations and custom type semantics are not evaluated.')
        elif kind == 'Environment':
            mappings = value.get('mappingDefinitions')
            if not isinstance(mappings, dict):
                self.gap(path, 'invalid_storage_mapping', 'Environment mappingDefinitions must map locations to database/schema declarations.')
            else:
                for i, (location, mapping) in enumerate(mappings.items()):
                    loc = _loc('$.mappingDefinitions', location)
                    has_location = _text(location)
                    self.r.object(path, loc, 'coalesce_storage_mapping',
                                  location if has_location else 'Unbound storage mapping [%d]' % i, parent_id=owner,
                                  environment_id=value['id'], raw_metadata=mapping, physical_binding='not_verified',
                                  native_location=location, name_binding='declared' if has_location else 'unresolved')
                    if not has_location:
                        self.gap(path, 'invalid_storage_location_name', 'Storage location must be a non-empty string; the display label is unbound and the original key is retained.', loc)
                    if not isinstance(mapping, dict) or not all(_text(mapping.get(k)) for k in ('database', 'schema')):
                        self.gap(path, 'invalid_storage_mapping', 'Storage mapping requires explicit non-empty database and schema strings.', loc)
                    elif set(mapping) - {'database', 'schema'}:
                        self.gap(path, 'unknown_mapping_fields', 'Additional mapping options are preserved without interpretation.', loc)
            self.gap(path, 'environment_security_unverified', 'Mapping declarations do not establish credentials, active environment, effective role, policies or access.')
        else:
            self.gap(path, 'macro_behavior_unverified', 'Macro bodies are retained without importing, rendering or inferring their dependencies.')
        self.r.cover(path, 'parsed')

    def yaml(self, path, value):
        if not isinstance(value, dict):
            self.gap(path, 'unsupported_yaml_shape', 'Expected a native versioned Coalesce Git mapping.')
            return
        name = PurePosixPath(path).name
        if name in ('data.yml', 'locations.yml'):
            expected = 3 if name == 'data.yml' else 1
            if type(value.get('fileVersion')) is not int or value['fileVersion'] != expected:
                self.gap(path, 'unsupported_file_version', 'Supported versions are data.yml 3 and locations.yml 1.')
                return
            known = {'fileVersion', 'defaultStorageMapping'} | ({'locations'} if name == 'locations.yml' else set())
            owner = self.r.object(path, '$', 'coalesce_project_configuration', name,
                                  project_scope=str(PurePosixPath(path).parent), raw_metadata=value)
            self.unknown(path, value, known, '$')
            self.declarations(path, '$', value, owner)
            if name == 'locations.yml':
                locations = value.get('locations')
                if not isinstance(locations, list) or not all(_text(v) for v in locations):
                    self.gap(path, 'invalid_locations', 'locations.yml requires an array of location-name strings.')
                else:
                    for i, location in enumerate(locations):
                        self.r.object(path, '$.locations[%d]' % i, 'coalesce_storage_location', location, parent_id=owner)
            self.gap(path, 'project_context_unverified', 'Git metadata does not establish project/workspace identity, repository revision, connection or active environment.')
            self.r.cover(path, 'parsed')
            return
        kind = value.get('type')
        if not isinstance(kind, str) or kind not in _CONTAINERS:
            self.gap(path, 'unsupported_git_object', 'Only Node, NodeType, Environment and Macro Git objects are interpreted; other assets remain source evidence.')
            return
        if type(value.get('fileVersion')) is not int or value['fileVersion'] != 1:
            self.gap(path, 'unsupported_file_version', 'Only integer fileVersion 1 is interpreted for this Git object.')
            return
        if not _text(value.get('id')) or not _text(value.get('name')):
            self.gap(path, 'invalid_native_identity', 'Native id and name strings are required; filenames never supply identity.')
            return
        scope = self.scope(path, kind)
        if kind == 'Node':
            self.node(path, value, scope)
        else:
            self.metadata(path, value, kind, scope)

    def run(self):
        for path, text in sorted(self.r.files.items()):
            self.r.cover(path, 'unsupported')
            suffix = PurePosixPath(path).suffix.lower()
            if suffix in ('.yaml', '.yml'):
                self.r.expression(path, '$raw', 'yaml', text, interpretation='original_file')
                try:
                    self.yaml(path, read_yaml(text))
                except ImportError:
                    self.gap(path, 'parser_dependency_missing', 'Install the pinned PyYAML dependency; original YAML is preserved.')
                except ValueError as error:
                    self.r.gap(path, str(error), 'Invalid or unsupported YAML; original file is retained.')
            elif suffix in ('.sql', '.j2'):
                self.r.expression(path, '$raw', 'coalesce:sql+jinja', text, interpretation='original_file')
                self.gap(path, 'sql_node_or_template_unmodeled', 'SQL annotations, dialect, ref resolution and template context require a separately qualified contract.')
                if _SECURITY_SQL.search(text):
                    self.gap(path, 'security_sql_unverified', 'Security SQL is retained without access or enforcement claims.')
                self.r.cover(path, 'partial')
            else:
                self.gap(path, 'unsupported_format', 'Supply native Coalesce Git YAML; REST/hydrated JSON and arbitrary export envelopes are outside this slice.')
        for path, loc, owner, target, key, kind, details in self.pending:
            candidates = self.index.get(key, []) if key[0] is not None else []
            self.r.dependency(path, loc, owner, target, kind=kind,
                              resolution='bound_in_supplied_project' if len(candidates) == 1 else 'unresolved',
                              target_object_id=candidates[0][2] if len(candidates) == 1 else None, **details)
            if len(candidates) != 1:
                self.gap(path, 'dependency_unresolved', 'Declared dependency has no unique native target within the supplied project scope.', loc)
        return self.r.finish()


def parse(files: dict[str, str]):
    return _Parser(files).run()
