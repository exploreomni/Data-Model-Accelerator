"""Focused assignment, applicability and consolidated-review regressions."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import task_routing as routing


def assignment(**updates):
    return {'schema_version': 1, 'task_id': 'orders-sql', 'domain_id': 'commerce',
            'stage': 'implementation', 'role': 'analytics_engineer', 'scope_ids': ['orders'],
            'objective': 'Create an order-grain candidate', 'outputs': ['models/fct_orders.sql'],
            'acceptance': ['One row per order; preserve observed filters'],
            'input_bindings': {'work_inputs': 'a' * 64}, 'dependencies': {},
            'unknowns': ['Live key uniqueness unverified'], 'authoring_mode': 'provisional', **updates}


class RoutingTests(unittest.TestCase):
    def test_provisional_and_aliases_work_but_mismatches_and_unsafe_outputs_fail(self):
        self.assertEqual(routing.validate_assignment(assignment())['authoring_mode'], 'provisional')
        value = assignment(stage='semantic', role='omni_modeler')
        self.assertEqual(routing.validate_assignment(value)['role'], 'semantic_modeler')
        for update in ({'role': 'warehouse_architect'}, {'outputs': ['../source.sql']},
                       {'outputs': ['project.json']}, {'outputs': ['Project.json']},
                       {'outputs': ['models/a.sql', 'models/A.sql']}, {'acceptance': []}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                routing.validate_assignment(assignment(**update))
        with self.assertRaisesRegex(ValueError, 'scope'):
            routing.bind_assignment(assignment(), task_id='orders-sql', role='analytics_engineer', scope_ids=['payments'])

    def test_review_selection_covers_access_and_consumers_without_blanket_fanout(self):
        presentation = routing.route_reviews(assignment(stage='packaging', role='documentation_specialist', outputs=['START_HERE.html']), ['presentation'])
        self.assertEqual([r['id'] for r in presentation['reviews']], ['experience'])
        join = routing.route_reviews(assignment(), ['joins'])
        self.assertEqual({r['id'] for r in join['reviews']}, {'logic', 'semantic', 'security'})
        unknown = routing.route_reviews(assignment(), ['presentation'], 'unknown')
        self.assertTrue(unknown['context_requests'])
        self.assertIn('security', {r['id'] for r in unknown['reviews']})

    def result(self, review, review_id, verdict='pass', findings=None):
        return {'review_id': review_id, 'candidate_sha256': review['candidate_sha256'],
                'verdict': verdict, 'findings': findings or [],
                'reviewer_reference': 'synthetic://independent', 'execution_mode': 'specialist'}

    def test_wait_all_consolidate_then_bounded_correction_and_stale_evidence(self):
        artifacts = {'models/fct_orders.sql': 'b' * 64}
        review = routing.start_review(assignment(), artifacts, ['joins'], builder_reference='synthetic://author')
        finding = {'id': 'duplicate-order', 'severity': 'blocking', 'message': 'Join duplicates an order',
                   'evidence': ['independent fixture: order 1 has two rows'], 'affected_ids': ['orders'],
                   'acceptance': 'Return one row for order 1'}
        review = routing.record_review(review, self.result(review, 'logic', 'changes', [finding]))
        self.assertEqual(routing.review_decision(review, artifacts)['action'], 'wait')
        review = routing.record_review(review, self.result(review, 'semantic', 'changes', [finding]))
        review = routing.record_review(review, self.result(review, 'security'))
        result = routing.review_decision(review, artifacts)
        self.assertEqual(result['action'], 'correct'); self.assertEqual(len(result['findings']), 1)
        changed = {'models/fct_orders.sql': 'c' * 64}
        self.assertEqual(routing.review_decision(review, changed)['action'], 'stale')
        revised = routing.revise_review(review, changed)
        with self.assertRaisesRegex(ValueError, 'stale'):
            routing.record_review(revised, self.result(review, 'logic'))
        for discipline in revised['plan']['reviews']:
            revised = routing.record_review(revised, self.result(revised, discipline['id'], 'changes', [finding]))
        self.assertEqual(routing.review_decision(revised, changed)['action'], 'needs_human')

    def test_inline_self_review_and_missing_dependency_evidence_never_approve(self):
        artifacts = {'models/fct_orders.sql': 'b' * 64}
        for mode, builder in [('inline', 'synthetic://author'), ('specialist', 'synthetic://independent')]:
            review = routing.start_review(assignment(outputs=['START_HERE.html']), {'START_HERE.html': 'b' * 64}, ['presentation'], builder_reference=builder)
            result = self.result(review, 'experience'); result['execution_mode'] = mode
            review = routing.record_review(review, result)
            self.assertEqual(routing.review_decision(review, {'START_HERE.html': 'b' * 64})['action'], 'needs_human')
        artifacts = {'START_HERE.html': 'b' * 64}
        review = routing.start_review(assignment(outputs=['START_HERE.html']), artifacts, ['presentation'], builder_reference='synthetic://author')
        review = routing.record_review(review, self.result(review, 'experience'))
        self.assertEqual(routing.review_decision(review, artifacts)['action'], 'reviews_complete')


if __name__ == '__main__':
    unittest.main()
