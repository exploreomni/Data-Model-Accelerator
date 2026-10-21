"""PM reuse pins upstream inputs and registered results across the first lifecycle."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import migration_planning as planning
import run_control
import legacy_alignment
import test_migration_planning as fixtures
from test_legacy_alignment import mapping


class PlanningReuseTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.MigrationPlanningTests(); self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.h.enable(); self.state = self.h.state
        self.artifacts = self.h.fixture.root / 'outputs'; self.artifacts.mkdir()
        self.output = self.artifacts / 'planning-result.txt'; self.output.write_text('Synthetic proposed plan result.')

    def claim(self, attempt='pm-1', state=None):
        return run_control.claim_work(state or self.state, {'schema_version': 1, 'work_id': 'plan-commerce',
            'attempt_id': attempt, 'role': 'migration_project_manager', 'scope_ids': ['commerce'], 'source_paths': []})

    def checkpoint(self, status='outputs_recorded', state=None):
        return run_control.checkpoint_work(state or self.state, {'schema_version': 1, 'attempt_id': 'pm-1',
            'status': status, 'reason': 'Synthetic scoped proposal checkpoint', 'outputs': [self.output.name]}, self.artifacts)

    def complete(self):
        self.assertEqual(self.claim()['action'], 'dispatch')
        self.h.save(fixtures.plan())
        self.checkpoint()

    def test_first_configure_claim_register_checkpoint_reuses_without_redrafting(self):
        before = planning.work_input_binding(self.state, 'commerce')
        self.complete()
        self.assertEqual(before, planning.work_input_binding(self.state, 'commerce'))
        self.assertIn('planning_result_binding', self.state['operations']['attempts'][0])
        self.assertEqual(self.claim('pm-2')['action'], 'reuse')
        self.assertEqual(self.state['workflow']['approvals'], [])

    def test_changed_upstream_cannot_be_blessed_by_registration_or_checkpoint(self):
        self.claim()
        (self.h.source / 'orders.sql').write_text('select 999 as orders_id')
        self.h.save(fixtures.plan())  # Registration must not rewrite the claim's input identity.
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'PM inputs changed'): self.checkpoint()
        self.assertEqual(before, self.state)
        self.assertEqual(self.checkpoint('interrupted')['status'], 'interrupted')
        self.assertEqual(self.claim('pm-2')['action'], 'dispatch')

    def test_completed_work_needs_registered_plan_but_interruption_does_not(self):
        self.claim()
        with self.assertRaisesRegex(ValueError, 'Register the retained'): self.checkpoint()
        self.assertEqual(self.checkpoint('interrupted')['status'], 'interrupted')
        result = self.claim('pm-2')
        self.assertEqual(result['action'], 'dispatch'); self.assertEqual(result['resumes_attempt_id'], 'pm-1')

    def test_model_alignment_config_and_human_edits_invalidate_reuse(self):
        self.complete(); original = copy.deepcopy(self.state)
        def model(): self.state['workflow']['design']['entities'][1]['grain'] = 'Changed order grain'
        def alignment():
            request = mapping(); request['mappings'][0]['rationale'] = 'Changed mapping definition'
            legacy_alignment.register_alignment(self.state, request, self.h.run)
        def config(): planning.configure(self.state, dict(fixtures.config(), output_format='local'))
        def human(): planning.edit_items(self.state, {'schema_version': 1, 'domain_id': 'commerce',
            'plan_sha256': planning.domain_snapshot(self.state, 'commerce')['plan_sha256'],
            'request_reference': 'synthetic://human/edit', 'edits': [{'id': 'req.orders', 'notes': 'New human requirement.'}]}, self.h.run)
        for mutate in (model, alignment, config, human):
            self.state.clear(); self.state.update(copy.deepcopy(original)); mutate()
            with self.subTest(mutation=mutate.__name__): self.assertEqual(self.claim('pm-2')['action'], 'dispatch')

    def test_changed_retained_plan_and_output_bytes_invalidate_even_when_inputs_match(self):
        self.complete(); original = copy.deepcopy(self.state)
        inputs = planning.work_input_binding(self.state, 'commerce')
        request = fixtures.plan(); request['narrative'] = 'A different retained result.'
        self.h.save(request)
        self.assertEqual(inputs, planning.work_input_binding(self.state, 'commerce'))
        self.assertEqual(self.claim('pm-2')['action'], 'dispatch')
        self.state.clear(); self.state.update(original)
        self.output.write_text('Changed actual result bytes')
        self.assertEqual(self.claim('pm-2')['action'], 'dispatch')

    def test_unrelated_model_change_preserves_reuse_and_tampered_plan_does_not(self):
        self.complete()
        self.state['workflow']['design']['entities'][2]['grain'] = 'Unrelated product change'
        self.assertEqual(self.claim('pm-2')['action'], 'reuse')
        ref = self.state['workflow']['migration_planning']['plans']['commerce']
        Path(ref['path']).write_text('{}')
        self.assertEqual(self.claim('pm-3')['action'], 'dispatch')

    def test_predesign_discovery_source_bytes_are_inputs_without_a_repository_scan(self):
        self.state['workflow']['design'] = None
        self.state['workflow'].pop('legacy_alignment')
        self.state['workflow']['domain_journey'] = {'active_domain_id': 'commerce', 'domains': [
            {'id': 'commerce', 'name': 'Commerce', 'source_paths': ['orders.sql'], 'asset_ids': [], 'shared_dependency_ids': []}]}
        self.claim()
        self.h.save({'schema_version': 1, 'domain_id': 'commerce', 'consumers': [], 'work_items': []})
        (self.h.source / 'orders.sql').write_text('changed retained discovery source')
        with self.assertRaisesRegex(ValueError, 'PM inputs changed'): self.checkpoint()


if __name__ == '__main__': unittest.main()
