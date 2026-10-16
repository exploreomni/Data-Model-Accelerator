"""Independent synthetic Unity Catalog fixtures; no Databricks connection."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from source_adapters.databricks import CAPABILITY, parse
from source_adapters.registry import parse as registered_parse, validate


def checked(files):
    result = parse(files)
    validate(result, files)
    return result


def exported(value, path='exports/unity/tables/orders.json'):
    return checked({path: json.dumps(value)})


def codes(result):
    return {g['code'] for g in result['gaps']}


def table(**updates):
    return dict({'name': 'Orders', 'catalog_name': 'Analytics', 'schema_name': 'Sales',
                 'full_name': 'Analytics.Sales.Orders', 'table_type': 'MANAGED',
                 'table_id': 'table-native-1', 'comment': 'Authored order facts',
                 'data_source_format': 'DELTA', 'properties': {'delta.enableChangeDataFeed': 'true'},
                 'columns': [{'name': 'OrderId', 'type_name': 'LONG', 'type_text': 'bigint',
                              'type_json': '{"type":"long","nullable":false}',
                              'position': 0, 'nullable': False, 'comment': 'Source order key'},
                             {'name': 'Total', 'type_name': 'DECIMAL', 'type_text': 'decimal(12,2)',
                              'type_precision': 12, 'type_scale': 2, 'position': 1, 'nullable': True}]}, **updates)


class DatabricksMetadataTests(unittest.TestCase):
    def test_native_table_fields_and_evidence_are_preserved(self):
        value = table()
        result = exported(value)
        relation = next(o for o in result['objects'] if o['kind'] == 'relation')
        self.assertEqual(relation['name'], '`Analytics`.`Sales`.`Orders`')
        self.assertEqual(relation['native_id'], 'table-native-1')
        self.assertEqual(relation['details']['identity_components'], ['Analytics', 'Sales', 'Orders'])
        self.assertEqual(relation['details']['comment'], 'Authored order facts')
        self.assertEqual(relation['details']['raw_metadata'], value)
        fields = [o for o in result['objects'] if o['kind'] == 'column']
        self.assertEqual([o['name'] for o in fields], ['OrderId', 'Total'])
        self.assertEqual(fields[0]['details']['comment'], 'Source order key')
        self.assertFalse(fields[0]['details']['nullable'])
        self.assertEqual(fields[1]['details']['data_type'], 'decimal(12,2)')
        self.assertEqual(fields[1]['details']['raw_metadata']['type_scale'], 2)
        self.assertEqual(fields[0]['details']['parent_id'], relation['id'])
        self.assertEqual(fields[0]['evidence'], {'path': 'exports/unity/tables/orders.json',
            'locator': '$.columns[0]', 'sha256': hashlib.sha256(json.dumps(value).encode()).hexdigest()})
        self.assertEqual(result['export_completeness'], 'not_established')
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['native_validation'], 'not_run')

    def test_documented_constraints_masks_and_filters_are_declarations(self):
        value = table(row_filter={'function_name': 'Analytics.Security.region_filter',
                                 'input_column_names': ['Region']}, table_constraints=[
            {'primary_key_constraint': {'name': 'pk_orders', 'child_columns': ['OrderId'], 'rely': True}},
            {'foreign_key_constraint': {'name': 'fk_customer', 'child_columns': ['CustomerId'],
                'parent_table': 'Analytics.Sales.Customers', 'parent_columns': ['Id'], 'rely': False}}])
        value['columns'][1]['mask'] = {'function_name': 'Analytics.Security.mask_amount',
                                      'using_column_names': ['Region']}
        result = exported(value)
        dependencies = {(d['details']['kind'], d['target']) for d in result['dependencies']}
        self.assertEqual(dependencies, {('row_filter_function', 'Analytics.Security.region_filter'),
            ('column_mask_function', 'Analytics.Security.mask_amount'),
            ('foreign_key', 'Analytics.Sales.Customers')})
        self.assertTrue(all(d['details']['resolution'] == 'unresolved' for d in result['dependencies']))
        self.assertIn('databricks.effective_security_unverified', codes(result))
        self.assertIn('databricks.constraint_integrity_unverified', codes(result))
        self.assertEqual(len([e for e in result['expressions'] if e['details']['interpretation'] == 'declared_constraint']), 2)

    def test_list_omissions_pagination_and_empty_pages_are_visible(self):
        for value in [{'tables': [table()], 'next_page_token': 'opaque'},
                      {'tables': [], 'next_page_token': 'next'}, {'tables': []}]:
            with self.subTest(value=value):
                result = exported(value)
                self.assertIn('databricks.list_omissions', codes(result))
                self.assertIn('databricks.visibility_unverified', codes(result))
                if value.get('next_page_token'):
                    self.assertIn('databricks.pagination_incomplete', codes(result))
                self.assertEqual(result['source_files'][0]['status'], 'partial')
        self.assertIn('databricks.invalid_pagination', codes(exported({'tables': [], 'next_page_token': True})))

    def test_missing_namespace_is_not_inferred_from_path_or_full_name(self):
        value = table()
        del value['catalog_name']
        del value['schema_name']
        result = exported(value, 'Analytics/Sales/Orders.json')
        relation = result['objects'][0]
        self.assertEqual(relation['details']['identity_components'], [None, None, 'Orders'])
        self.assertEqual(relation['details']['full_name'], 'Analytics.Sales.Orders')
        self.assertIn('databricks.namespace_unresolved', codes(result))

    def test_components_case_dots_and_quotes_are_not_collapsed(self):
        rows = [table(catalog_name='A.B', schema_name='C', full_name='A.B.C.Orders', table_id='one'),
                table(catalog_name='A', schema_name='B.C', full_name='A.B.C.Orders', table_id='two'),
                table(catalog_name='a', full_name='a.Sales.Orders', table_id='three'),
                table(catalog_name='A`Q', full_name='A`Q.Sales.Orders', table_id='four')]
        result = exported({'tables': rows})
        names = [o['name'] for o in result['objects'] if o['kind'] == 'relation']
        self.assertEqual(len(set(names)), 4)
        self.assertIn('`A``Q`.`Sales`.`Orders`', names)
        self.assertNotIn('databricks.duplicate_identity', codes(result))

    def test_duplicate_snapshots_and_conflicting_native_ids_are_flagged(self):
        result = exported({'tables': [table(), table(), table(name='Other', full_name='Analytics.Sales.Other')]})
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'relation']), 3)
        self.assertIn('databricks.duplicate_identity', codes(result))
        self.assertIn('databricks.native_identity_conflict', codes(result))
        self.assertEqual(len({o['id'] for o in result['objects']}), len(result['objects']))

    def test_conflicting_full_name_and_malformed_identifiers_do_not_create_tables(self):
        for value in [table(full_name='Other.Sales.Orders'), table(name=None), table(table_id=1),
                      table(schema_name={}), table(catalog_name=''), table(table_type=False)]:
            with self.subTest(value=value):
                result = exported(value)
                self.assertFalse(result['objects'])
                self.assertTrue(result['gaps'])

    def test_browse_metadata_and_missing_definitions_are_not_complete(self):
        value = table(table_type='VIEW', browse_only=True)
        del value['columns']
        del value['table_id']
        result = exported(value)
        self.assertTrue({'databricks.browse_only_metadata', 'databricks.columns_missing',
                         'databricks.view_definition_missing', 'databricks.native_id_missing'} <= codes(result))
        self.assertEqual([o['kind'] for o in result['objects']], ['relation'])
        self.assertFalse(result['dependencies'])

    def test_runtime_and_unknown_metadata_remain_visible(self):
        value = table(table_type='STREAMING_TABLE', pipeline_id='pipeline-native', future_security={'new': 'x'})
        result = exported(value)
        self.assertIn('databricks.runtime_semantics_unresolved', codes(result))
        self.assertIn('databricks.unknown_fields', codes(result))
        self.assertEqual(result['objects'][0]['details']['raw_metadata']['future_security'], {'new': 'x'})
        result = exported(table(table_type='FUTURE_TABLE_KIND'))
        self.assertIn('databricks.unknown_table_type', codes(result))

    def test_bad_column_types_are_rejected_and_omitted_nullability_is_unknown(self):
        for changes in [{'name': None}, {'type_text': {}}, {'type_name': False}, {'position': True},
                        {'position': -1}, {'nullable': 'false'}, {'type_scale': True}, {'comment': {}}]:
            column = dict(table()['columns'][0], **changes)
            with self.subTest(column=column):
                result = exported(table(columns=[column]))
                self.assertFalse([o for o in result['objects'] if o['kind'] == 'column'])
                self.assertIn('databricks.invalid_column', codes(result))
        result = exported(table(columns=[{'name': 'x', 'type_name': 'STRING'}]))
        self.assertIsNone(next(o for o in result['objects'] if o['kind'] == 'column')['details']['nullable'])

    def test_malformed_policy_or_constraint_never_becomes_dependency(self):
        for policy in [[], {}, {'function_name': 42}, {'function_name': 'security.mask', 'input_column_names': False}]:
            with self.subTest(policy=policy):
                result = exported(table(row_filter=policy))
                self.assertIn('databricks.invalid_policy', codes(result))
                self.assertFalse(result['dependencies'])
        for constraint in [None, {}, {'foreign_key_constraint': {'name': 'fk', 'child_columns': 1}},
                           {'foreign_key_constraint': {'name': 'fk', 'child_columns': ['a'],
                               'parent_table': 'cat.schema.t', 'parent_columns': ['a', 'b']}},
                           {'primary_key_constraint': {'name': 'pk', 'child_columns': ['id'], 'rely': 1}}]:
            with self.subTest(constraint=constraint):
                result = exported(table(table_constraints=[constraint]))
                self.assertIn('databricks.invalid_constraint', codes(result))
                self.assertFalse(result['dependencies'])

    def test_deprecated_policy_arguments_survive_without_conversion(self):
        policy = {'function_name': 'security.filter', 'input_arguments': [{'column': 'region'}, {'constant': 'US'}]}
        result = exported(table(row_filter=policy))
        self.assertIn('databricks.deprecated_policy_arguments', codes(result))
        self.assertEqual(result['dependencies'][0]['details']['raw_metadata'], policy)

    def test_malformed_unknown_and_mixed_json_fail_closed(self):
        for text in ['{', '{"tables":[],"tables":[]}', '[NaN]', '[' * 60 + '0' + ']' * 60]:
            with self.subTest(text=text):
                result = checked({'bad.json': text})
                self.assertEqual(codes(result), {'databricks.invalid_json'})
                self.assertFalse(result['objects'])
        for value in [{}, [], {'tables': {}}, {'tables': [table()], 'name': 'wrapper'},
                      {'source': 'databricks', 'data': table()}, {'nbformat': 4, 'cells': []}]:
            with self.subTest(value=value):
                result = exported(value)
                self.assertFalse(result['objects'])
                self.assertTrue(result['gaps'])

    def test_optional_packages_are_not_needed_for_metadata(self):
        with patch.dict(sys.modules, {'sqlglot': None, 'yaml': None, 'databricks': None, 'pyspark': None}):
            result = exported(table())
        self.assertEqual(len(result['objects']), 3)
        self.assertNotIn('sql.parser_dependency_missing', codes(result))

    def test_missing_sql_parser_preserves_view_source_and_gap(self):
        sql = 'SELECT OrderId FROM Analytics.Sales.Orders'
        with patch.dict(sys.modules, {'sqlglot': None}):
            result = exported(table(table_type='VIEW', view_definition=sql))
        self.assertIn('sql.parser_dependency_missing', codes(result))
        self.assertIn(sql, [e['text'] for e in result['expressions']])
        self.assertFalse(result['dependencies'])

    def test_code_and_bundle_files_are_preserved_without_execution_or_attribution(self):
        files = {'src/notebook.py': 'raise RuntimeError("must never run")',
                 'databricks.yml': 'bundle:\n  name: example\nresources: {}',
                 'other/notebook.ipynb': '{"cells": []}'}
        result = checked(files)
        self.assertFalse(result['objects'])
        self.assertFalse(result['execution_performed'])
        self.assertTrue(all(v['status'] == 'unsupported' for v in result['source_files']))
        self.assertEqual({e['text'] for e in result['expressions']}, set(files.values()))

    def test_dynamic_procedural_notebook_sql_stays_opaque(self):
        for text in ['EXECUTE IMMEDIATE statement;', 'SELECT * FROM IDENTIFIER( "name" );',
                     'SELECT * FROM ${catalog}.sales.orders;', 'BEGIN SELECT 1; END;',
                     '-- Databricks notebook source\nSELECT * FROM Analytics.Sales.Orders;',
                     '%python\nprint("unexecuted")']:
            with self.subTest(text=text):
                result = checked({'src/source.sql': text})
                self.assertFalse(result['objects'])
                self.assertFalse(result['dependencies'])
                self.assertEqual(result['expressions'][0]['text'], text)
                self.assertIn('databricks.dynamic_or_notebook_sql', codes(result))

    def test_registry_capability_and_evidence_contract(self):
        files = {'nested/source.json': json.dumps(table())}
        result = registered_parse('databricks', files)
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')
        self.assertEqual(len(result['component_sha256']), 64)
        for mutate in [lambda r: r.update(execution_performed=True),
                       lambda r: r['source_files'].clear(),
                       lambda r: r['objects'][0]['evidence'].update(sha256='0' * 64),
                       lambda r: r['source_files'][0].update(status='parsed')]:
            changed = copy.deepcopy(result)
            mutate(changed)
            with self.assertRaises(ValueError):
                validate(changed, files)

    def test_unsafe_paths_and_collisions_are_rejected(self):
        for files in [{'../source.sql': ''}, {'a.sql': '', 'A.sql': ''}, {'x': '', 'x/y.sql': ''}]:
            with self.subTest(files=files):
                with self.assertRaises(ValueError):
                    parse(files)


@unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'optional sqlglot parser not installed')
class DatabricksSQLTests(unittest.TestCase):
    def test_databricks_ddl_and_cte_reads(self):
        text = ('CREATE TABLE Analytics.Sales.Orders (id BIGINT, total DECIMAL(12,2)) USING DELTA;\n'
                'CREATE VIEW Analytics.Sales.Recent AS WITH c AS '
                '(SELECT id, total FROM Analytics.Sales.Orders) SELECT id, total FROM c WHERE total > 0;')
        result = checked({'sql/nested/models.sql': text})
        self.assertEqual(result['expressions'][0]['text'], text)
        relations = [o for o in result['objects'] if o['kind'] == 'relation']
        self.assertEqual({o['name'] for o in relations}, {'Analytics.Sales.Orders', 'Analytics.Sales.Recent'})
        self.assertEqual({d['target'] for d in result['dependencies']}, {'Analytics.Sales.Orders'})
        self.assertEqual(next(o for o in result['objects'] if o['name'] == 'total')['details']['data_type'], 'DECIMAL(12, 2)')

    def test_view_definition_is_owned_by_native_relation_and_keeps_namespace_unresolved(self):
        sql = 'SELECT OrderId, Total FROM source_orders WHERE Total > 0'
        result = exported(table(table_type='VIEW', view_definition=sql,
                                view_dependencies={'dependencies': [{'table': {'table_full_name': 'source_orders'}}]}))
        relation = next(o for o in result['objects'] if o['kind'] == 'relation')
        self.assertEqual([d['target'] for d in result['dependencies']], ['source_orders'])
        self.assertEqual(result['dependencies'][0]['source_id'], relation['id'])
        self.assertEqual(result['dependencies'][0]['details']['resolution'], 'unresolved')
        self.assertIn('databricks.view_dependency_metadata_unresolved', codes(result))
        self.assertEqual(next(e for e in result['expressions'] if e['text'] == sql)['object_id'], relation['id'])

    def test_streaming_security_and_parser_failures_remain_gaps(self):
        for sql, expected in [('CREATE STREAMING TABLE silver.orders AS SELECT * FROM STREAM(bronze.orders);',
                              'databricks.runtime_semantics_unresolved'),
                             ('GRANT SELECT ON TABLE Analytics.Sales.Orders TO analyst;',
                              'databricks.effective_security_unverified'),
                             ('SELECT ( FROM source_orders', 'sql.parse_error')]:
            with self.subTest(sql=sql):
                result = checked({'source.sql': sql})
                self.assertIn(expected, codes(result))
                self.assertEqual(result['expressions'][0]['text'], sql)


if __name__ == '__main__':
    unittest.main()
