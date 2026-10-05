"""Authenticate delivery evidence inside the existing deployment coordinator.

This module verifies externally issued statements; it never signs them, runs a
warehouse query, grants access or turns imported local reports into native proof.
"""
import copy

from ae_common import hash_json, require, _json_bytes
import delivery_assurance as assurance
from deployment_authority import verify_attestation
from privacy_contract import validate_disclosure_policy
from sensitive_data import scan_bytes

PR_LANES = {'classification', 'input_egress', 'output_disclosure'}
DEV_LANES = PR_LANES | {'access'}
CHECKS = {
    'source_coverage': {'independent_inventory'},
    'classification': {'classification_reviewed'},
    'input_egress': {'boundary_verified', 'input_projection_scanned'},
    'yaml': {'syntax_valid'},
    'omni_static': {'contract_valid'},
    'native_model': {'native_validated'},
    'warehouse_execution': {'executed'},
    'omni_queries': {'executed', 'modeled_queries'},
    'data_parity': {'independent_baseline', 'full_population_compared', 'negative_controls'},
    'dashboard_created': {'draft_readback'},
    'dashboard_behavior': {'rendered_interactions', 'all_selected_tiles'},
    'access': {'qualified_collector', 'current_state_observed', 'readback_verified', 'positive_personas', 'negative_personas', 'all_paths'},
    'ai_context': {'native_answers_observed', 'privacy_checked', 'approved_definitions_only'},
    'output_disclosure': {'classification_reviewed', 'audience_authorized', 'exact_bytes_scanned'},
    'business_acceptance': {'meaning_approved'},
}
NATIVE_LANES = assurance.NATIVE | {'ai_context'}


def _safe(value):
    require(len(_json_bytes(value)) <= 8 * 1024 * 1024, 'Delivery evidence exceeds the bounded contract')
    result = scan_bytes(_json_bytes(value), 'delivery-evidence.json')
    require(result['status'] == 'clear', 'Delivery evidence disclosure scan blocked; use approved value-free summaries')


def scope_hash(plan):
    return hash_json({'migration_scope': plan.get('migration_scope'),
                      'semantic_target': plan['review_target'].get('semantic_target')})


def evidence_bindings(plan, descriptor):
    """Evidence lives outside the frozen candidate to avoid circular hashes."""
    return {'source': plan['bindings']['source_bindings']['source'],
            'catalogue': plan['bindings']['source_bindings']['catalogue'],
            'candidate': plan['bindings']['handoff_manifest_sha256'],
            'target': hash_json(plan['target']), 'scope': scope_hash(plan),
            'policy': hash_json({'runner': plan['policy_sha256'],
                                 'disclosure': descriptor['disclosure_policy'],
                                 'access': descriptor['access']})}


def bind_context(plan, descriptor):
    require(plan.get('migration_scope') in assurance.SCOPES, 'Explicit migration scope required for enhanced release')
    require(type(descriptor) is dict and set(descriptor) == {'disclosure_policy', 'access', 'evidence'},
            'Delivery assurance requires disclosure policy, access bundle and evidence')
    _safe(descriptor)
    require(not validate_disclosure_policy(descriptor['disclosure_policy'])
            and descriptor['disclosure_policy']['review_status'] == 'approved',
            'Reviewed disclosure policy required')
    require(type(descriptor['evidence']) is list and len(descriptor['evidence']) <= len(assurance.LANES),
            'Invalid delivery evidence inventory')
    bindings = evidence_bindings(plan, descriptor)
    assurance.validate_bindings(bindings)
    access = descriptor['access']
    if access is not None:
        from security_contract import validate_contract
        require(type(access) is dict and set(access) == {'contract', 'current', 'candidate', 'readback', 'observations'},
                'Exact access contract/state/readback/persona bundle required')
        validate_contract(access['contract'], access['current'], access['candidate'])
        contract = access['contract']
        require(contract['migration_scope'] == plan['migration_scope']
                and contract['warehouse'] == plan['target']['warehouse'], 'Access scope or warehouse changed')
        target = plan['target']
        expected_environment = 'development' if target['environment'] in {'dev', 'test', 'staging', 'development'} else 'production'
        require(contract['destination']['environment'] == expected_environment, 'Access environment contradicts destination')
        identity = contract['destination']['identity']
        require(all(identity.get(k) == v for k, v in target['namespace'].items()),
                'Access namespace contradicts destination')
        if 'identity' in target:
            require(identity.get('principal') == target['identity'], 'Access principal contradicts destination')
        for key in ('project', 'location', 'region', 'base_url', 'role', 'compute', 'warehouse_id',
                    'cluster_identifier', 'workgroup_name', 'physical_destination'):
            if key in target:
                require(identity.get(key) == target[key], 'Access runtime identity contradicts destination')
        require(all(contract['bindings'][key] == bindings[key] for key in assurance.BINDINGS - {'policy'}),
                'Access evidence belongs to another source, catalogue, candidate, target or scope')
    return {'schema_version': 1, 'kind': 'delivery_release_context', 'bindings': bindings,
            'descriptor': copy.deepcopy(descriptor)}


def current_context(plan):
    context = plan.get('delivery_assurance')
    require(type(context) is dict and set(context) == {'schema_version', 'kind', 'bindings', 'descriptor'}
            and type(context['schema_version']) is int and context['schema_version'] == 1
            and context['kind'] == 'delivery_release_context', 'Current delivery assurance context required')
    require(context == bind_context(plan, context['descriptor']), 'Delivery assurance context changed')
    return context


def attestation_bindings(observation):
    return {'observation_sha256': hash_json(observation)}


def _check_result(observation, result):
    require(type(result) is dict and set(result) == {'schema_version', 'kind', 'lane', 'status', 'execution',
            'synthetic', 'checks', 'references'}, 'Invalid normalized delivery result')
    lane = observation['lane']
    require(type(result['schema_version']) is int and result['schema_version'] == 1
            and result['kind'] == 'delivery_lane_result' and result['lane'] == lane
            and result['status'] == observation['status'] and hash_json(result) == observation['result_sha256'],
            'Delivery result does not match its observation')
    require(type(result['synthetic']) is bool and result['synthetic'] is False,
            'Synthetic evidence cannot qualify a migration')
    expected = 'native' if lane in NATIVE_LANES else 'human' if lane == 'business_acceptance' else 'local'
    provenance = {'native': 'native_observation', 'human': 'human_decision', 'local': 'local_check'}[expected]
    require(result['execution'] == expected and observation['provenance'] == provenance,
            'Delivery lane requires its own native, human or local evidence')
    require(type(result['checks']) is dict and set(result['checks']) == CHECKS[lane]
            and all(type(v) is bool for v in result['checks'].values()), 'Incomplete typed delivery checks')
    if observation['status'] == 'passed':
        require(all(result['checks'].values()), 'A failed required check cannot become a passed lane')
    refs = result['references']
    require(type(refs) is list and 0 < len(refs) <= 100 and all(type(r) is dict
            and set(r) == {'reference', 'sha256'} and type(r['reference']) is str and r['reference'].strip()
            and type(r['sha256']) is str and assurance.SHA.fullmatch(r['sha256']) for r in refs),
            'Delivery evidence requires bounded original receipt references')


def evaluate_release(plan, policy, *, excluded_issuers=(), now=None):
    """Every pass, including a local result, requires an external trusted issuer.

    Normalized result references must be checked by that issuer against original
    outputs and native sessions. A signature authenticates its statement, not the
    remote system by itself. Independent provisioned issuers are a prerequisite.
    """
    context = current_context(plan)
    require(hash_json(policy) == plan['policy_sha256'], 'Runner policy changed')
    observations, trusted, issuers = [], [], []
    for item in context['descriptor']['evidence']:
        require(type(item) is dict and set(item) == {'observation', 'result', 'attestation'},
                'Unsigned or malformed evidence cannot satisfy release readiness')
        observation = item['observation']
        require(type(observation) is dict and set(observation) == {'lane', 'status', 'bindings', 'observed_at',
                'expires_at', 'result_sha256', 'provenance'} and observation['lane'] in assurance.LANES
                and observation['status'] in assurance.STATUSES, 'Invalid delivery observation')
        require(observation['bindings'] == context['bindings'], 'Stale delivery evidence bindings')
        payload = verify_attestation(item['attestation'], policy, purpose='delivery_evidence',
                                     bindings=attestation_bindings(observation), now=now)
        issuer = policy['issuers'][payload['issuer']]
        require(payload['issuer'] not in excluded_issuers, 'Evidence issuer must be independent of release approvers')
        require(observation['lane'] in issuer.get('evidence_lanes', []), 'Issuer cannot certify this evidence lane')
        require(assurance._time(payload['issued_at']) >= assurance._time(observation['observed_at'])
                and assurance._time(payload['expires_at']) <= assurance._time(observation['expires_at']),
                'Signed evidence cannot outlive or precede its observation')
        _check_result(observation, item['result'])
        observations.append(observation); trusted.append(hash_json(observation)); issuers.append(payload['issuer'])
    report = assurance.evaluate(plan['migration_scope'], context['bindings'], observations,
                                semantic_target=plan['review_target'].get('semantic_target') or 'none',
                                now=now, trusted_receipts=trusted)
    report.update(authority_authenticated=True, issuer_ids=sorted(set(issuers)),
                  runner_mode=policy['mode'])
    if policy['mode'] != 'live':
        report['acceptance_ready'] = False
        report['qualification'] = 'Simulation verifies the protocol only; it cannot qualify a live migration.'
    return report


def require_release(plan, policy, *, excluded_issuers=(), now=None):
    """Order gates so development testing is possible before final acceptance."""
    if plan.get('migration_scope') is None and policy['mode'] == 'simulation':
        require(plan.get('delivery_assurance') is None, 'Legacy simulation cannot acquire enhanced evidence')
        return {'acceptance_ready': False, 'qualification': 'Historical simulation only; migrate intake for live use.'}
    require(plan.get('migration_scope') in assurance.SCOPES,
            'Legacy or unscoped plans cannot authorize new live releases; refresh intake')
    report = evaluate_release(plan, policy, excluded_issuers=excluded_issuers, now=now)
    required = PR_LANES if plan['action'] == 'publish_pr' else DEV_LANES if plan['action'] == 'deploy_development' else assurance.required_lanes(plan['migration_scope'])
    indexed = {r['lane']: r['status'] for r in report['checks']}
    require(all(indexed.get(lane) == 'passed' for lane in required),
            'Required delivery evidence is missing, failed, unsupported or stale')
    if plan['action'] != 'publish_pr':
        from security_contract import evaluate_access
        access = plan['delivery_assurance']['descriptor']['access']
        require(access is not None, 'Existing destination access must be verified before exposure')
        result = evaluate_access(**access)
        require(result['status'] == 'locally_consistent', 'Access state/readback/persona evidence is incomplete or unsafe')
        entry = next(v for v in plan['delivery_assurance']['descriptor']['evidence'] if v['observation']['lane'] == 'access')
        require(any(r['sha256'] == hash_json(result) for r in entry['result']['references']),
                'Authenticated access lane must bind the exact evaluated security bundle')
    return report
