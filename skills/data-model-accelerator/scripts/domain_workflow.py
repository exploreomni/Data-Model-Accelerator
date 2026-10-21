"""Optional, durable one-domain-at-a-time coordination; no execution authority.

Discovery proposes a portfolio. A host-attributed user choice selects one scope.
Completion derives from current review and recorded file bytes, never a UI flag.
"""
import copy

from ae_common import hash_json, require, safe_relative

QUALIFICATION = ('Completed means reviewed candidate code is recorded for the selected domain. '
                 'Native validation, business acceptance, packaging and deployment remain separate. '
                 'User choices are host-attributed, not authenticated identity.')


def ledger(state):
    return state.get('workflow', {}).get('domain_journey')


def _models(state, domain, doc=None):
    doc = doc if doc is not None else state['workflow'].get('design') or {}
    labels = {domain['id'].casefold(), domain['name'].casefold()}
    return {e['id'] for e in doc.get('entities', []) if e['domain'].casefold() in labels}


def _domain(state, key=None):
    value = ledger(state)
    require(value is not None, 'Register candidate domains first')
    key = key or value['active_domain_id']
    result = next((d for d in value['domains'] if d['id'] == key), None)
    require(result is not None, 'Ask the user which domain to design first; record select-domain')
    return result


def _idle(state):
    require(not any(a.get('status') == 'active' and a.get('role') not in
                    {'source_specialist', 'catalogue_specialist'}
                    for a in state.get('operations', {}).get('attempts', [])),
            'Checkpoint active domain workers before changing domains')


def register(state, request):
    import engagement_stages as stages
    stages.fields(request, {'schema_version', 'domains'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1,
            'Unsupported domain discovery version')
    require(type(request['domains']) is list and 0 < len(request['domains']) <= 200,
            'Supply one to 200 candidate domains')
    require(all(type(d) is dict for d in request['domains']), 'Each domain must be a discovery object')
    stages.ids([d.get('id') for d in request['domains']], nonempty=True)
    labels = set()
    for d in request['domains']:
        stages.fields(d, {'id', 'name', 'description', 'asset_ids', 'source_paths', 'shared_dependency_ids'})
        stages.text(d['name']); stages.text(d['description'])
        own_labels = {d['id'].casefold(), d['name'].casefold()}
        require(not labels & own_labels, 'Domain identifiers and names must be unambiguous')
        labels.update(own_labels)
        stages.ids(d['asset_ids']); stages.ids(d['shared_dependency_ids'])
        require(type(d['source_paths']) is list and len(d['source_paths']) <= 512, 'Domain source paths must be bounded')
        for p in d['source_paths']:
            safe_relative(p)
    old = ledger(state)
    digest = hash_json(request['domains'])
    if old and old['candidates_sha256'] == digest:
        return
    _idle(state)
    if old:
        require(old['active_domain_id'] is None, 'Pause or complete the active domain before revising discovery')
        incoming = {d['id']: d for d in request['domains']}
        require(all(d['id'] in incoming and incoming[d['id']]['name'] == d['name'] for d in old['domains']),
                'Preserve existing domain identities and progress; discovery may add domains')
    value = copy.deepcopy(old) if old else {'schema_version': 1, 'active_domain_id': None, 'events': [], 'completions': []}
    value.update(domains=copy.deepcopy(request['domains']), candidates_sha256=digest)
    state['workflow']['domain_journey'] = value


def _request(state, request, *, select=False):
    import engagement_stages as stages
    stages.fields(request, {'schema_version', 'domain_id', 'request_reference'} |
                  ({'candidates_sha256'} if select else set()))
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported domain action version')
    stages.text(request['request_reference'])
    stages.identifier(request['domain_id'])
    domain = _domain(state, request['domain_id'])
    if select:
        require(request['candidates_sha256'] == ledger(state)['candidates_sha256'],
                'Domain candidates changed; show the current choices before recording selection')
    return domain


def _event(state, action, request):
    from guided_workflow import _now
    ledger(state)['events'].append({'action': action, 'domain_id': request['domain_id'],
        'request_reference': request['request_reference'], 'recorded_at': _now(),
        'assurance': 'host_reported_user_choice'})


def select_domain(state, request):
    domain = _request(state, request, select=True)
    value = ledger(state)
    require(value['active_domain_id'] in (None, domain['id']),
            'Complete or explicitly pause the active domain before choosing another')
    if value['active_domain_id'] == domain['id']:
        return
    _idle(state)
    value['active_domain_id'] = domain['id']
    _event(state, 'select', request)


def pause_domain(state, request):
    _request(state, request)
    require(ledger(state)['active_domain_id'] == request['domain_id'], 'Only the active domain can be paused')
    _idle(state)
    _event(state, 'pause', request)
    ledger(state)['active_domain_id'] = None


def scope(state, domain=None, doc=None):
    import engagement_stages as stages
    domain = domain or _domain(state)
    doc = doc if doc is not None else state['workflow'].get('design') or {}
    primary = _models(state, domain, doc)
    graph = {e['id']: e['depends_on'] for e in doc.get('entities', [])}
    return set(stages.closure(graph, sorted(primary))) if primary else set()


def require_scope(state, selected, stage='design'):
    if not ledger(state) or stage == 'packaging':
        return
    import engagement_stages as stages
    domain = _domain(state)
    doc = stages.design(state)
    primary = _models(state, domain, doc)
    allowed = primary | set(domain['shared_dependency_ids'])
    graph = {e['id']: e['depends_on'] for e in doc['entities']}
    stages.ids(selected, graph, True)
    expanded = set(stages.closure(graph, selected))
    require(bool(selected) and expanded <= allowed,
            'Work is outside the selected domain or its declared shared dependencies; pause and select that domain first')


def guard_design(state, value):
    if not ledger(state):
        return
    domain = _domain(state)
    previous = state['workflow'].get('design') or {}
    old = {e['id']: e for e in previous.get('entities', [])}
    new = {e['id']: e for e in value['entities']}
    require(all(key not in old or entity['domain'] == old[key]['domain'] for key, entity in new.items()),
            'Preserve existing model domain ownership; relabeling cannot expand the selected scope')
    allowed = (_models(state, domain, value) - set(old)) | _models(state, domain, previous) | set(domain['shared_dependency_ids'])
    require(all(key in new and new[key] == entity for key, entity in old.items() if key not in allowed),
            'Preserve designs for other domains; import a cumulative design')
    require(all(key in allowed or (key in old and old[key] == entity) for key, entity in new.items()),
            'Design only the selected domain and declared shared dependencies')
    known_labels = {label.casefold() for d in ledger(state)['domains'] for label in (d['id'], d['name'])}
    require(all(e['domain'].casefold() in known_labels or e['id'] in {key for d in ledger(state)['domains'] for key in d['shared_dependency_ids']} for e in value['entities']),
            'Map model domains to the discovered domain IDs or names')
    require(scope(state, domain, value) <= allowed, 'Declare required shared dependencies before designing their interfaces')
    # A cumulative import may amend selected/shared contracts, not unrelated
    # relationships, decisions, asset labels or existing-model evidence.
    active_assets = set(domain['asset_ids']) | {a for e in value['entities'] if e['id'] in allowed for a in e['asset_ids']}
    active_existing = {e['reuse']['existing_id'] for e in value['entities'] if e['id'] in allowed and e.get('reuse')}
    predicates = {
        'relationships': lambda r: r['from'] in allowed or r['to'] in allowed,
        'decisions': lambda r: bool(set(r['model_ids']) & allowed),
        'assets': lambda r: r['id'] in active_assets,
        'existing_models': lambda r: r['id'] in active_existing,
    }
    for key, editable in predicates.items():
        old_rows, new_rows = previous.get(key, []), value.get(key, [])
        require(all(row in new_rows for row in old_rows if not editable(row)) and
                all(editable(row) or row in old_rows for row in new_rows),
                'Preserve unrelated domain ' + key + ' in cumulative designs')


def merge_tasks(state, request):
    """Append/replace active tasks while retaining earlier domains and output owners."""
    if not ledger(state):
        return request
    previous = {t['id']: t for t in state['workflow']['tasks']}
    for task in request['tasks']:
        if previous.get(task['id']) == task:
            continue
        require_scope(state, task['entity_ids'], task['stage'])
        if task['id'] in previous:
            require_scope(state, previous[task['id']]['entity_ids'], previous[task['id']]['stage'])
        previous[task['id']] = task
    return {**request, 'tasks': list(previous.values())}


def guard_dispatch(state, request):
    if not ledger(state) or request['role'] in {'source_specialist', 'catalogue_specialist'}:
        return
    domain = _domain(state)
    if request['role'] == 'migration_project_manager':
        require(not request.get('task_id') and request['scope_ids'] == [domain['id']]
                and not request['source_paths'],
                'Migration planning must use the selected domain and retained evidence only')
        return
    if request.get('task_id'):
        require_scope(state, request['scope_ids'])
    elif request['role'] == 'warehouse_architect' and request['scope_ids'] == [domain['id']]:
        require(set(request['source_paths']) <= set(domain['source_paths']),
                'Domain design packet must use the selected discovery source paths')
    else:
        require_scope(state, request['scope_ids'])


def _required_stages(state):
    selected = set(state['answers'].get('deliverables', []))
    result = ['implementation'] if 'implementation' in selected else []
    if result and state['answers'].get('semantic_target') not in (None, 'none', 'retain_existing') and state['answers'].get('migration_scope') != 'model_only':
        result.append('semantic')
    return result


def _plan(state):
    import engagement_stages as stages
    wf = state['workflow']
    if not wf.get('artifact_root') or not wf['tasks']:
        return []
    return stages.plan_tasks(state, wf['artifact_root'])['tasks']


def _progress(state, domain, tasks):
    import engagement_stages as stages
    selected = scope(state, domain)
    statuses = {'design_status': 'not_started', 'implementation_status': 'not_requested', 'semantic_status': 'not_requested'}
    required = _required_stages(state)
    binding, gaps = None, []
    if not selected:
        gaps.append('Design the selected domain and its required shared interfaces.')
    else:
        approved = selected <= stages.approved_entities(state)
        statuses['design_status'] = 'review_recorded' if approved else 'needs_review'
        if not approved:
            gaps.append('Obtain current human design review for the domain and its shared dependencies.')
    represented_assets = {asset for e in (state['workflow'].get('design') or {}).get('entities', [])
                          if e['id'] in selected for asset in e.get('asset_ids', [])}
    missing_assets = set(domain['asset_ids']) - represented_assets
    if selected and missing_assets:
        gaps.append('Map the discovered domain assets to its models before completion: ' + ', '.join(sorted(missing_assets)))
    finished = []
    graph = {e['id']: e['depends_on'] for e in (state['workflow'].get('design') or {}).get('entities', [])}
    for stage in required:
        matches = [t for t in tasks if t['stage'] == stage and set(t['entity_ids']) & selected]
        current = [t for t in matches if t['action'] == 'reuse' and t.get('generation_mode') != 'provisional'
                   and set(t['entity_ids']) <= selected]
        covered = {e for t in current for e in (stages.closure(graph, t['entity_ids']) if stage == 'semantic' else t['entity_ids'])}
        done = bool(selected) and selected <= covered
        statuses[stage + '_status'] = ('outputs_recorded' if done else
            'provisional_outputs' if any(t['action'] == 'reuse' and t.get('generation_mode') == 'provisional' for t in matches)
            else 'partial' if current else 'pending')
        if not done:
            gaps.append('Record current reviewed ' + stage + ' outputs for: ' + ', '.join(sorted(selected - covered)))
        finished.extend(t for t in current if set(t['entity_ids']) <= selected)
    if not gaps:
        binding = hash_json({'domain': domain, 'entities': stages.entity_bindings(state, sorted(selected)), 'required_stages': required,
            'target': state['inputs']['target'], 'discovery': state['inputs']['discovery'],
            'tasks': {t['id']: {'fingerprint': t['fingerprint'], 'outputs': t['outputs']} for t in finished}})
    return statuses, gaps, binding


def complete_domain(state, request):
    domain = _request(state, request)
    require(ledger(state)['active_domain_id'] == domain['id'], 'Select the domain before completing it')
    _idle(state)
    statuses, gaps, binding = _progress(state, domain, _plan(state))
    require(not gaps, 'Domain is incomplete: ' + ' '.join(gaps))
    _event(state, 'complete', request)
    ledger(state)['completions'].append({'domain_id': domain['id'], 'binding': binding,
        'completion_kind': 'reviewed_code' if _required_stages(state) else 'reviewed_design_only',
        'request_reference': request['request_reference']})
    ledger(state)['active_domain_id'] = None


def public_summary(state, allowed_models=None):
    value = ledger(state)
    if not value:
        return None
    tasks = _plan(state)
    rows = []
    for domain in value['domains']:
        primary = _models(state, domain)
        # A restricted package must not reveal undisclosed domain/source names.
        if allowed_models is not None and (not primary or not (scope(state, domain) | set(domain['shared_dependency_ids'])) <= set(allowed_models)):
            continue
        statuses, gaps, binding = _progress(state, domain, tasks)
        receipt = next((r for r in reversed(value['completions']) if r['domain_id'] == domain['id']), None)
        events = [e['action'] for e in value['events'] if e['domain_id'] == domain['id']]
        completed = receipt and receipt['binding'] == binding
        status = ('active' if value['active_domain_id'] == domain['id'] else 'completed' if completed else
                  'stale' if receipt else 'paused' if 'pause' in events else 'queued')
        action = (gaps[0] if value['active_domain_id'] == domain['id'] and gaps else
                  'Record complete-domain, then ask which domain to work on next.' if status == 'active' else
                  'Candidate delivery recorded; native validation and deployment are separate.' if completed else
                  'Ask the user to select this domain before continuing.')
        rows.append({**{k: copy.deepcopy(domain[k]) for k in ('id', 'name', 'description', 'shared_dependency_ids')},
            'model_ids': sorted(primary), 'asset_count': len(domain['asset_ids']), 'status': status, **statuses,
            'completion_kind': receipt['completion_kind'] if completed else None, 'next_action': action})
    active = value['active_domain_id'] if any(r['id'] == value['active_domain_id'] for r in rows) else None
    all_done = bool(rows) and all(r['status'] == 'completed' for r in rows)
    next_action = (next(r['next_action'] for r in rows if r['id'] == active) if active else
        'All discovered domains have recorded candidate deliveries. Review validation and package the selected outputs.' if all_done else
        'Show the domain choices and ask which domain the user would like to design next. Do not select automatically.')
    return {'schema_version': 1, 'kind': 'domain_journey', 'candidates_sha256': value['candidates_sha256'],
        'active_domain_id': active, 'needs_selection': active is None and not all_done and bool(rows),
        'domains': rows, 'counts': {s: sum(r['status'] == s for r in rows) for s in ('queued', 'active', 'paused', 'completed', 'stale')},
        'next_action': next_action, 'qualification': QUALIFICATION}
