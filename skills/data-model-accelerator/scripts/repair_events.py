"""Append-only repair receipts with a caller-pinned, self-attested hash chain.

The caller must retain the expected head outside this file. The chain does not
authenticate actors/artifacts or make a rewritten file tamper-proof. POSIX locks
coordinate cooperating writers; this is not a hostile-filesystem sandbox.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat

from ae_common import hash_json, require

try:
    import fcntl
except ImportError:
    fcntl = None

ZERO_HEAD = '0' * 64
MAX_BYTES = 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}\Z')
KINDS = {'validation_failed', 'repair_completed', 'validation_passed'}
PAYLOAD = {'kind', 'candidate_sha256', 'evidence_sha256', 'at', 'actor_id', 'task_id', 'case_ids'}
FIELDS = PAYLOAD | {'sequence', 'previous_sha256', 'event_sha256'}


def _text(value, label):
    require(type(value) is str and value and value == value.strip() and
            not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid ' + label)
    return value


def _sha(value):
    require(type(value) is str and SHA.fullmatch(value) is not None, 'Invalid SHA-256')
    return value


def _scope(values, label):
    require(type(values) in (list, tuple, set), label + ' must be a collection of identifiers')
    for value in values:
        _text(value, label)
    require(len(set(values)) == len(values), 'Duplicate ' + label)
    return set(values)


def _time(value):
    _text(value, 'event timestamp')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.tzinfo is not None and stamp.utcoffset() == timezone.utc.utcoffset(stamp), 'Event timestamp must be UTC')
    return stamp


def _payload(event, case_ids, task_ids):
    require(type(event) is dict and set(event) == PAYLOAD, 'Missing or unknown event payload fields')
    require(type(event['kind']) is str and event['kind'] in KINDS, 'Invalid event kind')
    _sha(event['candidate_sha256'])
    _sha(event['evidence_sha256'])
    _text(event['actor_id'], 'actor_id')
    _time(event['at'])
    require(type(event['case_ids']) is list, 'Event case_ids must be a list')
    cases = _scope(event['case_ids'], 'case_ids')
    require(cases <= case_ids, 'Event references unknown case IDs')
    if event['kind'] == 'repair_completed':
        require(type(event['task_id']) is str and event['task_id'] in task_ids, 'Repair requires a known task_id')
    else:
        require(event['task_id'] is None, 'Validation task_id must be null')
        require(bool(cases) if event['kind'] == 'validation_failed' else not cases,
                'Failed validation requires cases; passed validation requires no failed cases')


def _verify(events, expected_head, case_ids, task_ids):
    _sha(expected_head)
    previous, previous_time, repairs = None, None, 0
    head = ZERO_HEAD
    for index, event in enumerate(events, 1):
        require(type(event) is dict and set(event) == FIELDS, 'Missing or unknown stored event fields')
        _payload({key: event[key] for key in PAYLOAD}, case_ids, task_ids)
        require(type(event['sequence']) is int and event['sequence'] == index, 'Invalid event sequence')
        require(_sha(event['previous_sha256']) == head, 'Broken previous hash association')
        digest = hash_json({key: value for key, value in event.items() if key != 'event_sha256'})
        require(_sha(event['event_sha256']) == digest, 'Event hash changed')
        instant = _time(event['at'])
        require(previous_time is None or instant >= previous_time, 'Event timestamps must be monotonic')
        kind = event['kind']
        if previous is None:
            require(kind in ('validation_failed', 'validation_passed'), 'First event must be validation')
        elif previous['kind'] == 'validation_failed':
            require(kind == 'repair_completed', 'Failed validation must be followed by repair_completed')
            require(event['candidate_sha256'] != previous['candidate_sha256'], 'Repair candidate must change from failed candidate')
        elif previous['kind'] == 'repair_completed':
            require(kind in ('validation_failed', 'validation_passed'), 'Repair must be followed by validation')
            require(event['candidate_sha256'] == previous['candidate_sha256'], 'Validation candidate must match preceding repair')
        else:
            raise ValueError('Cannot append after passed validation')
        if kind == 'repair_completed':
            repairs += 1
            require(repairs <= 3, 'Repair limit exceeded (3)')
        previous, previous_time, head = event, instant, digest
    require(head == expected_head, 'Event head differs from caller expected_head')
    return events


def _path(path):
    path = Path(path).absolute()
    require('..' not in path.parts and not any(p.is_symlink() for p in (path,) + tuple(path.parents)), 'Event path must not escape or traverse symlinks')
    require(path.parent.is_dir(), 'Event parent directory must exist')
    require(not path.exists() or path.is_file(), 'Event log must be a regular file')
    return path


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'Duplicate JSON event key')
        value[key] = item
    return value


def _read(stream):
    stream.seek(0)
    content = stream.read(MAX_BYTES + 1)
    require(len(content) <= MAX_BYTES, 'Event log byte limit exceeded')
    require(not content or content.endswith(b'\n'), 'Incomplete final JSONL event')
    return [json.loads(line, object_pairs_hook=_pairs) for line in content.decode('utf-8').splitlines()]


def _locked_file(path, write=False):
    require(fcntl is not None and hasattr(os, 'O_NOFOLLOW'), 'POSIX file locking is required for this event log')
    flags = (os.O_RDWR | os.O_CREAT if write else os.O_RDONLY) | os.O_NOFOLLOW
    descriptor = os.open(str(path), flags, 0o600)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), 'Event log must be a regular file')
        stream = os.fdopen(descriptor, 'r+b' if write else 'rb')
    except Exception:
        os.close(descriptor)
        raise
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
    except Exception:
        stream.close()
        raise
    return stream  # Closing the stream releases its flock.


def verify_events(path, expected_head, case_ids, task_ids):
    """Return validated events, including incomplete repair cycles for appending."""
    cases, tasks = _scope(case_ids, 'known case_ids'), _scope(task_ids, 'known task_ids')
    path = _path(path)
    if not path.exists():
        return _verify([], expected_head, cases, tasks)
    with _locked_file(path) as stream:
        return _verify(_read(stream), expected_head, cases, tasks)


def append_event(path, event, expected_head, case_ids, task_ids):
    """Validate the current pinned chain under lock before appending one event."""
    _sha(expected_head)
    cases, tasks = _scope(case_ids, 'known case_ids'), _scope(task_ids, 'known task_ids')
    _payload(event, cases, tasks)
    path = _path(path)
    if not path.exists():
        require(expected_head == ZERO_HEAD, 'Missing log differs from caller expected_head')
        require(event['kind'] in ('validation_failed', 'validation_passed'), 'First event must be validation')
    with _locked_file(path, write=True) as stream:
        events = _verify(_read(stream), expected_head, cases, tasks)
        stored = dict(event, sequence=len(events) + 1, previous_sha256=expected_head)
        stored['event_sha256'] = hash_json(stored)
        _verify(events + [stored], stored['event_sha256'], cases, tasks)
        content = (json.dumps(stored, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode('utf-8')
        stream.seek(0, os.SEEK_END)
        require(stream.tell() + len(content) <= MAX_BYTES, 'Event log byte limit exceeded')
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
        return stored
