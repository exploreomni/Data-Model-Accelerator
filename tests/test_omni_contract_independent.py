"""Independent synthetic fleet/energy contract cases; never native evidence.

Expected behavior follows the public Omni timeframes, week_start_day, format,
catalog and extends docs. In particular Excel formats and inherited overrides
are valid; omitted catalogs need verified default connection context.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_contract
from omni_contract import check_model


def context(warehouse='snowflake'):
    namespace = ({'project': 'fleet-project', 'dataset': 'gold', 'table': 'dispatches'}
                 if warehouse == 'bigquery' else {'database': 'FLEET', 'schema': 'GOLD', 'table': 'DISPATCHES'})
    columns = {'dispatch_id': 'number', 'dispatched_at': 'timestamp', 'completion_ratio': 'number'}
    if warehouse == 'snowflake':
        columns = {key.upper(): value for key, value in columns.items()}
    return {'schema_version': 1, 'kind': 'omni_model_context', 'warehouse': warehouse,
            'environment': 'independent-test-development', 'catalogue_sha256': 'c' * 64,
            'bindings': {'dispatches': {'namespace': namespace,
                'columns': columns,
                'evidence_sha256': 'd' * 64}},
            'inherited_views': {}, 'default_catalog': None, 'user_attributes': [], 'access_grants': []}


def files():
    return {'model': 'week_start_day: Monday\n',
            'dispatches.view': '''catalog: FLEET
schema: GOLD
table_name: DISPATCHES
dimensions:
  dispatch_id:
    sql: dispatch_id
    primary_key: true
  dispatched_at:
    sql: dispatched_at
    timeframes: [date, week, month]
    week_start_day: Monday
  completion_ratio:
    sql: completion_ratio
    format: "0.0%"
''',
            'dispatches.topic': '''base_view: dispatches
fields:
  - dispatches.dispatch_id
  - dispatches.dispatched_at[month]
  - dispatches.completion_ratio
'''}


@unittest.skipUnless(omni_contract.yaml is not None and omni_contract.sqlglot is not None,
                     'Optional PyYAML and sqlglot are required; execute in the pinned full runtime')
class OmniContractIndependentTests(unittest.TestCase):
    def result(self, value=None, binding=None):
        return check_model(files() if value is None else value, context() if binding is None else binding)

    def assert_failed(self, result):
        self.assertEqual(result['status'], 'failed', result)
        self.assertFalse(result['native_verified'])

    def test_valid_block_temporal_reference_and_custom_percent_format(self):
        result = self.result()
        self.assertEqual(result['status'], 'passed', result)
        self.assertFalse(result['native_verified'])

    def test_unknown_timeframe_is_invalid(self):
        candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace('[date, week, month]', '[date, time, month]')
        self.assert_failed(self.result(candidate))

    def test_documented_uppercase_timeframes_are_not_false_rejected(self):
        candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace('[date, week, month]', '[DATE, WEEK, MONTH]')
        result = self.result(candidate)
        self.assertEqual(result['status'], 'passed', result)

    def test_title_case_weekday_valid_lowercase_invalid(self):
        for day in ('Monday', 'Sunday', 'Thursday'):
            candidate = files(); candidate['model'] = 'week_start_day: ' + day + '\n'
            candidate['dispatches.view'] = candidate['dispatches.view'].replace('Monday', day)
            self.assertEqual(self.result(candidate)['status'], 'passed')
        candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace('Monday', 'monday')
        self.assert_failed(self.result(candidate))

    def test_quoted_flow_temporal_reference_passes_but_unquoted_flow_fails_yaml(self):
        candidate = files(); candidate['dispatches.topic'] = 'base_view: dispatches\nfields: ["dispatches.dispatched_at[month]"]\n'
        self.assertEqual(self.result(candidate)['status'], 'passed')
        candidate['dispatches.topic'] = 'base_view: dispatches\nfields: [dispatches.dispatched_at[month]]\n'
        self.assert_failed(self.result(candidate))

    def test_new_unbound_dimension_cannot_omit_sql(self):
        candidate = files(); candidate['dispatches.view'] += '  computed_dispatch_identifier:\n    label: Derived identifier\n'
        self.assertNotEqual(self.result(candidate)['status'], 'passed')

    def test_existing_schema_dimension_override_can_omit_sql(self):
        definition = {'catalog': 'FLEET', 'schema': 'GOLD', 'table_name': 'DISPATCHES',
                      'dimensions': {'dispatch_id': {'sql': 'dispatch_id'}}}
        digest = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        binding = context(); binding['inherited_views']['dispatches'] = {'definition': definition, 'sha256': digest}
        candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace('    sql: dispatch_id\n', '')
        result = self.result(candidate, binding)
        self.assertEqual(result['status'], 'passed', result)

    def test_inherited_definition_hash_mismatch_cannot_authorize_missing_sql(self):
        binding = context(); binding['inherited_views']['dispatches'] = {'definition': {'dimensions': {'dispatch_id': {'sql': 'dispatch_id'}}}, 'sha256': '0' * 64}
        candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace('    sql: dispatch_id\n', '')
        self.assertNotEqual(self.result(candidate, binding)['status'], 'passed')

    def test_catalog_omission_requires_verified_matching_default(self):
        candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace('catalog: FLEET\n', '')
        self.assertNotEqual(self.result(candidate)['status'], 'passed')
        binding = context(); binding['default_catalog'] = {'value': 'FLEET', 'verified': True, 'evidence_sha256': 'e' * 64}
        self.assertEqual(self.result(candidate, binding)['status'], 'passed')
        binding['default_catalog']['verified'] = False
        self.assertNotEqual(self.result(candidate, binding)['status'], 'passed')
        binding['default_catalog'].update(verified=True, value='WRONG')
        self.assertNotEqual(self.result(candidate, binding)['status'], 'passed')

    def test_bigquery_project_dataset_binding_and_verified_default(self):
        candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace('catalog: FLEET', 'catalog: fleet-project').replace('schema: GOLD', 'schema: gold').replace('table_name: DISPATCHES', 'table_name: dispatches')
        binding = context('bigquery')
        self.assertEqual(self.result(candidate, binding)['status'], 'passed')
        candidate['dispatches.view'] = candidate['dispatches.view'].replace('catalog: fleet-project\n', '')
        self.assertNotEqual(self.result(candidate, binding)['status'], 'passed')
        binding['default_catalog'] = {'value': 'fleet-project', 'verified': True, 'evidence_sha256': 'e' * 64}
        self.assertEqual(self.result(candidate, binding)['status'], 'passed')

    def test_qualified_field_and_topic_base_references_must_resolve(self):
        candidate = files(); candidate['dispatches.topic'] = 'base_view: dispatches\nfields:\n  - dispatches.missing\n'
        self.assert_failed(self.result(candidate))
        candidate['dispatches.topic'] = 'base_view: invented\n'
        self.assert_failed(self.result(candidate))

    def test_unsupported_temporal_suffix_is_not_a_real_field(self):
        candidate = files(); candidate['dispatches.topic'] = 'base_view: dispatches\nfields:\n  - dispatches.dispatched_at[time]\n'
        self.assert_failed(self.result(candidate))

    def test_same_view_sql_cycle_is_rejected(self):
        candidate = files(); candidate['dispatches.view'] += '''  distance_a:
    sql: ${distance_b}
  distance_b:
    sql: ${distance_a}
'''
        self.assert_failed(self.result(candidate))

    def test_dangling_sql_reference_cannot_pass(self):
        candidate = files(); candidate['dispatches.view'] += '''  impossible:
    sql: ${dispatches.not_present}
'''
        self.assert_failed(self.result(candidate))

    def test_view_inheritance_cycle_is_rejected(self):
        candidate = files()
        candidate['base.view'] = 'extends: [dispatches]\n' + candidate['dispatches.view']
        candidate['dispatches.view'] = 'extends: [base]\n' + candidate['dispatches.view']
        binding = context(); binding['bindings']['base'] = copy.deepcopy(binding['bindings']['dispatches'])
        self.assert_failed(self.result(candidate, binding))

    def test_unknown_physical_column_cannot_pass_verified_catalogue_binding(self):
        candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace('sql: dispatch_id', 'sql: absent_physical_column')
        self.assertNotEqual(self.result(candidate)['status'], 'passed')

    def test_quoted_snowflake_column_case_is_preserved(self):
        candidate = files(); binding = context()
        binding['bindings']['dispatches']['columns']['dispatch_id'] = binding['bindings']['dispatches']['columns'].pop('DISPATCH_ID')
        candidate['dispatches.view'] = candidate['dispatches.view'].replace('sql: dispatch_id', 'sql: \'"dispatch_id"\'')
        self.assertEqual(self.result(candidate, binding)['status'], 'passed')
        candidate['dispatches.view'] = candidate['dispatches.view'].replace('sql: \'"dispatch_id"\'', 'sql: \'"DISPATCH_ID"\'')
        self.assertNotEqual(self.result(candidate, binding)['status'], 'passed')

    def test_numeric_catalogue_field_cannot_gain_temporal_type_from_configuration(self):
        for property in ('timeframes: [month]', 'week_start_day: Monday'):
            with self.subTest(property=property):
                candidate = files(); candidate['dispatches.view'] += '    ' + property + '\n'
                self.assertNotEqual(self.result(candidate)['status'], 'passed')

    def test_unknown_parameter_is_unsupported_not_silently_accepted(self):
        candidate = files(); candidate['dispatches.view'] += 'unexpected_parameter: true\n'
        self.assertEqual(self.result(candidate)['status'], 'unsupported')

    def test_duplicate_yaml_key_is_rejected(self):
        candidate = files(); candidate['dispatches.view'] += 'catalog: ANOTHER\n'
        self.assert_failed(self.result(candidate))

    def test_malformed_parameter_shapes_return_report_instead_of_crashing(self):
        mutations = [
            ('week_start_day: Monday', 'week_start_day: [Monday]'),
            ('timeframes: [date, week, month]', 'timeframes: [{month: true}]'),
            ('format: "0.0%"', 'format: ["0.0%"]'),
            ('catalog: FLEET', 'catalog: [FLEET]'),
            ('primary_key: true', 'primary_key: "yes"')]
        for old, new in mutations:
            with self.subTest(parameter=old):
                candidate = files(); candidate['dispatches.view'] = candidate['dispatches.view'].replace(old, new)
                self.assertNotEqual(self.result(candidate)['status'], 'passed')

    def test_report_is_deterministic_and_does_not_echo_sql_expressions(self):
        candidate = files(); candidate['dispatches.view'] += '  broken:\n    sql: ${dispatches.not_present} /* PRIVATE_EXPRESSION_MARKER */\n'
        original = copy.deepcopy(candidate)
        first = self.result(candidate); second = self.result(candidate)
        self.assertEqual(first, second); self.assertEqual(candidate, original)
        self.assertNotIn('PRIVATE_EXPRESSION_MARKER', json.dumps(first))


if __name__ == '__main__':
    unittest.main()
