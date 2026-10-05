"""Independent synthetic native contract probes; never contacts an Omni tenant."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_contract
import omni_native as native

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except ImportError:
    Ed25519PrivateKey = None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def uid(n):
    return '10000000-0000-4000-8000-' + str(n).zfill(12)


def candidate():
    return {'fleet.view': 'catalog: ANALYTICS\nschema: GOLD\ntable_name: FLEET\ndimensions:\n  id:\n    sql: \'"ID"\'\n  traveled_at:\n    sql: \'"TRAVELED_AT"\'\n    timeframes: [date]\nmeasures:\n  journeys:\n    aggregate_type: count\n',
            'fleet.topic': 'base_view: fleet\njoins: {}\nfields:\n  - fleet.traveled_at[date]\n  - fleet.journeys\n'}


def context():
    return {'schema_version': 1, 'kind': 'omni_model_context', 'warehouse': 'snowflake',
            'environment': 'development', 'catalogue_sha256': 'a' * 64,
            'bindings': {'fleet': {'namespace': {'database': 'ANALYTICS', 'schema': 'GOLD', 'table': 'FLEET'},
                                   'columns': {'ID': 'number', 'TRAVELED_AT': 'timestamp'},
                                   'evidence_sha256': 'b' * 64}},
            'inherited_views': {}, 'default_catalog': None, 'user_attributes': [], 'access_grants': []}


class Remote:
    """Small API4-like response fixture; assertions are independent of adapter helpers."""
    def __init__(self, target, files):
        self.target = target
        self.files = copy.deepcopy(files)
        self.base_files = {'model': 'label: Synthetic base\n'}
        self.schema_files = {'fleet.view': 'table_name: FLEET\n'}
        self.calls = []
        self.validation_body = b'[]'
        self.validation_status = 200
        self.validation_mutation = None
        self.write_error = None
        self.write_commits_before_error = False
        self.query_reply = None
        self.query_error = None
        self.schema_generation = 1
        self.version = 1
        self.wrong_principal = False
        self.wrong_branch = False

    def snapshot(self, files, version=1):
        return {'files': copy.deepcopy(files),
                'checksums': {name: hashlib.sha256(body.encode()).hexdigest() for name, body in files.items()},
                'version': version, 'viewNames': {}}

    def expected(self):
        target = self.target
        connection = {'id': target['connection_id']}
        connections = [connection] if target['connection_id'] == target['environment_connection_id'] else [
            {'id': value} for value in sorted((target['connection_id'], target['environment_connection_id']))]
        identity = {'target': target, 'schema_id': uid(4), 'permissions': ['QUERY_FULL_MODEL', 'UPDATE'],
                    'key_scope': 'MODEL', 'connections': connections}
        authored = self.snapshot(self.files, self.version)
        return {'authored_sha256': digest(authored), 'resolved_sha256': digest(authored),
                'base_sha256': digest(self.snapshot(self.base_files)),
                'schema_sha256': digest(self.snapshot(self.schema_files, self.schema_generation)),
                'identity_sha256': digest(identity)}

    def request(self, method, path, params=None, body=None):
        self.calls.append({'method': method, 'path': path, 'params': copy.deepcopy(params), 'body': copy.deepcopy(body)})
        target = self.target
        if path == '/api/v1/whoami':
            data = {'user': {'id': uid(99) if self.wrong_principal else target['principal_id']},
                    'rolesByModel': {target['model_id']: {'connectionId': target['connection_id'], 'permissions': ['QUERY_FULL_MODEL', 'UPDATE']}},
                    'keyScope': 'MODEL'}
        elif path == '/api/v1/models':
            model_id = params['modelId']
            kind, base = ('SHARED', uid(4)) if model_id == target['model_id'] else (
                ('BRANCH', uid(99) if self.wrong_branch else target['model_id']) if model_id == target['branch_id'] else ('SCHEMA', None))
            data = {'records': [{'id': model_id, 'modelKind': kind, 'baseModelId': base,
                                 'connectionId': target['connection_id']}],
                    'pageInfo': {'hasNextPage': False, 'nextCursor': None}}
        elif path.startswith('/api/v1/connections/'):
            data = {'connection': {'id': path.rsplit('/', 1)[-1]}}
        elif path.endswith('/validate'):
            if self.validation_mutation:
                self.validation_mutation(self)
            return native.Response(self.validation_status, self.validation_body)
        elif path.endswith('/yaml') and method == 'GET':
            if path == '/api/v1/models/' + uid(4) + '/yaml':
                data = self.snapshot(self.schema_files, self.schema_generation)
            elif params.get('branchId') == target['branch_id']:
                data = self.snapshot(self.files, self.version)
            else:
                data = self.snapshot(self.base_files)
        elif path.endswith('/yaml') and method == 'POST':
            if self.write_error is None or self.write_commits_before_error:
                self.files[body['fileName']] = body['yaml']
                self.version += 1
            if self.write_error:
                raise self.write_error
            data = {'success': True, 'fileName': body['fileName']}
        elif path == '/api/v1/query/run':
            if self.query_error is not None:
                raise self.query_error
            if self.query_reply is not None:
                return self.query_reply
            raise AssertionError('Query response must be explicit in this fixture')
        else:
            raise AssertionError('Unexpected native endpoint')
        return native.Response(200, canonical(data))


RUNTIME = Ed25519PrivateKey is not None and omni_contract.yaml is not None and omni_contract.sqlglot is not None


@unittest.skipUnless(RUNTIME, 'Pinned optional semantic/deployment dependencies required')
class NativeIndependentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.candidate_root = self.root / 'candidate'
        self.candidate_root.mkdir()
        self.target = {'instance_url': 'https://synthetic-native.omniapp.co', 'model_id': uid(1), 'branch_id': uid(2),
                       'connection_id': uid(3), 'environment_connection_id': uid(3), 'principal_id': uid(5),
                       'environment': 'development'}
        self.remote = Remote(self.target, candidate())
        self.key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.policy = {'schema_version': 1, 'kind': 'deployment_runner_policy', 'runner_id': 'synthetic-runner',
                       'mode': 'simulation', 'allowed_actions': ['deploy_development'],
                       'destinations': {'dev': self.target}, 'state_root': str(self.root / 'private-state'),
                       'issuers': {'review-service': {'public_key': base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
                                                     'actors': ['reviewer'], 'purposes': ['deployment_approval']}},
                       'max_attestation_age_seconds': 3600, 'revoked_ids': []}
        self.policy_path = self.root / 'policy.json'
        self.save_policy()
        self.request = {'schema_version': 1, 'kind': 'omni_native_request', 'run_id': 'independent-1',
                        'operation': 'validate', 'destination_id': 'dev', 'target': copy.deepcopy(self.target),
                        'files': candidate(), 'context': context(), 'warning_policy': 'fail',
                        'expected_remote': self.remote.expected(), 'commit_message': 'Reviewed synthetic fixture'}

    def save_policy(self):
        self.policy_path.write_bytes(canonical(self.policy))
        self.policy_path.chmod(0o600)

    def approval(self, request=None, **claims):
        request = self.request if request is None else request
        now = datetime.now(timezone.utc)
        preflight = {name: True for name in ('principal_namespace_verified', 'permissions_verified', 'existing_destination_approved',
                                           'synthetic_data_only', 'isolated_destination', 'branch_exclusive')}
        preflight.update(target_sha256=digest(request['target']), audience_sha256='c' * 64,
                         access_policy_sha256='d' * 64, evidence_sha256='e' * 64,
                         evidence_reference='synthetic://independent/access')
        if request['operation'] == 'query': preflight['effective_timezone'] = request['timezone']
        payload = {'schema_version': 1, 'kind': 'deployment_attestation', 'purpose': 'deployment_approval',
                   'mode': self.policy['mode'], 'issuer': 'review-service', 'actor': 'reviewer', 'id': 'independent-approval',
                   'review_reference': 'synthetic://independent/approval',
                   'issued_at': (now - timedelta(minutes=1)).isoformat(), 'expires_at': (now + timedelta(minutes=30)).isoformat(),
                   'bindings': native.request_bindings(request, hashlib.sha256(self.policy_path.read_bytes()).hexdigest()),
                   'claims': {'preflight': preflight, **claims}}
        return self.sign(payload)

    def sign(self, payload):
        return {'payload': copy.deepcopy(payload), 'signature': base64.b64encode(self.key.sign(canonical(payload))).decode()}

    def run_native(self, approval=None, transport=None):
        return native.run(self.request, policy_path=self.policy_path, candidate_root=self.candidate_root,
                          approval=approval, transport=self.remote if transport is None else transport)

    def test_empty_issue_list_is_only_simulation_and_uses_exact_branch(self):
        receipt = self.run_native()
        self.assertEqual(receipt['status'], 'simulated_passed', receipt)
        self.assertFalse(receipt['native_verified'])
        validation = [call for call in self.remote.calls if call['path'].endswith('/validate')]
        self.assertEqual(validation[0]['params'], {'branchId': self.target['branch_id']})
        self.assertEqual(receipt['remote_before'], receipt['remote_after'])
        self.assertFalse(any(call['method'] == 'POST' for call in self.remote.calls))

    def test_http200_error_never_passes_and_native_autofix_remains_inert(self):
        marker = 'SYNTHETIC_PHI_CANARY_DO_NOT_ECHO'
        self.remote.validation_body = canonical([{'is_warning': False, 'message': marker, 'yaml_path': marker,
                                                  'auto_fix': {'description_short': 'Delete ' + marker}}])
        receipt = self.run_native()
        self.assertEqual(receipt['status'], 'failed', receipt)
        self.assertNotIn(marker, json.dumps(receipt))
        self.assertTrue(receipt['validation']['issues'][0]['automatic_fix_ignored'])
        self.assertFalse(any(call['method'] != 'GET' for call in self.remote.calls))

    def test_warnings_require_explicit_policy(self):
        self.remote.validation_body = canonical([{'is_warning': True, 'message': 'Synthetic warning', 'yaml_path': 'fleet.view'}])
        self.assertEqual(self.run_native()['status'], 'failed')
        self.request['run_id'] = 'warning-allowed'
        self.request['warning_policy'] = 'allow'
        self.assertEqual(self.run_native()['status'], 'simulated_passed')

    def test_malformed_issue_flags_or_envelopes_never_pass(self):
        for index, body in enumerate((b'{}', b'{"errors":[]}', b'[{"message":"x","yaml_path":"x"}]',
            b'[{"is_warning":"false","message":"x","yaml_path":"x"}]',
            b'[{"is_warning":false,"is_warning":true,"message":"x","yaml_path":"x"}]', b'[] trailing', b'\xff')):
            self.request['run_id'] = 'malformed-' + str(index)
            self.remote.validation_body = body
            with self.subTest(index=index):
                self.assertNotIn(self.run_native()['status'], ('passed', 'simulated_passed'))

    def test_wrong_principal_or_branch_blocks_before_validation(self):
        for field in ('wrong_principal', 'wrong_branch'):
            self.remote = Remote(self.target, candidate())
            setattr(self.remote, field, True)
            self.request['run_id'] = field
            receipt = self.run_native()
            self.assertEqual(receipt['status'], 'blocked')
            self.assertFalse(any(call['path'].endswith('/validate') for call in self.remote.calls))

    def test_remote_extra_missing_or_modified_candidate_files_fail(self):
        for index in range(3):
            self.remote = Remote(self.target, candidate())
            if index == 0: self.remote.files['extra.topic'] = 'base_view: fleet\n'
            if index == 1: self.remote.files.pop('fleet.topic')
            if index == 2: self.remote.files['fleet.topic'] += 'label: Changed\n'
            self.request['run_id'] = 'remote-inventory-' + str(index)
            self.request['expected_remote'] = self.remote.expected()
            self.assertEqual(self.run_native()['status'], 'blocked')
            self.assertFalse(any(call['path'].endswith('/validate') for call in self.remote.calls))

    def test_dependency_or_remote_change_during_validation_invalidates_result(self):
        for index, mutate in enumerate((lambda remote: setattr(remote, 'schema_generation', 2),
                                       lambda remote: remote.files.update({'fleet.topic': 'base_view: fleet\n'}))):
            self.remote = Remote(self.target, candidate())
            self.remote.validation_mutation = mutate
            self.request['run_id'] = 'race-' + str(index)
            self.request['expected_remote'] = self.remote.expected()
            receipt = self.run_native()
            self.assertEqual(receipt['status'], 'blocked')
            self.assertFalse(receipt['native_verified'])

    def test_mutation_requires_signed_exact_approval_before_any_transport(self):
        self.request['operation'] = 'update_and_validate'
        for envelope in (None, {'human_approved': True}):
            self.remote.calls.clear()
            self.assertEqual(self.run_native(envelope)['status'], 'blocked')
            self.assertEqual(self.remote.calls, [])
        approval = self.approval()
        self.request['files']['fleet.topic'] += 'label: Reviewed later\n'
        self.assertEqual(self.run_native(approval)['status'], 'blocked')
        self.assertEqual(self.remote.calls, [])

    def test_expired_or_incomplete_access_preflight_blocks_write(self):
        self.request['operation'] = 'update_and_validate'
        for mode in ('expired', 'audience', 'synthetic', 'exclusive'):
            envelope = self.approval()
            payload = envelope['payload']
            if mode == 'expired': payload['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            if mode == 'audience': payload['claims']['preflight'].pop('audience_sha256')
            if mode == 'synthetic': payload['claims']['preflight']['synthetic_data_only'] = False
            if mode == 'exclusive': payload['claims']['preflight']['branch_exclusive'] = False
            self.remote.calls.clear()
            self.assertEqual(self.run_native(self.sign(payload))['status'], 'blocked')
            self.assertEqual(self.remote.calls, [])

    def test_ambiguous_write_committed_remotely_is_not_duplicated_on_resume(self):
        self.request['operation'] = 'update_and_validate'
        self.request['files']['fleet.topic'] += 'label: Reviewed candidate\n'
        approval = self.approval()
        self.remote.write_error = native.TransportError('transport.timeout', uncertain=True)
        self.remote.write_commits_before_error = True
        first = self.run_native(approval)
        self.assertEqual(first['status'], 'pending', first)
        self.assertEqual(len([call for call in self.remote.calls if call['method'] == 'POST']), 1)
        self.remote.write_error = None
        second = self.run_native(approval)
        self.assertEqual(second['status'], 'simulated_passed', second)
        self.assertEqual(len([call for call in self.remote.calls if call['method'] == 'POST']), 1)
        journal = json.loads((self.root / 'private-state' / 'independent-1.json').read_text())
        self.assertNotIn('Reviewed candidate', json.dumps(journal))

    def test_existing_file_update_uses_checksum_and_exact_branch_without_deletion(self):
        self.request['operation'] = 'update_and_validate'
        self.request['files']['fleet.topic'] += 'label: Approved change\n'
        self.assertEqual(self.run_native(self.approval())['status'], 'simulated_passed')
        writes = [call for call in self.remote.calls if call['method'] == 'POST']
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['body']['branchId'], self.target['branch_id'])
        self.assertIn('previousChecksum', writes[0]['body'])
        self.assertEqual(writes[0]['body']['fullyResolved'], False)

    def query_request(self, mode='plan'):
        self.request.update(operation='query', query_mode=mode, timezone='UTC',
                            query={'modelId': self.target['model_id'], 'table': 'fleet',
                                   'fields': ['fleet.journeys'], 'limit': 10})

    def test_query_plan_is_separate_exact_scope_and_sql_is_never_persisted(self):
        self.query_request()
        marker = 'SYNTHETIC_PRIVATE_SQL_LITERAL'
        stream = [{'jobs_submitted': {uid(8): {}}},
                  {'job_id': uid(8), 'status': 'COMPLETE', 'summary': {'sql': 'SELECT ' + marker}},
                  {'remaining_job_ids': [], 'timed_out': 'false'}]
        self.remote.query_reply = native.Response(200, b'\n'.join(canonical(row) for row in stream), 'text/ndjson')
        receipt = self.run_native(self.approval())
        self.assertEqual(receipt['status'], 'simulated_passed', receipt)
        self.assertEqual(receipt['operation'], 'query')
        self.assertNotIn('validation', receipt)
        self.assertNotIn(marker, json.dumps(receipt))
        query_call = next(call for call in self.remote.calls if call['path'] == '/api/v1/query/run')
        self.assertEqual(query_call['body']['branchId'], self.target['branch_id'])
        self.assertEqual(query_call['body']['environmentConnectionId'], self.target['environment_connection_id'])
        self.assertIs(query_call['body']['planOnly'], True)
        self.assertEqual(query_call['body']['cache'], 'SkipCache')
        self.assertNotIn(marker, (self.root / 'private-state' / 'independent-1.json').read_text())

    def test_query_rows_remain_in_memory_only_receipt_records_permitted_count(self):
        self.query_request('execute')
        marker = 'SYNTHETIC_PRIVATE_QUERY_VALUE'
        self.remote.query_reply = native.Response(200, canonical([{'synthetic_result': marker}]))
        receipt = self.run_native(self.approval())
        self.assertEqual(receipt['status'], 'simulated_passed', receipt)
        self.assertEqual(receipt['query']['rows'], 1)
        self.assertNotIn(marker, json.dumps(receipt))
        self.assertNotIn(marker, (self.root / 'private-state' / 'independent-1.json').read_text())

    def test_incomplete_or_failed_query_stream_never_proves_completion(self):
        self.query_request()
        streams = [
            [{'jobs_submitted': {uid(8): {}}}, {'remaining_job_ids': [], 'timed_out': 'false'}],
            [{'jobs_submitted': {uid(8): {}}}, {'job_id': uid(8), 'status': 'FAILED', 'message': 'SYNTHETIC_PRIVATE'},
             {'remaining_job_ids': [], 'timed_out': 'false'}],
            [{'jobs_submitted': {uid(8): {}}}, {'job_id': uid(8), 'status': 'COMPLETE', 'summary': {'sql': 'SELECT 1'}},
             {'remaining_job_ids': [], 'timed_out': False}],
        ]
        for index, stream in enumerate(streams):
            self.request['run_id'] = 'incomplete-query-' + str(index)
            self.remote.query_reply = native.Response(200, b'\n'.join(canonical(row) for row in stream), 'text/ndjson')
            receipt = self.run_native(self.approval())
            self.assertNotIn(receipt['status'], ('passed', 'simulated_passed'))
            self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(receipt))

    def test_ambiguous_query_cannot_be_resubmitted_automatically(self):
        self.query_request()
        approval = self.approval()
        self.remote.query_error = native.TransportError('transport.timeout', uncertain=True)
        self.assertEqual(self.run_native(approval)['status'], 'pending')
        self.remote.query_error = None
        self.remote.query_reply = native.Response(200, b'[]')
        self.assertEqual(self.run_native(approval)['status'], 'blocked')
        self.assertEqual(len([call for call in self.remote.calls if call['path'] == '/api/v1/query/run']), 1)

    def test_completed_query_cannot_be_reissued_as_fresh_evidence(self):
        self.query_request('execute')
        self.remote.query_reply = native.Response(200, canonical([{'count': 1}]))
        approval = self.approval()
        self.assertEqual(self.run_native(approval)['status'], 'simulated_passed')
        repeat = self.run_native(self.approval())
        self.assertEqual(repeat['status'], 'blocked', repeat)
        self.assertEqual(repeat['code'], 'query.already_completed_use_original_receipt')
        self.assertEqual(len([call for call in self.remote.calls if call['path'] == '/api/v1/query/run']), 1)

    def test_direct_native_route_blocks_sensitive_candidate_and_query_literals(self):
        self.request['operation'] = 'update_and_validate'
        self.request['files']['fleet.topic'] += 'label: SYNTHETIC_PII_CANARY\n'
        self.assertEqual(self.run_native(self.approval())['status'], 'blocked')
        self.assertEqual(self.remote.calls, [])
        self.request['files'] = candidate()
        self.query_request('execute')
        self.request['query']['filters'] = {'fleet.id': {'is': 'SYNTHETIC_PHI_CANARY'}}
        self.assertEqual(self.run_native(self.approval())['status'], 'blocked')
        self.assertEqual(self.remote.calls, [])

    def test_live_policy_with_injected_transport_cannot_be_native_evidence(self):
        self.policy['mode'] = 'live'
        self.save_policy()
        receipt = self.run_native()
        self.assertEqual(receipt['status'], 'simulated_passed', receipt)
        self.assertEqual(receipt['execution_mode'], 'simulation')
        self.assertFalse(receipt['native_verified'])

    def test_missing_live_credentials_returns_pending_without_network(self):
        self.policy['mode'] = 'live'
        self.save_policy()
        with patch.dict(os.environ, {}, clear=True), patch.object(native.HTTPSOmniTransport, 'request', side_effect=AssertionError('No network')):
            receipt = native.run(self.request, policy_path=self.policy_path, candidate_root=self.candidate_root)
        self.assertEqual(receipt['status'], 'pending', receipt)
        self.assertEqual(receipt['code'], 'credentials.unavailable')

    def test_policy_inside_candidate_or_writable_by_others_is_blocked(self):
        original = self.policy_path
        inside = self.candidate_root / 'policy.json'
        inside.write_bytes(original.read_bytes()); inside.chmod(0o600)
        self.policy_path = inside
        self.assertEqual(self.run_native()['status'], 'blocked')
        self.policy_path = original
        original.chmod(0o666)
        self.assertEqual(self.run_native()['status'], 'blocked')
        self.assertEqual(self.remote.calls, [])


class NativeTransportIndependentTests(unittest.TestCase):
    def test_tls_transport_requires_canonical_https_host_and_blocks_redirects(self):
        for invalid in ('http://synthetic-native.omniapp.co', 'https://synthetic-native.omniapp.co/other',
                        'https://synthetic-native.omniapp.co@untrusted.invalid', 'https://untrusted.invalid',
                        'https://synthetic-native.omniapp.co:444'):
            with self.subTest(url=invalid), self.assertRaises(ValueError):
                native.HTTPSOmniTransport(invalid)
        self.assertIsNone(native._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://untrusted.invalid'))

    def test_json_parser_never_echoes_raw_provider_values(self):
        marker = 'SYNTHETIC_PII_CANARY_PRIVATE'
        with self.assertRaises(ValueError) as raised:
            native._json(('{' + marker).encode())
        self.assertNotIn(marker, str(raised.exception))


if __name__ == '__main__':
    unittest.main()
