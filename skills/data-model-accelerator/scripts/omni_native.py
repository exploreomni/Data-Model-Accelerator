"""Narrow Omni development-branch adapter. No live calls occur on import.

The trusted runner supplies an external policy and signed exact-action approval.
Injected transports are always simulations. Native observations are not business
acceptance, protected-data qualification, or permission to merge/publish.
"""
import argparse
import base64
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import ssl
import stat
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from deployment_authority import load_policy, verify_attestation, canonical_path, outside
from omni_contract import check_model, canonical_hash, _bounded
from sensitive_data import scan_bytes

MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 64
MAX_POLLS = 2
CONTRACT = 'omni-native-v1-2026-10-05'
SHA = re.compile(r'[a-f0-9]{64}\Z')
RUN_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')
TARGET_KEYS = {'instance_url', 'model_id', 'branch_id', 'connection_id',
               'environment_connection_id', 'principal_id', 'environment'}
SNAPSHOT_KEYS = {'authored_sha256', 'resolved_sha256', 'base_sha256', 'schema_sha256', 'identity_sha256'}


class AdapterError(ValueError):
    """Only adapter-owned codes may enter a public diagnostic."""


def _need(condition, code):
    if not condition:
        raise AdapterError(code)


def _json_bytes(value):
    _bounded(value)
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    _need(len(data) <= MAX_BYTES, 'input.byte_limit')
    return data


def _json(body):
    _need(type(body) is bytes and len(body) <= MAX_BYTES, 'response.byte_limit')
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, 'response.duplicate_key')
            result[key] = value
        return result
    def constant(_):
        raise AdapterError('response.nonfinite')
    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
        _bounded(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise AdapterError('response.invalid_json') from None


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _instance(value):
    _need(type(value) is str, 'target.instance')
    url = urlsplit(value)
    _need(url.scheme == 'https' and url.path in ('', '/') and not url.query and not url.fragment
          and not url.username and not url.password and url.port in (None, 443)
          and url.hostname is not None and re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.omniapp\.co', url.hostname),
          'target.https_omni_instance_required')
    _need(value == 'https://' + url.hostname, 'target.canonical_instance_required')
    return value


def validate_target(target):
    _need(type(target) is dict and set(target) == TARGET_KEYS, 'target.fields')
    _instance(target['instance_url'])
    _need(target['environment'] == 'development', 'target.development_only')
    _need(all(_uuid(target[k]) for k in TARGET_KEYS - {'instance_url', 'environment'}), 'target.identity')
    _need(target['branch_id'] != target['model_id'], 'target.branch_required')
    return copy.deepcopy(target)


def validate_request(request):
    _json_bytes(request)
    required = {'schema_version', 'kind', 'run_id', 'operation', 'destination_id', 'target', 'files',
                'context', 'warning_policy', 'expected_remote', 'commit_message'}
    _need(type(request) is dict and required <= set(request)
          and set(request) <= required | {'query', 'query_mode', 'timezone'}, 'request.fields')
    _need(type(request['schema_version']) is int and request['schema_version'] == 1
          and request['kind'] == 'omni_native_request', 'request.version')
    _need(type(request['run_id']) is str and RUN_ID.fullmatch(request['run_id']), 'request.run_id')
    _need(request['operation'] in ('validate', 'update_and_validate', 'query'), 'request.operation')
    _need(type(request['destination_id']) is str and RUN_ID.fullmatch(request['destination_id']), 'request.destination')
    validate_target(request['target'])
    _need(request['warning_policy'] in ('fail', 'allow'), 'request.warning_policy')
    _need(type(request['commit_message']) is str and 0 < len(request['commit_message']) <= 240, 'request.commit_message')
    files = request['files']
    _need(type(files) is dict and 0 < len(files) <= MAX_FILES, 'request.file_inventory')
    for name, body in files.items():
        path = PurePosixPath(name)
        _need(type(name) is str and path.name == name and '\\' not in name and ':' not in name
              and name not in ('.', '..') and (name in ('model', 'relationships')
                   or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\.(?:view|topic)', name))
              and type(body) is str and bool(body.strip()), 'request.native_file')
    expected = request['expected_remote']
    _need(type(expected) is dict and set(expected) == SNAPSHOT_KEYS and all(_sha(v) for v in expected.values()),
          'request.remote_snapshot_required')
    _need(type(request['context']) is dict and request['context'].get('environment') == 'development',
          'request.development_context_required')
    static = check_model(files, request['context'])
    _need(static['status'] == 'passed', 'request.static_check_not_passed')
    if request['operation'] == 'query':
        query = request.get('query')
        _need(type(query) is dict and request.get('query_mode') in ('plan', 'execute'), 'request.query')
        _need(query.get('modelId') == request['target']['model_id'] and type(query.get('table')) is str
              and query['table'] and type(query.get('fields')) is list and 0 < len(query['fields']) <= 100
              and all(type(x) is str and x for x in query['fields']), 'request.query_binding')
        _need(type(query.get('limit')) is int and 1 <= query['limit'] <= 1000, 'request.query_limit')
        _need(type(request.get('timezone')) is str, 'request.query_timezone_required')
        try:
            ZoneInfo(request['timezone'])
        except (ZoneInfoNotFoundError, ValueError):
            raise AdapterError('request.query_timezone_invalid') from None
        _need(set(query) <= {'modelId','table','fields','limit','sorts','filters','pivots','calculations',
                            'column_totals','row_totals','column_limit','join_paths_from_topic_name',
                            'join_via_map','version','default_group_by','dimensionIndex','fill_fields'},
              'request.query_unsupported_parameter')
    else:
        _need('query' not in request and 'query_mode' not in request and 'timezone' not in request, 'request.unused_query')
    scan = scan_bytes(_json_bytes(request), 'request.json')
    _need(scan['status'] == 'clear' and scan['coverage']['complete'], 'request.disclosure_scan_not_clear')
    return copy.deepcopy(request)


def request_bindings(request, policy_sha256):
    """Exact payload a separately controlled issuer must review and sign."""
    return {'adapter': CONTRACT, 'action': 'deploy_development', 'operation': request['operation'],
            'request_sha256': canonical_hash(request), 'target_sha256': canonical_hash(request['target']),
            'candidate_sha256': canonical_hash(request['files']), 'context_sha256': canonical_hash(request['context']),
            'policy_sha256': policy_sha256}


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str = 'application/json'


class TransportError(Exception):
    def __init__(self, code='transport.failure', status=None, uncertain=False):
        super().__init__('Omni request failed; provider diagnostics withheld')
        self.code = code if code in ('transport.timeout','transport.http','transport.failure','transport.size') else 'transport.failure'
        self.status = status if type(status) is int else None
        self.uncertain = bool(uncertain)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPSOmniTransport:
    """TLS verification on; redirects and environment proxies off; no raw errors."""
    def __init__(self, instance_url, token_env='OMNI_API_TOKEN', timeout=20):
        self.instance_url = _instance(instance_url)
        _need(type(token_env) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,80}', token_env), 'transport.token_env')
        _need(type(timeout) is int and 1 <= timeout <= 30, 'transport.timeout_bounds')
        self._token = os.environ.get(token_env)
        _need(self._token is None or ('\r' not in self._token and '\n' not in self._token), 'transport.token_invalid')
        self.timeout = timeout
        self._opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())

    @property
    def available(self):
        return bool(self._token)

    def request(self, method, path, params=None, body=None):
        _need(self.available and method in ('GET', 'POST') and type(path) is str
              and path.startswith('/api/v1/') and '?' not in path and '#' not in path
              and '..' not in path and '\\' not in path, 'transport.request_not_permitted')
        url = self.instance_url + path + ('?' + urlencode(params) if params else '')
        headers = {'Authorization': 'Bearer ' + self._token, 'Accept': 'application/json, text/ndjson'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(url, data=_json_bytes(body) if body is not None else None, method=method, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as reply:
                data = reply.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise TransportError('transport.size', uncertain=method == 'POST')
                return Response(reply.status, data, reply.headers.get_content_type())
        except HTTPError as error:
            if error.code == 408 and path == '/api/v1/query/run':
                data = error.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise TransportError('transport.size', uncertain=True) from None
                return Response(408, data, error.headers.get_content_type())
            # Do not include URLs, response text, credential headers or raw messages.
            raise TransportError('transport.http', error.code, method == 'POST' and error.code >= 500 or error.code == 408) from None
        except (TimeoutError, socket.timeout):
            raise TransportError('transport.timeout', uncertain=method == 'POST') from None
        except (URLError, OSError):
            raise TransportError('transport.failure', uncertain=method == 'POST') from None


def _call(transport, method, path, params=None, body=None):
    reply = transport.request(method, path, params=params, body=body)
    _need(type(reply) is Response and type(reply.status) is int and type(reply.body) is bytes
          and len(reply.body) <= MAX_BYTES, 'response.shape')
    if reply.status != 200:
        raise TransportError('transport.http', reply.status, method == 'POST' and (reply.status >= 500 or reply.status == 408))
    return reply


def _get(transport, path, params=None):
    return _json(_call(transport, 'GET', path, params).body)


def _model(transport, identity):
    data = _get(transport, '/api/v1/models', {'modelId': identity})
    _need(type(data) is dict and type(data.get('records')) is list and len(data['records']) == 1
          and type(data.get('pageInfo')) is dict and data['pageInfo'].get('hasNextPage') is False
          and data['pageInfo'].get('nextCursor') is None, 'identity.model_inventory_incomplete')
    model = data['records'][0]
    _need(type(model) is dict and model.get('id') == identity and model.get('deletedAt') is None,
          'identity.model_mismatch')
    return model


def _identity(transport, target):
    user = _get(transport, '/api/v1/whoami', {'modelId': target['model_id']})
    _need(type(user) is dict and type(user.get('user')) is dict and user['user'].get('id') == target['principal_id']
          and user.get('rolesByModelTruncated') is not True and type(user.get('rolesByModel')) is dict,
          'identity.principal_mismatch')
    role = user['rolesByModel'].get(target['model_id'])
    _need(type(role) is dict and role.get('connectionId') == target['connection_id']
          and type(role.get('permissions')) is list and all(type(x) is str for x in role['permissions']),
          'identity.model_permissions_missing')
    model, branch = _model(transport, target['model_id']), _model(transport, target['branch_id'])
    _need(model.get('modelKind') == 'SHARED' and _uuid(model.get('baseModelId'))
          and model.get('connectionId') == target['connection_id'], 'identity.shared_model_mismatch')
    _need(branch.get('modelKind') == 'BRANCH' and branch.get('baseModelId') == target['model_id']
          and branch.get('connectionId') == target['connection_id'], 'identity.branch_mismatch')
    schema = _model(transport, model['baseModelId'])
    _need(schema.get('modelKind') == 'SCHEMA' and schema.get('connectionId') == target['connection_id'],
          'identity.schema_mismatch')
    connections = []
    for connection_id in sorted({target['connection_id'], target['environment_connection_id']}):
        data = _get(transport, '/api/v1/connections/' + connection_id)
        connection = data.get('connection') if type(data) is dict else None
        _need(type(connection) is dict and connection.get('id') == connection_id and connection.get('deletedAt') is None,
              'identity.connection_mismatch')
        connections.append(connection)
    stable = {'target': target, 'schema_id': model['baseModelId'], 'permissions': sorted(role['permissions']),
              'key_scope': user.get('keyScope'), 'connections': connections}
    return {'sha256': canonical_hash(stable), 'schema_id': model['baseModelId'], 'permissions': role['permissions']}


def _yaml(transport, model_id, branch_id=None, resolved=False):
    params = {'mode': 'combined', 'includeChecksums': 'true', 'fullyResolved': 'true' if resolved else 'false'}
    if branch_id:
        params['branchId'] = branch_id
    data = _get(transport, '/api/v1/models/' + model_id + '/yaml', params)
    _need(type(data) is dict and type(data.get('files')) is dict and type(data.get('checksums')) is dict
          and type(data.get('version')) is int and type(data.get('viewNames', {})) is dict,
          'snapshot.invalid_yaml_response')
    _need(set(data['files']) == set(data['checksums']) and len(data['files']) <= MAX_FILES
          and all(type(k) is str and type(v) is str for k, v in data['files'].items())
          and all(type(v) is str and v for v in data['checksums'].values()), 'snapshot.incomplete_file_inventory')
    return {k: data.get(k, {}) for k in ('files', 'checksums', 'version', 'viewNames')}


def _state(transport, target):
    identity = _identity(transport, target)
    values = {'authored': _yaml(transport, target['model_id'], target['branch_id']),
              'resolved': _yaml(transport, target['model_id'], target['branch_id'], True),
              'base': _yaml(transport, target['model_id']),
              'schema': _yaml(transport, identity['schema_id'], resolved=True)}
    hashes = {key + '_sha256': canonical_hash(value) for key, value in values.items()}
    hashes['identity_sha256'] = identity['sha256']
    return {'hashes': hashes, 'snapshots': values, 'identity': identity}


def _policy(policy_path, candidate_root, destination_id, target):
    root = canonical_path(candidate_root)
    _need(root.is_dir(), 'runner.candidate_root')
    policy, digest = load_policy(policy_path, excluded_roots=(root,))
    _need('deploy_development' in policy['allowed_actions'] and policy['destinations'].get(destination_id) == target,
          'runner.destination_not_provisioned')
    return policy, digest


def _transport(policy, target, supplied):
    if supplied is not None:
        return supplied, 'simulation'
    _need(policy['mode'] == 'live', 'runner.simulation_requires_injected_transport')
    return HTTPSOmniTransport(target['instance_url']), 'live'


def _approval(request, policy, digest, envelope):
    try:
        payload = verify_attestation(envelope, policy, purpose='deployment_approval',
                                     bindings=request_bindings(request, digest))
    except (ValueError, TypeError, KeyError):
        raise AdapterError('authorization.attestation_invalid') from None
    claims = payload.get('claims', {})
    _need(type(claims) is dict, 'authorization.claims_required')
    preflight = claims.get('preflight', {})
    _need(type(preflight) is dict and preflight.get('target_sha256') == canonical_hash(request['target'])
          and all(preflight.get(k) is True for k in ('principal_namespace_verified', 'permissions_verified',
                  'existing_destination_approved', 'synthetic_data_only', 'isolated_destination', 'branch_exclusive'))
          and _sha(preflight.get('audience_sha256')) and _sha(preflight.get('access_policy_sha256'))
          and _sha(preflight.get('evidence_sha256')) and type(preflight.get('evidence_reference')) is str
          and bool(preflight['evidence_reference'].strip()), 'authorization.preflight_required')
    if request['operation'] == 'query':
        _need(preflight.get('effective_timezone') == request['timezone'], 'authorization.query_timezone_unverified')
    return payload


def _private_file(path, body, replace=False):
    path = canonical_path(path, exists=False)
    _need(path.parent.is_dir() and (replace or not path.exists()), 'runner.output_exists')
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.omni-', delete=False) as stream:
            tmp = Path(stream.name)
            os.chmod(tmp, 0o600)
            stream.write(_json_bytes(body) + b'\n'); stream.flush(); os.fsync(stream.fileno())
        if replace:
            os.replace(tmp, path)
        else:
            os.link(tmp, path); tmp.unlink()
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


class _Journal:
    def __init__(self, policy, candidate_root, request, policy_hash):
        self.root = outside(policy['state_root'], (candidate_root,))
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.stat()
        _need(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, 'runner.private_state_required')
        self.path = self.root / (request['run_id'] + '.json')
        self.lock_path = self.root / (request['run_id'] + '.lock')
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, 'r+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise AdapterError('runner.run_already_active') from None
        try:
            if self.path.exists():
                self.data = _json(_read(self.path))
                _need(self.path.stat().st_mode & 0o077 == 0 and self.data.get('request_sha256') == canonical_hash(request)
                      and self.data.get('policy_sha256') == policy_hash, 'runner.journal_binding_mismatch')
            else:
                self.data = {'schema_version': 1, 'kind': 'omni_operation_journal',
                             'request_sha256': canonical_hash(request), 'policy_sha256': policy_hash,
                             'updates': [], 'query': None}
                self.save()
        except BaseException:
            self.close()
            raise

    def save(self):
        _private_file(self.path, self.data, replace=self.path.exists())

    def close(self):
        self.lock.close()


def _same_dependencies(before, after):
    return all(before['hashes'][key] == after['hashes'][key]
               for key in ('base_sha256', 'schema_sha256', 'identity_sha256'))


def _assert_candidate(state, request):
    _need(state['snapshots']['authored']['files'] == request['files'], 'snapshot.candidate_mismatch')


def _validation(transport, target, files, warning_policy):
    reply = _call(transport, 'GET', '/api/v1/models/' + target['model_id'] + '/validate',
                  {'branchId': target['branch_id']})
    issues = _json(reply.body)
    _need(type(issues) is list and len(issues) <= 1000, 'validation.issue_array_required')
    findings = []
    paths = sorted(files)
    for index, item in enumerate(issues):
        _need(type(item) is dict and type(item.get('is_warning')) is bool
              and type(item.get('message')) is str and type(item.get('yaml_path')) is str,
              'validation.invalid_issue')
        findings.append({'index': index, 'severity': 'warning' if item['is_warning'] else 'error',
                         'file_index': paths.index(item['yaml_path']) if item['yaml_path'] in paths else None,
                         'automatic_fix_ignored': 'auto_fix' in item})
    failed = any(x['severity'] == 'error' or warning_policy == 'fail' for x in findings)
    return {'passed': not failed, 'issues': findings, 'response_sha256': hashlib.sha256(reply.body).hexdigest()}


def _update(transport, request, initial, journal, authorize):
    desired = request['files']; authored = initial['snapshots']['authored']
    _need(set(authored['files']) <= set(desired), 'write.deletion_not_supported')
    records = journal.data['updates']
    _need(type(records) is list and len(records) <= MAX_FILES, 'runner.invalid_journal')
    by_name = {row['file']: row for row in records}
    for name in sorted(desired):
        # Every retry reconciles exact remote content before considering a write.
        fresh = _state(transport, request['target'])
        _need(_same_dependencies(initial, fresh), 'snapshot.dependencies_changed')
        current = fresh['snapshots']['authored']
        for other, body in current['files'].items():
            expected = desired.get(other) if by_name.get(other, {}).get('state') == 'confirmed' else authored['files'].get(other)
            if other != name:
                _need(body == expected, 'write.unrelated_remote_change')
        existing = current['files'].get(name)
        record = by_name.get(name)
        if existing == desired[name]:
            if record is not None:
                record['state'] = 'confirmed'; journal.save()
            continue
        if record is not None:
            _need(existing == authored['files'].get(name), 'write.conflicting_reconciliation')
            _need(record['attempts'] < 2, 'write.retry_limit')
        else:
            _need(existing == authored['files'].get(name), 'write.remote_change')
            record = {'file': name, 'before_sha256': canonical_hash(existing),
                      'desired_sha256': canonical_hash(desired[name]), 'state': 'intent', 'attempts': 0}
            records.append(record); by_name[name] = record
        authorize()
        record['state'] = 'intent'; record['attempts'] += 1; journal.save()
        body = {'fileName': name, 'yaml': desired[name], 'mode': 'combined',
                'branchId': request['target']['branch_id'], 'fullyResolved': False,
                'commitMessage': request['commit_message']}
        if name in current['files']:
            body['previousChecksum'] = current['checksums'][name]
        try:
            response = _json(_call(transport, 'POST', '/api/v1/models/' + request['target']['model_id'] + '/yaml', body=body).body)
            _need(type(response) is dict and response.get('success') is True and response.get('fileName') == name,
                  'write.response_unconfirmed')
        except (TransportError, ValueError):
            record['state'] = 'unknown'; journal.save()
            # Never retry automatically after an ambiguous write. A resumed run
            # reads the exact branch first, then reconciles this recorded intent.
            raise
        readback = _yaml(transport, request['target']['model_id'], request['target']['branch_id'])
        _need(readback['files'].get(name) == desired[name], 'write.readback_mismatch')
        record['state'] = 'confirmed'; journal.save()
    return _state(transport, request['target'])


def _query(transport, request, journal, authorize):
    saved = journal.data.get('query')
    if saved and saved.get('state') == 'complete':
        raise AdapterError('query.already_completed_use_original_receipt')
    if saved and saved.get('state') == 'unknown':
        raise AdapterError('query.unknown_outcome_requires_reconciliation')
    if saved and saved.get('state') == 'intent':
        raise AdapterError('query.interrupted_submission_requires_reconciliation')
    jobs = saved.get('jobs', []) if saved else []
    evidence = saved.get('evidence', {'response_sha256': [], 'completed_jobs': [], 'rows': None}) if saved else {
        'response_sha256': [], 'completed_jobs': [], 'rows': None}
    reply = None
    if not saved:
        authorize()
        journal.data['query'] = {'state': 'intent'}; journal.save()
        body = {'query': request['query'], 'branchId': request['target']['branch_id'],
                'environmentConnectionId': request['target']['environment_connection_id'], 'cache': 'SkipCache',
                'timezone': request['timezone']}
        if request['query_mode'] == 'plan':
            body['planOnly'] = True
        else:
            body.update(resultType='json', formatResults=False)
        try:
            # 408 may contain resumable job IDs; retain the bounded body here.
            reply = transport.request('POST', '/api/v1/query/run', body=body)
            _need(type(reply) is Response and len(reply.body) <= MAX_BYTES, 'response.shape')
            if reply.status == 408:
                payload = _json(reply.body); jobs = payload.get('remaining_job_ids') if type(payload) is dict else None
                _need(type(jobs) is list and jobs and len(jobs) <= 20 and all(_uuid(x) for x in jobs), 'query.timeout_without_jobs')
                reply = None
            elif reply.status != 200:
                raise TransportError('transport.http', reply.status, reply.status >= 500)
        except (TransportError, ValueError):
            journal.data['query'] = {'state': 'unknown'}; journal.save()
            raise
    for poll in range(MAX_POLLS + 1):
        if reply is None:
            journal.data['query'] = {'state': 'jobs', 'jobs': jobs, 'evidence': evidence}; journal.save()
            if poll == MAX_POLLS:
                return dict(evidence, pending=True)
            authorize()
            reply = _call(transport, 'GET', '/api/v1/query/wait', {'jobIds': ','.join(jobs)})
        evidence['response_sha256'].append(hashlib.sha256(reply.body).hexdigest())
        if reply.content_type.split(';')[0] == 'application/json' and request['query_mode'] == 'execute':
            rows = _json(reply.body)
            _need(type(rows) is list and all(type(x) is dict for x in rows) and len(rows) <= 1000,
                  'query.result_rows_required')
            evidence['rows'] = len(rows); jobs = []
        else:
            _need(reply.content_type.split(';')[0] in ('text/ndjson', 'application/x-ndjson'), 'query.ndjson_required')
            lines = reply.body.splitlines()
            _need(1 <= len(lines) <= 100, 'query.stream_bounds')
            values = [_json(line) for line in lines]
            footer = values[-1]
            _need(type(footer) is dict and type(footer.get('remaining_job_ids')) is list
                  and footer.get('timed_out') in ('true', 'false'), 'query.footer_required')
            expected_jobs = set(jobs)
            for value in values[:-1]:
                _need(type(value) is dict, 'query.stream_object')
                if 'jobs_submitted' in value:
                    _need(not expected_jobs and type(value['jobs_submitted']) is dict and value['jobs_submitted']
                          and all(_uuid(x) for x in value['jobs_submitted']), 'query.submission_header')
                    expected_jobs = set(value['jobs_submitted']); continue
                identity = value.get('job_id')
                _need(identity in expected_jobs and identity not in evidence['completed_jobs']
                      and value.get('status') == 'COMPLETE', 'query.job_not_complete')
                if request['query_mode'] == 'plan':
                    _need(type(value.get('summary')) is dict and type(value['summary'].get('sql')) is str
                          and bool(value['summary']['sql'].strip()), 'query.plan_sql_missing')
                else:
                    _need(type(value.get('result')) is str, 'query.arrow_result_missing')
                    try:
                        decoded = base64.b64decode(value['result'], validate=True)
                        _need(bool(decoded), 'query.empty_arrow')
                    except ValueError:
                        raise AdapterError('query.invalid_arrow_encoding') from None
                evidence['completed_jobs'].append(identity)
            jobs = footer['remaining_job_ids']
            _need(len(jobs) <= 20 and all(_uuid(x) for x in jobs) and len(set(jobs)) == len(jobs)
                  and set(jobs) == expected_jobs - set(evidence['completed_jobs'])
                  and (footer['timed_out'] == 'false') == (not jobs), 'query.incomplete_stream')
            _need(bool(expected_jobs), 'query.no_jobs_observed')
        if not jobs:
            journal.data['query'] = {'state': 'complete', 'evidence': evidence}; journal.save()
            return evidence
        reply = None
    return dict(evidence, pending=True)


def run(request, *, policy_path, candidate_root, approval=None, transport=None):
    """Run exact reviewed work. Supplying any transport forces simulation labels."""
    report = {'schema_version': 1, 'kind': 'omni_native_receipt', 'contract_version': CONTRACT,
              'status': 'blocked', 'execution_mode': 'simulation' if transport is not None else 'live',
              'native_verified': False, 'native_qualification': 'pending', 'code': None,
              'observed_at': datetime.now(timezone.utc).isoformat(),
              'limitations': ['Observation is not business acceptance or access-policy qualification.',
                              'New-file creation has no documented atomic create-if-absent precondition.',
                              'Snapshot comparisons are not an atomic server-side validation transaction.']}
    journal = None
    try:
        request = validate_request(request)
        policy, policy_hash = _policy(policy_path, candidate_root, request['destination_id'], request['target'])
        report.update(request_sha256=canonical_hash(request), target=copy.deepcopy(request['target']),
                      candidate_sha256=canonical_hash(request['files']), context_sha256=canonical_hash(request['context']),
                      policy_sha256=policy_hash, operation=request['operation'])
        if request['operation'] == 'query':
            report.update(query_mode=request['query_mode'],
                          query_lane='native_compilation' if request['query_mode'] == 'plan' else 'modeled_query_execution',
                          timezone=request['timezone'])
        client, mode = _transport(policy, request['target'], transport); report['execution_mode'] = mode
        if mode == 'live' and not client.available:
            report.update(status='pending', code='credentials.unavailable'); return report
        def authorize():
            current_policy, current_hash = _policy(policy_path, candidate_root, request['destination_id'], request['target'])
            _need(current_hash == policy_hash, 'authorization.policy_changed')
            return _approval(request, current_policy, current_hash, approval)
        if request['operation'] != 'validate':
            authenticated = authorize(); report['approval_id'] = authenticated['id']
        initial = _state(client, request['target'])
        if request['operation'] == 'update_and_validate':
            _need('UPDATE' in initial['identity']['permissions'], 'authorization.model_update_permission_missing')
        elif request['operation'] == 'query':
            _need(bool(set(initial['identity']['permissions']) & {'QUERY_TOPICS', 'QUERY_FULL_MODEL'}),
                  'authorization.query_permission_missing')
        journal = _Journal(policy, candidate_root, request, policy_hash)
        # On resume, the original immutable snapshot remains the baseline. It
        # stores no raw YAML; recovered per-file intentions carry bounded hashes.
        saved = journal.data.get('baseline')
        if saved is None:
            _need(initial['hashes'] == request['expected_remote'], 'snapshot.baseline_changed')
            journal.data['baseline'] = {'hashes': initial['hashes'],
                'files': {k: canonical_hash(v) for k, v in initial['snapshots']['authored']['files'].items()}}
            journal.save()
        else:
            _need(saved['hashes'] == request['expected_remote']
                  and all(initial['hashes'][k] == saved['hashes'][k] for k in ('base_sha256','schema_sha256','identity_sha256')),
                  'snapshot.resume_dependencies_changed')
            _need(set(saved['files']) <= set(initial['snapshots']['authored']['files']), 'snapshot.resume_file_deleted')
            for name, body in initial['snapshots']['authored']['files'].items():
                previous = saved['files'].get(name)
                desired = request['files'].get(name)
                recorded = next((x for x in journal.data['updates'] if x['file'] == name), None)
                _need(canonical_hash(body) == previous or (recorded is not None and body == desired), 'snapshot.resume_content_conflict')
                if recorded and body == desired:
                    recorded['state'] = 'confirmed'
            journal.save()
        if request['operation'] == 'update_and_validate':
            # After restart, use the observed unchanged/past-confirmed bytes as
            # the next checkpoint; original hashes remain in the private journal.
            before = _update(client, request, initial, journal, authorize)
        else:
            before = initial
        _assert_candidate(before, request)
        if request['operation'] == 'query':
            evidence = _query(client, request, journal, authorize)
            report['query'] = evidence
            passed = not evidence.get('pending', False)
        else:
            evidence = _validation(client, request['target'], request['files'], request['warning_policy'])
            report['validation'] = evidence; passed = evidence['passed']
        after = _state(client, request['target'])
        _assert_candidate(after, request)
        _need(before['hashes'] == after['hashes'], 'snapshot.changed_during_validation')
        report.update(remote_before=before['hashes'], remote_after=after['hashes'],
                      status=('passed' if mode == 'live' else 'simulated_passed') if passed else ('pending' if evidence.get('pending') else 'failed'),
                      native_verified=passed and mode == 'live', code=None if passed else 'native.check_not_passed')
    except TransportError as error:
        report.update(status='pending' if error.uncertain or error.status in (408,429,500,502,503,504) else 'failed',
                      code=error.code, http_status=error.status, native_verified=False)
    except AdapterError as error:
        report.update(status='blocked', code=str(error), native_verified=False)
    except (ValueError, TypeError, OSError, RecursionError, KeyError, UnicodeError):
        # Never echo source/issuer/provider exceptions into ordinary diagnostics.
        report.update(status='blocked', code='native.invalid_or_unverified_state', native_verified=False)
    finally:
        if journal:
            journal.close()
    return report


def verify_receipt(request, receipt, policy_sha256):
    """Check exact local bindings/integrity, never authenticate imported claims."""
    result = {'status': 'failed', 'authenticated': False, 'native_qualification': 'pending',
              'code': 'receipt.invalid', 'assurance': 'Local consistency only; external evidence authentication is separate.'}
    try:
        request = validate_request(request)
        _json_bytes(receipt)
        _need(type(receipt) is dict and receipt.get('schema_version') == 1
              and receipt.get('kind') == 'omni_native_receipt' and receipt.get('contract_version') == CONTRACT,
              'receipt.schema')
        for key, expected in {'request_sha256': canonical_hash(request), 'target': request['target'],
            'candidate_sha256': canonical_hash(request['files']), 'context_sha256': canonical_hash(request['context']),
            'policy_sha256': policy_sha256, 'operation': request['operation']}.items():
            _need(receipt.get(key) == expected, 'receipt.bindings')
        if request['operation'] == 'query':
            _need(receipt.get('query_mode') == request['query_mode'] and receipt.get('timezone') == request['timezone']
                  and receipt.get('query_lane') == ('native_compilation' if request['query_mode'] == 'plan' else 'modeled_query_execution'),
                  'receipt.query_lane')
        mode, status = receipt.get('execution_mode'), receipt.get('status')
        _need(mode in ('live', 'simulation') and type(receipt.get('native_verified')) is bool,
              'receipt.execution_mode')
        _need(status in ('passed','simulated_passed','failed','pending','blocked'), 'receipt.status')
        _need(not receipt['native_verified'] or mode == 'live' and status == 'passed', 'receipt.simulation_not_native')
        if status in ('passed', 'simulated_passed'):
            _need((mode == 'live' and status == 'passed' and receipt['native_verified'])
                  or (mode == 'simulation' and status == 'simulated_passed' and not receipt['native_verified']),
                  'receipt.pass_mode')
            before, after = receipt.get('remote_before'), receipt.get('remote_after')
            _need(type(before) is dict and set(before) == SNAPSHOT_KEYS and all(_sha(x) for x in before.values())
                  and before == after, 'receipt.snapshot')
            evidence = receipt.get('query' if request['operation'] == 'query' else 'validation')
            _need(type(evidence) is dict, 'receipt.evidence')
            if request['operation'] != 'query':
                _need(evidence.get('passed') is True and _sha(evidence.get('response_sha256'))
                      and type(evidence.get('issues')) is list
                      and all(type(row) is dict and row.get('severity') == 'warning'
                              and request['warning_policy'] == 'allow' for row in evidence['issues']), 'receipt.validation')
            else:
                _need(type(evidence.get('response_sha256')) is list and evidence['response_sha256']
                      and all(_sha(x) for x in evidence['response_sha256']) and not evidence.get('pending'), 'receipt.query')
        result.update(status='integrity_verified', code=None)
    except AdapterError as error:
        result['code'] = str(error)
    except (ValueError, TypeError, KeyError, RecursionError):
        pass
    return result


def inspect_remote(target, *, policy_path, candidate_root, destination_id, transport=None):
    """Read-only bootstrap snapshot; raw remote YAML must stay private."""
    target = validate_target(target)
    policy, _ = _policy(policy_path, candidate_root, destination_id, target)
    client, mode = _transport(policy, target, transport)
    if mode == 'live' and not client.available:
        return {'schema_version': 1, 'kind': 'omni_remote_snapshot', 'status': 'pending', 'code': 'credentials.unavailable'}
    state = _state(client, target)
    return {'schema_version': 1, 'kind': 'omni_remote_snapshot', 'status': 'private_snapshot',
            'execution_mode': mode, 'native_verified': False, 'target': target,
            'expected_remote': state['hashes'], 'files': state['snapshots']['authored']['files'],
            'snapshot': state['snapshots'], 'assurance': 'Private bootstrap evidence, not validation or deployment authority.'}


def run_reviewed_variants(requests, *, policy_path, candidate_root, approvals, transport=None):
    """At most two independently signed variants; never generate/apply autofix."""
    _need(type(requests) is list and 1 <= len(requests) <= 2 and type(approvals) is list
          and len(requests) == len(approvals), 'repair.bounded_reviewed_variants_required')
    results = []
    for index, request in enumerate(requests):
        if index:
            policy, digest = _policy(policy_path, candidate_root, request['destination_id'], request['target'])
            payload = _approval(request, policy, digest, approvals[index])
            claims = payload.get('claims', {})
            if (claims.get('semantic_scope_unchanged') is not True
                    or claims.get('supersedes_request_sha256') != canonical_hash(requests[index-1])
                    or request['target'] != requests[0]['target']):
                return {'status': 'requires_review', 'attempts': results, 'automatic_fixes_applied': False}
        result = run(request, policy_path=policy_path, candidate_root=candidate_root,
                     approval=approvals[index], transport=transport)
        results.append(result)
        if result['status'] != 'failed':
            break
    return {'status': results[-1]['status'], 'attempts': results, 'automatic_fixes_applied': False}


def _read(path):
    path = canonical_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, 'input.file_bounds')
        data = stream.read(MAX_BYTES + 1); after = os.fstat(stream.fileno())
    _need((before.st_size,before.st_mtime_ns,before.st_ino,before.st_ctime_ns) ==
          (after.st_size,after.st_mtime_ns,after.st_ino,after.st_ctime_ns), 'input.changed')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'run', 'bindings', 'repair'))
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = _json(_read(args.request))
        approval = _json(_read(args.approval)) if args.approval else None
        if args.action == 'inspect':
            result = inspect_remote(request['target'], policy_path=args.policy, candidate_root=args.candidate_root,
                                    destination_id=request['destination_id'])
        elif args.action == 'bindings':
            request = validate_request(request)
            _, digest = _policy(args.policy, args.candidate_root, request['destination_id'], request['target'])
            result = request_bindings(request, digest)
        elif args.action == 'repair':
            result = run_reviewed_variants(request, policy_path=args.policy, candidate_root=args.candidate_root, approvals=approval)
        else:
            result = run(request, policy_path=args.policy, candidate_root=args.candidate_root, approval=approval)
        _private_file(outside(args.output, (args.candidate_root,)), result)
        print(json.dumps({'status': result.get('status', 'private_bindings'), 'native_verified': result.get('native_verified', False)}))
        return 0 if result.get('status') in ('passed', 'private_snapshot') or args.action == 'bindings' else 1
    except (ValueError, OSError, TypeError, KeyError, RecursionError, TransportError):
        print(json.dumps({'status': 'blocked', 'code': 'native.invalid_or_unavailable_input', 'native_verified': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
