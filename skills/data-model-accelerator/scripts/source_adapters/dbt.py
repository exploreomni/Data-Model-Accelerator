"""Offline dbt source declarations. Never import dbt or render project Jinja."""
import json
from pathlib import PurePosixPath

from .base import Report, read_json, read_yaml, sha, validate_files
from .sql import parse_sql

SUPPORTED_MANIFEST_SCHEMAS = ('https://schemas.getdbt.com/dbt/manifest/v12.json',)
CAPABILITY = {
    'formats': ['dbt manifest v12 JSON', 'dbt_project.yml config-version 2 (explicit or omitted)',
                'dbt properties .yml version 2 (explicit or omitted)', 'packages/dependencies/package-lock YAML',
                'authored SQL/Jinja and Python (preservation only)', 'seed CSV (hash only)'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'No dbt commands, Jinja rendering, macro/hook execution, package installation or introspection.',
        'Manifest v12 is a bounded structural contract, not full JSON Schema or native validation.',
        'Dependencies come from supplied manifest depends_on IDs, never regex ref inference.',
        'Compiled code is supplied evidence, not authenticated execution or revision parity.',
        'YAML config inheritance, runtime branches, remote packages and effective security remain unresolved.',
    ],
}

_DIALECTS = {'snowflake': 'snowflake', 'bigquery': 'bigquery', 'redshift': 'redshift',
             'postgres': 'postgres', 'duckdb': 'duckdb', 'databricks': 'databricks',
             'spark': 'spark', 'clickhouse': 'clickhouse', 'sqlserver': 'tsql'}
_COLLECTIONS = {'nodes': {'model', 'analysis', 'test', 'snapshot', 'seed', 'operation', 'sql_operation'},
                'sources': {'source'}, 'macros': {'macro'}, 'exposures': {'exposure'},
                'docs': {'doc'}, 'groups': {'group'}, 'metrics': {'metric'},
                'semantic_models': {'semantic_model'}, 'saved_queries': {'saved_query'},
                'unit_tests': {'unit_test'}}
_PROPERTIES = {'models', 'sources', 'seeds', 'snapshots', 'analyses', 'macros', 'exposures',
               'metrics', 'groups', 'semantic_models', 'saved_queries', 'unit_tests'}
_SECURITY = {'access', 'group', 'grants', 'masking_policy', 'row_access_policy',
             'policy_tags', 'row_access_policy_tags'}
_HOOKS = {'pre-hook', 'post-hook', 'pre_hook', 'post_hook', 'on-run-start', 'on-run-end', 'sql_header'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _loc(parent, key):
    return parent + '[' + json.dumps(str(key), ensure_ascii=True) + ']'


def _templated(text):
    return any(marker in text for marker in ('{{', '{%', '{#'))


class _Parser:
    def __init__(self, files):
        self.r = Report('dbt', files)
        self.projects, self.bindings = [], {}

    def gap(self, path, code, message, loc='$'):
        self.r.gap(path, 'dbt.' + code, message, loc)

    def declarations(self, path, loc, value, owner):
        """Retain exact declaration strings without evaluating nested contexts."""
        if isinstance(value, dict):
            for key, item in value.items():
                child = _loc(loc, key)
                plain = key.lstrip('+')
                if plain in _SECURITY:
                    self.gap(path, 'effective_security_unverified',
                             'Access, group and policy/grant declarations do not establish effective warehouse or platform access.', child)
                if plain in _HOOKS:
                    hooks = item if isinstance(item, list) else [item]
                    for index, hook in enumerate(hooks):
                        sql = hook.get('sql') if isinstance(hook, dict) else hook
                        if isinstance(sql, str):
                            self.r.expression(path, child + '[%d]' % index, 'dbt:hook', sql, owner,
                                              interpretation='unexecuted_declaration')
                        else:
                            self.gap(path, 'invalid_hook', 'Hook declaration must contain a string or sql string.', child)
                    self.gap(path, 'hook_behavior_unverified', 'Hooks and SQL headers are retained without execution or inferred dependencies.', child)
                else:
                    self.declarations(path, child, item, owner)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.declarations(path, loc + '[%d]' % index, item, owner)
        elif isinstance(value, str) and _templated(value):
            self.r.expression(path, loc, 'dbt:jinja', value, owner, interpretation='unrendered_declaration')
            self.gap(path, 'jinja_context_unresolved', 'Jinja, variables and environment-dependent declarations remain unrendered.', loc)

    def yaml(self, path, value):
        name = PurePosixPath(path).name
        if not isinstance(value, dict):
            self.gap(path, 'invalid_yaml_shape', 'Expected a dbt YAML mapping.')
            return
        if name == 'dbt_project.yml':
            if (('config-version' in value and (value['config-version'] != 2 or type(value['config-version']) is not int))
                    or not _text(value.get('name'))):
                self.gap(path, 'unsupported_project', 'A non-empty project name and config-version 2 (integer, if supplied) are required.')
                return
            oid = self.r.object(path, '$', 'dbt_project', value['name'], raw_metadata=value)
            self.projects.append((PurePosixPath(path).parent, value['name']))
            self.declarations(path, '$', value, oid)
            self.gap(path, 'config_resolution_unverified', 'Project/path/resource configuration precedence and vars are preserved, not evaluated.')
        elif name in ('packages.yml', 'dependencies.yml', 'package-lock.yml'):
            oid = self.r.object(path, '$', 'dbt_package_configuration', name, raw_metadata=value)
            found = False
            for key in ('packages', 'projects'):
                entries = value.get(key, [])
                if not isinstance(entries, list):
                    self.gap(path, 'invalid_packages', 'Package/project declarations must be arrays.', _loc('$', key))
                    continue
                for index, row in enumerate(entries):
                    loc = _loc('$', key) + '[%d]' % index
                    if not isinstance(row, dict) or not any(_text(row.get(k)) for k in ('package', 'git', 'local', 'tarball', 'name')):
                        self.gap(path, 'invalid_package', 'A package/project declaration needs an explicit native location or name.', loc)
                        continue
                    found = True
                    label = next(row[k] for k in ('package', 'git', 'local', 'tarball', 'name') if _text(row.get(k)))
                    self.r.object(path, loc, 'dbt_package_declaration', label, parent_id=oid, raw_metadata=row)
                    self.gap(path, 'package_resolution_unverified',
                             'Declared local/remote package or cross-project dependency is not fetched, installed or revision-verified.', loc)
            if not found:
                self.gap(path, 'package_scope_unverified', 'No usable package declarations establish the resolved package scope.')
            self.declarations(path, '$', value, oid)
        elif ('version' not in value or (value['version'] == 2 and type(value['version']) is int)) and set(value) & _PROPERTIES:
            oid = self.r.object(path, '$', 'dbt_properties', name, interpreted_version=2,
                                declared_version=value.get('version'))
            for key in sorted(set(value) & _PROPERTIES):
                rows = value[key]
                if not isinstance(rows, list):
                    self.gap(path, 'invalid_properties', 'Property resource groups must be arrays.', _loc('$', key))
                    continue
                for index, row in enumerate(rows):
                    loc = _loc('$', key) + '[%d]' % index
                    if not isinstance(row, dict) or not _text(row.get('name')):
                        self.gap(path, 'invalid_property_resource', 'Property resources require a non-empty name.', loc)
                        continue
                    rid = self.r.object(path, loc, 'dbt_' + key + '_declaration', row['name'],
                                        parent_id=oid, raw_metadata=row, native_identity='not_bound')
                    self.declarations(path, loc, row, rid)
                    if key == 'sources':
                        tables = row.get('tables', [])
                        if not isinstance(tables, list):
                            self.gap(path, 'invalid_source_tables', 'Source tables must be an array.', loc)
                        else:
                            for ti, table in enumerate(tables):
                                tloc = loc + '["tables"][%d]' % ti
                                if not isinstance(table, dict) or not _text(table.get('name')):
                                    self.gap(path, 'invalid_source_table', 'A source table needs a non-empty name.', tloc)
                                    continue
                                self.r.object(path, tloc, 'dbt_source_table_declaration', table['name'],
                                              parent_id=rid, source_name=row['name'], raw_metadata=table)
            unknown = set(value) - _PROPERTIES - {'version'}
            if unknown:
                self.gap(path, 'unsupported_property_keys', 'Unrecognized top-level property keys are retained in exact YAML only.')
            self.gap(path, 'property_binding_unverified',
                     'Properties, tests, versions and contracts are declarations; native IDs and effective config require matching manifest evidence.')
        else:
            self.gap(path, 'unsupported_yaml', 'Only project config-version 2, package configuration and properties version 2 are interpreted; omitted version fields use the current v2 structure.')
            return
        self.r.cover(path, 'parsed')

    def bind(self, path, loc, row, dialect, manifest_owner):
        original = row.get('original_file_path')
        raw = row.get('raw_code')
        if not isinstance(raw, str):
            return
        try:
            validate_files({original: ''})
        except (ValueError, TypeError):
            self.gap(path, 'invalid_original_path', 'Resource original_file_path must be a safe repository-relative path.', loc)
            return
        candidates = {str(root / original) for root, name in self.projects
                      if name == row['package_name'] and str(root / original) in self.r.files}
        if len(candidates) != 1:
            self.gap(path, 'authored_binding_unverified', 'A unique supplied project/package and original file path are required to bind authored bytes.', loc)
            return
        candidate = next(iter(candidates))
        if self.r.files[candidate] != raw:
            self.gap(path, 'authored_code_mismatch', 'Manifest raw_code differs from the supplied original file; no current-source binding is made.', loc)
            return
        checksum = row.get('checksum')
        if isinstance(checksum, dict) and checksum.get('name') == 'sha256' and checksum.get('checksum') != sha(raw):
            self.gap(path, 'checksum_mismatch', 'Declared sha256 checksum differs from exact supplied authored bytes.', loc)
            return
        self.bindings.setdefault(candidate, []).append({'dialect': dialect, 'manifest_path': path,
            'manifest_object_id': manifest_owner, 'native_id': row['unique_id'],
            'binding': 'package_original_path_exact_raw_code', 'sha256': sha(raw)})

    def resource(self, path, loc, key, row, allowed, disabled, metadata):
        if not isinstance(row, dict):
            self.gap(path, 'invalid_resource', 'Manifest resource must be an object.', loc)
            return None
        kind = row.get('resource_type')
        if kind is None and allowed in ({'doc'}, {'group'}):
            kind = next(iter(allowed))
        uid, package = row.get('unique_id'), row.get('package_name')
        if (not _text(uid) or uid != key or not _text(package) or not _text(row.get('name')) or
                not isinstance(kind, str) or kind not in allowed or not uid.startswith(kind + '.' + package + '.') or
                not uid[len(kind + '.' + package + '.'):]):
            self.gap(path, 'invalid_native_identity', 'Resource key, unique_id, type, package namespace and name must agree.', loc)
            return None
        oid = self.r.object(path, loc, 'dbt_' + kind, row['name'], native_id=uid,
                            package_name=package, disabled=disabled, raw_metadata=row,
                            manifest_schema=metadata['dbt_schema_version'], dbt_version=metadata.get('dbt_version'),
                            invocation_id=metadata.get('invocation_id'), generated_at=metadata.get('generated_at'))
        dialect = _DIALECTS.get(metadata.get('adapter_type')) if isinstance(metadata.get('adapter_type'), str) else None
        for field in ('raw_code', 'compiled_code', 'macro_sql', 'block_contents'):
            code = row.get(field)
            if code is None:
                continue
            if not isinstance(code, str):
                self.gap(path, 'invalid_code', 'Native code fields must be strings.', _loc(loc, field))
                continue
            language = 'python' if row.get('language') == 'python' else 'dbt:sql+jinja'
            if field == 'compiled_code':
                language = 'python' if row.get('language') == 'python' else dialect or 'sql:unknown'
            elif field == 'block_contents':
                language = 'markdown'
            self.r.expression(path, _loc(loc, field), language, code, oid,
                interpretation='supplied_' + field, adapter_type=metadata.get('adapter_type'),
                native_id=uid, invocation_id=metadata.get('invocation_id'),
                revision_binding='not_authenticated')
            if field == 'compiled_code':
                self.gap(path, 'compiled_revision_unverified',
                         'Compiled code is retained separately; invocation metadata does not authenticate commit, vars, target, packages or execution.', _loc(loc, field))
                if not dialect and row.get('language') != 'python':
                    self.gap(path, 'dialect_unknown', 'SQL dialect requires a supported manifest metadata.adapter_type.', loc)
        if _templated(row.get('raw_code', '') if isinstance(row.get('raw_code'), str) else ''):
            self.gap(path, 'dynamic_behavior_unverified', 'Manifest dependencies describe the supplied parse context; Jinja branches, dispatch and runtime-generated dependencies are not re-evaluated.', loc)
        if 'config' in row and not isinstance(row['config'], dict):
            self.gap(path, 'invalid_config', 'Manifest resource config must be a mapping.', _loc(loc, 'config'))
        else:
            self.declarations(path, _loc(loc, 'config'), row.get('config', {}), oid)
        for key_name in _SECURITY:
            if key_name in row:
                self.gap(path, 'effective_security_unverified', 'Native access and group declarations are not effective permission evidence.', _loc(loc, key_name))
        if kind in {'model', 'snapshot', 'seed'}:
            self.gap(path, 'materialization_unverified', 'Materialization, incremental/snapshot strategy and constraints are declarations, not executed behavior or observed uniqueness.', loc)
        if kind in {'metric', 'semantic_model', 'saved_query', 'unit_test'}:
            self.gap(path, 'resource_semantics_unmodeled', 'Resource metadata and declared dependencies are retained; its semantic execution is outside this slice.', loc)
        columns = row.get('columns', {})
        if not isinstance(columns, dict):
            self.gap(path, 'invalid_columns', 'Manifest columns must be an object keyed by source column name.', loc)
        else:
            for column, data in columns.items():
                cloc = _loc(_loc(loc, 'columns'), column)
                if not isinstance(data, dict) or not _text(data.get('name')):
                    self.gap(path, 'invalid_column', 'Column metadata needs an explicit name.', cloc)
                    continue
                self.r.object(path, cloc, 'dbt_column_declaration', data['name'],
                              parent_id=oid, raw_metadata=data, physical_presence='not_verified')
                self.declarations(path, cloc, data, oid)
        self.bind(path, loc, row, dialect, oid)
        return oid

    def manifest(self, path, value):
        if not isinstance(value, dict) or not isinstance(value.get('metadata'), dict):
            self.gap(path, 'unsupported_json', 'Expected a native manifest with metadata; run-results/catalog/custom envelopes are not inferred.')
            return
        metadata = value['metadata']
        if metadata.get('dbt_schema_version') not in SUPPORTED_MANIFEST_SCHEMAS:
            self.gap(path, 'unsupported_manifest_version', 'Only the explicitly supported manifest v12 schema URI is interpreted.')
            return
        if not _text(metadata.get('dbt_version')):
            self.gap(path, 'missing_dbt_version', 'Manifest engine dbt_version is required alongside its schema version.')
        self.r.object(path, '$.metadata', 'dbt_manifest', PurePosixPath(path).name,
                      raw_metadata=metadata, graph_maps={k: value[k] for k in ('parent_map', 'child_map', 'group_map', 'selectors') if k in value},
                      provenance='supplied_unverified', schema_validation='bounded_structure_only')
        resources = []
        for collection, allowed in _COLLECTIONS.items():
            rows = value.get(collection, {})
            if collection in ('nodes', 'sources', 'macros') and collection not in value:
                self.gap(path, 'missing_manifest_collection', 'Manifest is missing a core resource collection.', _loc('$', collection))
            if not isinstance(rows, dict):
                self.gap(path, 'invalid_collection', 'Manifest collections must be objects keyed by unique_id.', _loc('$', collection))
                continue
            for key, row in rows.items():
                resources.append((_loc(_loc('$', collection), key), key, row, allowed, False))
        disabled = value.get('disabled', {})
        if not isinstance(disabled, dict):
            self.gap(path, 'invalid_disabled', 'v12 disabled resources must map unique_id to an array of definitions.')
        else:
            for key, rows in disabled.items():
                if not isinstance(rows, list):
                    self.gap(path, 'invalid_disabled', 'Disabled resource definitions must be arrays.', _loc('$.disabled', key))
                    continue
                for index, row in enumerate(rows):
                    resources.append((_loc('$.disabled', key) + '[%d]' % index, key, row,
                                      set().union(*_COLLECTIONS.values()), True))
        entries, identities = [], {}
        for loc, key, row, allowed, off in resources:
            oid = self.resource(path, loc, key, row, allowed, off, metadata)
            if oid:
                entries.append((loc, row, oid, off))
                if not off:
                    identities.setdefault(key, []).append(oid)
                    if len(identities[key]) > 1:
                        self.gap(path, 'duplicate_native_identity', 'Multiple active resource definitions share a native ID; dependency binding is ambiguous.', loc)
        for loc, row, oid, off in entries:
            if 'depends_on' not in row and row.get('resource_type') in {'model', 'analysis', 'test', 'snapshot', 'macro', 'exposure'}:
                self.gap(path, 'missing_dependencies', 'This resource lacks depends_on; absence of dependency evidence is not an empty dependency set.', loc)
            depends = row.get('depends_on', {})
            if not isinstance(depends, dict):
                self.gap(path, 'invalid_dependencies', 'depends_on must be an object of nodes/macros arrays.', loc)
                continue
            for group in ('nodes', 'macros'):
                targets = depends.get(group, [])
                if not isinstance(targets, list) or any(not _text(t) for t in targets):
                    self.gap(path, 'invalid_dependencies', 'Native dependencies must be string-ID arrays.', _loc(loc, 'depends_on'))
                    continue
                for index, target in enumerate(targets):
                    dloc = _loc(_loc(loc, 'depends_on'), group) + '[%d]' % index
                    matching = identities.get(target, [])
                    correct_group = target.startswith('macro.') if group == 'macros' else not target.startswith('macro.')
                    resolved = len(matching) == 1 and not off and correct_group
                    self.r.dependency(path, dloc, oid, target, kind='manifest_' + group,
                                      resolution='supplied_manifest_id' if resolved else 'unresolved',
                                      target_object_id=matching[0] if resolved else None,
                                      source_disabled=off, effective_runtime_dependency='not_verified')
                    if not resolved:
                        self.gap(path, 'dependency_unresolved', 'Referenced native ID is absent, disabled, ambiguous, or the dependent resource is disabled.', dloc)
        unknown = set(value) - set(_COLLECTIONS) - {'metadata', 'disabled', 'parent_map', 'child_map', 'group_map', 'selectors', 'flat_graph'}
        if unknown:
            self.gap(path, 'unsupported_manifest_keys', 'Unrecognized top-level fields are retained in exact JSON only.')
        if not entries:
            self.gap(path, 'empty_manifest_scope', 'No usable resource definitions establish the supplied project scope.')
        self.r.cover(path, 'parsed')

    def code(self, path, text):
        bindings = self.bindings.get(path, [])
        binding = bindings[0] if len(bindings) == 1 else None
        oid = self.r.object(path, '$file', 'dbt_authored_file', PurePosixPath(path).name,
                            manifest_binding=binding, native_identity='not_inferred_from_filename')
        if len(bindings) > 1:
            self.gap(path, 'ambiguous_manifest_binding', 'Multiple supplied manifest definitions bind this file; none is selected as current.')
        if PurePosixPath(path).suffix.lower() == '.py':
            self.r.expression(path, '$code', 'python', text, oid, interpretation='preserved_original')
            self.gap(path, 'python_unexecuted', 'Python model source is retained without importing, execution or dependency inference.')
        elif _templated(text):
            self.r.expression(path, '$code', 'dbt:sql+jinja', text, oid, interpretation='preserved_original')
            self.gap(path, 'jinja_unrendered', 'Authored Jinja is preserved without extracting regex refs or rendering dynamic branches.')
        else:
            parse_sql(self.r, path, text, binding['dialect'] if binding else None, oid, '$code')
        if not binding:
            self.gap(path, 'authored_binding_unverified', 'No unambiguous matching manifest resource binds this file to native IDs, dialect and parse context.')
        self.r.cover(path, 'parsed')


def parse(files):
    parser = _Parser(files)
    # Projects are read before manifests so package/file bindings never depend
    # on lexical file order or an assumed target/ directory location.
    for path, text in sorted(files.items()):
        p = PurePosixPath(path)
        if p.suffix.lower() not in ('.yml', '.yaml'):
            continue
        if p.name in ('profiles.yml', 'profiles.yaml'):
            parser.gap(path, 'profiles_unsupported', 'Credential-bearing profiles are not interpreted; supply manifest adapter_type instead.')
            parser.r.cover(path, 'unsupported')
            continue
        parser.r.expression(path, '$yaml', 'yaml', text, interpretation='preserved_original')
        if p.suffix.lower() == '.yaml':
            parser.gap(path, 'yaml_extension_unsupported', 'The reviewed native project contract discovers .yml files; .yaml text is retained without claiming native recognition.')
            parser.r.cover(path, 'unsupported')
            continue
        try:
            value = read_yaml(text)
        except ImportError:
            parser.gap(path, 'yaml_dependency_missing', 'Pinned PyYAML is unavailable; exact YAML is retained without semantic extraction.')
            parser.r.cover(path, 'partial')
            continue
        except ValueError:
            parser.gap(path, 'invalid_yaml', 'YAML is malformed, contains aliases/duplicate keys/unsafe tags, or exceeds structure bounds.')
            parser.r.cover(path, 'partial')
            continue
        parser.yaml(path, value)
        if path not in parser.r.coverage:
            parser.r.cover(path, 'partial')
    for path, text in sorted(files.items()):
        if PurePosixPath(path).suffix.lower() == '.json':
            parser.r.expression(path, '$json', 'json', text, interpretation='preserved_original')
            try:
                value = read_json(text)
            except ValueError:
                parser.gap(path, 'invalid_json', 'JSON is malformed, contains duplicate keys, or exceeds structure bounds.')
                parser.r.cover(path, 'partial')
                continue
            parser.manifest(path, value)
            if path not in parser.r.coverage:
                parser.r.cover(path, 'partial')
    for path, text in sorted(files.items()):
        if path in parser.r.coverage:
            continue
        extension = PurePosixPath(path).suffix.lower()
        if extension in ('.sql', '.py'):
            parser.code(path, text)
        elif extension == '.csv':
            parser.r.object(path, '$file', 'dbt_seed_file_candidate', PurePosixPath(path).name,
                            contents='not_included', classification='extension_only_unbound',
                            byte_count=len(text.encode('utf-8')))
            parser.gap(path, 'seed_data_uninterpreted', 'CSV bytes are hashed only; delimiter, column types, seed binding and data rows are not interpreted.')
            parser.r.cover(path, 'partial')
        else:
            parser.gap(path, 'unsupported_file', 'File is outside this bounded source contract and remains unexecuted.')
            parser.r.cover(path, 'unsupported')
    return parser.r.finish()
