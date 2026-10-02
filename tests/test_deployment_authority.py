"""External approval verification tests; all signing keys are synthetic fixtures."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import deployment_authority as authority

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except ImportError:
    Ed25519PrivateKey = None

NOW = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)
BINDINGS = {'plan_sha256': 'a' * 64, 'action': 'deploy_development', 'target_sha256': 'b' * 64}


def signed_bytes(payload):
    # Independent implementation of the documented canonical JSON envelope.
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


@unittest.skipUnless(Ed25519PrivateKey, 'Optional deployment cryptography dependency is unavailable')
class DeploymentAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.other_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
        public = base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        self.policy = {
            'schema_version': 1, 'kind': 'deployment_runner_policy', 'runner_id': 'synthetic-runner',
            'mode': 'simulation', 'allowed_actions': ['deploy_development'],
            'destinations': {'dev': {'fixture': True}}, 'state_root': str(self.root / 'runner-state'),
            'issuers': {'review-service': {'public_key': public, 'actors': ['reviewer'],
                                         'purposes': ['deployment_approval']}},
            'max_attestation_age_seconds': 3600, 'revoked_ids': [],
        }
        self.policy_path = self.root / 'policy.json'
        self.write_policy()
        self.payload = {
            'schema_version': 1, 'kind': 'deployment_attestation', 'purpose': 'deployment_approval',
            'mode': 'simulation', 'issuer': 'review-service', 'actor': 'reviewer', 'id': 'approval-1',
            'review_reference': 'synthetic://authenticated-review/1',
            'issued_at': (NOW - timedelta(minutes=1)).isoformat(),
            'expires_at': (NOW + timedelta(minutes=30)).isoformat(), 'bindings': copy.deepcopy(BINDINGS),
        }

    def write_policy(self):
        self.policy_path.write_text(json.dumps(self.policy))
        self.policy_path.chmod(0o600)

    def signed(self, payload=None, key=None):
        payload = copy.deepcopy(self.payload if payload is None else payload)
        signature = (key or self.key).sign(signed_bytes(payload))
        return {'payload': payload, 'signature': base64.b64encode(signature).decode()}

    def verify(self, envelope=None, policy=None, **kwargs):
        return authority.verify_attestation(self.signed() if envelope is None else envelope,
            self.policy if policy is None else policy, purpose='deployment_approval', bindings=BINDINGS,
            now=NOW, **kwargs)

    def test_external_ed25519_signature_and_exact_bindings_pass(self):
        policy, digest = authority.load_policy(self.policy_path)
        self.assertEqual(len(digest), 64)
        self.assertEqual(self.verify(policy=policy), self.payload)

    def test_publication_registry_accepts_only_exact_configured_destinations(self):
        identity = {'repository': 'example/models', 'base': 'main', 'head': 'reviewed-release'}
        self.policy['publication_destinations'] = {'dev': identity}
        self.write_policy()
        self.assertEqual(authority.load_policy(self.policy_path)[0]['publication_destinations']['dev'], identity)
        for registry in ([], {'other': identity}, {'dev': dict(identity, head='release/*')},
                         {'dev': dict(identity, base='main', head='main')},
                         {'dev': dict(identity, head='branch.lock')}, {'dev': {'repository': 'example/models'}},
                         {'dev': dict(identity, allowed_heads=['*'])}):
            self.policy['publication_destinations'] = registry
            self.write_policy()
            with self.subTest(registry=registry), self.assertRaises(ValueError):
                authority.load_policy(self.policy_path)

    def test_unsigned_edited_and_wrong_key_approvals_fail(self):
        wrong = self.signed(key=self.other_key)
        edited = self.signed()
        edited['payload']['review_reference'] = 'synthetic://forged-reference'
        for envelope in ({'human_approved': True}, {'payload': self.payload}, wrong, edited):
            with self.subTest(envelope_fields=list(envelope)), self.assertRaises(ValueError):
                self.verify(envelope)

    def test_canonical_json_signature_does_not_depend_on_dict_order(self):
        envelope = self.signed()
        envelope['payload'] = dict(reversed(list(envelope['payload'].items())))
        self.assertEqual(self.verify(envelope), self.payload)

    def test_signature_encoding_and_length_fail_closed(self):
        for signature in ('%', '', base64.b64encode(b'wrong').decode(), ['not-a-string']):
            envelope = self.signed()
            envelope['signature'] = signature
            with self.subTest(signature_type=type(signature).__name__), self.assertRaises(ValueError):
                self.verify(envelope)

    def test_purpose_actor_issuer_mode_and_binding_substitutions_fail(self):
        mutations = [('purpose', 'model_signoff'), ('actor', 'unapproved-actor'),
                     ('issuer', 'request-selected-issuer'), ('mode', 'live'),
                     ('bindings', dict(BINDINGS, target_sha256='c' * 64))]
        for field, value in mutations:
            payload = dict(self.payload, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(self.signed(payload))

    def test_revoked_expired_future_and_excessive_lifetime_fail(self):
        revoked = copy.deepcopy(self.policy)
        revoked['revoked_ids'] = ['approval-1']
        with self.assertRaisesRegex(ValueError, 'revoked'):
            self.verify(policy=revoked)
        cases = [(NOW - timedelta(hours=2), NOW), (NOW + timedelta(seconds=1), NOW + timedelta(minutes=5)),
                 (NOW - timedelta(minutes=1), NOW + timedelta(hours=2)), (NOW, NOW)]
        for issued, expires in cases:
            payload = dict(self.payload, issued_at=issued.isoformat(), expires_at=expires.isoformat())
            with self.subTest(issued=issued, expires=expires), self.assertRaises(ValueError):
                self.verify(self.signed(payload))

    def test_exact_expiration_boundary_and_timezone_normalization(self):
        envelope = self.signed(dict(self.payload, expires_at=NOW.isoformat()))
        with self.assertRaises(ValueError):
            self.verify(envelope)
        equivalent = dict(self.payload, issued_at='2030-01-02T05:59:00-06:00',
                          expires_at='2030-01-02T06:30:00-06:00')
        self.assertEqual(self.verify(self.signed(equivalent)), equivalent)

    def test_timezone_missing_review_reference_and_invalid_identity_fail(self):
        for field, value in [('issued_at', '2030-01-02T11:59:00'), ('expires_at', 'not-a-time'),
                             ('review_reference', ''), ('id', '../approval')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(self.signed(dict(self.payload, **{field: value})))

    def test_untrusted_public_key_inside_envelope_does_not_establish_trust(self):
        envelope = self.signed(key=self.other_key)
        envelope['public_key'] = base64.b64encode(self.other_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        with self.assertRaises(ValueError):
            self.verify(envelope)

    def test_policy_rejects_candidate_root_symlink_and_writable_file(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            authority.load_policy(self.policy_path, excluded_roots=(self.root,))
        link = self.root / 'policy-link.json'
        link.symlink_to(self.policy_path)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            authority.load_policy(link)
        self.policy_path.chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'writable'):
            authority.load_policy(self.policy_path)

    def test_policy_rejects_state_root_inside_candidate(self):
        candidate = self.root / 'candidate'
        candidate.mkdir()
        self.policy['state_root'] = str(candidate / 'private-state')
        self.write_policy()
        with self.assertRaisesRegex(ValueError, 'outside'):
            authority.load_policy(self.policy_path, excluded_roots=(candidate,))

    def test_policy_rejects_duplicate_json_keys_and_bad_public_keys(self):
        self.policy_path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            authority.load_policy(self.policy_path)
        for key in ('not-base64', base64.b64encode(b'wrong-size').decode()):
            self.policy['issuers']['review-service']['public_key'] = key
            self.write_policy()
            with self.assertRaises(ValueError):
                authority.load_policy(self.policy_path)

    def test_boolean_schema_versions_are_not_version_one(self):
        payload = dict(self.payload, schema_version=True)
        with self.assertRaises(ValueError):
            self.verify(self.signed(payload))
        self.policy['schema_version'] = True
        self.write_policy()
        with self.assertRaises(ValueError):
            authority.load_policy(self.policy_path)

    def test_distinct_issuer_names_cannot_reuse_the_same_public_key(self):
        self.policy['issuers']['validator'] = dict(self.policy['issuers']['review-service'],
            actors=['validator'], purposes=['deployment_acceptance'])
        self.write_policy()
        with self.assertRaises(ValueError):
            authority.load_policy(self.policy_path)

    def test_noncanonical_base64_cannot_disguise_the_same_issuer_key(self):
        public = self.policy['issuers']['review-service']['public_key']
        decoded = base64.b64decode(public, validate=True)
        alternate = next(public[:-2] + char + '=' for char in
                         'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
                         if char != public[-2] and
                         base64.b64decode(public[:-2] + char + '=', validate=True) == decoded)
        self.assertNotEqual(public, alternate)
        self.policy['issuers']['validator'] = dict(self.policy['issuers']['review-service'],
            public_key=alternate, actors=['validator'], purposes=['deployment_acceptance'])
        self.write_policy()
        with self.assertRaises(ValueError):
            authority.load_policy(self.policy_path)


if __name__ == '__main__':
    unittest.main()
