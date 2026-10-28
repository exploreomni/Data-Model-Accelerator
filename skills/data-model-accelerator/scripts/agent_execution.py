"""Record bounded host observations against an existing specialist context packet.

``record_execution(packet_dir, request)`` returns a JSON-safe receipt and writes
nothing. It never launches a model, chooses an effort, reads host logs, measures
tokens, authenticates a host or establishes isolation. The caller supplies host
observations explicitly. Null observed settings remain unknown even when a
requested setting is present. Packet integrity is separate from host assurance.

The request pins the exact TASK.md and CONTEXT_RECEIPT.json bytes. Optional usage
contains input_tokens, output_tokens, cache_read_tokens and cache_write_tokens;
each is an explicit nonnegative integer or null. Counts are not summed because
host definitions can overlap. No model-price table or cost estimate is used.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from ae_common import _path, hash_json, require


MAX_PACKET_BYTES = 65536
MAX_CONTEXT_RECEIPT_BYTES = 512 * 1024
MAX_TOKEN_COUNT = 2**63 - 1
SHA = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z')
REQUEST_FIELDS = {'schema_version', 'kind', 'task_id', 'run_id', 'packet_sha256',
                  'source_context_receipt_sha256', 'requested_model', 'observed_model',
                  'requested_effort', 'observed_effort', 'context_mode', 'host_run_reference'}
USAGE_FIELDS = {'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens'}
CONTEXT_FIELDS = {'schema_version', 'kind', 'task_id', 'role', 'mode', 'request_sha256',
                  'packet_sha256', 'bindings', 'evidence', 'file_coverage', 'input_classifications',
                  'packet_classification', 'packet_bytes', 'max_packet_bytes', 'summary_bytes',
                  'selected_source_bytes', 'host_context_mode', 'specialist_executed',
                  'host_isolation_verified', 'assurance'}
TASK_MARKER = '## Task data and selected evidence\n\n'


def _fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional),
            'Invalid execution observation fields')


def _text(value, limit, nullable=False):
    if value is None and nullable:
        return
    require(type(value) is str and value == value.strip() and bool(value)
            and len(value.encode('utf-8')) <= limit
            and all(ord(char) >= 32 and ord(char) != 127 for char in value),
            'Expected bounded single-line observation text')


def _sha(value):
    require(type(value) is str and SHA.fullmatch(value), 'Invalid execution evidence pin')


def validate_request(request):
    """Validate explicit host input without resolving unknown observed values."""
    _fields(request, REQUEST_FIELDS, {'usage', 'usage_reference'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1
            and request['kind'] == 'agent_execution_request', 'Unsupported execution observation version')
    for name in ('task_id', 'run_id'):
        require(type(request[name]) is str and ID.fullmatch(request[name]), 'Invalid execution identity')
    for name in ('packet_sha256', 'source_context_receipt_sha256'):
        _sha(request[name])
    for name in ('requested_model', 'observed_model'):
        _text(request[name], 256, nullable=True)
    for name in ('requested_effort', 'observed_effort'):
        _text(request[name], 64, nullable=True)
    require(type(request['context_mode']) is str and request['context_mode'] in {'fresh', 'inherited', 'unknown'},
            'Invalid host context observation')
    _text(request['host_run_reference'], 1024, nullable=True)
    _text(request.get('usage_reference'), 1024, nullable=True)
    usage = request.get('usage', {key: None for key in USAGE_FIELDS})
    _fields(usage, USAGE_FIELDS)
    require(all(value is None or (type(value) is int and 0 <= value <= MAX_TOKEN_COUNT)
                for value in usage.values()), 'Invalid explicit host token count')
    return {**copy.deepcopy(request), 'usage': copy.deepcopy(usage),
            'usage_reference': request.get('usage_reference')}


def _read(path, limit):
    path = _path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit,
                'Invalid or oversized context evidence file')
        body = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        require(len(body) == before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns,
                'Context evidence changed while reading')
    return body


def _json(body):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'Duplicate context evidence field')
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError('Nonfinite context evidence number')

    value = json.loads(body, object_pairs_hook=pairs, parse_constant=nonfinite)
    # Reuse core JSON validation, including finite floating-point checks.
    hash_json(value)
    return value


def _context(receipt, packet, request):
    _fields(receipt, CONTEXT_FIELDS, {'requested_role', 'specialist_profile', 'assignment_sha256'})
    require(type(receipt['schema_version']) is int and receipt['schema_version'] == 1
            and receipt['kind'] == 'agent_context_receipt', 'Unsupported source context receipt')
    require(receipt['task_id'] == request['task_id'], 'Context task identity differs')
    _text(receipt['role'], 64)
    _text(receipt['assurance'], 2048)
    for name in ('request_sha256', 'packet_sha256'):
        _sha(receipt[name])
    for name in ('packet_bytes', 'max_packet_bytes', 'summary_bytes', 'selected_source_bytes'):
        require(type(receipt[name]) is int and receipt[name] >= 0, 'Invalid context byte count')
    require(receipt['packet_bytes'] == len(packet) and receipt['packet_sha256'] == request['packet_sha256']
            and 1024 <= receipt['max_packet_bytes'] <= MAX_PACKET_BYTES
            and len(packet) <= receipt['max_packet_bytes'] and receipt['summary_bytes'] <= 8192,
            'Context packet size or digest differs')
    require(receipt['host_context_mode'] == 'fresh_requested_not_verified'
            and receipt['specialist_executed'] is False and receipt['host_isolation_verified'] is False,
            'Source context receipt cannot claim execution or isolation')
    require(type(receipt['bindings']) is dict and receipt['bindings'], 'Missing source context bindings')
    for key, digest in receipt['bindings'].items():
        _text(key, 256); _sha(digest)
    for name in ('evidence', 'file_coverage', 'input_classifications'):
        require(type(receipt[name]) is list and receipt[name], 'Invalid source context collection')
    require(type(receipt['packet_classification']) is dict, 'Invalid source context classification')
    text = packet.decode('utf-8')
    require(text.startswith('# Bounded specialist task\n\n') and TASK_MARKER in text,
            'Unsupported specialist packet format')
    data = _json(text.split(TASK_MARKER, 1)[1])
    _fields(data, {'task_id', 'role', 'bindings', 'mode', 'brief', 'evidence', 'file_coverage'},
            {'requested_role', 'specialist_profile', 'delta', 'migration_intents', 'design_evidence', 'naming_contract', 'assignment',
             'modeling_standards', 'domain_classification'})
    require(all(data[key] == receipt[key] for key in ('task_id', 'role', 'bindings', 'mode', 'file_coverage')),
            'Context packet identity or bindings differ')
    if 'assignment' in data or 'assignment_sha256' in receipt:
        from task_routing import bind_assignment
        assignment = bind_assignment(data.get('assignment'), task_id=data['task_id'], role=data['role'],
                                     scope_ids=data['brief']['scope_ids'], bindings=data['bindings'])
        require(hash_json(assignment) == receipt.get('assignment_sha256'), 'Context assignment differs')
    from naming_context import validate_packet
    validate_packet(data)
    for module in ('modeling_standards', 'domain_classification'):
        from importlib import import_module
        import_module(module).validate_packet(data)
    if 'migration_intents' in data or any(k.startswith('migration_intent.') for k in data['bindings']):
        from migration_context import packet_evidence
        request_view = {'bindings': data['bindings'], 'migration_intents': data.get('migration_intents', []),
                        'evidence': data['evidence'],
                        'design_evidence': (data.get('design_evidence') or {}).get('evidence_roles', [])}
        require(packet_evidence(request_view) == data.get('design_evidence'),
                'Migration evidence assessment differs from supplied packet context')
    require(type(data['mode']) is str and data['mode'] in {'initial', 'delta'}
            and type(data['brief']) is dict and type(data['evidence']) is list,
            'Malformed specialist packet metadata')


def record_execution(packet_dir, request):
    """Return an additive, host-reported observation bound to exact packet bytes."""
    normalized = validate_request(request)
    root = _path(packet_dir)
    require(root.is_dir(), 'Context packet directory required')
    packet_path, receipt_path = root / 'TASK.md', root / 'CONTEXT_RECEIPT.json'
    packet = _read(packet_path, MAX_PACKET_BYTES)
    source_receipt = _read(receipt_path, MAX_CONTEXT_RECEIPT_BYTES)
    packet_sha = hashlib.sha256(packet).hexdigest()
    receipt_sha = hashlib.sha256(source_receipt).hexdigest()
    require(packet_sha == normalized['packet_sha256'] and receipt_sha == normalized['source_context_receipt_sha256'],
            'Execution request contains stale context pins')
    context_receipt = _json(source_receipt)
    _context(context_receipt, packet, normalized)
    require(_read(packet_path, MAX_PACKET_BYTES) == packet
            and _read(receipt_path, MAX_CONTEXT_RECEIPT_BYTES) == source_receipt,
            'Context evidence changed during recording')
    return {'schema_version': 1, 'kind': 'agent_execution_receipt',
            **{key: normalized[key] for key in REQUEST_FIELDS - {'schema_version', 'kind'}},
            'request_sha256': hash_json(request), 'packet_bytes': len(packet),
            'packet_sha256': packet_sha, 'source_context_receipt_sha256': receipt_sha,
            'context_bindings': copy.deepcopy(context_receipt['bindings']),
            'usage': normalized['usage'], 'usage_reference': normalized['usage_reference'],
            'observed_model_status': 'unknown' if normalized['observed_model'] is None else 'host_reported',
            'observed_effort_status': 'unknown' if normalized['observed_effort'] is None else 'host_reported',
            'assurance': 'host_reported', 'host_isolation_verified': False,
            'model_identity_verified': False, 'execution_verified': False, 'usage_verified': False,
            'qualification': 'Exact packet bytes checked; model, effort, context mode and usage are host observations. '
                             'No verified execution, isolation, billing, business acceptance or approval.'}
