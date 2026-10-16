"""Regression journeys for additive checks, never new approval authority."""
import copy
from unittest.mock import patch
import unittest

import test_engagement_stages as fixtures
from ae_common import hash_file
stages, guided = fixtures.stages, fixtures.guided
import authoring_quality as quality


class AuthoringQualityTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.h.action('approve-design', entities=['customers'], document={
            'schema_version': 1, 'kind': 'human_design_review', 'decision': 'approve',
            'reviewer': 'Synthetic reviewer', 'review_reference': 'synthetic://human',
            'bindings': stages.review_bindings(self.h.state, ['customers'])})
        self.h.plan(self.h.tasks())

    def record(self, supplied=None, run_id='authoring-1', execution=None):
        plan = self.h.plan()
        task = next(t for t in plan['tasks'] if t['id'] == 'build-customers')
        (self.h.artifacts / 'customers.sql').write_text('select count(1) as customers_id from customers')
        request = {'task_id': 'build-customers', 'run_id': run_id,
                   'plan_sha256': plan['plan_sha256'], 'fingerprint': task['fingerprint'],
                   'outputs': stages._output_hashes(self.h.artifacts, ['customers.sql']),
                   'evidence_reference': 'synthetic://host/run'}
        if supplied is not None: request['authoring_contract'] = supplied
        if execution is not None: request['execution'] = execution
        self.h.action('record-task', artifact_root=self.h.artifacts, document=request)

    def check(self, identity='recheck-1', contract=None):
        request = {'schema_version': 1, 'task_id': 'build-customers', 'observation_id': identity}
        if contract is not None: request['contract'] = contract
        self.h.action('check-task', artifact_root=self.h.artifacts, document=request)

    def test_legacy_record_gets_honest_unknowns_without_changing_approval(self):
        self.record(run_id='r' * 200)
        view = stages.public_view(self.h.state)
        self.assertNotEqual(view['authoring_checks'][0]['status'], 'passed')
        self.assertFalse(self.h.state['readiness']['execution_authorized'])
        self.assertEqual(stages.approved_entities(self.h.state), {'customers'})
        self.assertEqual(next(t['action'] for t in self.h.plan()['tasks'] if t['id'] == 'build-customers'), 'reuse')

    def test_recheck_retains_original_run_and_file_bytes(self):
        self.record()
        runs = copy.deepcopy(self.h.state['workflow']['runs'])
        outputs = stages._output_hashes(self.h.artifacts, ['customers.sql'])
        self.check()
        self.assertEqual(runs, self.h.state['workflow']['runs'])
        self.assertEqual(outputs, stages._output_hashes(self.h.artifacts, ['customers.sql']))
        self.assertEqual(len(self.h.state['workflow']['authoring_observations']), 2)
        self.assertEqual(quality.summaries(self.h.state)[0]['run_id'], 'authoring-1')

    def test_recheck_cannot_relabel_unapproved_context_as_reviewed(self):
        self.record()
        self.h.state['workflow']['approvals'] = []
        observation = quality.recheck_task(self.h.state, self.h.artifacts,
            {'schema_version': 1, 'task_id': 'build-customers', 'observation_id': 'unapproved-check'})
        self.assertEqual(observation['receipt']['mode'], 'provisional')

    def test_changed_code_rejected_and_old_receipt_stale(self):
        self.record()
        (self.h.artifacts / 'customers.sql').write_text('select 2 as customers_id')
        self.assertEqual(quality.summaries(self.h.state)[0]['status'], 'stale')
        with self.assertRaisesRegex(ValueError, 'changed authoring'):
            self.check()

    def test_checker_target_and_contract_changes_invalidate_observation(self):
        self.record()
        with patch.object(quality, 'checker_version', return_value='0' * 64):
            self.assertEqual(quality.summaries(self.h.state)[0]['status'], 'stale')
        changed = copy.deepcopy(self.h.state); changed['answers']['warehouse'] = 'bigquery'
        self.assertEqual(quality.summaries(changed)[0]['status'], 'stale')
        changed = copy.deepcopy(self.h.state)
        changed['workflow']['authoring_observations'][0]['contract']['models'][0]['columns'] = []
        self.assertEqual(quality.summaries(changed)[0]['status'], 'stale')

    def test_unmapped_legacy_engagement_can_recheck_without_new_run(self):
        self.record()
        del self.h.state['workflow']['authoring_observations']
        self.assertEqual(quality.summaries(self.h.state), [])
        before = copy.deepcopy(self.h.state['workflow']['runs'])
        quality.recheck_task(self.h.state, self.h.artifacts,
                            {'schema_version': 1, 'task_id': 'build-customers', 'observation_id': 'upgrade-check'})
        self.assertEqual(before, self.h.state['workflow']['runs'])
        self.assertNotEqual(quality.summaries(self.h.state)[0]['status'], 'passed')

    def test_task_removal_or_redefinition_cannot_keep_fresh_observation(self):
        self.record()
        changed = copy.deepcopy(self.h.state)
        changed['workflow']['tasks'][0]['outputs'] = ['replacement.sql']
        self.assertEqual(quality.summaries(changed)[0]['status'], 'stale')
        changed['workflow']['tasks'] = []
        self.assertEqual(quality.summaries(changed)[0]['status'], 'stale')

    def test_diagnostic_version_change_reuses_code_with_original_run(self):
        self.record()
        versions = stages.component_versions()
        versions['authoring_checks'] = '1' * 64
        versions['execution_observations'] = '2' * 64
        with patch.object(stages, 'component_versions', return_value=versions):
            task = next(t for t in stages.plan_tasks(self.h.state, self.h.artifacts)['tasks'] if t['id'] == 'build-customers')
        self.assertEqual(task['action'], 'reuse')
        self.assertEqual(task['original_run_id'], 'authoring-1')

    def test_contract_cannot_redefine_design_or_claim_other_task_path(self):
        task = self.h.state['workflow']['tasks'][0]
        contract = quality.default_contract(self.h.state, task, 'reviewed_candidate')
        contract['models'][0]['path'] = 'orders.sql'
        with self.assertRaisesRegex(ValueError, 'ownership'): self.record(contract)
        self.assertEqual(self.h.state['workflow']['runs'], [])
        contract['models'][0].update(path='customers.sql', columns=['invented'])
        with self.assertRaisesRegex(ValueError, 'pinned design'): self.record(contract)

    def test_context_receipt_binds_task_and_preserves_unknown_model(self):
        import test_agent_context as context_fixture
        context = context_fixture.AgentContextTests()
        context.setUp(); self.addCleanup(context.doCleanups)
        plan = self.h.plan()
        context.request['task_id'] = 'build-customers'
        context.request['bindings']['task_fingerprint'] = next(t['fingerprint'] for t in plan['tasks'] if t['id'] == 'build-customers')
        receipt = context.build()
        packet_dir = context.root / 'packet'
        request = {'schema_version': 1, 'kind': 'agent_execution_request', 'task_id': 'build-customers',
                   'run_id': 'authoring-1', 'packet_sha256': receipt['packet_sha256'],
                   'source_context_receipt_sha256': hash_file(packet_dir / 'CONTEXT_RECEIPT.json'),
                   'requested_model': 'configured-default', 'observed_model': None,
                   'requested_effort': None, 'observed_effort': None, 'context_mode': 'unknown',
                   'host_run_reference': None}
        self.record(execution={'packet_dir': str(packet_dir), 'request': request})
        observation = self.h.state['workflow']['runs'][0]['execution_observation']
        self.assertIsNone(observation['observed_model'])
        self.assertEqual(observation['requested_model'], 'configured-default')
        self.assertFalse(observation['model_identity_verified'])


if __name__ == '__main__': unittest.main()
