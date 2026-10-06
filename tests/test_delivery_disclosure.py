"""No customer data: exercise real packaging paths with fictional canaries."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from test_delivery_portal import fixture
import delivery_portal as portal


class DeliveryDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state, self.review = fixture(self.root)

    def test_allowed_documentation_cannot_bypass_content_scan(self):
        content = b'Contact: synthetic.person@example.invalid'
        (self.root / 'docs/model.md').write_bytes(content)
        self.review['artifacts'][0]['sha256'] = hashlib.sha256(content).hexdigest()
        with self.assertRaises(ValueError) as error:
            portal.package_delivery(self.state, self.review, self.root, self.root/'blocked.zip')
        self.assertNotIn('synthetic.person', str(error.exception))
        self.assertFalse((self.root/'blocked.zip').exists())

    def test_review_text_is_scanned_before_embedding(self):
        self.review['title'] = 'Contact synthetic.person@example.invalid'
        with self.assertRaises(ValueError):
            portal.package_delivery(self.state, self.review, self.root, self.root/'blocked.zip')
        self.assertFalse((self.root/'blocked.zip').exists())

    def test_clean_candidate_retains_pending_acceptance_and_scan_bounds(self):
        result = portal.package_delivery(self.state, self.review, self.root, self.root/'candidate.zip')
        self.assertFalse(result['acceptance_ready'])
        self.assertTrue(result['disclosure_scans'])
        self.assertTrue(all(s['status']=='clear' for s in result['disclosure_scans'].values()))
        self.assertEqual(portal.verify_delivery(self.root/'candidate.zip')['status'],'integrity_verified')

    def test_explicit_scope_requires_audience_policy_and_classification(self):
        from disclosure_fixtures import synthetic_disclosure
        self.state['answers']['migration_scope']='full_dashboard'
        self.review['context_sha256']=portal.context_fingerprint(self.state)
        with self.assertRaisesRegex(ValueError, 'disclosure contract'):
            portal.package_delivery(self.state,self.review,self.root,self.root/'denied.zip')
        self.review['disclosure']=synthetic_disclosure(['0'],'reviewer')
        result=portal.package_delivery(self.state,self.review,self.root,self.root/'allowed.zip')
        self.assertFalse(result['acceptance_ready'])
        self.review['disclosure']['artifacts']['0']['sensitivity']='UNKNOWN'
        with self.assertRaisesRegex(ValueError, 'disclosure policy'):
            portal.package_delivery(self.state,self.review,self.root,self.root/'unknown.zip')

    def test_archive_magic_cannot_hide_behind_document_extension(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('clean.txt','ordinary synthetic data')
        content=stream.getvalue()
        (self.root/'docs/model.md').write_bytes(content)
        self.review['artifacts'][0]['sha256']=hashlib.sha256(content).hexdigest()
        with self.assertRaisesRegex(ValueError,'Nested archives'):
            portal.package_delivery(self.state,self.review,self.root,self.root/'blocked.zip')
