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
               'execution_mode', 'audience', 'metadata_policy', 'naming_policy',
               'migration_scope', 'input_handling', 'security_reviewer',
               'business_reviewer', 'catalogue_authority', 'dbt_runtime', 'delivery_destination',
               'personal_data'}
DELIVERABLES = {'implementation', 'diagrams', 'documentation', 'dictionary',
                'validation', 'sample_data', 'technical_audit'}
ENUMS = {'engagement_type': {'migration', 'refactor', 'new_model', 'blind_test'},
         'migration_scope': {'model_only', 'model_semantic', 'full_dashboard'},
         'input_handling': {'metadata_only', 'pre_sanitized', 'protected_environment'},
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
    'migration_scope': ('Do you need the warehouse model, the model and semantic layer, or a complete dashboard migration?', ['model_only', 'model_semantic', 'full_dashboard']),
    'input_handling': ('Which approved input boundary applies to this engagement?', ['metadata_only', 'pre_sanitized', 'protected_environment']),
    'engagement_type': ('What are we doing: migrating, refactoring, designing a new model, or running a blind test?', ['migration', 'refactor', 'new_model', 'blind_test']),
    'priority_domain': ('Which business domain, report, or decision should we handle first?', []),
    'framework': ('How should the target transformations be delivered?', list(FRAMEWORKS)),
    'warehouse': ('Which warehouse will the target use? If you mean GCP, confirm whether it is BigQuery.', list(WAREHOUSES)),
    'semantic_target': ('Should we retain the semantic engine, target a named engine, or leave semantic implementation out of scope?', ['retain_existing', 'omni', 'none']),
    'deliverables': ('Which handoff outputs do you want?', sorted(DELIVERABLES)),
    'delivery_destination': ('Which new version directory should receive the verified handoff? Supply an absolute path.', []),
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
        if key == 'dbt_runtime':
            from dbt_runtime import validate_selection
            result[key] = validate_selection(value)
            continue
        if key == 'personal_data':
            from personal_data import normalize
            result[key] = normalize(value)
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
            if key == 'delivery_destination':
                from delivery_transfer import validate_destination
                value = str(validate_destination(value))
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
    if answers.get('semantic_target') == 'omni' or answers.get('engagement_type') == 'migration':
        fields += ['migration_scope', 'input_handling']
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
    # delivery_destination is private transfer logistics. It must not invalidate
    # source/design/approval or artifact-content bindings when it alone changes.
    target = {key: answers.get(key) for key in ('framework', 'warehouse', 'semantic_target')}
    # Preserve historical fingerprints when the feature was never selected.
    # Once supplied, all choices participate in invalidation, including null.
    for key in ('metadata_policy', 'naming_policy'):
        if key in answers:
            target[key] = answers[key]
    for key in ('migration_scope', 'input_handling', 'security_reviewer', 'business_reviewer', 'catalogue_authority'):
        if key in answers:
            target[key] = answers[key]
    if answers.get('personal_data') is not None:
        # A changed personal-data register invalidates reviews built without it.
        target['personal_data_sha256'] = _digest(answers['personal_data'])
    target['sha256'] = _digest(target)
    runtime = {key: answers.get(key) for key in ('host', 'environment', 'execution_mode')}
    runtime['execution_mode'] = runtime['execution_mode'] or 'candidate_only'
    if 'dbt_runtime' in answers:
        runtime['dbt_runtime'] = answers['dbt_runtime']
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


def _handoff_snapshot(state, review_path, artifact_root, audience, include, *, checkpoint=False):
    """Validate actual selected files, without interpreting reported test results."""
    from delivery_portal import validate_review, resolve_selection, select_artifacts
    review_path, artifact_root = _path(review_path), _path(artifact_root)
    review, review_hash = _nonsecret_json(review_path)
    validate_review(state, review)
    selected_categories = resolve_selection(state, audience, include)
    artifacts = select_artifacts(review, artifact_root, audience, selected_categories)
    _require(checkpoint or bool(artifacts), 'No artifacts match the handoff selection.')
    review_evidence = {}
    if state.get('workflow', {}).get('migration_inventory'):
        from migration_inventory import summarize as inventory_summary
        review_evidence['migration_inventory_sha256'] = _digest(inventory_summary(state))
    if state.get('workflow', {}).get('consumer_contracts'):
        from consumer_contracts import summarize as consumer_summary
        review_evidence['consumer_contracts_sha256'] = _digest(consumer_summary(state))
    if state.get('workflow', {}).get('upstream_context'):
        from upstream_context import scope_bindings as upstream_bindings
        review_evidence['upstream_context_sha256'] = _digest(upstream_bindings(state))
    if state.get('workflow', {}).get('staging_ports'):
        from staging_ports import scope_bindings as port_bindings
        review_evidence['staging_ports_sha256'] = _digest(port_bindings(state))
    if state.get('workflow', {}).get('naming_governance'):
        from naming_governance import summarize as naming_summary
        from naming_artifacts import summary as naming_artifact_summary
        review_evidence['naming_governance_sha256'] = _digest({
            'policy': naming_summary(state), 'artifacts': naming_artifact_summary(state)})
    if state.get('workflow', {}).get('review_assurance'):
        from review_assurance import records, public_summary
        review_evidence['review_evidence_sha256'] = _digest({'records': records(state), 'current': public_summary(state)})
    if state.get('workflow', {}).get('migration_intents'):
        from migration_intent import summary as intent_summary
        from migration_artifacts import summary as artifact_summary
        review_evidence['migration_intent_sha256'] = _digest({
            'records': state['workflow']['migration_intents'], 'current': intent_summary(state),
            'candidate_retention': artifact_summary(state)})
    if state.get('workflow', {}).get('migration_review'):
        from migration_review import fingerprint
        review_evidence['migration_review_sha256'] = fingerprint(state)
    if state.get('workflow', {}).get('domain_journey'):
        from domain_workflow import public_summary
        review_evidence['domain_journey_sha256'] = _digest(public_summary(state))
    if state.get('workflow', {}).get('legacy_alignment'):
        from legacy_alignment import fingerprint
        review_evidence['legacy_alignment_sha256'] = fingerprint(state)
    if state.get('workflow', {}).get('migration_planning'):
        from migration_planning import fingerprint
        review_evidence['migration_planning_sha256'] = fingerprint(state)
    if any(state.get('workflow', {}).get(k) for k in ('design_coverage', 'design_evidence', 'independent_design_reviews')):
        from design_readiness import summarize
        from design_evidence import scope_bindings as evidence_bindings
        from design_coverage import scope_bindings as coverage_bindings
        review_evidence['design_readiness_sha256'] = _digest({'summary': summarize(state),
            'evidence': evidence_bindings(state), 'coverage': coverage_bindings(state),
            'reviews': state['workflow'].get('independent_design_reviews', {})})
    return {**({'checkpoint': True} if checkpoint else {}), **review_evidence,
            'review_path': str(review_path), 'review_sha256': review_hash,
            'artifact_root': str(artifact_root), 'audience': audience,
            'deliverables': sorted(selected_categories), 'choices_sha256': _delivery_choices(state),
            'artifacts': [{'path': a['path'], 'destination': a['destination'],
                           'sha256': a['sha256'], 'bytes': len(a['content'])} for a in artifacts]}


def _provisional_handoff_allowed(state):
    """A current scoped draft request permits delivery, never native approval."""
    from engagement_stages import draft_entities
    models = {e['id'] for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}
    return bool(models and models <= draft_entities(state))


def _delivery_progress(state):
    prepared = next((item for item in reversed(state['evidence'])
                     if item['kind'] in {'prepared_handoff', 'checkpoint_handoff'} and item['status'] == 'current'
                     and item.get('assurance') == 'file_integrity_only' and 'handoff' in item), None)
    state.pop('delivery', None)
    if prepared and prepared['kind'] == 'checkpoint_handoff':
        snapshot = prepared['handoff']
        if state['status'] == 'handoff_prepared':
            state['status'] = 'candidate_preparation_ready' if state['readiness']['generation_ready'] else 'needs_evidence'
        state['delivery'] = {'status': 'checkpoint', 'artifact_count': len(snapshot['artifacts']),
            'assurance': 'file_integrity_only', 'audience': snapshot['audience'],
            'deliverables': snapshot['deliverables'],
            'qualification': 'Incomplete checkpoint only; preparation, validation and approval remain separate.'}
        state['next_actions'] = [a for a in state['next_actions']
                                 if a['id'] not in {'review_prepared_handoff', 'review_checkpoint_handoff'}]
        state['next_actions'].insert(0, {'id': 'review_checkpoint_handoff', 'scope': 'review',
            'action': 'Run finalize_delivery.py --checkpoint to review the available files, then resume outstanding work. This is not a completed handoff.'})
        return
    provisional = not state['readiness']['generation_ready'] and _provisional_handoff_allowed(state)
    if prepared is None or (not state['readiness']['generation_ready'] and not provisional):
        if state['status'] == 'handoff_prepared':
            state['status'] = 'candidate_preparation_ready' if state['readiness']['generation_ready'] else 'needs_evidence'
            state['next_actions'] = [a for a in state['next_actions'] if a['id'] != 'review_prepared_handoff']
        return
    snapshot = prepared['handoff']
    state['status'] = 'handoff_prepared'
    state['delivery'] = {'status': 'provisional_prepared' if provisional else 'prepared', 'artifact_count': len(snapshot['artifacts']),
                         'assurance': 'file_integrity_only', 'audience': snapshot['audience'],
                         'deliverables': snapshot['deliverables'],
                         'qualification': 'Prepared files only; business, native runtime and deployment approval remain separate.'}
    state['next_actions'] = [{'id': 'review_prepared_handoff', 'scope': 'review',
                             'action': 'Prepared files are not yet a verified delivery. Run finalize_delivery.py to create and verify START_HERE.html, the selected 01_Model design files and the portable ZIP, then review the handoff. Business, access and native target checks remain separate.'}]


def _invalidate(state):
    current = _bindings(state)
    invalidated = []
    for item in state['evidence']:
        if item['status'] != 'current':
            continue
        changed = [key for key, value in item['dependencies'].items() if current[key] != value]
        # A legacy assessment did not evaluate an explicitly selected engine.
        # Keep legacy behavior until a selection is made, then require refresh.
        if (item.get('kind') == 'static_readiness' and 'runtime' not in item['dependencies']
                and state['inputs']['runtime'].get('dbt_runtime') is not None):
            changed.append('runtime')
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
                                                     pinned['audience'], pinned['deliverables'],
                                                     checkpoint=pinned.get('checkpoint', False))
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


def _stage_progress(state):
    if not state.get('workflow'):
        return
    from engagement_stages import refresh, public_view
    refresh(state)
    stage_view = public_view(state, _refresh=False)
    # Preserve discovery and file-review actions; candidate readiness does not
    # substitute for the current stage's reviewed inputs.
    state['next_actions'] = [a for a in state['next_actions'] if a['scope'] in {'discovery', 'readiness', 'review'}
                             and not a['id'].startswith(('legacy_comparison:', 'migration_planning:'))]
    from domain_workflow import public_summary as domain_summary
    journey = domain_summary(state)
    if state['workflow'].get('migration_planning'):
        from migration_planning import public_summary as planning_summary
        for row in planning_summary(state)['domains']:
            if journey and row['domain_id'] != journey['active_domain_id']:
                continue
            if row.get('freshness') != 'current' or not row.get('plan_sha256'):
                state['next_actions'].append({'id': 'migration_planning:' + row['domain_id'], 'scope': 'review',
                    'action': 'Prepare or refresh this domain migration plan from retained mappings. '
                              'Missing planning context does not block explicitly requested provisional code.'})
    if state['workflow'].get('legacy_alignment'):
        from legacy_alignment import public_summary as alignment_summary
        for row in alignment_summary(state)['domains']:
            if not row['comparison_requested'] or journey and row['domain_id'] != journey['active_domain_id']:
                continue
            action = None
            if row['baseline_status'] in {'not_supplied', 'unavailable'}:
                action = 'Supply available historical schemas or logic, or retain the missing-evidence gap.'
            elif row['alignment_status'] in {'unassessed', 'stale', 'unavailable'}:
                action = 'Prepare or refresh the historical comparison using retained evidence before reviewing this domain.'
            if action:
                state['next_actions'].append({'id': 'legacy_comparison:' + row['domain_id'], 'scope': 'review',
                    'action': action + ' Explicitly requested provisional code remains available.'})
    if journey:
        state['next_actions'].insert(0, {'id': 'domain_journey', 'scope': 'stage', 'action': journey['next_action']})
        # Do not prompt an all-domain stage while a domain journey is active.
        return
    state['next_actions'].append({'id': 'continue_' + stage_view['current_stage'],
                                 'scope': 'stage', 'action': stage_view['next_action']})


def _refresh(state, *, catalogue=UNSET, readiness_options=None, stage_progress=True):
    from run_control import observe_runtime
    observe_runtime(state)
    repo = state['inputs']['source']['path']
    _require(Path(repo).is_dir(), 'Source repository is unavailable; restore it before refreshing this engagement.')
    options = dict(readiness_options if readiness_options is not None else state.get('readiness_options', {}))
    _secrets(options)
    state['readiness_options'] = options
    a = state['answers']
    from delivery_assurance import pending_summary
    state['delivery_assurance'] = pending_summary(a.get('migration_scope'))
    framework = a.get('framework') if _known(a.get('framework')) else None
    warehouse = a.get('warehouse') if _known(a.get('warehouse')) else None
    assessment_options = dict(options)
    if 'dbt_runtime' in a:
        assessment_options['dbt_runtime'] = a['dbt_runtime']
    platform = _assess_repository(repo, framework, warehouse, **assessment_options)
    _require(type(platform) is dict and platform.get('schema_version') == 1, 'Readiness collector returned an unsupported schema.')
    from source_roots import observe
    platform = observe(state, platform, _assess_repository, framework, warehouse, assessment_options)
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
                         'next_action': 'Supply a nonsecret physical catalogue with assess --catalogue PATH for physical verification. Continue assessment or explicitly requested provisional code while it is missing.'})
    elif not state['inputs']['catalogue']['available']:
        blockers.append({'id': 'restore_catalogue', 'summary': 'Previously recorded catalogue is unavailable.',
                         'next_action': 'Restore the recorded catalogue or explicitly supply its replacement.'})
    complete = platform.get('coverage', {}).get('complete') is True and fingerprint.get('complete') is True
    capable = platform.get('capabilities', {}).get('generation', {}).get('status') == 'agent_assisted'
    generation_ready = not missing and complete and capable and not blockers
    # Unknown business semantics are precisely what an explicit draft request
    # can carry forward. Target, scope and disclosure choices still must be known.
    provisional_missing = set(missing) - {'trusted_outputs', 'retained_behavior', 'corrected_behavior'}
    provisional_available = not provisional_missing and complete and capable and all(
        item['id'] in {'capture_catalogue', 'restore_catalogue'} for item in blockers)
    state['readiness'] = {'interview_complete': not missing, 'generation_ready': generation_ready,
                          'provisional_generation_available': provisional_available,
                          'assessment_allowed': True, 'execution_authorized': False,
                          'missing_answers': missing, 'questions': questions, 'platform': platform,
                          'assessed_at': _now(),
                          'qualification': 'Candidate preparation guidance only. A catalogue hash proves captured bytes, not normalized physical bindings. verify_catalogue, model, independent baseline and execution gates remain pending; this workflow does not run or replace them.'}
    if a.get('semantic_target') == 'omni':
        from omni_modeler import plan_request
        state['specialist_requests'] = [plan_request(fingerprint['value'], warehouse=warehouse if warehouse in WAREHOUSES else None)]
    else:
        state['specialist_requests'] = []
    if missing:
        state['status'] = 'interview_pending'
    elif generation_ready:
        state['status'] = 'candidate_preparation_ready'
    elif blockers or not complete:
        state['status'] = 'needs_evidence'
    else:
        state['status'] = 'assessment_ready'
    state['next_actions'] = [{'id': 'answer_' + q['id'], 'action': q['prompt'], 'scope': 'discovery'} for q in questions]
    if state['specialist_requests']:
        state['next_actions'].append({'id': 'prepare_omni_modeler', 'scope': 'specialist',
            'action': 'Prepare a pinned Omni Modeler task from approved inputs and invoke the available host adapter. This routing request has not run a specialist.'})
    if not missing:
        state['next_actions'] += [{'id': f['id'], 'action': f.get('next_action', f['summary']), 'scope': 'readiness'} for f in blockers]
        if not generation_ready and not blockers:
            state['next_actions'].append({'id': 'review_generation_contract', 'action': platform.get('capabilities', {}).get('generation', {}).get('reason', 'Resolve the generation contract and coverage gaps.'), 'scope': 'readiness'})
        if generation_ready:
            state['next_actions'].append({'id': 'prepare_selected_handoff', 'action': 'Verify the physical catalogue and review the scoped model contract before generating selected artifacts. Independent baseline and execution gates remain separate qualified actions.', 'scope': 'generation'})
    _delivery_progress(state)
    if stage_progress:
        _stage_progress(state)
    bindings = _bindings(state)
    assessment_dependencies = ('source', 'target', 'runtime') if 'dbt_runtime' in a else ('source', 'target')
    state['evidence'].append({'id': 'assessment-' + uuid.uuid4().hex, 'kind': 'static_readiness',
                              'status': 'current', 'assurance': 'static_read_only', 'recorded_at': _now(),
                              'dependencies': {key: bindings[key] for key in assessment_dependencies},
                              'result_sha256': _digest(platform), 'summary': _assessment_summary(platform),
                              'result_ref': None})
    return invalidated


def _save(run_dir, state, action, *, changed_answers=(), invalidated=()):
    from source_roots import ensure_output
    ensure_output(state, run_dir)
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
    from engagement_state_store import encode
    payload = encode(run_dir, state)
    _atomic_write(run_dir / revision_path, payload, replace=False)
    _atomic_write(run_dir / 'state.json', payload)
    return state


def _validate_state(run_dir, state):
    from engagement_state_store import hydrate, is_index
    stored = state
    state = hydrate(run_dir, stored)
    _require(type(state) is dict, 'Engagement state must be a JSON object.')
    _require(state.get('schema_version') == SCHEMA_VERSION and state.get('kind') == 'guided_engagement', 'Unsupported engagement state schema.')
    _require(state.get('status') in STATUSES, 'State contains an unsupported claimed lifecycle status.')
    _require(type(state.get('revision')) is int and state['revision'] > 0, 'State revision must be a positive integer.')
    _require(state.get('state_sha256') == _digest({k: v for k, v in state.items() if k != 'state_sha256'}), 'State integrity check failed; restore the last committed revision.')
    revision = run_dir / 'revisions' / ('%06d.json' % state['revision'])
    _require(revision.is_file(), 'State does not match its immutable revision.')
    committed = _json(revision)
    _require(committed == stored if is_index(stored) else hydrate(run_dir, committed) == state,
             'State does not match its immutable revision.')
    from source_roots import ensure_output
    ensure_output(state, run_dir)
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
        from engagement_stages import empty_workflow
        state['workflow'] = empty_workflow()
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
            stored = _json(revisions[-1])
            _validate_state(run_dir, stored)
            _atomic_write(run_dir / 'state.json', _bytes(stored))
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


def record_handoff(run_dir, review_path, artifact_root, audience=None, include=None, *, checkpoint=False):
    """Record prepared files before export; no test or approval claims are trusted."""
    run_dir = _path(run_dir)
    with _lock(run_dir):
        state = load_engagement(run_dir)
        invalidated = _refresh(state)
        _require(checkpoint or state['readiness']['generation_ready'] or _provisional_handoff_allowed(state),
                 'Record a current scoped provisional request or resolve interview prerequisites before recording a prepared handoff; use --checkpoint for incomplete work.')
        audience = audience or state['answers'].get('audience') or 'engineer'
        snapshot = _handoff_snapshot(state, review_path, artifact_root, audience, include, checkpoint=checkpoint)
        for item in state['evidence']:
            if item['kind'] in {'prepared_handoff', 'checkpoint_handoff'} and item['status'] == 'current':
                item.update(status='superseded', superseded_at=_now())
        state['evidence'].append({'id': 'handoff-' + uuid.uuid4().hex,
          'kind': 'checkpoint_handoff' if checkpoint else 'prepared_handoff', 'status': 'current', 'assurance': 'file_integrity_only',
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


def stage_action(run_dir, action, *, document=None, entities=None, stage=None,
                 artifact_root=None, policy=None, attestation=None):
    """Persist stage work using the same lock, fresh context and immutable history."""
    import engagement_stages as stages
    run_dir = _path(run_dir)
    with _lock(run_dir):
        state = load_engagement(run_dir)
        invalidated = _refresh(state, stage_progress=False)
        if document is not None:
            _secrets(document)
        if action in ('configure-frontend', 'record-frontend-progress'):
            import frontend_continuation
            if action == 'configure-frontend':
                frontend_continuation.choose(state, document)
            else:
                frontend_continuation.record_progress(state, document)
        elif action == 'register-source-roots':
            from source_roots import register
            register(state, document, run_dir)
            invalidated.extend(_refresh(state, stage_progress=False))
        elif action == 'record-migration-inventory':
            from migration_inventory import register
            register(state, document, run_dir)
        elif action == 'record-upstream-context':
            from upstream_context import register
            register(state, document, run_dir)
            state['workflow'].pop('upstream_context_view', None)
            state['workflow'].pop('upstream_context_packet', None)
        elif action in ('upstream-context', 'upstream-context-packet'):
            import upstream_context
            stages.fields(document, set(), {'entity_ids', 'domain_id'})
            _require(bool(document.get('entity_ids')) or bool(document.get('domain_id')),
                     'Select entity_ids or domain_id for upstream context.')
            selected, domain_id = document.get('entity_ids'), document.get('domain_id')
            if selected is not None:
                stages.ids(selected, {e['id'] for e in stages.design(state)['entities']})
            if domain_id is not None:
                stages.text(domain_id)
                from domain_workflow import _domain, _models
                domain = _domain(state, domain_id)
                _require(selected is None or set(selected) <= _models(state, domain),
                         'Upstream context entity selection exceeds its chosen domain.')
            if action == 'upstream-context':
                state['workflow']['upstream_context_view'] = upstream_context.derive(state, selected, domain_id)
            else:
                state['workflow']['upstream_context_packet'] = upstream_context.packet(state, selected, domain_id)
        elif action in ('configure-staging-ports', 'record-staging-ports'):
            import staging_ports
            if action == 'configure-staging-ports':
                staging_ports.configure(state, document)
            else:
                staging_ports.register(state, document, run_dir)
        elif action in ('record-consumer-contracts', 'consumer-review-bindings', 'review-consumer-changes'):
            import consumer_contracts
            if action == 'record-consumer-contracts':
                root = _path(artifact_root) if artifact_root is not None else None
                if root is not None:
                    from source_roots import ensure_output
                    ensure_output(state, root)
                    _require(root != run_dir and root not in run_dir.parents and run_dir not in root.parents,
                             'Consumer artifacts must be separate from engagement state')
                consumer_contracts.register(state, document, root)
            elif action == 'consumer-review-bindings':
                stages.fields(document, {'contract_ids'})
                state['workflow']['consumer_review_request'] = consumer_contracts.review_bindings(state, document['contract_ids'])
            else:
                consumer_contracts.review(state, document)
        elif action in ('configure-naming', 'record-model-identities'):
            import naming_governance
            (naming_governance.configure if action == 'configure-naming' else naming_governance.register)(state, document)
        elif action == 'naming-packet':
            from naming_context import packet_contract
            state['workflow']['naming_packet'] = packet_contract(state, entities)
        elif action == 'check-naming':
            from naming_artifacts import record
            from source_roots import ensure_output
            root = _path(artifact_root)
            ensure_output(state, root)
            _require(root != run_dir and root not in run_dir.parents and run_dir not in root.parents,
                     'Naming artifacts must be separate from engagement state')
            record(state, document, root)
        elif action in ('configure-migration-intent', 'migration-assessment-bindings',
                        'record-migration-assessment', 'migration-intent-packet'):
            import migration_intent
            if action == 'configure-migration-intent':
                migration_intent.configure(state, document)
            elif action == 'record-migration-assessment':
                migration_intent.record_assessment(state, document)
            else:
                stages.fields(document, {'domain_id'})
                if action == 'migration-assessment-bindings':
                    state['workflow']['migration_assessment_request'] = migration_intent.assessment_bindings(state, document['domain_id'])
                else:
                    state['workflow']['migration_intent_packet'] = migration_intent.packet_contract(state, document['domain_id'])
        elif action == 'migrate-stages':
            stages.migrate(state)
        elif action == 'record-delivery-plan':
            from delivery_plan import record_plan
            record_plan(state, document)
        elif action in ('select-batch', 'pause-batch', 'complete-batch'):
            import domain_batches
            if action == 'select-batch':
                domain_batches.select(state, document)
            else:
                domain_batches.finish(state, document, pause=action == 'pause-batch')
        elif action in ('register-domain-classification', 'domain-classification-packet'):
            import domain_classification
            if action == 'register-domain-classification':
                domain_classification.register(state, document)
            else:
                stages.fields(document, {'domain_id'})
                state['workflow']['domain_classification_packet'] = domain_classification.packet(state, document['domain_id'])
        elif action in ('configure-standards', 'preview-standards', 'standards-packet'):
            import modeling_standards
            if action == 'configure-standards': modeling_standards.configure(state, document)
            elif action == 'preview-standards': modeling_standards.preview(state, document)
            else: state['workflow']['standards_packet'] = modeling_standards.packet(state, entities)
        elif action in ('register-domains', 'select-domain', 'pause-domain', 'complete-domain'):
            import domain_workflow
            {'register-domains': domain_workflow.register, 'select-domain': domain_workflow.select_domain,
             'pause-domain': domain_workflow.pause_domain, 'complete-domain': domain_workflow.complete_domain}[action](state, document)
            if action == 'select-domain' and not _known(state['answers'].get('priority_domain')):
                # Retain the actual user choice; do not ask the intake question again.
                selected = next(d for d in domain_workflow.ledger(state)['domains'] if d['id'] == document['domain_id'])
                state['answers']['priority_domain'] = selected['name']
                invalidated += _refresh(state)
        elif action == 'import-design':
            stages.import_design(state, document)
        elif action == 'assemble-design':
            from design_builder import assemble
            stages.import_design(state, assemble(document))
        elif action == 'record-design-coverage':
            from design_coverage import record
            record(state, document, run_dir)
        elif action == 'record-design-evidence':
            from design_evidence import record
            record(state, document, run_dir)
        elif action == 'independent-review-bindings':
            from design_evidence import review_bindings
            state['workflow']['independent_review_request'] = review_bindings(state, entities)
        elif action == 'record-independent-review':
            from design_evidence import record_review
            record_review(state, document, run_dir)
        elif action == 'record-coverage':
            from mapping_coverage import register
            register(state, document, run_dir)
        elif action == 'record-reuse':
            from reuse_coverage import register
            register(state, document, run_dir)
        elif action == 'reconcile-design':
            from workflow_reconciliation import register
            register(state, document, run_dir)
        elif action == 'record-business-rules':
            from business_rules import register
            register(state, document, run_dir)
        elif action == 'review-business-rules':
            from business_rules import record_decisions
            record_decisions(state, document)
        elif action in ('configure-migration-planning', 'record-migration-plan', 'edit-migration-items'):
            import migration_planning
            if action == 'configure-migration-planning':
                migration_planning.configure(state, document)
            elif action == 'record-migration-plan':
                migration_planning.register_plan(state, document, run_dir)
            else:
                migration_planning.edit_items(state, document, run_dir)
        elif action in ('configure-legacy-comparison', 'record-legacy-baseline',
                        'record-legacy-alignment', 'review-legacy-alignment'):
            import legacy_alignment
            if action == 'configure-legacy-comparison':
                legacy_alignment.configure(state, document)
            elif action == 'record-legacy-baseline':
                legacy_alignment.register_baseline(state, document, run_dir)
            elif action == 'record-legacy-alignment':
                legacy_alignment.register_alignment(state, document, run_dir)
            else:
                legacy_alignment.record_decisions(state, document)
        elif action == 'recommend-shared-models':
            from shared_model_candidates import register
            register(state, document, run_dir)
        elif action == 'extract-periscope':
            from migration_review import extract_periscope
            extract_periscope(state, document, run_dir)
        elif action == 'record-migration-validation':
            from migration_review import register_parity
            register_parity(state, document, run_dir)
        elif action == 'migration-bindings':
            from migration_review import parity_bindings
            state['workflow']['migration_validation_bindings'] = parity_bindings(state, entities)
        elif action == 'answer-decisions':
            stages.record_responses(state, document)
        elif action == 'review-bindings':
            state['workflow']['review_request'] = stages.review_bindings(state, entities)
        elif action == 'draft-bindings':
            state['workflow']['draft_request_bindings'] = stages.draft_bindings(state, entities)
        elif action == 'request-draft':
            stages.record_draft_request(state, entities, document)
        elif action == 'approve-design':
            if document is not None:
                _require(policy is None and attestation is None, 'Choose human review recording or signed review, not both')
                stages.record_design_review(state, entities, document)
            else:
                _require(policy is not None and attestation is not None, 'An attributable human review record or external signed attestation is required')
                from deployment_authority import outside
                from source_roots import approved_roots
                outside(policy, (run_dir, *approved_roots(state)))
                stages.approve_design(state, entities, policy, attestation)
        elif action == 'assess-effort':
            stages.assess_development(state, document)
        elif action == 'prepare-dispatch':
            from run_control import prepare_dispatch
            state['last_work_action'] = prepare_dispatch(state, document)
        elif action == 'work-bindings':
            from run_control import assignment_bindings
            state['last_work_action'] = assignment_bindings(state, document)
        elif action == 'review-work':
            from run_control import review_work
            root = _path(artifact_root)
            _require(root != run_dir and root not in run_dir.parents and run_dir not in root.parents,
                     'Review files must be separate from engagement state')
            state['last_work_action'] = review_work(state, document, root)
        elif action in ('claim-work', 'configure-work'):
            import run_control
            state['last_work_action'] = (run_control.claim_work(state, document) if action == 'claim-work'
                                         else run_control.configure(state, document))
        elif action == 'record-dispatch':
            from run_control import record_dispatch
            state['last_work_action'] = record_dispatch(state, document)
        elif action == 'checkpoint-work':
            import run_control
            root = _path(artifact_root)
            from source_roots import ensure_output
            ensure_output(state, root)
            _require(root != run_dir and root not in run_dir.parents and run_dir not in root.parents,
                     'Checkpoint files must be separate from engagement state')
            state['last_work_action'] = run_control.checkpoint_work(state, document, root)
        elif action in ('plan-tasks', 'record-task', 'check-task'):
            root = _path(artifact_root)
            from source_roots import ensure_output
            ensure_output(state, root)
            _require(root != run_dir and root not in run_dir.parents and run_dir not in root.parents,
                     'Candidate artifacts must be separate from engagement state')
            _require(root.is_dir(), 'Artifact root must be an existing directory')
            if action == 'plan-tasks' and document is not None:
                stages.register_tasks(state, document)
            state['workflow']['artifact_root'] = str(root)
            if action == 'record-task':
                stages.record_task(state, root, document, refresh_plan=False)
            elif action == 'check-task':
                from authoring_quality import recheck_task
                recheck_task(state, root, document)
            else:
                state['workflow']['last_plan'] = stages.plan_tasks(state, root)
        elif action == 'stage':
            selected = stages.require_stage(state, stage, entities)
            state['workflow']['requested_stage'] = {'stage': stage, 'entity_ids': selected,
                'qualification': 'Stage prerequisites checked. Native execution and deployment remain separately authorized.'}
        else:
            raise ValueError('Unknown stage action')
        # Stage mutations can change a review binding after the initial refresh.
        # Invalidate the old package in this same revision, before rendering it.
        invalidated += _invalidate(state)
        _delivery_progress(state)
        _stage_progress(state)
        return _save(run_dir, state, action, invalidated=invalidated)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    stage_commands = ('register-domain-classification', 'domain-classification-packet', 'configure-standards', 'preview-standards', 'standards-packet', 'configure-frontend', 'record-frontend-progress', 'record-migration-inventory', 'record-consumer-contracts', 'consumer-review-bindings', 'review-consumer-changes', 'configure-naming', 'record-model-identities', 'check-naming', 'naming-packet', 'configure-migration-intent', 'migration-assessment-bindings', 'record-migration-assessment', 'migration-intent-packet', 'migrate-stages', 'import-design', 'assemble-design', 'record-design-coverage', 'record-design-evidence',
                      'record-upstream-context', 'upstream-context', 'upstream-context-packet', 'configure-staging-ports', 'record-staging-ports',
                      'independent-review-bindings', 'record-independent-review', 'answer-decisions', 'review-bindings', 'draft-bindings', 'request-draft',
                      'approve-design', 'assess-effort', 'plan-tasks', 'record-task', 'check-task', 'stage',
                      'claim-work', 'record-dispatch', 'checkpoint-work', 'configure-work', 'work-bindings', 'prepare-dispatch', 'review-work', 'record-delivery-plan', 'record-coverage', 'record-reuse', 'reconcile-design',
                      'record-business-rules', 'review-business-rules', 'recommend-shared-models',
                      'extract-periscope', 'record-migration-validation', 'migration-bindings',
                      'configure-legacy-comparison', 'record-legacy-baseline',
                      'record-legacy-alignment', 'review-legacy-alignment',
                      'configure-migration-planning', 'record-migration-plan', 'edit-migration-items',
                      'register-source-roots', 'register-domains', 'select-domain', 'pause-domain', 'complete-domain', 'select-batch', 'pause-batch', 'complete-batch')
    for command in ('init', 'start', 'answer', 'assess', 'status', 'resume', 'record-handoff', 'record-evidence') + stage_commands:
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
            p.add_argument('--checkpoint', action='store_true', help='Retain incomplete or provisional files without declaring a prepared handoff.')
            p.add_argument('--review', type=Path, required=True)
            p.add_argument('--artifact-root', type=Path, required=True)
            p.add_argument('--audience', choices=('reviewer', 'engineer', 'audit'))
            p.add_argument('--include', nargs='+', choices=sorted(DELIVERABLES))
        if command == 'record-evidence':
            p.add_argument('--path', type=Path, required=True)
            p.add_argument('--kind', required=True, help='Receipt type; imported claims remain unverified.')
        if command in ('register-domain-classification', 'domain-classification-packet', 'configure-standards', 'preview-standards', 'configure-frontend', 'record-frontend-progress', 'record-migration-inventory', 'record-consumer-contracts', 'consumer-review-bindings', 'review-consumer-changes', 'configure-naming', 'record-model-identities', 'check-naming', 'configure-migration-intent', 'migration-assessment-bindings', 'record-migration-assessment', 'migration-intent-packet', 'import-design', 'assemble-design', 'record-design-coverage', 'record-design-evidence', 'record-independent-review',
                       'record-upstream-context', 'upstream-context', 'upstream-context-packet', 'configure-staging-ports', 'record-staging-ports',
                       'answer-decisions', 'assess-effort', 'plan-tasks', 'record-task', 'check-task', 'request-draft',
                       'claim-work', 'record-dispatch', 'checkpoint-work', 'configure-work', 'work-bindings', 'prepare-dispatch', 'review-work', 'record-delivery-plan', 'record-coverage', 'record-reuse', 'reconcile-design',
                       'record-business-rules', 'review-business-rules', 'recommend-shared-models',
                       'extract-periscope', 'record-migration-validation',
                       'configure-legacy-comparison', 'record-legacy-baseline',
                       'record-legacy-alignment', 'review-legacy-alignment',
                       'configure-migration-planning', 'record-migration-plan', 'edit-migration-items',
                       'register-source-roots', 'register-domains', 'select-domain', 'pause-domain', 'complete-domain', 'select-batch', 'pause-batch', 'complete-batch'):
            p.add_argument('--document', type=Path, required=command != 'plan-tasks')
        if command in ('standards-packet', 'naming-packet', 'review-bindings', 'independent-review-bindings', 'approve-design', 'stage', 'draft-bindings', 'request-draft', 'migration-bindings'):
            p.add_argument('--entities', nargs='+', required=True)
        if command == 'approve-design':
            p.add_argument('--document', type=Path, help='Exact-scope human decision attributed by the trusted host; never an approval inferred from input files.')
            p.add_argument('--policy', type=Path)
            p.add_argument('--attestation', type=Path)
        if command in ('plan-tasks', 'record-task', 'check-task', 'checkpoint-work', 'review-work', 'check-naming'):
            p.add_argument('--artifact-root', type=Path, required=True)
        if command == 'record-consumer-contracts':
            p.add_argument('--artifact-root', type=Path)
        if command == 'stage':
            from engagement_stages import STAGES
            p.add_argument('--stage', choices=STAGES, required=True)
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
            state = record_handoff(args.run, args.review, args.artifact_root, args.audience, args.include,
                                   checkpoint=args.checkpoint)
        elif args.command == 'record-evidence':
            state = record_evidence(args.run, args.path, args.kind)
        elif args.command in stage_commands:
            document = _nonsecret_json(args.document)[0] if getattr(args, 'document', None) else None
            # Signed envelopes contain signatures, not private credentials.
            attestation = _json(args.attestation) if getattr(args, 'attestation', None) else None
            state = stage_action(args.run, args.command, document=document,
                entities=getattr(args, 'entities', None), stage=getattr(args, 'stage', None),
                artifact_root=getattr(args, 'artifact_root', None), policy=getattr(args, 'policy', None), attestation=attestation)
        else:
            state = status_engagement(args.run, refresh=args.refresh)
        render_failed = False
        if not args.no_render:
            try:
                from delivery_portal import render_engagement
                render_engagement(state, _path(args.run) / 'START_HERE.html')
            except (ImportError, ValueError, OSError, TypeError) as error:
                print('State is saved; offline page refresh unavailable: ' + str(error), file=sys.stderr)
                print('Handoff incomplete: repair the page refresh and finalize the delivery before reporting it ready.', file=sys.stderr)
                render_failed = True
        if args.json:
            print(json.dumps(state, indent=2))
        else:
            print('Engagement ' + state['engagement_id'] + ' — ' + state['status'])
            print('State: ' + str(_path(args.run) / 'state.json'))
            runtime = (state.get('runtime_observations') or [{}])[-1]
            print('Accelerator revision: ' + str(runtime.get('installed_revision') or 'unavailable (portable install)')
                  + '; freshness: ' + runtime.get('freshness', {}).get('status', 'unknown'))
            if args.command in ('claim-work', 'record-dispatch', 'checkpoint-work', 'configure-work', 'work-bindings', 'prepare-dispatch', 'review-work'):
                print('Work action: ' + json.dumps(state['last_work_action'], sort_keys=True))
            for action in state['next_actions']:
                print('- ' + action['action'])
            print('Assessment is read-only. No execution or business approval is implied.')
        return 2 if render_failed else 0
    except (ValueError, OSError, ImportError, KeyError, TypeError) as error:
        print('Guided workflow: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
