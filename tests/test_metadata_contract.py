"""Metadata projections must preserve exact bindings and explicit unknowns."""
import copy
import unittest
import test_data_dictionary_v2 as fixtures
from data_dictionary_v2 import migrate_dictionary
from metadata_contract import build_contract, verify_contract
from metadata_platforms import capabilities
from test_metadata_intake import OPTIONS
from test_privacy_contract import approved_classification, approved_policy


def dictionary(approved=True):
    value = migrate_dictionary(fixtures.canonical())
    for model in value['models']:
        for item in [model] + model['columns']:
            if approved:
                item['review_status'] = 'approved'
                item['provenance']['review_reference'] = 'synthetic-review:1'
                item['provenance']['evidence'] = [{'reference': 'synthetic-evidence', 'sha256': 'a'*64}]
        for column in model['columns']:
            if approved:
                column.update(sensitivity='INTERNAL', sensitivity_review_status='approved',
                              sensitivity_review_reference='synthetic-review:1',
                              sensitivity_evidence=[{'reference': 'synthetic-classification', 'sha256': 'b'*64}],
                              privacy=approved_classification())
    return value


def configuration(warehouse='snowflake', framework='dbt'):
    namespace = ['fixture_db', 'gold'] if warehouse != 'clickhouse' else ['fixture_db']
    return {'schema_version': 1, 'kind': 'metadata_configuration', 'warehouse': warehouse,
            'framework': framework, 'environment': 'development',
            'target': {'id': 'fixture-target', 'identity': {'account': 'synthetic', 'principal': 'fixture'}},
            'candidate_sha256': 'c'*64, 'catalogue_sha256': 'b'*64,
            'disclosure_policy': approved_policy(),
            'metadata_policy': copy.deepcopy(OPTIONS), 'resources': [{
                'resource_id': 'fixture.fact_customer', 'resource_type': 'model', 'layer': 'gold',
                'relation': {'namespace': namespace, 'name': 'fact_customer', 'kind': 'table'},
                'disposition': 'required', 'reason': None, 'columns': {'customer_id': 'CustomerId'},
                'source_write_decision': None, 'tags': [], 'column_tags': {}}]}


class MetadataContractTests(unittest.TestCase):
    def test_all_warehouse_comments_and_explicit_coalesce_matrix(self):
        for warehouse in ('snowflake', 'databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck'):
            for framework in ('dbt', 'native_sql', 'coalesce'):
                config = configuration(warehouse, framework)
                if framework == 'coalesce' and warehouse in ('redshift', 'clickhouse', 'motherduck'):
                    with self.assertRaises(ValueError):
                        build_contract(dictionary(), config)
                else:
                    contract = build_contract(dictionary(), config)
                    self.assertEqual(contract['blockers'], [])
                    self.assertEqual(verify_contract(contract), contract)
                    self.assertFalse(contract['capabilities']['native_qualified'])

    def test_unknown_definitions_are_reported_not_approved(self):
        contract = build_contract(dictionary(False), configuration())
        self.assertTrue(any('model definition requires review' in b for b in contract['blockers']))
        self.assertTrue(any('column definition requires review' in b for b in contract['blockers']))
        self.assertTrue(any('sensitivity requires review' in b for b in contract['blockers']))
        self.assertTrue(any('metadata disclosure blocked' in b for b in contract['blockers']))
        self.assertEqual(contract['resources'][0]['columns'][0]['sensitivity'], 'UNKNOWN')

    def test_source_writes_require_scope_decision_and_exact_lineage(self):
        config = configuration()
        config['resources'][0]['resource_type'] = 'source'
        with self.assertRaisesRegex(ValueError, 'Resource type differs'):
            build_contract(dictionary(), config)

    def test_missing_column_mapping_is_not_inferred(self):
        config = configuration()
        config['resources'][0]['columns'] = {}
        with self.assertRaisesRegex(ValueError, 'Exact column mapping'):
            build_contract(dictionary(), config)

    def test_units_cannot_turn_placeholder_into_complete_documentation(self):
        for description in ('TBD','TODO','UNKNOWN','TBD.'):
            value=dictionary();value['models'][0]['columns'][0].update(description=description,units='USD')
            self.assertTrue(build_contract(value,configuration())['blockers'])

    def test_contract_tamper_fails_even_when_resealed(self):
        from ae_common import hash_json
        value = build_contract(dictionary(), configuration())
        value['resources'][0]['description'] = 'Forged replacement'
        value['contract_sha256'] = hash_json({k: v for k,v in value.items() if k != 'contract_sha256'})
        with self.assertRaisesRegex(ValueError, 'canonical projection'):
            verify_contract(value)

    def test_unsupported_object_is_a_visible_blocker(self):
        config = configuration('redshift')
        config['resources'][0]['relation']['kind'] = 'late_binding_view'
        self.assertTrue(build_contract(dictionary(), config)['blockers'])

    def test_explicit_exclusion_remains_in_scope(self):
        config = configuration()
        config['resources'][0].update(disposition='documented_only', reason='Read-only source')
        self.assertEqual(len(build_contract(dictionary(False), config)['resources']), 1)

    def test_comments_only_unknown_and_missing_disclosure_policy_block_publication(self):
        config = configuration()
        self.assertEqual(config['metadata_policy']['mode'], 'comments')
        config.pop('disclosure_policy')
        self.assertTrue(any('disclosure blocked' in v for v in build_contract(dictionary(), config)['blockers']))
        value = dictionary(); column = value['models'][0]['columns'][0]
        column.update(sensitivity='UNKNOWN', sensitivity_review_status='unresolved',
                      sensitivity_review_reference=None, sensitivity_evidence=[])
        column.pop('privacy')
        self.assertTrue(any('sensitivity requires review' in v for v in build_contract(value, configuration())['blockers']))

    def test_sensitive_description_is_blocked_without_echoing_value(self):
        value = dictionary()
        value['models'][0]['columns'][0]['description'] = 'Contact fictional-person@example.invalid'
        result = build_contract(value, configuration())
        self.assertTrue(any('scan.not_clear' in v for v in result['blockers']))
        self.assertNotIn('fictional-person', str(result['blockers']))


if __name__ == '__main__':
    unittest.main()
