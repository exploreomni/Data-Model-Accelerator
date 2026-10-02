"""Authority labels cannot upgrade synthetic evidence or authorize a deployment."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from verify_engagement_authority import PINS, verify


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name).resolve() / 'authority.json'
        self.context = dict.fromkeys(PINS, 'a' * 64)
        self.context.update(rule_ids=['source', 'metric'], decision_ids=['correction'], origin='synthetic',
                            stage='local', execution_mode='fixture_replay')
        self.contract = {key: self.context[key] for key in PINS}
        self.contract.update(schema_version=1, kind='engagement_authority', purpose='simulation',
                             decision_state='simulation_authorized', actor_id='fixture-author',
                             review_reference='synthetic exercise decision', rule_ids=['source', 'metric'], decision_ids=['correction'])

    def check(self):
        self.path.write_text(json.dumps(self.contract))
        return verify(self.path, self.context)

    def test_simulation_keeps_authority_and_promotion_explicit(self):
        result = self.check()
        self.assertTrue(result['passed'])
        self.assertEqual(result['decision_state'], 'simulation_authorized')
        self.assertFalse(result['promotion_authorized'])
        self.assertFalse(result['human_approval_authenticated'])

    def test_every_pin_and_decision_denominator_is_required(self):
        original = copy.deepcopy(self.contract)
        for field in PINS + ('rule_ids', 'decision_ids'):
            self.contract = copy.deepcopy(original)
            self.contract[field] = 'b' * 64 if field in PINS else []
            with self.subTest(field=field), self.assertRaises(ValueError): self.check()

    def test_synthetic_or_fixture_cannot_be_relabeled_development(self):
        self.contract.update(purpose='development_validation', decision_state='proposed', review_reference=None)
        with self.assertRaises(ValueError): self.check()
        self.context['origin'] = 'provided_export'
        with self.assertRaises(ValueError): self.check()

    def test_simulation_cannot_claim_human_approval_or_target(self):
        self.contract['decision_state'] = 'human_approval_recorded'
        with self.assertRaises(ValueError): self.check()
        self.contract['decision_state'] = 'simulation_authorized'
        self.context['stage'] = 'target'
        with self.assertRaises(ValueError): self.check()

    def test_proposed_development_can_validate_without_implying_acceptance(self):
        self.context.update(origin='provided_export', execution_mode='host_subagent', stage='target')
        self.contract.update(purpose='development_validation', decision_state='proposed', review_reference=None)
        result = self.check()
        self.assertTrue(result['passed'])
        self.assertEqual(result['decision_state'], 'proposed')
        self.assertFalse(result['promotion_authorized'])
        self.contract['review_reference'] = 'claim acceptance'
        with self.assertRaises(ValueError): self.check()

    def test_recorded_human_approval_requires_reference_but_is_not_authenticated(self):
        self.context.update(origin='live_metadata', execution_mode='host_subagent', stage='target')
        self.contract.update(purpose='development_validation', decision_state='human_approval_recorded', review_reference='review/42')
        result = self.check()
        self.assertTrue(result['passed'])
        self.assertFalse(result['human_approval_authenticated'])
        self.assertFalse(result['promotion_authorized'])
        for invalid in (None, '', ' ', True):
            self.contract['review_reference'] = invalid
            with self.subTest(value=invalid), self.assertRaises(ValueError): self.check()

    def test_duplicate_ids_unknown_fields_and_invalid_states_rejected(self):
        original = copy.deepcopy(self.contract)
        for mutation in ({'rule_ids': ['source', 'source', 'metric']}, {'decision_ids': ['correction', 'correction']},
                         {'decision_state': 'accepted'}, {'purpose': 'production'}, {'schema_version': True}, {'deploy': True}):
            self.contract = dict(original, **mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.check()


if __name__ == '__main__': unittest.main()
