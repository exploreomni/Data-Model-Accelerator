"""Final handoff regression checks; synthetic files are not warehouse evidence."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import finalize_delivery as finalizer
from test_delivery_portal import fixture


class FinalizeDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.artifacts = self.root / 'candidate'
        self.artifacts.mkdir()
        self.state, self.review = fixture(self.artifacts)
        self.state['answers']['deliverables'] = ['documentation', 'diagrams', 'dictionary', 'implementation']
        self.review['handoff'] = {'design_artifact_id': '0'}
        self.output = self.root / 'delivery-v1'
        self.working_dir = self.root / 'private-work'

    def finalize(self, **kwargs):
        return finalizer.finalize_delivery(self.state, self.review, self.artifacts, self.output,
                                           working_dir=self.working_dir, **kwargs)

    def test_full_handoff_has_navigation_design_and_matching_extracted_files(self):
        before = copy.deepcopy((self.state, self.review))
        result = self.finalize()
        self.assertEqual(result['status'], 'handoff_verified')
        self.assertEqual(result['browser_review'], 'not_performed_by_finalizer')
        self.assertEqual(set(p.name for p in self.output.iterdir()), {'handoff', 'handoff.zip'})
        self.assertEqual(Path(result['entrypoint']).name, 'START_HERE.html')
        self.assertTrue((Path(result['design_folder']) / 'docs/model.md').is_file())
        self.assertTrue((Path(result['design_folder']) / 'ERD/model-001.svg').is_file())
        self.assertTrue((Path(result['design_folder']) / 'Dictionary/data-dictionary.csv').is_file())
        with zipfile.ZipFile(result['zip']) as archive:
            for name in archive.namelist():
                self.assertEqual(archive.read(name), (Path(result['folder']) / name).read_bytes())
            self.assertFalse(any('audit/' in name or 'seeds/' in name for name in archive.namelist()))
            manifest = json.loads(archive.read('DELIVERY_MANIFEST.json'))
            self.assertFalse(manifest['acceptance_ready'])
            self.assertFalse(manifest['deployment_authorized'])
        self.assertEqual((self.state, self.review), before)

    def test_selected_category_without_actual_files_is_incomplete(self):
        self.state['answers']['deliverables'].append('validation')
        with self.assertRaisesRegex(ValueError, 'Selected deliverables are missing: validation'):
            self.finalize()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.working_dir.glob('.dma-handoff-*')), [])

    def test_empty_design_document_does_not_satisfy_selected_documentation(self):
        (self.artifacts / 'docs/model.md').write_bytes(b'')
        self.review['artifacts'][0]['sha256'] = hashlib.sha256(b'').hexdigest()
        with self.assertRaisesRegex(ValueError, 'deliverables are missing: documentation'):
            self.finalize()
        self.assertFalse(self.output.exists())

    def test_provisional_files_package_without_upgrading_readiness(self):
        self.state['readiness']['generation_ready'] = False
        self.state['readiness']['execution_authorized'] = False
        self.review['description'] = 'Provisional code; catalogue bindings and business review pending.'
        result = self.finalize()
        page = Path(result['entrypoint']).read_text()
        self.assertIn('Provisional code; catalogue bindings and business review pending.', page)
        self.assertFalse(self.state['readiness']['execution_authorized'])

    def test_selected_documentation_needs_registered_audience_permitted_design(self):
        for mutation in ('no_binding', 'wrong_audience'):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.review)
                if mutation == 'no_binding':
                    self.review.pop('handoff')
                else:
                    self.review['artifacts'][0]['audiences'] = ['reviewer']
                with self.assertRaisesRegex(ValueError, 'design narrative|deliverables are missing'):
                    self.finalize()
                self.assertFalse(self.output.exists())
                self.review = original

    def test_missing_design_inventory_cannot_be_hidden_by_selected_code(self):
        self.review['models'] = []
        self.review['relationships'] = []
        with self.assertRaisesRegex(ValueError, 'Selected deliverables are missing'):
            self.finalize()
        self.assertFalse(self.output.exists())

    def test_canonical_model_omission_fails_even_with_matching_design_binding(self):
        manifest = {'files': [{'path': 'START_HERE.html'}, {'path': '01_Model/ERD/model.svg', 'category': 'diagrams', 'bytes': 123}]}
        self.state['workflow'] = {'design': {'entities': self.review['models'] + [{'id': 'gold.omitted'}]}}
        with self.assertRaisesRegex(ValueError, 'model coverage differs'):
            finalizer.check_selected_delivery(self.state, self.review, 'engineer', ['diagrams'], manifest)

    def test_design_only_reviewer_and_explicit_code_only_remain_supported(self):
        self.state['answers']['audience'] = 'reviewer'
        result = self.finalize()
        with zipfile.ZipFile(result['zip']) as archive:
            self.assertFalse(any(name.startswith('02_Implementation/') for name in archive.namelist()))
            self.assertIn('01_Model/docs/model.md', archive.namelist())
        self.output = self.root / 'code-only-v1'
        result = self.finalize(audience='engineer', include=['implementation'])
        self.assertIsNone(result['design_folder'])
        self.assertEqual(result['selected_deliverable_counts'], {'implementation': 1})
        with zipfile.ZipFile(result['zip']) as archive:
            self.assertIn('START_HERE.html', archive.namelist())
            self.assertFalse(any(name.startswith('01_Model/') for name in archive.namelist()))

    def test_audit_remains_separate(self):
        result = self.finalize(audience='audit')
        self.assertIsNone(result['design_folder'])
        self.assertEqual(result['selected_deliverable_counts'], {'technical_audit': 1})

    def test_bad_hash_or_page_failure_publishes_no_delivery(self):
        original = self.review['artifacts'][0]['sha256']
        self.review['artifacts'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.finalize()
        self.assertFalse(self.output.exists())
        self.review['artifacts'][0]['sha256'] = original
        with patch.object(portal, 'check_page', side_effect=ValueError('Navigation check failed')):
            with self.assertRaisesRegex(ValueError, 'Navigation check failed'):
                self.finalize()
        self.assertFalse(self.output.exists())

    def test_verifier_rejects_missing_navigation_before_publication(self):
        original = portal.package_delivery
        def broken(*args, **kwargs):
            manifest = original(*args, **kwargs)
            path = args[3]
            with zipfile.ZipFile(path) as archive:
                entries = {name: archive.read(name) for name in archive.namelist() if name != 'START_HERE.html'}
            with zipfile.ZipFile(path, 'w') as archive:
                for name, body in entries.items():
                    archive.writestr(name, body)
            return manifest
        with patch.object(portal, 'package_delivery', side_effect=broken):
            with self.assertRaisesRegex(ValueError, 'Start Here'):
                self.finalize()
        self.assertFalse(self.output.exists())

    def test_frozen_exports_and_candidate_directory_are_preserved(self):
        result = self.finalize()
        digest = hashlib.sha256(Path(result['zip']).read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.finalize()
        self.assertEqual(digest, hashlib.sha256(Path(result['zip']).read_bytes()).hexdigest())
        self.output = self.artifacts / 'bad-delivery'
        with self.assertRaisesRegex(ValueError, 'must be separate'):
            self.finalize()

    def test_exclusive_output_creation_preserves_new_directory(self):
        original = Path.mkdir
        marker = []
        def appeared(path, *args, **kwargs):
            if path == self.output and not path.exists():
                original(path)
                marker.append(path.stat().st_ino)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', appeared):
            with self.assertRaises(FileExistsError):
                self.finalize()
        self.assertEqual(self.output.stat().st_ino, marker[0])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_replaced_staging_directory_is_never_removed(self):
        original = portal.check_page
        replacement = []
        def replaced(*args, **kwargs):
            result = original(*args, **kwargs)
            staging = next(self.working_dir.glob('.dma-handoff-*'))
            staging.rename(self.root / 'retained-original-staging')
            staging.mkdir()
            (staging / 'unrelated.txt').write_text('Keep this file')
            replacement.append(staging)
            return result
        with patch.object(portal, 'check_page', side_effect=replaced):
            with self.assertRaisesRegex(ValueError, 'staging directory changed'):
                self.finalize()
        self.assertEqual((replacement[0] / 'unrelated.txt').read_text(), 'Keep this file')
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(shutil.which('node'), 'Node required for emitted JavaScript syntax checks')
    def test_finalizer_checks_actual_emitted_javascript(self):
        result = self.finalize(javascript=True)
        self.assertIn('javascript', result['page_check'])


if __name__ == '__main__':
    unittest.main()
