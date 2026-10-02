#!/usr/bin/env python3
"""Version-bound release planning and execution through a provisioned runner.

Planning is offline. Execution requires external signed approval and an installed
runner policy; candidate files and the review HTML never grant authority. Native
completion remains verification_pending until a separate validator attests the
exact run and required checks. No live qualification is inferred from fixtures.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ae_common import require, hash_json, hash_file, load_json, _json_bytes
from deployment_authority import load_policy, verify_attestation, canonical_path, outside, publication_destination, ACTIONS
import guided_workflow as workflow

MAX_RESPONSE = 8 * 1024 * 1024
MAX_RELEASE_BYTES = 100 * 1024 * 1024
REQUIRED_CHECKS = {'physical_schema', 'grain', 'fanout', 'source_reconciliation', 'metrics', 'access', 'principal_namespace'}
TERMINAL = {'published', 'deployed_verified', 'simulation_verified', 'recovered'}
LIVE_STATES = {'submitted', 'running', 'verification_pending', 'unknown_remote_state', 'failed', 'recovery_required', 'cancel_requested', 'cancelled'}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def envelope_digest(value, field):
    return digest({k: v for k, v in value.items() if k != field})


def relative_path(value):
    require(isinstance(value, str) and bool(value) and '\\' not in value, 'Invalid relative artifact path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in ('..', '.') for p in path.parts)
            and str(path) == value and ':' not in value, 'Artifact path escapes its root')
    return value


def _stable_bytes(path):
    path = canonical_path(path)
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_RELEASE_BYTES, 'Artifact must be a bounded regular file')
        data = stream.read(MAX_RELEASE_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    require(identity(before) == identity(after) and len(data) == after.st_size, 'Artifact changed during read')
    return data


def _write(path, value, *, replace=True):
    path = canonical_path(path, exists=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    workflow._atomic_write(path, _json_bytes(value) + b'\n', replace=replace)


def _safe_text(value):
    require(isinstance(value, str) and value.strip() and len(value) <= 10000, 'Expected bounded nonempty text')
    require(not workflow.SECRET_VALUE.search(value), 'Credential-like value is not allowed in the release plan')
    return value


def _assert_public(value):
    if isinstance(value, str):
        require(not workflow.SECRET_VALUE.search(value), 'Credential-like values cannot be included in a release plan')
    elif isinstance(value, list):
        for item in value:
            _assert_public(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            require((key.lower() not in {'password', 'private_key', 'access_token', 'secret_value'} or (key == 'password' and isinstance(item, str) and re.fullmatch(r'[A-Z][A-Z0-9_]+', item))), 'Credential field in release plan')
            _assert_public(item)


def _handoff(run_dir, *, refresh=False):
    from delivery_portal import context_fingerprint
    state = workflow.resume_engagement(run_dir) if refresh else workflow.load_engagement(run_dir)
    require(state['status'] == 'handoff_prepared', 'A current prepared handoff is required')
    record = next((r for r in reversed(state['evidence']) if r.get('kind') == 'prepared_handoff'
                   and r.get('status') == 'current' and r.get('assurance') == 'file_integrity_only'), None)
    require(record is not None, 'Prepared artifact evidence is missing')
    pinned = record['handoff']
    observed = workflow._handoff_snapshot(state, pinned['review_path'], pinned['artifact_root'],
                                          pinned['audience'], pinned['deliverables'])
    require(observed == pinned, 'Prepared artifact drift: refresh the handoff before deployment')
    bindings = {'engagement_id': state['engagement_id'], 'context_sha256': context_fingerprint(state),
                'handoff_manifest_sha256': workflow._digest(pinned['artifacts']),
                'source_bindings': workflow._bindings(state)}
    return state, pinned, bindings


def create_plan(run_dir, request, policy_path, output):
    """Create an exact reviewable plan. This does not authorize or execute it."""
    from deployment_adapters import validate_target, build_plan
    state, handoff, bindings = _handoff(run_dir, refresh=True)
    allowed = {'schema_version', 'action', 'destination_id', 'release_id', 'commit_sha',
               'artifacts', 'impact', 'recovery', 'required_checks', 'publication', 'qualification', 'quality', 'metadata_phase'}
    require(type(request) is dict and set(request) <= allowed and type(request.get('schema_version')) is int and request.get('schema_version') == 1, 'Invalid deployment request')
    _assert_public(request)
    action = request.get('action')
    require(action in ACTIONS, 'Choose publish_pr, deploy_development or promote')
    root = canonical_path(handoff['artifact_root'])
    policy, policy_hash = load_policy(policy_path, excluded_roots=(root, state['inputs']['source']['path']))
    require(action in policy['allowed_actions'], 'Action is not enabled by the runner policy')
    destination = request.get('destination_id')
    require(destination in policy['destinations'], 'Destination is not provisioned in the trusted runner')
    target = validate_target(policy['destinations'][destination])
    reviewed_framework = state['answers'].get('framework')
    target_framework = {'bundle': 'native_sql', 'dataform': 'native_sql', 'github': reviewed_framework}.get(target['framework'], target['framework'])
    metadata_descriptor = request.get('metadata_phase')
    require((target_framework == reviewed_framework or metadata_descriptor is not None and target_framework == 'native_sql')
            and target['warehouse'] == state['answers'].get('warehouse'), 'Destination differs from the reviewed framework/warehouse')
    require(metadata_descriptor is None or action != 'publish_pr', 'Metadata execution phases cannot be publication requests')
    if action == 'deploy_development':
        require(target['environment'] in {'development', 'dev', 'test', 'staging'}, 'Development action cannot target production')
    if action == 'promote':
        require(policy['mode'] == 'live', 'Simulation evidence cannot promote a release')
        require(bool(request.get('qualification')), 'Promotion requires prior qualified development evidence')
    release_id = request.get('release_id', 'release-' + uuid.uuid4().hex)
    require(isinstance(release_id, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', release_id), 'Invalid release ID')
    manifest = {entry['path']: entry for entry in handoff['artifacts']}
    selected = request.get('artifacts')
    require(type(selected) is list and bool(selected), 'Explicit deployment artifact selection is required')
    seen, artifacts, total = set(), [], 0
    for selected_item in selected:
        require(type(selected_item) is dict and set(selected_item) <= {'path', 'role'}, 'Invalid deployment artifact declaration')
        path = relative_path(selected_item.get('path'))
        require(path in manifest and path not in seen, 'Artifact is missing from the handoff or duplicated')
        seen.add(path)
        data = _stable_bytes(root / path)
        total += len(data)
        require(total <= MAX_RELEASE_BYTES, 'Release exceeds 100 MiB')
        require(hashlib.sha256(data).hexdigest() == manifest[path]['sha256'], 'Artifact digest mismatch')
        role = selected_item.get('role', 'model_sql')
        require(role in {'model_sql', 'validation_sql', 'deployment_plan', 'project', 'project_file', 'documentation', 'semantic'}, 'Unsupported artifact role')
        item = {'path': path, 'sha256': manifest[path]['sha256'], 'role': role}
        if role in {'model_sql', 'validation_sql', 'deployment_plan'}:
            item['content'] = data.decode('utf-8')
            _assert_public(item['content'])
        artifacts.append(item)
    # Snapshot the complete prepared package, not only entrypoint SQL: macros and
    # configuration executed by native tools must remain bound as well.
    for item in handoff['artifacts']:
        total += item['bytes'] if item['path'] not in seen else 0
        require(total <= MAX_RELEASE_BYTES, 'Prepared package exceeds 100 MiB')
    commit_sha = request.get('commit_sha')
    require(isinstance(commit_sha, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit_sha), 'An immutable candidate commit SHA is required')
    impact, recovery = request.get('impact'), request.get('recovery')
    require(type(impact) is list and bool(impact) and all(isinstance(x, str) and x.strip() for x in impact), 'Describe affected objects and operations')
    require(type(recovery) is list and bool(recovery) and all(isinstance(x, str) and x.strip() for x in recovery), 'A concrete recovery procedure is required')
    required_checks = request.get('required_checks', sorted(REQUIRED_CHECKS))
    require(type(required_checks) is list and len(set(required_checks)) == len(required_checks), 'Invalid required check list')
    required_checks = list(required_checks)
    if action != 'publish_pr':
        require(REQUIRED_CHECKS <= set(required_checks), 'Required deployment acceptance checks cannot be removed')
        if state['answers'].get('semantic_target') not in (None, 'none', 'retain_existing'):
            require('semantic' in required_checks, 'Selected semantic target requires consumer acceptance')
    metadata_binding = None
    metadata_required = (state['answers'].get('metadata_policy') or {}).get('mode') in ('comments', 'comments_and_tags')
    if metadata_descriptor is not None:
        from metadata_release import bind_phase, CHECKS as METADATA_CHECKS
        metadata_binding = bind_phase(metadata_descriptor, artifact_root=root, artifacts=artifacts,
            target=target, destination_id=destination, policy=policy, commit_sha=commit_sha,
            source_bindings=bindings['source_bindings'], reviewed_framework=reviewed_framework)
        required_checks = sorted(set(required_checks) | METADATA_CHECKS)
    elif metadata_required and action != 'publish_pr':
        required_checks = sorted(set(required_checks) | {'metadata_readback'})
    if action == 'publish_pr':
        publication_identity = _publication_destination(policy, destination, request.get('publication'))
        review, review_hash = workflow._nonsecret_json(handoff['review_path'])
        require(review_hash == handoff['review_sha256'], 'Prepared review changed')
        categories = {item['path']: item['category'] for item in review['artifacts']}
        require(all(item['role'] != 'documentation' or categories[item['path']] == 'documentation' for item in artifacts),
                'Implementation artifacts cannot be relabeled as documentation')
        publication_artifacts = [dict(item, category=categories[item['path']]) for item in handoff['artifacts']]
        native = _publication_plan(request.get('publication'), commit_sha, publication_artifacts)
    else:
        native = build_plan(target, artifacts, release_id=release_id, commit_sha=commit_sha)
    _assert_public(native)
    plan = {'schema_version': 1, 'kind': 'deployment_plan', 'id': release_id, 'created_at': now(),
            'mode': policy['mode'], 'action': action, 'destination_id': destination, 'target': target,
            'review_target': {k: state['answers'].get(k) for k in ('framework', 'warehouse', 'semantic_target')},
            'policy_sha256': policy_hash, 'bindings': bindings, 'commit_sha': commit_sha,
            'artifact_root': str(root), 'engagement_run': str(canonical_path(run_dir)),
            'artifact_manifest': handoff['artifacts'],
            'selected_artifacts': [{k: v for k, v in a.items() if k != 'content'} for a in artifacts],
            'native': native, 'impact': impact, 'recovery': recovery, 'required_checks': required_checks,
            'qualification': request.get('qualification')}
    if action == 'publish_pr':
        plan['publication_destination'] = publication_identity
    if metadata_binding is not None:
        plan['metadata_phase'] = metadata_binding
    elif metadata_required and action != 'publish_pr':
        plan['metadata_required'] = True
    if request.get('quality') is not None:
        from release_quality import bind_quality, quality_target
        plan['quality'] = bind_quality(request['quality'], root, handoff, quality_target(plan))
    plan['plan_sha256'] = envelope_digest(plan, 'plan_sha256')
    require(len(_json_bytes(plan)) <= 10 * 1024 * 1024, 'Deployment plan exceeds the bounded JSON size limit')
    output = outside(output, (root, state['inputs']['source']['path']))
    _write(output, plan, replace=False)
    return plan


def _publication_destination(policy, destination, publication):
    trusted = policy.get('publication_destinations', {}).get(destination)
    require(trusted is not None, 'Publication destination is not provisioned in the trusted runner')
    require(type(publication) is dict, 'Publication requires an exact destination')
    identity = publication_destination({key: publication.get(key) for key in ('repository', 'base', 'head')})
    require(identity == trusted, 'Publication repository/base/head differs from the trusted destination')
    return identity


def _publication_plan(publication, commit_sha, artifacts):
    """Publish an already reviewed and pushed immutable branch as a PR.

    Branch creation/commit/push can use the host's normal reviewed Git workflow;
    this adapter verifies its remote SHA before publishing and never auto-merges.
    """
    require(type(publication) is dict and set(publication) == {'repository', 'base', 'head', 'title', 'body_artifact'}, 'Publication requires repository/base/head/title/body_artifact')
    publication_destination({key: publication[key] for key in ('repository', 'base', 'head')})
    _safe_text(publication['title'])
    require(isinstance(publication['body_artifact'], str)
            and PurePosixPath(publication['body_artifact']).suffix.lower() in {'.md', '.txt'}
            and any(a['path'] == publication['body_artifact'] and a['category'] == 'documentation' for a in artifacts),
            'PR body must be a reviewed plain-text documentation artifact')
    operations = [
        {'id': 'publication-head', 'phase': 'preflight', 'effect': 'read', 'transport': 'process',
         'argv': ['gh', 'api', 'repos/' + publication['repository'] + '/commits/' + publication['head']],
         'auth_env': ['GH_TOKEN'], 'contract': 'publication_head', 'expected_identity': {'commit_sha': commit_sha}},
        {'id': 'publish-pr', 'phase': 'deploy', 'effect': 'write', 'transport': 'process',
         'depends_on': ['publication-head'], 'argv': ['gh', 'pr', 'create', '--repo', publication['repository'],
             '--base', publication['base'], '--head', publication['head'], '--draft', '--title', publication['title'],
             '--body-file', {'$artifact': publication['body_artifact']}], 'auth_env': ['GH_TOKEN'],
         'contract': 'publication_pr', 'expected_identity': {'repository': publication['repository'], 'commit_sha': commit_sha}}]
    # Only the reviewed PR body may be local; request roles cannot exempt code.
    checks = []
    for index, item in enumerate(artifacts):
        if item['path'] == publication['body_artifact']:
            continue
        checks.append({'id': 'remote-file-' + str(index), 'phase': 'preflight', 'effect': 'read', 'transport': 'process',
            'argv': ['gh', 'api', 'repos/' + publication['repository'] + '/contents/' + urllib.parse.quote(item['path'], safe='/') + '?ref=' + commit_sha],
            'auth_env': ['GH_TOKEN'], 'contract': 'publication_file', 'expected_identity': {'sha256': item['sha256']}})
    operations[1:1] = checks
    operations.append({'id': 'verify-pr', 'phase': 'observe', 'effect': 'read', 'transport': 'process',
        'argv': ['gh', 'pr', 'view', publication['head'], '--repo', publication['repository'], '--json', 'url,headRefOid,baseRefName,headRefName,state'],
        'auth_env': ['GH_TOKEN'], 'contract': 'publication_verify', 'expected_identity': dict(publication, commit_sha=commit_sha)})
    for index, operation in enumerate(operations):
        operation['depends_on'] = [operations[index-1]['id']] if index else []
    return {'adapter': 'github_pr', 'operations': operations}


def load_plan(path):
    plan = load_json(path)
    require(type(plan.get('schema_version')) is int and plan.get('schema_version') == 1 and plan.get('kind') == 'deployment_plan', 'Unsupported deployment plan')
    require(plan.get('plan_sha256') == envelope_digest(plan, 'plan_sha256'), 'Deployment plan integrity failed')
    require(plan.get('action') in ACTIONS, 'Invalid plan action')
    return plan


def validate_review_request(request, plan):
    """Consume a browser request as intent only; never convert it to approval."""
    require(type(request) is dict and type(request.get('schema_version')) is int and request.get('schema_version') == 1 and
            request.get('kind') == 'deployment_request' and request.get('request_only') is True,
            'Expected a non-authorizing guided review request')
    require(request.get('intent') == 'reviewed_plan_request', 'Prepare and review the concrete plan first')
    require(request.get('action') == plan['action'] and request.get('plan_id') == plan['id'] and
            request.get('plan_sha256') == plan['plan_sha256'], 'Requested plan/action changed')
    require(request.get('context_sha256') == plan['bindings']['context_sha256'] and
            request.get('handoff_manifest_sha256') == plan['bindings']['handoff_manifest_sha256'], 'Request context changed')
    target = request.get('target', {})
    require(all(target.get(k) == plan['target'].get(k) for k in ('warehouse', 'environment')), 'Requested destination changed')
    require(target.get('framework') == plan.get('review_target', {}).get('framework', plan['target']['framework']), 'Requested framework changed')
    return {'request_only': True, 'action': plan['action'], 'plan_sha256': plan['plan_sha256']}


def approval_bindings(plan):
    result = {'plan_sha256': plan['plan_sha256'], 'release_id': plan['id'], 'action': plan['action'],
            'target_sha256': digest(plan['target']), 'policy_sha256': plan['policy_sha256'],
            'context_sha256': plan['bindings']['context_sha256'],
            'handoff_manifest_sha256': plan['bindings']['handoff_manifest_sha256']}
    if plan['action'] == 'publish_pr':
        result['publication_destination_sha256'] = digest(plan['publication_destination'])
    return result


def model_bindings(plan):
    return {k: plan['bindings'][k] for k in ('engagement_id', 'context_sha256', 'handoff_manifest_sha256')}


def _plan_policy(plan, policy):
    require(digest(policy) == plan['policy_sha256'], 'Runner policy changed; use the original policy to recover, or prepare a new plan')
    require(plan['action'] in policy['allowed_actions'] and plan['mode'] == policy['mode'], 'Action or mode is not allowed')
    from deployment_adapters import validate_target
    target = validate_target(policy['destinations'].get(plan['destination_id'], {}))
    require(target == plan['target'], 'Destination configuration changed')
    if plan['action'] == 'publish_pr':
        _publication_destination(policy, plan['destination_id'], plan.get('publication_destination'))
    checks = plan.get('required_checks')
    require(type(checks) is list and all(isinstance(value, str) and value.strip() for value in checks)
            and len(checks) == len(set(checks)), 'Invalid required check list')
    if plan['action'] != 'publish_pr':
        require(REQUIRED_CHECKS <= set(checks), 'Required deployment acceptance checks cannot be removed')
        if plan.get('review_target', {}).get('semantic_target') not in (None, 'none', 'retain_existing'):
            require('semantic' in checks, 'Selected semantic target requires consumer acceptance')
        if plan.get('metadata_required'):
            require('metadata_readback' in checks, 'Metadata acceptance cannot be removed')
        if plan.get('metadata_phase') is not None:
            from metadata_release import revalidate
            revalidate(plan, policy)


def _record_plan(record, plan, policy):
    """Bind transitions to the authenticated original execution, without expiry replay.

    Recovery can still settle a run after candidate drift; it cannot change its
    policy, mode, destination, context or acceptance obligations.
    """
    require(record.get('plan_sha256') == plan['plan_sha256'], 'Recorded plan changed')
    require(record.get('policy_sha256') == plan['policy_sha256'] == digest(policy), 'Recorded runner policy changed')
    require(record.get('mode') == plan['mode'] == policy['mode'], 'Recorded execution mode changed')
    require(record.get('target_sha256') == digest(plan['target']), 'Recorded destination changed')
    require(record.get('bindings') == plan['bindings'], 'Recorded release context changed')
    require(record.get('required_checks') == plan['required_checks'], 'Recorded required checks changed')
    for key in ('action', 'destination_id'):
        require(record.get(key) == plan[key], 'Recorded ' + key + ' changed')
    for field, bindings in (('approval', approval_bindings(plan)), ('model_signoff', model_bindings(plan))):
        payload = record.get(field, {}).get('payload', {})
        require(payload.get('mode') == record['mode'] and payload.get('bindings') == bindings,
                'Recorded authorization context changed')
    _plan_policy(plan, policy)


def _current(plan, policy_path):
    state, handoff, bindings = _handoff(plan['engagement_run'], refresh=True)
    require(bindings == plan['bindings'] and handoff['artifacts'] == plan['artifact_manifest'], 'Release context or artifact drift')
    policy, _ = load_policy(policy_path, excluded_roots=(plan['artifact_root'], state['inputs']['source']['path']))
    if plan['action'] != 'publish_pr' and (state['answers'].get('metadata_policy') or {}).get('mode') in ('comments', 'comments_and_tags'):
        require(plan.get('metadata_required') is True or plan.get('metadata_phase') is not None,
                'Selected metadata delivery requires its release gate')
    _plan_policy(plan, policy)
    for item in plan['artifact_manifest']:
        require(hash_file(Path(plan['artifact_root']) / relative_path(item['path'])) == item['sha256'], 'Release file changed')
    if plan.get('quality') is not None:
        from release_quality import verify_quality
        verify_quality(plan, handoff)
    return policy


def _journal_key(policy):
    name = policy.get('journal_key_env')
    require(isinstance(name, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}', name), 'Configure a runner journal-key environment reference')
    value = os.environ.get(name, '')
    require(len(value.encode()) >= 32, 'Runner journal key is unavailable or too short')
    return value.encode()


def _seal(record, policy):
    result = dict(record)
    result.pop('journal_hmac', None)
    result['journal_hmac'] = hmac.new(_journal_key(policy), _json_bytes(result), hashlib.sha256).hexdigest()
    return result


def _read_record(path, policy):
    record = load_json(path)
    expected = _seal(record, policy)['journal_hmac']
    require(isinstance(record.get('journal_hmac'), str) and hmac.compare_digest(record['journal_hmac'], expected), 'Runner journal integrity failed')
    return record


def _root(policy):
    root = canonical_path(policy['state_root'], exists=False)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    require(root.stat().st_uid == os.getuid() and root.stat().st_mode & 0o077 == 0, 'Runner state must be private to the runner account')
    return root


@contextmanager
def _runner_lock(policy):
    # Global to this installed runner, across engagement folders and destinations.
    # Durable active.json below also excludes conflicts while async work is pending.
    with workflow._lock(_root(policy)):
        yield


def _save_record(root, record, policy, event):
    # Recheck the persisted plan/policy before every journal commit, including
    # recovery and asynchronous status observations.
    current_policy, _ = load_policy(record['policy_path'])
    require(current_policy == policy, 'Runner policy changed during the transition')
    plan = load_plan(record['plan_path'])
    _record_plan(record, plan, policy)
    active_path = root / 'active.json'
    if active_path.exists():
        active = _read_record(active_path, policy)
        if active['operation_id'] != record['operation_id']:
            previous = _load_record(root, active['operation_id'], policy)
            from metadata_release import pending_parent_allowed
            new_child = (event == 'authorized' and not record.get('history')
                         and pending_parent_allowed(previous, plan))
            require(previous['state'] in TERMINAL or new_child,
                    'Another active operation owns the runner journal; finish or recover that child first')
    record = dict(record)
    record.pop('journal_hmac', None)
    history = list(record.get('history', []))
    history.append({'sequence': len(history) + 1, 'at': now(), 'event': event,
                    'previous_sha256': digest(history[-1]) if history else None})
    record['history'] = history
    record['updated_at'] = now()
    sealed = _seal(record, policy)
    directory = root / 'operations' / record['operation_id']
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    _write(directory / ('%06d.json' % len(history)), sealed, replace=False)
    _write(directory / 'state.json', sealed)
    _write(root / 'active.json', _seal({'operation_id': record['operation_id'], 'state': record['state'],
                                      'revision': len(history), 'record_sha256': digest(sealed)}, policy))
    return sealed


def _load_record(root, operation_id, policy):
    require(re.fullmatch(r'[a-f0-9]{32}', operation_id) is not None, 'Invalid operation identity')
    record = _read_record(root / 'operations' / operation_id / 'state.json', policy)
    active_path = root / 'active.json'
    if active_path.exists():
        active = _read_record(active_path, policy)
        if active['operation_id'] == operation_id:
            require(active['record_sha256'] == digest(record) and active['revision'] == len(record['history']), 'Journal head does not match active operation')
    return record


def _snapshot(plan, root):
    snapshot = root / 'snapshots' / plan['plan_sha256']
    if snapshot.exists():
        allowed = {item['path'] for item in plan['artifact_manifest']}
        for path in snapshot.rglob('*'):
            require(not path.is_symlink(), 'Symlink appeared in runner snapshot')
            if path.is_file() and path.relative_to(snapshot).as_posix() not in allowed:
                require(path.parts[len(snapshot.parts)] in {'target', 'logs', '.databricks'}, 'Unexpected file appeared in runner snapshot')
        for item in plan['artifact_manifest']:
            require(hash_file(snapshot / relative_path(item['path'])) == item['sha256'], 'Runner snapshot drift')
        return snapshot
    snapshot.mkdir(parents=True, mode=0o700)
    for item in plan['artifact_manifest']:
        relative = relative_path(item['path'])
        data = _stable_bytes(Path(plan['artifact_root']) / relative)
        require(hashlib.sha256(data).hexdigest() == item['sha256'], 'Artifact changed during snapshot')
        path = snapshot / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        workflow._atomic_write(path, data, replace=False)
        path.chmod(0o400)
    return snapshot


def _artifact_refs(value, snapshot):
    if type(value) is dict and set(value) == {'$artifact'}:
        path = canonical_path(snapshot / relative_path(value['$artifact']))
        require(snapshot in path.parents, 'Artifact is outside the private snapshot')
        return str(path)
    if value == {'$artifact_root': True}:
        return str(snapshot)
    if type(value) is dict:
        return {k: _artifact_refs(v, snapshot) for k, v in value.items()}
    if type(value) is list:
        return [_artifact_refs(v, snapshot) for v in value]
    return value


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return value
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Deployment transport refuses HTTP redirects')


class NativeTransport:
    """Bounded process/HTTPS transport; injected doubles are simulation-only."""
    def __init__(self, policy, snapshot):
        self.policy, self.snapshot = policy, snapshot

    def __call__(self, operation):
        require(self.policy['mode'] == 'live', 'Simulation cannot use the live transport')
        operation = _artifact_refs(operation, self.snapshot)
        timeout = self.policy.get('timeout_seconds', 120)
        require(type(timeout) is int and 1 <= timeout <= 1800, 'Invalid runner timeout')
        if operation['transport'] == 'http':
            return self._http(operation, timeout)
        require(operation['transport'] == 'process', 'Unknown transport')
        return self._process(operation, timeout)

    def _http(self, operation, timeout):
        url = operation['url']
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment, 'Only explicit HTTPS endpoints are allowed')
        headers, secrets = dict(operation.get('headers', {})), []
        auth = operation.get('auth')
        if auth:
            require(auth.get('scheme') in {'bearer', 'token', 'basic'}, 'Unsupported HTTP authentication scheme')
            require(auth.get('env') != self.policy.get('journal_key_env'), 'Journal key cannot be used as platform authentication')
            secret = os.environ.get(auth['env'])
            require(bool(secret), 'Required runner authentication is unavailable')
            if auth['scheme'] == 'basic':
                encoded = base64.b64encode((auth['username'] + ':' + secret).encode()).decode()
                headers['Authorization'] = 'Basic ' + encoded
                secrets.append(encoded)
            else:
                headers['Authorization'] = ('Token ' if auth['scheme'] == 'token' else 'Bearer ') + secret
            secrets.append(secret)
        if operation.get('query'):
            url += ('&' if parsed.query else '?') + urllib.parse.urlencode(operation['query'])
        data = None
        if 'body' in operation:
            data = _json_bytes(operation['body'])
            headers.setdefault('Content-Type', 'application/json')
        elif 'text' in operation:
            data = operation['text'].encode('utf-8')
            headers.setdefault('Content-Type', 'text/plain; charset=utf-8')
        request = urllib.request.Request(url, data=data, headers=headers, method=operation.get('method', 'GET'))
        try:
            response = urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(MAX_RESPONSE + 1)
            require(len(raw) <= MAX_RESPONSE, 'Native response exceeded its output limit')
            text = raw.decode('utf-8', errors='replace')
            try:
                body = json.loads(text)
            except ValueError:
                body = text
            result = {'status_code': response.code, 'body': body, 'headers': dict(response.headers)}
        return _redact(result, secrets)

    def _process(self, operation, timeout):
        argv = operation['argv']
        require(type(argv) is list and bool(argv) and all(isinstance(x, str) for x in argv), 'Invalid native command')
        tool = self.policy.get('tools', {}).get(argv[0])
        require(type(tool) is dict, 'Native executable is not provisioned: ' + argv[0])
        executable = canonical_path(tool['path'])
        require(hash_file(executable) == tool['sha256'], 'Native executable changed; requalify and reapprove')
        cwd = canonical_path(operation.get('cwd', self.snapshot))
        require(cwd == self.snapshot or self.snapshot in cwd.parents, 'Native command directory is outside the snapshot')
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(self.snapshot.parent)}
        secrets = []
        names = operation.get('auth_env', [])
        if isinstance(names, dict):
            names = list(names.values())
        for name in names:
            require(name != self.policy.get('journal_key_env') and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name), 'Invalid credential environment reference')
            require(name in os.environ, 'Required runner authentication is unavailable')
            env[name] = os.environ[name]
            secrets.append(env[name])
        for name, expected in self.policy.get('runtime_env', {}).items():
            require(name != self.policy.get('journal_key_env') and name in os.environ, 'Invalid runtime environment reference')
            require(digest(os.environ[name]) == expected, 'Runtime configuration drift; prepare a new plan')
            env[name] = os.environ[name]
            secrets.append(env[name])
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen([str(executable), *argv[1:]], cwd=str(cwd), env=env,
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
            try:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if time.monotonic() >= deadline or out.tell() > MAX_RESPONSE or err.tell() > MAX_RESPONSE:
                        raise subprocess.TimeoutExpired(argv[0], timeout)
                    time.sleep(0.05)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise TimeoutError('Native command timed out; remote acceptance may already have occurred')
            out.seek(0); err.seek(0)
            stdout, stderr = out.read(MAX_RESPONSE + 1), err.read(MAX_RESPONSE + 1)
            require(len(stdout) <= MAX_RESPONSE and len(stderr) <= MAX_RESPONSE, 'Native output exceeded its limit')
        return _redact({'exit_code': process.returncode, 'stdout': stdout.decode('utf-8', errors='replace'),
                        'stderr': stderr.decode('utf-8', errors='replace')}, secrets)


def _normalize(operation, response):
    if operation.get('contract') in {'publication_file', 'publication_verify'}:
        try:
            body = json.loads(response.get('stdout', ''))
            expected = operation['expected_identity']
            if operation['contract'] == 'publication_file':
                valid = body.get('encoding') == 'base64' and hashlib.sha256(base64.b64decode(body['content'])).hexdigest() == expected['sha256']
            else:
                valid = (body.get('headRefOid') == expected['commit_sha'] and body.get('baseRefName') == expected['base'] and body.get('headRefName') == expected['head'] and body.get('state') == 'OPEN' and bool(re.fullmatch(r'https://github\.com/' + re.escape(expected['repository']) + r'/pull/[1-9][0-9]*', body.get('url', ''))))
            valid = valid and response.get('exit_code') == 0
        except (ValueError, KeyError, TypeError):
            body, valid = {}, False
        return {'state': 'succeeded' if valid else 'failed', 'identity_verified': valid, 'native_id': body.get('url'), 'evidence': {'verified': valid}}
    if operation.get('contract') == 'publication_head':
        try:
            body = json.loads(response.get('stdout', ''))
        except ValueError:
            body = {}
        valid = response.get('exit_code') == 0 and body.get('sha') == operation['expected_identity']['commit_sha']
        return {'state': 'succeeded' if valid else 'failed', 'identity_verified': valid,
                'native_id': body.get('sha'), 'evidence': {'observed_sha': body.get('sha')}}
    if operation.get('contract') == 'publication_pr':
        url = response.get('stdout', '').strip()
        repository = operation['expected_identity']['repository']
        valid = response.get('exit_code') == 0 and re.fullmatch(r'https://github\.com/' + re.escape(repository) + r'/pull/[1-9][0-9]*', url)
        return {'state': 'succeeded' if valid else 'unknown', 'identity_verified': bool(valid),
                'native_id': url if valid else None, 'evidence': {'pull_request_url': url if valid else None}}
    from deployment_adapters import normalize_response
    return normalize_response(operation, response)


def _approval(plan, policy, model_signoff, approval):
    model = verify_attestation(model_signoff, policy, purpose='model_signoff', bindings=model_bindings(plan))
    deploy = verify_attestation(approval, policy, purpose='deployment_approval', bindings=approval_bindings(plan))
    if plan.get('metadata_phase') is not None:
        from metadata_release import verify_preflight
        verify_preflight(plan, policy, deploy.get('claims', {}))
    if policy['mode'] == 'live':
        require(plan['action'] == 'publish_pr' or plan['target']['adapter'] != 'coalesce',
                'Coalesce live execution is unavailable until automatic status/results bind the approved profile domain; use the reviewed Git/CI handoff')
        require(plan.get('quality', {}).get('status') == 'verified_static', 'A complete, current lint report is required for live release')
        preflight = deploy.get('claims', {}).get('preflight', {})
        require(preflight.get('status') == 'passed' and preflight.get('target_sha256') == digest(plan['target'])
                and preflight.get('runtime_version') == plan['target']['runtime_version']
                and preflight.get('principal_namespace_verified') is True
                and preflight.get('artifact_commit_verified') is True
                and preflight.get('lint_report_sha256') == plan['quality']['report_sha256']
                and preflight.get('permissions_verified') is True
                and isinstance(preflight.get('evidence_sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', preflight['evidence_sha256'])
                and preflight.get('evidence_reference'), 'Live approval needs current native identity, permissions and artifact/commit preflight evidence')
    if plan['action'] == 'promote':
        qualification = plan.get('qualification')
        require(type(qualification) is dict, 'Promotion requires a qualified prior build')
        qualified = verify_attestation(qualification, policy, purpose='adapter_qualification',
            bindings={'artifact_manifest_sha256': plan['bindings']['handoff_manifest_sha256'],
                      'target_sha256': digest(plan['target']), 'runtime_version': plan['target']['runtime_version']})
        require(qualified.get('claims', {}).get('development_deployed_verified') is True and
                qualified.get('claims', {}).get('recovery_rehearsed') is True, 'Promotion qualification is incomplete')
    return model, deploy


def submit(plan_path, policy_path, model_signoff, approval, *, transport=None):
    plan = load_plan(plan_path)
    policy = _current(plan, policy_path)
    require(transport is None or policy['mode'] == 'simulation', 'Simulation boundary: Injected transports cannot produce live receipts')
    _approval(plan, policy, model_signoff, approval)
    root = _root(policy)
    with _runner_lock(policy):
        active = root / 'active.json'
        if active.exists():
            previous = _read_record(active, policy)
            from metadata_release import pending_parent_allowed
            metadata_parent = (plan.get('metadata_phase') is not None and previous['state'] == 'verification_pending'
                               and pending_parent_allowed(_load_record(root, previous['operation_id'], policy), plan))
            require(previous['state'] in TERMINAL or metadata_parent,
                    'Another release is active or needs recovery; do not replay it')
        # Immutable claim prevents a successful release from being submitted again.
        claims = root / 'claims'
        claims.mkdir(exist_ok=True, mode=0o700)
        claim = claims / (plan['plan_sha256'] + '.json')
        require(not claim.exists(), 'This approved plan was already submitted; resume its recorded operation')
        snapshot = _snapshot(plan, root)
        operation_id = uuid.uuid4().hex
        record = {'schema_version': 1, 'kind': 'deployment_execution', 'operation_id': operation_id,
                  'plan_sha256': plan['plan_sha256'], 'plan_path': str(canonical_path(plan_path)),
                  'mode': policy['mode'], 'state': 'deployment_authorized', 'created_at': now(),
                  'approval': approval, 'model_signoff': model_signoff, 'operations': [], 'history': [],
                  'snapshot': str(snapshot), 'required_checks': plan['required_checks'],
                  'bindings': plan['bindings'], 'action': plan['action'], 'destination_id': plan['destination_id'],
                  'target_sha256': digest(plan['target']), 'policy_sha256': plan['policy_sha256'], 'policy_path': str(canonical_path(policy_path))}
        _record_plan(record, plan, policy)
        _write(claim, _seal({'operation_id': operation_id, 'plan_sha256': plan['plan_sha256']}, policy), replace=False)
        record = _save_record(root, record, policy, 'authorized')
        return _advance(plan, policy, root, record, transport or NativeTransport(policy, snapshot))


def _advance(plan, policy, root, record, transport):
    _record_plan(record, plan, policy)
    from deployment_adapters import resolve_operation
    receipts = {item['id']: item['receipt'] for item in record['operations'] if item.get('receipt')}
    for declared in plan['native']['operations']:
        previous = next((item for item in record['operations'] if item['id'] == declared['id']), None)
        if previous:
            allowed_previous = {'succeeded'}
            for downstream in plan['native']['operations']:
                allowed_previous.update(downstream.get('prerequisite_states', {}).get(declared['id'], []))
            require(previous.get('receipt', {}).get('state') in allowed_previous, 'An incomplete operation must be reconciled, never resubmitted')
            continue
        _current(plan, record['policy_path'])
        _snapshot(plan, root)
        _approval(plan, policy, record['model_signoff'], record['approval'])
        for dependency in declared.get('depends_on', []):
            require(receipts.get(dependency, {}).get('state') in declared.get('prerequisite_states', {}).get(dependency, ['succeeded']), 'Native operation dependency is incomplete')
        operation = resolve_operation(declared, receipts)
        record['operations'].append({'id': declared['id'], 'declared': declared, 'resolved': operation,
                                      'submitted_at': now(), 'state': 'submission_pending'})
        record['state'] = 'submitted'
        record = _save_record(root, record, policy, 'submit:' + declared['id'])
        try:
            response = transport(operation)
            receipt = _normalize(operation, response)
            require(receipt.get('state') in {'submitted', 'running', 'succeeded', 'failed', 'cancelled', 'partial', 'unknown'}, 'Unsupported native state')
        except Exception as error:
            # A failed read before a write is safe to investigate; uncertainty after
            # submission never authorizes a second POST or process invocation.
            record['operations'][-1]['state'] = 'unknown'
            record['operations'][-1]['error'] = type(error).__name__
            record['state'] = 'unknown_remote_state'
            return _save_record(root, record, policy, 'uncertain:' + declared['id'])
        record['operations'][-1].update(state=receipt['state'], receipt=receipt, response_sha256=digest(response))
        _write(root / 'operations' / record['operation_id'] / (declared['id'] + '-response.json'), response, replace=False)
        receipts[declared['id']] = receipt
        accepted_for_next = any(receipt['state'] in downstream.get('prerequisite_states', {}).get(declared['id'], []) for downstream in plan['native']['operations'])
        if receipt['state'] == 'succeeded' or accepted_for_next:
            record = _save_record(root, record, policy, 'completed:' + declared['id'])
            continue
        mapping = {'submitted': 'running', 'running': 'running', 'partial': 'recovery_required',
                   'unknown': 'unknown_remote_state', 'failed': 'failed', 'cancelled': 'cancelled'}
        record['state'] = mapping[receipt['state']]
        return _save_record(root, record, policy, 'observed:' + declared['id'])
    record['state'] = 'published' if plan['action'] == 'publish_pr' else 'verification_pending'
    return _save_record(root, record, policy, record['state'])


def observe(policy_path, operation_id, *, cancel=False, transport=None):
    """Poll/cancel the existing native execution; never retry its submission."""
    policy, _ = load_policy(policy_path)
    require(transport is None or policy['mode'] == 'simulation', 'Simulation boundary: Injected transports cannot produce live receipts')
    root = _root(policy)
    with _runner_lock(policy):
        record = _load_record(root, operation_id, policy)
        plan = load_plan(record['plan_path'])
        _record_plan(record, plan, policy)
        if record['state'] in TERMINAL or record['state'] == 'verification_pending':
            return record
        require(bool(record['operations']), 'No native operation has been submitted')
        last = record['operations'][-1]
        receipt = last.get('receipt')
        require(receipt and receipt.get('native_id'), 'Remote identity is unknown; reconcile externally before recovery')
        from deployment_adapters import build_followup
        operation = build_followup(plan['native'], receipt, action='cancel' if cancel else 'status')
        caller = transport or NativeTransport(policy, canonical_path(record['snapshot']))
        try:
            response = caller(operation)
            updated = _normalize(operation, response)
        except Exception as error:
            record['state'] = 'unknown_remote_state'
            record['observation_error'] = type(error).__name__
            return _save_record(root, record, policy, 'observation_uncertain')
        last['receipt'], last['state'] = updated, updated['state']
        last['response_sha256'] = digest(response)
        _write(root / 'operations' / operation_id / ('observation-%06d.json' % len(record['history'])), response, replace=False)
        if cancel:
            record['state'] = 'cancelled' if updated['state'] == 'cancelled' else 'cancel_requested'
            return _save_record(root, record, policy, 'cancel_observed')
        if updated['state'] == 'succeeded':
            _current(plan, policy_path)
            record = _save_record(root, record, policy, 'native_completion_observed')
            return _advance(plan, policy, root, record, caller)
        record['state'] = {'running': 'running', 'submitted': 'running', 'failed': 'failed',
                           'partial': 'recovery_required', 'cancelled': 'cancelled'}.get(updated['state'], 'unknown_remote_state')
        return _save_record(root, record, policy, 'native_status_observed')


def execution_bindings(record, plan):
    return {'operation_id': record['operation_id'], 'plan_sha256': plan['plan_sha256'],
            'target_sha256': digest(plan['target']), 'artifact_manifest_sha256': plan['bindings']['handoff_manifest_sha256'],
            'native_receipts_sha256': digest([{'id': item['id'], 'receipt': item.get('receipt'),
                                             'response_sha256': item.get('response_sha256')} for item in record['operations']])}


def accept(policy_path, operation_id, attestation):
    policy, _ = load_policy(policy_path)
    root = _root(policy)
    with _runner_lock(policy):
        record = _load_record(root, operation_id, policy)
        require(record['state'] == 'verification_pending', 'Native execution must complete before acceptance')
        plan = load_plan(record['plan_path'])
        _record_plan(record, plan, policy)
        _current(plan, policy_path)
        require(all(item.get('receipt', {}).get('state') == 'succeeded' or (item['id'] == 'bundle-deploy' and item.get('receipt', {}).get('state') == 'submitted' and any(other['id'] == 'bundle-summary' and other.get('receipt', {}).get('state') == 'succeeded' for other in record['operations'])) for item in record['operations']), 'Native outcomes are incomplete')
        accepted = verify_attestation(attestation, policy, purpose='deployment_acceptance', bindings=execution_bindings(record, plan))
        require(accepted['issuer'] != record['approval']['payload']['issuer'], 'Acceptance must come from an independent validation issuer')
        checks = accepted.get('claims', {}).get('checks')
        require(type(checks) is list and all(type(c) is dict for c in checks), 'Acceptance check evidence is required')
        indexed = {check.get('id'): check for check in checks}
        require(len(indexed) == len(checks) and set(indexed) == set(plan['required_checks']), 'Acceptance must cover the exact required check set')
        for check in checks:
            require(check.get('status') == 'passed' and isinstance(check.get('evidence_sha256'), str)
                    and re.fullmatch(r'[0-9a-f]{64}', check['evidence_sha256']) and check.get('evidence_reference'), 'A required acceptance check is failed, skipped or unbound')
        if plan.get('metadata_phase') is not None or plan.get('metadata_required') is True:
            from metadata_release import verify_acceptance
            record['metadata_verification'] = verify_acceptance(plan, record, policy, accepted.get('claims', {}))
        record['acceptance'] = attestation
        record['state'] = 'deployed_verified' if record['mode'] == 'live' else 'simulation_verified'
        return _save_record(root, record, policy, 'independent_acceptance_verified')


def recovery_bindings(record, plan):
    return dict(execution_bindings(record, plan), journal_head_sha256=digest(record))


def recover(policy_path, operation_id, attestation):
    """Release the durable lock only after separately attested native recovery.

    This never executes rollback SQL or retries a prior request. The issuer must
    verify remote work is quiescent and the concrete recovery procedure complete.
    """
    policy, _ = load_policy(policy_path)
    root = _root(policy)
    with _runner_lock(policy):
        record = _load_record(root, operation_id, policy)
        require(record['state'] not in TERMINAL, 'Completed operation does not need recovery')
        plan = load_plan(record['plan_path'])
        _record_plan(record, plan, policy)
        approved = verify_attestation(attestation, policy, purpose='deployment_recovery', bindings=recovery_bindings(record, plan))
        require(approved['issuer'] != record['approval']['payload']['issuer'], 'Recovery requires independent verification')
        claims = approved.get('claims', {})
        require(claims.get('remote_quiescent') is True and claims.get('recovery_verified') is True
                and isinstance(claims.get('evidence_sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', claims['evidence_sha256'])
                and claims.get('evidence_reference'), 'Recovery needs verified native evidence')
        record.update(state='recovered', recovery=attestation)
        return _save_record(root, record, policy, 'external_recovery_verified')


def reconcile(policy_path, operation_id, attestation, *, transport=None):
    """Bind an externally located native run after an uncertain submission.

    Only a separately authenticated reconciler can identify it. The next action
    is a native read, never a repeat submission. No inferred latest-run matching.
    """
    policy, _ = load_policy(policy_path)
    require(transport is None or policy['mode'] == 'simulation', 'Simulation boundary: Injected transports cannot produce live receipts')
    root = _root(policy)
    with _runner_lock(policy):
        record = _load_record(root, operation_id, policy)
        require(record['state'] == 'unknown_remote_state' and record['operations'], 'Only uncertain submissions need reconciliation')
        plan = load_plan(record['plan_path'])
        _record_plan(record, plan, policy)
        _current(plan, policy_path)
        approved = verify_attestation(attestation, policy, purpose='deployment_reconciliation', bindings=recovery_bindings(record, plan))
        require(approved['issuer'] != record['approval']['payload']['issuer'], 'Reconciliation requires independent verification')
        receipt = approved.get('claims', {}).get('receipt')
        require(type(receipt) is dict and receipt.get('operation_id') == record['operations'][-1]['id'], 'Reconciliation must identify the uncertain operation')
        from deployment_adapters import build_followup
        build_followup(plan['native'], receipt, action='status')
        record['operations'][-1]['receipt'] = receipt
        record['reconciliation'] = attestation
        record = _save_record(root, record, policy, 'native_identity_reconciled')
    return observe(policy_path, operation_id, transport=transport)


def status(policy_path, operation_id):
    policy, _ = load_policy(policy_path)
    return _load_record(_root(policy), operation_id, policy)


def review_projection(plan, *, record=None):
    """Curated display only. Portable packages include registered evidence hashes."""
    target = plan['target']
    visible = dict(plan.get('review_target', {k: target.get(k) for k in ('framework', 'warehouse')}), environment=target['environment'])
    choices = [{'id': action, 'label': {'publish_pr': 'Publish a pull request', 'deploy_development': 'Deploy to development', 'promote': 'Promote a validated release'}[action],
                'available': action == plan['action'], 'reason': '' if action == plan['action'] else 'Prepare a separate plan for this action.'} for action in sorted(ACTIONS)]
    result = {'schema_version': 1, 'status': record['state'] if record else 'deployment_plan_ready',
              'target': visible, 'handoff': {'context_sha256': plan['bindings']['context_sha256'],
                  'manifest_sha256': plan['bindings']['handoff_manifest_sha256']}, 'choices': choices,
              'plan': {'id': plan['id'], 'sha256': plan['plan_sha256'], 'action': plan['action'],
                  'target_label': target['warehouse'] + ' / ' + target['environment'],
                  'summary': 'Version-bound release plan; external approval is required.',
                  'files': [{'path': a['path'], 'sha256': a['sha256'], 'version': plan['commit_sha'],
                             'operation': a['role']} for a in plan['selected_artifacts']],
                  'impacts': plan['impact'], 'recovery': plan['recovery'],
                  'steps': [op['id'] for op in plan['native']['operations']],
                  'prerequisites': ['Externally authenticated model sign-off and deployment authorization',
                                    'Qualified native execution and independent acceptance evidence']},
              'receipts': [], 'next_action': 'Review the exact release plan and request the selected action.'}
    if plan['action'] == 'publish_pr':
        identity = publication_destination(plan['publication_destination'])
        result['plan']['target_label'] = identity['repository'] + ' / ' + identity['base']
        result['plan']['summary'] = ('Publish a draft PR to ' + identity['repository'] + ', base ' + identity['base']
            + ', head ' + identity['head'] + ', commit ' + plan['commit_sha'] + '. External approval is required.')
    elif target['adapter'] == 'coalesce':
        result['plan']['summary'] = ('Coalesce live execution is blocked: automatic status/results do not yet bind the approved profile domain. '
                                    'Use the reviewed Git/CI handoff until that continuation is implemented and qualified.')
        result['plan']['prerequisites'].append('Implement and qualify Coalesce profile-domain binding before live submission.')
    if record:
        for choice in result['choices']:
            choice.update(available=False, reason='An operation already exists. Inspect its receipt; do not submit again.')
        result['next_action'] = {'verification_pending': 'Obtain independent native data and consumer acceptance for this exact run.',
            'deployed_verified': 'Review the verified release evidence; promotion requires its own plan.',
            'simulation_verified': 'The simulation passed. Live qualification is still required.',
            'published': 'Review the draft pull request in the repository.',
            'unknown_remote_state': 'Reconcile the recorded native operation before any new submission.',
            'recovered': 'Recovery is recorded. Prepare a new plan if more work is needed.'}.get(record['state'], 'Inspect and observe the existing operation; verify recovery if it failed.')
        result['receipts'] = [{'id': record['operation_id'], 'action': plan['action'], 'status': record['state'],
                               'scope': policy_scope(record), 'summary': 'Observed runner status; the offline page does not authenticate it.'}]
    return result


def policy_scope(record):
    return 'simulation' if record['mode'] == 'simulation' else 'native_execution'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('plan')
    for name in ('run', 'request', 'policy', 'output'):
        prepare.add_argument('--' + name, required=True)
    request = sub.add_parser('approval-request')
    request.add_argument('--plan', required=True)
    request.add_argument('--output', required=True)
    request.add_argument('--review-request')
    submit_parser = sub.add_parser('submit')
    for name in ('plan', 'model-signoff', 'approval'):
        submit_parser.add_argument('--' + name, required=True)
    for command in ('status', 'observe', 'cancel', 'accept', 'recover', 'reconcile'):
        child = sub.add_parser(command)
        child.add_argument('--operation', required=True)
        if command in {'accept', 'recover', 'reconcile'}:
            child.add_argument('--attestation', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            result = create_plan(args.run, load_json(args.request), args.policy, args.output)
            result = {'status': 'deployment_plan_ready', 'plan_sha256': result['plan_sha256'], 'path': str(Path(args.output).absolute())}
        elif args.command == 'approval-request':
            plan = load_plan(args.plan)
            if args.review_request:
                validate_review_request(load_json(args.review_request), plan)
            result = {'schema_version': 1, 'request_only': True, 'model_signoff_bindings': model_bindings(plan),
                      'deployment_approval_bindings': approval_bindings(plan), 'review': review_projection(plan),
                      'quality': {k: v for k, v in plan.get('quality', {}).items() if k in {'status', 'report_sha256', 'manifest_sha256', 'assurance'}}}
            _write(args.output, result, replace=False)
        else:
            policy_path = os.environ.get('DMA_RUNNER_POLICY')
            require(bool(policy_path), 'Provision DMA_RUNNER_POLICY in the trusted runner; requests cannot select execution policy')
            if args.command == 'submit':
                result = submit(args.plan, policy_path, load_json(args.model_signoff), load_json(args.approval))
            elif args.command == 'status':
                result = status(policy_path, args.operation)
            elif args.command in {'accept', 'recover', 'reconcile'}:
                result = {'accept': accept, 'recover': recover, 'reconcile': reconcile}[args.command](policy_path, args.operation, load_json(args.attestation))
            else:
                result = observe(policy_path, args.operation, cancel=args.command == 'cancel')
            result = {k: result[k] for k in ('operation_id', 'state', 'mode', 'plan_sha256')}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('Deployment refused: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
