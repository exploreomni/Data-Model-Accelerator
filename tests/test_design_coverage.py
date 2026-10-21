"""Synthetic offline scope evidence; no customer data or source execution."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import design_coverage as coverage
import guided_workflow as guided
from ae_common import hash_json


class DesignCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run = self.root / 'run'; self.run.mkdir()
        self.source = self.root / 'source'; self.source.mkdir()
        self.other = self.root / 'other'; self.other.mkdir()
        self.state = {'inputs': {'source': {'path': str(self.source)}}, 'workflow': {
            'design': {'entities': [
                {'id': 'orders', 'domain': 'commerce', 'layer': 'gold', 'depends_on': []},
                {'id': 'products', 'domain': 'catalog', 'layer': 'gold', 'depends_on': []}]},
            'tasks': [], 'approvals': [{'unchanged': True}]}}
        self.doc = {'schema_version': 1, 'sources': [], 'objects': [], 'consumers': [], 'assignments': []}
        self.add_source('orders', 'commerce', self.source)
        self.add_source('products', 'catalog', self.other)

    def add_source(self, name, domain, root):
        path = name + '.sql'; raw = ('select 1 as ' + name + '_id').encode()
        (root / path).write_bytes(raw)
        self.doc['sources'].append({'id': name + '.repo', 'namespace': 'synthetic.' + name,
            'role': 'transformation source', 'kind': 'repository', 'status': 'available',
            'domain_ids': [domain], 'root': str(root), 'inventory': {
                'status': 'complete', 'reference': 'synthetic://source/extraction', 'files': [
                    {'path': path, 'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'parsed', 'object_ids': ['raw.' + name]}]}})
        self.doc['objects'].append({'id': 'raw.' + name, 'source_id': name + '.repo', 'native_id': 'db.schema.' + name,
            'kind': 'table', 'status': 'parsed', 'domain_ids': [domain], 'evidence_paths': [path], 'depends_on': []})
        self.doc['assignments'].append({'id': name + '.map', 'object_ids': ['raw.' + name],
            'consumer_ids': [], 'model_ids': [name], 'kind': 'implementation', 'reason': 'Direct source to reviewed target.'})

    def codes(self, selected=None):
        return {f['code'] for f in coverage.summarize(self.state, selected)['findings']}

    def save(self):
        return coverage.record(self.state, self.doc, self.run)

    def test_legacy_read_is_unassessed_and_never_mutates(self):
        before = copy.deepcopy(self.state)
        self.assertEqual(coverage.summarize(self.state)['status'], 'unassessed')
        self.assertIsNone(coverage.load(self.state))
        self.assertEqual(coverage.scope_bindings(self.state), {})
        self.assertEqual(coverage.gaps(self.state, ['orders']), [])
        self.assertEqual(self.state, before)

    def test_complete_direct_source_to_gold_without_silver_or_cardinality(self):
        before = copy.deepcopy(self.state)
        result = self.save()
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(result['counts']['objects'], 2)
        self.assertEqual(result['counts']['assigned'], 2)
        self.assertEqual(coverage.gaps(self.state, ['orders']), [])
        after = copy.deepcopy(self.state); after['workflow'].pop('design_coverage')
        self.assertEqual(before, after)
        self.assertIn('not authenticated', result['qualification'])

    def test_content_addressed_private_sidecar_reused(self):
        self.save(); ref = copy.deepcopy(self.state['workflow']['design_coverage']['document'])
        self.save()
        self.assertEqual(ref, self.state['workflow']['design_coverage']['document'])
        self.assertEqual(len(list((self.run / 'design-coverage').iterdir())), 1)
        self.assertEqual(Path(ref['path']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(coverage.load(self.state)['request'], self.doc)

    def test_pre_design_observations_do_not_invent_associations(self):
        self.state['workflow']['design'] = None; self.doc['assignments'] = []
        self.assertEqual(self.save()['status'], 'partial')
        self.assertEqual(coverage.scope_bindings(self.state), {})
        self.assertIn('scope_unassigned', self.codes())

    def test_empty_opt_in_cannot_claim_complete_inventory(self):
        self.doc = {'schema_version': 1, 'sources': [], 'objects': [], 'consumers': [], 'assignments': []}
        self.assertEqual(self.save()['status'], 'partial')
        self.assertIn('inventory_not_supplied', self.codes())

    def test_missing_input_is_gap_scoped_to_declared_domain(self):
        self.doc['sources'].append({'id': 'missing.repo', 'namespace': 'missing', 'role': 'upstream inventory',
            'kind': 'external_inventory', 'status': 'missing', 'domain_ids': ['commerce'],
            'inventory': {'status': 'not_supplied', 'reference': 'synthetic://intake/missing', 'files': []}})
        self.save()
        self.assertIn('source_missing', self.codes(['orders']))
        self.assertEqual(self.codes(['products']), set())

    def test_unknown_file_object_cannot_shrink_denominator(self):
        self.doc['sources'][0]['inventory']['files'][0]['object_ids'].append('raw.missing')
        self.save(); self.assertIn('inventory_object_missing', self.codes())

    def test_unlisted_repository_file_is_independent_gap(self):
        self.save(); before = coverage.scope_bindings(self.state)
        (self.source / 'omitted.sql').write_text('select 2 as omitted')
        self.assertIn('files_uninventoried', self.codes(['orders']))
        after = coverage.scope_bindings(self.state)
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])

    def test_record_captures_unlisted_files_and_later_deletion_cannot_erase_them(self):
        path = self.source / 'omitted.sql'; path.write_text('select 2 as omitted')
        result = self.save(); self.assertEqual(result['counts']['files'], 3)
        captured = coverage.load(self.state)['request']['sources'][0]['inventory']['files']
        self.assertIn('omitted.sql', {r['path'] for r in captured})
        self.assertIn('file_objects_unknown', self.codes())
        path.unlink(); self.save()
        self.assertEqual(coverage.summarize(self.state)['counts']['files'], 3)
        self.assertIn('file_omitted', self.codes()); self.assertIn('file_unreadable', self.codes())

    def test_source_change_stales_only_associated_source(self):
        self.save(); before = coverage.scope_bindings(self.state)
        (self.source / 'orders.sql').write_text('select 99 as orders_id')
        self.assertIn('source_stale', self.codes(['orders']))
        self.assertEqual(self.codes(['products']), set())
        after = coverage.scope_bindings(self.state)
        self.assertNotEqual(before['orders'], after['orders']); self.assertEqual(before['products'], after['products'])

    def test_same_repository_and_domain_file_change_keeps_unrelated_model_current(self):
        (self.source / 'products.sql').write_bytes((self.other / 'products.sql').read_bytes())
        self.doc['sources'][0]['inventory']['files'].extend(self.doc['sources'][1]['inventory']['files'])
        self.doc['sources'].pop(1)
        self.doc['objects'][1].update(source_id='orders.repo', domain_ids=['commerce'])
        self.state['workflow']['design']['entities'][1]['domain'] = 'commerce'
        self.save(); before = coverage.scope_bindings(self.state)
        (self.source / 'orders.sql').write_text('select 99 as orders_id')
        after = coverage.scope_bindings(self.state)
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(self.codes(['products']), set())
        self.assertEqual(coverage.summarize(self.state, ['products'])['counts']['objects'], 1)
        (self.source / 'unknown.sql').write_text('select 1')
        self.assertNotEqual(after['products'], coverage.scope_bindings(self.state)['products'])
        self.assertIn('files_uninventoried', self.codes(['products']))

    def test_omitted_prior_observations_remain_in_denominator(self):
        self.save()
        self.doc['objects'].pop(0); self.doc['assignments'].pop(0)
        self.doc['sources'][0]['inventory']['files'][0]['object_ids'] = []
        result = self.save()
        self.assertEqual(result['counts']['objects'], 2)
        self.assertIn('observation_omitted', self.codes(['orders']))
        self.assertIn('scope_unassigned', self.codes(['orders']))
        self.save(); self.assertEqual(coverage.summarize(self.state)['counts']['objects'], 2)

    def test_omitted_file_and_source_persist(self):
        self.save(); self.doc['sources'][0]['inventory']['files'] = []
        self.save(); self.assertIn('file_omitted', self.codes())
        self.doc['sources'] = []; self.doc['objects'] = []; self.doc['assignments'] = []
        self.save()
        self.assertEqual(coverage.summarize(self.state)['counts']['sources'], 2)
        self.assertIn('source_omitted', self.codes())

    def test_partial_and_failed_parsing_never_turn_complete(self):
        for status in ('partial', 'unsupported', 'unreadable'):
            with self.subTest(status=status):
                self.doc['sources'][0]['inventory']['files'][0]['status'] = status
                self.save(); self.assertIn('file_partial', self.codes(['orders']))
        self.doc['sources'][0]['inventory']['files'][0]['status'] = 'parsed'
        self.doc['objects'][0]['status'] = 'unsupported'
        self.save(); self.assertIn('object_partial', self.codes())

    def test_unresolved_dependency_reference_is_retained_gap(self):
        self.doc['objects'][0]['depends_on'] = [{'reference': 'unresolved cross-repository reference', 'object_id': 'raw.absent'}]
        self.save(); self.assertIn('dependency_unresolved', self.codes(['orders']))
        self.assertEqual(coverage.load(self.state)['request']['objects'][0]['depends_on'], self.doc['objects'][0]['depends_on'])

    def test_target_removal_and_interface_only_never_pass(self):
        self.save(); self.state['workflow']['design']['entities'].pop(0)
        self.assertIn('target_missing', self.codes(['orders']))
        self.state['workflow']['design']['entities'].append({'id': 'orders', 'domain': 'commerce', 'object_kind': 'interface'})
        self.assertIn('interface_only', self.codes(['orders']))
        self.assertIn('scope_unassigned', self.codes(['orders']))

    def test_interface_assignment_visible_but_does_not_satisfy_implementation(self):
        self.doc['assignments'][0]['kind'] = 'interface'
        result = self.save()
        self.assertEqual(result['counts']['interfaces'], 1)
        self.assertIn('scope_unassigned', self.codes(['orders']))

    def test_reviewed_exclusion_retains_denominator_and_cannot_self_assert(self):
        row = self.doc['assignments'][0]; row.update(kind='excluded', model_ids=[])
        with self.assertRaises(ValueError): self.save()
        row['review'] = {'reviewer': 'Host-attributed reviewer', 'reference': 'synthetic://review/exclusion'}
        result = self.save()
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(result['counts']['objects'], 2)
        self.assertEqual(result['counts']['excluded'], 1)

    def test_conflicting_exclusion_and_implementation_is_gap(self):
        self.doc['assignments'].append({**copy.deepcopy(self.doc['assignments'][0]), 'id': 'excluded.orders',
            'kind': 'excluded', 'model_ids': [], 'review': {'reviewer': 'Reviewer', 'reference': 'synthetic://review'}})
        self.save(); self.assertIn('assignment_conflict', self.codes())

    def test_reassignment_and_removal_invalidate_old_model_scope(self):
        self.save(); initial = coverage.scope_bindings(self.state)
        self.doc['assignments'][0]['model_ids'] = ['products']
        self.save(); moved = coverage.scope_bindings(self.state)
        self.assertEqual(set(moved), {'orders', 'products'})
        self.assertNotEqual(initial['orders'], moved['orders']); self.assertNotEqual(initial['products'], moved['products'])
        self.doc['assignments'].pop(0); self.save(); removed = coverage.scope_bindings(self.state)
        self.assertNotEqual(moved['orders'], removed['orders']); self.assertNotEqual(moved['products'], removed['products'])

    def test_scoped_summary_never_discloses_paths_prose_or_unselected_ids(self):
        self.doc['objects'][0]['depends_on'] = [{'reference': 'private source excerpt /sensitive/path'}]
        self.doc['objects'][1]['depends_on'] = [{'reference': 'other private source excerpt'}]
        self.save(); public = coverage.summarize(self.state, ['orders']); raw = json.dumps(public)
        for hidden in (str(self.source), 'orders.sql', 'private source excerpt', 'products', 'catalog'):
            self.assertNotIn(hidden, raw)
        self.assertEqual(public['counts']['objects'], 1)

    def test_native_identity_conflict_rejected_without_mutation(self):
        self.save(); before = copy.deepcopy(self.state)
        self.doc['objects'][0]['native_id'] = 'another.native.identity'
        with self.assertRaises(ValueError): self.save()
        self.assertEqual(self.state, before)

    def test_sidecar_tampering_and_missing_evidence_are_unavailable(self):
        self.save(); before = coverage.scope_bindings(self.state)
        path = Path(self.state['workflow']['design_coverage']['document']['path'])
        path.write_text('{}')
        self.assertEqual(coverage.summarize(self.state)['status'], 'unavailable')
        after = coverage.scope_bindings(self.state)
        self.assertEqual(set(after), set(before)); self.assertNotEqual(after, before)
        self.assertTrue(coverage.gaps(self.state, ['orders']))
        path.unlink(); self.assertEqual(coverage.summarize(self.state)['status'], 'unavailable')

    def test_rehashed_invalid_request_is_revalidated_on_read(self):
        self.save(); ref = self.state['workflow']['design_coverage']['document']; path = Path(ref['path'])
        doc = json.loads(path.read_text()); doc['request']['assignments'][0]['kind'] = 'verified_by_name'
        doc['request_sha256'] = hash_json(doc['request']); raw = guided._bytes(doc); path.write_bytes(raw)
        ref.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        self.assertEqual(coverage.summarize(self.state)['status'], 'unavailable')

    def test_source_and_output_symlinks_are_rejected_or_visible_gaps(self):
        self.save(); p = self.source / 'orders.sql'; p.unlink(); p.symlink_to(self.other / 'products.sql')
        self.assertIn('file_unreadable', self.codes())
        self.assertIn('inventory_symlink', self.codes())
        fake = self.root / 'linkedrun'; fake.symlink_to(self.run)
        with self.assertRaises(ValueError): coverage.record(self.state, self.doc, fake)
        linked = self.root / 'linkedsource'; linked.symlink_to(self.source)
        self.doc['sources'][0]['root'] = str(linked)
        with self.assertRaises(ValueError): self.save()

    def test_run_inside_any_input_source_is_rejected(self):
        with self.assertRaises(ValueError): coverage.record(self.state, self.doc, self.other)
        self.assertNotIn('design_coverage', self.state['workflow'])

    def test_output_subdirectory_cannot_overlap_a_declared_source(self):
        source = self.run / 'design-coverage'; source.mkdir()
        (source / 'orders.sql').write_bytes((self.source / 'orders.sql').read_bytes())
        self.doc['sources'][0]['root'] = str(source)
        with self.assertRaises(ValueError): self.save()
        self.assertEqual({p.name for p in source.iterdir()}, {'orders.sql'})

    def test_source_bytes_and_approvals_are_preserved(self):
        before = {p: p.read_bytes() for root in (self.source, self.other) for p in root.iterdir()}
        approvals = copy.deepcopy(self.state['workflow']['approvals'])
        self.save(); coverage.load(self.state); coverage.scope_bindings(self.state); coverage.gaps(self.state, ['orders'])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(approvals, self.state['workflow']['approvals'])

    def test_secret_paths_and_injection_never_read_or_execute(self):
        bad = copy.deepcopy(self.doc); bad['sources'][0]['inventory']['files'][0]['path'] = '.aws/config'
        with patch('source_adapters.filesystem.read_assigned', side_effect=AssertionError('No reads')):
            with self.assertRaises(ValueError): coverage.record(self.state, bad, self.run)
        bad = copy.deepcopy(self.doc); bad['assignments'][0]['reason'] = 'password=unsafe'
        with self.assertRaises(ValueError): coverage.record(self.state, bad, self.run)
        sentinel = self.root / 'executed'
        (self.source / 'orders.sql').write_text('$(touch ' + str(sentinel) + '); import os; raise RuntimeError("execute")')
        with patch('subprocess.run', side_effect=AssertionError('No subprocess')):
            self.save()
        self.assertFalse(sentinel.exists())
        self.assertIn('source_stale', self.codes())

    def test_consumer_requirement_has_independent_denominator(self):
        self.doc['consumers'] = [{'id': 'daily.orders', 'source_id': 'orders.repo', 'object_ids': ['raw.orders'],
            'domain_ids': ['commerce'], 'evidence_paths': ['orders.sql'], 'description': 'Daily order count by retained population.'}]
        self.save(); self.assertIn('scope_unassigned', self.codes(['orders']))
        self.doc['assignments'][0]['consumer_ids'] = ['daily.orders']
        self.assertEqual(self.save()['status'], 'complete')
        self.doc['consumers'][0]['object_ids'].append('unknown.report.source')
        self.save(); self.assertIn('consumer_reference_unknown', self.codes())

    def test_known_dependency_requires_target_path_but_can_fold_into_one_target(self):
        self.doc['objects'][0]['depends_on'] = [{'reference': 'source relation', 'object_id': 'raw.products'}]
        self.save(); self.assertIn('dependency_target_missing', self.codes(['orders']))
        self.state['workflow']['design']['entities'][0]['depends_on'] = ['products']
        self.assertEqual(self.codes(['orders']), set())
        self.state['workflow']['design']['entities'][0]['depends_on'] = []
        self.doc['assignments'][1]['model_ids'] = ['orders']
        self.save(); self.assertEqual(self.codes(['orders']), set())

    def test_known_dependency_on_unassigned_source_remains_gap(self):
        self.doc['objects'][0]['depends_on'] = [{'reference': 'source relation', 'object_id': 'raw.products'}]
        self.doc['assignments'].pop(1)
        self.save(); self.assertIn('dependency_uncovered', self.codes(['orders']))

    def test_consumer_cannot_bind_an_unrelated_target(self):
        self.doc['consumers'] = [{'id': 'daily.orders', 'source_id': 'orders.repo', 'object_ids': ['raw.orders'],
            'domain_ids': ['commerce'], 'evidence_paths': ['orders.sql'], 'description': 'Daily order count.'}]
        self.doc['assignments'].append({'id': 'consumer.map', 'object_ids': [], 'consumer_ids': ['daily.orders'],
            'model_ids': ['products'], 'kind': 'implementation', 'reason': 'Proposed mapping'})
        self.save(); self.assertIn('consumer_target_missing', self.codes())
        self.state['workflow']['design']['entities'][1]['depends_on'] = ['orders']
        self.assertNotIn('consumer_target_missing', self.codes())

    def test_ambiguous_casefold_file_identity_is_rejected(self):
        row = copy.deepcopy(self.doc['sources'][0]['inventory']['files'][0]); row['path'] = 'ORDERS.sql'
        self.doc['sources'][0]['inventory']['files'].append(row)
        with self.assertRaises(ValueError): self.save()

    def test_sidecar_symlink_cannot_be_loaded(self):
        self.save(); ref = self.state['workflow']['design_coverage']['document']
        actual = Path(ref['path']); other = self.run / 'copy.json'; other.write_bytes(actual.read_bytes())
        actual.unlink(); actual.symlink_to(other)
        self.assertEqual(coverage.summarize(self.state)['status'], 'unavailable')

    def test_external_inventory_is_hash_checked_without_repository_scan(self):
        self.doc['sources'][0]['kind'] = 'external_inventory'
        (self.source / 'outside-inventory.txt').write_text('Out of this explicitly bounded external inventory.')
        self.assertEqual(self.save()['status'], 'complete')
        (self.source / 'orders.sql').unlink()
        self.assertIn('file_unreadable', self.codes())


if __name__ == '__main__':
    unittest.main()
