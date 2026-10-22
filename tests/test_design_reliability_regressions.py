"""Durable synthetic regressions for design review, provenance and input safety."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import test_design_evidence as support
import design_coverage as coverage
import design_evidence as evidence
import domain_workflow as domains
import engagement_stages as stages


class ReliabilityRegressions(unittest.TestCase):
    # Reuse setup and request builders without inheriting and repeating its tests.
    setUp = support.EvidenceTests.setUp
    action = support.EvidenceTests.action
    coverage = support.EvidenceTests.coverage
    document = support.EvidenceTests.document
    register = support.EvidenceTests.register
    review = support.EvidenceTests.review

    def human_review(self, selected):
        return {'schema_version': 1, 'kind': 'human_design_review', 'decision': 'approve',
                'reviewer': 'Synthetic human', 'review_reference': 'synthetic://human/review',
                'bindings': stages.review_bindings(self.state, selected)}

    def rejected_review(self, selected=None):
        request = self.review(selected)
        request['result'] = 'changes_requested'
        request['findings'] = [{'id': 'products-definition', 'model_ids': ['products'],
            'severity': 'blocking', 'status': 'open', 'description': 'A newly identified definition gap.',
            'evidence_reference': 'synthetic://independent/new-gap'}]
        return request

    def test_newer_broad_rejection_overrides_older_narrow_acceptance(self):
        self.register()
        evidence.record_review(self.state, self.review(), self.run)
        evidence.record_review(self.state, self.review(['products']), self.run)
        evidence.record_review(self.state, self.rejected_review(), self.run)
        self.assertEqual(evidence.review_summary(self.state, ['products'])['status'], 'changes_requested')
        self.assertTrue(stages._design_gaps(self.state, ['products']))
        with self.assertRaisesRegex(ValueError, 'independent design review'):
            stages.record_design_review(self.state, ['products'], self.human_review(['products']))

    def test_newer_broad_acceptance_can_resolve_older_narrow_rejection(self):
        self.register()
        evidence.record_review(self.state, self.review(), self.run)
        evidence.record_review(self.state, self.rejected_review(['products']), self.run)
        self.assertEqual(evidence.review_summary(self.state, ['products'])['status'], 'changes_requested')
        evidence.record_review(self.state, self.review(), self.run)
        self.assertEqual(evidence.review_summary(self.state, ['products'])['status'], 'recorded')
        self.assertEqual(stages._design_gaps(self.state, ['products']), [])
        stages.record_design_review(self.state, ['products'], self.human_review(['products']))
        self.assertIn('products', stages.approved_entities(self.state))

    def test_unresolved_interface_blocks_review_but_explicit_draft_still_works(self):
        design = copy.deepcopy(self.doc); design['revision'] = 2
        interface = copy.deepcopy(design['entities'][0])
        interface.update(id='external_customer', name='External customer contract', domain='external',
            object_kind='interface', grain='unknown', keys=[], columns=[], security='unknown',
            history='unknown', disposition='undetermined', depends_on=[], source_paths=[],
            catalogue_pointers=[], asset_ids=[])
        design['entities'].append(interface)
        design['entities'][1]['depends_on'].append('external_customer')
        stages.import_design(self.state, design)
        self.assertTrue(any('external interface' in gap for gap in stages._design_gaps(self.state, ['orders'])))
        with self.assertRaisesRegex(ValueError, 'external interface'):
            stages.record_design_review(self.state, ['orders'], self.human_review(['orders']))
        request = {'schema_version': 1, 'kind': 'provisional_code_request', 'requester': 'Synthetic operator',
            'request_reference': 'synthetic://explicit-draft', 'request_text': 'Draft while the external contract is unresolved.',
            'bindings': stages.draft_bindings(self.state, ['orders'])}
        stages.record_draft_request(self.state, ['orders'], request)
        scope = stages.require_stage(self.state, 'implementation', ['orders'])
        self.assertEqual(stages.generation_mode(self.state, 'implementation', scope), 'provisional')
        self.assertEqual(stages.approved_entities(self.state), set())
        # A resolved external contract needs no implementation disposition.
        design['revision'] = 3
        interface.update(grain='One row per external customer', keys=['customer_id'],
            columns=[{'name': 'customer_id', 'type': 'integer', 'description': 'Declared external identity'}],
            security='Restricted to the selected domain', history='Current state')
        stages.import_design(self.state, design)
        self.assertEqual(stages._design_gaps(self.state, ['orders']), [])

    def test_actual_evidence_output_folder_cannot_overlap_any_input(self):
        readonly = self.run / 'review-evidence'; readonly.mkdir(exist_ok=True)
        raw = b'{}'; (readonly / 'capture.json').write_bytes(raw)
        request = self.coverage()
        request['sources'].append({'id': 'captured', 'namespace': 'synthetic.capture',
            'role': 'warehouse_catalogue', 'kind': 'external_inventory', 'status': 'available',
            'domain_ids': [], 'root': str(readonly), 'inventory': {'status': 'complete',
                'reference': 'synthetic://capture', 'files': [{'path': 'capture.json',
                    'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'parsed', 'object_ids': []}]}})
        coverage.record(self.state, request, self.run)
        before = {p.name: p.read_bytes() for p in readonly.iterdir()}
        state_before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'outside'):
            evidence.record(self.state, self.document(), self.run)
        self.assertEqual({p.name: p.read_bytes() for p in readonly.iterdir()}, before)
        self.assertEqual(self.state, state_before)

    def test_source_role_downgrade_invalidates_retained_observed_metadata(self):
        request = self.coverage(); request['sources'][0]['role'] = 'warehouse_catalogue'
        coverage.record(self.state, request, self.run)
        document = self.document(); document['claims'][0]['basis'] = 'observed_metadata'
        evidence.record(self.state, document, self.run)
        before = evidence.scope_bindings(self.state)
        request['sources'][0]['role'] = 'legacy_repository'
        coverage.record(self.state, request, self.run)
        self.assertEqual(evidence.summarize(self.state, ['customers'])['status'], 'gaps')
        self.assertTrue(evidence.gaps(self.state, ['customers']))
        self.assertNotEqual(before['customers'], evidence.scope_bindings(self.state)['customers'])
        self.assertEqual(before['products'], evidence.scope_bindings(self.state)['products'])
        with self.assertRaisesRegex(ValueError, 'warehouse_catalogue'):
            evidence.record(self.state, document, self.run)

    def test_design_only_domain_cannot_complete_after_independent_rejection(self):
        self.register()
        self.state['answers']['deliverables'] = ['erd']
        definition = {'id': 'commerce', 'name': 'Commerce', 'description': 'Synthetic design-only scope',
                      'asset_ids': [], 'source_paths': ['customers.sql', 'orders.sql', 'products.sql'],
                      'shared_dependency_ids': []}
        domains.register(self.state, {'schema_version': 1, 'domains': [definition]})
        request = {'schema_version': 1, 'domain_id': 'commerce', 'request_reference': 'synthetic://domain/choice'}
        domains.select_domain(self.state, {**request, 'candidates_sha256': domains.ledger(self.state)['candidates_sha256']})
        selected = ['customers', 'orders', 'products']
        evidence.record_review(self.state, self.review(), self.run)
        stages.record_design_review(self.state, selected, self.human_review(selected))
        self.assertIsNotNone(domains._progress(self.state, definition, [])[2])
        evidence.record_review(self.state, self.rejected_review(), self.run)
        self.assertEqual(set(selected), stages.approved_entities(self.state))
        with self.assertRaisesRegex(ValueError, 'independent design review'):
            domains.complete_domain(self.state, request)
        self.assertEqual(domains.ledger(self.state)['completions'], [])
        self.assertEqual(domains.ledger(self.state)['active_domain_id'], 'commerce')

    def baseline_fixture(self):
        existing = {'id': 'existing.customers', 'name': 'legacy.customers',
            'grain': 'One row per customer', 'keys': ['customers_id'],
            'definitions': 'Retained customer identities', 'history': 'Current state',
            'security': 'No personal fields selected', 'dependencies': [],
            'evidence_refs': ['capture.customers']}
        design = copy.deepcopy(self.doc); design['revision'] = 2
        design['existing_models'] = [copy.deepcopy(existing)]
        design['entities'][0].update(disposition='reuse', reuse={'existing_id': existing['id'],
            'rationale': 'Compare each retained dimension to its separately captured snapshot.',
            'dimensions': {dimension: {'status': 'compatible', 'evidence_refs': ['baseline.' + dimension],
                'explanation': 'Independent captured dimension supplied for comparison.'} for dimension in stages.DIMENSIONS}})
        stages.import_design(self.state, design)
        captured = self.root / 'captured-baseline'; captured.mkdir()
        different = {**existing, 'grain': 'One row per source event'}
        raw = json.dumps({'snapshots': [existing, different]}, sort_keys=True).encode()
        (captured / 'snapshot.json').write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        source = {'id': 'baseline', 'namespace': 'synthetic.existing', 'role': 'existing_models',
            'kind': 'external_inventory', 'status': 'available', 'domain_ids': ['commerce'],
            'root': str(captured), 'inventory': {'status': 'complete', 'reference': 'synthetic://baseline/capture',
                'files': [{'path': 'snapshot.json', 'sha256': sha, 'status': 'parsed', 'object_ids': ['captured.customers']}]}}
        expected = self.coverage(); expected['sources'].append(source)
        expected['objects'].append({'id': 'captured.customers', 'source_id': 'baseline',
            'native_id': existing['id'], 'kind': 'model', 'status': 'parsed', 'domain_ids': ['commerce'],
            'evidence_paths': ['snapshot.json'], 'depends_on': []})
        expected['assignments'].append({'id': 'baseline.customers', 'object_ids': ['captured.customers'],
            'consumer_ids': [], 'model_ids': ['customers'], 'kind': 'implementation',
            'reason': 'Retained customer model under comparison.'})
        coverage.record(self.state, expected, self.run)
        ref = {'source_id': 'baseline', 'path': 'snapshot.json', 'sha256': sha, 'locator': '/snapshots/0'}
        document = self.document()
        document['claims'].extend({'id': 'baseline.' + dimension, 'model_ids': ['customers'],
            'subject': dimension, 'basis': 'repository_declaration', 'statement': 'Captured baseline ' + dimension + '.',
            'sources': [{**ref, 'locator': '/snapshots/0/' + dimension}], 'baseline_id': existing['id']}
            for dimension in sorted(stages.DIMENSIONS))
        document['baselines'] = [{'existing_id': existing['id'], 'snapshot': copy.deepcopy(existing),
            'snapshot_source': ref, 'claim_ids': ['baseline.' + dimension for dimension in sorted(stages.DIMENSIONS)],
            'captured_by': 'Synthetic capture operator', 'capture_reference': 'synthetic://captured-snapshot'}]
        return document, expected

    def test_baseline_requires_exact_captured_json_pointer(self):
        document, _ = self.baseline_fixture()
        wrong = copy.deepcopy(document); wrong['baselines'][0]['snapshot_source']['locator'] = '/snapshots/1'
        with self.assertRaisesRegex(ValueError, 'JSON pointer'):
            evidence.record(self.state, wrong, self.run)
        self.assertNotIn('design_evidence', self.state['workflow'])
        evidence.record(self.state, document, self.run)
        self.assertEqual(evidence.gaps(self.state, ['customers']), [])
        # Matching the proposal and canonical baseline alone cannot manufacture
        # agreement with an independently retained snapshot.
        changed = copy.deepcopy(document)
        changed['baselines'][0]['snapshot']['grain'] = 'One row per proposed target event'
        self.state['workflow']['design']['existing_models'][0]['grain'] = 'One row per proposed target event'
        with self.assertRaisesRegex(ValueError, 'JSON pointer'):
            evidence.record(self.state, changed, self.run)

    def test_all_six_reuse_dimensions_need_independent_matching_evidence(self):
        document, _ = self.baseline_fixture()
        evidence.record(self.state, document, self.run)
        self.assertEqual(evidence.gaps(self.state, ['customers']), [])
        for dimension in sorted(stages.DIMENSIONS):
            with self.subTest(dimension=dimension):
                incomplete = copy.deepcopy(document); key = 'baseline.' + dimension
                incomplete['claims'] = [c for c in incomplete['claims'] if c['id'] != key]
                incomplete['baselines'][0]['claim_ids'].remove(key)
                evidence.record(self.state, incomplete, self.run)
                self.assertIn('customers: reuse ' + dimension + ' needs independent evidence',
                              evidence.gaps(self.state, ['customers']))
                self.assertEqual(evidence.gaps(self.state, ['products']), [])
        proposed = copy.deepcopy(document); proposed['claims'][-1]['basis'] = 'proposal'
        with self.assertRaisesRegex(ValueError, 'proposal'):
            evidence.record(self.state, proposed, self.run)

    def test_retained_baseline_source_role_is_rechecked(self):
        document, expected = self.baseline_fixture()
        evidence.record(self.state, document, self.run)
        expected['sources'][-1]['role'] = 'legacy_repository'
        coverage.record(self.state, expected, self.run)
        self.assertIn('customers: independent baseline source changed or is unavailable',
                      evidence.gaps(self.state, ['customers']))
        self.assertEqual(evidence.gaps(self.state, ['products']), [])


if __name__ == '__main__':
    unittest.main()
