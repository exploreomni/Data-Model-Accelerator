import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from disclosure_fixtures import synthetic_disclosure
import prepare_agent_input as staging


class PrepareAgentInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root/'source'; self.source.mkdir()
        self.content = b'SELECT order_id FROM orders\n'
        (self.source/'orders.sql').write_bytes(self.content)
        d = synthetic_disclosure(['x'])
        c = d['artifacts']['x']; c['handling']['agent_input']='allow'
        p = d['policy']; p['destinations']['agent_input']={'allowed_sensitivities':['PUBLIC'],'allowed_categories':[]}
        p['host_boundary']={'mode':'presanitized_only','evidence_reference':'synthetic-test-only'}
        self.request = {'schema_version':1,'kind':'agent_input_request','policy':p,
                        'files':[{'path':'orders.sql','sha256':hashlib.sha256(self.content).hexdigest(),'classification':c}]}

    def test_projection_preserves_original_and_has_restricted_permissions(self):
        out=self.root/'projection'; result=staging.prepare(self.source,self.request,out)
        self.assertEqual((out/'orders.sql').read_bytes(),self.content)
        self.assertEqual((self.source/'orders.sql').read_bytes(),self.content)
        self.assertEqual(out.stat().st_mode & 0o777,0o700)
        self.assertEqual((out/'orders.sql').stat().st_mode & 0o777,0o600)
        self.assertFalse(result['host_isolation_verified'])

    def test_claimed_protected_host_cannot_bypass(self):
        self.request['policy']['host_boundary']['mode']='claimed_enforced'
        with self.assertRaises(ValueError): staging.prepare(self.source,self.request,self.root/'denied')
        self.assertFalse((self.root/'denied').exists())

    def test_changed_input_and_path_escape_are_rejected(self):
        self.request['files'][0]['sha256']='b'*64
        with self.assertRaises(ValueError): staging.prepare(self.source,self.request,self.root/'denied')
        self.request['files'][0]['path']='../orders.sql'
        with self.assertRaises(ValueError): staging.prepare(self.source,self.request,self.root/'denied')

    def test_write_failure_cleans_only_run_owned_output(self):
        with patch.object(staging,'write_json',side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError): staging.prepare(self.source,self.request,self.root/'failed')
        self.assertFalse((self.root/'failed').exists())
        self.assertEqual((self.source/'orders.sql').read_bytes(),self.content)
