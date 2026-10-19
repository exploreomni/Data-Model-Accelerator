"""Pinned reuse assignments preserve ownership gaps and scoped freshness."""
import copy
import importlib
from pathlib import Path
import unittest

import test_engagement_stages as fixtures
from ae_common import hash_json
import mapping_coverage
from review_assurance import records


class ReuseCoverageTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.reuse = importlib.import_module('reuse_coverage')
        doc = copy.deepcopy(self.h.doc)
        doc['revision'] += 1
        doc['existing_models'] = [
            {'id': 'existing-' + name, 'name': name, 'grain': 'One row per ' + name,
             'keys': [name + '_id'], 'definitions': 'Synthetic ' + name,
             'history': 'Current state', 'security': 'Restricted', 'dependencies': [],
             'evidence_refs': ['inventory:' + name]} for name in ('orders', 'products')]
        for model in doc['entities']:
            if model['id'] in ('orders', 'products'):
                model.update(disposition='reuse', reuse={
                    'existing_id': 'existing-' + model['id'], 'rationale': 'Retain the declared model',
                    'dimensions': {name: {'status': 'compatible', 'evidence_refs': ['comparison:' + name],
                                          'explanation': 'Synthetic comparison evidence'}
                                   for name in fixtures.stages.DIMENSIONS}})
        fixtures.stages.import_design(self.h.state, doc)
        self.coverage_request = {'schema_version': 1, 'expected_files': [], 'reports': [],
            'requirements': [{'id': 'requirement-' + name, 'description': 'Retain ' + name,
                              'domain': 'finance' if name == 'orders' else 'commerce'}
                             for name in ('orders', 'products')], 'targets': [], 'mappings': []}
        mapping_coverage.register(self.h.state, self.coverage_request, self.h.run)
        self.request = {'schema_version': 1, 'inventory': [
            {'existing_id': row['id'], 'namespace': 'synthetic', 'native_id': 'model.synthetic.' + row['name'],
             'snapshot_sha256': hash_json(row)} for row in doc['existing_models']],
            'assignments': [self.assignment(name) for name in ('orders', 'products')]}

    def assignment(self, name, **changes):
        return {'existing_ids': ['existing-' + name], 'owner_domain': 'commerce',
                'disposition': 'reuse', 'model_ids': [name],
                'requirement_ids': ['requirement-' + name], 'evidence_refs': ['comparison:' + name],
                'rationale': 'Synthetic ownership and compatibility review', **changes}

    def register(self, request=None):
        return self.reuse.register(self.h.state, request or self.request, self.h.run)

    def assert_rejected(self, request):
        before = copy.deepcopy(self.h.state)
        files = {str(p.relative_to(self.h.run)): p.read_bytes()
                 for p in self.h.run.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError):
            self.reuse.register(self.h.state, request, self.h.run)
        self.assertEqual(self.h.state, before)
        self.assertEqual({str(p.relative_to(self.h.run)): p.read_bytes()
                          for p in self.h.run.rglob('*') if p.is_file()}, files)

    def rows(self):
        return {row['existing_id']: row for row in self.reuse.summarize(self.h.state)['rows']}

    def test_legacy_absence_is_unassessed_and_never_invents_authority(self):
        legacy = {'schema_version': 1}
        before = copy.deepcopy(legacy)
        self.assertIsNone(self.reuse.read(legacy))
        self.assertEqual(self.reuse.scope_bindings(legacy), {})
        self.assertEqual(self.reuse.summarize(legacy)['status'], 'unassessed')
        self.assertEqual(legacy, before)
        self.register()
        self.assertEqual(self.h.state['workflow']['approvals'], [])
        self.assertFalse(self.h.state['readiness']['execution_authorized'])

    def test_omitted_assignments_are_unassigned_with_inferred_canonical_scope(self):
        request = copy.deepcopy(self.request)
        request['assignments'] = []
        summary = self.register(request)
        self.assertEqual(summary['counts']['total'], 2)
        self.assertEqual(summary['counts']['unassigned'], 2)
        self.assertEqual(summary['counts']['by_disposition']['undetermined'], 2)
        self.assertEqual(set(self.reuse.scope_bindings(self.h.state)), {'orders', 'products'})
        for row in summary['rows']:
            self.assertIsNone(row['owner_domain'])
            self.assertEqual(row['compatibility'], 'unknown')
            self.assertEqual(row['freshness'], 'current')

    def test_inventory_must_be_complete_unique_and_match_canonical_snapshots(self):
        for case in ('missing', 'duplicate_id', 'duplicate_native', 'wrong_snapshot', 'unknown_id'):
            with self.subTest(case=case):
                request = copy.deepcopy(self.request)
                if case == 'missing': request['inventory'].pop()
                elif case == 'duplicate_id': request['inventory'].append(copy.deepcopy(request['inventory'][0]))
                elif case == 'duplicate_native': request['inventory'][1]['native_id'] = request['inventory'][0]['native_id']
                elif case == 'wrong_snapshot': request['inventory'][0]['snapshot_sha256'] = 'a' * 64
                else: request['inventory'][0]['existing_id'] = 'missing-existing'
                self.assert_rejected(request)

    def test_wildcards_expand_only_pinned_ids_and_keep_exact_resolution(self):
        request = copy.deepcopy(self.request)
        request['assignments'] = [self.assignment('orders', existing_ids=['existing-*'],
            model_ids=['orders', 'products'], requirement_ids=[])]
        summary = self.register(request)
        self.assertEqual(summary['counts']['by_disposition']['reuse'], 2)
        saved = self.reuse.read(self.h.state)
        self.assertEqual(set(saved['assignments']), {'existing-orders', 'existing-products'})
        self.assertEqual(len(saved['inventory_sha256']), 64)
        for identity, row in saved['assignments'].items():
            self.assertEqual(row['existing_ids'], [identity])
        for pattern in ('missing-*', 'model.synthetic.*'):
            request['assignments'][0]['existing_ids'] = [pattern]
            self.assert_rejected(request)

    def test_conflicting_owners_and_dangling_references_are_atomic_errors(self):
        self.register()
        for case in ('owner', 'domain', 'model', 'requirement', 'out_of_domain'):
            with self.subTest(case=case):
                request = copy.deepcopy(self.request)
                if case == 'owner': request['assignments'].append(self.assignment('orders', owner_domain='finance'))
                elif case == 'domain': request['assignments'][0]['owner_domain'] = 'unknown-domain'
                elif case == 'model': request['assignments'][0]['model_ids'] = ['absent-model']
                elif case == 'requirement': request['assignments'][0]['requirement_ids'] = ['absent-requirement']
                else: request['assignments'][0]['disposition'] = 'OUT_OF_DOMAIN'
                self.assert_rejected(request)
        request = copy.deepcopy(self.request)
        request['assignments'][0]['owner_domain'] = 'finance'
        self.assertEqual(self.register(request)['counts']['unassigned'], 0)

    def test_claimed_reuse_must_match_canonical_disposition_and_existing_link(self):
        for change in ({'disposition': 'extend'}, {'model_ids': ['products']}, {'model_ids': ['customers']}):
            with self.subTest(change=change):
                request = copy.deepcopy(self.request)
                request['assignments'][0].update(change)
                self.assert_rejected(request)
        request = copy.deepcopy(self.request)
        request['assignments'][0]['model_ids'] = []
        self.register(request)
        self.assertEqual(self.rows()['existing-orders']['model_ids'], ['orders'])

    def test_existing_dimension_changes_stale_only_affected_models(self):
        self.register()
        before = self.reuse.scope_bindings(self.h.state)
        doc = self.h.state['workflow']['design']
        original = doc['existing_models'][0]['history']
        doc['existing_models'][0]['history'] = 'Changed historical retention'
        after = self.reuse.scope_bindings(self.h.state)
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(self.rows()['existing-orders']['freshness'], 'stale')
        self.assertEqual(self.rows()['existing-products']['freshness'], 'current')
        self.assertEqual(self.rows()['existing-orders']['compatibility'], 'unknown')
        doc['existing_models'][0]['history'] = original
        order = next(model for model in doc['entities'] if model['id'] == 'orders')
        order['reuse']['dimensions']['security']['explanation'] = 'Changed security interpretation'
        changed_model = self.reuse.scope_bindings(self.h.state)
        self.assertNotEqual(before['orders'], changed_model['orders'])
        self.assertEqual(before['products'], changed_model['products'])
        doc['existing_models'].append({**doc['existing_models'][1], 'id': 'new-existing-model'})
        summary = self.reuse.summarize(self.h.state)
        self.assertEqual(summary['uninventoried_existing_ids'], ['new-existing-model'])
        self.assertEqual(self.reuse.scope_bindings(self.h.state)['products'], before['products'])

    def test_requirement_changes_and_missing_requirement_evidence_are_scoped(self):
        self.register()
        before = self.reuse.scope_bindings(self.h.state)
        self.coverage_request['requirements'][0]['description'] = 'Changed order definition'
        mapping_coverage.register(self.h.state, self.coverage_request, self.h.run)
        after = self.reuse.scope_bindings(self.h.state)
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(self.rows()['existing-orders']['freshness'], 'stale')
        self.assertEqual(self.rows()['existing-products']['freshness'], 'current')
        Path(records(self.h.state)['coverage']['document']['path']).unlink()
        unavailable = self.reuse.scope_bindings(self.h.state)
        self.assertNotEqual(after['orders'], unavailable['orders'])
        self.assertNotEqual(after['products'], unavailable['products'])

    def test_missing_comparison_evidence_and_host_exclusion_never_mean_validated(self):
        summary = self.register()
        self.assertTrue(all(row['compatibility'] == 'evidence_recorded' for row in summary['rows']))
        model = next(e for e in self.h.state['workflow']['design']['entities'] if e['id'] == 'orders')
        model['reuse']['dimensions']['grain']['evidence_refs'] = []
        request = copy.deepcopy(self.request)
        self.register(request)
        self.assertEqual(self.rows()['existing-orders']['compatibility'], 'unknown')
        request['assignments'][0].update(disposition='out_of_scope', model_ids=[], requirement_ids=[])
        self.assert_rejected(request)
        request['assignments'][0]['review_reference'] = 'synthetic://review/exclusion'
        summary = self.register(request)
        self.assertEqual(summary['counts']['by_disposition']['out_of_scope'], 1)
        self.assertEqual(self.rows()['existing-orders']['compatibility'], 'unknown')
        self.assertEqual(self.h.state['workflow']['approvals'], [])

    def test_missing_or_tampered_sidecar_invalidates_prior_scope_and_drafts_stay_available(self):
        self.register()
        before = self.reuse.scope_bindings(self.h.state)
        path = Path(records(self.h.state)['reuse']['document']['path'])
        raw = path.read_bytes()
        for case in ('tampered', 'missing'):
            with self.subTest(case=case):
                if case == 'tampered': path.write_text('{}')
                else: path.unlink()
                after = self.reuse.scope_bindings(self.h.state)
                self.assertEqual(set(after), set(before))
                self.assertTrue(all(after[key] != before[key] for key in before))
                self.assertTrue(all(after[key].startswith('unavailable:') for key in after))
                self.assertTrue(fixtures.stages.draft_bindings(self.h.state, ['orders']))
                path.write_bytes(raw)


if __name__ == '__main__':
    unittest.main()
