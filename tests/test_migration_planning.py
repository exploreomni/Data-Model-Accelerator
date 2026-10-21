"""Synthetic migration planning contracts; no source execution or external writes."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import migration_planning as planning
import legacy_alignment as alignment
import domain_workflow
import test_legacy_alignment as fixtures
from test_legacy_alignment import baseline, mapping


def config(domain='commerce'):
    return {'schema_version': 1, 'domain_id': domain, 'mode': 'refactor', 'output_format': 'both',
            'ticket_platform': 'generic', 'request_reference': 'synthetic://human/format-selection'}


def plan(domain='commerce'):
    return {'schema_version': 1, 'domain_id': domain,
        'consumers': [{'id': 'report:orders', 'kind': 'dashboard', 'label': 'Order dashboard',
            'legacy_table_ids': ['old.orders'], 'model_ids': ['orders'], 'topic_ids': ['orders_topic'],
            'status': 'proposed', 'disposition': 'reconnect'},
            {'id': 'chart:net', 'parent_id': 'report:orders', 'kind': 'chart', 'label': 'Net amount',
             'legacy_table_ids': ['old.orders'], 'model_ids': ['orders', 'customers'], 'topic_ids': ['orders_topic'],
             'status': 'unresolved'}],
        'work_items': [{'id': 'req.orders', 'title': 'Preserve order attribution', 'outcome': 'Orders retain customer attribution.',
            'scope': 'Selected order domain only', 'model_ids': ['orders'], 'mapping_ids': ['orders.key'],
            'consumer_ids': ['report:orders', 'chart:net'], 'dependencies': [],
            'acceptance_criteria': [{'id': 'oracle', 'expected': 'Compare independently supplied attribution cases.',
                                     'evidence_ref': 'synthetic://private/oracle', 'evidence_label': 'Independent fixture oracle'}]}],
        'decisions': [], 'questions': [{'id': 'definition', 'text': 'Confirm the unresolved net definition.',
                                        'model_ids': ['orders'], 'consumer_ids': ['chart:net']}],
        'waves': [{'id': 'pilot', 'title': 'Pilot', 'item_ids': ['req.orders'], 'depends_on': []}],
        'narrative': 'A synthetic plan, pending independent acceptance.'}


class MigrationPlanningTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LegacyAlignmentTests('test_absent_feature_and_declined_comparison_preserve_material_bindings')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.state = self.fixture.state; self.run = self.fixture.run; self.source = self.fixture.source

    def enable(self):
        self.fixture.enable(); planning.configure(self.state, config())

    def row(self, domain='commerce', allowed=None):
        return next(d for d in planning.public_summary(self.state, allowed)['domains'] if d['domain_id'] == domain)

    def save(self, request):
        current = self.state.get('workflow', {}).get('migration_planning', {}).get('plans', {}).get(request['domain_id'])
        request = copy.deepcopy(request)
        if current: request['expected_plan_sha256'] = current['sha256']
        planning.register_plan(self.state, request, self.run)

    def test_absent_legacy_compatibility_and_baselineless_draft(self):
        before = copy.deepcopy(self.state)
        self.assertIsNone(planning.public_summary(self.state)); self.assertIsNone(planning.fingerprint(self.state))
        self.assertIsNone(planning.context_packet(self.state, 'commerce')); self.assertEqual(before, self.state)
        self.state['workflow']['design'] = None
        planning.configure(self.state, config())
        self.assertEqual(planning.context_packet(self.state, 'commerce')['plan']['freshness'], 'unassessed')
        self.save({'schema_version': 1, 'domain_id': 'commerce', 'consumers': [], 'work_items': []})
        row = self.row(); self.assertEqual(row['freshness'], 'current'); self.assertEqual(row['inventory']['baseline_status'], 'not_supplied')
        self.assertEqual(row['source_lineage']['status'], 'unknown'); self.assertEqual(self.state['workflow']['approvals'], [])

    def test_many_to_many_grouped_graph_independent_coverage_and_missing_consumers(self):
        self.enable(); request = mapping(); request['mappings'][0]['targets'].append({'model_id': 'customers', 'kind': 'table'})
        pack = baseline(); other = copy.deepcopy(pack['tables'][0]); other.update(id='old.other', native_id='other')
        pack['tables'].append(other); alignment.register_baseline(self.state, pack, self.run)
        request['mappings'][0]['sources'].append({'table_id': 'old.other', 'kind': 'column', 'field_id': 'key'})
        alignment.register_alignment(self.state, request, self.run)
        before = copy.deepcopy(self.state['workflow']['approvals']); self.save(plan()); row = self.row()
        self.assertEqual(row['inventory']['mappings'][0]['relationship'], 'many_to_many')
        self.assertEqual(row['inventory']['coverage']['columns']['total'], 4)
        self.assertEqual(row['inventory']['coverage']['columns']['unmatched'], 2)
        mapping_edges = [e for e in row['graph_edges'] if 'mapping_id' in e]
        self.assertEqual(len(mapping_edges), 4)
        self.assertTrue(all(e['source']['kind'] == 'mapping' or e['target']['kind'] == 'mapping' for e in mapping_edges))
        self.assertIn('report:customers', {c['id'] for c in row['missing_consumers']})
        self.assertEqual(row['consumer_coverage']['total'], 3)
        self.assertEqual(before, self.state['workflow']['approvals'])
        self.assertEqual(row['work_items'][0]['effort']['complexity'], None)
        self.assertNotIn('synthetic://private/oracle', json.dumps(row))

    def test_dangling_duplicates_cycles_and_invalid_estimates_fail_atomically(self):
        self.enable(); self.save(plan()); before = copy.deepcopy(self.state)
        changes = [lambda p: p['work_items'][0]['model_ids'].append('absent'),
                   lambda p: p['work_items'][0]['mapping_ids'].append('absent'),
                   lambda p: p['work_items'][0]['dependencies'].append('req.orders'),
                   lambda p: p['consumers'].append(copy.deepcopy(p['consumers'][0])),
                   lambda p: p['consumers'][1].update(parent_id='missing'),
                   lambda p: p['work_items'][0].update(effort={'value': 3, 'unit': 'hours', 'confidence': 'high', 'basis': 'Guess'}),
                   lambda p: p['work_items'][0].update(operation='update')]
        for change in changes:
            request = plan(); change(request)
            with self.subTest(change=change), self.assertRaises(ValueError): self.save(request)
            self.assertEqual(self.state, before)

    def test_scoped_staleness_labels_and_optimistic_regeneration(self):
        self.enable(); self.save(plan()); current = self.row()['plan_sha256']
        self.save(plan()); self.assertEqual(self.row()['plan_sha256'], current)
        self.state['workflow']['design']['entities'][2]['grain'] = 'Unrelated product change'
        self.assertEqual(self.row()['freshness'], 'current')
        (self.source / 'orders.sql').write_text('select 2 as orders_id')
        self.assertEqual(self.row()['freshness'], 'stale')
        with self.assertRaisesRegex(ValueError, 'Plan changed'): planning.register_plan(self.state, plan(), self.run)
        self.save(plan()); self.assertEqual(self.row()['freshness'], 'stale')
        alignment.register_alignment(self.state, mapping(), self.run)
        self.save(plan()); self.assertEqual(self.row()['freshness'], 'current')
        self.assertEqual(self.state['workflow']['approvals'], [])

    def test_human_edits_survive_regeneration_and_removed_items_are_archived(self):
        self.enable(); self.save(plan()); old = self.row()['plan_sha256']
        edits = {'schema_version': 1, 'domain_id': 'commerce', 'plan_sha256': old,
                 'request_reference': 'synthetic://human/edit', 'edits': [{'id': 'req.orders', 'notes': 'Keep this rationale.',
                    'owner': 'Synthetic reviewer', 'due_date': '2027-02-03'}]}
        planning.edit_items(self.state, edits, self.run)
        with self.assertRaisesRegex(ValueError, 'Plan changed'): planning.edit_items(self.state, edits, self.run)
        request = plan(); request['work_items'][0]['owner'] = 'Generated overwrite'
        self.save(request); self.assertEqual(self.row()['work_items'][0]['owner'], 'Synthetic reviewer')
        request['work_items'] = []; request['waves'] = []; self.save(request)
        self.assertEqual(self.row()['archived_edits'][0]['notes'], 'Keep this rationale.')
        self.save(plan()); self.assertEqual(self.row()['work_items'][0]['notes'], 'Keep this rationale.')
        bad = dict(edits, plan_sha256=self.row()['plan_sha256'], edits=[{'id': 'req.orders', 'outcome': 'Unauthorized rewrite'}])
        with self.assertRaises(ValueError): planning.edit_items(self.state, bad, self.run)

    def test_source_lineage_validates_identity_evidence_and_dag(self):
        self.enable(); request = plan(); raw = (self.source / 'orders.sql').read_bytes()
        request['source_lineage'] = {'nodes': [{'id': 'raw', 'kind': 'source', 'label': 'Raw orders'},
            {'id': 'sql', 'kind': 'transformation', 'label': 'Order SQL'},
            {'id': 'old', 'kind': 'legacy_table', 'label': 'Historical orders', 'legacy_table_id': 'old.orders'}],
            'edges': [{'id': 'edge.raw.sql', 'source_id': 'raw', 'target_id': 'sql', 'status': 'observed',
                'evidence_refs': [{'label': 'Supplied SQL', 'reference': 'synthetic://sql', 'source_path': 'orders.sql', 'sha256': hashlib.sha256(raw).hexdigest()}]},
                {'id': 'edge.sql.old', 'source_id': 'sql', 'target_id': 'old', 'status': 'proposed', 'evidence_refs': []}]}
        self.save(request); self.assertEqual(self.row()['source_lineage']['status'], 'supplied')
        public = json.dumps(self.row()); self.assertNotIn('source_path', public); self.assertNotIn('synthetic://sql', public)
        cyclic = copy.deepcopy(request); cyclic['source_lineage']['edges'].append({'id': 'cycle', 'source_id': 'old', 'target_id': 'raw', 'status': 'proposed', 'evidence_refs': []})
        with self.assertRaisesRegex(ValueError, 'Cyclic'): self.save(cyclic)
        (self.source / 'orders.sql').write_text('changed')
        self.assertEqual(self.row()['freshness'], 'stale')
        with self.assertRaisesRegex(ValueError, 'evidence changed'): self.save(request)

    def test_subset_omits_shared_consumers_notes_and_dependent_items(self):
        self.enable(); request = plan(); request['consumers'][0]['model_ids'].append('products')
        request['consumers'][0]['label'] = 'PRIVATE_SHARED_DASHBOARD'
        request['narrative'] = 'PRIVATE_WIDE_NARRATIVE'; request['waves'][0]['title'] = 'PRIVATE_WAVE'
        self.save(request); subset = self.row(allowed={'orders', 'customers'})
        content = json.dumps(subset); self.assertNotIn('PRIVATE_', content)
        self.assertEqual(subset['consumers'], []); self.assertEqual(subset['work_items'], [])
        self.assertEqual(planning.public_summary(self.state, {'orders'})['domains'], [])

    def test_domain_selection_does_not_change_discovery_or_approval(self):
        self.enable()
        domain_workflow.register(self.state, {'schema_version': 1, 'domains': [
            {'id': d, 'name': d.title(), 'description': 'Synthetic domain', 'asset_ids': [], 'source_paths': [], 'shared_dependency_ids': []}
            for d in ('commerce', 'catalog')]})
        ledger = domain_workflow.ledger(self.state)
        domain_workflow.select_domain(self.state, {'schema_version': 1, 'domain_id': 'commerce', 'request_reference': 'synthetic://select', 'candidates_sha256': ledger['candidates_sha256']})
        before = copy.deepcopy(ledger)
        with self.assertRaisesRegex(ValueError, 'Select'): planning.configure(self.state, config('catalog'))
        self.save(plan()); self.assertEqual(before, ledger)
        self.assertEqual(self.state['workflow']['approvals'], [])

    def test_context_is_bounded_partitioned_and_never_executes(self):
        self.enable(); self.save(plan()); before = copy.deepcopy(self.state)
        packet = planning.context_packet(self.state, 'commerce')
        self.assertIn('work_item:req.orders', packet['available_records'])
        partial = planning.context_packet(self.state, 'commerce', record_ids=['work_item:req.orders'])
        self.assertGreater(partial['omitted_records'], 0); self.assertFalse(partial['reuse_eligible'])
        self.assertEqual(len(partial['plan']['work_items']), 1); self.assertEqual(partial['plan']['models'], [])
        with self.assertRaisesRegex(ValueError, 'Nothing was truncated'): planning.context_packet(self.state, 'commerce', 1024)
        self.assertEqual(before, self.state)

    def test_source_protection_and_tampered_sidecar_fail_closed(self):
        self.enable()
        with self.assertRaises(ValueError): planning.register_plan(self.state, plan(), self.source)
        self.save(plan()); ref = self.state['workflow']['migration_planning']['plans']['commerce']
        Path(ref['path']).write_text('{}')
        self.assertEqual(self.row()['freshness'], 'unavailable')
        self.assertEqual(self.state['workflow']['approvals'], [])

    def test_scoped_migration_context_preserves_missing_consumers_without_inheriting_pass(self):
        self.enable()
        definitions = {'rows': [{'id': 'net', 'name': 'Net definition', 'statement': 'Preserve documented net semantics.',
            'definition': {'population': 'Completed orders'}, 'status': 'proposed', 'model_ids': ['orders'],
            'source': {'reference': 'PRIVATE_RULE_REFERENCE'}}]}
        report = {'report': {'status': 'pass', 'crosswalk': [
            {'subject_kind': 'tile', 'subject_id': 'tile:known', 'dashboard_id': 'dashboard:known',
             'dashboard_label': 'Known dashboard', 'source_label': 'Known chart', 'model_ids': ['orders'], 'topic_ids': ['order_topic'], 'status': 'pass'},
            {'subject_kind': 'tile', 'subject_id': 'tile:other', 'dashboard_id': 'dashboard:other',
             'dashboard_label': 'PRIVATE_OTHER_DASHBOARD', 'source_label': 'Other chart', 'model_ids': ['products'], 'topic_ids': ['product_topic'], 'status': 'pass'}]}}
        import migration_review
        original = migration_review.load
        def saved(state, kind): return report if kind == 'parity' else original(state, kind)
        with patch('business_rules.summary', return_value=definitions), patch('migration_review.load', side_effect=saved):
            self.save(plan()); row = self.row(); context = row['migration_context']
            self.assertEqual(context['validation_status'], 'not_revalidated')
            self.assertEqual(len(context['consumer_crosswalk']), 1)
            self.assertNotIn('status', context['consumer_crosswalk'][0])
            self.assertIn('tile:known', {c['id'] for c in row['missing_consumers']})
            self.assertNotIn('PRIVATE_', json.dumps(row))
            self.assertTrue(planning.context_packet(self.state, 'commerce')['plan']['migration_context']['definitions'])


if __name__ == '__main__': unittest.main()
