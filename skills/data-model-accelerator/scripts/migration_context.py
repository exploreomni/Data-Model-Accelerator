"""Carry explicit domain intent into bounded packets without repository discovery."""
import copy

from ae_common import require


def task_contracts(state, selected=None):
    from migration_intent import packet_contract
    configured = state.get('workflow', {}).get('migration_intents') or {}
    if not configured:
        return []
    entities = {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}
    if selected is None:
        domains = set(configured)
    else:
        from engagement_stages import closure
        selected = set(selected)
        graph = {key: e['depends_on'] for key, e in entities.items()}
        scope = closure(graph, selected & set(entities)) if selected & set(entities) else set()
        from migration_intent import _models
        domains = (selected & set(configured)) | {domain for domain in configured if set(scope) & set(_models(state, domain))}
    return [packet_contract(state, key) for key in sorted(domains & set(configured))]


def contract_bindings(contracts):
    return {'migration_intent.' + row['domain_id']: row['binding_sha256'] for row in contracts}


def packet_evidence(request):
    """Check declared evidence roles, not the semantic truth of those labels.

    Incomplete evidence produces a discovery-only context report. It never
    prevents an explicitly requested provisional design or code candidate.
    """
    contracts = request.get('migration_intents', [])
    pins = {k: v for k, v in request['bindings'].items() if k.startswith('migration_intent.')}
    require(type(contracts) is list and len(contracts) <= 32, 'Invalid scoped migration intents')
    if not contracts:
        require(not pins and not request.get('design_evidence'), 'Intent pins/evidence require the complete scoped intent contract')
        return None
    from migration_intent import validate_packet_contract
    for row in contracts:
        validate_packet_contract(row)
    require(len({row['domain_id'] for row in contracts}) == len(contracts), 'Duplicate domain intent')
    require(pins == contract_bindings(contracts), 'Migration intent packet pins differ or are missing')
    rows = request.get('design_evidence', [])
    require(type(rows) is list and len(rows) <= 64, 'Invalid scoped design evidence')
    evidence = {e['id'] for e in request['evidence']}
    declared = {}
    allowed = {'legacy_transformation', 'source_contract', 'target_convention', 'target_model', 'consumer_requirement'}
    for row in rows:
        require(type(row) is dict and set(row) == {'domain_id', 'evidence_id', 'role'}, 'Invalid design evidence role')
        require(row['domain_id'] in {c['domain_id'] for c in contracts} and row['evidence_id'] in evidence
                and row['role'] in allowed, 'Design evidence must reference supplied excerpts and known domains')
        declared.setdefault(row['domain_id'], set()).add(row['role'])
    reports = []
    for contract in contracts:
        # The contract body is owned by migration_intent, independent of packet prose.
        intent = contract['intent']
        required = {'legacy_transformation', 'source_contract'} if intent['structural_objective'] == 'refactor' else {'source_contract'}
        if any(r['role'] == 'target_implementation' for r in intent['source_roles']):
            required |= {'target_convention', 'target_model'}
        missing = sorted(required - declared.get(contract['domain_id'], set()))
        reports.append({'domain_id': contract['domain_id'], 'missing_evidence_roles': missing,
                        'status': 'context_incomplete' if missing else 'declared_evidence_supplied'})
    return {'domains': reports, 'evidence_roles': copy.deepcopy(rows),
            'qualification': 'Declared excerpt roles only, not proof of sufficient semantics. Verify filters, grain, keys, history and security in the excerpts; request exact missing context. Provisional authoring remains available.'}
