"""Bounded local dispatch and restart accounting for the existing guided workflow.

Claims reserve coordinator slots; they do not launch or contain host agents.
Checkpoints preserve files without establishing their meaning or native validity.
No model selection, provider billing inference, source execution or approval.
"""
import copy
from pathlib import Path

from ae_common import hash_file, hash_json, require, safe_relative

ROLES = {'source_specialist', 'catalogue_specialist', 'warehouse_architect',
         'analytics_engineer', 'semantic_modeler', 'validation_analyst',
         'independent_reviewer', 'documentation_specialist'}
DEFAULT_LIMIT = 2


def content_manifest(skill_root=None):
    root = Path(skill_root) if skill_root is not None else Path(__file__).resolve().parent.parent
    require(root.is_absolute() and root.is_dir() and (root / 'SKILL.md').is_file(), 'Expected an absolute skill directory containing SKILL.md')
    require(not any(p.is_symlink() for p in (root, *root.parents)), 'Skill identity does not follow symlinks')
    require(not (root / 'SKILL.md').is_symlink(), 'Skill identity does not follow symlinks')
    # Content identity works for installed skills without Git. Do not read host
    # credentials, Git remotes, user settings or the customer's repository code.
    paths = [root / 'SKILL.md']
    for folder in ('scripts', 'references', 'agents', 'assets'):
        require(not (root / folder).is_symlink(), 'Skill identity does not follow symlinks')
        for path in (root / folder).rglob('*'):
            if any(part in {'__pycache__', '.git', '.venv', 'node_modules'} for part in path.relative_to(root).parts):
                continue
            require(not path.is_symlink(), 'Skill identity does not follow symlinks')
            if path.is_file() and path.suffix != '.pyc' and path.name != '.DS_Store':
                paths.append(path)
    return {str(p.relative_to(root)): hash_file(p) for p in sorted(paths)}


def runtime_identity():
    manifest = content_manifest()
    return {'kind': 'accelerator_runtime_identity', 'schema_version': 1,
            'runtime_sha256': hash_json(manifest), 'file_count': len(manifest),
            'identity_scope': 'skill_scripts_references_agents_assets',
            'qualification': 'Installed content identity, including specialist instructions and templates; not a release or execution attestation.'}


def observe_runtime(state):
    current = runtime_identity()
    records = state.setdefault('runtime_observations', [])
    if not records or records[-1]['runtime_sha256'] != current['runtime_sha256']:
        records.append(current)


def configure(state, request):
    import engagement_stages as stages
    stages.fields(request, {'schema_version', 'max_workers', 'reason'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported work policy')
    require(type(request['max_workers']) is int and 1 <= request['max_workers'] <= 8,
            'Concurrency limit must be between one and eight')
    stages.text(request['reason'])
    ops = copy.deepcopy(state.get('operations') or {'schema_version': 1, 'max_workers': DEFAULT_LIMIT,
                                                  'attempts': [], 'reuse_count': 0})
    active = sum(a['status'] == 'active' and a['execution_mode'] == 'specialist' for a in ops['attempts'])
    require(active <= request['max_workers'], 'Checkpoint active workers before lowering concurrency')
    ops.update(max_workers=request['max_workers'], policy_reason=request['reason'])
    state['operations'] = ops
    return public_summary(state)


def _binding(state, request):
    import engagement_stages as stages
    from authoring_evidence import capture
    import guided_workflow as guided
    from source_adapters.registry import SOURCES, component_fingerprint
    source_type = request.get('source_type')
    require(source_type is None or source_type in SOURCES, 'Unknown source type')
    paths = request['source_paths']
    require(type(paths) is list and len(paths) <= 512 and len(set(paths)) == len(paths),
            'Source paths must be a bounded unique list')
    for path in paths:
        safe_relative(path)
        require(not any(p.lower() in guided.SECRET_FILES or p.lower().startswith('.env')
                        or guided.SECRET_PATH.search(p) for p in Path(path).parts),
                'Credential paths cannot be work inputs')
    if request.get('task_id'):
        root = state['workflow'].get('artifact_root')
        require(root, 'Plan stage tasks with an artifact root before dispatch')
        plan = stages.plan_tasks(state, root)
        task = next((t for t in plan['tasks'] if t['id'] == request['task_id']), None)
        require(task and task['action'] in {'regenerate', 'reuse'}, 'Stage task is blocked or unplanned')
        require(set(request['scope_ids']) == set(task['entity_ids']), 'Dispatch scope differs from stage task')
        return {'task_id': task['id'], 'fingerprint': task['fingerprint']}, task
    require(paths, 'Non-stage work requires exact source paths; scope labels alone are not evidence')
    source = Path(state['inputs']['source']['path'])
    binding = {'source_files': capture(source, paths), 'role': request['role'],
               'scope_ids': sorted(request['scope_ids']),
               'extractor_sha256': hash_json({name: component_fingerprint(name) for name in
                    ([source_type] if source_type else SOURCES)})}
    if request['role'] not in {'source_specialist', 'catalogue_specialist'}:
        binding['design_sha256'] = (state.get('workflow', {}).get('design') or {}).get('sha256')
        binding['target'] = state.get('inputs', {}).get('target')
    return binding, None


def _outputs_current(record):
    from authoring_evidence import capture
    try:
        return bool(record.get('outputs')) and capture(record['artifact_root'], list(record['outputs'])) == record['outputs']
    except (OSError, ValueError, TypeError, KeyError):
        return False


def claim_work(state, request):
    """Called under the guided state lock; duplicate active work never dispatches."""
    import engagement_stages as stages
    from guided_workflow import _now
    stages.fields(request, {'schema_version', 'work_id', 'attempt_id', 'role', 'scope_ids', 'source_paths'},
                  {'task_id', 'execution_mode', 'source_type'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported work request')
    stages.identifier(request['work_id']); stages.identifier(request['attempt_id'])
    stages.ids(request['scope_ids'], nonempty=True)
    require(request['role'] in ROLES, 'Unknown specialist role')
    mode = request.get('execution_mode', 'specialist')
    require(mode in {'inline', 'specialist'}, 'Unknown execution mode')
    from domain_workflow import guard_dispatch
    guard_dispatch(state, request)
    binding, task = _binding(state, request)
    fingerprint = hash_json(binding)
    ops = copy.deepcopy(state.get('operations') or {'schema_version': 1, 'max_workers': DEFAULT_LIMIT,
                                                  'attempts': [], 'reuse_count': 0})
    limit = ops['max_workers']
    require(type(limit) is int and 1 <= limit <= 8, 'Invalid concurrency limit')
    active = [a for a in ops['attempts'] if a['status'] == 'active']
    for record in active:
        if (record['work_id'] == request['work_id'] or record['fingerprint'] == fingerprint
                or (request.get('task_id') and record.get('task_id') == request['task_id'])):
            require(record['fingerprint'] == fingerprint, 'Checkpoint active work before changing its scope')
            return {'action': 'already_active', 'attempt_id': record['attempt_id'],
                    'qualification': 'Reuse the existing host worker; do not launch another.'}
    for record in reversed(ops['attempts']):
        if (record['fingerprint'] == fingerprint
                and record['status'] == 'outputs_recorded' and _outputs_current(record)):
            ops['reuse_count'] += 1
            state['operations'] = ops
            return {'action': 'reuse', 'attempt_id': record['attempt_id'], 'outputs': record['outputs'],
                    'qualification': 'Retained bytes and inputs match; original assurance is unchanged.'}
    if task and task['action'] == 'reuse':
        ops['reuse_count'] += 1
        state['operations'] = ops
        return {'action': 'reuse', 'run_id': task['original_run_id'], 'outputs': task['outputs'],
                'qualification': 'Existing stage result reused without a new agent.'}
    require(mode == 'inline' or sum(a['execution_mode'] == 'specialist' for a in active) < limit,
            'Specialist concurrency limit reached; checkpoint or finish active work before dispatching more')
    require(all(a['attempt_id'] != request['attempt_id'] for a in ops['attempts']), 'Attempt ID already recorded')
    previous = next((a for a in reversed(ops['attempts']) if a['work_id'] == request['work_id']
                     and a['fingerprint'] == fingerprint and a['status'] == 'interrupted'), None)
    attempt = {**copy.deepcopy(request), 'execution_mode': mode, 'fingerprint': fingerprint,
               'bindings': binding, 'status': 'active', 'started_at': _now(),
               'resumes_attempt_id': previous['attempt_id'] if previous else None,
               'outputs': {}, 'execution_verified': False}
    require(len(ops['attempts']) < 20000, 'Work history limit reached; retain this engagement and start a linked scope')
    ops['attempts'].append(attempt)
    state['operations'] = ops
    return {'action': 'dispatch', 'attempt_id': attempt['attempt_id'], 'fingerprint': fingerprint,
            'resumes_attempt_id': attempt['resumes_attempt_id'],
            'qualification': 'Slot reserved only. Invoke the actual host with a bounded packet; this is not execution.'}


def checkpoint_work(state, request, artifact_root):
    import engagement_stages as stages
    from guided_workflow import _now, _path
    from authoring_evidence import capture
    stages.fields(request, {'schema_version', 'attempt_id', 'status', 'reason', 'outputs'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported checkpoint request')
    stages.identifier(request['attempt_id']); stages.text(request['reason'])
    require(request['status'] in {'interrupted', 'outputs_recorded'}, 'Unknown checkpoint status')
    require(type(request['outputs']) is list and len(request['outputs']) <= 512
            and len(set(request['outputs'])) == len(request['outputs']), 'Invalid checkpoint output list')
    ops = copy.deepcopy(state.get('operations', {}))
    attempt = next((a for a in ops.get('attempts', []) if a['attempt_id'] == request['attempt_id']), None)
    require(attempt and attempt['status'] == 'active', 'Checkpoint requires an active attempt')
    root, source = _path(artifact_root), _path(state['inputs']['source']['path'])
    require(root != source and root not in source.parents and source not in root.parents,
            'Checkpoint outputs must be separate from the source')
    outputs = capture(root, request['outputs'])
    if request['status'] == 'outputs_recorded':
        require(outputs, 'Completed work needs retained output files')
        # Stage output registration has its own byte, scope and review checks.
        if attempt.get('task_id'):
            task = next(t for t in stages.plan_tasks(state, root)['tasks'] if t['id'] == attempt['task_id'])
            require(task['action'] == 'reuse' and task['fingerprint'] == attempt['bindings']['fingerprint'],
                    'Record current stage task outputs before completing its dispatch')
            require(task['outputs'] == outputs, 'Checkpoint differs from registered stage outputs')
    attempt.update(status=request['status'], reason=request['reason'], outputs=outputs,
                   artifact_root=str(root), checkpoint_at=_now())
    state['operations'] = ops
    return {'attempt_id': attempt['attempt_id'], 'status': attempt['status'], 'outputs': outputs,
            'qualification': 'Local checkpoint only; output presence does not establish validation.'}


def public_summary(state):
    ops = state.get('operations')
    attempts = (ops or {}).get('attempts', [])
    return {'status': 'tracked' if ops else 'untracked',
            'runtime_sha256': (state.get('runtime_observations') or [{}])[-1].get('runtime_sha256'),
            'max_workers': (ops or {}).get('max_workers', DEFAULT_LIMIT),
            'counts': {status: sum(a['status'] == status for a in attempts)
                       for status in ('active', 'interrupted', 'outputs_recorded')},
            'attempts': len(attempts), 'reused': (ops or {}).get('reuse_count', 0),
            'cost': None, 'execution_verified': False,
            'qualification': 'Coordinator records only. Host invocation, token usage, cost and native validation remain separate evidence.'}
