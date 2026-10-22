"""Bounded requested-scope fixtures; no warehouse execution or customer data."""
import copy
import csv
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import migration_inventory as inventory
import migration_planning as planning
import migration_plan_exports as exports
import legacy_alignment as alignment
import test_legacy_alignment as fixtures
import test_migration_planning as plan_fixtures


def row(identity='orders', namespace='legacy', **changes):
    return {'id': identity, 'source_namespace': namespace, 'native_id': 'schema.' + identity,
            'domain_ids': ['commerce'], 'evidence_refs': ['synthetic://register-row'], **changes}


def request(*rows, kind='model'):
    return {'schema_version': 1, 'registers': [{'id': kind, 'kind': kind,
            'evidence_refs': ['synthetic://register'], 'rows': list(rows)}]}


class MigrationInventoryTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.LegacyAlignmentTests('test_absent_feature_and_declined_comparison_preserve_material_bindings')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state = self.h.state; self.run = self.h.run

    def register(self, req):
        return inventory.register(self.state, req, self.run)

    def domain(self, selected=None):
        return next(d for d in inventory.summarize(self.state, selected)['domains'] if d['domain_id'] == 'commerce')

    def test_absent_feature_is_unchanged_and_metadata_is_not_mapping_authority(self):
        before = copy.deepcopy(self.state)
        self.assertIsNone(inventory.summarize(self.state)); self.assertEqual(inventory.scope_bindings(self.state), {})
        self.assertEqual(inventory.gaps(self.state, ['orders']), []); self.assertEqual(self.state, before)
        self.register(request())
        self.assertEqual(inventory.summarize(self.state)['status'], 'unassessed')
        self.assertTrue(inventory.gaps(self.state, ['orders']))
        self.register(request(row(metadata={'target': 'orders', 'approved': True, 'status': 'mapped'})))
        self.assertEqual(self.domain()['counts']['accounted'], 0)
        self.assertEqual(self.state['workflow']['approvals'], [])

    def test_union_retains_ownership_only_and_every_occurrence_without_basename_matching(self):
        req = request(row())
        for kind in ('ownership', 'ticket', 'explore', 'dashboard'):
            req['registers'].extend(request(row(), kind=kind)['registers'])
        req['registers'][1]['rows'].append(row('ownership_only'))
        req['registers'][0]['rows'].append(row('second', namespace='other', native_id='schema.orders'))
        self.register(req); d = self.domain()
        self.assertEqual(d['counts']['requested'], 3)
        self.assertEqual(d['counts']['unresolved'], 3)
        shared = next(r for r in d['rows'] if r['source_namespace'] == 'legacy' and r['native_id'] == 'schema.orders')
        self.assertEqual(len(shared['occurrences']), 5)
        self.assertEqual(len({r['id'] for r in d['rows']}), 3)

    def test_import_is_idempotent_cumulative_and_rejects_identity_reassignment_atomically(self):
        req = request(row(evidence_refs=['synthetic://b', 'synthetic://a']), row('retained'))
        self.register(req); first = copy.deepcopy(self.state['workflow']['migration_inventory'])
        inventory.register(self.state, req)
        self.assertEqual(first, self.state['workflow']['migration_inventory'])
        self.register(request(row()))
        self.assertEqual(self.domain()['counts']['requested'], 2)
        old = next(r for r in self.domain()['rows'] if r['native_id'] == 'schema.retained')
        self.assertTrue(old['occurrences'][0]['omitted_from_latest_import'])
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'cannot be reassigned'):
            self.register(request(row(native_id='different.orders')))
        self.assertEqual(before, self.state)

    def test_unmodeled_expected_scope_changes_only_its_domain_binding(self):
        req = request(row(), row('products', domain_ids=['catalog']))
        self.register(req); before = inventory.scope_bindings(self.state)
        req['registers'][0]['rows'].append(row('not_in_design'))
        self.register(req); after = inventory.scope_bindings(self.state)
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(self.domain(['orders'])['counts']['requested'], 2)
        self.assertTrue(inventory.gaps(self.state, ['orders']))
        req['registers'][0]['rows'].append(row('shared', domain_ids=['commerce', 'catalog']))
        self.register(req)
        scoped = self.domain(['orders'])
        self.assertEqual(scoped['counts']['requested'], 3)
        self.assertEqual(scoped['omitted_detail_rows'], 1)
        self.assertNotIn('schema.shared', json.dumps(scoped['rows']))

    def _aligned(self):
        self.h.enable(mapped=False)
        baseline = fixtures.baseline()
        upstream = copy.deepcopy(baseline['tables'][0]); upstream.update(id='old.upstream', native_id='upstream')
        baseline['tables'].append(upstream); alignment.register_baseline(self.state, baseline, self.run)
        mapped = fixtures.mapping()
        mapped['mappings'][0]['sources'] = [{'table_id': 'old.orders', 'kind': 'table'}]
        mapped['mappings'][0]['targets'] = [{'model_id': 'orders', 'kind': 'table'}]
        alignment.register_alignment(self.state, mapped, self.run)
        self.register(request(row(legacy_table_id='old.orders'), row('upstream', legacy_table_id='old.upstream')))
        planning.configure(self.state, plan_fixtures.config())
        plan = {'schema_version': 1, 'domain_id': 'commerce', 'consumers': [], 'work_items': [],
            'source_lineage': {'nodes': [
                {'id': 'upstream', 'kind': 'legacy_table', 'label': 'Upstream', 'legacy_table_id': 'old.upstream'},
                {'id': 'final', 'kind': 'legacy_table', 'label': 'Final', 'legacy_table_id': 'old.orders'}],
                'edges': [{'id': 'observed.edge', 'source_id': 'upstream', 'target_id': 'final', 'status': 'observed',
                    'evidence_refs': [{'label': 'Supplied SQL', 'reference': 'synthetic://observed-edge'}]}]}}
        planning.register_plan(self.state, plan, self.run)
        return plan

    def test_observed_upstream_path_is_not_replacement_and_planning_keeps_denominator(self):
        self._aligned(); d = self.domain()
        self.assertEqual(d['counts']['replacement_mapping'], 1)
        self.assertEqual(d['counts']['upstream_only'], 1)
        self.assertEqual(d['counts']['accounted'], 1); self.assertEqual(d['counts']['unresolved'], 1)
        p = planning.public_summary(self.state)['domains'][0]
        self.assertEqual(p['requested_inventory']['counts'], d['counts'])

    def test_stale_lineage_never_supplies_upstream_coverage(self):
        self._aligned()
        (self.h.source / 'orders.sql').write_text('select 2 as orders_id')
        self.assertEqual(self.domain()['counts']['upstream_only'], 0)
        self.assertEqual(self.domain()['counts']['accounted'], 0)

    def test_exclusion_needs_its_own_decision_and_remains_visible_not_mapped(self):
        req = request(row('exclude'))
        req['exclusions'] = [{'id': 'decision.exclude', 'source_namespace': 'legacy', 'native_id': 'schema.exclude',
            'domain_ids': ['commerce'], 'reason': 'Explicit scoped exclusion', 'review_reference': ''}]
        with self.assertRaises(ValueError): self.register(req)
        req['exclusions'][0]['review_reference'] = 'synthetic://human/exclusion'
        self.register(req); counts = self.domain()['counts']
        self.assertEqual(counts['requested'], 1); self.assertEqual(counts['accounted'], 1)
        self.assertEqual(counts['explicit_exclusion'], 1); self.assertEqual(counts['replacement_mapping'], 0)
        self.assertEqual(self.domain()['rows'][0]['exclusion_ids'], ['decision.exclude'])
        self.assertEqual(self.state['workflow']['approvals'], [])

    def test_conflicting_explicit_crosswalks_are_unresolved(self):
        req = request(row(legacy_table_id='old.orders'))
        req['registers'].extend(request(row(legacy_table_id='old.other'), kind='ownership')['registers'])
        self.register(req)
        self.assertIn('resolve_crosswalk_conflict', self.domain()['rows'][0]['requirements'])
        self.assertEqual(self.domain()['counts']['accounted'], 0)

    def test_requested_inventory_exports_all_550_rows_and_consumer_target_is_not_proof(self):
        import test_migration_plan_exports as export_fixture
        rows = [row('item.%d' % i) for i in range(550)]
        rows.append(row('dashboard', consumer_id='report:orders'))
        self.register(request(*rows)); planning.configure(self.state, plan_fixtures.config())
        planning.register_plan(self.state, {'schema_version': 1, 'domain_id': 'commerce', 'work_items': [],
            'consumers': [{'id': 'report:orders', 'kind': 'dashboard', 'label': 'Report', 'legacy_table_ids': [],
                           'model_ids': ['orders'], 'topic_ids': [], 'status': 'proposed'}]}, self.run)
        summary = planning.public_summary(self.state); d = summary['domains'][0]
        self.assertEqual(d['requested_inventory']['counts']['accounted'], 0)
        files = exports.export_files(summary)
        workbook = next(f for f in files if f['path'].endswith('inventory.xlsx'))
        tabs = export_fixture.workbook(workbook['content'])
        self.assertEqual(len(tabs['Requested scope'][0]) - 1, 551)
        self.assertEqual(len(tabs['Inventory provenance'][0]) - 1, 551)
        self.assertNotIn('synthetic://register-row', str(tabs))
        document = next(f for f in files if f['path'].endswith('migration-plan.docx'))
        _, text = export_fixture.document(document['content'])
        self.assertIn('Complete requested migration scope', text)
        self.assertIn('schema.item.549', '\n'.join(text))
        self.assertIn('Evidence reference count', text)

    def test_occurrence_export_bypasses_display_cap_without_changing_counts(self):
        import test_mapping_coverage as coverage_fixture
        from source_adapters.base import Report, sha
        h = coverage_fixture.MappingCoverageTests(); h.setUp(); self.addCleanup(h.doCleanups)
        source = (h.h.repo / 'orders.sql').read_text()
        report = Report('dbt', {'orders.sql': source})
        for i in range(550): report.object('orders.sql', '$objects[%d]' % i, 'model', 'object.%d' % i)
        report.cover('orders.sql')
        contract = report.finish()
        req = {'schema_version': 1, 'reports': [contract], 'expected_files': [
            {'source': 'dbt', 'path': 'orders.sql', 'sha256': sha(source)}], 'requirements': [], 'targets': [], 'mappings': []}
        req['requirements'] = [{'id': key, 'domain': key, 'description': 'Explicit requested domain'} for key in ('commerce', 'catalog')]
        for i, obj in enumerate(contract['objects']):
            domains = ['commerce'] if i < 546 else ['commerce', 'catalog'] if i == 546 else ['catalog'] if i < 549 else []
            req['mappings'].append({'occurrence_id': obj['occurrence_id'], 'requirement_ids': domains, 'target_ids': [],
                'status': 'unresolved', 'basis': 'unassessed', 'rationale': 'No target selected.'})
        h.coverage.register(h.h.state, req, h.h.run)
        display = h.coverage.summarize(h.h.state)
        self.assertEqual(len(display['rows']), 500); self.assertEqual(display['omitted_detail_rows'], 50)
        exported = exports.mapping_coverage_export(h.h.state)
        rows = list(csv.DictReader(io.StringIO(exported['content'].decode('utf-8-sig'))))
        self.assertEqual(len(rows), 550)
        self.assertEqual({r['Occurrence ID'] for r in rows}, set(h.coverage.read(h.h.state)['occurrences']))
        self.assertEqual(display['counts']['total'], 550)
        scoped = h.coverage.detail_rows(h.h.state, ['orders'])
        self.assertEqual(len(scoped), 546)
        self.assertTrue(all(r['domain_ids'] == ['commerce'] and r['status'] == 'unresolved' for r in scoped))
        self.assertEqual(h.coverage.detail_rows(h.h.state, []), [])
        scoped_export = exports.mapping_coverage_export(h.h.state, ['orders'])
        self.assertEqual(scoped_export, exports.mapping_coverage_rows_export(scoped))
        self.assertEqual(len(list(csv.DictReader(io.StringIO(scoped_export['content'].decode('utf-8-sig'))))), 546)


if __name__ == '__main__': unittest.main()
