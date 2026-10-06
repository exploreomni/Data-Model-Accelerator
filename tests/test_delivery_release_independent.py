"""Independent signed-release attacks; synthetic keys, no remote execution."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import delivery_release as release
from ae_common import hash_json
from privacy_contract import default_policy
import security_contract as security
from test_security_contract_independent import access_fixture, renew, observations_for

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except ImportError:
    Ed25519PrivateKey = None

NOW = datetime(2031, 6, 4, 12, tzinfo=timezone.utc)
EXPECTED_CHECKS = {
    'source_coverage': ['independent_inventory'], 'classification': ['classification_reviewed'],
    'input_egress': ['boundary_verified', 'input_projection_scanned'],
    'yaml': ['syntax_valid'], 'omni_static': ['contract_valid'], 'native_model': ['native_validated'],
    'warehouse_execution': ['executed'], 'omni_queries': ['executed', 'modeled_queries'],
    'data_parity': ['independent_baseline', 'full_population_compared', 'negative_controls'],
    'dashboard_created': ['draft_readback'], 'dashboard_behavior': ['rendered_interactions', 'all_selected_tiles'],
    'access': ['readback_verified', 'positive_personas', 'negative_personas', 'all_paths',
               'qualified_collector', 'current_state_observed'],
    'ai_context': ['native_answers_observed', 'privacy_checked', 'approved_definitions_only'],
    'output_disclosure': ['classification_reviewed', 'audience_authorized', 'exact_bytes_scanned'],
    'business_acceptance': ['meaning_approved']}
NATIVE = {'native_model', 'warehouse_execution', 'omni_queries', 'dashboard_created',
          'dashboard_behavior', 'access', 'ai_context'}


def sign(key, payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    return {'payload': copy.deepcopy(payload), 'signature': base64.b64encode(key.sign(encoded)).decode()}


@unittest.skipUnless(Ed25519PrivateKey, 'Optional deployment cryptography dependency is unavailable')
class IndependentDeliveryReleaseTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.from_private_bytes(bytes(range(20, 52)))
        public = base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        self.policy = {'schema_version': 1, 'kind': 'deployment_runner_policy', 'mode': 'live',
            'issuers': {'evidence-service': {'public_key': public, 'actors': ['qualified-observer'],
                'purposes': ['delivery_evidence'], 'evidence_lanes': sorted(EXPECTED_CHECKS)}},
            'max_attestation_age_seconds': 3600, 'revoked_ids': []}
        self.plan = {'migration_scope': 'full_dashboard', 'review_target': {'semantic_target': 'omni'},
            'target': {'warehouse': 'snowflake', 'framework': 'dbt', 'environment': 'development',
                       'namespace': {'database': 'ANALYTICS'}},
            'policy_sha256': hash_json(self.policy), 'action': 'promote',
            'bindings': {'source_bindings': {'source': 'a' * 64, 'catalogue': 'b' * 64},
                         'handoff_manifest_sha256': 'c' * 64}}
        disclosure = default_policy()
        disclosure.update(policy_id='fixture-policy', review_status='approved', review_reference='synthetic-review',
                          evidence=[{'reference': 'synthetic-policy', 'sha256': 'd' * 64}])
        self.descriptor = {'disclosure_policy': disclosure, 'access': None, 'evidence': []}
        contract, current, candidate, readback, observations = access_fixture()
        outer = release.evidence_bindings(self.plan, self.descriptor)
        for obj in (contract, current, candidate, readback):
            obj['bindings'].update({k: v for k, v in outer.items() if k != 'policy'})
        renew(contract, current, candidate)
        self.descriptor['access'] = {'contract': contract, 'current': current, 'candidate': candidate,
            'readback': readback, 'observations': observations_for(contract, candidate)}
        self.renew_evidence()

    def renew_evidence(self, lanes=None):
        bindings = release.evidence_bindings(self.plan, self.descriptor)
        entries = []
        for lane in sorted(EXPECTED_CHECKS if lanes is None else lanes):
            execution = 'native' if lane in NATIVE else 'human' if lane == 'business_acceptance' else 'local'
            refs = [{'reference': 'synthetic-fixture-only', 'sha256': hash_json(['original', lane])}]
            if lane == 'access':
                refs = [{'reference': 'synthetic-access-only',
                         'sha256': hash_json(security.evaluate_access(**self.descriptor['access']))}]
            result = {'schema_version': 1, 'kind': 'delivery_lane_result', 'lane': lane,
                'status': 'passed', 'execution': execution, 'synthetic': False,
                'checks': {k: True for k in EXPECTED_CHECKS[lane]}, 'references': refs}
            observation = {'lane': lane, 'status': 'passed', 'bindings': copy.deepcopy(bindings),
                'observed_at': (NOW - timedelta(minutes=5)).isoformat(),
                'expires_at': (NOW + timedelta(minutes=20)).isoformat(), 'result_sha256': hash_json(result),
                'provenance': {'native': 'native_observation', 'human': 'human_decision', 'local': 'local_check'}[execution]}
            entries.append({'observation': observation, 'result': result, 'attestation': self.attestation(observation)})
        self.descriptor['evidence'] = entries
        self.rebind()

    def attestation(self, observation, **changes):
        payload = {'schema_version': 1, 'kind': 'deployment_attestation', 'purpose': 'delivery_evidence',
            'issuer': 'evidence-service', 'actor': 'qualified-observer', 'mode': self.policy['mode'],
            'id': 'fixture-' + observation['lane'], 'review_reference': 'synthetic-runner-review',
            'issued_at': (NOW - timedelta(minutes=1)).isoformat(),
            'expires_at': (NOW + timedelta(minutes=10)).isoformat(),
            'bindings': {'observation_sha256': hash_json(observation)}}
        payload.update(changes)
        return sign(self.key, payload)

    def rebind(self): self.plan['delivery_assurance'] = release.bind_context(self.plan, self.descriptor)

    def lane(self, lane): return next(x for x in self.descriptor['evidence'] if x['observation']['lane'] == lane)

    def resign_result(self, entry):
        entry['observation']['result_sha256'] = hash_json(entry['result'])
        entry['attestation'] = self.attestation(entry['observation'])
        self.rebind()

    def require(self, **kwargs): return release.require_release(self.plan, self.policy, now=NOW, **kwargs)

    def test_complete_signed_protocol_evidence_does_not_itself_authorize_deployment(self):
        report = self.require()
        self.assertTrue(report['acceptance_ready'])
        self.assertTrue(report['authority_authenticated'])
        self.assertFalse(report['deployment_authorized'])
        self.assertEqual(len([x for x in report['checks'] if x['required']]), 15)

    def test_unsigned_local_reports_and_edited_signatures_cannot_pass(self):
        for attack in ('absent', 'claim', 'signature'):
            self.setUp(); entry = self.lane('classification')
            if attack == 'absent': entry.pop('attestation')
            elif attack == 'claim': entry['attestation'] = {'approved': True, 'native_verified': True}
            else: entry['attestation']['payload']['review_reference'] = 'forged-review'
            self.rebind()
            with self.subTest(attack=attack), self.assertRaises(ValueError): self.require()

    def test_every_binding_is_exact_even_with_valid_signature(self):
        for binding in ('source', 'catalogue', 'candidate', 'target', 'policy', 'scope'):
            self.setUp(); entry = self.lane('output_disclosure')
            entry['observation']['bindings'][binding] = 'f' * 64
            entry['attestation'] = self.attestation(entry['observation']); self.rebind()
            with self.subTest(binding=binding), self.assertRaises(ValueError): self.require()

    def test_lane_issuer_purpose_actor_and_mode_boundaries(self):
        for field, value in [('purpose', 'deployment_approval'), ('actor', 'other'),
                             ('issuer', 'other'), ('mode', 'simulation')]:
            self.setUp(); entry = self.lane('access')
            entry['attestation'] = self.attestation(entry['observation'], **{field: value}); self.rebind()
            with self.subTest(field=field), self.assertRaises(ValueError): self.require()
        self.setUp(); self.policy['issuers']['evidence-service']['evidence_lanes'].remove('access')
        self.plan['policy_sha256'] = hash_json(self.policy); self.renew_evidence()
        with self.assertRaisesRegex(ValueError, 'lane'): self.require()
        self.setUp()
        with self.assertRaisesRegex(ValueError, 'independent'):
            self.require(excluded_issuers={'evidence-service'})

    def test_expired_revoked_future_and_observation_window_fail_closed(self):
        for change in ({'expires_at': NOW.isoformat()}, {'issued_at': (NOW + timedelta(seconds=1)).isoformat()},
                       {'issued_at': (NOW - timedelta(minutes=6)).isoformat()},
                       {'expires_at': (NOW + timedelta(minutes=21)).isoformat()}):
            self.setUp(); entry = self.lane('source_coverage')
            entry['attestation'] = self.attestation(entry['observation'], **change); self.rebind()
            with self.subTest(change=list(change)), self.assertRaises(ValueError): self.require()
        self.setUp(); self.policy['revoked_ids'] = ['fixture-access']
        self.plan['policy_sha256'] = hash_json(self.policy); self.renew_evidence()
        with self.assertRaisesRegex(ValueError, 'revoked'): self.require()

    def test_plan_only_queries_and_synthetic_results_cannot_be_qualified(self):
        entry = self.lane('omni_queries'); entry['result']['checks']['executed'] = False
        self.resign_result(entry)
        with self.assertRaises(ValueError): self.require()
        self.setUp(); entry = self.lane('native_model'); entry['result']['synthetic'] = True
        self.resign_result(entry)
        with self.assertRaisesRegex(ValueError, 'Synthetic'): self.require()
        self.setUp(); entry = self.lane('omni_queries'); entry['result']['execution'] = 'local'
        self.resign_result(entry)
        with self.assertRaises(ValueError): self.require()

    def test_ai_context_requires_native_observation_and_frozen_definitions(self):
        for field in ('native_answers_observed', 'privacy_checked', 'approved_definitions_only'):
            self.setUp(); entry = self.lane('ai_context'); entry['result']['checks'][field] = False
            self.resign_result(entry)
            with self.subTest(field=field), self.assertRaises(ValueError): self.require()

    def test_missing_duplicate_or_not_applicable_full_scope_lane_blocks_promotion(self):
        self.renew_evidence(set(EXPECTED_CHECKS) - {'dashboard_behavior'})
        with self.assertRaises(ValueError): self.require()
        self.setUp(); self.descriptor['evidence'].pop()
        self.descriptor['evidence'].append(copy.deepcopy(self.lane('classification'))); self.rebind()
        with self.assertRaisesRegex(ValueError, 'Duplicate'): self.require()
        self.setUp(); entry = self.lane('dashboard_behavior')
        entry['observation']['status'] = entry['result']['status'] = 'not_applicable'; self.resign_result(entry)
        with self.assertRaises(ValueError): self.require()

    def test_pr_and_development_have_separate_pre_exposure_gates(self):
        self.plan['action'] = 'publish_pr'; self.renew_evidence({'classification', 'input_egress', 'output_disclosure'})
        self.assertFalse(self.require()['acceptance_ready'])
        self.plan['action'] = 'deploy_development'
        with self.assertRaises(ValueError): self.require()
        self.renew_evidence({'classification', 'input_egress', 'output_disclosure', 'access'})
        self.assertFalse(self.require()['acceptance_ready'])
        self.plan['action'] = 'promote'
        with self.assertRaises(ValueError): self.require()

    def test_access_lane_requires_exact_current_comparator_result(self):
        entry = self.lane('access'); entry['result']['references'][0]['sha256'] = '0' * 64
        self.resign_result(entry)
        with self.assertRaisesRegex(ValueError, 'exact'): self.require()
        self.setUp(); self.descriptor['access']['observations']['cases'].pop('case-0')
        self.renew_evidence()
        with self.assertRaisesRegex(ValueError, 'Access'): self.require()

    def test_access_requires_qualified_collection_and_current_native_state(self):
        for field in ('qualified_collector', 'current_state_observed'):
            self.setUp(); entry = self.lane('access'); entry['result']['checks'][field] = False
            self.resign_result(entry)
            with self.subTest(field=field), self.assertRaises(ValueError): self.require()

    def test_disclosure_access_or_runner_changes_invalidate_old_evidence(self):
        self.descriptor['disclosure_policy']['policy_id'] = 'changed-policy'; self.rebind()
        with self.assertRaisesRegex(ValueError, 'Stale'): self.require()
        self.setUp(); self.descriptor['access']['observations']['cases'].pop('case-0'); self.rebind()
        with self.assertRaisesRegex(ValueError, 'Stale'): self.require()
        self.setUp(); self.policy['max_attestation_age_seconds'] = 1800
        with self.assertRaisesRegex(ValueError, 'policy changed'): self.require()

    def test_false_boolean_numeric_checks_and_unreferenced_result_are_rejected(self):
        for checks in ({'syntax_valid': 1}, {'syntax_valid': False}, {}):
            self.setUp(); entry = self.lane('yaml'); entry['result']['checks'] = checks; self.resign_result(entry)
            with self.subTest(checks=checks), self.assertRaises(ValueError): self.require()
        self.setUp(); entry = self.lane('yaml'); entry['result']['references'] = []; self.resign_result(entry)
        with self.assertRaises(ValueError): self.require()

    def test_simulation_and_legacy_cannot_claim_live_qualification(self):
        self.policy['mode'] = 'simulation'; self.plan['policy_sha256'] = hash_json(self.policy); self.renew_evidence()
        report = self.require()
        self.assertFalse(report['acceptance_ready'])
        self.assertIn('Simulation', report['qualification'])
        self.plan['migration_scope'] = None; self.plan['delivery_assurance'] = None
        self.assertFalse(self.require()['acceptance_ready'])
        self.policy['mode'] = 'live'
        with self.assertRaises(ValueError): self.require()

    def test_sensitive_provider_values_are_rejected_without_echo(self):
        entry = self.lane('access'); entry['result']['references'][0]['reference'] = 'fixture.person@example.com'
        entry['observation']['result_sha256'] = hash_json(entry['result'])
        entry['attestation'] = self.attestation(entry['observation'])
        with self.assertRaises(ValueError) as error: self.rebind()
        self.assertNotIn('fixture.person', str(error.exception))

    def test_rebound_target_cannot_qualify_different_access_environment_or_database(self):
        for field, value in [('environment', 'production'), ('database', 'OTHER_DB')]:
            self.setUp(); access = self.descriptor['access']
            for name in ('contract', 'current', 'candidate', 'readback'):
                destination = access[name]['destination']
                if field == 'environment': destination['environment'] = value
                else: destination['identity']['database'] = value
            renew(access['contract'], access['current'], access['candidate'])
            access['observations'] = observations_for(access['contract'], access['candidate'])
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.renew_evidence(); self.require()


if __name__ == '__main__': unittest.main()
