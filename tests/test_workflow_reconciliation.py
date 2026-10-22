"""Canonical reconciliation is mandatory evidence, not native approval."""
import copy
import importlib
import unittest

import test_engagement_stages as fixtures
from review_assurance import records


class WorkflowReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.reconciliation = importlib.import_module('workflow_reconciliation')

    def proposal(self, identity, revision=2, **changes):
        design = copy.deepcopy(self.h.doc)
        design['revision'] = revision
        for entity in design['entities']:
            if entity['id'] == 'orders':
                entity.update(changes)
        return {'id': identity, 'design': design, 'shared_rules': []}

    def conflict_request(self):
        return {'schema_version': 1, 'proposals': [
            self.proposal('domain-one'),
            self.proposal('domain-two', grain='One row per order line')]}

    def reconcile(self, request):
        self.h.action('reconcile-design', document=request)
        return self.reconciliation.summarize(self.h.state)

    def human_review(self, selected):
        return {'schema_version': 1, 'kind': 'human_design_review', 'decision': 'approve',
                'reviewer': 'Synthetic business reviewer', 'review_reference': 'synthetic://review/canonical',
                'bindings': fixtures.stages.review_bindings(self.h.state, selected)}

    def test_import_records_canonical_diagnostics_without_claiming_approval(self):
        self.assertIsNotNone(records(self.h.state)['reconciliation'])
        summary = self.reconciliation.summarize(self.h.state)
        self.assertEqual(summary['status'], 'consistent')
        self.assertEqual(self.reconciliation.gaps(self.h.state, ['orders']), [])
        self.assertFalse(self.h.state['readiness']['execution_authorized'])
        self.assertEqual(self.h.state['workflow']['approvals'], [])

    def test_contradictory_proposals_keep_canonical_and_survive_later_direct_import(self):
        before = copy.deepcopy(self.h.state['workflow']['design'])
        request = self.conflict_request()
        request_before = copy.deepcopy(request)
        summary = self.reconcile(request)
        self.assertEqual(summary['status'], 'conflicts')
        self.assertEqual(self.h.state['workflow']['design'], before)
        self.assertEqual(request, request_before)
        self.assertTrue(any('orders' in finding['model_ids'] for finding in summary['findings']))
        direct = copy.deepcopy(self.h.doc)
        direct['revision'] = 2
        self.h.action('import-design', document=direct)
        retained = self.reconciliation.summarize(self.h.state)
        self.assertTrue(any('orders' in finding['model_ids'] for finding in retained['findings']))
        self.assertTrue(self.reconciliation.gaps(self.h.state, ['orders']))

    def test_shared_currency_conflict_covers_both_domains_without_choosing_a_winner(self):
        first, second = self.proposal('sales-domain'), self.proposal('product-domain')
        first['shared_rules'] = [{'id': 'currency-basis', 'dimension': 'currency', 'value': 'month_start',
                                  'model_ids': ['orders'], 'evidence_refs': ['source:orders']}]
        second['shared_rules'] = [{'id': 'currency-basis', 'dimension': 'currency', 'value': 'daily',
                                   'model_ids': ['products'], 'evidence_refs': ['source:products']}]
        before = copy.deepcopy(self.h.state['workflow']['design'])
        summary = self.reconcile({'schema_version': 1, 'proposals': [first, second]})
        self.assertEqual(summary['status'], 'conflicts')
        self.assertEqual(self.h.state['workflow']['design'], before)
        self.assertTrue(any({'orders', 'products'} <= set(finding['model_ids'])
                            for finding in summary['findings']))
        self.assertTrue(self.reconciliation.gaps(self.h.state, ['orders']))
        self.assertTrue(self.reconciliation.gaps(self.h.state, ['products']))
        self.assertEqual(self.reconciliation.gaps(self.h.state, ['customers']), [])
        first['shared_rules'][0]['value'] = 'UNKNOWN'
        second['shared_rules'][0].update(dimension='security', value='restricted')
        summary = self.reconcile({'schema_version': 1, 'proposals': [first, second]})
        self.assertEqual(summary['status'], 'conflicts', 'Unknown values cannot hide a conflicting rule dimension')
        self.assertEqual(self.h.state['workflow']['design'], before)

    def test_resolving_new_revision_imports_consensus_without_reconstructing_approval(self):
        self.reconcile(self.conflict_request())
        request = {'schema_version': 1, 'proposals': [
            self.proposal('domain-one', revision=3, grain='One row per order line'),
            self.proposal('domain-two', revision=3, grain='One row per order line')]}
        summary = self.reconcile(request)
        self.assertEqual(summary['status'], 'consistent')
        self.assertEqual(self.h.state['workflow']['design']['revision'], 3)
        order = next(row for row in self.h.state['workflow']['design']['entities'] if row['id'] == 'orders')
        self.assertEqual(order['grain'], 'One row per order line')
        self.assertEqual(self.reconciliation.gaps(self.h.state, ['orders']), [])
        self.assertEqual(self.h.state['workflow']['approvals'], [])

    def test_conflict_invalidates_affected_review_but_preserves_unrelated_scope(self):
        scope = ['customers', 'orders', 'products']
        self.h.action('approve-design', entities=scope, document=self.human_review(scope))
        before = fixtures.stages.entity_bindings(self.h.state, scope)
        self.reconcile(self.conflict_request())
        after = fixtures.stages.entity_bindings(self.h.state, scope)
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(before['customers'], after['customers'])
        approved = fixtures.stages.approved_entities(self.h.state)
        self.assertIn('products', approved)
        self.assertIn('customers', approved)
        self.assertNotIn('orders', approved)

    def test_changed_proposal_source_stales_only_affected_scope(self):
        self.reconcile({'schema_version': 1, 'proposals': [self.proposal('domain-one')]})
        before = fixtures.stages.entity_bindings(self.h.state, ['orders', 'products'])
        (self.h.repo / 'orders.sql').write_text('select 2 as orders_id')
        self.h.state = fixtures.guided.resume_engagement(self.h.run)
        summary = self.reconciliation.summarize(self.h.state)
        self.assertEqual(summary['status'], 'stale')
        self.assertTrue(self.reconciliation.gaps(self.h.state, ['orders']))
        self.assertEqual(self.reconciliation.gaps(self.h.state, ['products']), [])
        after = fixtures.stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])

    def test_conflict_blocks_new_human_review_but_preserves_explicit_provisional_request(self):
        self.reconcile(self.conflict_request())
        with self.assertRaises(ValueError):
            self.h.action('approve-design', entities=['orders'], document=self.human_review(['orders']))
        binding = fixtures.stages.draft_bindings(self.h.state, ['orders'])
        self.h.action('request-draft', entities=['orders'], document={'schema_version': 1,
            'kind': 'provisional_code_request', 'requester': 'Synthetic operator',
            'request_reference': 'synthetic://request/provisional', 'request_text': 'Generate provisional code',
            'bindings': binding})
        self.assertIn('orders', fixtures.stages.draft_entities(self.h.state))
        self.assertEqual(self.h.state['workflow']['approvals'], [])
        self.assertFalse(self.h.state['readiness']['execution_authorized'])
        self.assertEqual(self.reconciliation.summarize(self.h.state)['status'], 'conflicts')

    def test_duplicate_proposal_entity_keeps_original_scope_and_blocks_affected_review(self):
        proposal = self.proposal('duplicate-domain')
        duplicate = copy.deepcopy(proposal['design']['entities'][0])
        self.assertEqual(duplicate['id'], 'customers')
        duplicate['grain'] = 'One row per customer version'
        # The duplicate occupies index 1, where a deduplicated inventory would
        # incorrectly point at orders instead of the conflicting customers row.
        proposal['design']['entities'].insert(1, duplicate)
        before = copy.deepcopy(self.h.state['workflow']['design'])
        summary = self.reconcile({'schema_version': 1, 'proposals': [proposal]})
        self.assertEqual(summary['status'], 'conflicts')
        self.assertEqual(self.h.state['workflow']['design'], before)
        duplicates = [row for row in summary['findings']
                      if row['code'] in {'duplicate_entity_id', 'duplicate_model_name'}]
        self.assertTrue(duplicates)
        for finding in duplicates:
            self.assertEqual(finding['model_ids'], ['customers'])
        self.assertTrue(self.reconciliation.gaps(self.h.state, ['customers']))
        self.assertEqual(self.reconciliation.gaps(self.h.state, ['products']), [])
        with self.assertRaises(ValueError):
            self.h.action('approve-design', entities=['customers'],
                          document=self.human_review(['customers']))
        self.assertNotIn('customers', fixtures.stages.approved_entities(self.h.state))

    def test_many_unknowns_use_bounded_scope_index_and_keep_exact_owners(self):
        from unittest.mock import patch
        count = 2400
        design = {'entities': [{'id': 'model-' + str(i), 'name': 'model_' + str(i),
                               'layer': 'gold'} for i in range(count)],
                  'decisions': [], 'relationships': []}
        diagnostics = {'findings': [], 'unknowns': [
            {'path': '/entities/' + str(i) + '/grain', 'code': 'unknown_grain'}
            for i in range(count)]}
        with patch.object(self.reconciliation, 'reconcile_proposals', return_value=diagnostics), \
             patch.object(self.reconciliation, 'hash_json', wraps=self.reconciliation.hash_json) as hashes:
            result = self.reconciliation._checks([design])
            self.assertLess(hashes.call_count, count * 4)
        self.assertEqual([r['model_ids'] for r in result['unknowns']],
                         [['model-' + str(i)] for i in range(count)])

    def test_scope_index_unions_decision_and_relationship_claims(self):
        first = {'entities': [{'id': 'a'}, {'id': 'b'}],
                 'decisions': [{'id': 'shared', 'model_ids': ['a']}], 'relationships': []}
        second = {'entities': [{'id': 'c'}],
                  'decisions': [{'id': 'shared', 'model_ids': ['c']}], 'relationships': []}
        index = self.reconciliation._scope_index([first, second])
        self.assertEqual(self.reconciliation._scope({'path': '/decisions/0'}, [first, second], index), ['a', 'c'])
        self.assertEqual(self.reconciliation._scope({'path': '/entities/2'}, [first, second], index), ['c'])

    def test_legacy_absence_and_repeat_views_preserve_saved_state(self):
        legacy = copy.deepcopy(self.h.state)
        legacy['workflow'].pop('review_assurance', None)
        before = copy.deepcopy(legacy)
        self.assertEqual(self.reconciliation.summarize(legacy)['status'], 'unassessed')
        self.assertEqual(self.reconciliation.scope_bindings(legacy), {})
        self.reconciliation.refresh(legacy)
        self.assertEqual(legacy, before)
        fixtures.stages.public_view(legacy)
        self.assertEqual(legacy, before)
        current = copy.deepcopy(self.h.state)
        self.reconciliation.summarize(current)
        fixtures.stages.public_view(current)
        self.assertEqual(current, self.h.state)


if __name__ == '__main__':
    unittest.main()
