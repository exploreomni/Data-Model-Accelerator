"""Real local process and mocked HTTP transport boundaries; no warehouse calls."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import deployment_workflow as d


class Response(io.BytesIO):
    code = 200
    headers = {}


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        executable = Path(sys.executable).resolve()
        self.policy = {'mode': 'live', 'journal_key_env': 'DMA_JOURNAL',
                       'tools': {'fixture': {'path': str(executable), 'sha256': d.hash_file(executable)}}}
        self.transport = d.NativeTransport(self.policy, self.root)

    def test_real_process_does_not_inherit_unselected_secrets_or_journal(self):
        with patch.dict(os.environ, {'DMA_JOURNAL': 'private-journal', 'UNSELECTED_SECRET': 'private', 'FIXTURE_TOKEN': 'selected-secret'}):
            response = self.transport({'transport': 'process', 'argv': ['fixture', '-c',
                'import os,json; print(json.dumps(dict(os.environ)))'], 'auth_env': ['FIXTURE_TOKEN']})
        env = json.loads(response['stdout'])
        self.assertNotIn('DMA_JOURNAL', env)
        self.assertNotIn('UNSELECTED_SECRET', env)
        self.assertEqual(env['FIXTURE_TOKEN'], '[REDACTED]')

    def test_executable_and_runtime_configuration_drift_are_rejected(self):
        op = {'transport': 'process', 'argv': ['fixture', '-c', 'print(1)']}
        self.policy['tools']['fixture']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'executable changed'):
            self.transport(op)
        self.policy['tools']['fixture']['sha256'] = d.hash_file(Path(sys.executable).resolve())
        self.policy['runtime_env'] = {'FIXTURE_REGION': d.digest('reviewed')}
        with patch.dict(os.environ, {'FIXTURE_REGION': 'changed'}), self.assertRaisesRegex(ValueError, 'configuration drift'):
            self.transport(op)

    def test_token_bearer_basic_and_text_are_encoded_and_redacted(self):
        for scheme, prefix in [('token', 'Token '), ('bearer', 'Bearer '), ('basic', 'Basic ')]:
            with self.subTest(scheme=scheme), patch.dict(os.environ, {'FIXTURE_TOKEN': 'secret-value'}), patch('urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = Response(b'{"echo":"secret-value"}')
                response = self.transport({'transport': 'http', 'url': 'https://example.test', 'method': 'POST',
                    'text': 'select 1', 'auth': {'scheme': scheme, 'env': 'FIXTURE_TOKEN', 'username': 'fixture'}})
                request = opener.return_value.open.call_args.args[0]
                expected = base64.b64encode(b'fixture:secret-value').decode() if scheme == 'basic' else 'secret-value'
                self.assertEqual(request.headers['Authorization'], prefix + expected)
                self.assertEqual(request.data, b'select 1')
                self.assertEqual(response['body']['echo'], '[REDACTED]')

    def test_journal_key_cannot_be_platform_authentication(self):
        for operation in [
            {'transport': 'process', 'argv': ['fixture', '-c', 'print(1)'], 'auth_env': ['DMA_JOURNAL']},
            {'transport': 'http', 'url': 'https://example.test', 'auth': {'scheme': 'bearer', 'env': 'DMA_JOURNAL'}},
        ]:
            with self.assertRaises(ValueError):
                self.transport(operation)

    def test_oversized_native_output_is_not_accepted(self):
        with patch.object(d, 'MAX_RESPONSE', 1024), self.assertRaises((ValueError, TimeoutError)):
            self.transport({'transport': 'process', 'argv': ['fixture', '-c', 'print("x" * 5000)']})

    def test_simulation_and_redirects_cannot_execute_native_transport(self):
        self.policy['mode'] = 'simulation'
        with self.assertRaisesRegex(ValueError, 'Simulation'):
            self.transport({'transport': 'process', 'argv': ['fixture']})
        with self.assertRaisesRegex(ValueError, 'redirects'):
            d._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test')


if __name__ == '__main__':
    unittest.main()
