"""Bounded, offline Databricks SQL and Unity Catalog metadata extraction."""
import json
from pathlib import PurePosixPath
import re

from .base import Report, read_json
from .sql import parse_sql


CAPABILITY = {
    'formats': ['Databricks .sql', 'Unity Catalog TableInfo and ListTables JSON'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'No execution, API acquisition, credentials, SDK, Spark session or customer-code import.',
        'TableInfo/ListTables snapshots do not establish export completeness or effective permissions.',
        'SQL namespaces, dynamic identifiers, jobs, notebooks, bundle targets and streaming runtime remain unresolved.',
        'Constraints, row filters and masks are declarations, not verified integrity or access enforcement.',
    ],
}

_TABLE_STRINGS = {
    'name', 'catalog_name', 'schema_name', 'table_type', 'data_source_format',
    'storage_location', 'view_definition', 'sql_path', 'owner', 'comment',
    'storage_credential_name', 'pipeline_id', 'enable_predictive_optimization',
    'metastore_id', 'full_name', 'data_access_configuration_id', 'created_by',
    'updated_by', 'table_id', 'access_point',
}
_TABLE_INTS = {'created_at', 'updated_at', 'deleted_at'}
_TABLE_MAPS = {'properties', 'view_dependencies', 'row_filter',
               'delta_runtime_properties_kvpairs', 'effective_predictive_optimization_flag',
               'securable_kind_manifest'}
_TABLE_FIELDS = _TABLE_STRINGS | _TABLE_INTS | _TABLE_MAPS | {
    'columns', 'table_constraints', 'browse_only'}
_COLUMN_STRINGS = {'name', 'type_text', 'type_name', 'type_json', 'type_interval_type', 'comment'}
_COLUMN_INTS = {'position', 'type_precision', 'type_scale', 'partition_index'}
_COLUMN_FIELDS = _COLUMN_STRINGS | _COLUMN_INTS | {'nullable', 'mask'}
_TABLE_TYPES = {'MANAGED', 'EXTERNAL', 'VIEW', 'MATERIALIZED_VIEW', 'STREAMING_TABLE',
                'MANAGED_SHALLOW_CLONE', 'EXTERNAL_SHALLOW_CLONE', 'FOREIGN', 'METRIC_VIEW'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value):
    return isinstance(value, list) and all(_text(v) for v in value)


def _qualified(parts):
    return '.'.join('`' + p.replace('`', '``') + '`' for p in parts if p is not None)


class _Parser:
    def __init__(self, files):
        self.r = Report('databricks', files)
        self.identities, self.native_ids = set(), {}

    def gap(self, path, code, message, loc='$'):
        self.r.gap(path, 'databricks.' + code, message, loc)

    def unknown(self, path, loc, value, allowed):
        if set(value) - allowed:
            self.gap(path, 'unknown_fields', 'Uninterpreted metadata fields remain in the original source and raw metadata.', loc)

    def policy(self, path, loc, value, owner, kind):
        self.r.expression(path, loc, 'json', json.dumps(value, ensure_ascii=False), owner,
                          interpretation='declared_' + kind)
        self.gap(path, 'effective_security_unverified', 'Policy declarations do not establish UDF behavior, inherited policies or effective principal access.', loc)
        if not isinstance(value, dict):
            self.gap(path, 'invalid_policy', 'Row filters and column masks must be objects.', loc)
            return
        columns = 'input_column_names' if kind == 'row_filter' else 'using_column_names'
        arguments = 'input_arguments' if kind == 'row_filter' else 'using_arguments'
        self.unknown(path, loc, value, {'function_name', columns, arguments})
        valid = (_text(value.get('function_name')) and
                 (columns not in value or _strings(value[columns])))
        if arguments in value:
            args = value[arguments]
            valid = valid and isinstance(args, list) and all(
                isinstance(a, dict) and len(a) == 1 and
                next(iter(a)) in ('column', 'constant') and
                isinstance(next(iter(a.values())), str) for a in args)
            self.gap(path, 'deprecated_policy_arguments', 'Deprecated policy argument fields are retained without substituting modern argument semantics.', loc)
        if not valid:
            self.gap(path, 'invalid_policy', 'Policy extraction requires a function name and correctly typed arguments.', loc)
            return
        self.r.dependency(path, loc, owner, value['function_name'], kind=kind + '_function',
                          resolution='unresolved', enforcement='not_verified', raw_metadata=value)

    def constraints(self, path, loc, value, owner):
        if not isinstance(value, list):
            self.gap(path, 'invalid_constraints', 'Table constraints must be an array.', loc)
            return
        if value:
            self.gap(path, 'constraint_integrity_unverified', 'Declared constraints and RELY flags do not establish actual key integrity or enforcement.', loc)
        for i, item in enumerate(value):
            at = loc + '[%d]' % i
            self.r.expression(path, at, 'json', json.dumps(item, ensure_ascii=False), owner,
                              interpretation='declared_constraint')
            kinds = {'primary_key_constraint', 'foreign_key_constraint', 'named_table_constraint'}
            if not isinstance(item, dict) or len(item) != 1 or not set(item) <= kinds:
                self.gap(path, 'invalid_constraint', 'Each constraint must contain exactly one supported native constraint type.', at)
                continue
            kind, detail = next(iter(item.items()))
            if not isinstance(detail, dict) or not _text(detail.get('name')):
                self.gap(path, 'invalid_constraint', 'Constraint details require a declared name.', at)
                continue
            allowed = {'name'}
            if kind == 'primary_key_constraint':
                allowed |= {'child_columns', 'rely', 'timeseries_columns'}
            elif kind == 'foreign_key_constraint':
                allowed |= {'child_columns', 'parent_table', 'parent_columns', 'rely'}
            self.unknown(path, at, detail, allowed)
            valid = ('rely' not in detail or type(detail['rely']) is bool)
            for field in ('child_columns', 'parent_columns', 'timeseries_columns'):
                if field in detail:
                    valid = valid and _strings(detail[field])
            if kind != 'named_table_constraint':
                valid = valid and bool(detail.get('child_columns'))
            if kind == 'foreign_key_constraint':
                valid = (valid and _text(detail.get('parent_table')) and
                         bool(detail.get('parent_columns')) and
                         len(detail['child_columns']) == len(detail['parent_columns']))
            if not valid:
                self.gap(path, 'invalid_constraint', 'Constraint columns, references or RELY metadata are malformed.', at)
                continue
            if kind == 'foreign_key_constraint':
                self.r.dependency(path, at, owner, detail['parent_table'], kind='foreign_key',
                    resolution='unresolved', enforcement='not_verified',
                    source_columns=detail['child_columns'], target_columns=detail['parent_columns'])

    def columns(self, path, loc, value, owner):
        if not isinstance(value, list):
            self.gap(path, 'invalid_columns', 'TableInfo columns must be an array.', loc)
            return
        seen = set()
        if not value:
            self.gap(path, 'columns_missing', 'An empty column array does not establish a complete physical schema.', loc)
        for i, column in enumerate(value):
            at = loc + '[%d]' % i
            if not isinstance(column, dict):
                self.gap(path, 'invalid_column', 'ColumnInfo must be an object.', at)
                continue
            self.unknown(path, at, column, _COLUMN_FIELDS)
            if (not _text(column.get('name')) or
                    not any(_text(column.get(k)) for k in ('type_text', 'type_name', 'type_json')) or
                    any(not isinstance(column[k], str) for k in _COLUMN_STRINGS & set(column)) or
                    any(type(column[k]) is not int for k in _COLUMN_INTS & set(column)) or
                    ('position' in column and column['position'] < 0) or
                    ('nullable' in column and type(column['nullable']) is not bool)):
                self.gap(path, 'invalid_column', 'Column extraction requires name, supplied type metadata and correctly typed optional fields.', at)
                continue
            if column['name'] in seen:
                self.gap(path, 'duplicate_column', 'Repeated column identity retained separately; schema consistency is unresolved.', at)
            seen.add(column['name'])
            oid = self.r.object(path, at, 'column', column['name'], parent_id=owner,
                data_type=column.get('type_text') or column.get('type_name'),
                type_json=column.get('type_json'), position=column.get('position'),
                nullable=column.get('nullable'), comment=column.get('comment'), raw_metadata=column)
            if 'mask' in column:
                self.policy(path, at + '.mask', column['mask'], oid, 'column_mask')

    def table(self, path, loc, value, contract):
        if not isinstance(value, dict) or not _text(value.get('name')) or not _text(value.get('table_type')):
            self.gap(path, 'invalid_table', 'TableInfo requires an explicit name and table_type; filenames never supply identity.', loc)
            return
        self.unknown(path, loc, value, _TABLE_FIELDS)
        if (any(not isinstance(value[k], str) for k in _TABLE_STRINGS & set(value)) or
                any(k in value and not _text(value[k]) for k in ('catalog_name', 'schema_name', 'table_id', 'full_name'))):
            self.gap(path, 'invalid_table', 'Supplied names, IDs and string metadata must have valid native types.', loc)
            return
        parts = tuple(value.get(k) for k in ('catalog_name', 'schema_name', 'name'))
        if None not in parts and value.get('full_name') and value['full_name'] != '.'.join(parts):
            self.gap(path, 'identity_conflict', 'full_name disagrees with explicit catalog, schema and table names; no identity is chosen.', loc)
            return
        if None in parts:
            self.gap(path, 'namespace_unresolved', 'Catalog/schema are missing; full_name and filenames are not split or used to invent namespace.', loc)
        if parts in self.identities:
            self.gap(path, 'duplicate_identity', 'Repeated table identity retained as separate evidence; snapshot equivalence is not established.', loc)
        self.identities.add(parts)
        native = value.get('table_id')
        if native and native in self.native_ids and self.native_ids[native] != parts:
            self.gap(path, 'native_identity_conflict', 'One native table ID has conflicting namespace components; snapshots remain unresolved.', loc)
        if native:
            self.native_ids[native] = parts
        else:
            self.gap(path, 'native_id_missing', 'A native table ID was not supplied; no stable vendor identity is inferred.', loc)
        owner = self.r.object(path, loc, 'relation', _qualified(parts), native_id=native,
            catalog_name=parts[0], schema_name=parts[1], identity_components=list(parts),
            full_name=value.get('full_name'), table_type=value['table_type'],
            comment=value.get('comment'), metadata_contract=contract, raw_metadata=value,
            metadata_only=True, effective_access='not_verified')
        if (any(type(value[k]) is not int for k in _TABLE_INTS & set(value)) or
                any(not isinstance(value[k], dict) for k in _TABLE_MAPS & set(value)) or
                ('browse_only' in value and type(value['browse_only']) is not bool)):
            self.gap(path, 'invalid_metadata', 'Some optional native metadata fields have invalid types; raw values remain preserved.', loc)
        if value.get('browse_only') is True:
            self.gap(path, 'browse_only_metadata', 'BROWSE-only access can return selective metadata; omissions are not negative evidence.', loc)
        if value['table_type'] not in _TABLE_TYPES:
            self.gap(path, 'unknown_table_type', 'Unrecognized table type is retained without behavior interpretation.', loc)
        if value['table_type'] in ('STREAMING_TABLE', 'MATERIALIZED_VIEW', 'METRIC_VIEW') or value.get('pipeline_id'):
            self.gap(path, 'runtime_semantics_unresolved', 'Refresh, streaming state, late data, metric semantics and pipeline/job behavior require native runtime evidence.', loc)
        if 'columns' in value:
            self.columns(path, loc + '.columns', value['columns'], owner)
        else:
            self.gap(path, 'columns_missing', 'Columns were omitted; do not treat the export as a complete physical definition.', loc)
        if 'table_constraints' in value:
            self.constraints(path, loc + '.table_constraints', value['table_constraints'], owner)
        if 'row_filter' in value:
            self.policy(path, loc + '.row_filter', value['row_filter'], owner, 'row_filter')
        if value.get('view_definition'):
            self.sql(path, value['view_definition'], owner, loc + '.view_definition')
        elif value['table_type'] in ('VIEW', 'MATERIALIZED_VIEW', 'METRIC_VIEW'):
            self.gap(path, 'view_definition_missing', 'The view definition was not supplied; view behavior cannot be recovered.', loc)
        if 'view_dependencies' in value:
            self.gap(path, 'view_dependency_metadata_unresolved', 'Native view dependency metadata is retained; its bindings are not authenticated or resolved.', loc + '.view_dependencies')

    def metadata(self, path, value):
        if not isinstance(value, dict):
            self.gap(path, 'unsupported_json_shape', 'Expected a documented TableInfo object or ListTables response, not an invented envelope or row array.')
            return
        if 'tables' in value:
            if set(value) - {'tables', 'next_page_token'}:
                self.gap(path, 'unsupported_json_shape', 'Mixed or wrapped ListTables envelopes are not interpreted.')
                return
            if not isinstance(value['tables'], list):
                self.gap(path, 'invalid_tables', 'ListTables tables must be an array.')
                return
            if 'next_page_token' in value and not isinstance(value['next_page_token'], str):
                self.gap(path, 'invalid_pagination', 'next_page_token must be a string.')
            elif value.get('next_page_token'):
                self.gap(path, 'pagination_incomplete', 'A further page is advertised; no complete or authenticated page chain is established.')
            self.gap(path, 'list_omissions', 'ListTables omits table constraints and view dependencies and may omit columns, properties or usernames.')
            if not value['tables']:
                self.gap(path, 'empty_metadata', 'An empty page does not establish absence of objects or end of pagination.')
            for i, table in enumerate(value['tables']):
                self.table(path, '$.tables[%d]' % i, table, 'Unity Catalog ListTables')
        elif 'name' in value and 'table_type' in value:
            self.table(path, '$', value, 'Unity Catalog TableInfo')
        else:
            self.gap(path, 'unsupported_json_shape', 'JSON does not match the supported native Unity Catalog response shapes.')
            return
        self.gap(path, 'visibility_unverified', 'Acquisition scope, privileges, request options and effective access are not established by supplied metadata.')

    def sql(self, path, text, owner=None, locator='$sql'):
        if re.search(r'\b(?:EXECUTE\s+IMMEDIATE|DECLARE|PROCEDURE|BEGIN|CALL)\b|\bIDENTIFIER\s*\(|\$\{|{{|{%|Databricks notebook source|(?m:^\s*%)', text, re.I):
            self.r.expression(path, locator, 'databricks', text, owner, interpretation='preserved_original')
            self.gap(path, 'dynamic_or_notebook_sql', 'Dynamic, procedural and notebook sources remain unexecuted; supply literal SQL with explicit context.', locator)
            self.r.cover(path, 'partial')
            return
        parse_sql(self.r, path, text, 'databricks', owner_id=owner, locator=locator)
        self.gap(path, 'sql_context_unresolved', 'Session catalog/schema, parameter bindings, runtime and source permissions are not established.', locator)
        if re.search(r'\b(?:STREAM|STREAMING|LIVE|WATERMARK|APPLY\s+CHANGES|AUTO\s+CDC|MATERIALIZED)\b', text, re.I):
            self.gap(path, 'runtime_semantics_unresolved', 'Static SQL cannot establish streaming checkpoints, late-data policy, refresh or pipeline execution behavior.', locator)
        if re.search(r'\b(?:PRIMARY\s+KEY|FOREIGN\s+KEY|CONSTRAINT|RELY)\b', text, re.I):
            self.gap(path, 'constraint_integrity_unverified', 'Declared constraints require independent integrity and enforcement evidence.', locator)
        if re.search(r'\b(?:GRANT|REVOKE|ROW\s+FILTER|MASK|POLICY)\b', text, re.I):
            self.gap(path, 'effective_security_unverified', 'Security statements do not establish effective grants, policy behavior or principal access.', locator)


def parse(files):
    parser = _Parser(files)
    for path, text in sorted(files.items()):
        extension = PurePosixPath(path).suffix.lower()
        if extension == '.sql':
            parser.sql(path, text)
        elif extension == '.json':
            parser.r.expression(path, '$json', 'json', text, interpretation='preserved_original')
            try:
                value = read_json(text)
            except ValueError:
                parser.gap(path, 'invalid_json', 'JSON is malformed, ambiguous or exceeds the bounded structure contract.')
                parser.r.cover(path, 'partial')
                continue
            parser.metadata(path, value)
            parser.r.cover(path, 'parsed')
        else:
            parser.r.expression(path, '$source', 'python' if extension == '.py' else 'text', text,
                                interpretation='preserved_original')
            parser.gap(path, 'unsupported_file', 'Only SQL and native Unity Catalog JSON are interpreted; notebook, bundle and job code is not executed or attributed by extension.')
            parser.r.cover(path, 'unsupported')
    return parser.r.finish()
