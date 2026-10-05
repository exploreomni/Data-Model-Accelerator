"""External test-only signers exercise the release evidence protocol, never a tenant."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from ae_common import hash_json, _json_bytes
import delivery_assurance as assurance
import delivery_release as release
import deployment_workflow as deployment
import security_contract as security
from test_privacy_contract import approved_policy
from test_security_contract import fixture as access_fixture, seal
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except ImportError:
    Ed25519PrivateKey = None


def fixture(scope='full_dashboard', action='deploy_development', mode='live'):
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(3, 35)))
    now = datetime.now(timezone.utc)
    policy = {'mode': mode, 'max_attestation_age_seconds': 3600, 'revoked_ids': [], 'issuers': {
        'independent-validator': {'purposes': ['delivery_evidence'], 'actors': ['reviewer'],
            'evidence_lanes': sorted(assurance.LANES),
            'public_key': base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()}}}
    plan = {'migration_scope': scope, 'action': action, 'policy_sha256': hash_json(policy),
            'target': {'warehouse': 'snowflake', 'environment': 'development', 'namespace': {'database': 'DEMO'}},
            'review_target': {'semantic_target': 'omni' if scope != 'model_only' else 'none'},
            'bindings': {'handoff_manifest_sha256': 'a' * 64, 'source_bindings': {'source': 'b' * 64, 'catalogue': 'c' * 64}}}
    descriptor = {'disclosure_policy': approved_policy(), 'access': None, 'evidence': []}
    c, current, candidate, readback, observations = access_fixture()
    # Keep security policy hash independent of the enclosing contract (no self-hash).
    binding = dict(release.evidence_bindings(plan, descriptor), policy='d' * 64)
    c['bindings'] = binding
    c['migration_scope'] = scope
    keep = {'warehouse'} | (set() if scope == 'model_only' else {'omni_topic'}) | ({'omni_document'} if scope == 'full_dashboard' else set())
    for state in (current, candidate, readback):
        state['bindings'] = copy.deepcopy(binding)
        state['resources'] = [r for r in state['resources'] if r['kind'] in keep]
    ids = {r['id'] for r in candidate['resources']}
    c['cases'] = [case for case in c['cases'] if case['resource_id'] in ids]
    seal(c, current, candidate)
    observations.update(contract_sha256=hash_json(c), state_sha256=security.state_hash(candidate), bindings=binding,
        cases={case['id']: {'context': security.expected_context(c, case), 'result': copy.deepcopy(case['expected'])} for case in c['cases']})
    descriptor['access'] = dict(contract=c, current=current, candidate=candidate, readback=readback, observations=observations)
    plan['delivery_assurance'] = release.bind_context(plan, descriptor)
    return plan, policy, key, now


def add_evidence(plan, policy, key, now, lanes):
    context = plan['delivery_assurance']
    for lane in sorted(lanes):
        execution = 'native' if lane in release.NATIVE_LANES else 'human' if lane == 'business_acceptance' else 'local'
        reference_hash = hash_json(security.evaluate_access(**context['descriptor']['access'])) if lane == 'access' else 'e' * 64
        result = {'schema_version': 1, 'kind': 'delivery_lane_result', 'lane': lane, 'status': 'passed',
                  'execution': execution, 'synthetic': False, 'checks': {k: True for k in release.CHECKS[lane]},
                  'references': [{'reference': 'test-only-normalized-reference', 'sha256': reference_hash}]}
        observation = {'lane': lane, 'status': 'passed', 'bindings': context['bindings'],
            'observed_at': (now-timedelta(minutes=2)).isoformat(), 'expires_at': (now+timedelta(minutes=30)).isoformat(),
            'result_sha256': hash_json(result), 'provenance': {'native': 'native_observation', 'human': 'human_decision', 'local': 'local_check'}[execution]}
        payload = {'schema_version': 1, 'kind': 'deployment_attestation', 'purpose': 'delivery_evidence',
            'issuer': 'independent-validator', 'actor': 'reviewer', 'mode': policy['mode'], 'id': 'test-only-'+lane,
            'review_reference': 'test-only-authority', 'issued_at': (now-timedelta(minutes=1)).isoformat(),
            'expires_at': (now+timedelta(minutes=20)).isoformat(), 'bindings': release.attestation_bindings(observation)}
        envelope = {'payload': payload, 'signature': base64.b64encode(key.sign(_json_bytes(payload))).decode()}
        context['descriptor']['evidence'].append({'observation': observation, 'result': result, 'attestation': envelope})
    return plan


@unittest.skipUnless(Ed25519PrivateKey, 'Pinned deployment runtime required')
class DeliveryReleaseTests(unittest.TestCase):
    def test_development_does_not_require_post_deployment_or_business_passes(self):
        args = fixture(); add_evidence(*args, release.DEV_LANES)
        result = release.require_release(args[0], args[1], now=args[3])
        self.assertFalse(result['acceptance_ready'])
        self.assertFalse(result['deployment_authorized'])

    def test_pr_has_privacy_gate_without_requiring_native_dashboard(self):
        args = fixture(action='publish_pr'); add_evidence(*args, release.PR_LANES)
        self.assertFalse(release.require_release(args[0], args[1], now=args[3])['acceptance_ready'])

    def test_promotion_requires_every_selected_scope_lane(self):
        for scope in assurance.SCOPES:
            args = fixture(scope, 'promote'); add_evidence(*args, assurance.required_lanes(scope))
            self.assertTrue(release.require_release(args[0], args[1], now=args[3])['acceptance_ready'])
            del args[0]['delivery_assurance']['descriptor']['evidence'][0]
            with self.assertRaises(ValueError): release.require_release(args[0], args[1], now=args[3])

    def test_simulated_protocol_never_qualifies_live_acceptance(self):
        args = fixture(mode='simulation'); add_evidence(*args, assurance.required_lanes('full_dashboard'))
        self.assertFalse(release.require_release(args[0], args[1], now=args[3])['acceptance_ready'])

    def test_unsigned_local_results_cannot_pass_either(self):
        args = fixture(action='publish_pr'); add_evidence(*args, release.PR_LANES)
        args[0]['delivery_assurance']['descriptor']['evidence'][0].pop('attestation')
        with self.assertRaises(ValueError): release.require_release(args[0], args[1], now=args[3])

    def test_all_input_changes_invalidate_evidence(self):
        original = fixture(); add_evidence(*original, release.DEV_LANES)
        for mutation in ('source', 'catalogue', 'candidate', 'target', 'policy', 'scope'):
            plan, policy = copy.deepcopy(original[0]), copy.deepcopy(original[1])
            now = original[3]
            if mutation in ('source', 'catalogue'): plan['bindings']['source_bindings'][mutation] = 'f'*64
            elif mutation == 'candidate': plan['bindings']['handoff_manifest_sha256'] = 'f'*64
            elif mutation == 'target': plan['target']['namespace']['database'] = 'OTHER'
            elif mutation == 'policy': policy['revoked_ids'] = ['test-only-access']
            else: plan['migration_scope'] = 'model_only'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): release.require_release(plan, policy, now=now)

    def test_same_approver_cannot_certify_the_result(self):
        args = fixture(); add_evidence(*args, release.DEV_LANES)
        with self.assertRaisesRegex(ValueError, 'independent'): release.require_release(args[0], args[1], excluded_issuers={'independent-validator'}, now=args[3])

    def test_wrong_lane_and_expired_issuer_cannot_pass(self):
        args = fixture(); add_evidence(*args, release.DEV_LANES)
        with self.assertRaises(ValueError): release.require_release(args[0], args[1], now=args[3]+timedelta(days=2))
        args[1]['issuers']['independent-validator']['evidence_lanes'] = ['yaml']
        with self.assertRaises(ValueError): release.require_release(args[0], args[1], now=args[3])

    def test_security_readback_cannot_be_omitted_or_rebound(self):
        args = fixture(); add_evidence(*args, release.DEV_LANES)
        args[0]['delivery_assurance']['descriptor']['access']['readback'] = None
        with self.assertRaises(ValueError): release.require_release(args[0], args[1], now=args[3])

    def test_legacy_live_release_is_blocked_but_historical_simulation_readable(self):
        self.assertFalse(release.require_release({}, {'mode':'simulation'})['acceptance_ready'])
        with self.assertRaises(ValueError): release.require_release({}, {'mode':'live'})


class ExactReleaseByteTests(unittest.TestCase):
    def test_unchanged_protected_literal_is_blocked_even_with_valid_manifest_hash(self):
        with tempfile.TemporaryDirectory() as root:
            root = str(Path(root).resolve()); path = Path(root)/'model.sql'; data = b"select 'SYNTHETIC_PHI_CANARY' as note\n"; path.write_bytes(data)
            item = {'path':'model.sql', 'sha256':hashlib.sha256(data).hexdigest()}
            with self.assertRaisesRegex(ValueError, 'disclosure'): deployment._release_bytes({'artifact_root':root}, item)

    def test_changed_safe_bytes_still_fail_manifest_binding(self):
        with tempfile.TemporaryDirectory() as root:
            root = str(Path(root).resolve()); path=Path(root)/'model.sql'; path.write_text('select 2 as value\n')
            item={'path':'model.sql', 'sha256':hashlib.sha256(b'select 1 as value\n').hexdigest()}
            with self.assertRaisesRegex(ValueError,'changed'): deployment._release_bytes({'artifact_root':root},item)
