"""Optional bounded work within one domain; retain the cumulative model design."""
import copy

from ae_common import hash_json, require


def active(state):
    from domain_workflow import ledger
    domain_id = (ledger(state) or {}).get('active_domain_id')
    return (state.get('workflow', {}).get('domain_batches') or {}).get(domain_id)


def selected_scope(state, doc=None):
    batch = active(state)
    if not batch or batch['status'] != 'active':
        return None
    from engagement_stages import closure
    graph = {e['id']: e['depends_on'] for e in (doc or state['workflow']['design'])['entities']}
    require(set(batch['entity_ids']) <= set(graph), 'Selected batch changed; retain its model IDs or select a revised batch')
    return set(closure(graph, batch['entity_ids']))


def select(state, request):
    import engagement_stages as stages
    import domain_workflow as domains
    stages.fields(request, {'schema_version', 'domain_id', 'batch_id', 'name', 'entity_ids', 'request_reference'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported batch selection')
    domain = domains._domain(state)
    require(request['domain_id'] == domain['id'], 'Select the domain before selecting its batch')
    stages.identifier(request['batch_id']); stages.text(request['name']); stages.text(request['request_reference'])
    stages.ids(request['entity_ids'], domains._models(state, domain), True)
    domains._idle(state)
    previous = active(state)
    if previous and previous['status'] == 'active':
        require(previous['batch_id'] == request['batch_id'] and previous['entity_ids'] == request['entity_ids'],
                'Complete or explicitly pause the current batch before selecting another')
        return
    history = state['workflow'].setdefault('domain_batch_history', [])
    require(all(r['batch_id'] != request['batch_id'] or (r['domain_id'] == domain['id'] and r['entity_ids'] == request['entity_ids'])
                for r in history), 'Preserve batch identity and scope; use a new ID for different entities')
    batch = {**copy.deepcopy(request), 'status': 'active', 'assurance': 'host_reported_user_choice'}
    state['workflow'].setdefault('domain_batches', {})[domain['id']] = batch
    history.append(copy.deepcopy(batch))


def finish(state, request, *, pause=False):
    import engagement_stages as stages
    import domain_workflow as domains
    stages.fields(request, {'schema_version', 'batch_id', 'request_reference'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported batch action')
    stages.text(request['request_reference'])
    batch = active(state)
    require(batch and batch['status'] == 'active' and batch['batch_id'] == request['batch_id'], 'Select this batch first')
    domains._idle(state)
    if not pause:
        _, gaps, binding = domains._progress(state, domains._domain(state), domains._plan(state), selected=selected_scope(state))
        require(not gaps, 'Batch is incomplete: ' + ' '.join(gaps))
        batch['completion_binding'] = binding
    batch.update(status='paused' if pause else 'completed', request_reference=request['request_reference'])
    state['workflow']['domain_batch_history'].append(copy.deepcopy(batch))


def scope_preview(state, domain):
    import domain_workflow as domains
    doc = state.get('workflow', {}).get('design') or {}
    models = [e for e in doc.get('entities', []) if e['id'] in domains.scope(state, domain)]
    counts = {'models': len(models), 'columns': sum(len(e['columns']) for e in models),
              'source_files': len(domain['source_paths']), 'assets': len(domain['asset_ids'])}
    large = counts['models'] > 25 or counts['columns'] > 500 or counts['source_files'] > 100 or counts['assets'] > 20
    return {**counts, 'batching_recommended': large,
            'qualification': 'Review-size heuristic, not a cost or duration estimate. Dependencies remain in scope; existing current outputs may be reused.'}


def public_summary(state, tasks=None):
    import domain_workflow as domains
    batch = active(state)
    if not batch:
        return None
    scope = selected_scope(state)
    if scope is None:
        from engagement_stages import closure
        graph = {e['id']: e['depends_on'] for e in state['workflow']['design']['entities']}
        scope = set(closure(graph, batch['entity_ids'])) if set(batch['entity_ids']) <= set(graph) else set()
    statuses, gaps, binding = domains._progress(state, domains._domain(state), domains._plan(state) if tasks is None else tasks, selected=scope)
    return {'batch_id': batch['batch_id'], 'name': batch['name'], 'entity_ids': batch['entity_ids'],
            'dependency_ids': sorted(scope - set(batch['entity_ids'])),
            'status': 'stale' if batch['status'] == 'completed' and batch.get('completion_binding') != binding else batch['status'],
            **statuses, 'next_action': gaps[0] if gaps else 'Review this batch, then record completion and select the next batch.',
            'qualification': 'Batch completion never completes the rest of the domain or establishes native validation.'}
