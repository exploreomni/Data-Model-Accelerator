"""Reconcile requested outcomes with an explicit host-authored execution plan."""
import copy

from ae_common import hash_json, require
from deliverable_contract import required_stages

STAGES = ('design', 'implementation', 'semantic', 'validation', 'packaging')


def binding(state):
    from domain_workflow import ledger
    journey = ledger(state) or {}
    intent = {}
    if state.get('workflow', {}).get('migration_intents'):
        from migration_context import task_contracts, contract_bindings
        selected = [journey['active_domain_id']] if journey.get('active_domain_id') else None
        intent = {'migration_intents': contract_bindings(task_contracts(state, selected))}
    return hash_json({**intent, 'selection': {k: state['answers'].get(k) for k in
        ('deliverables', 'framework', 'warehouse', 'semantic_target', 'migration_scope')},
        'active_domain_id': journey.get('active_domain_id'),
        'active_batch': (state.get('workflow', {}).get('domain_batches') or {}).get(journey.get('active_domain_id'))})


def record_plan(state, request):
    import engagement_stages as stages
    stages.fields(request, {'schema_version', 'stages', 'request_reference'})
    require(request['schema_version'] == 1 and type(request['stages']) is list,
            'Unsupported delivery plan')
    stages.text(request['request_reference'])
    required = set(required_stages(state)) | {'design', 'packaging'}
    rows = {}
    for row in request['stages']:
        stages.fields(row, {'stage', 'status', 'reason'}, {'request_reference'})
        require(row['stage'] in STAGES and row['stage'] not in rows, 'Unknown or repeated plan stage')
        require(row['status'] in {'planned', 'deferred', 'not_selected'}, 'Invalid plan stage status')
        stages.text(row['reason'])
        if row['stage'] in required:
            require(row['status'] != 'not_selected', 'Requested ' + row['stage'] + ' cannot be omitted; explicitly defer it or change intake')
        if row['status'] == 'deferred':
            stages.text(row.get('request_reference'))
        rows[row['stage']] = copy.deepcopy(row)
    require(required <= set(rows), 'Delivery plan must account for every requested stage: ' + ', '.join(sorted(required - set(rows))))
    if rows.get('semantic', {}).get('status') == 'planned':
        require(rows.get('implementation', {}).get('status') == 'planned',
                'Omni/semantic authoring requires a planned warehouse implementation or verified reuse-binding stage')
    from domain_workflow import ledger, scope
    journey = ledger(state) or {}
    domain_id = journey.get('active_domain_id')
    scope_ids = (sorted(scope(state)) if domain_id else
                 sorted(e['id'] for e in (state['workflow'].get('design') or {}).get('entities', [])))
    result = {'schema_version': 1, 'kind': 'delivery_execution_plan', 'binding': binding(state),
              'domain_id': domain_id, 'scope_ids': scope_ids,
              'stages': list(rows.values()), 'request_reference': request['request_reference'],
              'assurance': 'host_reported_scope_plan',
              'qualification': 'Deferral is outstanding work, not completion or design approval. This plan grants no execution authority.'}
    state['workflow']['delivery_plan'] = result
    return result


def require_not_deferred(state, stage):
    plan = state.get('workflow', {}).get('delivery_plan')
    if not plan or plan['binding'] != binding(state):
        return  # Legacy/no plan does not block explicit provisional authoring.
    require(not any(r['stage'] == stage and r['status'] == 'deferred' for r in plan['stages']),
            'This stage is explicitly deferred. Update record-delivery-plan to planned before authoring it; requested code remains outstanding.')


def public_summary(state, allowed_models=None):
    wf = state.get('workflow') or {}
    recorded = wf.get('delivery_plan')
    current = bool(recorded and recorded['binding'] == binding(state))
    if recorded and allowed_models is not None and (not recorded.get('scope_ids')
            or not set(recorded['scope_ids']) <= set(allowed_models)):
        return {'status': 'outside_review_scope', 'stages': [], 'deferred_stages': [], 'unplanned_code_stages': [],
                'qualification': 'Planning details are omitted because their full recorded scope is outside this review.'}
    declared = {r['stage']: r for r in recorded['stages']} if current else {}
    required = ['design', *required_stages(state), 'packaging']
    tasks = wf.get('tasks', [])
    if allowed_models is not None:
        tasks = [t for t in tasks if set(t['entity_ids']) <= set(allowed_models)]
    rows = []
    for stage in required:
        row = declared.get(stage, {})
        rows.append({'stage': stage, 'plan_status': row.get('status', 'unrecorded'),
                     'reason': row.get('reason'), 'task_count': sum(t['stage'] == stage for t in tasks)})
    return {'status': 'current' if current else 'stale' if recorded else 'unrecorded',
            'stages': rows, 'deferred_stages': [r['stage'] for r in rows if r['plan_status'] == 'deferred'],
            'unplanned_code_stages': [r['stage'] for r in rows if r['stage'] in {'implementation', 'semantic'} and not r['task_count']],
            'qualification': 'Requested outcomes remain pending until their files and separate validation evidence are recorded. Deferral never means delivery.'}
