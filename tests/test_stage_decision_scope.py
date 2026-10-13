"""Semantic decisions must not invalidate unchanged physical implementations."""
import copy
import unittest

import test_engagement_stages as fixtures

stages = fixtures.stages


class StageDecisionScopeTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_semantic_only_decision_does_not_block_warehouse_design')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.doc['revision'] += 1
        self.h.doc['decisions'] = [{'id': 'topic', 'question': 'Which topic grouping?',
            'options': [], 'recommendation': None, 'reviewer_role': 'Semantic owner',
            'model_ids': ['orders'], 'asset_ids': ['report:orders'], 'blocking_stages': ['semantic'],
            'rationale': 'Choose the semantic organization.', 'evidence_summary': 'Grouping remains open.'}]
        self.h.action('import-design', document=self.h.doc)

    def approve(self, signed=False, identity='first'):
        if signed:
            self.h.approve(identity=identity)
        else:
            self.h.action('approve-design', entities=['customers', 'orders', 'products'], document={
                'schema_version': 1, 'kind': 'human_design_review', 'decision': 'approve',
                'reviewer': 'Synthetic reviewer', 'review_reference': 'synthetic://human/' + identity,
                'bindings': stages.review_bindings(self.h.state, ['customers', 'orders', 'products'])})

    def answer(self, value):
        doc = self.h.state['workflow']['design']
        self.h.action('answer-decisions', document={
            'schema_version': 1, 'kind': 'decision_responses', 'intent': 'record_answers',
            'engagement_id': self.h.state['engagement_id'], 'design_id': doc['id'],
            'design_revision': doc['revision'], 'design_sha256': doc['sha256'], 'request_only': True,
            'answers': [{'decision_id': 'topic', 'answer': value, 'option_id': None, 'rationale': ''}]})

    def actions(self):
        return {row['id']: row['action'] for row in self.h.plan()['tasks']}

    def sequence(self, signed):
        self.approve(signed)
        tasks = self.h.tasks()
        tasks['tasks'].append({'id': 'validate', 'stage': 'validation', 'entity_ids': ['orders'],
                               'depends_on': ['semantic'], 'components': [], 'outputs': ['validation.json']})
        self.h.plan(tasks)
        for task in ('build-customers', 'build-orders', 'build-products'):
            self.h.complete(task)
        original = stages.review_bindings(self.h.state, ['orders'])
        self.answer('Separate a curated sales topic.')
        current = stages.review_bindings(self.h.state, ['orders'])
        self.assertEqual(original['stage_entities']['implementation'], current['stage_entities']['implementation'])
        self.assertNotEqual(original['stage_entities']['semantic'], current['stage_entities']['semantic'])
        self.assertIn('orders', stages.approved_entities(self.h.state))
        self.assertNotIn('orders', stages.approved_entities(self.h.state, stage='semantic'))
        self.assertNotIn('orders', stages.approved_entities(self.h.state, stage='validation'))
        self.assertEqual(self.actions(), {'build-customers': 'reuse', 'build-products': 'reuse',
                                         'build-orders': 'reuse', 'semantic': 'blocked', 'validate': 'blocked'})
        self.assertEqual(stages.public_view(self.h.state)['decisions'][0]['status'], 'answer_recorded')
        with self.assertRaisesRegex(ValueError, 'design review'):
            self.h.action('stage', entities=['orders'], stage='semantic')
        self.approve(signed, 'after-answer')
        self.assertEqual(stages.public_view(self.h.state)['decisions'][0]['status'], 'resolved')
        self.assertEqual(self.actions()['semantic'], 'regenerate')
        self.h.complete('semantic'); self.h.complete('validate')
        self.assertTrue(all(action == 'reuse' for action in self.actions().values()))
        self.answer('Split sales and fulfillment topics.')
        self.assertEqual(self.actions(), {'build-customers': 'reuse', 'build-products': 'reuse',
                                         'build-orders': 'reuse', 'semantic': 'blocked', 'validate': 'blocked'})
        self.assertEqual(len(self.h.state['workflow']['runs']), 5)
        self.assertEqual(stages.public_view(self.h.state)['decisions'][0]['status'], 'answer_recorded')
        with self.assertRaisesRegex(ValueError, 'separate signed deployment|design review'):
            self.h.action('stage', entities=['orders'], stage='deployment')

    def test_host_review_preserves_physical_outputs_but_answer_import_does_not_approve_semantics(self):
        self.sequence(False)
        view = stages.public_view(self.h.state)
        self.assertEqual(next(row['status'] for row in view['stages'] if row['id'] == 'design'), 'review_recorded')
        self.assertIn('not independently authenticated', view['qualification'])
        self.assertFalse(self.h.state['readiness']['execution_authorized'])

    @unittest.skipIf(fixtures.Ed25519PrivateKey is None, 'Optional cryptography dependency required')
    def test_signed_review_remains_exact_and_stage_scoped(self):
        self.sequence(True)
        view = stages.public_view(self.h.state)
        self.assertEqual(next(row['status'] for row in view['stages'] if row['id'] == 'design'), 'signature_verified')
        state = copy.deepcopy(self.h.state)
        state['workflow']['approvals'][0]['bindings']['stage_entities']['implementation']['orders'] = '0' * 64
        state['workflow']['approvals'] = state['workflow']['approvals'][:1]
        self.assertEqual(stages.approved_entities(state), set())

    def test_business_definition_changes_still_invalidate_physical_and_semantic_review(self):
        self.h.doc['revision'] += 1
        self.h.doc['decisions'][0]['blocking_stages'] = ['design']
        self.h.action('import-design', document=self.h.doc)
        self.answer('Use the settled order population.')
        self.approve()
        self.assertIn('orders', stages.approved_entities(self.h.state))
        self.answer('Include unsettled orders.')
        self.assertNotIn('orders', stages.approved_entities(self.h.state))
        self.assertNotIn('orders', stages.approved_entities(self.h.state, stage='semantic'))
        self.assertEqual(stages.public_view(self.h.state)['decisions'][0]['status'], 'answer_recorded')

    def test_stage_cache_does_not_mix_semantic_and_physical_bindings(self):
        self.answer('Sales topic')
        cache = {}
        physical = stages.entity_bindings(self.h.state, ['orders'], stage='implementation', _cache=cache)
        semantic = stages.entity_bindings(self.h.state, ['orders'], stage='semantic', _cache=cache)
        self.assertNotEqual(physical['orders'], semantic['orders'])
        self.assertEqual(physical['customers'], semantic['customers'])


if __name__ == '__main__': unittest.main()
