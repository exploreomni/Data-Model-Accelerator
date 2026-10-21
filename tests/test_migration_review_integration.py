"""Synthetic guided journeys: actual extraction, scoped design, private parity."""
import copy
import hashlib
import json
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import business_rules
import migration_review
import migration_validation
import shared_model_candidates
import engagement_stages
from ae_common import hash_json
import test_engagement_stages as fixtures
from test_shared_model_candidates import fixture as portfolio_fixture
from test_migration_validation import fixture as parity_fixture


class MigrationReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def reference(self, name, document):
        path = self.h.root / name
        raw = json.dumps(document).encode(); path.write_bytes(raw)
        return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

    def parity_request(self, mismatch=False):
        flow, requests = parity_fixture(draft=True)
        flow['crosswalk'][0]['model_ids'] = ['orders']
        flow['plan']['bindings'] = migration_review.parity_bindings(self.h.state, ['orders'])
        flow = migration_validation.prepare({k: flow[k] for k in ('schema_version', 'plan', 'crosswalk')})
        if mismatch: requests[2]['cases'][0]['payload'][1]['revenue'] = 999
        captures = [migration_validation.import_capture(flow, r) for r in requests]
        flow = migration_validation.freeze(flow, captures[0], 'synthetic-independent-analyst')
        return {'schema_version': 1, 'workflow': self.reference('flow.json', flow),
                **{k: self.reference(k + '.json', v) for k, v in zip(('baseline', 'warehouse', 'omni'), captures)},
                'current_bindings': flow['plan']['bindings']}

    @unittest.skipUnless(importlib.util.find_spec('yaml'), 'Optional PyYAML source parser dependency required')
    def test_source_discovery_reuses_actual_contracts_without_source_write(self):
        folder = self.h.repo / 'views/orders'; folder.mkdir(parents=True)
        (folder / 'orders.yaml').write_text('Database Name: warehouse\nSettings:\n  Materialize View: true\n')
        (folder / 'orders.sql').write_text('select orders_id from raw.orders')
        before = {str(p): p.read_bytes() for p in self.h.repo.rglob('*') if p.is_file()}
        request = {'schema_version': 1, 'source_profiles': ['periscope:.'],
                   'source_identity': {'repository_id': 'synthetic-repo', 'space_ids': {'.': 'synthetic-space'}}}
        self.h.action('extract-periscope', document=request)
        record = migration_review.load(self.h.state, 'source_discovery')
        self.assertTrue(record['contracts'])
        self.assertFalse(record['report']['execution_performed'])
        with patch('periscope_workflow.run_periscope_workflow', side_effect=AssertionError('Unchanged input rescanned')):
            self.h.action('extract-periscope', document=request)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.h.repo.rglob('*') if p.is_file()})
        summary = migration_review.public_summary(self.h.state)
        self.assertEqual(summary['source_discovery']['freshness'], 'current')
        self.assertNotIn('source_discovery', migration_review.public_summary(self.h.state, ['products']))
        Path(record['contracts'][0]['path']).write_text('{}')
        self.assertEqual(migration_review.public_summary(self.h.state)['source_discovery']['freshness'], 'stale')
        self.h.state['inputs']['source']['fingerprint'] = 'f' * 64
        self.assertEqual(migration_review.public_summary(self.h.state)['source_discovery']['freshness'], 'stale')

    def test_rules_portfolio_task_packet_and_scoped_freshness(self):
        pack = business_rules.from_text('Exclude internal orders.', rule_id='orders.population',
            domain='commerce', source_reference='synthetic-interview')
        pack['rules'][0]['scope'] = {'domains': [], 'model_ids': ['orders'], 'asset_ids': []}
        self.h.action('record-business-rules', document=pack)
        request = portfolio_fixture()
        for row in request['assets']: row['contract']['rule_ids'] = ['orders.population']
        self.h.action('recommend-shared-models', document=request)
        self.h.approve()
        self.h.action('plan-tasks', document=self.h.tasks(), artifact_root=self.h.artifacts)
        tasks = {r['id']: r for r in self.h.state['workflow']['last_plan']['tasks']}
        self.assertNotIn('business_rule_context', tasks['build-products'])
        self.assertEqual(tasks['build-orders']['business_rule_context']['rules'][0]['status'], 'proposed')
        self.assertEqual(shared_model_candidates.summary(self.h.state)['status'], 'proposed')
        self.h.state['workflow']['design']['entities'][1]['grain'] = 'Changed grain'
        summary = shared_model_candidates.summary(self.h.state)
        self.assertEqual(summary['status'], 'stale')
        self.assertEqual(summary['candidates'][0]['freshness'], 'stale')

    def test_three_lane_parity_report_is_recomputed_and_row_free(self):
        self.h.action('record-migration-validation', document=self.parity_request())
        report = migration_review.public_summary(self.h.state)['parity']
        self.assertEqual(report['status'], 'pass')
        self.assertFalse(report['native_verified']); self.assertFalse(report['acceptance_ready'])
        self.assertNotIn('revenue', json.dumps(migration_review.load(self.h.state, 'parity')))
        self.assertEqual(migration_review.public_summary(self.h.state, ['products'])['parity']['status'], 'unassessed')
        request = self.parity_request(mismatch=True)
        self.h.action('record-migration-validation', document=request)
        self.assertEqual(migration_review.public_summary(self.h.state)['parity']['status'], 'fail')

    def test_private_capture_change_or_removal_cannot_retain_pass(self):
        request = self.parity_request()
        self.h.action('record-migration-validation', document=request)
        Path(request['baseline']['path']).unlink()
        summary = migration_review.public_summary(self.h.state)['parity']
        self.assertTrue(summary['stale']); self.assertEqual(summary['status'], 'pending')

    def test_code_or_rule_changes_stale_parity_without_approving_any_stage(self):
        self.h.action('record-migration-validation', document=self.parity_request())
        pack = business_rules.from_text('UTC days', rule_id='orders.time', domain='commerce', source_reference='synthetic-interview')
        self.h.action('record-business-rules', document=pack)
        report = migration_review.public_summary(self.h.state)['parity']
        self.assertTrue(report['stale']); self.assertEqual(self.h.state['workflow']['approvals'], [])

    def test_imported_scorecard_is_not_accepted_as_comparison_evidence(self):
        with self.assertRaises(ValueError):
            self.h.action('record-migration-validation', document={'schema_version': 1, 'status': 'pass'})

    def test_re_registering_old_capture_cannot_claim_current_engagement(self):
        request = self.parity_request()
        self.h.action('record-migration-validation', document=request)
        pack = business_rules.from_text('A new definition', rule_id='new.definition', domain='commerce', source_reference='synthetic')
        self.h.action('record-business-rules', document=pack)
        # A caller replaying the old plan's current_bindings cannot override
        # current inputs and candidate bindings derived inside the coordinator.
        self.h.action('record-migration-validation', document=request)
        report = migration_review.public_summary(self.h.state)['parity']
        self.assertEqual(report['status'], 'fail'); self.assertTrue(report['stale'])

    def test_binding_command_exposes_current_local_contract_without_approval(self):
        self.h.action('migration-bindings', entities=['orders'])
        self.assertEqual(self.h.state['workflow']['migration_validation_bindings'],
                         migration_review.parity_bindings(self.h.state, ['orders']))
        self.assertEqual(self.h.state['workflow']['approvals'], [])

    def test_shared_proposals_can_precede_entity_design(self):
        state = copy.deepcopy(self.h.state)
        state['workflow']['design'] = None
        request = portfolio_fixture()
        for row in request['assets']: row['model_ids'] = []
        shared_model_candidates.register(state, request, self.h.run)
        report = shared_model_candidates.summary(state)
        self.assertEqual(report['covered_assets'], 2)
        self.assertEqual(report['candidates'][0]['disposition'], 'shared_aggregate_candidate')
        self.assertEqual(shared_model_candidates.summary(state, [])['candidates'], [])


if __name__ == '__main__': unittest.main()
