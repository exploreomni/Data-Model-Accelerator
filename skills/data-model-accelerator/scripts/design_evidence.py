"""Scoped design provenance and independent review, separate from human approval.

File hashes prove unchanged supplied bytes, not the truth of an interpretation.
Host-reported identities and model observations are never authenticated here.
Absent companions preserve older engagements; once adopted, gaps stay visible.
"""
import copy
import hashlib
import json

from ae_common import hash_json, require
from engagement_stages import DIMENSIONS, fields, identifier, ids, text
from review_assurance import load_document

BASES = {'observed_metadata', 'repository_declaration', 'user_assertion', 'proposal'}
SUBJECTS = DIMENSIONS | {'columns', 'relationship', 'baseline'}
QUALIFICATION = ('Evidence classifications and independent review are host-reported. Source hashes prove '
                 'local integrity only; they do not authenticate an observation, reviewer, business rule '
                 'or native execution. Proposed and repository-declared fields are not verified raw metadata.')


def _models(state):
    return {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}


def _save(state, key, document, run_dir, pins=None):
    import guided_workflow as guided
    guided._secrets(document)
    raw = json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False,
                     separators=(',', ':')).encode()
    require(len(raw) <= guided.MAX_JSON_BYTES, 'Design evidence exceeds the bounded document limit')
    digest = hashlib.sha256(raw).hexdigest()
    run_dir = guided._path(run_dir)
    folder = run_dir / 'review-evidence'
    primary = state.get('inputs', {}).get('source', {}).get('path')
    if primary:
        guided._outside(run_dir, guided._path(primary))
        guided._outside(folder, guided._path(primary))
    for source in _sources(state).values():
        if source.get('root'):
            guided._outside(run_dir, guided._path(source['root']))
            guided._outside(folder, guided._path(source['root']))
    require(not folder.is_symlink(), 'Evidence directory must not be a symlink')
    folder.mkdir(exist_ok=True)
    path = folder / (digest + '.json')
    ref = {'path': str(path), 'sha256': digest, 'bytes': len(raw)}
    if path.exists():
        require(load_document(ref) == document, 'Stored evidence differs')
    else:
        guided._atomic_write(path, raw, replace=False)
    state['workflow'][key] = {'schema_version': 1, 'document': ref,
                              'scope_bindings': copy.deepcopy(pins or {})}


def load(state):
    record = state.get('workflow', {}).get('design_evidence')
    if record is None:
        return None
    fields(record, {'schema_version', 'document', 'scope_bindings'})
    require(type(record['schema_version']) is int and record['schema_version'] == 1, 'Unsupported design evidence record')
    value = load_document(record['document'])
    fields(value, {'schema_version', 'kind', 'claims', 'baselines'})
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['kind'] == 'design_evidence', 'Unsupported design evidence')
    return value


def _sources(state):
    from design_coverage import load as coverage
    value = coverage(state)
    # Coverage retains its request under a content-addressed document.
    if value is None:
        return {}
    return {s['id']: s for s in value['request']['sources']}


def _reference(source, reference):
    """Resolve only an explicitly registered file, never an agent-invented path."""
    from design_coverage import _root, _relative
    from deployment_workflow import _stable_bytes
    from guided_workflow import _path, MAX_JSON_BYTES
    fields(reference, {'source_id', 'path', 'sha256', 'locator'})
    text(reference['locator'])
    require(source and source['status'] == 'available', 'Evidence source is unavailable or unregistered')
    match = next((f for f in source['inventory']['files'] if f['path'] == reference['path']), None)
    require(match and match['sha256'] == reference['sha256'], 'Evidence reference is not in the registered inventory')
    root = _root(source['root'])
    path = _path(root / _relative(reference['path']))
    require(root in path.parents and path.is_file() and path.stat().st_size <= MAX_JSON_BYTES,
            'Evidence file is missing, outside its root or too large')
    require(hashlib.sha256(_stable_bytes(path)).hexdigest() == reference['sha256'], 'Evidence source bytes changed')
    return path


def _claim_reference(sources, claim, reference):
    source = sources.get(reference.get('source_id'))
    path = _reference(source, reference)
    if claim['basis'] == 'observed_metadata':
        require(source['role'] == 'warehouse_catalogue',
                'Observed physical metadata requires a warehouse_catalogue source, not staging declarations')
    return path


def record(state, request, run_dir):
    fields(request, {'schema_version', 'kind', 'claims', 'baselines'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1
            and request['kind'] == 'design_evidence', 'Unsupported design evidence contract')
    models = _models(state)
    require(models, 'Import the design before recording its evidence')
    sources = _sources(state)
    for key in ('claims', 'baselines'):
        require(type(request[key]) is list and len(request[key]) <= 20000, 'Evidence rows must be bounded lists')
    ids([c.get('id') for c in request['claims']])
    claims = {c['id']: c for c in request['claims']}
    for claim in claims.values():
        fields(claim, {'id', 'model_ids', 'subject', 'basis', 'statement', 'sources'}, {'baseline_id', 'assertion_reference'})
        ids(claim['model_ids'], models, True); text(claim['statement'])
        require(claim['subject'] in SUBJECTS and claim['basis'] in BASES, 'Invalid evidence subject or basis')
        require(type(claim['sources']) is list and len(claim['sources']) <= 2000, 'Evidence sources must be bounded')
        if claim['basis'] in {'observed_metadata', 'repository_declaration'}:
            require(claim['sources'], 'Observed or declared evidence needs registered source references')
        if claim['basis'] == 'user_assertion':
            text(claim.get('assertion_reference'))
        if 'baseline_id' in claim:
            identifier(claim['baseline_id'])
            require(claim['basis'] != 'proposal', 'A proposal cannot establish an existing baseline')
        for ref in claim['sources']:
            _claim_reference(sources, claim, ref)
    existing = {e['id']: e for e in state['workflow']['design']['existing_models']}
    ids([b.get('existing_id') for b in request['baselines']], existing)
    for baseline in request['baselines']:
        fields(baseline, {'existing_id', 'snapshot', 'snapshot_source', 'claim_ids', 'captured_by', 'capture_reference'})
        text(baseline['captured_by']); text(baseline['capture_reference'])
        ids(baseline['claim_ids'], claims, True)
        require(baseline['snapshot'] == existing[baseline['existing_id']], 'Independent baseline differs from canonical existing snapshot')
        ref = baseline['snapshot_source']
        source = sources.get(ref.get('source_id'))
        require(source and source['role'] == 'existing_models', 'Baseline snapshot needs a separately registered existing_models source')
        path = _reference(source, ref)
        from guided_workflow import _nonsecret_json
        from engagement_stages import _pointer
        require(ref['locator'].startswith('/') and
                _pointer(_nonsecret_json(path)[0], ref['locator']) == baseline['snapshot'],
                'Existing baseline must match its captured JSON pointer, not a copy of the proposed target')
        require(all(claims[c].get('baseline_id') == baseline['existing_id'] and
                    claims[c]['basis'] != 'proposal' and claims[c]['sources'] for c in baseline['claim_ids']),
                'Baseline claims require independently captured source evidence; target proposals are insufficient')
    known = {b['existing_id'] for b in request['baselines']}
    require(all(c.get('baseline_id') in known for c in claims.values() if 'baseline_id' in c), 'Unknown independent baseline')
    # Retain removed associations, so withdrawing evidence cannot restore an old approval.
    historical = state['workflow'].get('design_evidence', {}).get('scope_bindings', {})
    pins = {key: hash_json([c for c in claims.values() if key in c['model_ids']])
            for key in set(historical) | {m for c in claims.values() for m in c['model_ids']}}
    _save(state, 'design_evidence', copy.deepcopy(request), run_dir, pins)
    return summarize(state)


def scope_bindings(state):
    record = state.get('workflow', {}).get('design_evidence')
    if record is None:
        return {}
    historical = record.get('scope_bindings', {})
    try:
        value, sources = load(state), _sources(state)
        result = {}
        for key in set(historical) | {m for c in value['claims'] for m in c['model_ids']}:
            claims = [c for c in value['claims'] if key in c['model_ids']]
            freshness = []
            for claim in claims:
                for ref in claim['sources']:
                    try:
                        _claim_reference(sources, claim, ref)
                        freshness.append('current')
                    except (ValueError, OSError, KeyError, TypeError):
                        freshness.append('unavailable')
            baseline_ids = {c.get('baseline_id') for c in claims}
            baselines = [b for b in value['baselines'] if b['existing_id'] in baseline_ids]
            for baseline in baselines:
                try:
                    ref = baseline['snapshot_source']
                    _reference(sources.get(ref['source_id']), ref)
                    freshness.append('current')
                except (ValueError, OSError, KeyError, TypeError):
                    freshness.append('unavailable')
            result[key] = hash_json({'claims': claims, 'baselines': baselines, 'freshness': freshness})
        return result
    except (ValueError, OSError, KeyError, TypeError):
        return {k: 'unavailable:' + v for k, v in historical.items()}


def gaps(state, selected):
    if not state.get('workflow', {}).get('design_evidence'):
        return []
    try:
        value, sources = load(state), _sources(state)
        claims = value['claims']
        result = []
        baselines = {b['existing_id']: b for b in value['baselines']}
        for key in selected:
            model = _models(state)[key]
            own = [c for c in claims if key in c['model_ids']]
            if not own and model.get('object_kind') != 'interface':
                result.append(key + ': classify the design evidence or mark the assumptions as proposals')
            for claim in own:
                for ref in claim['sources']:
                    try:
                        _claim_reference(sources, claim, ref)
                    except (ValueError, OSError, KeyError, TypeError):
                        result.append(key + ': evidence source is missing or changed')
            reuse = model.get('reuse')
            if reuse:
                baseline = baselines.get(reuse['existing_id'])
                current = next((e for e in state['workflow']['design']['existing_models'] if e['id'] == reuse['existing_id']), None)
                if baseline is None or baseline['snapshot'] != current:
                    result.append(key + ': capture an independent current existing-model baseline')
                elif baseline:
                    try:
                        ref = baseline['snapshot_source']
                        require(sources.get(ref['source_id'], {}).get('role') == 'existing_models', 'Baseline source role changed')
                        _reference(sources.get(ref['source_id']), ref)
                    except (ValueError, OSError, KeyError, TypeError):
                        result.append(key + ': independent baseline source changed or is unavailable')
                for dimension in DIMENSIONS:
                    matching = [c for c in own if c.get('baseline_id') == reuse['existing_id'] and
                                c['subject'] == dimension and c['sources'] and c['basis'] != 'proposal'
                                and c['id'] in reuse['dimensions'][dimension]['evidence_refs']]
                    if not matching:
                        result.append(key + ': reuse ' + dimension + ' needs independent evidence')
        return sorted(set(result))
    except (ValueError, OSError, KeyError, TypeError):
        return ['Design provenance is missing, changed or unsupported; re-register it']


def summarize(state, selected=None):
    scope = set(selected) if selected is not None else set(_models(state))
    try:
        value = load(state)
        if value is None:
            return {'status': 'unassessed', 'qualification': QUALIFICATION}
        claims = [c for c in value['claims'] if scope.intersection(c['model_ids'])]
        return {'status': 'gaps' if gaps(state, scope) else 'recorded',
                'counts': {basis: sum(c['basis'] == basis for c in claims) for basis in sorted(BASES)},
                'qualification': QUALIFICATION}
    except (ValueError, OSError, KeyError, TypeError):
        return {'status': 'unavailable', 'qualification': QUALIFICATION}


def review_bindings(state, selected):
    from engagement_stages import entity_bindings, closure
    models = _models(state)
    scope = closure({k: e['depends_on'] for k, e in models.items()}, ids(selected, models, True))
    require(state['workflow'].get('design_coverage') and state['workflow'].get('design_evidence'),
            'Record expected coverage and provenance before independent review')
    return {'engagement_id': state['engagement_id'], 'design_id': state['workflow']['design']['id'],
            'operation': 'independent_design_review',
            'entities': entity_bindings(state, scope, stage='implementation')}


def record_review(state, request, run_dir):
    fields(request, {'schema_version', 'kind', 'reviewer_id', 'author_ids', 'review_reference',
                     'bindings', 'claim_ids', 'findings', 'result', 'execution'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1 and
            request['kind'] == 'independent_design_review', 'Unsupported independent review')
    identifier(request['reviewer_id']); ids(request['author_ids'], nonempty=True); text(request['review_reference'])
    require(request['reviewer_id'] not in request['author_ids'], 'Author cannot supply independent review')
    require(request['bindings'] == review_bindings(state, list(request['bindings'].get('entities', {}))),
            'Independent review is stale or belongs to another scope')
    scope = set(request['bindings']['entities'])
    claims = {c['id']: c for c in load(state)['claims'] if scope.intersection(c['model_ids'])}
    ids(request['claim_ids'], claims)
    require(set(request['claim_ids']) == set(claims), 'Independent reviewer must address the scoped evidence, not just the summary')
    require(type(request['findings']) is list and len(request['findings']) <= 20000, 'Invalid review findings')
    ids([f.get('id') for f in request['findings']])
    for finding in request['findings']:
        fields(finding, {'id', 'model_ids', 'severity', 'status', 'description', 'evidence_reference'})
        ids(finding['model_ids'], scope, True); text(finding['description']); text(finding['evidence_reference'])
        require(finding['severity'] in {'blocking', 'advisory'} and finding['status'] in {'open', 'resolved'}, 'Invalid review finding')
    require(request['result'] in {'accepted', 'changes_requested'}, 'Invalid review result')
    require(request['result'] != 'accepted' or not any(f['severity'] == 'blocking' and f['status'] == 'open'
                                                    for f in request['findings']), 'Open blocking findings cannot be accepted')
    execution = request['execution']
    fields(execution, {'host', 'task_reference', 'context_reference', 'requested_model', 'observed_model',
                       'requested_effort', 'observed_effort'})
    for key in ('host', 'task_reference', 'context_reference'):
        text(execution[key])
    for key in ('requested_model', 'observed_model', 'requested_effort', 'observed_effort'):
        require(execution[key] is None or (type(execution[key]) is str and bool(execution[key].strip())), 'Model observations must be text or unknown')
    # One content-addressed review per scope; other domains keep their own records.
    key = hash_json(sorted(scope))
    holder = {'inputs': state.get('inputs', {}), 'workflow': {'design_coverage': state['workflow'].get('design_coverage')}}
    _save(holder, 'review', copy.deepcopy(request), run_dir)
    records = state['workflow'].setdefault('independent_design_reviews', {})
    entry = holder['workflow']['review']
    entry['sequence'] = max((r.get('sequence', 0) for r in records.values()), default=0) + 1
    records[key] = entry
    return review_summary(state, sorted(scope))


def review_summary(state, selected=None):
    scope = set(selected) if selected is not None else set(_models(state))
    records = state.get('workflow', {}).get('independent_design_reviews', {})
    covered, observed = set(), set()
    latest = {}
    for record in sorted(records.values(), key=lambda r: r.get('sequence', 0)):
        try:
            value = load_document(record['document'])
            pins = value['bindings']
            relevant = scope.intersection(pins['entities'])
            if not relevant:
                continue
            observed.update(relevant)
            current = review_bindings(state, list(pins['entities']))
            from engagement_stages import closure
            graph = {k: e['depends_on'] for k, e in _models(state).items()}
            fresh = {k for k in relevant if pins['engagement_id'] == current['engagement_id'] and
                     pins['design_id'] == current['design_id'] and all(pins['entities'].get(p) == current['entities'].get(p)
                     for p in closure(graph, [k]))}
            blocking = set()
            for finding in value['findings']:
                if finding['status'] == 'open' and finding['severity'] == 'blocking':
                    blocking.update(set(finding['model_ids']) & relevant)
            for key in fresh:
                latest[key] = 'blocked' if key in blocking else value['result']
        except (ValueError, OSError, KeyError, TypeError):
            continue
    blocking = {k for k, result in latest.items() if result == 'blocked'}
    covered = {k for k, result in latest.items() if result == 'accepted'}
    status = ('changes_requested' if blocking or 'changes_requested' in latest.values() else 'recorded' if scope and scope <= covered else
              'partial' if covered else 'stale' if observed else 'unassessed')
    return {'status': status, 'reviewed_models': len(covered - blocking), 'expected_objects': len(scope),
            'qualification': 'Independent review is attributed by the host and bound to current scoped evidence. It is not human approval, authenticated identity, native validation or deployment authority.'}


def readiness_gaps(state, selected):
    """New evidence opt-in never prevents an explicit provisional-code request."""
    wf = state.get('workflow', {})
    if not wf.get('design_coverage') and not wf.get('design_evidence'):
        return []
    result = gaps(state, selected)
    if not wf.get('design_evidence'):
        result.append('Record design provenance before reviewed implementation')
    if not wf.get('design_coverage'):
        result.append('Record source-derived expected coverage before reviewed implementation')
    if review_summary(state, selected)['status'] != 'recorded':
        result.append('Current independent design review is incomplete')
    return result
