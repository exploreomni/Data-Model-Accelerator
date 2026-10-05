"""Focused transport, recovery and receipt tests; no live network calls."""
import copy
from email.message import Message
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_native as native


def response(value, content_type='text/ndjson'):
    return native.Response(200, json.dumps(value).encode(), content_type)


class Journal:
    def __init__(self):
        self.data = {'query': None}
        self.saves = 0
    def save(self):
        self.saves += 1


class NativeTransportTests(unittest.TestCase):
    def test_actual_http_408_retains_bounded_resume_body(self):
        headers = Message(); headers['Content-Type'] = 'application/json'
        data = b'{"remaining_job_ids":["a0000000-0000-4000-8000-000000000001"]}'
        with patch.dict(os.environ, {'OMNI_API_TOKEN': 'synthetic-unit-token'}):
            transport = native.HTTPSOmniTransport('https://synthetic-unit.omniapp.co')
        error = HTTPError('https://synthetic-unit.omniapp.co/api/v1/query/run', 408, 'sensitive-provider-text', headers, io.BytesIO(data))
        with patch.object(transport._opener, 'open', side_effect=error):
            reply = transport.request('POST', '/api/v1/query/run', body={})
        self.assertEqual((reply.status, reply.body, reply.content_type), (408, data, 'application/json'))

    def test_http_errors_do_not_echo_provider_body_or_allow_redirects(self):
        with patch.dict(os.environ, {'OMNI_API_TOKEN': 'synthetic-unit-token'}):
            transport = native.HTTPSOmniTransport('https://synthetic-unit.omniapp.co')
        error = HTTPError('https://synthetic-unit.omniapp.co/api/v1/models', 401, 'sensitive-provider-text', Message(), io.BytesIO(b'sensitive-provider-body'))
        with patch.object(transport._opener, 'open', side_effect=error):
            with self.assertRaises(native.TransportError) as found:
                transport.request('GET', '/api/v1/models')
        self.assertNotIn('sensitive', str(found.exception))
        self.assertEqual(found.exception.code, 'transport.http')
        self.assertIsNone(native._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_targets_and_v2_mutations_fail_before_transport(self):
        for url in ('http://synthetic.omniapp.co', 'https://synthetic.omniapp.co.evil.example',
                    'https://synthetic.omniapp.co/path', 'https://synthetic.omniapp.co:444',
                    'https://user@synthetic.omniapp.co', 'https://127.0.0.1'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                native.HTTPSOmniTransport(url)
        with patch.dict(os.environ, {'OMNI_API_TOKEN': 'synthetic-unit-token'}):
            transport = native.HTTPSOmniTransport('https://synthetic-unit.omniapp.co')
        with self.assertRaises(ValueError):
            transport.request('PATCH', '/api/v2/documents/example')

    def test_ndjson_footer_only_timeout_resumes_without_resubmission(self):
        job = 'a0000000-0000-4000-8000-000000000001'
        class Remote:
            def __init__(self): self.calls = []
            def request(self, method, path, params=None, body=None):
                self.calls.append((method, path, params))
                if method == 'POST':
                    return native.Response(408, json.dumps({'remaining_job_ids': [job]}).encode())
                if len(self.calls) <= 3:
                    return response({'remaining_job_ids': [job], 'timed_out': 'true'})
                return native.Response(200, (json.dumps({'job_id': job, 'status': 'COMPLETE', 'summary': {'sql': 'SELECT hidden_value'}}) + '\n' + json.dumps({'remaining_job_ids': [], 'timed_out': 'false'})).encode(), 'text/ndjson')
        request = {'target': {'branch_id': 'branch', 'environment_connection_id': 'environment'}, 'query': {},
                   'query_mode': 'plan', 'timezone': 'UTC'}
        remote, journal = Remote(), Journal()
        pending = native._query(remote, request, journal, lambda: None)
        self.assertTrue(pending['pending'])
        self.assertEqual(journal.data['query']['state'], 'jobs')
        complete = native._query(remote, request, journal, lambda: None)
        self.assertNotIn('pending', complete)
        self.assertEqual(complete['completed_jobs'], [job])
        self.assertEqual(sum(call[0] == 'POST' for call in remote.calls), 1)
        self.assertNotIn('hidden_value', json.dumps(journal.data))
        with self.assertRaisesRegex(native.AdapterError, 'already_completed'):
            native._query(remote, request, journal, lambda: None)

    def test_receipt_verification_is_integrity_only_and_binds_query_lane(self):
        request = {'operation': 'query', 'target': {'model_id': 'synthetic'}, 'files': {'v.view': 'x'},
                   'context': {}, 'query_mode': 'plan', 'timezone': 'UTC'}
        receipt = {'schema_version': 1, 'kind': 'omni_native_receipt', 'contract_version': native.CONTRACT,
                   'request_sha256': native.canonical_hash(request), 'target': request['target'],
                   'candidate_sha256': native.canonical_hash(request['files']), 'context_sha256': native.canonical_hash({}),
                   'policy_sha256': 'a' * 64, 'operation': 'query', 'query_mode': 'plan', 'timezone': 'UTC',
                   'query_lane': 'native_compilation', 'execution_mode': 'simulation', 'status': 'simulated_passed',
                   'native_verified': False, 'remote_before': dict.fromkeys(native.SNAPSHOT_KEYS, 'b' * 64),
                   'remote_after': dict.fromkeys(native.SNAPSHOT_KEYS, 'b' * 64), 'query': {'response_sha256': ['c' * 64]}}
        with patch.object(native, 'validate_request', side_effect=lambda value: copy.deepcopy(value)):
            result = native.verify_receipt(request, receipt, 'a' * 64)
            self.assertEqual(result['status'], 'integrity_verified')
            self.assertFalse(result['authenticated'])
            altered = copy.deepcopy(receipt); altered['query_lane'] = 'modeled_query_execution'
            self.assertEqual(native.verify_receipt(request, altered, 'a' * 64)['status'], 'failed')
            altered = copy.deepcopy(receipt); altered['native_verified'] = True
            self.assertEqual(native.verify_receipt(request, altered, 'a' * 64)['status'], 'failed')

    def test_repair_is_bounded_and_requires_separate_semantic_attestation(self):
        with self.assertRaisesRegex(native.AdapterError, 'bounded_reviewed'):
            native.run_reviewed_variants([{}, {}, {}], policy_path='unused', candidate_root='unused', approvals=[{}, {}, {}])
        requests = [{'destination_id': 'dev', 'target': {'model_id': 'synthetic'}},
                    {'destination_id': 'dev', 'target': {'model_id': 'synthetic'}, 'revision': 2}]
        with patch.object(native, 'run', return_value={'status': 'failed'}) as run, \
             patch.object(native, '_policy', return_value=({}, 'a' * 64)), \
             patch.object(native, '_approval', return_value={'claims': {}}):
            result = native.run_reviewed_variants(requests, policy_path='unused', candidate_root='unused', approvals=[{}, {}])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result['status'], 'requires_review')
        self.assertFalse(result['automatic_fixes_applied'])


if __name__ == '__main__': unittest.main()
