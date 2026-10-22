import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import domain_batches as batches
import domain_workflow as domains
import engagement_stages as stages
import test_domain_workflow as fixtures


class DomainBatchTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.DomainTests()
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.h.select()
        self.state = self.h.state
        doc = copy.deepcopy(self.state['workflow']['design']); doc.pop('sha256')
        doc['revision'] += 1
        extra = copy.deepcopy(doc['entities'][1]); extra.update(id='refunds', name='refunds', depends_on=['orders'])
        doc['entities'].append(extra)
        stages.import_design(self.state, doc)
        self.selection = {'schema_version': 1, 'domain_id': 'sales', 'batch_id': 'orders-first', 'name': 'Orders',
                          'entity_ids': ['orders'], 'request_reference': 'synthetic://human/batch'}

    def test_selected_batch_includes_dependencies_but_not_rest_of_domain(self):
        batches.select(self.state, self.selection)
        self.assertEqual(domains.scope(self.state), {'orders', 'customers'})
        domains.require_scope(self.state, ['orders'], 'implementation')
        with self.assertRaisesRegex(ValueError, 'outside'):
            domains.require_scope(self.state, ['refunds'], 'implementation')
        self.assertEqual(domains.scope(self.state, domains._domain(self.state)), {'orders', 'customers', 'refunds'})

    def test_cumulative_design_preserves_other_batch(self):
        batches.select(self.state, self.selection)
        doc = copy.deepcopy(self.state['workflow']['design']); doc.pop('sha256'); doc['revision'] += 1
        next(e for e in doc['entities'] if e['id'] == 'refunds')['grain'] = 'Changed outside selected batch'
        with self.assertRaisesRegex(ValueError, 'Preserve designs'):
            stages.import_design(self.state, doc)

    def test_pause_and_user_selection_are_explicit_without_clearing_prior_work(self):
        batches.select(self.state, self.selection)
        second = {**self.selection, 'batch_id': 'refunds-next', 'name': 'Refunds', 'entity_ids': ['refunds']}
        with self.assertRaisesRegex(ValueError, 'Complete or explicitly pause'):
            batches.select(self.state, second)
        batches.finish(self.state, {'schema_version': 1, 'batch_id': 'orders-first', 'request_reference': 'synthetic://human/pause'}, pause=True)
        with self.assertRaisesRegex(ValueError, 'Select a batch'):
            domains.require_scope(self.state, ['refunds'], 'implementation')
        batches.select(self.state, second)
        self.assertEqual(domains.scope(self.state), {'refunds', 'orders', 'customers'})
        self.assertEqual(len(self.state['workflow']['domain_batch_history']), 3)

    def test_batch_cannot_complete_before_its_design_and_code(self):
        batches.select(self.state, self.selection)
        with self.assertRaisesRegex(ValueError, 'Batch is incomplete'):
            batches.finish(self.state, {'schema_version': 1, 'batch_id': 'orders-first', 'request_reference': 'synthetic://human/complete'})

    def test_complete_one_batch_keeps_domain_incomplete(self):
        # A distinct report belongs to the future batch, not this one.
        doc = copy.deepcopy(self.state['workflow']['design']); doc.pop('sha256'); doc['revision'] += 1
        doc['assets'].append({'id': 'report:refunds', 'name': 'Refunds', 'kind': 'report', 'mapping_status': 'verified'})
        next(e for e in doc['entities'] if e['id'] == 'refunds')['asset_ids'] = ['report:refunds']
        domains._domain(self.state)['asset_ids'].append('report:refunds')
        stages.import_design(self.state, doc)
        batches.select(self.state, self.selection)
        self.h.approve(['orders'])
        stages.register_tasks(self.state, self.h.tasks())
        for task in ('build-customers', 'build-orders', 'semantic'):
            self.h.record(task)
        batches.finish(self.state, {'schema_version': 1, 'batch_id': 'orders-first', 'request_reference': 'synthetic://human/complete'})
        self.assertEqual(batches.public_summary(self.state)['status'], 'completed')
        with self.assertRaisesRegex(ValueError, 'Domain is incomplete'):
            domains.complete_domain(self.state, self.h.request())
        self.assertEqual(domains.ledger(self.state)['active_domain_id'], 'sales')

    def test_refactor_intent_does_not_require_future_batch_assessment(self):
        from migration_intent import configure, summary
        configure(self.state, {'schema_version': 1, 'kind': 'migration_intent', 'domain_id': 'sales',
            'structural_objective': 'refactor', 'behavior': 'preserve',
            'objectives': [{'id': 'reshape', 'statement': 'Refactor all selected domain objects'}],
            'source_roles': [{'id': 'old', 'root_id': 'primary', 'role': 'legacy_baseline'}],
            'behavior_constraints': ['Preserve current rules'], 'request_reference': 'synthetic://user/refactor'})
        self.test_complete_one_batch_keeps_domain_incomplete()
        self.assertFalse(next(r for r in summary(self.state)['domains'] if r['domain_id'] == 'sales')['refactor_complete'])

    def test_large_scope_advisory_does_not_guess_cost_or_block_work(self):
        domain = copy.deepcopy(domains._domain(self.state))
        domain['source_paths'] = ['model-%d.sql' % n for n in range(101)]
        preview = batches.scope_preview(self.state, domain)
        self.assertTrue(preview['batching_recommended'])
        self.assertNotIn('cost', preview)
        batches.select(self.state, self.selection)
        domains.require_scope(self.state, ['orders'])
