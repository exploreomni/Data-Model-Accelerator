"""Interrupted handoffs remain useful without becoming final deliveries."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import finalize_delivery as finalizer
from test_delivery_portal import fixture


class CheckpointDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.artifacts = self.root / 'candidate'; self.artifacts.mkdir()
        self.state, self.review = fixture(self.artifacts)
        self.state['answers']['deliverables'] = ['documentation', 'diagrams', 'dictionary', 'implementation', 'validation']
        self.review['handoff'] = {'design_artifact_id': '0'}

    def test_partial_package_is_labeled_in_page_readme_and_manifest(self):
        before = copy.deepcopy((self.state, self.review))
        result = finalizer.finalize_delivery(self.state, self.review, self.artifacts,
            self.root / 'checkpoint', checkpoint=True)
        self.assertEqual(result['status'], 'checkpoint_verified')
        with zipfile.ZipFile(result['zip']) as archive:
            manifest = json.loads(archive.read('DELIVERY_MANIFEST.json'))
            self.assertEqual(manifest['delivery_kind'], 'checkpoint')
            self.assertIn('validation', manifest['checkpoint']['missing_categories'])
            self.assertIn(b'Checkpoint', archive.read('README.md'))
            self.assertIn(b'checkpoint', archive.read('START_HERE.html'))
            self.assertFalse(manifest['acceptance_ready'])
        self.assertEqual((self.state, self.review), before)
        with self.assertRaisesRegex(ValueError, 'validation'):
            finalizer.finalize_delivery(self.state, self.review, self.artifacts, self.root / 'final')

    def test_empty_interrupted_run_still_has_entrypoint_and_requested_scope(self):
        self.review.update(models=[], relationships=[], artifacts=[])
        self.review.pop('handoff', None)
        result = finalizer.finalize_delivery(self.state, self.review, self.artifacts,
            self.root / 'empty-checkpoint', checkpoint=True)
        with zipfile.ZipFile(result['zip']) as archive:
            self.assertEqual(set(archive.namelist()), {'START_HERE.html', 'README.md', 'DELIVERY_MANIFEST.json'})
            manifest = json.loads(archive.read('DELIVERY_MANIFEST.json'))
            self.assertEqual(set(manifest['checkpoint']['missing_categories']), set(self.state['answers']['deliverables']))

    def test_checkpoint_still_checks_file_integrity_and_never_overwrites(self):
        result = finalizer.finalize_delivery(self.state, self.review, self.artifacts,
            self.root / 'checkpoint', checkpoint=True)
        original = Path(result['zip']).read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            finalizer.finalize_delivery(self.state, self.review, self.artifacts,
                self.root / 'checkpoint', checkpoint=True)
        self.assertEqual(Path(result['zip']).read_bytes(), original)
        self.review['artifacts'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            finalizer.finalize_delivery(self.state, self.review, self.artifacts,
                self.root / 'invalid', checkpoint=True)
        self.assertFalse((self.root / 'invalid').exists())
