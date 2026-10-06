"""Independent offline access-contract attacks; no provider or raw data calls."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import security_capabilities as matrix
import security_contract as security
from ae_common import hash_json


def access_fixture():
    bindings = {name: (hex(index + 1)[2:] * 64) for index, name in enumerate(
        ('source', 'catalogue', 'candidate', 'target', 'policy', 'scope'))}
    destination = {'warehouse': 'snowflake', 'environment': 'development', 'identity': {
        'account': 'synthetic-account', 'database': 'ANALYTICS', 'omni_instance': 'https://synthetic.omni.invalid',
        'omni_model_id': 'synthetic-model', 'omni_connection_id': 'synthetic-connection', 'omni_branch_id': 'synthetic-branch'}}
    state = {'schema_version': 1, 'kind': 'security_state', 'bindings': bindings,
             'destination': destination, 'resources': []}
    for kind in ('warehouse', 'omni_topic', 'omni_document'):
        state['resources'].append({'id': kind + '.freight', 'kind': kind, 'namespace': {'object': 'synthetic.freight'},
            'principals': {'users': [], 'groups': ['reviewers']}, 'allowed_actions': sorted(security.REQUIRED_PATHS[kind]),
            'row_policy_sha256': 'a' * 64, 'metadata_visible': False,
            'inheritance': {'new_columns': 'deny', 'policy_sha256': 'b' * 64},
            'columns': {
                'total': {'classification': 'INTERNAL', 'mode': 'allow', 'policy_sha256': None,
                          'metadata_visible': False, 'inherited_from': []},
                'private_marker': {'classification': 'RESTRICTED', 'mode': 'mask', 'policy_sha256': 'c' * 64,
                          'metadata_visible': False, 'inherited_from': []},
                'unknown': {'classification': 'UNKNOWN', 'mode': 'deny', 'policy_sha256': 'd' * 64,
                          'metadata_visible': False, 'inherited_from': []}}})
    contract = {'schema_version': 1, 'kind': 'security_contract', 'migration_scope': 'full_dashboard',
        'bindings': bindings, 'warehouse': 'snowflake', 'framework': 'dbt', 'destination': destination,
        'current_sha256': security.state_hash(state), 'candidate_sha256': security.state_hash(state),
        'snapshot_sha256': 'e' * 64,
        'personas': {'reviewer': {'principal_id': 'synthetic-principal', 'groups': ['reviewers'],
            'attributes': {'region': 'f' * 64}, 'required_attributes': ['region'], 'unexpected_groups': ['unexpected']}},
        'cases': [], 'review': {}}
    for resource in state['resources']:
        for path in sorted(security.REQUIRED_PATHS[resource['kind']]):
            for scenario in ('positive', 'negative', 'missing_attribute', 'unexpected_group'):
                allowed = scenario == 'positive'
                case = {'id': 'case-' + str(len(contract['cases'])), 'resource_id': resource['id'],
                    'persona_id': 'reviewer', 'path': path, 'scenario': scenario, 'probe_sha256': hash_json([path, scenario]),
                    'expected': {'decision': 'masked' if allowed else 'deny', 'row_scope_sha256': '1' * 64 if allowed else None,
                        'columns': ['total', 'private_marker'] if allowed else [],
                        'masked_columns': ['private_marker'] if allowed else [], 'metadata_visible': False, 'canary_visible': False}}
                contract['cases'].append(case)
    current, candidate = copy.deepcopy(state), copy.deepcopy(state)
    readback = copy.deepcopy(state)
    renew(contract, current, candidate)
    return contract, current, candidate, readback, observations_for(contract, candidate)


def renew(contract, current, candidate):
    contract['current_sha256'] = security.state_hash(current)
    contract['candidate_sha256'] = security.state_hash(candidate)
    contract['review'] = {'status': 'approved', 'reference': 'synthetic-review', 'contract_sha256': security.review_hash(contract)}


def observations_for(contract, candidate):
    return {'schema_version': 1, 'kind': 'security_observations', 'contract_sha256': hash_json(contract),
        'state_sha256': security.state_hash(candidate), 'bindings': copy.deepcopy(contract['bindings']),
        'destination': copy.deepcopy(contract['destination']),
        'cases': {case['id']: {'context': security.expected_context(contract, case), 'result': copy.deepcopy(case['expected'])}
                  for case in contract['cases']}}


class IndependentSecurityCapabilityTests(unittest.TestCase):
    def test_every_supported_route_limits_qualification_to_offline_comparison(self):
        for warehouse in ('snowflake', 'databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck'):
            for framework in ('dbt', 'coalesce', 'native_sql'):
                with self.subTest(warehouse=warehouse, framework=framework):
                    item = matrix.capabilities(warehouse, framework)
                    self.assertTrue(item['documented'])
                    self.assertTrue(item['implemented'])
                    self.assertFalse(item['live_qualified'])
                    self.assertFalse(item['native_policy_writes'])
                    self.assertFalse(item['native_evidence_authenticated'])
                    self.assertIn('Offline', item['implementation_scope'])
                    self.assertTrue(item['official_sources'])
                    self.assertTrue(item['read_only_inspection_recipe'])

    def test_framework_aliases_do_not_upgrade_runtime_claims(self):
        for alias in ('dbt_core', 'dbt_platform'):
            item = matrix.capabilities('snowflake', alias)
            self.assertEqual(item['framework'], 'dbt')
            self.assertFalse(item['live_qualified'])

    def test_unknown_platform_or_framework_is_not_guessed(self):
        for warehouse, framework in [('unknown', 'dbt'), ('snowflake', 'unknown'), ('duckdb', 'native_sql')]:
            with self.assertRaises(ValueError): matrix.capabilities(warehouse, framework)

    def test_returned_capability_cannot_mutate_shared_vendor_requirements(self):
        original = matrix.capabilities('motherduck')
        modified = matrix.capabilities('motherduck')
        modified['vendor_documented_controls'].clear()
        modified['qualification_requirements'].clear()
        self.assertEqual(matrix.capabilities('motherduck'), original)


class IndependentSecurityContractTests(unittest.TestCase):
    def setUp(self): self.contract, self.current, self.candidate, self.readback, self.observed = access_fixture()

    def evaluate(self):
        return security.evaluate_access(self.contract, self.current, self.candidate, self.readback, self.observed)

    def reapprove(self):
        renew(self.contract, self.current, self.candidate)
        self.readback = copy.deepcopy(self.candidate)
        self.observed = observations_for(self.contract, self.candidate)

    def test_exact_imported_match_is_local_only_and_cannot_authorize_deployment(self):
        result = self.evaluate()
        self.assertEqual(result['status'], 'locally_consistent', result)
        for flag in ('native_verified', 'evidence_authenticated', 'live_qualified', 'protected_deployment_allowed', 'policy_writes_performed'):
            self.assertIs(result[flag], False)
        self.assertEqual(result['cases_compared'], 36)

    def test_incomplete_readback_or_observations_is_pending_never_accepted(self):
        self.assertEqual(security.evaluate_access(self.contract, self.current, self.candidate)['status'], 'pending')
        self.observed['cases'].pop(next(iter(self.observed['cases'])))
        self.assertEqual(self.evaluate()['status'], 'pending')

    def test_reapproved_policy_loosening_remains_blocked(self):
        mutations = [lambda r: r.update(row_policy_sha256=None),
                     lambda r: r.update(row_policy_sha256='2' * 64),
                     lambda r: r['principals']['groups'].append('broad-audience'),
                     lambda r: r.update(metadata_visible=True),
                     lambda r: r['columns']['private_marker'].update(mode='allow', policy_sha256=None),
                     lambda r: r['columns']['private_marker'].update(policy_sha256='2' * 64),
                     lambda r: r['columns']['private_marker'].update(classification='PUBLIC'),
                     lambda r: r['columns']['private_marker'].update(metadata_visible=True),
                     lambda r: r['inheritance'].update(policy_sha256='2' * 64)]
        for mutate in mutations:
            self.setUp(); mutate(self.candidate['resources'][0]); self.reapprove()
            with self.subTest(mutate=mutate): self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_restrictive_policy_change_still_needs_qualified_write_path(self):
        self.candidate['resources'][0]['columns']['unknown']['policy_sha256'] = '2' * 64
        self.reapprove()
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('security.policy_provisioning_unqualified', [f['code'] for f in result['findings']])

    def test_new_or_unclassified_column_cannot_default_to_visible_access(self):
        for mode, metadata in [('allow', False), ('deny', True)]:
            self.setUp()
            self.candidate['resources'][0]['columns']['new_field'] = {'classification': 'UNKNOWN' if mode == 'deny' else 'INTERNAL',
                'mode': mode, 'policy_sha256': '2' * 64 if mode == 'deny' else None, 'metadata_visible': metadata, 'inherited_from': []}
            self.reapprove()
            self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_existing_inheritance_cannot_disappear(self):
        self.current['resources'][1]['columns']['private_marker']['inherited_from'] = ['warehouse.freight']
        self.reapprove()
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('security.inherited_control_removed', [f['code'] for f in result['findings']])

    def test_imported_readback_must_match_exact_destination_namespace_and_state(self):
        for mutate in (lambda r: r['destination']['identity'].update(database='OTHER'),
                       lambda r: r['resources'][0]['namespace'].update(object='other'),
                       lambda r: r['resources'][0]['columns']['private_marker'].update(policy_sha256='2' * 64),
                       lambda r: r['bindings'].update(source='2' * 64)):
            self.setUp(); mutate(self.readback)
            self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_missing_negative_or_extra_scenario_cannot_be_reapproved_as_full_coverage(self):
        for scenario in ('negative', 'missing_attribute', 'unexpected_group'):
            self.setUp()
            self.contract['cases'] = [case for case in self.contract['cases'] if case['scenario'] != scenario]
            self.reapprove()
            self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_duplicate_scenario_and_omitted_resource_are_not_valid_coverage(self):
        self.contract['cases'].append(dict(self.contract['cases'][0], id='duplicate-probe'))
        self.reapprove()
        self.assertEqual(self.evaluate()['status'], 'blocked')
        self.setUp(); self.candidate['resources'].pop(); self.reapprove()
        self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_live_claims_extra_fields_and_raw_values_do_not_authenticate_imports(self):
        marker = 'SYNTHETIC_PHI_CANARY'
        for value in (True, marker):
            self.setUp(); self.observed['native_verified'] = value
            result = self.evaluate()
            self.assertEqual(result['status'], 'blocked')
            self.assertNotIn(marker, json.dumps(result))
            self.assertFalse(result['native_verified'])

    def test_persona_groups_attributes_probe_and_context_pins_cannot_be_substituted(self):
        mutations = [lambda c: c.update(principal_id='wrong-persona'), lambda c: c.update(groups=['broad-audience']),
                     lambda c: c.update(attributes={'region': '2' * 64}), lambda c: c.update(probe_sha256='2' * 64),
                     lambda c: c.update(snapshot_sha256='2' * 64), lambda c: c.update(destination_sha256='2' * 64)]
        for mutate in mutations:
            self.setUp(); mutate(self.observed['cases']['case-0']['context'])
            self.assertEqual(self.evaluate()['status'], 'failed')

    def test_extra_rows_unmasked_values_denied_metadata_and_visible_canary_fail(self):
        mutations = [lambda r: r.update(row_scope_sha256='2' * 64), lambda r: r.update(masked_columns=[]),
                     lambda r: r.update(metadata_visible=True), lambda r: r.update(canary_visible=True),
                     lambda r: r['columns'].append('unknown'), lambda r: r.update(raw_rows=['SYNTHETIC_PII_CANARY'])]
        for mutate in mutations:
            self.setUp(); mutate(self.observed['cases']['case-0']['result'])
            result = self.evaluate()
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('SYNTHETIC_PII_CANARY', json.dumps(result))

    def test_negative_scenario_cannot_claim_any_returned_columns(self):
        denied = next(case for case in self.contract['cases'] if case['scenario'] == 'negative')
        self.observed['cases'][denied['id']]['result']['columns'] = ['total']
        self.assertEqual(self.evaluate()['status'], 'failed')

    def test_resource_metadata_cannot_make_hidden_column_metadata_visible(self):
        for state in (self.current, self.candidate): state['resources'][0]['metadata_visible'] = True
        for case in self.contract['cases']:
            if case['resource_id'] == 'warehouse.freight' and case['path'] == 'warehouse_metadata' and case['scenario'] == 'positive':
                case['expected']['metadata_visible'] = True
        self.reapprove()
        self.assertEqual(self.evaluate()['status'], 'blocked')


if __name__ == '__main__': unittest.main()
