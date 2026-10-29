"""Optional domain companion uses the existing finalizer and selected audience."""
import copy
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import domain_review_page as page
import finalize_delivery as finalizer
from test_delivery_portal import fixture


class DomainReviewDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.artifacts = self.root / 'candidate'; self.artifacts.mkdir()
        self.state, self.review = fixture(self.artifacts)
        self.review['domain_review'] = {'domain': 'orders'}
        self.review['handoff'] = {'design_artifact_id': '0'}
        for model in self.review['models']:
            model.update(domain='orders')

    def package(self, name, **kwargs):
        output = self.root / (name + '.zip')
        portal.package_delivery(self.state, self.review, self.artifacts, output,
                                audience=kwargs.pop('audience', 'engineer'), **kwargs)
        portal.verify_delivery(output)
        with zipfile.ZipFile(output) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_finalizer_retains_one_start_here_and_candidate_authority(self):
        self.review['package_layout_version'] = 2
        self.state['answers']['deliverables'] = ['documentation', 'diagrams', 'dictionary', 'implementation']
        self.review['context_sha256'] = portal.context_fingerprint(self.state)
        result = finalizer.finalize_delivery(self.state, self.review, self.artifacts, self.root / 'handoff',
                                            working_dir=self.root / 'work')
        with zipfile.ZipFile(result['zip']) as archive:
            names = archive.namelist()
            self.assertEqual([n for n in names if n.endswith('START_HERE.html')], ['START_HERE.html'])
            companion = '03_Design_Documents/Domain_Review.html'
            self.assertIn(companion, names)
            self.assertIn(companion, archive.read('START_HERE.html').decode())
            data = page.page_data(archive.read(companion).decode())
            self.assertEqual(len(data['models']), 3)
            self.assertTrue(all(m['disp'] == 'unassessed' for m in data['models']))
            self.assertIn('dbt on snowflake', data['meta']['facts'])
            manifest = json.loads(archive.read('DELIVERY_MANIFEST.json'))
            self.assertFalse(manifest['acceptance_ready'])
            self.assertFalse(manifest['deployment_authorized'])
            self.assertTrue(all(f['path'].startswith('04_Code_Generation/') for f in data['files']))

    def test_audience_and_selection_cannot_be_expanded_by_companion(self):
        self.review['package_layout_version'] = 2
        rows = self.package('reviewer', audience='reviewer', include=['documentation'])
        data = page.page_data(rows['03_Design_Documents/Domain_Review.html'].decode())
        self.assertEqual(data['files'], [])
        self.assertTrue(all(not m['cols'] for m in data['models']))
        self.assertNotIn('PRIVATE_VALUE_MARKER', json.dumps(data))
        self.assertNotIn('SENSITIVE_RAW_MARKER', json.dumps(data))
        self.assertNotIn('INTERNAL_AUDIT_MARKER', json.dumps(data))
        for name, options in [('audit', {'audience': 'audit', 'include': ['technical_audit']}),
                              ('code-only', {'include': ['implementation']})]:
            rows = self.package(name, **options)
            self.assertFalse(any(p.endswith('Domain_Review.html') for p in rows))
        self.review.pop('domain_review')
        self.assertFalse(any(p.endswith('Domain_Review.html') for p in self.package('default', include=['documentation'])))

    def test_native_and_coalesce_files_keep_the_selected_framework(self):
        for framework in ('native_sql', 'coalesce'):
            self.state['answers']['framework'] = framework
            self.review['target']['framework'] = framework
            self.review['context_sha256'] = portal.context_fingerprint(self.state)
            rows = self.package(framework, include=['documentation', 'implementation'])
            data = page.page_data(rows['01_Model/Domain_Review.html'].decode())
            self.assertIn(framework + ' on snowflake', data['meta']['facts'])
            self.assertEqual(data['files'][0]['content'], 'select 1 as id')
            self.assertNotIn('Models without YAML', [s['label'] for s in data['static']])
            self.assertFalse(any(f['path'].startswith('02_dbt/') for f in data['files']))

    @unittest.skipUnless(importlib.util.find_spec('yaml') and importlib.util.find_spec('sqlglot'),
                         'Pinned YAML/SQL runtime required for native topology evidence')
    def test_companion_reuses_selected_omni_topology_and_relocated_files(self):
        from test_topic_delivery import fixture as semantic_fixture
        self.state, self.review = semantic_fixture(self.artifacts)
        self.review['domain_review'] = {'domain': 'Sales'}
        for model in self.review['models']:
            model['disposition'] = 'create'
        rows = self.package('semantic', include=['documentation', 'implementation', 'validation'])
        data = page.page_data(rows['03_Design_Documents/Domain_Review.html'].decode())
        topics = {t['topic']: t for t in data['topics']}
        self.assertEqual(set(topics), {'activity', 'health'})
        self.assertEqual(topics['activity']['base_model_ids'], ['gold.orders'])
        self.assertEqual(topics['health']['base_model_ids'], [])
        self.assertEqual(topics['health']['domain'], 'Operations')
        for topic in topics.values():
            self.assertIn(topic['path'], [f['path'] for f in data['files']])
        # An omitted private/native evidence artifact must not become a complete mapping.
        next(a for a in self.review['artifacts'] if a['id'] == self.review['omni']['artifact_id'])['audiences'] = ['reviewer']
        rows = self.package('semantic-omitted', include=['documentation', 'implementation'])
        omitted = page.page_data(rows['03_Design_Documents/Domain_Review.html'].decode())
        self.assertTrue(all(not t['base_model_ids'] for t in omitted['topics']))
        self.assertTrue(any(o['kind'] == 'Semantic gap' for o in omitted['open']))

    def test_existing_sparse_metadata_does_not_become_a_new_delivery_gate(self):
        self.review['decisions'] = [{'id': 'decision-1', 'question': 'Owner?', 'answer': None}]
        self.review['changes'] = [{'id': 'change-1', 'description': 'Review key grain'}]
        self.review['assets'] = [{'id': 'source-1', 'name': 'Source table', 'kind': 'source_table', 'mapping_status': 'mapped'},
                                 {'id': 'dashboard-1', 'name': 'Orders', 'kind': 'bi_dashboard'}]
        rows = self.package('sparse', include=['documentation'])
        data = page.page_data(rows['01_Model/Domain_Review.html'].decode())
        self.assertEqual(data['decisions'][0]['status'], 'unassessed')
        self.assertEqual(len(data['dashboards']), 1)
        self.assertEqual(data['dashboards'][0]['status'], 'unassessed')
        self.assertEqual(data['legacy'], [])
        self.assertTrue(any('Review key grain' in r for r in data['remaining']))

    def test_opt_in_still_rejects_stale_bytes_and_invalid_options(self):
        bad = copy.deepcopy(self.review)
        for value in ({}, {'domain': ''}, {'domain': 'orders', 'bypass': True}):
            bad['domain_review'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'domain_review'):
                portal.validate_review(self.state, bad)
        self.review['artifacts'][1]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.package('stale', include=['documentation', 'implementation'])
        self.assertFalse((self.root / 'stale.zip').exists())


if __name__ == '__main__':
    unittest.main()
