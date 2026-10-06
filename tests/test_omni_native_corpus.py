"""Execute the frozen authorization no-ops without credentials or network access.

Only response-fixture helpers are reused; no TestCase is inherited or imported.
The corpus remains immutable, and every negative starts with supported SQL and
an otherwise valid request so a parser failure cannot impersonate authorization.
"""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_contract
import omni_inventory
import omni_native
import test_omni_native_independent as fixtures

CORPUS = Path(__file__).parent / 'fixtures/omni_modeler'
SCENARIOS = json.loads((CORPUS / 'authorization_scenarios.json').read_text())
CASE_IDS = {
    'local_preview_without_deploy_authority', 'update_without_approval',
    'query_without_approval', 'synthetic_claim_is_not_authorization',
    'production_target_rejected', 'stale_candidate_attestation',
    'wrong_destination_policy', 'static_success_never_authorizes',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


@unittest.skipUnless(fixtures.RUNTIME, 'Pinned optional semantic/deployment dependencies required')
class NativeAuthorizationCorpusTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual({case['id'] for case in SCENARIOS['cases']}, CASE_IDS)
        self.assertEqual(len(SCENARIOS['cases']), len(CASE_IDS))
        freeze = json.loads((CORPUS / 'FROZEN_SHA256.json').read_text())['files']
        self.corpus_bytes = {}
        for name in ('authorization_scenarios.json', 'context.json',
                     'source/auth_noop_orders.view', 'source/auth_noop_orders.topic'):
            self.corpus_bytes[name] = (CORPUS / name).read_bytes()
            self.assertEqual(sha(self.corpus_bytes[name]), freeze[name])
        self.addCleanup(self.assert_corpus_unchanged)

        # Abort both the adapter's real transport and lower-level sockets. The
        # recording fixture is the only allowed transport for this entire suite.
        self.network_guards = []
        for entry in ('omni_native.HTTPSOmniTransport', 'socket.create_connection',
                      'socket.socket.connect', 'socket.socket.connect_ex', 'socket.getaddrinfo'):
            guard = patch(entry, side_effect=AssertionError('Network forbidden'))
            self.network_guards.append(guard.start())
            self.addCleanup(guard.stop)

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.candidate_root = self.root / 'candidate'
        self.candidate_root.mkdir(mode=0o700)
        self.files = {name: self.corpus_bytes['source/auth_noop_' + name].decode()
                      for name in ('orders.view', 'orders.topic')}
        self.context = json.loads(self.corpus_bytes['context.json'])
        self.target = copy.deepcopy(SCENARIOS['target'])
        self.remote = fixtures.Remote(self.target, self.files)
        self.remote.schema_files = {'orders.view': 'table_name: ORDERS\n'}
        self.before = self.remote_state()
        # Only this temporary issuer exists; no operational key is read or saved.
        self.key = fixtures.Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(fixtures.Encoding.Raw, fixtures.PublicFormat.Raw)
        self.policy = {
            'schema_version': 1, 'kind': 'deployment_runner_policy', 'runner_id': 'corpus-runner',
            'mode': 'simulation', 'allowed_actions': ['deploy_development'],
            'destinations': {'dev': self.target}, 'state_root': str(self.root / 'private-state'),
            'issuers': {'test-only': {'public_key': base64.b64encode(public).decode(),
                        'actors': ['test-reviewer'], 'purposes': ['deployment_approval']}},
            'max_attestation_age_seconds': 3600, 'revoked_ids': [],
        }
        self.policy_path = self.root / 'policy.json'
        self.policy_path.write_bytes(fixtures.canonical(self.policy))
        self.policy_path.chmod(0o600)
        self.request = {
            'schema_version': 1, 'kind': 'omni_native_request', 'run_id': 'frozen-noop',
            'operation': 'validate', 'destination_id': 'dev', 'target': copy.deepcopy(self.target),
            'files': copy.deepcopy(self.files), 'context': copy.deepcopy(self.context),
            'warning_policy': 'fail', 'expected_remote': self.remote.expected(),
            'commit_message': 'Frozen synthetic authorization test',
        }
        static = omni_contract.check_model(self.files, self.context)
        self.assertEqual(static['status'], 'passed', static)
        omni_native.validate_request(self.request)

    def assert_corpus_unchanged(self):
        for name, original in self.corpus_bytes.items():
            self.assertEqual((CORPUS / name).read_bytes(), original, name)

    def remote_state(self):
        return fixtures.canonical({'files': self.remote.files, 'base': self.remote.base_files,
                                   'schema': self.remote.schema_files, 'version': self.remote.version,
                                   'schema_generation': self.remote.schema_generation})

    def approval(self):
        now = datetime.now(timezone.utc)
        preflight = {name: True for name in (
            'principal_namespace_verified', 'permissions_verified', 'existing_destination_approved',
            'synthetic_data_only', 'isolated_destination', 'branch_exclusive')}
        preflight.update(target_sha256=fixtures.digest(self.request['target']),
                         audience_sha256='c' * 64, access_policy_sha256='d' * 64,
                         evidence_sha256='e' * 64, evidence_reference='synthetic://corpus/preflight')
        payload = {
            'schema_version': 1, 'kind': 'deployment_attestation', 'purpose': 'deployment_approval',
            'mode': 'simulation', 'issuer': 'test-only', 'actor': 'test-reviewer', 'id': 'test-approval',
            'review_reference': 'synthetic://corpus/review',
            'issued_at': (now - timedelta(minutes=1)).isoformat(),
            'expires_at': (now + timedelta(minutes=10)).isoformat(),
            'bindings': omni_native.request_bindings(self.request, sha(self.policy_path.read_bytes())),
            'claims': {'preflight': preflight},
        }
        envelope = {'payload': payload, 'signature': base64.b64encode(self.key.sign(fixtures.canonical(payload))).decode()}
        # Prove the original attestation is valid before changing candidate bytes.
        omni_native._approval(self.request, self.policy, sha(self.policy_path.read_bytes()), envelope)
        return envelope

    def run_native(self, approval=None):
        return omni_native.run(self.request, policy_path=self.policy_path,
                               candidate_root=self.candidate_root, approval=approval, transport=self.remote)

    def exercise(self, case):
        operation = case['operation']
        if operation == 'local_preview':
            proposal = omni_inventory.propose_patch(self.files, {}, [{
                'path': 'orders.view', 'pointer': '/label', 'value': 'Reviewed synthetic orders',
                'expected_sha256': sha(self.files['orders.view'].encode()),
            }])
            self.assertFalse(proposal['applied'])
            self.assertFalse(proposal['deployment_authorized'])
            observed = {'candidate_state': proposal['status'], 'native_verified': proposal['native_verified']}
        elif operation == 'local_static_check':
            check = omni_contract.check_model(self.files, self.context)
            self.assertIsNot(check.get('deployment_authorized'), True)
            self.request['operation'] = 'update_and_validate'
            receipt = self.run_native()
            self.assertEqual(receipt['code'], 'authorization.attestation_invalid', receipt)
            # Static success still cannot get an unsigned write past the adapter.
            observed = {'static_status': check['status'], 'native_verified': check['native_verified'],
                        'security_verified': check['security_verified'],
                        'deployment_authorized': receipt.get('deployment_authorized', False)}
        else:
            self.request['operation'] = operation
            if operation == 'query':
                self.request.update(query_mode=case['query_mode'], timezone='UTC',
                    query=dict(copy.deepcopy(case['query']), modelId=self.target['model_id']))
            # Reach the intended authorization/target gate, never unrelated SQL failure.
            omni_native.validate_request(self.request)
            approval = copy.deepcopy(case.get('approval'))
            if case['id'] == 'stale_candidate_attestation':
                approval = self.approval()
                for path, addition in case['candidate_append'].items():
                    self.request['files'][path] += addition
                omni_native.validate_request(self.request)
            if 'target_patch' in case:
                self.request['target'].update(case['target_patch'])
            if 'destination_id' in case:
                self.request['destination_id'] = case['destination_id']
            observed = self.run_native(approval)
            expected_code = ('target.development_only' if 'target_patch' in case else
                             'runner.destination_not_provisioned' if 'destination_id' in case else
                             'authorization.attestation_invalid')
            self.assertEqual(observed['code'], expected_code, observed)
            self.assertEqual(observed['execution_mode'], 'simulation')

        observed['transport_calls'] = len(self.remote.calls)
        observed['remote_mutations'] = sum(call['method'] != 'GET' for call in self.remote.calls)
        for key, value in case['expected'].items():
            self.assertEqual(observed[key], value, (case['id'], key, observed))
        self.assertEqual(self.remote_state(), self.before, 'Remote file bytes or versions changed')
        for guard in self.network_guards:
            guard.assert_not_called()


def scenario_test(case):
    def test(self):
        self.exercise(copy.deepcopy(case))
    return test


# Eight independently reported tests are generated from the frozen scenario list.
for scenario in SCENARIOS['cases']:
    setattr(NativeAuthorizationCorpusTests, 'test_' + scenario['id'], scenario_test(scenario))


if __name__ == '__main__':
    unittest.main()
