"""Additive, versioned review evidence; never approval or execution authority.

Missing records in older engagements mean unassessed. Reading this contract
does not migrate state or alter any design, review, draft or task bindings.
"""
import copy
import hashlib
import json
from pathlib import Path

from ae_common import require

KINDS = ('coverage', 'reuse', 'reconciliation')


def records(state):
    value = state.get('workflow', {}).get('review_assurance')
    if value is None:
        return {'schema_version': 1, **{key: None for key in KINDS}}
    require(type(value) is dict and set(value) == {'schema_version', *KINDS}
            and type(value['schema_version']) is int and value['schema_version'] == 1,
            'Unsupported review assurance schema; preserve the saved engagement')
    for key in KINDS:
        record = value[key]
        require(record is None or (type(record) is dict and type(record.get('schema_version')) is int
                and record['schema_version'] == 1 and record.get('kind') == key),
                'Unsupported ' + key + ' record; preserve the saved engagement')
    return copy.deepcopy(value)


def save(state, kind, record):
    require(kind in KINDS, 'Unknown review evidence kind')
    require('workflow' in state, 'Adopt stages before recording review evidence')
    value = records(state)
    require(type(record) is dict and type(record.get('schema_version')) is int
            and record['schema_version'] == 1 and record.get('kind') == kind,
            'Invalid versioned review evidence')
    value[kind] = copy.deepcopy(record)
    state['workflow']['review_assurance'] = value


def save_document(state, kind, document, run_dir):
    """Content-addressed local evidence avoids copying large ledgers per revision."""
    import guided_workflow as guided
    records(state)  # Validate before writing anything.
    require(kind in KINDS, 'Unknown review evidence kind')
    raw = json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False,
                     separators=(',', ':')).encode('utf-8')
    require(len(raw) <= guided.MAX_JSON_BYTES, 'Review evidence exceeds 16 MiB; use a smaller scoped engagement')
    digest = hashlib.sha256(raw).hexdigest()
    folder = guided._path(run_dir) / 'review-evidence'
    require(not folder.is_symlink(), 'Review evidence directory must not be a symlink')
    folder.mkdir(exist_ok=True)
    path = folder / (digest + '.json')
    if path.exists():
        require(load_document({'path': str(path), 'sha256': digest, 'bytes': len(raw)}) == document,
                'Existing review evidence differs')
    else:
        guided._atomic_write(path, raw, replace=False)
    save(state, kind, {'schema_version': 1, 'kind': kind,
                      'document': {'path': str(path), 'sha256': digest, 'bytes': len(raw)}})


def load_document(reference):
    import guided_workflow as guided
    require(type(reference) is dict and set(reference) == {'path', 'sha256', 'bytes'},
            'Invalid review evidence reference')
    path = Path(reference['path'])
    require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)),
            'Review evidence requires an absolute nonsymlink path')
    require(type(reference['bytes']) is int and 0 <= reference['bytes'] <= guided.MAX_JSON_BYTES,
            'Invalid review evidence size')
    value, digest = guided._nonsecret_json(path)
    require(path.stat().st_size == reference['bytes'] and digest == reference['sha256'],
            'Review evidence bytes changed; re-register the evidence')
    return value


def public_summary(state):
    value = records(state)
    result = {'schema_version': 1, **{key: {'status': 'unassessed' if value[key] is None else 'recorded'}
                                    for key in KINDS},
            'qualification': 'Mapping and reuse records describe supplied evidence. They do not establish native parity, human approval or deployment readiness.'}
    if value['coverage']:
        from mapping_coverage import summarize
        try:
            result['coverage'] = summarize(state)
        except (OSError, ValueError, KeyError, TypeError):
            result['coverage'] = {'status': 'unavailable', 'qualification': 'Coverage evidence is missing, changed or unsupported; re-register it.'}
    if value['reuse']:
        from reuse_coverage import summarize
        try:
            result['reuse'] = summarize(state)
        except (OSError, ValueError, KeyError, TypeError):
            result['reuse'] = {'status': 'unavailable', 'qualification': 'Reuse evidence is missing, changed or unsupported; re-register it.'}
    if value['reconciliation']:
        from workflow_reconciliation import summarize
        result['reconciliation'] = summarize(state)
    return result
