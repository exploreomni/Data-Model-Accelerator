"""Offline Snowflake SQL and documented SQL API / CLI metadata snapshots."""
from pathlib import PurePosixPath
import re

from .base import Report, read_json
from .sql import parse_sql


CAPABILITY = {
    'formats': ['Snowflake .sql', 'SQL API v2 ResultSet JSON',
                'Snowflake CLI JSON/JSON_EXT metadata row arrays'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'No SQL execution, API acquisition, credential loading, or CLI execution.',
        'Only documented metadata column signatures are interpreted as catalogue rows.',
        'Result columns do not establish physical columns or authenticated source provenance.',
        'Policy attachments, grants, pagination, dynamic SQL and procedural behavior require separate review.',
    ],
}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _positive(value):
    return (type(value) is int and value > 0) or (isinstance(value, str) and bool(re.fullmatch(r'[1-9][0-9]*', value)))


def _qualified(parts):
    # Metadata values are stored identifiers, not SQL tokens. Always quote each
    # component so A.B / C and A / B.C cannot collapse into the same identity.
    return '.'.join('"' + part.replace('"', '""') + '"' for part in parts)


class _Parser:
    def __init__(self, files):
        self.r = Report('snowflake', files)
        self.parents = {}
        self.identities = set()

    def gap(self, path, code, message, loc='$'):
        self.r.gap(path, 'snowflake.' + code, message, loc)

    def identity(self, path, loc, row, keys):
        if not all(_text(row.get(key)) for key in keys):
            self.gap(path, 'missing_identity', 'Explicit non-empty database, schema and object identifiers are required.', loc)
            return None
        return tuple(row[key] for key in keys)

    def unique(self, path, loc, kind, parts):
        key = (kind, parts)
        if key in self.identities:
            self.gap(path, 'duplicate_identity', 'Repeated metadata identity; snapshots are not merged or deduplicated.', loc)
        self.identities.add(key)

    def parent(self, path, loc, parts):
        key = (path, parts)
        if key not in self.parents:
            self.parents[key] = self.r.object(path, loc + '.relation', 'relation', _qualified(parts),
                identity_components=list(parts), identity_kind='qualified_name', metadata_only=True)
        return self.parents[key]

    def row(self, path, loc, row):
        if not isinstance(row, dict):
            self.gap(path, 'invalid_row', 'Expected an object with documented metadata column names.', loc)
            return
        keys = set(row)
        if {'COLUMN_NAME', 'DATA_TYPE', 'ORDINAL_POSITION'} <= keys:
            parts = self.identity(path, loc, row, ('TABLE_CATALOG', 'TABLE_SCHEMA', 'TABLE_NAME', 'COLUMN_NAME'))
            if parts is None:
                return
            if not _text(row['DATA_TYPE']) or not _positive(row['ORDINAL_POSITION']) or row.get('IS_NULLABLE') not in ('YES', 'NO'):
                self.gap(path, 'invalid_column', 'COLUMNS requires a type, positive ordinal and YES/NO nullability.', loc)
                return
            self.unique(path, loc, 'column', parts)
            oid = self.r.object(path, loc, 'column', parts[-1], parent_id=self.parent(path, loc, parts[:3]),
                identity_components=list(parts), data_type=row['DATA_TYPE'],
                ordinal_position=row['ORDINAL_POSITION'], nullable=row['IS_NULLABLE'] == 'YES',
                comment=row.get('COMMENT'), raw_metadata=row, metadata_contract='INFORMATION_SCHEMA.COLUMNS')
            default = row.get('COLUMN_DEFAULT')
            if isinstance(default, str) and default:
                self.r.expression(path, loc + '.COLUMN_DEFAULT', 'snowflake', default, oid, interpretation='declared_default')
        elif {'TABLE_TYPE', 'TABLE_NAME'} <= keys:
            parts = self.identity(path, loc, row, ('TABLE_CATALOG', 'TABLE_SCHEMA', 'TABLE_NAME'))
            if parts is None:
                return
            if not _text(row['TABLE_TYPE']):
                self.gap(path, 'invalid_table', 'TABLES requires a non-empty TABLE_TYPE.', loc)
                return
            self.unique(path, loc, 'table', parts)
            self.r.object(path, loc, 'relation', _qualified(parts), identity_components=list(parts),
                table_type=row['TABLE_TYPE'], comment=row.get('COMMENT'), raw_metadata=row,
                metadata_contract='INFORMATION_SCHEMA.TABLES')
            if 'VIEW' in row['TABLE_TYPE']:
                self.gap(path, 'definition_missing', 'TABLES does not provide the view SQL definition.', loc)
        elif {'column_name', 'data_type', 'kind'} <= keys:
            parts = self.identity(path, loc, row, ('database_name', 'schema_name', 'table_name', 'column_name'))
            if parts is None:
                return
            dtype = row['data_type']
            if isinstance(dtype, str):
                try:
                    dtype = read_json(dtype)
                except ValueError:
                    dtype = None
            null_value = row.get('null?')
            if (not isinstance(dtype, dict) or not _text(dtype.get('type')) or
                    not (type(null_value) is bool or (isinstance(null_value, str) and null_value in ('true', 'false')))):
                self.gap(path, 'invalid_column', 'SHOW COLUMNS requires its JSON data_type and documented null? value.', loc)
                return
            if row['kind'] not in ('COLUMN', 'VIRTUAL_COLUMN'):
                self.gap(path, 'unsupported_column_kind', 'Semantic-view dimensions, facts and metrics need a separate semantic contract.', loc)
                return
            self.unique(path, loc, 'column', parts)
            oid = self.r.object(path, loc, 'column', parts[-1], parent_id=self.parent(path, loc, parts[:3]),
                identity_components=list(parts), data_type=dtype['type'], data_type_metadata=dtype,
                nullable=row['null?'] in (True, 'true'), comment=row.get('comment'),
                raw_metadata=row, metadata_contract='SHOW COLUMNS')
            for key in ('default', 'expression'):
                if isinstance(row.get(key), str) and row[key]:
                    self.r.expression(path, loc + '.' + key, 'snowflake', row[key], oid, interpretation='declared_' + key)
        elif {'key_sequence', 'constraint_name', 'column_name'} <= keys:
            parts = self.identity(path, loc, row, ('database_name', 'schema_name', 'table_name', 'column_name', 'constraint_name'))
            if parts is None:
                return
            if not _positive(row['key_sequence']):
                self.gap(path, 'invalid_constraint', 'SHOW PRIMARY KEYS requires a positive key_sequence.', loc)
                return
            self.unique(path, loc, 'primary_key_column', parts)
            self.r.object(path, loc, 'primary_key_column', row['constraint_name'],
                parent_id=self.parent(path, loc, parts[:3]), identity_components=list(parts),
                column_name=row['column_name'], key_sequence=row['key_sequence'], comment=row.get('comment'),
                enforcement='not_verified', raw_metadata=row, metadata_contract='SHOW PRIMARY KEYS')
            self.gap(path, 'key_enforcement_unverified', 'A declared primary key is not observed uniqueness; enforcement depends on table kind.', loc)
        elif {'POLICY_NAME', 'POLICY_KIND'} <= keys:
            parts = self.identity(path, loc, row, ('POLICY_DB', 'POLICY_SCHEMA', 'POLICY_NAME'))
            if parts is None:
                return
            if not _text(row['POLICY_KIND']):
                self.gap(path, 'invalid_policy', 'POLICY_REFERENCES requires a policy kind.', loc)
                return
            oid = self.r.object(path, loc, 'policy_reference', _qualified(parts), identity_components=list(parts),
                policy_kind=row['POLICY_KIND'], policy_status=row.get('POLICY_STATUS'),
                raw_metadata=row, metadata_contract='INFORMATION_SCHEMA.POLICY_REFERENCES')
            if row.get('REF_ENTITY_DOMAIN') in ('TABLE', 'VIEW'):
                target = self.identity(path, loc, row, ('REF_DATABASE_NAME', 'REF_SCHEMA_NAME', 'REF_ENTITY_NAME'))
                if target:
                    self.r.dependency(path, loc, oid, _qualified(target), kind='policy_attachment',
                        target_components=list(target), column_name=row.get('REF_COLUMN_NAME'),
                        resolution='unresolved', effective_access='not_verified')
            else:
                self.gap(path, 'policy_target_unresolved', 'Only explicitly qualified TABLE/VIEW policy targets are structurally linked.', loc)
            self.gap(path, 'effective_security_unverified', 'Policy association is supplied evidence only; policy bodies, role grants, tag propagation and effective access require validation.', loc)
        else:
            self.gap(path, 'unsupported_metadata_row', 'Row does not match a supported documented metadata column signature.', loc)

    def result_set(self, path, value):
        if value.get('sqlState') != '00000' or not _text(value.get('statementHandle')):
            self.gap(path, 'invalid_result_set', 'A successful ResultSet requires sqlState 00000 and a statementHandle.')
            return
        metadata, data = value.get('resultSetMetaData'), value.get('data')
        if not isinstance(metadata, dict) or not isinstance(data, list):
            self.gap(path, 'invalid_result_set', 'ResultSet requires resultSetMetaData and a data array.')
            return
        columns = metadata.get('rowType')
        if (not isinstance(columns, list) or not columns or
                any(not isinstance(c, dict) or not _text(c.get('name')) or not _text(c.get('type')) for c in columns)):
            self.gap(path, 'invalid_row_type', 'rowType must contain named and typed result columns.')
            return
        if metadata.get('format', 'jsonv2') != 'jsonv2':
            self.gap(path, 'unsupported_result_format', 'Only jsonv2 ResultSet data is supported.')
            return
        count = metadata.get('numRows')
        if type(count) is not int or count < 0:
            self.gap(path, 'invalid_row_count', 'numRows must be a non-negative integer.')
            return
        oid = self.r.object(path, '$', 'result_set', value['statementHandle'], native_id=value['statementHandle'],
            result_metadata=metadata, statement_status_url=value.get('statementStatusUrl'),
            supplied_row_count=len(data), declared_row_count=count, provenance='supplied_unverified')
        for i, column in enumerate(columns):
            self.r.object(path, '$.resultSetMetaData.rowType[%d]' % i, 'result_column', column['name'],
                parent_id=oid, data_type=column['type'], raw_metadata=column)
        if 'statementHandles' in value:
            self.gap(path, 'multiple_statement_results', 'A multi-statement response does not contain each statement result; supply individual ResultSets.')
            return
        partitions = metadata.get('partitionInfo')
        if partitions is not None:
            if (not isinstance(partitions, list) or not partitions or
                    any(not isinstance(p, dict) or type(p.get('rowCount')) is not int or p['rowCount'] < 0 for p in partitions)):
                self.gap(path, 'invalid_partitions', 'partitionInfo requires non-negative integer rowCount entries.')
            elif sum(p['rowCount'] for p in partitions) != count:
                self.gap(path, 'row_count_mismatch', 'Partition row counts do not match numRows.')
            if isinstance(partitions, list) and len(partitions) > 1:
                self.gap(path, 'partition_scope_unverified', 'Multiple partitions declared; file presence does not authenticate a complete, non-overlapping partition chain.')
        if count != len(data):
            self.gap(path, 'row_count_mismatch', 'This response row count differs from numRows; other partitions may be absent.')
        names = [c['name'] for c in columns]
        if len(set(names)) != len(names):
            self.gap(path, 'duplicate_result_column', 'Duplicate result-column names prevent safe mapping to catalogue row keys.')
            return
        if not data:
            self.gap(path, 'empty_rows', 'Empty results do not establish catalogue scope or absence of objects.')
        for i, row in enumerate(data):
            loc = '$.data[%d]' % i
            if not isinstance(row, list) or len(row) != len(names) or any(v is not None and not isinstance(v, str) for v in row):
                self.gap(path, 'invalid_result_row', 'jsonv2 rows must contain one string or null cell per result column.', loc)
                continue
            self.row(path, loc, dict(zip(names, row)))

    def sql(self, path, text):
        # Conservatively retain procedural/templated bodies as one source unit;
        # interpreting incidental SELECT statements would invent runtime reads.
        if re.search(r'\b(?:PROCEDURE|FUNCTION|EXECUTE\s+IMMEDIATE|DECLARE|BEGIN|CALL)\b|\$\$|<%|{{|{%', text, re.I):
            self.r.expression(path, '$sql', 'snowflake', text, interpretation='preserved_original')
            self.gap(path, 'procedural_or_dynamic_sql', 'Procedural, dynamic or templated SQL is retained without execution or runtime dependency claims.')
            self.r.cover(path, 'partial')
        else:
            parse_sql(self.r, path, text, 'snowflake')
        if re.search(r'\b(?:MASKING\s+POLICY|ROW\s+ACCESS\s+POLICY|TAG|GRANT|REVOKE)\b|#UNKNOWN', text, re.I):
            self.gap(path, 'security_sql_unverified', 'Security declarations or GET_DDL placeholders require complete policy definitions, attachments and role-context validation.')


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
                parser.gap(path, 'invalid_json', 'JSON is malformed, ambiguous, or exceeds the bounded structure contract.')
                parser.r.cover(path, 'partial')
                continue
            parser.r.expression(path, '$json', 'json', text, interpretation='preserved_original')
            if isinstance(value, dict) and 'resultSetMetaData' in value:
                parser.result_set(path, value)
            elif isinstance(value, list):
                if not value:
                    parser.gap(path, 'empty_rows', 'Empty arrays do not identify the exporting query or establish absence of objects.')
                for i, row in enumerate(value):
                    parser.row(path, '$[%d]' % i, row)
            else:
                parser.gap(path, 'unsupported_json_shape', 'Supply a documented SQL API ResultSet or CLI metadata row array; custom envelopes and data-only partitions are not inferred.')
            parser.r.cover(path, 'parsed')
        else:
            parser.gap(path, 'unsupported_file', 'Only supplied SQL and JSON metadata snapshots are interpreted; project configuration and executable sources remain unexecuted.')
            parser.r.cover(path, 'unsupported')
    return parser.r.finish()
