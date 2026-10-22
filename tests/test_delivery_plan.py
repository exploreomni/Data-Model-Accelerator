import copy
import json
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_plan as plans
import guided_workflow as guided
import test_engagement_stages as fixtures


class DeliveryPlanTests(unittest.TestCase):
    def setUp(self):
        self.state = {'answers': {'deliverables': ['implementation'], 'framework': 'dbt',
                                 'semantic_target': 'omni', 'migration_scope': 'model_semantic'},
                      'workflow': {'tasks': []}}
        self.request = {'schema_version': 1, 'request_reference': 'synthetic://request',
                        'stages': [{'stage': stage, 'status': 'planned', 'reason': 'Requested output'} for stage in plans.STAGES]}

    def test_selected_stages_cannot_be_silently_omitted(self):
        self.request['stages'] = [r for r in self.request['stages'] if r['stage'] != 'implementation']
        with self.assertRaisesRegex(ValueError, 'every requested stage'):
            plans.record_plan(self.state, self.request)

    def test_semantic_cannot_be_planned_while_warehouse_is_deferred(self):
        self.request['stages'][1].update(status='deferred', request_reference='synthetic://design-first')
        with self.assertRaisesRegex(ValueError, 'warehouse implementation'):
            plans.record_plan(self.state, self.request)

    def test_deferral_is_explicit_pending_work_and_can_be_resumed(self):
        for row in self.request['stages'][1:4]:
            row.update(status='deferred', request_reference='synthetic://design-first')
        plans.record_plan(self.state, self.request)
        summary = plans.public_summary(self.state)
        self.assertEqual(summary['deferred_stages'], ['implementation', 'semantic', 'validation'])
        with self.assertRaisesRegex(ValueError, 'deferred'):
            plans.require_not_deferred(self.state, 'implementation')
        for row in self.request['stages']:
            row['status'] = 'planned'
        plans.record_plan(self.state, self.request)
        plans.require_not_deferred(self.state, 'implementation')
        self.assertEqual(plans.public_summary(self.state)['unplanned_code_stages'], ['implementation', 'semantic'])

    def test_stale_or_missing_plan_does_not_block_provisional_authoring(self):
        plans.require_not_deferred(self.state, 'implementation')
        plans.record_plan(self.state, self.request)
        self.state['answers']['warehouse'] = 'bigquery'
        self.assertEqual(plans.public_summary(self.state)['status'], 'stale')
        plans.require_not_deferred(self.state, 'implementation')

    def test_subset_review_never_discloses_other_domain_plan_or_counts(self):
        self.state['workflow']['design'] = fixtures.candidate()
        self.state['workflow']['tasks'] = [{'stage': 'implementation', 'entity_ids': ['customers']}]
        for row in self.request['stages']:
            row['reason'] = 'PRIVATE_PLAN_MARKER'
        plans.record_plan(self.state, self.request)
        restricted = plans.public_summary(self.state, {'products'})
        self.assertNotIn('PRIVATE_PLAN_MARKER', json.dumps(restricted))
        self.assertEqual(restricted['stages'], [])

    def test_cli_records_plan_without_granting_approval(self):
        h = fixtures.StageTests(methodName='test_design_only_and_forged_approval_never_unlock_code')
        h.setUp(); self.addCleanup(h.doCleanups)
        path = h.root / 'plan.json'; path.write_text(json.dumps(self.request))
        with redirect_stdout(io.StringIO()):
            code = guided.main(['record-delivery-plan', '--run', str(h.run), '--document', str(path), '--no-render'])
        self.assertEqual(code, 0)
        state = guided.load_engagement(h.run)
        self.assertEqual(plans.public_summary(state)['status'], 'current')
        self.assertEqual(state['workflow']['approvals'], [])
        self.assertFalse(state['readiness']['execution_authorized'])
