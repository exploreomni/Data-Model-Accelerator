"""Independent synthetic Snowflake source expectations; no source execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from source_adapters.snowflake import CAPABILITY, parse
from source_adapters.registry import validate


def column(**updates):
    row = {'TABLE_CATALOG': 'ANALYTICS', 'TABLE_SCHEMA': 'Sales', 'TABLE_NAME': 'Orders',
           'COLUMN_NAME': 'OrderId', 'ORDINAL_POSITION': 1, 'DATA_TYPE': 'NUMBER',
           'IS_NULLABLE': 'NO', 'NUMERIC_PRECISION': 38, 'NUMERIC_SCALE': 0,
           'COMMENT': 'Source order key', 'COLUMN_DEFAULT': 'SEQ.NEXTVAL'}
    return dict(row, **updates)


def response(rows=None):
    # SQL API jsonv2 cells are strings or null, unlike native JSON_EXT rows.
    rows = rows if rows is not None else [column()]
    keys = list(rows[0])
    return {'code': '090001', 'sqlState': '00000',
            'statementHandle': '536fad38-b564-4dc5-9892-a4543504df6c',
            'statementStatusUrl': '/api/v2/statements/536fad38-b564-4dc5-9892-a4543504df6c',
            'resultSetMetaData': {'numRows': len(rows), 'format': 'jsonv2',
                'rowType': [{'name': k, 'type': 'text'} for k in keys],
                'partitionInfo': [{'rowCount': len(rows), 'uncompressedSize': 200}]},
            'data': [[None if row[k] is None else str(row[k]) for k in keys] for row in rows]}


def checked(files):
    result = parse(files)
    validate(result, files)
    return result


class NativeMaterializationTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Pinned SQL parser required')
    def test_dynamic_table_is_not_an_ordinary_fully_interpreted_table(self):
        text = "CREATE DYNAMIC TABLE D.S.DT TARGET_LAG = '1 minute' WAREHOUSE = W AS SELECT ID FROM D.S.T"
        result = checked({'dynamic.sql': text})
        self.assertEqual(result['source_files'][0]['status'], 'partial')
        self.assertIn('sql.native_materialization', {g['code'] for g in result['gaps']})
        relation = next(o for o in result['objects'] if o['kind'] == 'relation')
        self.assertIn('DynamicProperty', relation['details']['native_property_kinds'])
        self.assertTrue(any(e['text'] == text for e in result['expressions']))


def exported(value, path='snapshots/nested/catalogue.json'):
    return checked({path: json.dumps(value)})


def codes(result):
    return {gap['code'] for gap in result['gaps']}


class SnowflakeMetadataTests(unittest.TestCase):
    def test_capability_is_offline(self):
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')

    def test_information_schema_columns_preserve_identifiers_types_comments_and_defaults(self):
        rows = [column(), column(COLUMN_NAME='Amount', ORDINAL_POSITION=2, DATA_TYPE='NUMBER',
                                  NUMERIC_SCALE=2, IS_NULLABLE='YES', COLUMN_DEFAULT=None)]
        result = exported(rows)
        relations = [o for o in result['objects'] if o['kind'] == 'relation']
        self.assertEqual([o['name'] for o in relations], ['"ANALYTICS"."Sales"."Orders"'])
        fields = [o for o in result['objects'] if o['kind'] == 'column']
        self.assertEqual([f['name'] for f in fields], ['OrderId', 'Amount'])
        self.assertEqual(fields[0]['details']['data_type'], 'NUMBER')
        self.assertEqual(fields[0]['details']['comment'], 'Source order key')
        self.assertFalse(fields[0]['details']['nullable'])
        self.assertTrue(fields[1]['details']['nullable'])
        self.assertEqual(fields[1]['details']['raw_metadata']['NUMERIC_SCALE'], 2)
        self.assertEqual(fields[0]['details']['parent_id'], relations[0]['id'])
        self.assertIn('SEQ.NEXTVAL', [e['text'] for e in result['expressions']])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')
        self.assertFalse(result['execution_performed'])

    def test_real_sql_api_shape_preserves_native_handle_and_row_locator(self):
        value = response()
        source = json.dumps(value)
        result = checked({'exports/schema/part0.json': source})
        result_set = next(o for o in result['objects'] if o['kind'] == 'result_set')
        self.assertEqual(result_set['native_id'], value['statementHandle'])
        field = next(o for o in result['objects'] if o['kind'] == 'column')
        self.assertEqual(field['evidence'], {'path': 'exports/schema/part0.json', 'locator': '$.data[0]',
                                            'sha256': hashlib.sha256(source.encode()).hexdigest()})
        self.assertEqual(result_set['details']['declared_row_count'], 1)

    def test_query_result_columns_are_not_physical_columns(self):
        value = response([{'customer_id': '42', 'total': '19.00'}])
        result = exported(value)
        self.assertEqual({o['kind'] for o in result['objects']}, {'result_set', 'result_column'})
        self.assertIn('snowflake.unsupported_metadata_row', codes(result))
        self.assertFalse(result['dependencies'])

    def test_show_columns_supports_cli_json_and_json_ext_without_running_cli(self):
        row = {'database_name': 'ANALYTICS', 'schema_name': 'PUBLIC', 'table_name': 'ORDERS',
               'column_name': 'N', 'data_type': {'type': 'FIXED', 'precision': 38, 'scale': 0, 'nullable': True},
               'kind': 'COLUMN', 'null?': True, 'comment': 'sequence', 'default': '5'}
        for dtype in (row['data_type'], json.dumps(row['data_type'])):
            with self.subTest(dtype=dtype):
                result = exported([dict(row, data_type=dtype)])
                field = next(o for o in result['objects'] if o['kind'] == 'column')
                self.assertEqual(field['details']['data_type'], 'FIXED')
                self.assertEqual(field['details']['data_type_metadata']['precision'], 38)
                self.assertIn('5', [e['text'] for e in result['expressions']])

    def test_table_metadata_retains_type_comment_and_flags_missing_view_definition(self):
        result = exported([{'TABLE_CATALOG': 'D', 'TABLE_SCHEMA': 'S', 'TABLE_NAME': 'V',
                            'TABLE_TYPE': 'VIEW', 'COMMENT': 'Customer totals'}])
        self.assertEqual(result['objects'][0]['details']['comment'], 'Customer totals')
        self.assertIn('snowflake.definition_missing', codes(result))
        self.assertFalse(result['dependencies'])

    def test_primary_key_order_is_declaration_not_observed_uniqueness(self):
        result = exported([{'database_name': 'D', 'schema_name': 'S', 'table_name': 'T',
            'column_name': 'TENANT_ID', 'key_sequence': '1', 'constraint_name': 'PK_T', 'comment': 'tenant key'},
            {'database_name': 'D', 'schema_name': 'S', 'table_name': 'T',
             'column_name': 'ID', 'key_sequence': '2', 'constraint_name': 'PK_T', 'comment': None}])
        keys = [o for o in result['objects'] if o['kind'] == 'primary_key_column']
        self.assertEqual([o['details']['column_name'] for o in keys], ['TENANT_ID', 'ID'])
        self.assertEqual([o['details']['key_sequence'] for o in keys], ['1', '2'])
        self.assertTrue(all(o['details']['enforcement'] == 'not_verified' for o in keys))
        self.assertIn('snowflake.key_enforcement_unverified', codes(result))

    def test_policy_attachment_preserves_status_without_security_success_claim(self):
        row = {'POLICY_DB': 'GOV', 'POLICY_SCHEMA': 'SEC', 'POLICY_NAME': 'MASK_EMAIL',
               'POLICY_KIND': 'MASKING_POLICY', 'REF_DATABASE_NAME': 'D', 'REF_SCHEMA_NAME': 'S',
               'REF_ENTITY_NAME': 'T', 'REF_ENTITY_DOMAIN': 'TABLE', 'REF_COLUMN_NAME': 'EMAIL',
               'POLICY_STATUS': 'COLUMN_DATATYPE_MISMATCH_FOR_SECONDARY_ARG',
               'TAG_DATABASE': 'GOV', 'TAG_SCHEMA': 'SEC', 'TAG_NAME': 'PII'}
        result = exported([row])
        policy = result['objects'][0]
        self.assertEqual(policy['details']['policy_status'], row['POLICY_STATUS'])
        self.assertEqual(policy['details']['raw_metadata']['TAG_NAME'], 'PII')
        dependency = result['dependencies'][0]
        self.assertEqual(dependency['target'], '"D"."S"."T"')
        self.assertEqual(dependency['details']['column_name'], 'EMAIL')
        self.assertEqual(dependency['details']['effective_access'], 'not_verified')
        self.assertIn('snowflake.effective_security_unverified', codes(result))
        row['REF_ENTITY_DOMAIN'] = 'ACCOUNT'
        self.assertFalse(exported([row])['dependencies'])

    def test_components_preserve_dots_quotes_and_case_without_identity_collision(self):
        result = exported([column(TABLE_CATALOG='D.S', TABLE_SCHEMA='X', COLUMN_DEFAULT=None),
                           column(TABLE_CATALOG='D', TABLE_SCHEMA='S.X', COLUMN_DEFAULT=None),
                           column(TABLE_CATALOG='d', TABLE_SCHEMA='S.X', COLUMN_DEFAULT=None),
                           column(TABLE_CATALOG='D"Q', TABLE_SCHEMA='S.X', COLUMN_DEFAULT=None)])
        relations = [o['name'] for o in result['objects'] if o['kind'] == 'relation']
        self.assertEqual(len(set(relations)), 4)
        self.assertIn('"D""Q"."S.X"."Orders"', relations)

    def test_duplicate_identity_remains_visible(self):
        result = exported([column(), column()])
        self.assertIn('snowflake.duplicate_identity', codes(result))
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'column']), 2)

    def test_missing_identity_is_not_inferred_from_filename(self):
        row = column()
        del row['TABLE_CATALOG']
        result = exported([row], 'D/S/T.json')
        self.assertIn('snowflake.missing_identity', codes(result))
        self.assertFalse(result['objects'])

    def test_invalid_columns_and_rows_cannot_create_physical_schema(self):
        for row in [column(ORDINAL_POSITION=True), column(DATA_TYPE={}), column(IS_NULLABLE='maybe'),
                    column(TABLE_SCHEMA=None), 3, False]:
            with self.subTest(row=row):
                self.assertFalse(exported([row])['objects'])

    def test_malformed_ambiguous_and_nonfinite_json(self):
        for text in ['{', '{"data":1,"data":2}', '[NaN]', '[' * 60 + '0' + ']' * 60]:
            with self.subTest(text=text):
                result = checked({'bad.json': text})
                self.assertEqual(codes(result), {'snowflake.invalid_json'})
                self.assertFalse(result['objects'])

    def test_unknown_envelopes_partition_only_and_empty_input_are_gaps(self):
        for value in [{'tables': [column()]}, {'data': [['x']]}, {}, []]:
            with self.subTest(value=value):
                result = exported(value)
                self.assertTrue(result['gaps'])
                self.assertFalse(result['objects'])

    def test_pagination_and_count_mismatches_remain_unverified(self):
        value = response()
        value['resultSetMetaData']['numRows'] = 2
        value['resultSetMetaData']['partitionInfo'].append({'rowCount': 1})
        result = exported(value)
        self.assertIn('snowflake.partition_scope_unverified', codes(result))
        self.assertIn('snowflake.row_count_mismatch', codes(result))
        self.assertEqual(result['source_files'][0]['status'], 'partial')

    def test_error_status_bad_types_duplicate_column_and_bad_row_width(self):
        mutations = [lambda v: v.update(sqlState='42000'),
                     lambda v: v['resultSetMetaData'].update(rowType='bad'),
                     lambda v: v['resultSetMetaData'].update(numRows=True),
                     lambda v: v['resultSetMetaData'].update(format='csv'),
                     lambda v: v['data'][0].pop(),
                     lambda v: v['data'][0].__setitem__(0, 42),
                     lambda v: v['resultSetMetaData']['rowType'][1].update(name='TABLE_CATALOG')]
        for mutate in mutations:
            value = response()
            mutate(value)
            with self.subTest(value=value):
                result = exported(value)
                self.assertTrue(result['gaps'])
                self.assertFalse([o for o in result['objects'] if o['kind'] == 'column'])

    def test_security_and_procedural_sql_are_retained_without_execution(self):
        text = 'CREATE PROCEDURE p() RETURNS STRING LANGUAGE PYTHON AS $$ import os; os.remove("sentinel") $$;'
        result = checked({'nested/code.sql': text, 'nested/snowflake.yml': 'definition_version: 2'})
        self.assertEqual(result['expressions'][0]['text'], text)
        self.assertFalse(result['objects'])
        self.assertFalse(result['dependencies'])
        self.assertIn('snowflake.procedural_or_dynamic_sql', codes(result))
        self.assertIn('snowflake.unsupported_file', codes(result))

    def test_missing_optional_sql_parser_is_visible(self):
        with patch.dict(sys.modules, {'sqlglot': None}):
            result = checked({'query.sql': 'SELECT id FROM D.S.T'})
        self.assertIn('sql.parser_dependency_missing', codes(result))
        self.assertEqual(result['expressions'][0]['text'], 'SELECT id FROM D.S.T')

    def test_unsafe_source_paths_rejected(self):
        for files in [{'../ddl.sql': 'SELECT 1'}, {'a.sql': '', 'A.sql': ''}, {'x': '', 'x/y.sql': ''}]:
            with self.subTest(files=files):
                with self.assertRaises(ValueError):
                    parse(files)


@unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'optional sqlglot parser not installed')
class SnowflakeSQLTests(unittest.TestCase):
    def test_snowflake_ddl_query_and_original_source(self):
        text = ('CREATE TABLE "D"."S"."Orders" (ID NUMBER(38,0) PRIMARY KEY, AMOUNT NUMBER(12,2));\n'
                'CREATE VIEW "D"."S"."Ranked" AS SELECT ID, AMOUNT FROM "D"."S"."Orders" '
                'QUALIFY ROW_NUMBER() OVER (ORDER BY AMOUNT DESC) = 1;')
        result = checked({'nested/ddl/source.sql': text})
        self.assertEqual(result['expressions'][0]['text'], text)
        self.assertEqual({o['name'] for o in result['objects'] if o['kind'] == 'relation'},
                         {'"D"."S"."Orders"', '"D"."S"."Ranked"'})
        self.assertTrue(next(o for o in result['objects'] if o['name'] == 'ID')['details']['primary_key_declared'])
        self.assertIn('"D"."S"."Orders"', [d['target'] for d in result['dependencies']])
        self.assertIn('Qualify', [e['details'].get('expression_kind') for e in result['expressions']])

    def test_cte_is_not_a_physical_source(self):
        result = checked({'query.sql': 'WITH c AS (SELECT ID FROM D.S.T) SELECT ID FROM c'})
        self.assertEqual([d['target'] for d in result['dependencies']], ['D.S.T'])

    def test_policy_placeholder_is_an_explicit_gap(self):
        text = 'CREATE TABLE D.S.T (EMAIL VARCHAR) WITH ROW ACCESS POLICY #UNKNOWN_POLICY ON (EMAIL);'
        result = checked({'policy.sql': text})
        self.assertIn('snowflake.security_sql_unverified', codes(result))
        self.assertEqual(result['expressions'][0]['text'], text)


if __name__ == '__main__':
    unittest.main()
