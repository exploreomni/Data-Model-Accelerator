"""Scoped migration intent and attributed architecture assessment, never approval.

The canonical schema remains v1. Intent bindings deliberately exclude authored
assessments; recording a review must not invalidate the work it reviewed.
"""
import copy
import json
import stat

from ae_common import hash_file, hash_json, require, safe_relative
from engagement_stages import DIMENSIONS, SHA, fields, identifier, ids, text

ROLES = {'legacy_baseline', 'target_implementation', 'raw_staging', 'consumer_requirements'}
QUALIFICATION = ('Host-attributed architecture evidence only; identities and judgments are not authenticated. '
                 'No native validation, behavioral parity, business approval, retirement or execution authority.')
MAX_BYTES = 262144


def _safe(value):
    import guided_workflow as guided
    guided._secrets(value)
    require(len(guided._bytes(value)) <= MAX_BYTES, 'Migration intent evidence exceeds the bounded request size')


def _list(value, label, maximum=128):
    require(type(value) is list and len(value) <= maximum, 'Invalid bounded ' + label)
    return value


def _strings(value, label, nonempty=False):
    _list(value, label)
    require(not nonempty or value, label + ' must not be empty')
    for item in value:
        text(item)
    require(len(value) == len(set(value)), 'Duplicate ' + label)


def _source_refs(value, allowed=None):
    _strings(value, 'source references', nonempty=True)
    for reference in value:
        safe_relative(reference)
    require(allowed is None or set(value) <= set(allowed), 'Source references must belong to byte-pinned assessment evidence')


def _records(state):
    value = state.get('workflow', {}).get('migration_intents', {})
    require(type(value) is dict, 'Invalid migration intent state')
    return value


def _models(state, domain_id):
    from domain_workflow import ledger
    definition = next((d for d in (ledger(state) or {}).get('domains', []) if d['id'] == domain_id), {})
    labels = {domain_id.casefold(), definition.get('name', domain_id).casefold()}
    return {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])
            if e['domain'].casefold() in labels}


def _is_model(entity):
    from design_builder import object_kind
    return object_kind(entity) == 'model'


def _active(state, domain_id):
    from domain_workflow import ledger
    journey = ledger(state)
    if journey:
        require(journey['active_domain_id'] == domain_id, 'Select this domain before changing its intent or assessment')


def _validate_intent(value):
    fields(value, {'schema_version', 'kind', 'domain_id', 'structural_objective', 'behavior',
                   'objectives', 'source_roles', 'behavior_constraints', 'request_reference'})
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['kind'] == 'migration_intent', 'Unsupported migration intent')
    identifier(value['domain_id']); text(value['request_reference'])
    require(value['structural_objective'] in {'refactor', 'preserve', 'new_model'}, 'Invalid structural objective')
    require(value['behavior'] in {'preserve', 'specified_corrections', 'undecided'}, 'Invalid behavior choice')
    _strings(value['behavior_constraints'], 'behavior constraints')
    _list(value['objectives'], 'objectives'); ids([o.get('id') for o in value['objectives']])
    for objective in value['objectives']:
        fields(objective, {'id', 'statement'}, {'kind'})
        identifier(objective['id']); text(objective['statement'])
        require(objective.get('kind', 'general') in {'general', 'eliminate_legacy_dependencies'}, 'Invalid objective kind')
    _list(value['source_roles'], 'source roles', 64); ids([r.get('id') for r in value['source_roles']])
    for role in value['source_roles']:
        fields(role, {'id', 'root_id', 'role'}, {'path_prefix'})
        identifier(role['id']); identifier(role['root_id'])
        require(role['role'] in ROLES, 'Invalid repository evidence role')
        if 'path_prefix' in role:
            safe_relative(role['path_prefix'])
            require(not role['path_prefix'].startswith('@sources/'), 'Role paths are relative to their named root')
    _safe(value)


def configure(state, request):
    """Record the requested outcome; unknown evidence is allowed at intake."""
    from source_roots import _rows
    _validate_intent(request)
    require(type(state.get('workflow')) is dict, 'Adopt stages before configuring migration intent')
    _active(state, request['domain_id'])
    require(request['domain_id'] in _records(state) or len(_records(state)) < 128, 'Too many configured intent domains')
    known = {r['id'] for r in _rows(state)}
    require(all(r['root_id'] in known for r in request['source_roles']), 'Unknown registered source root')
    value = copy.deepcopy(request)
    previous = _records(state).get(value['domain_id'], {})
    record = {'intent': value, 'intent_sha256': hash_json(value)}
    if previous.get('assessment') is not None:
        record['assessment'] = copy.deepcopy(previous['assessment'])
    state['workflow'].setdefault('migration_intents', {})[value['domain_id']] = record
    return summary(state)


def _intent(state, domain_id):
    record = _records(state).get(domain_id)
    if record is None:
        return None
    value = record['intent']; _validate_intent(value)
    require(value['domain_id'] == domain_id and hash_json(value) == record['intent_sha256'], 'Intent integrity differs')
    return value


def _material(state, domain_id):
    from source_roots import _rows
    value = _intent(state, domain_id)
    if value is None:
        return None
    roots = {r['id']: r for r in _rows(state)}
    return {'intent': value, 'root_bindings': {r['id']: hash_json(roots[r['root_id']])
            if r['root_id'] in roots else 'unavailable' for r in value['source_roles']}}


def packet_contract(state, domain_id):
    material = _material(state, domain_id)
    if material is None:
        return None
    value = {'schema_version': 1, 'kind': 'migration_intent_packet', 'domain_id': domain_id,
             **copy.deepcopy(material), 'binding_sha256': hash_json(material),
             'qualification': QUALIFICATION}
    validate_packet_contract(value)
    return value


def validate_packet_contract(contract):
    """Pure shape/hash validation; the coordinator must verify current bindings."""
    fields(contract, {'schema_version', 'kind', 'domain_id', 'intent', 'root_bindings', 'binding_sha256', 'qualification'})
    require(type(contract['schema_version']) is int and contract['schema_version'] == 1
            and contract['kind'] == 'migration_intent_packet', 'Unsupported migration intent packet')
    _validate_intent(contract['intent'])
    require(contract['domain_id'] == contract['intent']['domain_id'], 'Packet domain differs')
    pins = contract['root_bindings']
    require(type(pins) is dict and set(pins) == {r['id'] for r in contract['intent']['source_roles']}, 'Packet root bindings differ')
    require(all(type(v) is str and SHA.fullmatch(v) for v in pins.values()), 'Unavailable packet root identity')
    require(contract['binding_sha256'] == hash_json({k: contract[k] for k in ('intent', 'root_bindings')}), 'Packet intent hash differs')
    require(contract['qualification'] == QUALIFICATION, 'Packet qualification differs')
    require(len(json.dumps(contract, ensure_ascii=False).encode()) <= 32768,
            'Intent packet exceeds 32 KiB; narrow the domain objectives before dispatch')
    return contract


def scope_bindings(state):
    result = {}
    for domain_id in _records(state):
        try:
            pin = hash_json(_material(state, domain_id))
        except (ValueError, OSError, KeyError, TypeError):
            pin = hash_json({'migration_intent': 'unavailable', 'domain_id': domain_id})
        result.update({key: pin for key in _models(state, domain_id)})
    return result


def _source_pins(state, references):
    from source_roots import resolve
    from engagement_stages import _source_hash
    result, total = {}, 0
    for reference in sorted(set(references)):
        try:
            path = resolve(state, reference); info = path.stat(); total += info.st_size
            require(stat.S_ISREG(info.st_mode) and info.st_size <= 4 * 1024 * 1024
                    and total <= 32 * 1024 * 1024, 'Evidence byte bound exceeded')
            result[reference] = _source_hash(state, reference)
        except (ValueError, OSError, KeyError, TypeError):
            result[reference] = 'unavailable'
    return result


def _alignment(state, domain_id):
    import legacy_alignment
    value = state.get('workflow', {}).get('legacy_alignment')
    if not value or domain_id not in value.get('domains', {}):
        return None
    return legacy_alignment._domain_summary(state, domain_id, None)


def _assessment_engine_sha256():
    return hash_file(__file__)


def assessment_bindings(state, domain_id):
    """Current design/source/alignment inputs, excluding authored review output."""
    from engagement_stages import closure
    material = _material(state, domain_id)
    require(material is not None, 'Configure migration intent before assessment')
    doc = state.get('workflow', {}).get('design') or {}
    models = {m['id']: m for m in doc.get('entities', [])}
    owned = _models(state, domain_id)
    scope = closure({k: m['depends_on'] for k, m in models.items()}, list(owned))
    existing = {(m.get('reuse') or {}).get('existing_id') for k, m in models.items() if k in scope}
    decision_ids = {models[k].get('replacement_decision_id') for k in scope}
    decisions = [r for r in doc.get('decisions', []) if r['id'] in decision_ids or set(r.get('model_ids', [])) & set(scope)]
    design = {'id': doc.get('id'), 'models': {k: models[k] for k in sorted(scope)},
              'relationships': [r for r in doc.get('relationships', []) if r['from'] in scope or r['to'] in scope],
              'existing_models': [r for r in doc.get('existing_models', []) if r['id'] in existing],
              'decisions': decisions,
              'responses': [r for r in state.get('workflow', {}).get('responses', [])
                            if r.get('decision_id') in {d['id'] for d in decisions} or set(r.get('model_ids', [])) & set(scope)]}
    sources = _source_pins(state, [p for k in scope for p in models[k]['source_paths']])
    alignment = _alignment(state, domain_id)
    value = {'schema_version': 1, 'domain_id': domain_id, 'intent_binding': hash_json(material),
             'assessment_engine_sha256': _assessment_engine_sha256(),
             'model_ids': sorted(owned), 'design_sha256': hash_json(design), 'source_sha256': sources,
             'alignment_sha256': alignment.get('comparison_sha256') if alignment else None}
    if state.get('workflow', {}).get('design_evidence'):
        from design_evidence import scope_bindings as evidence_bindings
        evidence = evidence_bindings(state)
        value['design_evidence_sha256'] = hash_json({k: evidence[k] for k in sorted(scope) if k in evidence})
    return {**value, 'binding_sha256': hash_json(value)}


def _roles_for(state, intent, reference):
    from source_roots import split_reference
    safe_relative(reference); split_reference(state, reference)
    root_id, relative = (reference.split('/', 2)[1:] if reference.startswith('@sources/') else ('primary', reference))
    return {r['role'] for r in intent['source_roles'] if r['root_id'] == root_id and
            ('path_prefix' not in r or relative == r['path_prefix'] or relative.startswith(r['path_prefix'] + '/'))}


def source_roles_for_reference(state, domain_id, reference):
    """Classify an exact registered reference; roles confer no approval."""
    intent = _intent(state, domain_id)
    return sorted(_roles_for(state, intent, reference)) if intent else []


def _semantic_requested(state):
    answers = state.get('answers', {})
    return answers.get('semantic_target') not in (None, 'none', 'retain_existing') and answers.get('migration_scope') != 'model_only'


def _registered_reuse_evidence(state, key, original, comparisons, refs, pins, cache):
    """Resolve canonical claim IDs through the retained independent baseline."""
    if not state.get('workflow', {}).get('design_evidence'):
        return set(), {}
    import design_evidence as evidence
    from source_roots import resolve
    if 'evidence' not in cache:
        value = evidence.load(state)
        cache.update(evidence={c['id']: c for c in value['claims']},
                     baselines={b['existing_id']: b for b in value['baselines']}, sources=evidence._sources(state))
    baseline = cache['baselines'].get(original.get('id'))
    if baseline is None:
        return set(), {}
    require(baseline['snapshot'] == original, 'Registered reuse baseline differs from the current existing model')
    snapshot = baseline['snapshot_source']; source = cache['sources'].get(snapshot['source_id'])
    require(source and source['role'] == 'existing_models', 'Reuse baseline requires the registered existing-model source')
    path = evidence._reference(source, snapshot)
    from guided_workflow import _nonsecret_json
    from engagement_stages import _pointer
    require(snapshot['locator'].startswith('/') and _pointer(_nonsecret_json(path)[0], snapshot['locator']) == original,
            'Reuse baseline no longer matches its independently captured source')
    paths = {resolve(state, ref): ref for ref in refs}

    def claim_refs(claim_id, dimension=None):
        claim = cache['evidence'].get(claim_id)
        if not claim or key not in claim['model_ids'] or claim.get('baseline_id') != original['id'] or claim['basis'] == 'proposal':
            return set()
        if dimension is not None and claim['subject'] != dimension:
            return set()
        result = set()
        for reference in claim['sources']:
            actual = evidence._claim_reference(cache['sources'], claim, reference)
            matched = paths.get(actual)
            if matched is not None and pins[matched] == reference['sha256']:
                result.add(matched)
        return result

    origins = set()
    for claim_id in set(baseline['claim_ids']) | set(original.get('evidence_refs', [])):
        origins.update(claim_refs(claim_id))
    dimensions = {dimension: set().union(*(claim_refs(ref, dimension) for ref in comparison['evidence_refs']))
                  for dimension, comparison in comparisons.items()}
    return origins, dimensions


def record_assessment(state, request):
    fields(request, {'schema_version', 'domain_id', 'binding_sha256', 'author', 'reviewer', 'review_reference',
                     'status', 'objective_results', 'transitional_dependencies', 'semantic_purpose', 'findings'}, {'legacy_exceptions'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported intent assessment')
    _safe(request); domain = request['domain_id']; _active(state, domain)
    intent = _intent(state, domain); require(intent is not None, 'Configure migration intent first')
    identifier(request['author']); identifier(request['reviewer']); text(request['review_reference'])
    require(request['author'] != request['reviewer'], 'Independent reviewer must differ from the author')
    require(request['status'] in {'accepted', 'changes_requested'}, 'Invalid assessment result')
    pins = assessment_bindings(state, domain)
    require(request['binding_sha256'] == pins['binding_sha256'], 'Assessment inputs are stale')
    objectives = {r['id'] for r in intent['objectives']}
    owned = _models(state, domain)
    models = {k: m for k, m in owned.items() if _is_model(m)}
    entities = {m['id']: m for m in (state['workflow'].get('design') or {}).get('entities', [])}
    graph = {k: m['depends_on'] for k, m in entities.items()}
    from engagement_stages import closure
    supporting = {k: entities[k] for k in closure(graph, list(models)) if _is_model(entities[k])}
    existing = {r['id']: r for r in (state['workflow'].get('design') or {}).get('existing_models', [])}
    exceptions = {}
    for row in _list(request.get('legacy_exceptions', []), 'legacy exceptions'):
        fields(row, {'model_id', 'reason', 'evidence_refs'})
        require(row['model_id'] in supporting and row['model_id'] not in exceptions, 'Unknown or duplicate legacy exception model')
        text(row['reason']); _source_refs(row['evidence_refs'])
        exceptions[row['model_id']] = row
    require(not exceptions or not any(o.get('kind') == 'eliminate_legacy_dependencies' for o in intent['objectives']),
            'Legacy exceptions cannot fulfill an eliminate-legacy objective')
    alignment = _alignment(state, domain)
    mappings = {r['id']: r for r in (alignment or {}).get('mappings', [])}
    rows = _list(request['objective_results'], 'objective results'); ids([r.get('objective_id') for r in rows], objectives)
    covered, evidence_pins, source_roles, provenance_cache, resolved_origins = set(), {}, {}, {}, {}
    for row in rows:
        fields(row, {'objective_id', 'status', 'model_ids', 'source_evidence', 'mapping_ids', 'analysis', 'findings'})
        require(row['status'] in {'addressed', 'unresolved', 'not_met'}, 'Invalid objective result')
        ids(row['model_ids'], models); ids(row['mapping_ids'], mappings); text(row['analysis'])
        _strings(row['findings'], 'objective findings')
        _list(row['source_evidence'], 'source evidence', 64)
        refs = []
        for evidence in row['source_evidence']:
            fields(evidence, {'reference', 'sha256'})
            reference = evidence['reference']; roles = _roles_for(state, intent, reference)
            require(roles, 'Source evidence is outside the declared repository role scopes')
            require(type(evidence['sha256']) is str and SHA.fullmatch(evidence['sha256']), 'Invalid evidence hash')
            require(reference not in refs, 'Duplicate objective source reference'); refs.append(reference)
            require(reference not in evidence_pins or evidence_pins[reference] == evidence['sha256'], 'Conflicting evidence hashes')
            evidence_pins[reference] = evidence['sha256']; source_roles[reference] = roles
        if row['status'] == 'addressed':
            require(row['model_ids'] and refs, 'Addressed objectives require models and original source bytes')
            require(intent['structural_objective'] != 'refactor' or row['mapping_ids'], 'Refactor objectives require alignment mappings')
            if row['mapping_ids']:
                require(alignment and alignment['freshness'] == 'current', 'Current source-to-target alignment is required')
                selected = [mappings[k] for k in row['mapping_ids']]
                require(all(m['status'] == 'mapped' and m['basis'] != 'unassessed' and m['legacy_sources'] for m in selected),
                        'Unresolved mappings cannot fulfill structural objectives')
                targets = {k for m in selected for k in m['model_ids']}
                require(set(row['model_ids']) <= targets <= set(models), 'Objective mappings must cover its models within the domain')
            require(intent['structural_objective'] != 'refactor' or any('legacy_baseline' in source_roles[r] for r in refs),
                    'Refactor assessment needs original baseline source evidence')
            objective_scope = closure(graph, row['model_ids'])
            # Historical final tables map to the assessed target entities. Their
            # supporting raw/staging objects are accounted through the declared
            # DAG, without inventing historical final-table mappings for them.
            for key in sorted(objective_scope):
                model = entities[key]
                if model['disposition'] in {'reuse', 'extend', 'replace'}:
                    comparisons = (model.get('reuse') or {}).get('dimensions', {})
                    require(set(comparisons) == DIMENSIONS, 'Reuse needs every canonical comparison dimension')
                    original = existing.get(model['reuse']['existing_id'], {})
                    original_refs = set(original.get('evidence_refs', [])) & set(refs)
                    registered, dimension_refs = _registered_reuse_evidence(
                        state, key, original, comparisons, refs, evidence_pins, provenance_cache)
                    original_refs.update(registered)
                    resolved_origins.setdefault(key, set()).update(original_refs)
                    target_origins = {r for r in original_refs if 'target_implementation' in source_roles[r]}
                    legacy_origins = {r for r in original_refs if 'legacy_baseline' in source_roles[r]}
                    exception = exceptions.get(key)
                    permitted_legacy = legacy_origins & set((exception or {}).get('evidence_refs', []))
                    require(original_refs and (target_origins or legacy_origins), 'Existing model origin needs pinned original source evidence')
                    if model['disposition'] == 'reuse':
                        require(target_origins or permitted_legacy, 'Legacy reuse needs an explicit exception pinned to its actual source origin')
                    else:
                        require(any('target_implementation' in source_roles[r] for r in refs), 'Changed-model evaluation needs target implementation evidence')
                    for dimension, comparison in comparisons.items():
                        allowed = {'compatible'} if model['disposition'] == 'reuse' else {'compatible', 'change_required'}
                        referenced = (set(comparison['evidence_refs']) & set(refs)) | dimension_refs.get(dimension, set())
                        require(comparison['status'] in allowed and referenced & original_refs,
                                'Reuse comparisons need current original source evidence, not copied hashes or unexplained labels')
            covered.update(objective_scope)
    require(_source_pins(state, evidence_pins) == evidence_pins, 'Assessment source bytes differ or are unavailable')
    for row in _list(request['transitional_dependencies'], 'transitional dependencies'):
        fields(row, {'model_id', 'reason', 'resolution'}); require(row['model_id'] in supporting, 'Unknown transitional model')
        text(row['reason']); text(row['resolution'])
    ids([r['model_id'] for r in request['transitional_dependencies']])
    all_refs = set(evidence_pins)
    for row in exceptions.values():
        _source_refs(row['evidence_refs'], all_refs)
        model = supporting[row['model_id']]
        original = existing.get((model.get('reuse') or {}).get('existing_id'), {})
        origins = set(model['source_paths']) | set(original.get('evidence_refs', [])) | resolved_origins.get(row['model_id'], set())
        require(any(r in origins and 'legacy_baseline' in source_roles[r] for r in row['evidence_refs']),
                'Legacy exception must pin this model original legacy source')
    assets = {a for m in models.values() for a in m['asset_ids']}
    purposes = assets | set(mappings) | {k + '.' + c['name'] for k, m in models.items() for c in m['columns']}
    for row in _list(request['semantic_purpose'], 'semantic purposes'):
        fields(row, {'model_ids', 'topic_ids', 'consumer_or_metric_refs', 'evidence_refs'})
        ids(row['model_ids'], models, True); ids(row['topic_ids'], nonempty=True)
        ids(row['consumer_or_metric_refs'], purposes, True); _source_refs(row['evidence_refs'], all_refs)
    _strings(request['findings'], 'assessment findings')
    if request['status'] == 'accepted':
        require(objectives and {r['objective_id'] for r in rows} == objectives and all(r['status'] == 'addressed' for r in rows),
                'Every structural objective must be addressed')
        require(models and set(owned) <= covered, 'Assessment must account for every in-domain object')
        require(not request['findings'] and not any(r['findings'] for r in rows), 'Unresolved findings cannot be accepted')
    value = copy.deepcopy(request)
    _records(state)[domain]['assessment'] = {'request': value, 'request_sha256': hash_json(value), 'source_sha256': evidence_pins}
    return summary(state)


def _domain_summary(state, domain_id):
    intent = _intent(state, domain_id); models = _models(state, domain_id)
    record = _records(state)[domain_id].get('assessment'); gaps = []
    pins = assessment_bindings(state, domain_id)
    if not intent['objectives']: gaps.append('structural_objectives_missing')
    if not intent['source_roles']: gaps.append('repository_roles_missing')
    if intent['behavior'] == 'undecided': gaps.append('behavior_policy_undecided')
    if not models: gaps.append('design_scope_missing')
    status = 'unassessed'; request = None
    if record:
        request = record['request']
        fresh = (hash_json(request) == record['request_sha256'] and
                 request['binding_sha256'] == pins['binding_sha256'] and
                 _source_pins(state, record['source_sha256']) == record['source_sha256'])
        status = request['status'] if fresh else 'stale'
        if not fresh: gaps.append('assessment_stale')
    else:
        gaps.append('architecture_assessment_missing')
    if request:
        addressed = {r['objective_id'] for r in request['objective_results'] if r['status'] == 'addressed'}
        if addressed != {o['id'] for o in intent['objectives']}: gaps.append('objectives_unaddressed')
        if request['findings'] or any(r['findings'] for r in request['objective_results']): gaps.append('review_findings_open')
        if request['transitional_dependencies']:
            gaps.append('transitional_dependencies_outstanding')
            if any(o.get('kind') == 'eliminate_legacy_dependencies' for o in intent['objectives']):
                gaps.append('legacy_dependency_elimination_incomplete')
    if 'unavailable' in pins['source_sha256'].values(): gaps.append('scoped_source_bytes_unavailable')
    alignment = _alignment(state, domain_id)
    if intent['structural_objective'] == 'refactor':
        if not alignment or alignment['freshness'] != 'current' or alignment['baseline_status'] != 'complete':
            gaps.append('baseline_alignment_unavailable_or_incomplete')
        elif not alignment.get('coverage', {}).get('tables', {}).get('total') or any(
                c.get('unmatched', 0) or c.get('unsupported', 0) for c in alignment.get('coverage', {}).values()):
            gaps.append('source_to_target_coverage_incomplete')
    if _semantic_requested(state):
        expected = {k for k, m in models.items() if _is_model(m) and m['layer'] == 'gold'}
        covered = {k for r in (request or {}).get('semantic_purpose', []) for k in r['model_ids']}
        if expected - covered: gaps.append('semantic_purpose_unassessed')
    if status == 'accepted' and gaps: status = 'partial'
    return {'domain_id': domain_id, 'status': status, 'intent_sha256': hash_json(intent),
            'structural_objective': intent['structural_objective'], 'behavior': intent['behavior'],
            'model_ids': sorted(models), 'objective_ids': [r['id'] for r in intent['objectives']],
            'source_roles': [{'id': r['id'], 'root_id': r['root_id'], 'role': r['role']} for r in intent['source_roles']],
            'gaps': sorted(set(gaps)), 'transitional_dependency_count': len((request or {}).get('transitional_dependencies', [])),
            'legacy_exception_count': len((request or {}).get('legacy_exceptions', [])),
            'legacy_exception_model_ids': [r['model_id'] for r in (request or {}).get('legacy_exceptions', [])] if status == 'accepted' else [],
            'model_disposition_counts': {d: sum(_is_model(m) and m['disposition'] == d for m in models.values())
                                         for d in ('create', 'reuse', 'extend', 'replace', 'undetermined')},
            'semantic_purpose_count': len((request or {}).get('semantic_purpose', [])),
            'refactor_complete': intent['structural_objective'] == 'refactor' and status == 'accepted' and not gaps,
            'review_authority': 'host_attributed_not_authenticated'}


def summary(state, selected=None):
    allowed = set(selected) if selected is not None else None
    rows = []
    for domain in sorted(_records(state)):
        model_ids = set(_models(state, domain))
        if allowed is not None and (not model_ids or not model_ids <= allowed):
            continue
        try:
            row = _domain_summary(state, domain)
            if allowed is not None:
                row['legacy_exception_model_ids'] = [k for k in row['legacy_exception_model_ids'] if k in allowed]
            rows.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            rows.append({'domain_id': domain, 'status': 'stale', 'model_ids': sorted(model_ids),
                         'structural_objective': (_records(state)[domain].get('intent') or {}).get('structural_objective'),
                         'gaps': ['intent_evidence_unavailable'], 'refactor_complete': False})
    return {'schema_version': 1, 'status': 'recorded' if rows else 'unassessed', 'domains': rows,
            'qualification': QUALIFICATION, 'native_validation': 'not_established', 'business_acceptance': 'not_established'}


def require_complete(state, selected=None):
    """Only a full-refactor completion claim uses this gate; drafts never do."""
    value = summary(state, selected)
    # Public subset projection omits entire shared domains. That omission must
    # never become a completion bypass for an overlapping requested scope.
    allowed = set(selected) if selected is not None else None
    incomplete = [r['domain_id'] for r in summary(state)['domains'] if r.get('structural_objective') == 'refactor'
                  and (allowed is None or set(r['model_ids']) & allowed) and not r['refactor_complete']]
    require(not incomplete, 'Refactor completion lacks current objective evidence for: ' + ', '.join(incomplete)
            + '. Provisional authoring and incomplete checkpoint export remain available.')
    return value
