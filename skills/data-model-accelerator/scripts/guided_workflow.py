"""Durable local discovery workflow; never executes input code or a warehouse.

Readiness is static guidance. Recorded reports and operator answers cannot confer
verified execution, business approval, deployment permission or production status.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

from platform_matrix import FRAMEWORKS, WAREHOUSES

SCHEMA_VERSION = 1
MAX_JSON_BYTES = 16 * 1024 * 1024
UNSET = object()
ANSWER_KEYS = {'engagement_type', 'priority_domain', 'framework', 'warehouse',
               'semantic_target', 'deliverables', 'trusted_outputs',
               'retained_behavior', 'corrected_behavior', 'host', 'environment',
               'execution_mode', 'audience', 'metadata_policy', 'naming_policy'}
DELIVERABLES = {'implementation', 'diagrams', 'documentation', 'dictionary',
                'validation', 'sample_data', 'technical_audit'}
ENUMS = {'engagement_type': {'migration', 'refactor', 'new_model', 'blind_test'},
         'framework': set(FRAMEWORKS),
         'warehouse': set(WAREHOUSES) | {'gcp'},
         'execution_mode': {'assessment_only', 'candidate_only',
                            'local_validation_requested', 'target_validation_requested'}}
UNKNOWN = {'', 'unknown', 'tbd', 'unspecified', 'not sure', 'unavailable', 'none available'}
SECRET_KEY = re.compile(r'(?:password|passwd|credential|secret|api[_ -]?key|access[_ -]?token|private[_ -]?key|authorization)', re.I)
SECRET_VALUE = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+|\bAKIA[A-Z0-9]{16}\b|\bsk-[A-Za-z0-9_-]{16,}|://[^\s/@:]+:[^\s/@]+@|\b(?:password|passwd|token|secret|api[_ -]?key)\s*[:=]\s*\S+', re.I)
SECRET_FILES = {'.env', 'profiles.yml', 'profiles.yaml', 'credentials', 'credentials.json',
                'id_rsa', 'id_ed25519', 'secrets.json', 'secrets.yml', 'secrets.yaml',
                'connections.toml', '.npmrc', '.pypirc', '.aws', '.azure', '.ssh', '.dbt', '.config', 'oauth.json'}
SECRET_PATH = re.compile(r'(?:^|[._-])(?:credentials?|secrets?|tokens?|service[._-]?account|private[._-]?key)(?:[._-]|$)', re.I)
DEPENDENCIES = {'source', 'catalogue', 'target', 'runtime', 'discovery'}
STATUSES = {'interview_pending', 'assessment_ready', 'candidate_preparation_ready', 'needs_evidence', 'handoff_prepared'}
QUESTIONS = {
    'engagement_type': ('What are we doing: migrating, refactoring, designing a new model, or running a blind test?', ['migration', 'refactor', 'new_model', 'blind_test']),
    'priority_domain': ('Which business domain, report, or decision should we handle first?', []),
    'framework': ('How should the target transformations be delivered?', list(FRAMEWORKS)),
    'warehouse': ('Which warehouse will the target use? If you mean GCP, confirm whether it is BigQuery.', list(WAREHOUSES)),
    'semantic_target': ('Should we retain the semantic engine, target a named engine, or leave semantic implementation out of scope?', ['retain_existing', 'omni', 'none']),
    'deliverables': ('Which handoff outputs do you want?', sorted(DELIVERABLES)),
    'trusted_outputs': ('Which report IDs or versioned outputs provide the trusted comparison baseline?', []),
    'retained_behavior': ('Which existing behavior must remain compatible? Supply a list.', []),
    'corrected_behavior': ('Which behavior should intentionally change? Supply a list, or [] for no requested corrections.', []),
    'metadata_policy': ('Confirm the metadata delivery scope, RAW ownership, taxonomy, environments and reviewer before generating deployment metadata.', []),
    'naming_policy': ('Preserve current names, or apply a reviewed type/domain or layer/domain convention?', ['preserve', 'type_domain', 'layer_domain']),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf-8')


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            _require(isinstance(key, str) and not SECRET_KEY.search(key),
                     'Credential fields are not accepted; keep credentials outside the workflow.')
            _secrets(item)
    elif isinstance(value, list):
        for item in value:
            _secrets(item)
    elif isinstance(value, str):
        _require(not SECRET_VALUE.search(value),
                 'Credential-like values are not accepted; keep credentials outside the workflow.')


def _json_with_hash(path):
    path = _path(path)
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode), 'Expected a regular JSON file: ' + str(path))
        _require(before.st_size <= MAX_JSON_BYTES, 'JSON file exceeds the 16 MiB bound.')
        raw = stream.read(MAX_JSON_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    _require(identity(before) == identity(after) and len(raw) == after.st_size,
             'JSON file changed during the read; retry with a stable input.')
    _require(len(raw) <= MAX_JSON_BYTES, 'JSON file exceeds the 16 MiB bound.')
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    content = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON number.')))
    return content, hashlib.sha256(raw).hexdigest()


def _json(path):
    return _json_with_hash(path)[0]


def _nonsecret_json(path):
    path = _path(path)
    _require(not any(p.name.lower() in SECRET_FILES or p.name.lower().startswith('.env.')
                     or SECRET_PATH.search(p.name) or p.suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}
                     for p in [path, *path.parents]), 'Credential files cannot be workflow inputs.')
    content, digest = _json_with_hash(path)
    _secrets(content)
    return content, digest


def _path(value):
    path = Path(value).expanduser().absolute()
    _require(not any(p.is_symlink() for p in [path, *path.parents]), 'Symlink paths are not accepted: ' + str(path))
    return path.resolve()


def _outside(run_dir, repo):
    _require(run_dir != repo and repo not in run_dir.parents,
             'The engagement run folder must be outside the read-only input repository.')


@contextmanager
def _lock(run_dir):
    """Cooperating POSIX writers; atomic files remain authoritative after interruption."""
    try:
        import fcntl
    except ImportError as error:
        raise ValueError('This workflow currently requires POSIX file locking; use a qualified POSIX host.') from error
    lock = run_dir / '.workflow.lock'
    _require(not lock.is_symlink(), 'Workflow lock must not be a symlink.')
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another workflow writer is active; retry after it finishes.') from error
        yield


def _atomic_write(path, payload, *, replace=True):
    """Fsync a same-directory temporary file before atomic publication."""
    path = Path(path)
    _require(not path.is_symlink(), 'Output must not be a symlink: ' + str(path))
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # Exclusive immutable revision, never overwrite.
            os.unlink(temporary)
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _answers(answers):
    _require(type(answers) is dict, 'Answers must be a JSON object.')
    _secrets(answers)
    _require(set(answers) <= ANSWER_KEYS,
             'Unknown answer fields: ' + ', '.join(sorted(set(answers) - ANSWER_KEYS)))
    result = {}
    for key, value in answers.items():
        if value is None:
            result[key] = None
            continue
        if key in ('metadata_policy', 'naming_policy'):
            from metadata_options import validate_options, validate_naming
            result[key] = (validate_options if key == 'metadata_policy' else validate_naming)(value)
            continue
        if key in ('deliverables', 'trusted_outputs', 'retained_behavior', 'corrected_behavior'):
            _require(type(value) is list and all(type(v) is str and len(v) <= 4000 for v in value), key + ' must be a list of nonsecret strings.')
            value = [v.strip() for v in value]
            _require(len(value) <= 100 and len(set(value)) == len(value), key + ' must have at most 100 distinct values.')
            if key == 'deliverables':
                _require(set(value) <= DELIVERABLES, 'Unknown deliverable selection.')
        else:
            _require(type(value) is str and len(value) <= 4000, key + ' must be a nonsecret string.')
            value = value.strip()
            if key in ENUMS and value.lower() not in UNKNOWN:
                _require(value in ENUMS[key], 'Unsupported ' + key + '; choose ' + ', '.join(sorted(ENUMS[key])) + '.')
        result[key] = value
    return result


def _known(value):
    if value is None:
        return False
    if isinstance(value, str):
        return value.lower().strip() not in UNKNOWN
    return bool(value) and all(_known(item) for item in value)


def _missing(answers):
    fields = ['engagement_type', 'priority_domain', 'framework', 'warehouse', 'semantic_target', 'deliverables']
    if answers.get('engagement_type') in ('migration', 'refactor'):
        fields += ['trusted_outputs', 'retained_behavior', 'corrected_behavior']
    missing = []
    for field in fields:
        value = answers.get(field)
        known = field in answers and value == [] if field == 'corrected_behavior' else False
        if not known:
            known = _known(value)
        if field == 'warehouse' and value == 'gcp':
            known = False
        if not known:
            missing.append(field)
    return missing


def _selection(answers):
    target = {key: answers.get(key) for key in ('framework', 'warehouse', 'semantic_target')}
    # Preserve historical fingerprints when the feature was never selected.
    # Once supplied, all choices participate in invalidation, including null.
    for key in ('metadata_policy', 'naming_policy'):
        if key in answers:
            target[key] = answers[key]
    target['sha256'] = _digest(target)
    runtime = {key: answers.get(key) for key in ('host', 'environment', 'execution_mode')}
    runtime['execution_mode'] = runtime['execution_mode'] or 'candidate_only'
    runtime['sha256'] = _digest(runtime)
    discovery = {key: answers.get(key) for key in ('engagement_type', 'priority_domain', 'trusted_outputs', 'retained_behavior', 'corrected_behavior')}
    return target, runtime, {'sha256': _digest(discovery)}


def _catalogue(path, *, previously_recorded=False):
    if path is None:
        return None
    path = _path(path)
    if previously_recorded and not path.exists():
        return {'path': str(path), 'sha256': None, 'available': False, 'reason': 'Previously recorded catalogue is missing.'}
    _, digest = _nonsecret_json(path)
    return {'path': str(path), 'sha256': digest, 'available': True}


def _assess_repository(repo, framework, warehouse, **options):
    from platform_readiness import assess_repository
    return assess_repository(repo, framework, warehouse, **options)


def _bindings(state):
    inputs = state['inputs']
    return {'source': _digest(inputs['source']['fingerprint']),
            'catalogue': _digest(inputs['catalogue']),
            **{key: inputs[key]['sha256'] for key in ('target', 'runtime', 'discovery')}}


def _delivery_choices(state):
    return _digest({key: state['answers'].get(key) for key in ('audience', 'deliverables')})


def _handoff_snapshot(state, review_path, artifact_root, audience, include):
    """Validate actual selected files, without interpreting reported test results."""
    from delivery_portal import validate_review, resolve_selection, select_artifacts
    review_path, artifact_root = _path(review_path), _path(artifact_root)
    review, review_hash = _nonsecret_json(review_path)
    validate_review(state, review)
    selected_categories = resolve_selection(state, audience, include)
    artifacts = select_artifacts(review, artifact_root, audience, selected_categories)
    _require(bool(artifacts), 'No artifacts match the handoff selection.')
    return {'review_path': str(review_path), 'review_sha256': review_hash,
            'artifact_root': str(artifact_root), 'audience': audience,
            'deliverables': sorted(selected_categories), 'choices_sha256': _delivery_choices(state),
            'artifacts': [{'path': a['path'], 'destination': a['destination'],
                           'sha256': a['sha256'], 'bytes': len(a['content'])} for a in artifacts]}


def _delivery_progress(state):
    prepared = next((item for item in reversed(state['evidence'])
                     if item['kind'] == 'prepared_handoff' and item['status'] == 'current'
                     and item.get('assurance') == 'file_integrity_only' and 'handoff' in item), None)
    state.pop('delivery', None)
    if prepared is None or not state['readiness']['generation_ready']:
        return
    snapshot = prepared['handoff']
    state['status'] = 'handoff_prepared'
    state['delivery'] = {'status': 'prepared', 'artifact_count': len(snapshot['artifacts']),
                         'assurance': 'file_integrity_only', 'audience': snapshot['audience'],
                         'deliverables': snapshot['deliverables'],
                         'qualification': 'Prepared files only; business, native runtime and deployment approval remain separate.'}
    state['next_actions'] = [{'id': 'review_prepared_handoff', 'scope': 'review',
                             'action': 'Review the prepared model, selected files and reported validation. Resolve outstanding business definitions, access rules and native target checks before approval or deployment.'}]


def _invalidate(state):
    current = _bindings(state)
    invalidated = []
    for item in state['evidence']:
        if item['status'] != 'current':
            continue
        changed = [key for key, value in item['dependencies'].items() if current[key] != value]
        if 'receipt' in item:
            try:
                _, digest = _nonsecret_json(item['receipt']['path'])
                if digest != item['receipt']['sha256']:
                    changed.append('receipt')
            except (ValueError, OSError):
                changed.append('receipt')
        if 'handoff' in item:
            pinned = item['handoff']
            if pinned['choices_sha256'] != _delivery_choices(state):
                changed.append('delivery_selection')
            if not changed:
                try:
                    _, review_hash = _nonsecret_json(pinned['review_path'])
                    # A changed contract is already stale; do not interpret its
                    # regenerated artifact declarations as the original handoff.
                    if review_hash != pinned['review_sha256']:
                        changed.append('handoff_files')
                    else:
                        observed = _handoff_snapshot(state, pinned['review_path'], pinned['artifact_root'],
                                                     pinned['audience'], pinned['deliverables'])
                        if observed != pinned:
                            changed.append('handoff_files')
                except (ValueError, OSError, KeyError, TypeError):
                    changed.append('handoff_files')
        if changed:
            item.update(status='stale', invalidated_at=_now(), invalidated_by=changed)
            invalidated.append({'evidence_id': item['id'], 'dependencies': changed})
    return invalidated


def _assessment_summary(platform):
    """Keep history growth independent of inventory and finding-list sizes."""
    coverage = platform.get('coverage', {})
    findings = platform.get('findings', [])
    return {
        'coverage': {**{key: coverage.get(key) for key in ('complete', 'scanned_files', 'scanned_bytes')},
                     'exclusion_count': len(coverage.get('exclusions', [])),
                     'gap_count': len(coverage.get('gaps', []))},
        'capabilities': {key: platform.get('capabilities', {}).get(key, {}).get('status')
                         for key in ('assessment', 'generation', 'execution')},
        'finding_counts': {severity: sum(item.get('severity') == severity for item in findings)
                           for severity in ('blocker', 'warning', 'info')},
        'detected_source_count': len(platform.get('detected_sources', [])),
        'question_count': len(platform.get('questions', [])),
    }


def _refresh(state, *, catalogue=UNSET, readiness_options=None):
    repo = state['inputs']['source']['path']
    _require(Path(repo).is_dir(), 'Source repository is unavailable; restore it before refreshing this engagement.')
    options = dict(readiness_options if readiness_options is not None else state.get('readiness_options', {}))
    _secrets(options)
    state['readiness_options'] = options
    a = state['answers']
    framework = a.get('framework') if _known(a.get('framework')) else None
    warehouse = a.get('warehouse') if _known(a.get('warehouse')) else None
    platform = _assess_repository(repo, framework, warehouse, **options)
    _require(type(platform) is dict and platform.get('schema_version') == 1, 'Readiness collector returned an unsupported schema.')
    fingerprint = platform['source_fingerprint']
    _require(re.fullmatch('[0-9a-f]{64}', fingerprint.get('value', '')) is not None, 'Readiness source fingerprint is invalid.')
    state['inputs']['source']['fingerprint'] = fingerprint
    state['source_fingerprint'] = fingerprint
    if catalogue is UNSET:
        existing = state['inputs'].get('catalogue')
        state['inputs']['catalogue'] = _catalogue(existing['path'], previously_recorded=True) if existing else None
    else:
        state['inputs']['catalogue'] = _catalogue(catalogue)
    target, runtime, discovery = _selection(a)
    state['inputs'].update(target=target, runtime=runtime, discovery=discovery)
    invalidated = _invalidate(state)
    missing = _missing(a)
    questions = [{'id': key, 'prompt': QUESTIONS[key][0], 'choices': QUESTIONS[key][1]} for key in missing[:3]]
    blockers = [f for f in platform.get('findings', []) if f.get('severity') == 'blocker'
                and 'generation' in f.get('blocks', ['generation'])]
    if state['inputs']['catalogue'] is None:
        blockers.append({'id': 'capture_catalogue', 'summary': 'No physical catalogue has been supplied.',
                         'next_action': 'Supply a nonsecret physical catalogue with assess --catalogue PATH. Static assessment can continue while it is missing.'})
    elif not state['inputs']['catalogue']['available']:
        blockers.append({'id': 'restore_catalogue', 'summary': 'Previously recorded catalogue is unavailable.',
                         'next_action': 'Restore the recorded catalogue or explicitly supply its replacement.'})
    complete = platform.get('coverage', {}).get('complete') is True and fingerprint.get('complete') is True
    capable = platform.get('capabilities', {}).get('generation', {}).get('status') == 'agent_assisted'
    generation_ready = not missing and complete and capable and not blockers
    state['readiness'] = {'interview_complete': not missing, 'generation_ready': generation_ready,
                          'assessment_allowed': True, 'execution_authorized': False,
                          'missing_answers': missing, 'questions': questions, 'platform': platform,
                          'assessed_at': _now(),
                          'qualification': 'Candidate preparation guidance only. A catalogue hash proves captured bytes, not normalized physical bindings. verify_catalogue, model, independent baseline and execution gates remain pending; this workflow does not run or replace them.'}
    if missing:
        state['status'] = 'interview_pending'
    elif generation_ready:
        state['status'] = 'candidate_preparation_ready'
    elif blockers or not complete:
        state['status'] = 'needs_evidence'
    else:
        state['status'] = 'assessment_ready'
    state['next_actions'] = [{'id': 'answer_' + q['id'], 'action': q['prompt'], 'scope': 'discovery'} for q in questions]
    if not missing:
        state['next_actions'] += [{'id': f['id'], 'action': f.get('next_action', f['summary']), 'scope': 'readiness'} for f in blockers]
        if not generation_ready and not blockers:
            state['next_actions'].append({'id': 'review_generation_contract', 'action': platform.get('capabilities', {}).get('generation', {}).get('reason', 'Resolve the generation contract and coverage gaps.'), 'scope': 'readiness'})
        if generation_ready:
            state['next_actions'].append({'id': 'prepare_selected_handoff', 'action': 'Verify the physical catalogue and review the scoped model contract before generating selected artifacts. Independent baseline and execution gates remain separate qualified actions.', 'scope': 'generation'})
    _delivery_progress(state)
    bindings = _bindings(state)
    state['evidence'].append({'id': 'assessment-' + uuid.uuid4().hex, 'kind': 'static_readiness',
                              'status': 'current', 'assurance': 'static_read_only', 'recorded_at': _now(),
                              'dependencies': {key: bindings[key] for key in ('source', 'target')},
                              'result_sha256': _digest(platform), 'summary': _assessment_summary(platform),
                              'result_ref': None})
    return invalidated


def _save(run_dir, state, action, *, changed_answers=(), invalidated=()):
    revisions = run_dir / 'revisions'
    revisions.mkdir(exist_ok=True)
    _require(not revisions.is_symlink(), 'Revision directory must not be a symlink.')
    numbers = [int(p.stem) for p in revisions.glob('*.json') if p.stem.isdigit()]
    state['revision'] = max([state.get('revision', 0), *numbers]) + 1
    revision_path = 'revisions/%06d.json' % state['revision']
    for item in state['evidence']:
        if item.get('kind') == 'static_readiness' and 'result_ref' in item and item['result_ref'] is None:
            item['result_ref'] = {'path': revision_path, 'json_pointer': '/readiness/platform'}
    state['updated_at'] = _now()
    state['history'].append({'revision': state['revision'], 'at': state['updated_at'], 'action': action,
                             'changed_answers': sorted(changed_answers), 'invalidated_evidence': list(invalidated)})
    state.pop('state_sha256', None)
    state['state_sha256'] = _digest(state)
    payload = _bytes(state)
    _require(len(payload) <= MAX_JSON_BYTES, 'State exceeds 16 MiB; start a linked new engagement instead of discarding history.')
    _atomic_write(run_dir / revision_path, payload, replace=False)
    _atomic_write(run_dir / 'state.json', payload)
    return state


def _validate_state(run_dir, state):
    _require(type(state) is dict, 'Engagement state must be a JSON object.')
    _require(state.get('schema_version') == SCHEMA_VERSION and state.get('kind') == 'guided_engagement', 'Unsupported engagement state schema.')
    _require(state.get('status') in STATUSES, 'State contains an unsupported claimed lifecycle status.')
    _require(type(state.get('revision')) is int and state['revision'] > 0, 'State revision must be a positive integer.')
    _require(state.get('state_sha256') == _digest({k: v for k, v in state.items() if k != 'state_sha256'}), 'State integrity check failed; restore the last committed revision.')
    revision = run_dir / 'revisions' / ('%06d.json' % state['revision'])
    _require(revision.is_file() and _json(revision) == state, 'State does not match its immutable revision.')
    _outside(run_dir, _path(state['inputs']['source']['path']))
    return state


def load_engagement(run_dir):
    run_dir = _path(run_dir)
    return _validate_state(run_dir, _json(run_dir / 'state.json'))


def start_engagement(repo, run_dir, answers=None, catalogue=None, engagement_id=None, readiness_options=None):
    repo, run_dir = _path(repo), _path(run_dir)
    _require(repo.is_dir(), 'Input repository must be an existing directory.')
    _outside(run_dir, repo)
    _require(not run_dir.exists() or not any(p.name != '.workflow.lock' for p in run_dir.iterdir()),
             'Start requires a new or empty run folder; use resume for an existing engagement.')
    supplied = _answers(answers or {})
    identifier = engagement_id or str(uuid.uuid4())
    _require(type(identifier) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', identifier), 'Invalid engagement_id.')
    run_dir.mkdir(parents=True, exist_ok=True)
    with _lock(run_dir):
        _require(not (run_dir / 'state.json').exists(), 'An engagement already exists; use resume.')
        state = {'schema_version': 1, 'kind': 'guided_engagement', 'engagement_id': identifier,
                 'revision': 0, 'created_at': _now(), 'answers': supplied,
                 'inputs': {'source': {'path': str(repo)}, 'catalogue': None},
                 'readiness': {}, 'evidence': [], 'history': [], 'status': 'interview_pending',
                 'next_actions': [], 'authority': 'Requests and local guidance only; no execution, deployment or business approval is conferred.'}
        invalidated = _refresh(state, catalogue=catalogue, readiness_options=readiness_options)
        return _save(run_dir, state, 'started', changed_answers=supplied, invalidated=invalidated)


def update_answers(run_dir, answers, *, catalogue=UNSET, readiness_options=None):
    updates = _answers(answers)
    run_dir = _path(run_dir)
    with _lock(run_dir):
        state = load_engagement(run_dir)
        changed = [key for key, value in updates.items() if key not in state['answers'] or state['answers'][key] != value]
        state['answers'].update(updates)
        invalidated = _refresh(state, catalogue=catalogue, readiness_options=readiness_options)
        return _save(run_dir, state, 'answers_updated', changed_answers=changed, invalidated=invalidated)


def assess_engagement(run_dir, *, catalogue=UNSET, readiness_options=None, _action='assessed'):
    run_dir = _path(run_dir)
    with _lock(run_dir):
        state = load_engagement(run_dir)
        invalidated = _refresh(state, catalogue=catalogue, readiness_options=readiness_options)
        return _save(run_dir, state, _action, invalidated=invalidated)


def status_engagement(run_dir, refresh=False):
    return assess_engagement(run_dir) if refresh else load_engagement(run_dir)


def resume_engagement(run_dir):
    run_dir = _path(run_dir)
    with _lock(run_dir):
        recovered = False
        if not (run_dir / 'state.json').exists():
            revisions = sorted((run_dir / 'revisions').glob('[0-9]*.json'))
            _require(bool(revisions), 'No committed state or recovery revision exists; start a new engagement.')
            state = _validate_state(run_dir, _json(revisions[-1]))
            _atomic_write(run_dir / 'state.json', _bytes(state))
            recovered = True
        state = load_engagement(run_dir)
        invalidated = _refresh(state)
        return _save(run_dir, state, 'resumed_after_interrupted_start' if recovered else 'resumed', invalidated=invalidated)


def record_evidence(run_dir, path, kind, depends_on=('source', 'catalogue', 'target', 'discovery')):
    """Register an external JSON receipt, always unverified; never copy its contents."""
    path, run_dir = _path(path), _path(run_dir)
    _, receipt_hash = _nonsecret_json(path)
    _require(type(kind) is str and re.fullmatch(r'[a-z][a-z0-9_-]{0,79}', kind), 'Evidence kind must be a short lowercase identifier.')
    _require(type(depends_on) in (list, tuple) and depends_on and set(depends_on) <= DEPENDENCIES and len(set(depends_on)) == len(depends_on), 'Evidence dependencies must be distinct known input names.')
    with _lock(run_dir):
        state = load_engagement(run_dir)
        # Refresh pins before accepting a receipt; no stale saved fingerprint binding.
        invalidated = _refresh(state)
        bindings = _bindings(state)
        state['evidence'].append({'id': 'receipt-' + uuid.uuid4().hex, 'kind': kind, 'status': 'current',
          'assurance': 'recorded_unverified', 'recorded_at': _now(),
          'dependencies': {key: bindings[key] for key in depends_on},
          'receipt': {'path': str(path), 'sha256': receipt_hash},
          'qualification': 'Contents and claimed outcomes are not authenticated by this workflow.'})
        return _save(run_dir, state, 'evidence_recorded', invalidated=invalidated)


def record_handoff(run_dir, review_path, artifact_root, audience=None, include=None):
    """Record prepared files before export; no test or approval claims are trusted."""
    run_dir = _path(run_dir)
    with _lock(run_dir):
        state = load_engagement(run_dir)
        invalidated = _refresh(state)
        _require(state['readiness']['generation_ready'], 'Resolve interview and evidence prerequisites before recording a prepared handoff.')
        audience = audience or state['answers'].get('audience') or 'engineer'
        snapshot = _handoff_snapshot(state, review_path, artifact_root, audience, include)
        for item in state['evidence']:
            if item['kind'] == 'prepared_handoff' and item['status'] == 'current':
                item.update(status='superseded', superseded_at=_now())
        state['evidence'].append({'id': 'handoff-' + uuid.uuid4().hex,
          'kind': 'prepared_handoff', 'status': 'current', 'assurance': 'file_integrity_only',
          'recorded_at': _now(), 'dependencies': _bindings(state), 'handoff': snapshot})
        _delivery_progress(state)
        return _save(run_dir, state, 'handoff_recorded', invalidated=invalidated)


def _cli_answers(args):
    values = _nonsecret_json(args.answers)[0] if getattr(args, 'answers', None) else {}
    _require(type(values) is dict, '--answers must contain an answers object.')
    for assignment in getattr(args, 'set', []) or []:
        _require('=' in assignment, '--set requires KEY=VALUE; quote JSON arrays in your shell.')
        key, value = assignment.split('=', 1)
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
        values[key] = value
    return values


def _cli_options(args):
    path = getattr(args, 'readiness_options', None)
    if path is None:
        return None
    value = _nonsecret_json(path)[0]
    _require(type(value) is dict, '--readiness-options must contain a nonsecret JSON object.')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('init', 'start', 'answer', 'assess', 'status', 'resume', 'record-handoff'):
        p = sub.add_parser(command)
        p.add_argument('--run', type=Path, required=True, help='Local engagement folder outside the input repository.')
        p.add_argument('--no-render', action='store_true', help='Skip the offline START_HERE.html refresh.')
        p.add_argument('--json', action='store_true', help='Print complete durable state instead of a short next-action summary.')
        if command in ('init', 'start'):
            p.add_argument('--repo', type=Path, required=True)
        if command in ('init', 'start', 'answer'):
            p.add_argument('--answers', type=Path, help='JSON answers object; never a credentials file.')
            p.add_argument('--set', action='append', metavar='KEY=VALUE')
        if command in ('init', 'start', 'answer', 'assess'):
            p.add_argument('--catalogue', type=Path)
            p.add_argument('--readiness-options', type=Path, help='Nonsecret JSON scan limits, include_paths, or a Coalesce contract; saved for resume.')
        if command == 'status':
            p.add_argument('--refresh', action='store_true')
        if command == 'record-handoff':
            p.add_argument('--review', type=Path, required=True)
            p.add_argument('--artifact-root', type=Path, required=True)
            p.add_argument('--audience', choices=('reviewer', 'engineer', 'audit'))
            p.add_argument('--include', nargs='+', choices=sorted(DELIVERABLES))
    args = parser.parse_args(argv)
    try:
        if args.command in ('init', 'start'):
            state = start_engagement(args.repo, args.run, _cli_answers(args), catalogue=args.catalogue, readiness_options=_cli_options(args))
        elif args.command == 'answer':
            state = update_answers(args.run, _cli_answers(args), catalogue=args.catalogue if args.catalogue else UNSET, readiness_options=_cli_options(args))
        elif args.command == 'assess':
            state = assess_engagement(args.run, catalogue=args.catalogue if args.catalogue else UNSET, readiness_options=_cli_options(args))
        elif args.command == 'resume':
            state = resume_engagement(args.run)
        elif args.command == 'record-handoff':
            state = record_handoff(args.run, args.review, args.artifact_root, args.audience, args.include)
        else:
            state = status_engagement(args.run, refresh=args.refresh)
        if not args.no_render:
            try:
                from delivery_portal import render_engagement
                render_engagement(state, _path(args.run) / 'START_HERE.html')
            except (ImportError, ValueError, OSError, TypeError) as error:
                print('State is saved; offline page refresh unavailable: ' + str(error), file=sys.stderr)
        if args.json:
            print(json.dumps(state, indent=2))
        else:
            print('Engagement ' + state['engagement_id'] + ' — ' + state['status'])
            print('State: ' + str(_path(args.run) / 'state.json'))
            for action in state['next_actions']:
                print('- ' + action['action'])
            print('Assessment is read-only. No execution or business approval is implied.')
        return 0
    except (ValueError, OSError, ImportError, KeyError, TypeError) as error:
        print('Guided workflow: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
