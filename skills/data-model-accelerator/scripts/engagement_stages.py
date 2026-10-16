"""Versioned stage contracts, scoped review and conservative task reuse.

This coordinator does not generate SQL, execute input code, or deploy anything.
Host specialists perform planned work; registered outputs retain their assurance.
Design review is attributed by the host or verified by an external signer.
Host-reported review opens local candidate preparation, never deployment authority.
"""
import copy
import hashlib
from pathlib import Path
import re

from ae_common import hash_json, require, safe_relative

STAGES = ('design', 'implementation', 'semantic', 'validation', 'packaging', 'deployment')
SHA = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z')
DIMENSIONS = {'grain', 'keys', 'definitions', 'history', 'security', 'dependencies'}
COMPONENT_FILES = {
    'workflow': ('scripts/engagement_stages.py',),
    'design': ('references/modeling-and-validation.md', 'references/semantic-placement.md'),
    'implementation': ('references/analytics-engineering.md', 'scripts/plan_refactor.py'),
    'semantic': ('scripts/omni_modeler.py', 'references/omni-modeler.md'),
    'validation': ('references/modeling-and-validation.md', 'scripts/verify_refactor_run.py'),
    'packaging': ('scripts/delivery_portal.py', 'scripts/finalize_delivery.py', 'assets/guided-delivery/portal.js',
                  'assets/guided-delivery/portal.css', 'assets/guided-delivery/portal.html'),
    'deployment': ('scripts/deployment_workflow.py', 'scripts/deployment_authority.py'),
    'dbt_runtime': ('scripts/dbt_runtime.py', 'scripts/dbt_compatibility.py',
                    'scripts/dbt_feature_delivery.py', 'scripts/dbt_information_schema.py',
                    'scripts/dbt_native_lint.py', 'scripts/run_dbt_project.py',
                    'scripts/verify_dbt_evidence.py',
                    'scripts/requirements-dbt-v2.txt', 'scripts/requirements-dbt-oss.txt',
                    'scripts/requirements-dbt-metadata.txt',
                    'references/dbt-runtime.md'),
}


def fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional),
            'Invalid fields; expected ' + ', '.join(sorted(required)))


def identifier(value):
    require(type(value) is str and ID.fullmatch(value), 'Invalid stable identifier')
    return value


def text(value):
    require(type(value) is str and value.strip() and len(value) <= 8000, 'Expected bounded nonempty text')
    return value


def ids(value, allowed=None, nonempty=False):
    require(type(value) is list and (value or not nonempty), 'Expected identifier list')
    result = [identifier(x) for x in value]
    require(len(set(result)) == len(result), 'Duplicate identifiers')
    require(allowed is None or set(result) <= set(allowed), 'Unknown identifier in scope or dependency')
    return result


def empty_workflow():
    return {'schema_version': 1, 'design': None, 'approvals': [], 'responses': [],
            'tasks': [], 'runs': [], 'effort': None, 'migration': 'new', 'last_plan': None}


def migrate(state):
    """Explicitly adopt legacy discovery; never reconstruct missing approvals."""
    require('workflow' not in state, 'Engagement already uses stages')
    state['workflow'] = empty_workflow()
    state['workflow']['migration'] = 'legacy_adopted_without_approval'


def workflow(state):
    require('workflow' in state, 'Legacy engagement: run migrate-stages before using stage commands')
    return state['workflow']


def design(state):
    result = workflow(state)['design']
    require(result is not None, 'Import a design before continuing')
    return result


def closure(graph, selected):
    result = set(selected)
    pending = list(result)
    while pending:
        for parent in graph[pending.pop()]:
            if parent not in result:
                result.add(parent)
                pending.append(parent)
    return sorted(result)


def waves(graph):
    remaining = {k: set(v) for k, v in graph.items()}
    result = []
    while remaining:
        ready = sorted(k for k, v in remaining.items() if not v)
        require(ready, 'Dependency cycle')
        result.extend(ready)
        for key in ready:
            del remaining[key]
        for values in remaining.values():
            values.difference_update(ready)
    return result


def validate_design(value):
    fields(value, {'schema_version', 'id', 'revision', 'entities', 'relationships', 'assets', 'decisions', 'existing_models'})
    require(type(value['schema_version']) is int and value['schema_version'] == 1, 'Unsupported design schema')
    identifier(value['id'])
    require(type(value['revision']) is int and value['revision'] > 0, 'Design revision must be positive')
    for name in ('entities', 'relationships', 'assets', 'decisions', 'existing_models'):
        require(type(value[name]) is list and len(value[name]) <= 20000 and all(type(v) is dict for v in value[name]), name + ' must be a bounded object list')
    require(value['entities'], 'Design requires entities')
    entity_ids = ids([e.get('id') for e in value['entities']], nonempty=True)
    asset_ids = ids([a.get('id') for a in value['assets']])
    existing_ids = ids([m.get('id') for m in value['existing_models']])
    decision_ids = ids([d.get('id') for d in value['decisions']])
    for asset in value['assets']:
        fields(asset, {'id', 'name', 'kind', 'mapping_status'}, {'evidence_refs'})
        text(asset['name']); text(asset['kind'])
        require(asset['mapping_status'] in {'verified', 'inferred', 'unmapped'}, 'Invalid asset mapping status')
    for existing in value['existing_models']:
        fields(existing, {'id', 'name', 'grain', 'keys', 'definitions', 'history', 'security', 'dependencies', 'evidence_refs'})
        for key in ('name', 'grain', 'definitions', 'history', 'security'):
            text(existing[key])
        ids(existing['keys']); ids(existing['dependencies']); ids(existing['evidence_refs'], nonempty=True)
    for entity in value['entities']:
        fields(entity, {'id', 'name', 'domain', 'layer', 'grain', 'keys', 'columns', 'depends_on',
                        'asset_ids', 'security', 'history', 'disposition', 'reuse', 'source_paths', 'catalogue_pointers'},
               {'description', 'display_label', 'replacement_decision_id', 'mapping_status'})
        for key in ('name', 'domain', 'layer', 'grain', 'security', 'history'):
            text(entity[key])
        require(entity['layer'] in {'bronze', 'silver', 'gold'}, 'Use a canonical refinement tier; preserve physical naming separately')
        require(entity.get('mapping_status', 'inferred') in {'verified', 'inferred', 'unmapped'}, 'Invalid entity asset mapping status')
        ids(entity['keys']); ids(entity['depends_on'], entity_ids); ids(entity['asset_ids'], asset_ids)
        require(type(entity['columns']) is list and len(entity['columns']) <= 20000, 'Columns must be a bounded list')
        column_names = []
        for column in entity['columns']:
            fields(column, {'name', 'type', 'description'}, {'key', 'nullable'})
            for key in ('name', 'type', 'description'):
                text(column[key])
            column_names.append(column['name'])
        require(len(set(column_names)) == len(column_names) and set(entity['keys']) <= set(column_names),
                'Duplicate columns or keys outside the entity columns')
        require(type(entity['source_paths']) is list and type(entity['catalogue_pointers']) is list, 'Invalid input slices')
        for path in entity['source_paths']:
            safe_relative(path)
        for pointer in entity['catalogue_pointers']:
            require(type(pointer) is str and (pointer == '' or pointer.startswith('/')), 'Invalid catalogue JSON pointer')
        require(entity['disposition'] in {'reuse', 'extend', 'create', 'replace', 'undetermined'}, 'Invalid model disposition')
        if entity['disposition'] in {'reuse', 'extend', 'replace'}:
            reuse = entity['reuse']
            fields(reuse, {'existing_id', 'dimensions', 'rationale'})
            require(reuse['existing_id'] in existing_ids, 'Reuse target is not inventoried')
            text(reuse['rationale'])
            require(type(reuse['dimensions']) is dict and set(reuse['dimensions']) == DIMENSIONS,
                    'Reuse comparison must cover grain, keys, definitions, history, security and dependencies')
            for comparison in reuse['dimensions'].values():
                fields(comparison, {'status', 'evidence_refs', 'explanation'})
                require(comparison['status'] in {'compatible', 'change_required', 'unknown'}, 'Invalid compatibility result')
                ids(comparison['evidence_refs']); text(comparison['explanation'])
            if entity['disposition'] == 'replace':
                require(entity.get('replacement_decision_id') in decision_ids, 'Replacement needs an explicit decision')
        else:
            require(entity['reuse'] is None, 'Create/undetermined cannot assert a reuse binding')
    waves({e['id']: e['depends_on'] for e in value['entities']})
    for edge in value['relationships']:
        fields(edge, {'from', 'to', 'kind'}, {'label', 'predicate', 'cardinality', 'role', 'evidence', 'status'})
        require(edge['from'] in entity_ids and edge['to'] in entity_ids, 'Unknown relationship endpoint')
        require(edge['kind'] in {'lineage', 'relationship'}, 'Relationship kind must be lineage or relationship')
    for decision in value['decisions']:
        fields(decision, {'id', 'question', 'options', 'recommendation', 'reviewer_role', 'model_ids',
                          'asset_ids', 'blocking_stages', 'rationale', 'evidence_summary'})
        for key in ('question', 'reviewer_role', 'rationale', 'evidence_summary'):
            text(decision[key])
        ids(decision['model_ids'], entity_ids, nonempty=True); ids(decision['asset_ids'], asset_ids)
        ids(decision['blocking_stages'], STAGES)
        require(type(decision['options']) is list, 'Decision options must be a list')
        ids([o.get('id') for o in decision['options']])
        for option in decision['options']:
            fields(option, {'id', 'label'}); text(option['label'])
        require(decision['recommendation'] is None or type(decision['recommendation']) is str, 'Invalid recommendation')
    return copy.deepcopy(value)


def import_design(state, value):
    value = validate_design(value)
    old = workflow(state)['design']
    if old:
        require(value['id'] == old['id'] and value['revision'] > old['revision'],
                'Keep design identity and advance its revision')
    value['sha256'] = hash_json(value)
    workflow(state)['design'] = value
    workflow(state)['last_plan'] = None
    return value


def _pointer(value, pointer):
    for part in pointer.split('/')[1:] if pointer else []:
        key = part.replace('~1', '/').replace('~0', '~')
        if type(value) is list:
            require(key.isdigit() and int(key) < len(value), 'Catalogue slice is unavailable')
            value = value[int(key)]
        else:
            require(type(value) is dict and key in value, 'Catalogue slice is unavailable')
            value = value[key]
    return value


def _source_hash(state, relative):
    import guided_workflow as guided
    path = guided._path(Path(state['inputs']['source']['path']) / safe_relative(relative))
    root = guided._path(state['inputs']['source']['path'])
    require(root in path.parents, 'Source slice escapes input repository')
    require(not any(p.name.lower() in guided.SECRET_FILES or p.name.lower().startswith('.env')
                    or guided.SECRET_PATH.search(p.name) or p.suffix.lower() in {'.key', '.pem', '.p12', '.pfx'}
                    for p in path.relative_to(root).parents) and
            path.name.lower() not in guided.SECRET_FILES and not guided.SECRET_PATH.search(path.name)
            and not path.name.lower().startswith('.env') and path.suffix.lower() not in {'.key', '.pem', '.p12', '.pfx'},
            'Credential files cannot be source slices')
    from deployment_workflow import _stable_bytes
    return hashlib.sha256(_stable_bytes(path)).hexdigest()


def component_versions():
    root = Path(__file__).resolve().parents[1]
    result = {name: hash_json({path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                            if (root / path).is_file() else 'unavailable' for path in paths})
            for name, paths in COMPONENT_FILES.items()}
    classified = {path for paths in COMPONENT_FILES.values() for path in paths}
    # Unknown impact (parser, generator, security policy or prompt changes) is
    # conservative. Explicit presentation-only files stay in packaging's pin.
    remaining = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for folder in ('scripts', 'references', 'agents', 'assets')
                 for p in (root / folder).rglob('*')
                 if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts
                 and p.suffix != '.pyc' and p.name != '.DS_Store'
                 and str(p.relative_to(root)) not in classified}
    remaining['SKILL.md'] = hashlib.sha256((root / 'SKILL.md').read_bytes()).hexdigest()
    result['workflow'] = hash_json({'core': result['workflow'], 'unclassified': remaining})
    for stage, suffix in zip(STAGES, ('design', 'implement', 'semantic', 'validate', 'package', 'deploy')):
        entry = root.parent / ('data-model-' + suffix) / 'SKILL.md'
        result[stage] = hash_json({'core': result[stage], 'entrypoint': hashlib.sha256(entry.read_bytes()).hexdigest()
                                  if entry.is_file() else 'unavailable'})
    return result


def _decision_stage(decision, doc):
    """Unknown scope and replacement decisions conservatively affect the design."""
    if any(e.get('replacement_decision_id') == decision['id'] for e in doc['entities']):
        return 'design'
    blocked = decision['blocking_stages']
    return min(blocked, key=STAGES.index) if blocked else 'design'


def _decision_applies(decision, doc, stage):
    # Implementation choices also belong in physical design review. Other stages
    # inherit earlier decisions, while semantic-only changes leave physical work.
    limit = max(STAGES.index(stage), STAGES.index('implementation'))
    return STAGES.index(_decision_stage(decision, doc)) <= limit


def entity_bindings(state, selected, *, presentation=False, stage=None, _cache=None):
    require(stage is None or stage in STAGES, 'Unknown binding stage')
    doc = design(state)
    entities = {e['id']: e for e in doc['entities']}
    selected = closure({k: v['depends_on'] for k, v in entities.items()}, ids(selected, entities, True))
    result = {}
    cache = _cache if _cache is not None else {}
    import guided_workflow as guided
    catalogue = state['inputs']['catalogue']
    if 'catalogue_data' not in cache:
        cache['catalogue_data'] = guided._nonsecret_json(catalogue['path'])[0] if catalogue and catalogue.get('available') else None
    catalogue_data = cache['catalogue_data']
    for key in selected:
        cache_key = ('entity', presentation, stage, key)
        if cache_key in cache:
            result[key] = cache[cache_key]
            continue
        entity = copy.deepcopy(entities[key])
        if not presentation:
            entity.pop('display_label', None)
            entity.pop('asset_ids', None)
        for path in entity['source_paths']:
            if ('source', path) not in cache:
                cache[('source', path)] = _source_hash(state, path)
        inputs = {'source': {p: cache[('source', p)] for p in entity['source_paths']}
                  if entity['source_paths'] else state['inputs']['source']['fingerprint'],
                  'catalogue': {p: _pointer(catalogue_data, p) for p in entity['catalogue_pointers']}
                  if entity['catalogue_pointers'] and catalogue_data is not None else catalogue}
        edges = [r for r in doc['relationships'] if key in (r['from'], r['to'])]
        decisions = [d for d in doc['decisions'] if key in d['model_ids'] and
                     (stage is None or presentation or _decision_applies(d, doc, stage))]
        responses = [r for r in workflow(state)['responses'] if any(r['decision_id'] == d['id'] and
                     r['decision_sha256'] == hash_json(d) for d in decisions)]
        existing = next((m for m in doc['existing_models'] if entity['reuse'] and m['id'] == entity['reuse']['existing_id']), None)
        result[key] = hash_json({'entity': entity, 'inputs': inputs, 'relationships': edges,
                                'decisions': decisions, 'responses': responses, 'existing': existing})
        cache[cache_key] = result[key]
    return result


def review_bindings(state, selected):
    doc = design(state)
    cache = {}
    return {'engagement_id': state['engagement_id'], 'operation': 'design_review',
            'design_id': doc['id'], 'design_revision': doc['revision'],
            'entities': entity_bindings(state, selected, stage='implementation', _cache=cache),
            'stage_entities': {stage: entity_bindings(state, selected, stage=stage, _cache=cache) for stage in STAGES},
            'target_sha256': state['inputs']['target']['sha256'],
            'discovery_sha256': state['inputs']['discovery']['sha256']}


def record_responses(state, request):
    fields(request, {'schema_version', 'kind', 'intent', 'engagement_id', 'design_id', 'design_revision',
                     'design_sha256', 'answers', 'request_only'})
    doc = design(state)
    require(request['schema_version'] == 1 and request['kind'] == 'decision_responses' and
            request['intent'] == 'record_answers' and request['request_only'] is True, 'Answers are requests, never approval')
    require(request['engagement_id'] == state['engagement_id'] and request['design_id'] == doc['id'] and
            request['design_revision'] == doc['revision'] and request['design_sha256'] == doc['sha256'],
            'Decision response is stale or belongs to another engagement')
    require(type(request['answers']) is list and request['answers'], 'No answers supplied')
    decisions = {d['id']: d for d in doc['decisions']}
    ids([a.get('decision_id') for a in request['answers']], decisions, True)
    new = []
    for answer in request['answers']:
        fields(answer, {'decision_id', 'answer', 'option_id', 'rationale'})
        text(answer['answer'])
        require(type(answer['rationale']) is str and len(answer['rationale']) <= 8000, 'Invalid answer rationale')
        decision = decisions[answer['decision_id']]
        require(answer['option_id'] is None or answer['option_id'] in {o['id'] for o in decision['options']}, 'Unknown answer option')
        new.append({**answer, 'decision_sha256': hash_json(decision)})
    previous = workflow(state)['responses']
    workflow(state)['responses'] = [r for r in previous if r['decision_id'] not in {a['decision_id'] for a in new}] + new


def _design_gaps(state, selected, stage='design'):
    doc = design(state)
    entities = {e['id']: e for e in doc['entities']}
    scope = closure({k: v['depends_on'] for k, v in entities.items()}, selected)
    gaps = []
    for key in scope:
        entity = entities[key]
        if not entity['keys'] or not entity['columns'] or any(entity[k].lower() in {'unknown', 'tbd', 'unresolved'} for k in ('grain', 'security', 'history')):
            gaps.append(key + ': resolve grain, keys, columns, history and security')
        if entity['disposition'] == 'undetermined':
            gaps.append(key + ': choose reuse, extend, create or reviewed replacement')
        if entity['reuse']:
            for dimension, comparison in entity['reuse']['dimensions'].items():
                if not comparison['evidence_refs'] or comparison['status'] == 'unknown' or (entity['disposition'] == 'reuse' and comparison['status'] != 'compatible'):
                    gaps.append(key + ': unresolved reuse comparison ' + dimension)
    answers = {r['decision_id']: r for r in workflow(state)['responses']}
    for decision in doc['decisions']:
        replacement = any(entities[e].get('replacement_decision_id') == decision['id'] for e in scope)
        if (set(decision['model_ids']) & set(scope)) and (stage in decision['blocking_stages'] or replacement):
            if decision['id'] not in answers or answers[decision['id']]['decision_sha256'] != hash_json(decision):
                gaps.append(decision['id'] + ': answer required before ' + stage)
    return gaps


def approve_design(state, selected, policy_path, envelope):
    from deployment_authority import load_policy, verify_attestation
    selected = ids(selected, [e['id'] for e in design(state)['entities']], True)
    require(state['readiness']['generation_ready'], 'Resolve catalogue and discovery prerequisites')
    gaps = _design_gaps(state, selected)
    require(not gaps, '; '.join(gaps))
    policy, policy_hash = load_policy(policy_path, excluded_roots=(state['inputs']['source']['path'],))
    require(policy['mode'] == 'live', 'Simulation approvals cannot open a real design scope')
    bindings = review_bindings(state, selected)
    payload = verify_attestation(envelope, policy, purpose='model_signoff', bindings=bindings)
    entry = {'assurance': 'signature_verified', 'bindings': bindings, 'policy_path': str(Path(policy_path).absolute()), 'policy_sha256': policy_hash,
             'envelope': copy.deepcopy(envelope), 'review_reference': payload['review_reference']}
    require(all(a.get('envelope', {}).get('payload', {}).get('id') != payload['id'] for a in workflow(state)['approvals']), 'Approval already recorded')
    workflow(state)['approvals'].append(entry)


def record_design_review(state, selected, request):
    """Record an actual human decision relayed by the trusted host.

    The runtime checks scope and freshness, not the referenced conversation's
    identity or contents. Host instructions require direct human authorization;
    generated files and source-repository claims never supply it.
    """
    fields(request, {'schema_version', 'kind', 'decision', 'reviewer', 'review_reference', 'bindings'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1
            and request['kind'] == 'human_design_review' and request['decision'] == 'approve', 'Invalid human review record')
    text(request['reviewer']); text(request['review_reference'])
    require(state['readiness']['generation_ready'], 'Resolve catalogue and discovery prerequisites')
    gaps = _design_gaps(state, selected)
    require(not gaps, '; '.join(gaps))
    bindings = review_bindings(state, selected)
    require(request['bindings'] == bindings, 'Human review is stale or does not match the selected design scope')
    entry = {'assurance': 'host_reported_human_review', 'bindings': bindings,
             'reviewer': request['reviewer'], 'review_reference': request['review_reference'],
             'review_sha256': hash_json(request),
             'qualification': 'Human decision attributed by the host; identity and conversation are not independently authenticated. Local candidate preparation only.'}
    require(all(a.get('review_sha256') != entry['review_sha256'] for a in workflow(state)['approvals']), 'Approval already recorded')
    workflow(state)['approvals'].append(entry)


def _current_reviews(state, *, stage='implementation', _cache=None):
    require(stage in STAGES, 'Unknown review stage')
    from deployment_authority import load_policy, verify_attestation
    reviews = []
    for approval in workflow(state)['approvals']:
        try:
            if approval.get('assurance') == 'host_reported_human_review':
                text(approval['reviewer']); text(approval['review_reference'])
                require(approval['review_sha256'] == hash_json({'schema_version': 1, 'kind': 'human_design_review',
                    'decision': 'approve', 'reviewer': approval['reviewer'], 'review_reference': approval['review_reference'],
                    'bindings': approval['bindings']}), 'Human review record changed')
            else:
                policy, policy_hash = load_policy(approval['policy_path'], excluded_roots=(state['inputs']['source']['path'],))
                require(policy_hash == approval['policy_sha256'] and policy['mode'] == 'live', 'Approval policy changed')
                verify_attestation(approval['envelope'], policy, purpose='model_signoff', bindings=approval['bindings'])
            pins = approval['bindings']
            # Legacy stage records bind all decisions and remain conservative.
            # Never infer narrower approval by changing a stored signed payload.
            pinned_entities = pins['stage_entities'][stage] if 'stage_entities' in pins else pins['entities']
            require(set(pinned_entities) == set(pins['entities']), 'Review stage scope differs')
            current = entity_bindings(state, list(pinned_entities), stage=stage if 'stage_entities' in pins else None, _cache=_cache)
            require(pins['design_id'] == design(state)['id'] and pins['target_sha256'] == state['inputs']['target']['sha256']
                    and pins['discovery_sha256'] == state['inputs']['discovery']['sha256'], 'Approval target or business scope changed')
            approved = set()
            for key in pinned_entities:
                entity = next(e for e in design(state)['entities'] if e['id'] == key)
                parents = closure({e['id']: e['depends_on'] for e in design(state)['entities']}, [key])
                if all(current[p] == pinned_entities.get(p) for p in parents):
                    approved.add(entity['id'])
            if approved:
                reviews.append((approval, approved))
        except (ValueError, OSError, KeyError, TypeError):
            continue
    return reviews


def approved_entities(state, *, stage='implementation', _cache=None):
    return set().union(*(scope for _, scope in _current_reviews(state, stage=stage, _cache=_cache)))


def draft_bindings(state, selected):
    """Bind an explicit draft request without creating a design approval."""
    return {**review_bindings(state, selected), 'operation': 'provisional_code_generation'}


def record_draft_request(state, selected, request):
    fields(request, {'schema_version', 'kind', 'requester', 'request_reference', 'request_text', 'bindings'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1
            and request['kind'] == 'provisional_code_request', 'Invalid provisional code request')
    for key in ('requester', 'request_reference', 'request_text'):
        text(request[key])
    require(state['readiness'].get('provisional_generation_available'),
            'Resolve discovery, source coverage or unsupported-platform blockers before drafting')
    require(request['bindings'] == draft_bindings(state, selected), 'Draft request is stale or has different scope')
    records = workflow(state).setdefault('draft_requests', [])
    digest = hash_json(request)
    require(all(record['request_sha256'] != digest for record in records), 'Draft request already recorded')
    records.append({'request': copy.deepcopy(request), 'request_sha256': digest,
                    'assurance': 'host_reported_user_request',
                    'qualification': 'Provisional files only; not design approval, physical verification or execution authority.'})


def draft_entities(state, stage='implementation'):
    """Return scope with a current attributable request; source claims confer none."""
    if stage not in {'implementation', 'semantic'} or not state['readiness'].get('provisional_generation_available'):
        return set()
    result = set()
    for record in workflow(state).get('draft_requests', []):
        try:
            request = record['request']
            require(record['request_sha256'] == hash_json(request), 'Draft request changed')
            require(request['kind'] == 'provisional_code_request', 'Wrong request kind')
            for field in ('requester', 'request_reference', 'request_text'):
                text(request[field])
            pins = request['bindings']
            require(pins['operation'] == 'provisional_code_generation', 'Not a draft request')
            current = draft_bindings(state, list(pins['entities']))
            require(all(pins[k] == current[k] for k in ('engagement_id', 'design_id', 'target_sha256', 'discovery_sha256')),
                    'Draft request context changed')
            for key in pins['entities']:
                parents = closure({e['id']: e['depends_on'] for e in design(state)['entities']}, [key])
                if all(pins['stage_entities'][stage].get(p) == current['stage_entities'][stage].get(p) for p in parents):
                    result.add(key)
        except (ValueError, OSError, KeyError, TypeError):
            continue
    return result


def generation_mode(state, stage, scope, approved=None):
    if stage not in {'implementation', 'semantic'}:
        return 'reviewed_candidate'
    approved = approved if approved is not None else approved_entities(state, stage=stage)
    reviewed = (state['readiness']['generation_ready'] and set(scope) <= approved
                and not _design_gaps(state, scope, stage))
    return 'provisional' if not reviewed and set(scope) <= draft_entities(state, stage) else 'reviewed_candidate'


def require_stage(state, stage, selected, *, _planning=False, _approved=None):
    require(stage in STAGES, 'Unknown stage')
    doc = design(state)
    scope = closure({e['id']: e['depends_on'] for e in doc['entities']}, ids(selected, [e['id'] for e in doc['entities']], True))
    if stage not in {'design', 'packaging'}:
        approved = _approved if _approved is not None else approved_entities(state, stage=stage)
        if generation_mode(state, stage, scope, approved) != 'provisional':
            require(state['readiness']['generation_ready'], 'Discovery or physical prerequisites are incomplete; an explicit user draft request may allow provisional code')
            require(set(scope) <= approved, 'Current recorded human or signed design review is required for this scope')
            gaps = _design_gaps(state, scope, stage)
            require(not gaps, '; '.join(gaps))
    if stage == 'semantic':
        require(state['answers'].get('semantic_target') not in (None, 'none'), 'Semantic delivery is not selected')
    if stage in {'semantic', 'validation'} and not _planning:
        wf = workflow(state)
        require(wf.get('artifact_root') and wf['tasks'], 'Record physical implementation or reused-binding tasks before ' + stage)
        plan = plan_tasks(state, wf['artifact_root'])
        bound = {e for task in plan['tasks'] if task['stage'] == 'implementation' and task['action'] == 'reuse'
                 and (stage != 'validation' or task.get('generation_mode') != 'provisional')
                 for e in task['entity_ids']}
        require(set(scope) <= bound, 'Current physical implementation or reused-binding outputs are required before ' + stage)
    if stage == 'deployment':
        raise ValueError('Use the separate signed deployment workflow; stage selection does not authorize execution')
    return scope


def _code_artifacts(state, task):
    """Minimum native file presence, not syntax, semantics or execution proof."""
    if task['stage'] not in {'implementation', 'semantic'}:
        return []
    native_names = set()
    if task['stage'] == 'implementation':
        entities = {entity['id']: entity for entity in design(state)['entities']}
        reuse_only = all(entities[key]['disposition'] == 'reuse' for key in task['entity_ids'])
        framework = state['answers'].get('framework')
        suffixes = ({'.json', '.yaml', '.yml'} if framework == 'coalesce'
                    else {'.sql', '.py', '.yaml', '.yml'} if framework == 'dbt'
                    else {'.sql', '.sqlx', '.py'})
        if reuse_only:
            suffixes = suffixes | {'.json'}  # Explicit existing-model binding record.
    else:
        if state['answers'].get('semantic_target') == 'omni':
            suffixes = {'.yaml', '.yml', '.view', '.topic'}
            native_names = {'model', 'relationships'}
        else:
            suffixes = {'.yaml', '.yml', '.json', '.sql', '.lkml'}
    paths = [path for path in task['outputs'] if Path(path).suffix.lower() in suffixes or Path(path).name in native_names]
    require(paths, task['stage'] + ' tasks require native code artifacts or explicit reuse bindings; documents alone do not fulfill code requests')
    return paths


def register_tasks(state, request):
    fields(request, {'schema_version', 'tasks'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1 and type(request['tasks']) is list
            and len(request['tasks']) <= 20000 and all(type(t) is dict for t in request['tasks']), 'Invalid stage task plan')
    doc = design(state)
    task_ids = ids([t.get('id') for t in request['tasks']], nonempty=True)
    output_owners = set()
    for task in request['tasks']:
        fields(task, {'id', 'stage', 'entity_ids', 'depends_on', 'components', 'outputs'})
        require(task['stage'] in STAGES and task['stage'] != 'deployment', 'Deployment uses the separate release workflow')
        ids(task['entity_ids'], [e['id'] for e in doc['entities']], True)
        ids(task['depends_on'], task_ids)
        ids(task['components'], COMPONENT_FILES)
        require(type(task['outputs']) is list and task['outputs'], 'Tasks must declare output files')
        for output in task['outputs']:
            safe_relative(output)
            import guided_workflow as guided
            require(not any(p.lower() in guided.SECRET_FILES or p.lower().startswith('.env') or guided.SECRET_PATH.search(p)
                            for p in Path(output).parts)
                    and Path(output).suffix.lower() not in {'.key', '.pem', '.p12', '.pfx'}, 'Credential files cannot be task outputs')
            lower = output.casefold()
            require(not any(lower == p or lower.startswith(p + '/') or p.startswith(lower + '/') for p in output_owners), 'Task outputs overlap')
            output_owners.add(lower)
        if task['stage'] == 'design':
            require(all(Path(p).suffix.lower() in {'.json', '.md', '.svg', '.html', '.csv'} for p in task['outputs']),
                    'Design tasks cannot own implementation code')
        _code_artifacts(state, task)
    by_id = {t['id']: t for t in request['tasks']}
    waves({t['id']: t['depends_on'] for t in request['tasks']})
    for task in request['tasks']:
        require(all(STAGES.index(by_id[p]['stage']) <= STAGES.index(task['stage']) for p in task['depends_on']), 'Stage dependency points backward')
        if task['stage'] in {'semantic', 'validation'}:
            ancestors = closure({t['id']: t['depends_on'] for t in request['tasks']}, [task['id']])
            bound = {e for p in ancestors if by_id[p]['stage'] == 'implementation' for e in by_id[p]['entity_ids']}
            required = closure({e['id']: e['depends_on'] for e in doc['entities']}, task['entity_ids'])
            require(set(required) <= bound, 'Semantic/validation tasks need scoped physical implementation dependencies (including reused bindings)')
    workflow(state)['tasks'] = copy.deepcopy(request['tasks'])
    workflow(state)['last_plan'] = None


def _output_hashes(root, paths):
    import guided_workflow as guided
    from deployment_workflow import _stable_bytes
    root = guided._path(root)
    result = {}
    for relative in paths:
        path = guided._path(root / safe_relative(relative))
        require(root in path.parents, 'Output escapes artifact root')
        result[relative] = hashlib.sha256(_stable_bytes(path)).hexdigest()
    return result


def plan_tasks(state, artifact_root):
    tasks = workflow(state)['tasks']
    require(tasks, 'Register stage tasks first')
    versions = component_versions()
    cache = {}
    approved = {stage: approved_entities(state, stage=stage, _cache=cache) for stage in {t['stage'] for t in tasks}}
    by_id = {t['id']: t for t in tasks}
    results = {}
    for key in waves({t['id']: t['depends_on'] for t in tasks}):
        task = by_id[key]
        reason, fingerprint = None, None
        try:
            _code_artifacts(state, task)
            require_stage(state, task['stage'], task['entity_ids'], _planning=True, _approved=approved[task['stage']])
            material = entity_bindings(state, task['entity_ids'], presentation=task['stage'] in {'design', 'packaging'}, stage=task['stage'], _cache=cache)
            parts = set(task['components']) | {'workflow', task['stage']}
            if task['stage'] != 'design' and state['answers'].get('dbt_runtime'):
                parts.add('dbt_runtime')
            scope = closure({e['id']: e['depends_on'] for e in design(state)['entities']}, task['entity_ids'])
            mode = generation_mode(state, task['stage'], scope, approved[task['stage']])
            # Runtime changes invalidate code and downstream work, not the
            # reviewed entity design. Preserve old fingerprints when unselected.
            runtime_binding = ({'dbt_runtime': state['answers']['dbt_runtime']}
                               if task['stage'] != 'design' and 'dbt_runtime' in state['answers'] else {})
            fingerprint = hash_json({'task': task, 'entities': material,
                **runtime_binding,
                'generation_mode': mode,
                'components': {p: versions[p] for p in sorted(parts)},
                'target': state['inputs']['target'],
                'discovery': state['inputs']['discovery'],
                'environment': state['answers'].get('environment') if task['stage'] == 'validation' else None,
                'selection': {k: state['answers'].get(k) for k in ('deliverables', 'audience')} if task['stage'] == 'packaging' else None,
                'parents': {p: {'fingerprint': results[p]['fingerprint'], 'outputs': results[p].get('outputs')}
                            for p in task['depends_on']}})
        except OSError:
            reason = 'A required input is missing or unreadable; refresh the scoped inventory.'
        except (ValueError, KeyError, TypeError):
            reason = 'Review or input prerequisites are incomplete or stale for this scope; inspect the decisions and stage gate.'
        parents = [p for p in task['depends_on'] if results[p]['action'] != 'reuse']
        action = 'blocked' if reason else 'regenerate'
        if parents and not reason:
            reason = 'Dependencies need completion: ' + ', '.join(parents)
            action = 'blocked'
        original = None
        if not reason:
            reason = 'No matching completed task with current output bytes'
            for run in reversed(workflow(state)['runs']):
                if run['task_id'] != key or run['fingerprint'] != fingerprint:
                    continue
                try:
                    require(_output_hashes(artifact_root, task['outputs']) == run['outputs'], 'Output bytes changed')
                    action, reason, original = 'reuse', 'Inputs, component versions and output bytes match', run
                    break
                except (ValueError, OSError):
                    reason = 'Recorded output is missing or changed'
        results[key] = {'id': key, 'stage': task['stage'], 'entity_ids': task['entity_ids'], 'action': action,
                        'generation_mode': mode if fingerprint is not None else None,
                        'reason': reason, 'fingerprint': fingerprint, 'original_run_id': original['run_id'] if original else None,
                        'outputs': original['outputs'] if original else None}
    return {'schema_version': 1, 'kind': 'stage_execution_plan', 'tasks': list(results.values()),
            'plan_sha256': hash_json(results), 'qualification': 'Dependency plan only; reuse retains original execution assurance.'}


def record_task(state, artifact_root, request):
    fields(request, {'task_id', 'run_id', 'plan_sha256', 'fingerprint', 'outputs', 'evidence_reference'})
    identifier(request['run_id']); text(request['evidence_reference'])
    require(all(r['run_id'] != request['run_id'] for r in workflow(state)['runs']), 'Run ID already recorded')
    plan = plan_tasks(state, artifact_root)
    require(request['plan_sha256'] == plan['plan_sha256'], 'Task plan changed; refresh before recording results')
    task = next((t for t in plan['tasks'] if t['id'] == request['task_id']), None)
    require(task is not None and task['action'] == 'regenerate', 'Task is blocked, unplanned or already reusable')
    require(request['fingerprint'] == task['fingerprint'], 'Task input binding changed')
    specification = next(t for t in workflow(state)['tasks'] if t['id'] == request['task_id'])
    outputs = _output_hashes(artifact_root, specification['outputs'])
    from deployment_workflow import _stable_bytes
    for path in _code_artifacts(state, specification):
        require(_stable_bytes(Path(artifact_root) / path).strip(), 'Native code artifact is empty: ' + path)
    require(request['outputs'] == outputs, 'Output manifest does not match generated files')
    import guided_workflow as guided
    workflow(state)['runs'].append({**copy.deepcopy(request), 'recorded_at': guided._now(),
        'generation_mode': task['generation_mode'],
        'assurance': 'host_reported_file_integrity', 'qualification': 'Output registration is not native validation or deployment approval.'})
    workflow(state)['last_plan'] = plan_tasks(state, artifact_root)


def effort_request(state, supplied):
    """Bind declared complexity factors to the current reviewed model scope."""
    from development_effort import digest
    fields(supplied, {'scope', 'evidence', 'packages'})
    require(type(supplied['packages']) is list and supplied['packages'], 'Effort needs scoped work packages')
    known = [e['id'] for e in design(state)['entities']]
    selected = set()
    bindings, reviewed, cache = {}, True, {}
    packages = copy.deepcopy(supplied['packages'])
    for package in packages:
        selected.update(ids(package.get('model_ids'), known, True))
        require(type(package.get('material_inputs')) is dict, 'Effort material inputs must be a map')
        stage = 'deployment' if package.get('stage') == 'cutover' else package.get('stage')
        require(stage in STAGES, 'Unknown effort stage')
        material = entity_bindings(state, package['model_ids'], stage=stage, _cache=cache)
        for key, value in material.items():
            package['material_inputs']['model:' + key] = value
        bindings[package['id']] = {'stage': stage, 'entities': material}
        reviewed = reviewed and set(material) <= approved_entities(state, stage=stage, _cache=cache)
    return {'schema_version': 1, 'kind': 'development_effort_request',
            'bindings': {'design_revision': str(design(state)['revision']),
                         'design_material_sha256': hash_json(bindings),
                         'scope_sha256': digest(supplied['scope']),
                         'route_sha256': state['inputs']['target']['sha256']},
            'review': {'status': 'reviewed' if reviewed else 'pending',
                       'reference': 'design:' + design(state)['id'] + ':' + hash_json(bindings) if reviewed else None},
            'scope': copy.deepcopy(supplied['scope']), 'evidence': copy.deepcopy(supplied['evidence']), 'packages': packages}


def assess_development(state, supplied):
    from development_effort import assess_effort
    request = effort_request(state, supplied)
    require(request['review']['status'] == 'reviewed', 'Complete the scoped design review before assessing development effort')
    result = assess_effort(request)
    workflow(state)['effort'] = result
    workflow(state)['effort_inputs'] = copy.deepcopy(supplied)
    workflow(state)['effort_freshness'] = None
    return result


def refresh(state):
    if not state.get('workflow') or not state['workflow']['design']:
        return
    wf = workflow(state)
    if wf.get('artifact_root') and wf['tasks']:
        try:
            wf['last_plan'] = plan_tasks(state, wf['artifact_root'])
        except (ValueError, OSError, KeyError, TypeError) as error:
            wf['last_plan'] = None
            wf['refresh_gap'] = str(error)
    if wf.get('effort'):
        from development_effort import refresh_effort
        try:
            wf['effort_freshness'] = refresh_effort(wf['effort'], effort_request(state, wf['effort_inputs']))
        except (ValueError, OSError, KeyError, TypeError) as error:
            wf['effort_freshness'] = {'status': 'stale', 'overall': {'status': 'stale', 'category': None,
                'confidence': 'low'}, 'packages': [], 'qualification': str(error)}


def _requested_progress(state, result):
    """Requested deliverables, not the registered task subset, define remaining work."""
    doc = workflow(state)['design']
    if not doc:
        return
    graph = {e['id']: e['depends_on'] for e in doc['entities']}
    expected = set(graph)
    selections = set(state['answers'].get('deliverables', []))
    code_selected = 'implementation' in selections
    required = ['implementation'] if code_selected else []
    if (code_selected and state['answers'].get('semantic_target') not in (None, 'none', 'retain_existing')
            and state['answers'].get('migration_scope') != 'model_only'):
        required.append('semantic')
    if code_selected or 'validation' in selections:
        required.append('validation')
    tasks = result.get('task_plan', {}).get('tasks', [])
    rows = {row['id']: row for row in result['stages']}
    result['requested_stages'] = required
    result['delivery_status'] = 'requested_outputs_pending'
    if not required and any(task['stage'] == 'design' and task['action'] != 'reuse' for task in tasks):
        result['delivery_status'] = 'design_proposal_pending'
        return
    provisional = False
    for stage in required:
        selected = [task for task in tasks if task['stage'] == stage]
        finished = [task for task in selected if task['action'] == 'reuse']
        # A semantic/validation task may own a fact together with its dependency interfaces.
        covered = set().union(*(set(closure(graph, task['entity_ids'])) if stage != 'implementation'
                                else set(task['entity_ids']) for task in finished))
        missing = sorted(expected - covered)
        provisional = provisional or any(task.get('generation_mode') == 'provisional' for task in finished)
        row = rows[stage]
        stage_provisional = any(task.get('generation_mode') == 'provisional' for task in finished)
        if stage_provisional:
            row['status'] = 'provisional_outputs_recorded' if not missing else 'partial_provisional_outputs'
        if not missing:
            continue
        planned = set().union(*(set(closure(graph, task['entity_ids'])) if stage != 'implementation'
                               else set(task['entity_ids']) for task in selected))
        unplanned = sorted(expected - planned)
        label = 'implementation code' if stage == 'implementation' else 'semantic code' if stage == 'semantic' else 'independent validation'
        if unplanned:
            row['status'] = 'partial_provisional_outputs' if stage_provisional else 'partial_outputs_recorded' if finished else 'not_planned'
            row['next_action'] = 'Plan requested ' + label + ' for: ' + ', '.join(unplanned) + '. Design documents do not fulfill code requests.'
        elif selected:
            row['next_action'] = 'Finish requested ' + label + ' for: ' + ', '.join(missing) + '. ' + row['next_action']
        if stage_provisional:
            row['next_action'] += ' Recorded code remains provisional; physical bindings or design decisions are unverified.'
        if stage in {'implementation', 'semantic'} and not finished:
            eligible_drafts = draft_entities(state, stage)
            if expected <= eligible_drafts:
                row['next_action'] += ' The explicit user request permits provisional files with unverified bindings; it grants no execution authority.'
            elif not approved_entities(state, stage=stage):
                row['next_action'] += ' Record scoped design review, or the user\'s explicit request for provisional code.'
        if stage == 'validation' and provisional:
            row['status'] = 'blocked'
            row['next_action'] = 'Provisional code is recorded. Obtain missing catalogue/binding evidence and design review, then reconcile the drafts before claiming independent validation. Drafts may be packaged with these limits.'
            result['delivery_status'] = 'provisional_code_generated'
        result.update(current_stage=stage, next_action=row['next_action'])
        return
    result.update(current_stage='packaging', delivery_status='design_proposal' if not required else 'provisional_code_generated' if provisional else 'requested_stage_outputs_recorded',
                  next_action='Run finalize_delivery.py to verify the selected files, START_HERE.html and extracted handoff. Registered task outputs are not a completed delivery; package integrity does not establish native validation or acceptance.')


def public_view(state, *, _refresh=True):
    # Recheck bytes and approval lifetime even when a caller renders saved state
    # without invoking the discovery refresher first. Never write from a view.
    state = copy.deepcopy(state)
    if _refresh:
        refresh(state)
    wf = workflow(state)
    doc = wf['design']
    review_records = _current_reviews(state) if doc else []
    approved = set().union(*(scope for _, scope in review_records))
    signed = set().union(*(scope for record, scope in review_records
                           if record.get('assurance') != 'host_reported_human_review'))
    result = {'schema_version': 1, 'engagement_id': state['engagement_id'],
              'design_id': doc['id'] if doc else None, 'design_revision': doc['revision'] if doc else None,
              'design_sha256': doc['sha256'] if doc else None, 'current_stage': 'design',
              'next_action': 'Prepare or import the entity design, then review its scoped decisions.',
              'review_qualification': 'Design review permits local candidate preparation. Host-reported review is not authenticated identity or deployment authorization.',
              'qualification': 'Review recorded means a human decision attributed by the host, not independently authenticated identity. Signature verified means an external issuer signature was checked. Neither authorizes execution or deployment.',
              'stages': [], 'decisions': [], 'models': [], 'relationships': [], 'assets': [], 'effort': None}
    if doc:
        result.update(models=copy.deepcopy(doc['entities']), relationships=doc['relationships'], assets=doc['assets'])
        answers = {r['decision_id']: r for r in wf['responses']}
        decision_reviews = {}
        for decision in doc['decisions']:
            answer = answers.get(decision['id'])
            current = answer and answer['decision_sha256'] == hash_json(decision)
            stage = _decision_stage(decision, doc)
            if stage not in decision_reviews:
                decision_reviews[stage] = approved_entities(state, stage=stage)
            resolved = current and set(decision['model_ids']) <= decision_reviews[stage]
            result['decisions'].append({**decision, 'status': 'resolved' if resolved else 'answer_recorded' if current else 'unresolved',
                                        'answer': answer['answer'] if current else None})
        result['next_action'] = 'Review and approve the exact design scope.' if not approved else 'Assess development effort and plan the selected implementation scope.'
    for stage in STAGES:
        status = 'ready' if stage in {'design', 'packaging'} else 'blocked'
        if approved and stage == 'implementation':
            status = 'ready'
        if stage == 'semantic' and state['answers'].get('semantic_target') == 'none':
            status = 'not_selected'
        if stage == 'design' and doc:
            status = ('signature_verified' if len(signed) == len(doc['entities']) else 'review_recorded') if len(approved) == len(doc['entities']) else 'partially_review_recorded' if approved else 'needs_review'
        result['stages'].append({'id': stage, 'label': stage.replace('_', ' ').title(), 'status': status,
                                'next_action': 'Separate release authorization required' if stage == 'deployment'
                                    else 'Select deliverables and prepare the reviewed package.' if stage == 'packaging' else result['next_action']})
    if wf.get('last_plan'):
        result['task_plan'] = wf['last_plan']
        for row in result['stages']:
            tasks = [t for t in wf['last_plan']['tasks'] if t['stage'] == row['id']]
            if tasks:
                row['status'] = 'outputs_recorded' if all(t['action'] == 'reuse' for t in tasks) else 'blocked' if any(t['action'] == 'blocked' for t in tasks) else 'ready'
                row['next_action'] = '; '.join(t['id'] + ': ' + t['reason'] for t in tasks)
            elif row['id'] in {'semantic', 'validation'} and row['status'] != 'not_selected':
                row['status'] = 'not_planned'
                row['next_action'] = ('Plan independent validation for the selected outputs; native execution remains separately authorized.'
                    if row['id'] == 'validation' else 'Plan the selected semantic artifacts against current physical outputs.')
        pending = next((t for t in wf['last_plan']['tasks'] if t['action'] != 'reuse'), None)
        if pending:
            result.update(current_stage=pending['stage'], next_action=pending['id'] + ': ' + pending['reason'])
        else:
            done = {t['stage'] for t in wf['last_plan']['tasks']}
            next_stage = 'validation' if 'validation' not in done else 'packaging'
            result.update(current_stage=next_stage, next_action='Selected outputs are recorded. Review the artifacts and prepare '
                          + ('independent validation evidence.' if next_stage == 'validation' else 'the selected delivery package.'))
    if wf.get('effort'):
        report = wf['effort']
        fresh = wf.get('effort_freshness')
        overall = fresh['overall'] if fresh else report['overall']
        by_id = {p['id']: p for p in (fresh or {}).get('packages', [])}
        result['effort'] = {'category': overall['category'], 'confidence': overall['confidence'],
            'readiness': overall.get('readiness', overall['status']), 'breadth': str(len(report['packages'])) + ' work packages',
            'summary': report['qualification'], 'rationale': overall.get('rationale', 'Material changes require reassessment.'),
            'included_work': report['scope']['stages'], 'excluded_work': report['scope']['excluded_stages'],
            'work_packages': []}
        for package in report['packages']:
            current = by_id.get(package['id'], {'category': None, 'confidence': 'low', 'status': 'stale',
                'reasons': ['Current effort bindings are unavailable; reassess after resolving prerequisites.']}
                if fresh and fresh['status'] == 'stale' else package)
            result['effort']['work_packages'].append({'id': package['id'], 'model_ids': package['model_ids'],
                'category': current['category'], 'confidence': current['confidence'],
                'readiness': current.get('readiness', current.get('assessment_status') or current['status']),
                'assumptions': package['assumptions'], 'dependencies': package['depends_on'],
                'rationale': '; '.join(current['reasons']) or 'Bounded factors and evidence are recorded.',
                'dimensions': [{'name': d['factor'], 'level': d['level'], 'rationale': d['rationale']} for d in package['drivers']]})
    _requested_progress(state, result)
    return result
