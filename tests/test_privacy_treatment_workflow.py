"""Draft delivery stays available while native execution retains its privacy gate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import deployment_workflow as deployment
import personal_data


class PrivacyTreatmentWorkflowTests(unittest.TestCase):
    def fixture(self):
        state = {'answers': {'personal_data': {'schema_version': 2, 'entries': [
            {'table': 'customers', 'column': 'email', 'origin': 'prompt'}], 'treatments': []}}}
        review = {'models': [{'id': 'gold.customers', 'layer': 'gold', 'artifact_id': 'code',
                            'columns': [{'name': 'email'}]}],
                  'artifacts': [{'id': 'code', 'path': 'model.sql', 'category': 'implementation'}]}
        selected = [dict(review['artifacts'][0], content=b'SELECT email FROM customers')]
        return state, review, selected

    def test_unresolved_treatment_keeps_candidate_review_available(self):
        state, review, selected = self.fixture()
        report = portal._check_personal_data(state, review, selected)
        self.assertEqual(report['status'], 'unresolved')
        self.assertIn('unresolved', portal._privacy_panel(report))
        self.assertFalse(report['authorization_authenticated'])

    def test_only_projected_outputs_are_checked_and_input_lineage_is_retained(self):
        rows = personal_data.sql_outputs('SELECT SHA2(email, 256) AS customer_key FROM customers', 'gold.customers')
        if importlib.util.find_spec('sqlglot') is not None:
            self.assertEqual([r['identifier'] for r in rows], ['customer_key'])
            self.assertTrue(any(c['column'] == 'email' for c in rows[0]['source_columns']))
        else:
            self.assertFalse(rows[0]['lineage_complete'])
            self.assertEqual(rows[0]['lineage_reasons'], ['sql.parser_unavailable'])
        with patch.dict(sys.modules, {'sqlglot': None}):
            unsupported = personal_data.sql_outputs('SELECT email FROM customers', 'gold.customers')
        self.assertFalse(unsupported[0]['lineage_complete'])
        self.assertEqual(unsupported[0]['lineage_reasons'], ['sql.parser_unavailable'])

    def test_native_preflight_rejects_unresolved_treatment_and_changed_bytes(self):
        state, review, selected = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); raw = json.dumps(review).encode()
            (root/'review.json').write_bytes(raw); (root/'model.sql').write_bytes(selected[0]['content'])
            handoff = {'review_path': str(root/'review.json'), 'review_sha256': hashlib.sha256(raw).hexdigest(),
                       'artifact_root': str(root), 'artifacts': [{'path': 'model.sql', 'sha256': hashlib.sha256(selected[0]['content']).hexdigest()}]}
            with self.assertRaisesRegex(ValueError, 'Privacy treatment'):
                deployment._privacy_preflight(state, handoff)
            (root/'model.sql').write_text('SELECT 1 AS id')
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                deployment._privacy_preflight(state, handoff)
