"""Independent lifecycle holdouts; imported declarations never become authority.

Uses the author's small synthetic setup, but supplies separate mutations and
expected boundaries. No native adapter run, credentials, or network is needed.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_contract
import omni_inventory
import omni_lifecycle as lifecycle
import test_omni_lifecycle as fixtures


@unittest.skipUnless(omni_contract.yaml is not None, 'Pinned YAML runtime required')
class IndependentLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.contract, self.before, self.after, self.observed = fixtures.fixture()
        _, self.files, self.context, self.target, self.remote = fixtures.inputs()

    def seal(self):
        fixtures.reseal(self.contract, self.before, self.after, self.observed)

    def assess(self):
        return lifecycle.assess_lifecycle(self.contract, self.before, self.after, self.observed)

    def request(self):
        return lifecycle.prepare_request(self.contract, self.before, self.after, self.observed)

    def verify(self, payload=None, **overrides):
        arguments = dict(files=self.files, context=self.context, target=self.target,
                         expected_remote=self.remote, operation=self.contract['operation'])
        arguments.update(overrides)
        return lifecycle.verify_request(self.request() if payload is None else payload, **arguments)

    def test_native_binding_drift_is_not_repaired_by_unchanged_local_assessment(self):
        original = copy.deepcopy((self.contract, self.before, self.after, self.observed))
        payload = self.request()
        self.assertEqual(self.verify(payload)['preflight_status'], 'passed')
        for name in ('files', 'context', 'target', 'expected_remote', 'operation'):
            if name == 'files':
                value = dict(self.files); value['fleet.view'] += '# A later candidate\n'
            elif name == 'context':
                value = copy.deepcopy(self.context); value['catalogue_sha256'] = '0' * 64
            elif name == 'target':
                value = dict(self.target); value['branch_id'] = fixtures.helpers.uid(41)
            elif name == 'expected_remote':
                value = dict(self.remote); value['schema_sha256'] = '0' * 64
            else:
                value = 'validate'
            with self.subTest(binding=name), self.assertRaisesRegex(
                    lifecycle.LifecycleError, '^lifecycle.native_binding_mismatch$'):
                self.verify(payload, **{name: value})
        self.assertEqual((self.contract, self.before, self.after, self.observed), original)

    def test_resealed_physical_omission_or_namespace_substitution_fails_actual_catalogue(self):
        original = copy.deepcopy(self.contract)
        for mutation in ('omit', 'namespace'):
            self.contract = copy.deepcopy(original)
            physical = self.contract['environment']['physical_resolution']
            if mutation == 'omit':
                physical.pop()
            else:
                physical[0]['namespace']['schema'] = 'UNREVIEWED'
            self.seal()
            # Imported declarations can be internally consistent while being
            # wrong for the selected native context. Test the second gate.
            self.assertEqual(self.assess()['preflight_status'], 'passed')
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                    lifecycle.LifecycleError, '^lifecycle.physical_catalogue_mismatch$'):
                self.verify()

    def test_resealed_principal_and_environment_changes_cannot_relabel_the_target(self):
        self.contract['cases'][0]['principal_id'] = fixtures.helpers.uid(42)
        self.seal()
        with self.assertRaisesRegex(lifecycle.LifecycleError, '^lifecycle.selected_principal_mismatch$'):
            self.verify()
        self.contract['cases'][0]['principal_id'] = self.target['principal_id']
        self.contract['environment']['environment_connection_id'] = fixtures.helpers.uid(43)
        self.seal()
        with self.assertRaisesRegex(lifecycle.LifecycleError, '^lifecycle.native_environment_mismatch$'):
            self.verify()

    def test_plan_execution_and_timezone_each_require_the_selected_exact_query_case(self):
        self.contract['operation'] = 'query'
        self.seal()
        query = {'modelId': self.target['model_id'], 'table': 'fleet', 'fields': ['fleet.journeys'], 'limit': 10}
        for mode in ('plan', 'execute'):
            self.assertEqual(self.verify(query=query, query_mode=mode, timezone='UTC')['status'], 'passed')
        changed = dict(query, limit=9)
        for overrides in (
                {'query': changed, 'query_mode': 'execute', 'timezone': 'UTC'},
                {'query': query, 'query_mode': 'execute', 'timezone': 'America/Chicago'}):
            with self.subTest(change=overrides), self.assertRaisesRegex(
                    lifecycle.LifecycleError, '^lifecycle.selected_query_case_missing$'):
                self.verify(**overrides)
        self.contract['cases'] = [case for case in self.contract['cases'] if case['lane'] != 'native_compilation']
        self.observed['cases'].pop('compile')
        self.seal()
        with self.assertRaisesRegex(lifecycle.LifecycleError, '^lifecycle.selected_query_case_missing$'):
            self.verify(query=query, query_mode='plan', timezone='UTC')

    def test_candidate_only_scan_cannot_erase_unknown_baseline_or_become_write_preflight(self):
        self.observed['baseline'] = None
        report = self.assess()
        self.assertEqual(report['status'], 'pending')
        self.assertEqual(report['preflight_status'], 'pending')
        self.assertEqual(report['lanes']['reference_scan']['status'], 'pending')
        with self.assertRaisesRegex(lifecycle.LifecycleError, '^lifecycle.preflight_not_passed$'):
            self.verify()

    def test_changed_issue_location_with_reused_fingerprint_is_new_failure(self):
        baseline = {'fingerprint_sha256': '8' * 64, 'node_ids': ['authored:view:other'],
                    'content_ids': [], 'severity': 'error'}
        self.observed['baseline']['issues'] = [baseline]
        self.observed['candidate']['issues'] = [dict(baseline, node_ids=['authored:topic:fleet'])]
        report = self.assess()
        self.assertEqual(report['status'], 'failed')
        self.assertIn('lifecycle.new_content_failure', {f['code'] for f in report['findings']})
        self.assertEqual(report['unrelated_baseline_issue_sha256'], [])

    def test_effective_only_change_propagates_to_effective_topic_without_changing_authored_hash(self):
        authored = lifecycle._files(self.before)
        effective = dict(authored)
        changed_effective = dict(effective)
        changed_effective['fleet.view'] += 'description: Synthetic inherited definition changed\n'
        self.before = omni_inventory.inspect_model(authored, effective_files=effective)
        self.after = omni_inventory.inspect_model(authored, effective_files=changed_effective)
        self.files = authored
        self.seal()
        report = self.assess()
        self.assertEqual(self.contract['bindings']['baseline_files_sha256'], self.contract['bindings']['candidate_files_sha256'])
        self.assertIn(omni_contract.canonical_hash('effective:topic:fleet'), report['affected_node_sha256'])
        self.assertIn(omni_contract.canonical_hash('effective:view:fleet/field:journeys'), report['affected_node_sha256'])
        self.assertIn(omni_contract.canonical_hash('authored:topic:fleet'), report['affected_node_sha256'])
        self.assertEqual(report['affected_content_sha256'], [omni_contract.canonical_hash('draft-a')])
        self.assertTrue(report['changed_nodes'])

    def test_observation_edit_and_assessment_edit_require_recomputing_the_exact_request(self):
        payload = self.request()
        payload['observations']['cases']['execute']['actual']['row_count'] = 7
        with self.assertRaisesRegex(lifecycle.LifecycleError, '^lifecycle.assessment_changed$'):
            self.verify(payload)
        report = lifecycle.assess_lifecycle(payload['contract'], payload['baseline_inventory'],
                                            payload['candidate_inventory'], payload['observations'])
        payload['assessment_sha256'] = report['assessment_sha256']
        with self.assertRaisesRegex(lifecycle.LifecycleError, '^lifecycle.preflight_not_passed$'):
            self.verify(payload)


class IndependentLifecycleBoundaryTests(unittest.TestCase):
    def test_nonjson_and_unhashable_values_fail_without_raw_values_or_authentication(self):
        for value in (None, [], {'operation': ['SYNTHETIC_PHI_CANARY']},
                      {'schema_version': float('nan')}, {'unexpected': '\ud800'}):
            with self.subTest(value_type=type(value).__name__):
                report = lifecycle.assess_lifecycle(value, None, None)
                self.assertEqual(report['status'], 'failed')
                self.assertNotIn('SYNTHETIC_PHI_CANARY', json.dumps(report))
                for flag in ('native_verified', 'security_verified', 'deployment_authorized',
                             'imported_evidence_authenticated'):
                    self.assertIs(report[flag], False)

    def test_cli_rejects_ancestor_symlink_without_writing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real = root / 'real'; real.mkdir()
            alias = root / 'alias'; alias.symlink_to(real, target_is_directory=True)
            source = real / 'request.json'
            source.write_text(json.dumps({'contract': {}, 'baseline_inventory': None,
                                          'candidate_inventory': None, 'observations': None}))
            source.chmod(0o600)
            for linked in ('input', 'output'):
                output = (alias if linked == 'output' else root) / ('report-' + linked + '.json')
                command = [sys.executable, str(Path(lifecycle.__file__)), '--request',
                           str(alias / source.name if linked == 'input' else source), '--output', str(output)]
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists(), (linked, result.stdout, result.stderr))
                self.assertNotIn(str(root), result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
