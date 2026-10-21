"""Domain-by-domain journeys preserve scoped review, provisional work and reuse."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import domain_workflow as domains
import engagement_stages as stages
import guided_workflow as guided
import run_control
from ae_common import hash_json
import test_engagement_stages as stage_fixtures


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.h = stage_fixtures.StageTests('test_host_attributed_review_opens_candidates_not_deployment')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.state = self.h.state
        self.doc = copy.deepcopy(self.h.doc)
        self.doc['revision'] = 2
        for e in self.doc['entities']:
            e['domain'] = {'orders': 'sales', 'customers': 'shared', 'products': 'catalog'}[e['id']]
        stages.import_design(self.state, self.doc)
        self.candidates = {'schema_version': 1, 'domains': [
            {'id': 'sales', 'name': 'Sales', 'description': 'Orders and customers',
             'asset_ids': ['report:orders', 'report:customers'], 'source_paths': ['orders.sql', 'customers.sql'],
             'shared_dependency_ids': ['customers']},
            {'id': 'catalog', 'name': 'Catalog', 'description': 'Product assortment',
             'asset_ids': ['report:products'], 'source_paths': ['products.sql'], 'shared_dependency_ids': []}]}
        domains.register(self.state, self.candidates)
        self.state['workflow']['artifact_root'] = str(self.h.artifacts)

    def request(self, key='sales', select=False):
        return {'schema_version': 1, 'domain_id': key, 'request_reference': 'synthetic://user/choice',
                **({'candidates_sha256': domains.ledger(self.state)['candidates_sha256']} if select else {})}

    def select(self, key='sales'):
        domains.select_domain(self.state, self.request(key, True))

    def approve(self, selected):
        stages.record_design_review(self.state, selected, {'schema_version': 1, 'kind': 'human_design_review',
            'decision': 'approve', 'reviewer': 'Synthetic user', 'review_reference': 'synthetic://human/approval',
            'bindings': stages.review_bindings(self.state, selected)})

    def tasks(self, key='sales'):
        original = self.h.tasks()['tasks']
        if key == 'sales':
            return {'schema_version': 1, 'tasks': [t for t in original if t['id'] != 'build-products']}
        return {'schema_version': 1, 'tasks': [next(t for t in original if t['id'] == 'build-products'),
            {'id': 'catalog-semantic', 'stage': 'semantic', 'entity_ids': ['products'], 'depends_on': ['build-products'],
             'components': [], 'outputs': ['products.topic.yaml']}]}

    def record(self, key):
        plan = stages.plan_tasks(self.state, self.h.artifacts)
        task = next(t for t in plan['tasks'] if t['id'] == key)
        self.assertEqual(task['action'], 'regenerate', task['reason'])
        spec = next(t for t in self.state['workflow']['tasks'] if t['id'] == key)
        for path in spec['outputs']:
            (self.h.artifacts / path).write_text('base_view: orders\n' if path.endswith('.yaml') else 'select 1 as id\n')
        stages.record_task(self.state, self.h.artifacts, {'task_id': key, 'run_id': key + '-' + str(len(self.state['workflow']['runs'])),
            'plan_sha256': plan['plan_sha256'], 'fingerprint': task['fingerprint'],
            'outputs': stages._output_hashes(self.h.artifacts, spec['outputs']), 'evidence_reference': 'synthetic://files'})

    def finish_sales(self):
        self.select(); self.approve(['orders'])
        stages.register_tasks(self.state, self.tasks())
        for key in ('build-customers', 'build-orders', 'semantic'):
            self.record(key)
        domains.complete_domain(self.state, self.request())

    def test_discovery_never_selects_or_opens_design(self):
        summary = domains.public_summary(self.state)
        self.assertTrue(summary['needs_selection'])
        self.assertIsNone(summary['active_domain_id'])
        with self.assertRaisesRegex(ValueError, 'which domain'):
            stages.require_stage(self.state, 'design', ['orders'])
        with self.assertRaisesRegex(ValueError, 'which domain'):
            stages.import_design(self.state, {**self.doc, 'revision': 3})

    def test_stale_selection_is_rejected(self):
        request = self.request(select=True); request['candidates_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'candidates changed'):
            domains.select_domain(self.state, request)

    def test_selection_is_not_approval_or_automatic_next(self):
        self.select()
        self.assertEqual(stages.approved_entities(self.state), set())
        with self.assertRaisesRegex(ValueError, 'pause'):
            self.select('catalog')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            domains.complete_domain(self.state, self.request())

    def test_selected_design_and_shared_interface_only(self):
        self.select()
        stages.require_stage(self.state, 'design', ['orders'])
        with self.assertRaisesRegex(ValueError, 'outside the selected domain'):
            stages.require_stage(self.state, 'design', ['products'])
        proposed = copy.deepcopy(self.doc); proposed['revision'] = 3
        proposed['entities'][2]['grain'] = 'Changed other domain'
        with self.assertRaisesRegex(ValueError, 'other domains'):
            stages.import_design(self.state, proposed)
        proposed['entities'][2] = copy.deepcopy(self.doc['entities'][2])
        proposed['entities'][1]['grain'] = 'One row per verified order'
        stages.import_design(self.state, proposed)

    def test_missing_shared_interface_is_explicit(self):
        self.candidates['domains'][0]['shared_dependency_ids'] = []
        domains.register(self.state, self.candidates); self.select()
        with self.assertRaisesRegex(ValueError, 'shared dependencies'):
            stages.require_stage(self.state, 'design', ['orders'])

    def test_restricted_projection_hides_queued_and_shared_ids(self):
        self.assertEqual(domains.public_summary(self.state, {'products'})['domains'][0]['id'], 'catalog')
        self.assertFalse(domains.public_summary(self.state, {'orders'})['domains'])

    def test_outside_approval_and_tasks_are_rejected(self):
        self.select()
        with self.assertRaisesRegex(ValueError, 'outside the selected domain'):
            self.approve(['products'])
        with self.assertRaisesRegex(ValueError, 'outside the selected domain'):
            stages.register_tasks(self.state, self.tasks('catalog'))

    def test_complete_requires_omni_and_files_and_approval(self):
        self.select(); self.approve(['orders']); stages.register_tasks(self.state, self.tasks())
        for key in ('build-customers', 'build-orders'):
            self.record(key)
        with self.assertRaisesRegex(ValueError, 'semantic'):
            domains.complete_domain(self.state, self.request())
        self.record('semantic')
        (self.h.artifacts / 'orders.sql').unlink()
        with self.assertRaisesRegex(ValueError, 'implementation'):
            domains.complete_domain(self.state, self.request())

    def test_two_domains_retain_original_code_and_history(self):
        self.finish_sales()
        first = {r['task_id']: r['run_id'] for r in self.state['workflow']['runs']}
        self.assertTrue(domains.public_summary(self.state)['needs_selection'])
        self.select('catalog'); self.approve(['products'])
        stages.register_tasks(self.state, self.tasks('catalog'))
        for key in ('build-products', 'catalog-semantic'):
            self.record(key)
        domains.complete_domain(self.state, self.request('catalog'))
        view = domains.public_summary(self.state)
        self.assertEqual(view['counts']['completed'], 2)
        self.assertFalse(view['needs_selection'])
        plan = stages.plan_tasks(self.state, self.h.artifacts)
        self.assertTrue(all(t['action'] == 'reuse' for t in plan['tasks']))
        for t in plan['tasks']:
            if t['id'] in first:
                self.assertEqual(t['original_run_id'], first[t['id']])

    def test_shared_change_stales_only_affected_domain(self):
        self.test_two_domains_retain_original_code_and_history()
        (self.h.repo / 'customers.sql').write_text('select 2 as customers_id')
        view = domains.public_summary(self.state)
        self.assertEqual({r['id']: r['status'] for r in view['domains']}, {'sales': 'stale', 'catalog': 'completed'})

    def test_paused_drafts_stay_available_but_are_not_complete(self):
        self.select()
        scope = ['orders']
        stages.record_draft_request(self.state, scope, {'schema_version': 1, 'kind': 'provisional_code_request',
            'requester': 'Synthetic user', 'request_reference': 'synthetic://user/draft',
            'request_text': 'Generate provisional code now', 'bindings': stages.draft_bindings(self.state, scope)})
        stages.register_tasks(self.state, self.tasks())
        for key in ('build-customers', 'build-orders', 'semantic'):
            self.record(key)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            domains.complete_domain(self.state, self.request())
        domains.pause_domain(self.state, self.request()); self.select('catalog')
        self.assertEqual(domains.public_summary(self.state)['domains'][0]['status'], 'paused')
        self.assertTrue((self.h.artifacts / 'orders.sql').exists())

    def test_active_workers_must_checkpoint_before_switching(self):
        self.select()
        self.state['operations'] = {'attempts': [{'status': 'active', 'role': 'warehouse_architect'}]}
        with self.assertRaisesRegex(ValueError, 'Checkpoint'):
            domains.pause_domain(self.state, self.request())

    def test_source_inventory_allowed_but_queued_dispatch_rejected(self):
        request = {'schema_version': 1, 'work_id': 'inventory', 'attempt_id': 'a1', 'role': 'source_specialist',
                   'scope_ids': ['all'], 'source_paths': ['products.sql']}
        self.assertEqual(run_control.claim_work(self.state, request)['action'], 'dispatch')
        request.update(work_id='design', attempt_id='a2', role='warehouse_architect', scope_ids=['catalog'])
        self.select()
        with self.assertRaises(ValueError):
            run_control.claim_work(self.state, request)

    def test_predesign_registration_and_first_scoped_import(self):
        self.state['workflow']['design'] = None
        self.select()
        doc = copy.deepcopy(self.doc)
        doc['entities'] = [e for e in doc['entities'] if e['id'] != 'products']
        doc['assets'] = [a for a in doc['assets'] if a['id'] != 'report:products']
        stages.import_design(self.state, doc)
        self.assertEqual(domains.public_summary(self.state)['domains'][1]['model_ids'], [])

    def test_relabeling_cannot_take_ownership_of_another_domain(self):
        self.select()
        doc = copy.deepcopy(self.doc); doc['revision'] = 3
        doc['entities'][2]['domain'] = 'sales'
        doc['entities'][2]['grain'] = 'Changed unrelated product model'
        with self.assertRaisesRegex(ValueError, 'domain ownership'):
            stages.import_design(self.state, doc)

    def test_scope_expansion_stales_receipt_but_new_domain_does_not(self):
        self.finish_sales()
        expanded = copy.deepcopy(self.candidates)
        expanded['domains'].append({'id': 'support', 'name': 'Support', 'description': 'Cases',
            'asset_ids': [], 'source_paths': [], 'shared_dependency_ids': []})
        domains.register(self.state, expanded)
        self.assertEqual(domains.public_summary(self.state)['domains'][0]['status'], 'completed')
        expanded['domains'][0]['asset_ids'].append('report:returns')
        expanded['domains'][0]['source_paths'].append('returns.sql')
        domains.register(self.state, expanded)
        self.assertEqual(domains.public_summary(self.state)['domains'][0]['status'], 'stale')
        self.select()
        with self.assertRaisesRegex(ValueError, 'Map the discovered domain assets'):
            domains.complete_domain(self.state, self.request())

    def test_tasks_from_inactive_domain_cannot_regenerate(self):
        self.finish_sales(); self.select('catalog')
        (self.h.artifacts / 'orders.sql').write_text('select 9 as id')
        plan = stages.plan_tasks(self.state, self.h.artifacts)
        task = next(t for t in plan['tasks'] if t['id'] == 'build-orders')
        self.assertEqual(task['action'], 'blocked')
        self.assertIn('selected domain', task['reason'])

    def test_legacy_absence_is_unchanged(self):
        del self.state['workflow']['domain_journey']
        self.assertIsNone(domains.public_summary(self.state))
        stages.require_stage(self.state, 'design', ['orders', 'products'])
        stages.register_tasks(self.state, self.h.tasks())

    def test_guided_commands_persist_and_prioritize_selection(self):
        # Exercise durable command routing on a separate untouched fixture state.
        result = guided.stage_action(self.h.run, 'register-domains', document=self.candidates)
        self.assertEqual(result['next_actions'][0]['id'], 'domain_journey')
        request = self.request(select=True)
        result = guided.stage_action(self.h.run, 'select-domain', document=request)
        self.assertEqual(domains.ledger(guided.load_engagement(self.h.run))['active_domain_id'], 'sales')


if __name__ == '__main__':
    unittest.main()
