"""Bounded synthetic planning diagnostics; no native parity or review inference."""
import copy
import hashlib
import json
import unittest

import test_legacy_alignment as fixtures
import legacy_alignment as alignment
import migration_planning as planning
from test_migration_planning import config as planning_config, plan


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LegacyAlignmentTests('test_absent_feature_and_declined_comparison_preserve_material_bindings')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.state, self.run = self.fixture.state, self.fixture.run
        self.fixture.enable()

    def summary(self):
        return self.fixture.summary()

    def upstream_baseline(self):
        baseline = fixtures.baseline()
        upstream = copy.deepcopy(baseline['tables'][0]); upstream.update(id='old.upstream', native_id='upstream')
        baseline['tables'].append(upstream)
        alignment.register_baseline(self.state, baseline, self.run)
        mapping = fixtures.mapping()
        mapping['mappings'][0]['sources'].append({'table_id': 'old.orders', 'kind': 'table'})
        alignment.register_alignment(self.state, mapping, self.run)

    def lineage(self):
        return {'nodes': [{'id': 'up', 'kind': 'legacy_table', 'legacy_table_id': 'old.upstream'},
                          {'id': 'down', 'kind': 'legacy_table', 'legacy_table_id': 'old.orders'}],
                'edges': [{'source_id': 'up', 'target_id': 'down', 'status': 'observed', 'evidence_labels': ['Supplied SQL dependency']}]}

    def test_unique_denominators_preserve_existing_counts_and_separate_consumers(self):
        request = fixtures.mapping(); duplicate = copy.deepcopy(request['mappings'][0]); duplicate['id'] = 'second.placement'
        duplicate['targets'] = [{'model_id': 'customers', 'kind': 'column', 'field': 'customers_id'}]
        request['mappings'].append(duplicate)
        before = copy.deepcopy(self.state['workflow']['approvals'])
        alignment.register_alignment(self.state, request, self.run)
        summary = self.summary(); counts = summary['reconciliation']['counts']
        self.assertEqual(summary['coverage']['columns'], {'total': 2, 'mapped': 1, 'unmatched': 1, 'unsupported': 0, 'excluded': 0})
        self.assertEqual(counts['columns']['replacement_mapping'], 1)
        self.assertEqual([counts[k]['total'] for k in ('tables', 'columns', 'rules', 'consumers')], [1, 2, 1, None])
        self.assertEqual(counts['tables']['missing_target'], 1)
        self.assertEqual(before, self.state['workflow']['approvals'])

    def test_missing_evidence_and_removed_target_are_distinct_and_questions_are_scoped(self):
        baseline = fixtures.baseline(); baseline['status'] = 'partial'
        baseline['tables'][0].update(evidence_ids=[], completeness={'columns': 'unknown', 'rules': 'unknown'})
        alignment.register_baseline(self.state, baseline, self.run)
        alignment.register_alignment(self.state, fixtures.mapping(), self.run)
        self.assertEqual(self.summary()['reconciliation']['counts']['columns']['missing_evidence'], 2)
        self.state['workflow']['design']['entities'] = [m for m in self.state['workflow']['design']['entities'] if m['id'] != 'orders']
        result = self.summary()['reconciliation']
        key = next(r for r in result['items'] if r.get('field_id') == 'key')
        self.assertEqual(key['classification'], 'missing_target')
        question = next(q for q in result['follow_up_questions'] if q['source'].get('field_id') == 'key')
        self.assertEqual(question['domain_id'], 'commerce')
        self.assertNotIn('orders', question['model_ids'])
        self.assertIn('orders', question['referenced_model_ids'])
        self.assertIn('repair_missing_target', question['requirements'])
        self.assertEqual(question['status'], 'proposed')

    def test_explicit_exclusion_does_not_invent_accepted_review(self):
        request = fixtures.mapping()
        request['mappings'][0].update(status='unmatched', targets=[], disposition='out_of_scope')
        alignment.register_alignment(self.state, request, self.run)
        result = self.summary()
        self.assertEqual(result['coverage']['columns']['excluded'], 0)
        self.assertEqual(result['reconciliation']['counts']['columns']['explicit_exclusion'], 1)
        item = next(r for r in result['reconciliation']['items'] if r.get('field_id') == 'key')
        self.assertEqual(item['review_statuses'], ['proposed'])
        self.assertIn('review_explicit_exclusion', item['requirements'])
        alignment.record_decisions(self.state, self.fixture.review())
        result = self.summary()
        self.assertEqual(result['coverage']['columns']['excluded'], 1)
        item = next(r for r in result['reconciliation']['items'] if r.get('field_id') == 'key')
        self.assertNotIn('review_explicit_exclusion', item['requirements'])

    def test_upstream_only_needs_observed_current_source_edges_not_target_ancestors(self):
        self.upstream_baseline(); original = self.summary()
        self.assertEqual(original['reconciliation']['counts']['tables']['upstream_only'], 0)
        result = alignment.reconciliation_summary(original, source_lineage=self.lineage(), evidence_current=True)
        self.assertEqual(result['counts']['tables']['upstream_only'], 1)
        self.assertEqual(result['counts']['tables']['replacement_mapping'], 1)
        self.assertEqual(result['counts']['columns']['upstream_only'], 0)
        self.assertEqual(result['counts']['rules']['upstream_only'], 0)
        self.assertEqual(original['coverage']['tables']['mapped'], 1)
        for status, current in [('proposed', True), ('observed', False)]:
            lineage = self.lineage(); lineage['edges'][0]['status'] = status
            result = alignment.reconciliation_summary(original, source_lineage=lineage, evidence_current=current)
            self.assertEqual(result['counts']['tables']['upstream_only'], 0)

    def test_consumer_denominator_deduplicates_crosswalk_and_known_inventory(self):
        result = alignment.reconciliation_summary(self.summary(), evidence_current=True,
            known_consumers=[{'id': 'report:orders', 'model_ids': ['orders']}, {'id': 'report:customers', 'model_ids': ['customers']}],
            consumers=[{'id': 'report:orders', 'model_ids': ['orders'], 'status': 'observed', 'evidence_labels': ['Supplied crosswalk']},
                       {'id': 'chart:net', 'model_ids': ['orders'], 'status': 'proposed', 'evidence_labels': []}])
        self.assertEqual(result['counts']['consumers']['total'], 3)
        self.assertEqual(result['counts']['consumers']['replacement_mapping'], 1)
        self.assertEqual(result['counts']['consumers']['missing_evidence'], 2)
        self.assertEqual(result['counts']['columns']['total'], 2)

    def test_planning_projection_is_current_and_partitionable_without_self_staling(self):
        self.upstream_baseline(); planning.configure(self.state, planning_config())
        evidence_path = self.fixture.source / 'lineage.sql'; evidence_path.write_text('select * from upstream')
        request = plan(); lineage = self.lineage()
        for node in lineage['nodes']: node['label'] = node['id']
        edge = lineage['edges'][0]; edge.update(id='dep.up.down', evidence_refs=[{
            'label': 'Supplied dependency', 'reference': 'synthetic://private/lineage', 'source_path': 'lineage.sql',
            'sha256': hashlib.sha256(evidence_path.read_bytes()).hexdigest()}]); edge.pop('evidence_labels')
        request['source_lineage'] = lineage
        planning.register_plan(self.state, request, self.run)
        result = planning.public_summary(self.state)['domains'][0]
        self.assertEqual(result['freshness'], 'current')
        self.assertEqual(result['reconciliation']['counts']['tables']['upstream_only'], 1)
        self.assertEqual(result['reconciliation']['counts']['consumers']['total'], result['consumer_coverage']['total'])
        self.assertNotIn('synthetic://private/lineage', json.dumps(result))
        packet = planning.context_packet(self.state, 'commerce', record_ids=['work_item:req.orders'])
        self.assertFalse(packet['plan']['reconciliation']['items'])
        self.assertFalse(packet['plan']['reconciliation']['follow_up_questions'])
        evidence_path.write_text('changed supplied dependency')
        stale = planning.public_summary(self.state)['domains'][0]
        self.assertEqual(stale['freshness'], 'stale')
        self.assertEqual(stale['reconciliation']['counts']['tables']['upstream_only'], 0)


if __name__ == '__main__': unittest.main()
