"""Independent synthetic Redshift source expectations; never access a cluster."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from source_adapters.redshift import CAPABILITY, parse
from source_adapters.registry import validate


def checked(files):
    result = parse(files)
    validate(result, files)
    return result


def exported(value, path='snapshots/nested/catalogue.json'):
    return checked({path: json.dumps(value)})


def codes(result):
    return {g['code'] for g in result['gaps']}


def svv(**updates):
    return dict({'table_catalog': 'Analytics', 'table_schema': 'Sales', 'table_name': 'Orders',
                 'column_name': 'OrderId', 'ordinal_position': 1, 'data_type': 'bigint',
                 'is_nullable': 'NO', 'column_default': '0', 'remarks': 'Source order key',
                 'numeric_precision': 64, 'numeric_scale': 0}, **updates)


def api_column(**updates):
    return dict({'name': 'OrderId', 'typeName': 'int8', 'schemaName': 'Sales', 'tableName': 'Orders',
                 'nullable': 0, 'isSigned': True, 'precision': 19, 'columnDefault': '0'}, **updates)


class RedshiftMetadataTests(unittest.TestCase):
    def test_capability_is_offline(self):
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')

    def test_svv_preserves_database_column_comments_defaults_and_evidence(self):
        rows = [svv(), svv(column_name='Total', ordinal_position=2, data_type='numeric',
                           numeric_precision=12, numeric_scale=2, is_nullable='YES', column_default=None)]
        path = 'exports/nested/schema/columns.json'
        result = exported(rows, path)
        relation = next(o for o in result['objects'] if o['kind'] == 'relation')
        self.assertEqual(relation['name'], '"Analytics"."Sales"."Orders"')
        fields = [o for o in result['objects'] if o['kind'] == 'column']
        self.assertEqual([o['name'] for o in fields], ['OrderId', 'Total'])
        self.assertEqual(fields[0]['details']['comment'], 'Source order key')
        self.assertEqual(fields[0]['details']['parent_id'], relation['id'])
        self.assertFalse(fields[0]['details']['nullable'])
        self.assertTrue(fields[1]['details']['nullable'])
        self.assertEqual(fields[1]['details']['raw_metadata']['numeric_scale'], 2)
        self.assertEqual(fields[0]['evidence'], {'path': path, 'locator': '$[0]',
            'sha256': hashlib.sha256(json.dumps(rows).encode()).hexdigest()})
        self.assertIn('0', [e['text'] for e in result['expressions']])
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')

    def test_describe_uses_documented_column_namespace_and_keeps_database_unknown(self):
        result = exported({'TableName': 'Orders', 'ColumnList': [api_column()]})
        relation = next(o for o in result['objects'] if o['kind'] == 'relation')
        field = next(o for o in result['objects'] if o['kind'] == 'column')
        self.assertEqual(relation['name'], '"Sales"."Orders"')
        self.assertEqual(relation['details']['identity_components'], [None, 'Sales', 'Orders'])
        self.assertIsNone(relation['details']['database'])
        self.assertEqual(field['details']['nullable_code'], 0)
        self.assertIn('redshift.database_identity_missing', codes(result))

    def test_describe_can_use_response_table_name_but_never_filename_schema(self):
        col = api_column()
        del col['tableName']
        result = exported({'TableName': 'Orders', 'ColumnList': [col]})
        self.assertTrue(any(o['kind'] == 'column' for o in result['objects']))
        del col['schemaName']
        result = exported({'TableName': 'Orders', 'ColumnList': [col]}, 'Analytics/Sales/Orders.json')
        self.assertFalse(result['objects'])
        self.assertIn('redshift.missing_identity', codes(result))

    def test_list_tables_preserves_type_without_inventing_columns(self):
        result = exported({'Tables': [{'schema': 'Sales', 'name': 'Recent', 'type': 'VIEW'}]})
        self.assertEqual([o['kind'] for o in result['objects']], ['relation'])
        self.assertEqual(result['objects'][0]['details']['table_type'], 'VIEW')
        self.assertIn('redshift.definition_missing', codes(result))
        self.assertFalse(result['dependencies'])

    def test_query_result_columns_never_become_physical_definitions(self):
        value = {'ColumnMetadata': [api_column()], 'Records': [[{'longValue': 42}]], 'TotalNumRows': 1}
        result = exported(value)
        self.assertEqual({o['kind'] for o in result['objects']}, {'result_set', 'result_column'})
        self.assertFalse(result['dependencies'])
        self.assertIn('redshift.query_result_not_catalogue', codes(result))
        self.assertEqual(result['expressions'][0]['text'], json.dumps(value))

    def test_result_rows_with_catalogue_names_are_still_results(self):
        value = {'ColumnMetadata': [{'name': k, 'typeName': 'varchar'} for k in svv()],
                 'Records': [[{'stringValue': str(v)} for v in svv().values()]], 'TotalNumRows': 1}
        result = exported(value)
        self.assertFalse([o for o in result['objects'] if o['kind'] in ('relation', 'column')])

    def test_result_field_union_types_and_width_are_checked(self):
        for field in [{}, {'isNull': False}, {'longValue': True}, {'stringValue': 3},
                      {'unknownValue': 'x'}, {'isNull': True, 'stringValue': 'x'}]:
            with self.subTest(field=field):
                result = exported({'ColumnMetadata': [api_column()], 'Records': [[field]], 'TotalNumRows': 1})
                self.assertIn('redshift.invalid_result_field', codes(result))
        result = exported({'ColumnMetadata': [api_column()], 'Records': [[]], 'TotalNumRows': 1})
        self.assertIn('redshift.invalid_result_row', codes(result))

    def test_result_all_supported_tagged_fields_preserved(self):
        fields = [{'longValue': 42}, {'doubleValue': 2.5}, {'stringValue': 'v'},
                  {'blobValue': 'YQ=='}, {'booleanValue': True}, {'isNull': True}]
        value = {'ColumnMetadata': [api_column(name='c' + str(i)) for i in range(len(fields))],
                 'Records': [fields], 'TotalNumRows': 1}
        self.assertNotIn('redshift.invalid_result_field', codes(exported(value)))

    def test_pagination_count_mismatch_and_missing_total_are_visible(self):
        value = {'ColumnMetadata': [api_column()], 'Records': [[{'longValue': 1}]],
                 'TotalNumRows': 2, 'NextToken': 'opaque'}
        result = exported(value)
        self.assertIn('redshift.pagination_incomplete', codes(result))
        self.assertIn('redshift.row_count_mismatch', codes(result))
        del value['TotalNumRows']
        self.assertIn('redshift.row_count_missing', codes(exported(value)))
        for v in [{'Tables': [], 'NextToken': 1}, {'ColumnList': [], 'NextToken': 'next'}]:
            self.assertTrue(exported(v)['gaps'])

    def test_unknown_security_metadata_survives_with_gap(self):
        row = svv(masking_policy='secure_mask', security_owner='role_a')
        result = exported([row])
        column = next(o for o in result['objects'] if o['kind'] == 'column')
        self.assertEqual(column['details']['raw_metadata']['masking_policy'], 'secure_mask')
        self.assertIn('redshift.unknown_fields', codes(result))
        self.assertEqual(result['source_files'][0]['status'], 'partial')

    def test_component_identity_dots_quotes_and_case_do_not_collide(self):
        result = exported([svv(table_catalog='D.S', table_schema='X'),
                           svv(table_catalog='D', table_schema='S.X'),
                           svv(table_catalog='d', table_schema='S.X'),
                           svv(table_catalog='D"Q')])
        names = [o['name'] for o in result['objects'] if o['kind'] == 'relation']
        self.assertEqual(len(set(names)), 4)
        self.assertIn('"D""Q"."Sales"."Orders"', names)

    def test_duplicate_snapshots_are_retained_and_flagged(self):
        result = exported([svv(), svv()])
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'column']), 2)
        self.assertIn('redshift.duplicate_identity', codes(result))

    def test_bad_columns_and_conflicting_response_identity_fail_closed(self):
        for col in [api_column(name=None), api_column(typeName={}), api_column(nullable=True),
                    api_column(isSigned=1), api_column(tableName='Different')]:
            with self.subTest(col=col):
                self.assertFalse(exported({'TableName': 'Orders', 'ColumnList': [col]})['objects'])
        for row in [svv(table_catalog=None), svv(ordinal_position=True), svv(is_nullable='maybe'),
                    svv(remarks={}), svv(data_type=False), svv(column_default=3),
                    svv(numeric_precision={}), svv(numeric_scale=True)]:
            with self.subTest(row=row):
                self.assertFalse(exported([row])['objects'])

    def test_invalid_and_mixed_api_containers_do_not_create_definitions(self):
        for value in [{}, {'ColumnList': {}}, {'Tables': False}, {'ColumnMetadata': []},
                      {'ColumnList': [api_column()], 'Tables': []}, {'Tables': [{'name': 'x'}]},
                      {'ColumnMetadata': [], 'Records': [], 'TotalNumRows': True}]:
            with self.subTest(value=value):
                result = exported(value)
                self.assertFalse(result['objects'])
                self.assertTrue(result['gaps'])

    def test_malformed_duplicate_key_nonfinite_deep_json(self):
        for text in ['{', '{"Tables":[],"Tables":[]}', '[NaN]', '[' * 60 + '0' + ']' * 60]:
            with self.subTest(text=text):
                result = checked({'bad.json': text})
                self.assertEqual(codes(result), {'redshift.invalid_json'})
                self.assertFalse(result['objects'])

    def test_procedural_external_and_unknown_files_are_not_executed(self):
        for text, code in [('CREATE PROCEDURE p() AS $$ BEGIN SELECT * FROM private.t; END $$ LANGUAGE plpgsql;',
                            'redshift.procedural_or_dynamic_sql'),
                           ("UNLOAD ('SELECT * FROM private.t') TO 's3://bucket/path';", 'redshift.external_behavior_unresolved'),
                           ('CREATE EXTERNAL TABLE ext.t (id int);', 'redshift.external_behavior_unresolved')]:
            with self.subTest(text=text):
                result = checked({'nested/source.sql': text})
                self.assertEqual(result['expressions'][0]['text'], text)
                self.assertFalse(result['objects'])
                self.assertFalse(result['dependencies'])
                self.assertIn(code, codes(result))
        result = checked({'nested/executable.py': 'raise RuntimeError("not executed")'})
        self.assertEqual(result['source_files'][0]['status'], 'unsupported')

    def test_missing_optional_parser_is_an_explicit_gap(self):
        with patch.dict(sys.modules, {'sqlglot': None}):
            result = checked({'nested/query.sql': 'SELECT id FROM sales.orders'})
        self.assertIn('sql.parser_dependency_missing', codes(result))

    def test_unsafe_paths_rejected(self):
        for files in [{'../ddl.sql': ''}, {'a.sql': '', 'A.sql': ''}, {'x': '', 'x/y.sql': ''}]:
            with self.subTest(files=files):
                with self.assertRaises(ValueError):
                    parse(files)

    def test_registry_rejects_loss_and_forged_evidence(self):
        files = {'nested/columns.json': json.dumps([svv()])}
        result = checked(files)
        for mutation in [lambda r: r['source_files'].clear(),
                         lambda r: r['objects'][0]['evidence'].update(sha256='0' * 64),
                         lambda r: r.update(execution_performed=True),
                         lambda r: r['source_files'][0].update(status='parsed')]:
            changed = copy.deepcopy(result)
            mutation(changed)
            with self.assertRaises(ValueError):
                validate(changed, files)


@unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'optional sqlglot parser not installed')
class RedshiftSQLTests(unittest.TestCase):
    def test_redshift_ddl_keeps_keys_distribution_types_and_read_dependencies(self):
        text = ('CREATE TABLE sales.orders (id BIGINT PRIMARY KEY, customer_id BIGINT, amount DECIMAL(12,2), '
                'FOREIGN KEY (customer_id) REFERENCES sales.customers(id)) DISTSTYLE KEY DISTKEY(id) SORTKEY(id);\n'
                'CREATE VIEW sales.ranked AS SELECT id, amount FROM sales.orders '
                'QUALIFY ROW_NUMBER() OVER (ORDER BY amount DESC) = 1;')
        result = checked({'nested/ddl.sql': text})
        self.assertEqual(result['expressions'][0]['text'], text)
        relations = [o for o in result['objects'] if o['kind'] == 'relation']
        self.assertEqual({o['name'] for o in relations}, {'sales.orders', 'sales.ranked'})
        self.assertIn('DISTKEY', relations[0]['details']['properties'])
        self.assertTrue(next(o for o in result['objects'] if o['name'] == 'id')['details']['primary_key_declared'])
        self.assertEqual({d['target'] for d in result['dependencies']}, {'sales.orders', 'sales.customers'})
        self.assertIn('redshift.key_integrity_unverified', codes(result))

    def test_cte_is_not_physical_and_security_source_stays_unverified(self):
        result = checked({'query.sql': 'WITH c AS (SELECT id FROM sales.orders) SELECT id FROM c',
                          'security.sql': 'GRANT SELECT ON sales.orders TO reporting;'})
        self.assertEqual([d['target'] for d in result['dependencies']], ['sales.orders'])
        self.assertIn('redshift.effective_security_unverified', codes(result))
        self.assertIn('GRANT SELECT ON sales.orders TO reporting;', [e['text'] for e in result['expressions']])

    def test_sql_comments_are_preserved_without_claiming_catalogue_descriptions(self):
        text = "COMMENT ON TABLE sales.orders IS 'Order facts';"
        result = checked({'comments.sql': text})
        self.assertEqual(result['expressions'][0]['text'], text)
        self.assertIn('sql.unsupported_statement', codes(result))


if __name__ == '__main__':
    unittest.main()
