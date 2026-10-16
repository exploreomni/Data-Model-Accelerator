"""Bounded offline Redshift SQL and documented metadata response extraction."""
from pathlib import PurePosixPath
import re

from .base import Report, read_json
from .sql import parse_sql


CAPABILITY = {
    'formats': ['Redshift .sql', 'Data API DescribeTable/ListTables/GetStatementResult JSON',
                'SVV_COLUMNS JSON row arrays'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'No SQL execution, API acquisition, credentials, SDK or driver dependency.',
        'Data API result columns are query outputs, never physical table definitions.',
        'Data API metadata responses omit database identity; pagination and provenance remain unverified.',
        'Procedures, dynamic SQL, external behavior, effective permissions and key integrity require separate review.',
    ],
}

_COLUMN_STRINGS = {'columnDefault', 'label', 'name', 'schemaName', 'tableName', 'typeName'}
_COLUMN_INTS = {'length', 'nullable', 'precision', 'scale'}
_COLUMN_BOOLS = {'isCaseSensitive', 'isCurrency', 'isSigned'}
_SVV_FIELDS = {'table_catalog', 'table_schema', 'table_name', 'column_name', 'ordinal_position',
               'column_default', 'is_nullable', 'data_type', 'character_maximum_length',
               'numeric_precision', 'numeric_precision_radix', 'numeric_scale', 'datetime_precision',
               'interval_type', 'interval_precision', 'character_set_catalog', 'character_set_schema',
               'character_set_name', 'collation_catalog', 'collation_schema', 'collation_name',
               'domain_name', 'remarks'}
_SVV_INTS = {'ordinal_position', 'character_maximum_length', 'numeric_precision',
             'numeric_precision_radix', 'numeric_scale', 'datetime_precision'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _qualified(parts):
    return '.'.join('"' + part.replace('"', '""') + '"' for part in parts)


class _Parser:
    def __init__(self, files):
        self.r = Report('redshift', files)
        self.parents, self.identities = {}, set()

    def gap(self, path, code, message, loc='$'):
        self.r.gap(path, 'redshift.' + code, message, loc)

    def unknown(self, path, loc, value, allowed):
        if set(value) - allowed:
            self.gap(path, 'unknown_fields', 'Uninterpreted fields are retained in original JSON and raw metadata where available.', loc)

    def unique(self, path, loc, kind, parts):
        key = (kind, parts)
        if key in self.identities:
            self.gap(path, 'duplicate_identity', 'Repeated metadata identity retained separately; snapshot equivalence is not established.', loc)
        self.identities.add(key)

    def parent(self, path, loc, parts, contract):
        # A missing database must never merge with an explicitly named database.
        key = (path, parts)
        if key not in self.parents:
            self.parents[key] = self.r.object(path, loc + '.relation', 'relation',
                _qualified([p for p in parts if p is not None]), database=parts[0],
                identity_components=list(parts), metadata_contract=contract,
                metadata_only=True, relation_kind='not_established')
        return self.parents[key]

    def pagination(self, path, value):
        if 'NextToken' in value and not isinstance(value['NextToken'], str):
            self.gap(path, 'invalid_pagination', 'NextToken must be a string.')
        elif value.get('NextToken'):
            self.gap(path, 'pagination_incomplete', 'A further page is advertised; supplied files do not authenticate a complete page chain.')

    def api_column(self, path, loc, column):
        if not isinstance(column, dict):
            self.gap(path, 'invalid_column', 'Column metadata must be an object.', loc)
            return False
        self.unknown(path, loc, column, _COLUMN_STRINGS | _COLUMN_INTS | _COLUMN_BOOLS)
        if (any(not isinstance(column[k], str) for k in _COLUMN_STRINGS & set(column)) or
                any(type(column[k]) is not int for k in _COLUMN_INTS & set(column)) or
                any(type(column[k]) is not bool for k in _COLUMN_BOOLS & set(column)) or
                not _text(column.get('name')) or not _text(column.get('typeName'))):
            self.gap(path, 'invalid_column', 'Column extraction requires explicit name/typeName and correctly typed optional metadata.', loc)
            return False
        return True

    def describe(self, path, value):
        self.unknown(path, '$', value, {'ColumnList', 'TableName', 'NextToken', 'ResponseMetadata'})
        self.pagination(path, value)
        columns = value['ColumnList']
        if not isinstance(columns, list):
            self.gap(path, 'invalid_columns', 'DescribeTable ColumnList must be an array.')
            return
        self.gap(path, 'database_identity_missing', 'DescribeTable omits the database; bind the acquisition request separately before resolving relations.')
        if 'TableName' in value and not _text(value['TableName']):
            self.gap(path, 'missing_identity', 'TableName, when supplied, must be a non-empty identifier.')
            return
        if not columns:
            self.gap(path, 'empty_metadata', 'An empty column list does not establish table absence or export completeness.')
        for i, column in enumerate(columns):
            loc = '$.ColumnList[%d]' % i
            if not self.api_column(path, loc, column):
                continue
            table = column.get('tableName') or value.get('TableName')
            if not _text(column.get('schemaName')) or not _text(table):
                self.gap(path, 'missing_identity', 'Explicit schema and table are required; filenames never supply namespace.', loc)
                continue
            if column.get('tableName') and value.get('TableName') and column['tableName'] != value['TableName']:
                self.gap(path, 'identity_conflict', 'Column and response table identities disagree.', loc)
                continue
            parts = (None, column['schemaName'], table)
            self.unique(path, loc, 'column', parts + (column['name'],))
            oid = self.r.object(path, loc, 'column', column['name'], parent_id=self.parent(path, loc, parts, 'Data API DescribeTable'),
                identity_components=list(parts) + [column['name']], data_type=column['typeName'],
                nullable_code=column.get('nullable'), raw_metadata=column,
                metadata_contract='Data API DescribeTable',
                constraints_validation='not_verified')
            if column.get('columnDefault'):
                self.r.expression(path, loc + '.columnDefault', 'redshift', column['columnDefault'], oid, interpretation='declared_default')

    def tables(self, path, value):
        self.unknown(path, '$', value, {'Tables', 'NextToken', 'ResponseMetadata'})
        self.pagination(path, value)
        if not isinstance(value['Tables'], list):
            self.gap(path, 'invalid_tables', 'ListTables Tables must be an array.')
            return
        self.gap(path, 'database_identity_missing', 'ListTables omits the database; table list entries cannot establish complete physical definitions.')
        if not value['Tables']:
            self.gap(path, 'empty_metadata', 'An empty table list does not establish absence of accessible objects.')
        for i, table in enumerate(value['Tables']):
            loc = '$.Tables[%d]' % i
            if not isinstance(table, dict) or not all(_text(table.get(k)) for k in ('name', 'schema', 'type')):
                self.gap(path, 'invalid_table', 'ListTables entries require explicit name, schema and type.', loc)
                continue
            self.unknown(path, loc, table, {'name', 'schema', 'type'})
            parts = (None, table['schema'], table['name'])
            self.unique(path, loc, 'relation', parts)
            self.r.object(path, loc, 'relation', _qualified(parts[1:]), database=None,
                identity_components=list(parts), table_type=table['type'], raw_metadata=table,
                metadata_contract='Data API ListTables', metadata_only=True)
            self.gap(path, 'definition_missing', 'ListTables contains no column or view SQL definition.', loc)

    def result(self, path, value):
        self.unknown(path, '$', value, {'ColumnMetadata', 'Records', 'TotalNumRows', 'NextToken', 'ResponseMetadata'})
        self.pagination(path, value)
        columns, records = value.get('ColumnMetadata'), value.get('Records')
        total = value.get('TotalNumRows')
        if (not isinstance(columns, list) or not isinstance(records, list) or
                (total is not None and (type(total) is not int or total < 0))):
            self.gap(path, 'invalid_result', 'GetStatementResult requires column and record arrays and a non-negative TotalNumRows when present.')
            return
        oid = self.r.object(path, '$', 'result_set', path, supplied_row_count=len(records),
            declared_row_count=total, metadata_contract='Data API GetStatementResult', provenance='supplied_unverified')
        self.gap(path, 'query_result_not_catalogue', 'Query result metadata does not establish physical columns or the original query/statement identity.')
        for i, column in enumerate(columns):
            loc = '$.ColumnMetadata[%d]' % i
            if self.api_column(path, loc, column):
                self.r.object(path, loc, 'result_column', column['name'], parent_id=oid,
                    data_type=column['typeName'], raw_metadata=column)
        if total is None:
            self.gap(path, 'row_count_missing', 'TotalNumRows is absent; result coverage cannot be compared.')
        elif total != len(records):
            self.gap(path, 'row_count_mismatch', 'Supplied rows differ from TotalNumRows; additional pages may be missing.')
        for i, row in enumerate(records):
            loc = '$.Records[%d]' % i
            if not isinstance(row, list) or len(row) != len(columns):
                self.gap(path, 'invalid_result_row', 'Each record requires one tagged Field per result column.', loc)
                continue
            for field in row:
                valid = isinstance(field, dict) and len(field) == 1
                if valid:
                    key, cell = next(iter(field.items()))
                    valid = ((key in ('stringValue', 'blobValue') and isinstance(cell, str)) or
                             (key == 'booleanValue' and type(cell) is bool) or
                             (key == 'isNull' and cell is True) or
                             (key == 'longValue' and type(cell) is int) or
                             (key == 'doubleValue' and type(cell) in (int, float)))
                if not valid:
                    self.gap(path, 'invalid_result_field', 'Data API Field must contain exactly one supported, correctly typed tagged value.', loc)

    def svv_column(self, path, loc, row):
        if not isinstance(row, dict) or not {'column_name', 'ordinal_position', 'data_type'} <= set(row):
            self.gap(path, 'unsupported_metadata_row', 'Only the documented SVV_COLUMNS row signature is supported.', loc)
            return
        self.unknown(path, loc, row, _SVV_FIELDS)
        keys = ('table_catalog', 'table_schema', 'table_name', 'column_name')
        if not all(_text(row.get(k)) for k in keys):
            self.gap(path, 'missing_identity', 'SVV_COLUMNS requires catalog, schema, table and column identifiers.', loc)
            return
        if (not _text(row['data_type']) or type(row['ordinal_position']) is not int or row['ordinal_position'] <= 0 or
                row.get('is_nullable') not in ('YES', 'NO') or
                any(row[k] is not None and type(row[k]) is not int for k in _SVV_INTS & set(row)) or
                any(row[k] is not None and not isinstance(row[k], str) for k in (_SVV_FIELDS - _SVV_INTS) & set(row))):
            self.gap(path, 'invalid_column', 'SVV_COLUMNS requires valid type, ordinal, nullability, comment and default values.', loc)
            return
        parts = tuple(row[k] for k in keys)
        self.unique(path, loc, 'column', parts)
        oid = self.r.object(path, loc, 'column', parts[-1], parent_id=self.parent(path, loc, parts[:3], 'SVV_COLUMNS'),
            identity_components=list(parts), data_type=row['data_type'], ordinal_position=row['ordinal_position'],
            nullable=row['is_nullable'] == 'YES', comment=row.get('remarks'), raw_metadata=row,
            metadata_contract='SVV_COLUMNS', constraints_validation='not_verified')
        if row.get('column_default'):
            self.r.expression(path, loc + '.column_default', 'redshift', row['column_default'], oid, interpretation='declared_default')

    def sql(self, path, text):
        if re.search(r'\b(?:PROCEDURE|FUNCTION|EXECUTE|DECLARE|BEGIN|CALL)\b|\$[A-Za-z_0-9]*\$|{{|{%', text, re.I):
            self.r.expression(path, '$sql', 'redshift', text, interpretation='preserved_original')
            self.gap(path, 'procedural_or_dynamic_sql', 'Procedural, templated and dynamic SQL is retained without runtime dependency claims.')
            self.r.cover(path, 'partial')
        elif re.search(r'\b(?:CREATE\s+EXTERNAL|COPY|UNLOAD|CREATE\s+LIBRARY)\b', text, re.I):
            self.r.expression(path, '$sql', 'redshift', text, interpretation='preserved_original')
            self.gap(path, 'external_behavior_unresolved', 'External catalog, file movement and library behavior require separate evidence.')
            self.r.cover(path, 'partial')
        else:
            parse_sql(self.r, path, text, 'redshift')
        if re.search(r'\b(?:PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE)\b', text, re.I):
            self.gap(path, 'key_integrity_unverified', 'Redshift primary, foreign and unique keys are informational; actual integrity is not verified.')
        if re.search(r'\b(?:GRANT|REVOKE|POLICY|ROW\s+LEVEL\s+SECURITY|MASKING)\b', text, re.I):
            self.gap(path, 'effective_security_unverified', 'Security source is preserved; effective grants, policy bindings and principal access require native review.')


def parse(files):
    parser = _Parser(files)
    for path, text in sorted(files.items()):
        extension = PurePosixPath(path).suffix.lower()
        if extension == '.sql':
            parser.sql(path, text)
        elif extension == '.json':
            try:
                value = read_json(text)
            except ValueError:
                parser.gap(path, 'invalid_json', 'JSON is malformed, ambiguous or exceeds the bounded structure contract.')
                parser.r.cover(path, 'partial')
                continue
            parser.r.expression(path, '$json', 'json', text, interpretation='preserved_original')
            if isinstance(value, dict):
                shapes = [k for k in ('ColumnList', 'Tables', 'Records', 'ColumnMetadata') if k in value]
                if shapes == ['ColumnList']:
                    parser.describe(path, value)
                elif shapes == ['Tables']:
                    parser.tables(path, value)
                elif shapes and set(shapes) <= {'Records', 'ColumnMetadata'}:
                    parser.result(path, value)
                else:
                    parser.gap(path, 'unsupported_json_shape', 'Supply a single documented Data API response; unknown and mixed envelopes are not inferred.')
            elif isinstance(value, list):
                if not value:
                    parser.gap(path, 'empty_metadata', 'Empty row arrays do not establish metadata absence.')
                for i, row in enumerate(value):
                    parser.svv_column(path, '$[%d]' % i, row)
                parser.gap(path, 'catalogue_scope_unverified', 'SVV_COLUMNS includes local/external tables and views; query, permissions, object kind and full export scope remain unverified.')
            else:
                parser.gap(path, 'unsupported_json_shape', 'Expected a documented Data API response or SVV_COLUMNS row array.')
            parser.r.cover(path, 'parsed')
        else:
            parser.gap(path, 'unsupported_file', 'Only supplied SQL and JSON snapshots are interpreted; executables and configuration remain unexecuted.')
            parser.r.cover(path, 'unsupported')
    return parser.r.finish()
