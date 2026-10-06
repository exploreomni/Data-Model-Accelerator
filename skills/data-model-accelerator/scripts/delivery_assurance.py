"""Scope-aware evidence evaluation. Imported assertions are never native proof."""
from datetime import datetime, timezone
import re

from ae_common import hash_json, require

SCOPES = {'model_only', 'model_semantic', 'full_dashboard'}
STATUSES = {'passed', 'failed', 'pending', 'unsupported', 'not_applicable', 'stale'}
BASE = {'source_coverage', 'classification', 'input_egress', 'warehouse_execution',
        'data_parity', 'access', 'output_disclosure', 'business_acceptance'}
SEMANTIC = {'yaml', 'omni_static', 'native_model', 'omni_queries', 'ai_context'}
DASHBOARD = {'dashboard_created', 'dashboard_behavior'}
LANES = BASE | SEMANTIC | DASHBOARD
NATIVE = {'warehouse_execution', 'native_model', 'omni_queries',
          'dashboard_created', 'dashboard_behavior', 'access'}
BINDINGS = {'source', 'catalogue', 'candidate', 'target', 'policy', 'scope'}
SHA = re.compile(r'[a-f0-9]{64}\Z')


def required_lanes(scope, semantic_target='omni'):
    require(scope in SCOPES, 'Explicit migration_scope required')
    result = set(BASE)
    if scope != 'model_only':
        require(semantic_target == 'omni', 'Enhanced semantic qualification currently requires Omni')
        result |= SEMANTIC
    if scope == 'full_dashboard':
        result |= DASHBOARD
    return result


def validate_bindings(bindings):
    require(type(bindings) is dict and set(bindings) == BINDINGS
            and all(type(v) is str and SHA.fullmatch(v) for v in bindings.values()),
            'Complete source/catalogue/candidate/target/policy/scope hashes required')


def _time(value):
    require(type(value) is str, 'Evidence timestamp required')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid evidence timestamp') from None
    require(stamp.tzinfo is not None, 'Evidence timestamp requires timezone')
    return stamp


def evaluate(scope, bindings, observations=(), *, semantic_target='omni', now=None,
             trusted_receipts=()):
    """trusted_receipts contains digests independently observed by this caller.

    It is a process trust boundary, not a JSON field or a signature scheme. CLI
    callers/imported reports cannot authenticate their own native or human pass.
    Native adapters must independently re-observe remote state before reuse.
    """
    validate_bindings(bindings)
    required = required_lanes(scope, semantic_target)
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None, 'Evaluation time requires timezone')
    require(type(observations) in (list, tuple), 'Expected evidence list')
    indexed = {}
    for item in observations:
        require(type(item) is dict and item.get('lane') in LANES, 'Unknown evidence lane')
        lane = item['lane']
        require(lane not in indexed, 'Duplicate evidence lane; reconcile observations explicitly')
        require(item.get('status') in STATUSES, 'Unsupported evidence status')
        validate_bindings(item.get('bindings'))
        indexed[lane] = item
    checks = []
    for lane in sorted(LANES):
        item = indexed.get(lane)
        status, reason = 'pending', 'Required evidence has not been collected'
        if lane not in required:
            status, reason = 'not_applicable', 'Excluded by selected migration scope'
        elif item:
            status, reason = item['status'], 'Recorded evidence'
            if item['bindings'] != bindings:
                status, reason = 'stale', 'Evidence belongs to different inputs or target'
            elif status == 'not_applicable':
                status, reason = 'failed', 'Required lane cannot be marked not applicable'
            elif status == 'passed':
                started, expires = _time(item.get('observed_at')), _time(item.get('expires_at'))
                if started > now or expires <= now or expires <= started:
                    status, reason = 'stale', 'Evidence is expired or has invalid timing'
                elif not SHA.fullmatch(str(item.get('result_sha256', ''))):
                    status, reason = 'failed', 'Evidence lacks a result binding'
                elif lane in NATIVE | {'business_acceptance'} and hash_json(item) not in trusted_receipts:
                    status, reason = 'pending', 'Imported assertion requires independent native or human confirmation'
                elif item.get('provenance') not in {'local_check', 'native_observation', 'human_decision'}:
                    status, reason = 'pending', 'Synthetic or unverified assertions cannot satisfy readiness'
                elif lane in NATIVE and item['provenance'] != 'native_observation':
                    status, reason = 'pending', 'Native observation required'
                elif lane == 'business_acceptance' and item['provenance'] != 'human_decision':
                    status, reason = 'pending', 'Human business acceptance required'
        checks.append({'lane': lane, 'status': status, 'reason': reason, 'required': lane in required})
    ready = all(c['status'] == 'passed' for c in checks if c['required'])
    return {'schema_version': 1, 'kind': 'delivery_assurance', 'migration_scope': scope,
            'bindings': dict(bindings), 'checks': checks, 'acceptance_ready': ready,
            'deployment_authorized': False,
            'assurance': 'Evidence evaluation only; destination authorization remains separate.'}


def pending_summary(scope):
    if scope not in SCOPES:
        return {'migration_scope': None, 'acceptance_ready': False, 'deployment_authorized': False,
                'qualification': 'Migration scope is unresolved; prepared files do not establish acceptance.'}
    return evaluate(scope, {k: '0' * 64 for k in BINDINGS})
