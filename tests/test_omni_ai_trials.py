"""Repeated AI observations stay imported evidence with a fixed denominator."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_ai_context as ai
import omni_contract as omni
from test_omni_ai_context import fixture, evaluation_fixture


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None, 'Pinned semantic runtime required')
class AITrialTests(unittest.TestCase):
    def setUp(self):
        spec, inputs = fixture()
        self.context = ai.build_context(spec, **inputs)['context']
        self.suite, answers = evaluation_fixture(self.context)
        self.plan = {'schema_version': 1, 'kind': 'omni_ai_trial_plan',
                     'suite_sha256': ai.digest(self.suite), 'minimum_trials': 3,
                     'provider': {'name': 'synthetic-offline-provider', 'model': 'fixture-only',
                                  'settings_sha256': 'a' * 64}}
        self.observations = {'schema_version': 1, 'kind': 'omni_ai_trials',
            'plan_sha256': ai.digest(self.plan), 'trials': [
                {'id': 'trial-'+str(index), 'provider': copy.deepcopy(self.plan['provider']),
                 'delivered_context_sha256': self.context['context_sha256'],
                 'observations': copy.deepcopy(answers)} for index in range(3)]}

    def evaluate(self):
        return ai.evaluate_trials(self.plan, self.suite, self.observations, self.context)

    def test_repeated_structured_passes_do_not_claim_native_or_prose_truth(self):
        report = self.evaluate()
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['trials_compared'], 3)
        self.assertEqual(report['cases_compared'], 9)
        self.assertFalse(report['live_ai_authenticated'])
        self.assertFalse(report['natural_language_answer_verified'])
        self.assertFalse(report['access_enforcement_verified'])
        self.assertFalse(report['business_accepted'])

    def test_one_confident_wrong_metric_fails_the_whole_batch(self):
        answer = self.observations['trials'][1]['observations']['answers'][0]
        answer['fields'] = ['shipments.count']
        report = self.evaluate()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['failed_trials'], 1)

    def test_missing_trial_cannot_reduce_the_denominator(self):
        self.observations['trials'].pop()
        self.assertEqual(self.evaluate()['status'], 'failed')

    def test_duplicate_ids_cannot_fake_repeated_observations(self):
        self.observations['trials'][1]['id'] = self.observations['trials'][0]['id']
        self.assertEqual(self.evaluate()['status'], 'failed')

    def test_changed_provider_settings_or_truncated_context_fail(self):
        original = copy.deepcopy(self.observations)
        for field in ('provider', 'delivered_context_sha256'):
            self.observations = copy.deepcopy(original)
            trial = self.observations['trials'][1]
            if field == 'provider': trial[field]['settings_sha256'] = 'b' * 64
            else: trial[field] = 'b' * 64
            with self.subTest(field=field): self.assertEqual(self.evaluate()['status'], 'failed')

    def test_missing_attribute_and_ambiguity_cannot_be_answered_away(self):
        for index in (1, 2):
            observed = copy.deepcopy(self.observations)
            observed['trials'][0]['observations']['answers'][index]['decision'] = 'answer'
            self.assertEqual(ai.evaluate_trials(self.plan, self.suite, observed, self.context)['status'], 'failed')

    def test_source_or_suite_drift_invalidates_all_trials(self):
        self.context['pins']['model_sha256'] = 'f' * 64
        self.assertEqual(self.evaluate()['status'], 'failed')

    def test_sensitive_diagnostic_data_is_redacted(self):
        self.observations['trials'][0]['provider']['name'] = 'SYNTHETIC_PHI_CANARY'
        report = self.evaluate()
        self.assertEqual(report['status'], 'failed')
        self.assertNotIn('SYNTHETIC_PHI_CANARY', str(report))


if __name__ == '__main__':
    unittest.main()
