"""Synthetic provenance, review freshness and explicit provisional-code journeys."""
import copy
import hashlib
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import test_engagement_stages as support
import engagement_stages as stages
import design_coverage
import design_evidence as evidence
import design_readiness


class EvidenceTests(unittest.TestCase):
    setUp = support.StageTests.setUp
    action = support.StageTests.action

    def coverage(self):
        names = ('customers', 'orders', 'products')
        files = [{'path': n + '.sql', 'sha256': hashlib.sha256((self.repo / (n + '.sql')).read_bytes()).hexdigest(),
                  'status': 'parsed', 'object_ids': ['src:' + n]} for n in names]
        return {'schema_version': 1, 'sources': [{'id': 'source', 'namespace': 'synthetic', 'role': 'legacy_repository',
            'kind': 'repository', 'status': 'available', 'domain_ids': ['commerce'], 'root': str(self.repo),
            'inventory': {'status': 'complete', 'reference': 'synthetic://inventory', 'files': files}}],
            'objects': [{'id': 'src:' + n, 'source_id': 'source', 'native_id': n, 'kind': 'model', 'status': 'parsed',
                         'domain_ids': ['commerce'], 'evidence_paths': [n + '.sql'], 'depends_on': []} for n in names],
            'consumers': [], 'assignments': [{'id': 'map:' + n, 'object_ids': ['src:' + n], 'consumer_ids': [],
                'model_ids': [n], 'kind': 'implementation', 'reason': 'Synthetic retained computation'} for n in names]}

    def document(self):
        files = self.coverage()['sources'][0]['inventory']['files']
        return {'schema_version': 1, 'kind': 'design_evidence', 'baselines': [], 'claims': [
            {'id': 'claim:' + n, 'model_ids': [n], 'subject': 'keys', 'basis': 'repository_declaration',
             'statement': 'SQL declares an output field; uniqueness has not been executed.',
             'sources': [{'source_id': 'source', 'path': f['path'], 'sha256': f['sha256'], 'locator': 'line 1'}]}
            for n, f in zip(('customers', 'orders', 'products'), files)]}

    def register(self):
        self.action('record-design-coverage', document=self.coverage())
        self.action('record-design-evidence', document=self.document())

    def review(self, selected=None):
        selected = selected or ['customers', 'orders', 'products']
        pins = evidence.review_bindings(self.state, selected)
        claims = [c['id'] for c in self.document()['claims'] if set(c['model_ids']) & set(pins['entities'])]
        return {'schema_version': 1, 'kind': 'independent_design_review', 'reviewer_id': 'reviewer',
                'author_ids': ['architect'], 'review_reference': 'synthetic://independent-review', 'bindings': pins,
                'claim_ids': claims, 'findings': [], 'result': 'accepted', 'execution': {
                    'host': 'synthetic', 'task_reference': 'synthetic://task', 'context_reference': 'synthetic://packet',
                    'requested_model': None, 'observed_model': None, 'requested_effort': None, 'observed_effort': None}}

    def test_legacy_read_only_is_unassessed_and_bindings_unchanged(self):
        before = copy.deepcopy(self.state)
        pins = stages.entity_bindings(self.state, ['orders'])
        self.assertEqual(evidence.summarize(self.state)['status'], 'unassessed')
        self.assertEqual(evidence.readiness_gaps(self.state, ['orders']), [])
        self.assertEqual(stages.entity_bindings(self.state, ['orders']), pins)
        self.assertEqual(self.state, before)

    def test_declaration_cannot_become_observed_raw_catalogue(self):
        self.action('record-design-coverage', document=self.coverage())
        doc = self.document(); doc['claims'][0]['basis'] = 'observed_metadata'
        with self.assertRaisesRegex(ValueError, 'warehouse_catalogue'):
            self.action('record-design-evidence', document=doc)

    def test_source_reference_hash_and_scope_are_checked(self):
        self.action('record-design-coverage', document=self.coverage())
        for mutation in ('hash', 'path', 'source'):
            doc = self.document(); ref = doc['claims'][0]['sources'][0]
            ref[{'hash': 'sha256', 'path': 'path', 'source': 'source_id'}[mutation]] = 'not-registered'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.action('record-design-evidence', document=doc)

    def test_author_cannot_independently_approve_and_claims_cannot_be_skipped(self):
        self.register()
        doc = self.review(); doc['reviewer_id'] = 'architect'
        with self.assertRaisesRegex(ValueError, 'Author'):
            self.action('record-independent-review', document=doc)
        doc = self.review(); doc['claim_ids'] = []
        with self.assertRaisesRegex(ValueError, 'scoped evidence'):
            self.action('record-independent-review', document=doc)

    def test_review_freshness_propagates_only_to_affected_descendants(self):
        self.register()
        self.action('record-independent-review', document=self.review())
        self.assertEqual(evidence.review_summary(self.state)['status'], 'recorded')
        (self.repo / 'customers.sql').write_text('select 2 as customers_id')
        self.assertEqual(evidence.review_summary(self.state, ['products'])['status'], 'recorded')
        self.assertEqual(evidence.review_summary(self.state, ['orders'])['status'], 'stale')
        self.assertTrue(evidence.gaps(self.state, ['customers']))

    def test_evidence_edit_stales_review_but_does_not_touch_unrelated_model(self):
        self.register()
        self.action('record-independent-review', document=self.review())
        pins = stages.entity_bindings(self.state, ['products'])
        doc = self.document(); doc['claims'][0]['statement'] = 'Revised proposal interpretation'
        self.action('record-design-evidence', document=doc)
        self.assertEqual(stages.entity_bindings(self.state, ['products']), pins)
        self.assertEqual(evidence.review_summary(self.state, ['orders'])['status'], 'stale')
        self.assertEqual(evidence.review_summary(self.state, ['products'])['status'], 'recorded')

    def test_removed_evidence_retains_invalidation(self):
        self.register()
        before = stages.entity_bindings(self.state, ['customers'])
        doc = self.document(); doc['claims'] = []
        self.action('record-design-evidence', document=doc)
        self.assertIn('customers', evidence.scope_bindings(self.state))
        self.assertNotEqual(before, stages.entity_bindings(self.state, ['customers']))
        self.assertTrue(evidence.gaps(self.state, ['customers']))

    def test_review_is_not_human_approval_and_unknown_model_is_preserved(self):
        self.register()
        self.action('record-independent-review', document=self.review())
        self.assertEqual(stages.approved_entities(self.state), set())
        summary = design_readiness.summarize(self.state)
        self.assertEqual(summary['independent_review']['status'], 'recorded')
        self.assertEqual(summary['human_review']['status'], 'unassessed')
        self.assertEqual(summary['native_validation']['status'], 'unassessed')
        self.assertNotIn(str(self.repo), str(summary))
        self.assertEqual(summary['counts']['models'], 3)
        self.assertEqual(design_readiness.summarize(self.state, ['products'])['counts']['models'], 1)

    def test_blocking_findings_prevent_accepted_record(self):
        self.register()
        doc = self.review(); doc['findings'] = [{'id': 'bad-key', 'model_ids': ['customers'], 'severity': 'blocking',
            'status': 'open', 'description': 'Synthetic missing key evidence', 'evidence_reference': 'synthetic://evidence'}]
        with self.assertRaisesRegex(ValueError, 'blocking'):
            self.action('record-independent-review', document=doc)
        doc['result'] = 'changes_requested'
        self.action('record-independent-review', document=doc)
        self.assertEqual(evidence.review_summary(self.state)['status'], 'changes_requested')

    def test_missing_inventory_does_not_block_explicit_provisional_generation(self):
        self.action('record-design-coverage', document={'schema_version': 1, 'sources': [], 'objects': [], 'consumers': [], 'assignments': []})
        request = {'schema_version': 1, 'kind': 'provisional_code_request', 'requester': 'Synthetic operator',
                   'request_reference': 'synthetic://explicit-draft-request',
                   'request_text': 'Generate provisional code while coverage is missing.',
                   'bindings': stages.draft_bindings(self.state, ['orders'])}
        self.action('request-draft', entities=['orders'], document=request)
        self.assertEqual(stages.generation_mode(self.state, 'implementation', ['customers', 'orders']), 'provisional')
        self.action('stage', entities=['orders'], stage='implementation')


if __name__ == '__main__':
    unittest.main()
