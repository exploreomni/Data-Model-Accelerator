"""Optional planning integrated with saved stages, work reuse and private exports."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import engagement_stages as stages
import guided_workflow as guided
import migration_plan_tools as tools
import migration_planning as planning
import run_control
import test_engagement_stages as stage_fixture
import test_legacy_alignment as legacy_fixture
import test_migration_planning as planning_fixture


class PlanningWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = stage_fixture.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.source_bytes = {p.name: p.read_bytes() for p in self.h.repo.iterdir()}

    def record(self):
        h = self.h
        h.action('configure-legacy-comparison', document=legacy_fixture.config())
        baseline = legacy_fixture.baseline()
        baseline['tables'] = baseline['tables'][:1]
        h.action('record-legacy-baseline', document=baseline)
        h.action('record-legacy-alignment', document=legacy_fixture.mapping())
        h.action('configure-migration-planning', document=planning_fixture.config())
        h.action('record-migration-plan', document=planning_fixture.plan())

    def test_locked_roundtrip_edits_change_handoff_not_design_authority(self):
        self.record(); h = self.h
        old_bindings = stages.review_bindings(h.state, ['orders'])
        old_handoff = planning.fingerprint(h.state)
        row = planning.domain_snapshot(h.state, 'commerce')
        h.action('edit-migration-items', document={'schema_version': 1, 'domain_id': 'commerce',
            'plan_sha256': row['plan_sha256'], 'request_reference': 'synthetic://human/notes',
            'edits': [{'id': 'req.orders', 'owner': 'Requested reviewer', 'notes': 'Keep the reconciliation evidence.'}]})
        reopened = guided.load_engagement(h.run)
        self.assertEqual(stages.review_bindings(reopened, ['orders']), old_bindings)
        self.assertNotEqual(planning.fingerprint(reopened), old_handoff)
        self.assertEqual(reopened['workflow']['approvals'], [])
        self.assertEqual(planning.domain_snapshot(reopened, 'commerce')['work_items'][0]['notes'],
                         'Keep the reconciliation evidence.')
        self.assertEqual({p.name: p.read_bytes() for p in h.repo.iterdir()}, self.source_bytes)

    def test_pm_reuses_retained_scope_and_invalidates_changed_bound_evidence(self):
        self.record(); h = self.h
        request = {'schema_version': 1, 'role': 'migration_project_manager', 'work_id': 'plan-commerce',
            'attempt_id': 'plan-1', 'scope_ids': ['commerce'], 'source_paths': []}
        self.assertEqual(run_control.claim_work(h.state, request)['action'], 'dispatch')
        output = h.artifacts / 'planning-result.txt'; output.write_text('Scoped result')
        run_control.checkpoint_work(h.state, {'schema_version': 1, 'attempt_id': 'plan-1',
            'status': 'outputs_recorded', 'reason': 'Local proposal recorded', 'outputs': [output.name]}, h.artifacts)
        self.assertEqual(run_control.claim_work(h.state, dict(request, attempt_id='plan-2'))['action'], 'reuse')
        # Reusing evidence still checks the existing source bindings for drift.
        (h.repo / 'orders.sql').write_text('Source intentionally changed outside the retained planning scope')
        self.assertEqual(run_control.claim_work(h.state, dict(request, attempt_id='plan-3'))['action'], 'dispatch')
        for patch in ({'source_paths': ['orders.sql']}, {'scope_ids': ['commerce', 'other']},
                      {'task_id': 'implementation-task'}, {'source_type': 'looker'}):
            with self.assertRaises(ValueError): run_control.claim_work(h.state, dict(request, **patch))

    def test_bounded_context_export_integrity_and_no_overwrite(self):
        self.record(); h = self.h
        packet = tools.inspect(h.state, 'context', 'commerce')
        self.assertLessEqual(len(json.dumps(packet).encode()), 32768)
        self.assertNotIn(str(h.repo), json.dumps(packet))
        with self.assertRaisesRegex(ValueError, 'budget reason'):
            tools.inspect(h.state, 'context', 'commerce', 65536)
        output = h.root / 'planning-export'
        receipt = tools.export(h.state, output, 'commerce')
        self.assertFalse(receipt['external_writes'])
        self.assertTrue(any(r['path'].endswith('.xlsx') for r in receipt['files']))
        self.assertTrue(any(r['path'].endswith('.docx') for r in receipt['files']))
        for row in receipt['files']:
            self.assertEqual(hashlib.sha256((output / row['path']).read_bytes()).hexdigest(), row['sha256'])
        with self.assertRaises(ValueError): tools.export(h.state, output, 'commerce')
        with self.assertRaises(ValueError): tools.export(h.state, h.repo / 'unsafe', 'commerce')
        self.assertEqual({p.name: p.read_bytes() for p in h.repo.iterdir()}, self.source_bytes)

    def test_optional_intake_does_not_change_code_bindings_or_require_plan(self):
        h = self.h
        before = stages.review_bindings(h.state, ['orders'])
        old_stages = copy.deepcopy(stages.STAGES)
        h.action('configure-migration-planning', document=planning_fixture.config())
        self.assertEqual(stages.review_bindings(h.state, ['orders']), before)
        self.assertEqual(stages.STAGES, old_stages)
        self.assertEqual(h.state['workflow']['approvals'], [])
        self.assertIn('provisional', json.dumps(h.state['next_actions']).lower())
        self.assertFalse(planning.domain_snapshot(h.state, 'commerce')['plan_sha256'])


if __name__ == '__main__': unittest.main()
