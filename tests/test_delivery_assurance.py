import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_assurance as assurance
import guided_workflow as workflow
from ae_common import hash_json


class DeliveryAssuranceTests(unittest.TestCase):
    def setUp(self):
        self.bindings = {k: 'a' * 64 for k in assurance.BINDINGS}
        self.now = datetime(2026, 10, 5, tzinfo=timezone.utc)

    def receipt(self, lane):
        return dict(lane=lane, status='passed', bindings=self.bindings.copy(),
                    observed_at='2026-10-04T00:00:00Z', expires_at='2026-10-06T00:00:00Z',
                    result_sha256='b' * 64, provenance='native_observation' if lane in assurance.NATIVE else 'local_check')

    def test_scope_controls_dashboard_requirement(self):
        self.assertNotIn('dashboard_created', assurance.required_lanes('model_semantic'))
        self.assertIn('dashboard_created', assurance.required_lanes('full_dashboard'))
        self.assertFalse(assurance.evaluate('full_dashboard', self.bindings)['acceptance_ready'])

    def test_imported_native_claim_never_passes(self):
        r = self.receipt('native_model')
        result = assurance.evaluate('model_semantic', self.bindings, [r], now=self.now)
        self.assertEqual(next(c for c in result['checks'] if c['lane']=='native_model')['status'], 'pending')
        result = assurance.evaluate('model_semantic', self.bindings, [r], now=self.now, trusted_receipts=[hash_json(r)])
        self.assertEqual(next(c for c in result['checks'] if c['lane']=='native_model')['status'], 'passed')
        self.assertFalse(result['deployment_authorized'])

    def test_changed_binding_and_expiry(self):
        for key in assurance.BINDINGS:
            r = self.receipt('yaml'); r['bindings'][key] = 'c' * 64
            checks = assurance.evaluate('model_semantic', self.bindings, [r], now=self.now)['checks']
            self.assertEqual(next(c for c in checks if c['lane']=='yaml')['status'], 'stale')
        r = self.receipt('yaml'); r['expires_at']='2026-10-03T00:00:00Z'
        self.assertEqual(next(c for c in assurance.evaluate('model_semantic', self.bindings,[r],now=self.now)['checks'] if c['lane']=='yaml')['status'],'stale')

    def test_duplicate_and_inapplicable_receipts_fail(self):
        r = self.receipt('yaml')
        with self.assertRaises(ValueError): assurance.evaluate('model_semantic', self.bindings,[r,r])
        r['status']='not_applicable'
        result=assurance.evaluate('model_semantic',self.bindings,[r])
        self.assertEqual(next(c for c in result['checks'] if c['lane']=='yaml')['status'],'failed')

    def test_synthetic_not_native_even_if_trusted(self):
        r=self.receipt('native_model'); r['provenance']='synthetic'
        result=assurance.evaluate('model_semantic',self.bindings,[r],now=self.now,trusted_receipts=[hash_json(r)])
        self.assertEqual(next(c for c in result['checks'] if c['lane']=='native_model')['status'],'pending')

    def test_intake_explicit_answers_and_fingerprint(self):
        answers={'semantic_target':'omni','engagement_type':'migration'}
        self.assertIn('migration_scope', workflow._missing(answers))
        before=workflow._selection(answers)[0]['sha256']
        answers.update(migration_scope='full_dashboard',input_handling='pre_sanitized')
        self.assertNotIn('migration_scope',workflow._missing(answers))
        self.assertNotEqual(before,workflow._selection(answers)[0]['sha256'])
        self.assertEqual(workflow._answers(answers),answers)
