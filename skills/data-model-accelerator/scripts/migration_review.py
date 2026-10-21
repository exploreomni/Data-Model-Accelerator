"""Optional migration review records. Absent records preserve legacy behavior."""
import copy
import hashlib
import json
from pathlib import Path

from ae_common import require, hash_json

KINDS = {'business_rules', 'portfolio', 'parity', 'source_discovery'}


def records(state):
    value = state.get('workflow', {}).get('migration_review', {})
    require(type(value) is dict and set(value) <= KINDS, 'Invalid migration review records')
    return copy.deepcopy(value)


def store(state, kind, document, run_dir):
    import guided_workflow as guided
    require(kind in KINDS and 'workflow' in state, 'Unknown migration review kind or missing stages')
    guided._secrets(document)
    raw = guided._bytes(document)
    require(len(raw) <= guided.MAX_JSON_BYTES, 'Migration review exceeds bounded engagement size')
    digest = hashlib.sha256(raw).hexdigest()
    folder = guided._path(run_dir) / 'migration-review'
    require(not folder.is_symlink(), 'Migration review directory cannot be a symlink')
    folder.mkdir(exist_ok=True)
    path = folder / (digest + '.json')
    reference = {'path': str(path), 'sha256': digest, 'bytes': len(raw)}
    if path.exists():
        from review_assurance import load_document
        require(load_document(reference) == document, 'Migration review content changed')
    else:
        guided._atomic_write(path, raw, replace=False)
    value = records(state)
    value[kind] = reference
    state['workflow']['migration_review'] = value


def load(state, kind):
    from review_assurance import load_document
    reference = records(state).get(kind)
    return load_document(reference) if reference else None


def fingerprint(state):
    value = records(state)
    if not value: return None
    # Reading all records detects changed or missing files before cached handoff use.
    return hash_json({'records': {kind: load(state, kind) for kind in value},
                      'decisions': state['workflow'].get('business_rule_decisions', [])})


def public_summary(state, allowed_models=None):
    if not records(state): return None
    result = {'schema_version': 1, 'qualification': 'Supplied migration evidence; local consistency is not native validation or business acceptance.'}
    if 'business_rules' in records(state):
        import business_rules
        result['business_rules'] = business_rules.summary(state, allowed_models)
    if 'portfolio' in records(state):
        import shared_model_candidates
        result['portfolio'] = shared_model_candidates.summary(state, allowed_models)
    if 'source_discovery' in records(state):
        known = {m['id'] for m in (state['workflow'].get('design') or {}).get('entities', [])}
        # Repository-wide counts are not meaningful for a selected model subset.
        if allowed_models is None or known and known <= set(allowed_models):
            value = load(state, 'source_discovery')
            report = value['report']
            coverage = report['coverage']
            version = report['version']
            current = source_version()
            stale = value['source'] != state['inputs']['source']['fingerprint'] or value['runtime'] != current
            from review_assurance import load_document
            try:
                for ref in value['contracts']: load_document(ref)
            except (ValueError, OSError):
                stale = True
            result['source_discovery'] = {'status': 'stale' if stale else report['status'],
                'freshness': 'stale' if stale else 'current',
                'version': {k: version[k] for k in ('workflow', 'workflow_sha256', 'planner_sha256', 'adapter_component_sha256')},
                'coverage': {k: coverage[k] for k in ('counts', 'known_file_denominator', 'repository_file_denominator', 'enumeration_complete', 'export_completeness')},
                'gaps': [{'code': g['code']} for g in report['gaps']],
                'qualification': 'Offline Git extraction only; export completeness and native Periscope execution are unverified.'}
    if 'parity' in records(state):
        value = load(state, 'parity')
        report = copy.deepcopy(value['report'])
        stale = value['engagement'] != engagement_binding(state)
        # Captures stay private. Recheck their bytes without copying values into
        # state or the portable package; unavailable evidence cannot retain a pass.
        from review_assurance import load_document
        try:
            for ref in value['references'].values():
                if ref is not None: load_document(ref)
        except (ValueError, OSError):
            stale = True
        if allowed_models is not None:
            allowed = set(allowed_models)
            report['crosswalk'] = [r for r in report['crosswalk'] if r['model_ids'] and set(r['model_ids']) <= allowed]
        if stale:
            for row in report['crosswalk']:
                row['status'] = 'pending'; row['stale'] = True
                row['issues'].append({'code': 'engagement_or_private_evidence_changed', 'status': 'pending'})
            report['stale'] = True
        report['counts'] = {s: sum(r['status'] == s for r in report['crosswalk']) for s in ('pass', 'fail', 'pending', 'unsupported')}
        required = [r for r in report['crosswalk'] if r.get('required', True)]
        report['status'] = next((s for s in ('fail', 'unsupported', 'pending') if any(r['status'] == s for r in required)),
                                'pass' if required else 'unassessed')
        result['parity'] = report
    return result


def source_version():
    from source_adapters.registry import component_fingerprint
    from specialist_profiles import profile_binding
    root = Path(__file__).parent
    return {'workflow': hashlib.sha256((root / 'periscope_workflow.py').read_bytes()).hexdigest(),
            'planner': hashlib.sha256((root / 'plan_specialists.py').read_bytes()).hexdigest(),
            'adapter': component_fingerprint('periscope'), 'profile': profile_binding('periscope')['sha256']}


def extract_periscope(state, request, run_dir):
    from engagement_stages import fields
    from periscope_workflow import run_periscope_workflow
    fields(request, {'schema_version'}, {'source_profiles', 'source_identity', 'verified_connection_dialects'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported source extraction request')
    # This new directory is separate from the read-only source. Never overwrite
    # extraction evidence on retries or reuse a changed local tool silently.
    binding = {'source': state['inputs']['source']['fingerprint'], 'runtime': source_version(), 'request': request}
    output = Path(run_dir) / 'source-extraction' / hash_json(binding)
    old = load(state, 'source_discovery')
    if old and old['binding'] == hash_json(binding):
        require(Path(old['output']).is_dir(), 'Extraction output missing; retain evidence or use a new engagement')
        for ref in old['contracts']:
            from review_assurance import load_document
            load_document(ref)
        return
    report = run_periscope_workflow(state['inputs']['source']['path'], output,
        source_profiles=request.get('source_profiles', ()), source_identity=request.get('source_identity'),
        verified_connection_dialects=request.get('verified_connection_dialects', ()))
    contracts = []
    for item in report['extraction']:
        if item['contract_path']:
            path = output / item['contract_path']; raw = path.read_bytes()
            contracts.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    store(state, 'source_discovery', {'report': report, 'source': binding['source'], 'runtime': binding['runtime'],
        'binding': hash_json(binding), 'contracts': contracts, 'output': str(output)}, run_dir)


def engagement_binding(state):
    """Detect drift in design, rules, source context and registered code bytes."""
    import engagement_stages as stages
    workflow = state.get('workflow', {})
    artifacts = None
    if workflow.get('artifact_root') and workflow.get('tasks'):
        paths = sorted({p for task in workflow['tasks'] for p in task['outputs']})
        try: artifacts = stages._output_hashes(workflow['artifact_root'], paths)
        except (ValueError, OSError): artifacts = 'unavailable'
    return hash_json({'inputs': state['inputs'], 'design': workflow.get('design'), 'artifacts': artifacts,
                      'rules': load(state, 'business_rules'), 'decisions': workflow.get('business_rule_decisions', [])})


def parity_bindings(state, model_ids):
    """Local engagement comparison identity, never a deployment policy binding.

    Derive from observed inputs and registered file bytes, not a capture's claim
    about itself. The separate release workflow retains its own exact bindings.
    """
    import guided_workflow as guided
    import engagement_stages as stages
    from business_rules import scope_bindings
    models = {m['id'] for m in (state['workflow'].get('design') or {}).get('entities', [])}
    stages.ids(model_ids, models, True)
    bound = guided._bindings(state)
    material = stages.entity_bindings(state, model_ids)
    relevant = set(material)
    workflow = state['workflow']
    outputs = None
    if workflow.get('artifact_root') and workflow.get('tasks'):
        paths = sorted({p for t in workflow['tasks'] if relevant & set(t['entity_ids']) for p in t['outputs']})
        try: outputs = stages._output_hashes(workflow['artifact_root'], paths)
        except (ValueError, OSError): outputs = 'unavailable'
    return {'source': bound['source'], 'catalogue': bound['catalogue'],
            'candidate': hash_json({'kind': 'guided_parity_candidate_v1', 'entities': material, 'outputs': outputs,
                                   'rules': {k: v for k, v in scope_bindings(state).items() if k in relevant}}),
            'target': hash_json(state['inputs']['target']),
            'policy': hash_json({'kind': 'local_comparison_only_v1', 'input_handling': state['answers'].get('input_handling'),
                                'execution_authorized': False, 'deployment_authorized': False}),
            'scope': hash_json({'models': sorted(relevant), 'migration_scope': state['answers'].get('migration_scope'),
                               'semantic_target': state['answers'].get('semantic_target')})}


def register_parity(state, request, run_dir):
    from engagement_stages import fields
    from review_assurance import load_document
    from migration_validation import evaluate
    fields(request, {'schema_version', 'workflow'}, {'baseline', 'warehouse', 'omni', 'current_bindings'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported parity review request')
    refs = {key: request.get(key) for key in ('workflow', 'baseline', 'warehouse', 'omni')}
    documents = {key: load_document(ref) if ref is not None else None for key, ref in refs.items()}
    selected = sorted({m for row in documents['workflow']['crosswalk'] for m in row['model_ids']})
    current = parity_bindings(state, selected)
    report = evaluate(documents['workflow'], documents['baseline'], documents['warehouse'], documents['omni'],
                      current_bindings=current)
    known = {m['id'] for m in (state['workflow'].get('design') or {}).get('entities', [])}
    require(all(set(r['model_ids']) <= known for r in report['crosswalk']), 'Parity crosswalk references unknown design models')
    store(state, 'parity', {'report': report, 'references': refs, 'engagement': engagement_binding(state)}, run_dir)
