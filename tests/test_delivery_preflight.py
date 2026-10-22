"""Delivery planning separates useful provisional files from validation authority."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from delivery_preflight import assess, completion
from test_delivery_portal import fixture
import guided_workflow as guided


class DeliveryPreflightTests(unittest.TestCase):
    def test_reports_missing_disclosure_before_finalization_without_mutating_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            state, review = fixture(Path(directory))
            state['answers']['migration_scope'] = 'model_only'
            before = copy.deepcopy(state)
            result = assess(state, review, directory, 'engineer')
            self.assertIn('disclosure_context_required', [r['code'] for r in result['issues']])
            self.assertEqual(state, before)
            self.assertGreater(result['selected_bytes'], 0)

    def test_completion_is_not_validation_and_checkpoint_stays_incomplete(self):
        state = {'readiness': {'generation_ready': False}}
        self.assertEqual(completion(state)['artifact_delivery'], 'provisional_delivery_complete')
        self.assertFalse(completion(state)['deployment_authorized'])
        self.assertEqual(completion(state, True)['artifact_delivery'], 'incomplete_checkpoint')

    def test_provisional_handoff_requires_current_request_for_every_selected_model(self):
        state = {'workflow': {'design': {'entities': [{'id': 'one'}, {'id': 'two'}]}}}
        with patch('engagement_stages.draft_entities', return_value={'one'}):
            self.assertFalse(guided._provisional_handoff_allowed(state))
        with patch('engagement_stages.draft_entities', return_value={'one', 'two'}):
            self.assertTrue(guided._provisional_handoff_allowed(state))

    def test_efficiency_deduplicates_packet_bytes_and_does_not_claim_cost(self):
        from run_efficiency import summarize
        receipt = {'packet_sha256': 'a' * 64, 'packet_bytes': 1200}
        result = summarize({'workflow': {'runs': [
            {'task_id': 'one', 'fingerprint': 'f', 'execution_observation': receipt},
            {'task_id': 'one', 'fingerprint': 'f', 'execution_observation': receipt},
            {'task_id': 'two', 'fingerprint': 'g'}],
            'last_plan': {'tasks': [{'action': 'reuse'}, {'action': 'regenerate'}]}}})
        self.assertEqual(result['unique_packet_bytes'], 1200)
        self.assertEqual(result['dispatched_packet_bytes'], 2400)
        self.assertEqual(result['repeated_task_attempts'], 1)
        self.assertEqual(result['runs_without_packet_receipts'], 1)
        self.assertNotIn('cost', result)


if __name__ == '__main__':
    unittest.main()
