"""Independent synthetic assertions for the documented Domo export subset."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from source_adapters.domo import CAPABILITY, MAX_ACTIONS, parse
from source_adapters.registry import validate


def dataset():
    return {'id': 'sales-source', 'name': 'Sales',
            'schema': {'columns': [{'name': 'region', 'type': 'STRING'},
                                   {'name': 'revenue', 'type': 'DECIMAL'}]},
            'pdpEnabled': True,
            'policies': [{'id': 41, 'name': 'West viewers', 'type': 'user',
                          'users': [17], 'groups': [23],
                          'filters': [{'column': 'region', 'operator': 'EQUALS',
                                       'values': ['West'], 'not': False}]}]}


def beast():
    return {'id': 72, 'name': 'Net sales', 'legacyId': 'calculation_test',
            'expression': 'SUM(`revenue`) - SUM(`refund`)', 'aggregated': True,
            'links': [{'resource': {'type': 'DATA_SOURCE', 'id': 'sales-source'},
                       'active': False, 'visible': True, 'valid': 'VALID'}]}


def clipboard():
    return {'contentType': 'domo/dataflow-actions', 'data': [
        {'id': 'load', 'name': 'Sales', 'type': 'LoadFromVault', 'dependsOn': [],
         'dataSourceId': 'sales-source', 'onlyLoadNewVersions': False},
        {'id': 'calc', 'name': 'Gross amount', 'type': 'ExpressionEvaluator',
         'dependsOn': ['load'], 'expressions': [
             {'fieldName': 'gross', 'expression': '`revenue` * 1.2', 'settings': None}]},
        {'id': 'filter', 'name': 'Keep positive', 'type': 'Filter', 'dependsOn': ['calc'],
         'filterList': [{'leftField': 'gross', 'operator': 'GT', 'rightExpr': '0',
                         'andFilterList': []}]},
        {'id': 'output', 'name': 'Prepared sales', 'type': 'PublishToVault',
         'dependsOn': ['filter'], 'dataSource': {'guid': 'prepared-sales', 'type': 'DataFlow'},
         'versionChainType': 'REPLACE', 'partitionIdColumns': []}]}


def encoded(**values):
    return {name + '.json': json.dumps(value) for name, value in values.items()}


class DomoTests(unittest.TestCase):
    def codes(self, report):
        return {gap['code'] for gap in report['gaps']}

    def test_dataset_columns_pdp_and_exact_original(self):
        files = encoded(dataset=dataset())
        result = parse(files)
        validate(result, files)
        root = next(o for o in result['objects'] if o['kind'] == 'dataset')
        self.assertEqual((root['native_id'], root['name']), ('sales-source', 'Sales'))
        self.assertEqual([(o['name'], o['details']['data_type']) for o in result['objects'] if o['kind'] == 'column'],
                         [('region', 'STRING'), ('revenue', 'DECIMAL')])
        policy = next(o for o in result['objects'] if o['kind'] == 'pdp_policy')
        self.assertEqual(policy['native_id'], '41')
        self.assertEqual(policy['details']['native_definition']['groups'], [23])
        self.assertEqual(policy['details']['native_definition']['users'], [17])
        predicate = next(e for e in result['expressions'] if e['language'] == 'domo:pdp_filter')
        self.assertEqual(json.loads(predicate['text']), {'column': 'region', 'operator': 'EQUALS', 'values': ['West'], 'not': False})
        self.assertEqual(policy['details']['effective_access'], 'not_established')
        self.assertEqual(result['expressions'][0]['text'], files['dataset.json'])
        self.assertIn('domo.effective_access_unverified', self.codes(result))
        self.assertEqual(result['source_files'][0]['status'], 'partial')

    def test_beast_formula_and_declared_inactive_link_preserved(self):
        result = parse(encoded(dataset=dataset(), beast=beast()))
        expression = next(e for e in result['expressions'] if e['language'] == 'domo:beast_mode')
        self.assertEqual(expression['text'], 'SUM(`revenue`) - SUM(`refund`)')
        edge = next(e for e in result['dependencies'] if e['details']['kind'] == 'beast_mode_link')
        target = next(o['id'] for o in result['objects'] if o['kind'] == 'dataset')
        self.assertEqual(edge['target'], target)
        self.assertEqual(edge['details']['resolution'], 'declared')
        self.assertFalse(edge['details']['native_link']['active'])
        self.assertFalse(any(e['language'] == 'mysql' for e in result['expressions']))

    def test_magic_graph_formula_filter_and_dataset_lineage(self):
        files = encoded(dataset=dataset(), magic=clipboard())
        result = parse(files)
        validate(result, files)
        actions = {o['native_id']: o for o in result['objects'] if o['kind'] == 'etl_action'}
        self.assertEqual(set(actions), {'load', 'calc', 'filter', 'output'})
        expected = {(actions['calc']['id'], actions['load']['id']),
                    (actions['filter']['id'], actions['calc']['id']),
                    (actions['output']['id'], actions['filter']['id'])}
        actual = {(e['source_id'], e['target']) for e in result['dependencies'] if e['details']['kind'] == 'depends_on'}
        self.assertEqual(actual, expected)
        expr = next(e for e in result['expressions'] if e['language'] == 'domo:magic_etl_formula')
        self.assertEqual((expr['object_id'], expr['text'], expr['details']['output_name']),
                         (actions['calc']['id'], '`revenue` * 1.2', 'gross'))
        predicate = actions['filter']['details']['native_definition']['filterList'][0]
        self.assertEqual(predicate, {'leftField': 'gross', 'operator': 'GT', 'rightExpr': '0', 'andFilterList': []})
        output = next(e for e in result['dependencies'] if e['details']['kind'] == 'writes_to')
        self.assertEqual(output['target'], 'dataset:prepared-sales')
        self.assertEqual(actions['output']['details']['native_definition']['versionChainType'], 'REPLACE')
        self.assertIn('domo.clipboard_scope_partial', self.codes(result))

    def test_unknown_action_and_fields_are_retained_with_gaps(self):
        value = clipboard()
        value['data'][1]['type'] = 'FutureModelAction'
        value['data'][1]['script'] = 'raise RuntimeError("must not execute")'
        value['data'][0]['futureOption'] = {'filter': 'retain'}
        result = parse(encoded(magic=value))
        self.assertTrue({'domo.unknown_action', 'domo.opaque_fields'} <= self.codes(result))
        unknown = next(o for o in result['objects'] if o['native_id'] == 'calc')
        self.assertEqual(unknown['details']['native_definition']['script'], 'raise RuntimeError("must not execute")')
        self.assertEqual(len([e for e in result['dependencies'] if e['details']['kind'] == 'depends_on']), 3)

    def test_duplicates_and_missing_action_targets_do_not_bind(self):
        value = clipboard()
        value['data'].append(copy.deepcopy(value['data'][0]))
        value['data'][2]['dependsOn'] = ['absent']
        result = parse(encoded(magic=value))
        self.assertIn('domo.duplicate_action_id', self.codes(result))
        edges = {e['details'].get('native_reference'): e for e in result['dependencies'] if e['details']['kind'] == 'depends_on'}
        self.assertEqual(edges['load']['details']['resolution'], 'unresolved')
        self.assertEqual(edges['absent']['target'], 'action:absent')

    def test_cycles_are_explicit(self):
        value = clipboard()
        value['data'][0]['dependsOn'] = ['output']
        self.assertIn('domo.action_cycle', self.codes(parse(encoded(magic=value))))

    def test_empty_input_and_empty_export_never_prove_completeness(self):
        self.assertEqual(parse({})['objects'], [])
        for value in ({}, [], {'contentType': 'domo/dataflow-actions', 'data': []},
                      {'results': [], 'totalHits': 0, 'hasMore': False, 'degraded': False}):
            result = parse(encoded(empty=value))
            self.assertTrue({'domo.empty_export', 'domo.empty_actions'} & self.codes(result))
            self.assertEqual(result['export_completeness'], 'not_established')
            self.assertNotEqual(result['source_files'][0]['status'], 'parsed')

    def test_search_metadata_is_not_formula_or_complete_inventory(self):
        metadata = beast()
        del metadata['expression']
        result = parse(encoded(search={'results': [metadata], 'totalHits': 80, 'hasMore': True, 'degraded': True}))
        self.assertTrue({'domo.formula_missing', 'domo.pagination_unverified', 'domo.more_pages', 'domo.degraded_search'} <= self.codes(result))
        self.assertEqual([e for e in result['expressions'] if e['language'] == 'domo:beast_mode'], [])

    def test_malformed_json_and_ambiguous_keys_fail_closed(self):
        for text in ('{"schema":', '{"schema":{},"schema":{}}', '{"schema":NaN}'):
            with self.subTest(text=text):
                result = parse({'bad.json': text})
                self.assertEqual(result['objects'], [])
                self.assertIn('domo.invalid_json', self.codes(result))
                self.assertEqual(result['expressions'][0]['text'], text)

    def test_malformed_shapes_do_not_throw_or_infer(self):
        bad = dataset()
        bad.update(id=True, schema={'columns': 'incorrect'}, policies='incorrect', pdpEnabled='true')
        result = parse(encoded(bad=bad))
        self.assertTrue({'domo.native_id_missing', 'domo.invalid_columns', 'domo.policies_missing_or_invalid', 'domo.pdp_state_missing'} <= self.codes(result))
        self.assertEqual(next(o for o in result['objects'] if o['kind'] == 'dataset')['native_id'], None)
        for mutation, expected in (({'dependsOn': 'load'}, 'domo.invalid_action_dependencies'),
                                   ({'dependsOn': [{}]}, 'domo.invalid_action_dependency'),
                                   ({'expressions': [{'fieldName': 'gross', 'expression': 2}]}, 'domo.invalid_formula')):
            value = clipboard()
            value['data'][1].update(mutation)
            self.assertIn(expected, self.codes(parse(encoded(magic=value))))

    def test_pdp_enabled_with_no_policies_and_invalid_filters(self):
        value = dataset()
        value['policies'] = []
        self.assertIn('domo.enabled_pdp_without_policies', self.codes(parse(encoded(dataset=value))))
        value = dataset()
        value['policies'][0]['filters'][0]['values'] = 'West'
        value['policies'][0]['users'] = {'17': True}
        result = parse(encoded(dataset=value))
        self.assertTrue({'domo.invalid_pdp_filter', 'domo.invalid_policy_principals'} <= self.codes(result))

    def test_non_string_policy_and_resource_types_are_gaps(self):
        source, formula = dataset(), beast()
        source['policies'][0]['type'] = {'unexpected': 'mapping'}
        formula['links'][0]['resource']['type'] = ['DATA_SOURCE']
        result = parse(encoded(dataset=source, beast=formula))
        self.assertTrue({'domo.unknown_policy_type', 'domo.unknown_link_type'} <= self.codes(result))

    def test_unknown_types_and_columns_and_opaque_nested_fields(self):
        value = dataset()
        value['schema']['columns'].append({'name': 'revenue', 'type': 'FUTURE', 'formula': 'opaque'})
        value['policies'][0]['futureRule'] = {'operator': 'unknown'}
        result = parse(encoded(dataset=value))
        self.assertTrue({'domo.duplicate_column', 'domo.unknown_data_type', 'domo.opaque_fields'} <= self.codes(result))

    def test_duplicate_dataset_ids_make_cross_file_links_ambiguous(self):
        result = parse(encoded(first=dataset(), second=dataset(), beast=beast()))
        self.assertIn('domo.duplicate_native_id', self.codes(result))
        edge = next(e for e in result['dependencies'] if e['details']['kind'] == 'beast_mode_link')
        self.assertEqual((edge['target'], edge['details']['resolution']), ('dataset:sales-source', 'unresolved'))

    def test_limits_do_not_partially_interpret_oversized_graph(self):
        value = {'contentType': 'domo/dataflow-actions', 'data':
                 [{'id': str(i), 'name': 'Input', 'type': 'LoadFromVault', 'dependsOn': [], 'dataSourceId': 'source'} for i in range(MAX_ACTIONS + 1)]}
        result = parse(encoded(magic=value))
        self.assertIn('domo.graph_limit', self.codes(result))
        self.assertFalse(any(o['kind'] == 'etl_action' for o in result['objects']))

    def test_no_guessing_other_domo_api_or_custom_envelopes(self):
        files = encoded(card={'id': 2, 'title': 'Card', 'dataSetId': 'sales-source'},
                        dataflow={'id': 9, 'actions': clipboard()['data']},
                        custom={'datasets': [dataset()], 'sql': 'SELECT 1'})
        result = parse(files)
        self.assertEqual(result['objects'], [])
        self.assertTrue(all(f['status'] == 'unsupported' for f in result['source_files']))
        self.assertIn('domo.unsupported_shape', self.codes(result))

    def test_determinism_and_no_network_or_execution(self):
        files = encoded(dataset=dataset(), beast=beast(), magic=clipboard())
        with patch('subprocess.run', side_effect=AssertionError('execution forbidden')), patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            result = parse(files)
            self.assertEqual(result, parse(dict(reversed(list(files.items())))))
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')


if __name__ == '__main__':
    unittest.main()
