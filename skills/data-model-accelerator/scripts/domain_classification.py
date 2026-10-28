#!/usr/bin/env python3
"""Optional source-qualified domain proposals; never scope or approval authority.

Imports preserve supplied IDs. They do not infer table names, select a domain,
change accepted naming, edit a design or advance an engagement stage.
"""
import argparse
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat

from ae_common import _path, hash_json, load_json, require

MAX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_HISTORY = 20
MAX_HISTORY_BYTES = 8 * 1024 * 1024
MAX_PACKET_BYTES = 16384
MAX_PACKET_ENTRIES = 64
SHA = re.compile(r'[0-9a-f]{64}')
FIELDS = {'schema_version', 'kind', 'version', 'source_reference', 'source_sha256', 'entries'}
ENTRY_FIELDS = {'id', 'table_id', 'domain_id', 'confidence', 'rationale', 'required_columns', 'shared_domain_ids', 'evidence_refs'}
QUALIFICATION = ('Imported metadata proposals only. Source IDs are preserved; confidence and rationale are supplied evidence, '
                 'not authenticated review. Accepted domains, scope, names, models and deployment authority remain unchanged.')


def _text(value, label, limit=1024):
    require(type(value) is str and bool(value.strip()) and len(value.encode('utf-8')) <= limit,
            'Invalid classification ' + label)
    return value  # IDs must not be lowercased, stripped, split or guessed.


def _sha(value):
    require(type(value) is str and SHA.fullmatch(value) is not None, 'Invalid classification SHA-256')
    return value


def _strings(value, label, limit=256):
    require(type(value) is list and len(value) <= limit, 'Invalid classification ' + label)
    for item in value: _text(item, label)
    require(len(set(value)) == len(value), 'Duplicate classification ' + label)
    return list(value)


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def normalize(doc):
    """Validate and copy a schema-1 metadata proposal; no source lookup occurs."""
    require(type(doc) is dict and FIELDS <= set(doc) <= FIELDS | {'import_sha256'}, 'Invalid domain classification fields')
    require(type(doc['schema_version']) is int and doc['schema_version'] == 1 and doc['kind'] == 'domain_classification',
            'Unsupported domain classification schema')
    _text(doc['version'], 'version', 128); _text(doc['source_reference'], 'source reference', 4096); _sha(doc['source_sha256'])
    if 'import_sha256' in doc: _sha(doc['import_sha256'])
    require(type(doc['entries']) is list and len(doc['entries']) <= MAX_ENTRIES, 'Classification entry bound exceeded')
    seen = set()
    for row in doc['entries']:
        require(type(row) is dict and set(row) == ENTRY_FIELDS, 'Invalid classification entry fields')
        for key in ('id', 'table_id', 'domain_id'): _text(row[key], key)
        require(row['id'] not in seen, 'Duplicate classification entry ID'); seen.add(row['id'])
        require(type(row['confidence']) in (int, float) and 0 <= row['confidence'] <= 1 and math.isfinite(row['confidence']),
                'Classification confidence must be a number from zero to one')
        _text(row['rationale'], 'rationale', 4000)
        _strings(row['required_columns'], 'required columns')
        _strings(row['shared_domain_ids'], 'shared domains', 200)
        _strings(row['evidence_refs'], 'evidence references', 32)
        require(row['domain_id'] not in row['shared_domain_ids'], 'Own domain must not also be a shared domain')
    require(len(_bytes(doc)) <= MAX_BYTES, 'Classification byte bound exceeded')
    return copy.deepcopy(doc)


def from_csv(path, source_reference, source_sha256, version='1'):
    """Import canonical entry columns; list-valued cells must be JSON arrays.

    source_sha256 is the existing engagement source fingerprint, not a guessed
    warehouse identity. import_sha256 independently pins the exact CSV bytes.
    """
    path = _path(path)
    require(stat.S_ISREG(path.stat().st_mode) and path.stat().st_size <= MAX_BYTES, 'Classification CSV must be a bounded regular file')
    with path.open('rb') as stream: body = stream.read(MAX_BYTES + 1)
    require(len(body) <= MAX_BYTES, 'Classification CSV byte bound exceeded')
    reader = csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
    require(reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames))
            and set(reader.fieldnames) == ENTRY_FIELDS, 'CSV requires canonical classification columns')
    entries = []
    for row in reader:
        require(len(entries) < MAX_ENTRIES and None not in row and all(v is not None for v in row.values()), 'Invalid or oversized classification CSV row')
        try:
            row['confidence'] = float(row['confidence'])
            for field in ('required_columns', 'shared_domain_ids', 'evidence_refs'):
                row[field] = json.loads(row[field]) if row[field].strip() else []
        except (ValueError, TypeError): raise ValueError('Invalid confidence or JSON list in classification CSV') from None
        entries.append(row)
    return normalize({'schema_version': 1, 'kind': 'domain_classification', 'version': version,
                      'source_reference': source_reference, 'source_sha256': source_sha256,
                      'import_sha256': hashlib.sha256(body).hexdigest(), 'entries': entries})


def _source(state):
    value = state.get('inputs', {}).get('source', {}).get('fingerprint', {}).get('value')
    return _sha(value)


def _registered(state):
    record = state.get('workflow', {}).get('domain_classification')
    if record is None: return None
    require(type(record) is dict and set(record) == {'schema_version', 'kind', 'current', 'document_sha256', 'history'}
            and type(record['schema_version']) is int and record['schema_version'] == 1
            and record['kind'] == 'domain_classification_register', 'Invalid classification register')
    doc = normalize(record['current'])
    require(record['document_sha256'] == hash_json(doc), 'Classification register content changed')
    require(type(record['history']) is list and len(record['history']) <= MAX_HISTORY, 'Classification history bound exceeded')
    versions = {doc['version']}
    for previous in record['history']:
        require(type(previous) is dict and set(previous) == {'document', 'document_sha256'}, 'Invalid classification history')
        old = normalize(previous['document'])
        require(previous['document_sha256'] == hash_json(old) and old['version'] not in versions, 'Classification history content changed')
        versions.add(old['version'])
    require(len(_bytes(record)) <= MAX_HISTORY_BYTES, 'Classification register byte bound exceeded')
    return record


def register(state, doc):
    """Write only workflow.domain_classification, bound to existing source bytes."""
    doc = normalize(doc); current_source = _source(state)
    require(doc['source_sha256'] == current_source, 'Classification source fingerprint differs; reimport current source evidence')
    require(type(state.get('workflow')) is dict, 'Existing workflow required')
    old = _registered(state); digest = hash_json(doc)
    if old:
        for prior in [{'document': old['current'], 'document_sha256': old['document_sha256']}, *old['history']]:
            if prior['document']['version'] == doc['version']:
                require(prior['document_sha256'] == digest, 'Classification version content changed; supply a new version')
                require(old['document_sha256'] == digest, 'Historical classification version cannot replace the current version')
                return summary(state)
    history = [] if old is None else [*copy.deepcopy(old['history']), {'document': copy.deepcopy(old['current']), 'document_sha256': old['document_sha256']}]
    require(len(history) <= MAX_HISTORY, 'Classification history is full; retain it and start a new engagement register')
    record = {'schema_version': 1, 'kind': 'domain_classification_register', 'current': doc,
              'document_sha256': digest, 'history': history}
    require(len(_bytes(record)) <= MAX_HISTORY_BYTES, 'Classification register byte bound exceeded')
    state['workflow']['domain_classification'] = record
    return summary(state)


def _selected(doc, domain_id):
    return [row for row in doc['entries'] if domain_id is None or row['domain_id'] == domain_id or domain_id in row['shared_domain_ids']]


def _scope_ids(state, domain_id):
    """Use explicit workflow identities; metadata proposals never expand scope."""
    workflow = state.get('workflow', {})
    domains = (workflow.get('domain_journey') or {}).get('domains', [])
    selected = [domain for domain in domains if domain.get('id') == domain_id]
    require(len(selected) <= 1, 'Ambiguous selected domain identity')
    labels = {domain_id}
    scope = {domain_id}  # A pre-design architect brief can target the domain.
    if selected:
        labels.add(_text(selected[0]['name'], 'domain name'))
        scope.update(_strings(selected[0].get('shared_dependency_ids', []), 'shared dependency IDs', MAX_ENTRIES))
    for entity in (workflow.get('design') or {}).get('entities', []):
        if entity.get('domain') in labels:
            scope.add(_text(entity.get('id'), 'entity ID'))
    require(len(scope) <= MAX_ENTRIES, 'Classification scope bound exceeded; select a smaller domain')
    return sorted(scope)


def summary(state, domain_id=None):
    """Small counts and freshness only; no catalog rows, rationale or names."""
    if domain_id is not None: _text(domain_id, 'selected domain')
    record = _registered(state)
    if record is None:
        return {'status': 'not_imported', 'optional': True, 'entry_count': 0, 'shared_entry_count': 0,
                'document_sha256': None, 'version': None, 'proposal_only': True}
    doc = record['current']; rows = _selected(doc, domain_id)
    return {'status': 'current' if doc['source_sha256'] == _source(state) else 'stale', 'optional': True,
            'entry_count': len(rows), 'shared_entry_count': sum(row['domain_id'] != domain_id for row in rows) if domain_id else 0,
            'proposed_domain_count': len({row['domain_id'] for row in rows}),
            'document_sha256': record['document_sha256'], 'source_sha256': doc['source_sha256'],
            'version': doc['version'], 'history_count': len(record['history']), 'proposal_only': True}


def packet(state, domain_id):
    """Bounded own-domain and explicitly shared proposals, never the full catalog.

    Oversized scope is explicitly partial. Stale evidence emits no row proposals
    until reimport; neither absence nor stale metadata changes stage authority.
    """
    _text(domain_id, 'selected domain')
    record = _registered(state)
    if record is None: return None
    doc = record['current']; candidates = _selected(doc, domain_id)
    current_source = _source(state); status = 'current' if doc['source_sha256'] == current_source else 'stale'
    result = {'schema_version': 1, 'kind': 'domain_classification_context', 'domain_id': domain_id,
              'scope_ids': _scope_ids(state, domain_id),
              'version': doc['version'], 'source_reference': doc['source_reference'], 'source_sha256': doc['source_sha256'],
              'current_source_sha256': current_source, 'document_sha256': record['document_sha256'],
              'status': status, 'entries': [], 'scope_complete': status == 'current', 'omitted_entry_count': len(candidates),
              'proposal_only': True, 'qualification': QUALIFICATION}
    require(len(_bytes(result)) + 128 <= MAX_PACKET_BYTES, 'Classification identity scope exceeds packet bound; select a smaller domain')
    for row in candidates if status == 'current' else []:
        proposed = {**result, 'entries': [*result['entries'], row]}
        # Reserve space for the SHA pin and count/status changes.
        if len(result['entries']) >= MAX_PACKET_ENTRIES or len(_bytes(proposed)) + 128 > MAX_PACKET_BYTES: break
        result['entries'].append(copy.deepcopy(row))
    result['omitted_entry_count'] = len(candidates) - len(result['entries'])
    result['scope_complete'] = status == 'current' and result['omitted_entry_count'] == 0
    result['sha256'] = hash_json(result)
    return result


def validate_packet(request):
    """Validate bounded proposal evidence and its request binding, not approval."""
    body = request.get('domain_classification'); pin = request.get('bindings', {}).get('domain_classification')
    if body is None:
        require(pin is None, 'Classification pin requires its packet'); return None
    expected = {'schema_version', 'kind', 'domain_id', 'scope_ids', 'version', 'source_reference', 'source_sha256', 'current_source_sha256',
                'document_sha256', 'status', 'entries', 'scope_complete', 'omitted_entry_count', 'proposal_only', 'qualification', 'sha256'}
    require(type(body) is dict and set(body) == expected and type(body['schema_version']) is int and body['schema_version'] == 1
            and body['kind'] == 'domain_classification_context', 'Invalid classification packet')
    _text(body['domain_id'], 'selected domain'); _sha(body['current_source_sha256']); _sha(body['document_sha256'])
    _strings(body['scope_ids'], 'scope IDs', MAX_ENTRIES)
    require(body['domain_id'] in body['scope_ids'], 'Classification packet must include its domain scope')
    if 'brief' in request:
        require(type(request['brief']) is dict, 'Invalid classification request brief')
        requested = _strings(request['brief'].get('scope_ids'), 'requested scope IDs', MAX_ENTRIES)
        require(bool(requested) and set(requested) <= set(body['scope_ids']), 'Classification evidence exceeds the specialist task scope')
    normalize({key: body[key] for key in ('schema_version', 'version', 'source_reference', 'source_sha256', 'entries')} |
              {'kind': 'domain_classification'})
    require(len(body['entries']) <= MAX_PACKET_ENTRIES and len(_bytes(body)) <= MAX_PACKET_BYTES, 'Classification packet bound exceeded')
    require(body['status'] in ('current', 'stale') and body['proposal_only'] is True and body['qualification'] == QUALIFICATION,
            'Classification packet cannot claim scope or approval authority')
    require((body['status'] == 'current') == (body['source_sha256'] == body['current_source_sha256']), 'Classification packet freshness mismatch')
    require(body['status'] != 'stale' or not body['entries'], 'Stale classification packet cannot supply current proposals')
    require(type(body['omitted_entry_count']) is int and 0 <= body['omitted_entry_count'] <= MAX_ENTRIES
            and type(body['scope_complete']) is bool
            and body['scope_complete'] == (body['status'] == 'current' and body['omitted_entry_count'] == 0), 'Invalid classification scope coverage')
    require(all(row['domain_id'] == body['domain_id'] or body['domain_id'] in row['shared_domain_ids'] for row in body['entries']),
            'Classification packet includes unrelated domains')
    require(pin == body['sha256'] == hash_json({k: v for k, v in body.items() if k != 'sha256'}), 'Classification packet pin mismatch')
    return copy.deepcopy(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--csv'); source.add_argument('--json')
    parser.add_argument('--source-reference'); parser.add_argument('--source-sha256'); parser.add_argument('--version', default='1')
    parser.add_argument('--output', required=True, help='New JSON file; existing files are never overwritten')
    args = parser.parse_args(argv)
    doc = from_csv(args.csv, args.source_reference, args.source_sha256, args.version) if args.csv else normalize(load_json(args.json, max_bytes=MAX_BYTES))
    output = _path(args.output, must_exist=False)
    require(output.parent.is_dir(), 'Classification output parent must exist')
    with output.open('x', encoding='utf-8') as stream: stream.write(json.dumps(doc, indent=2, ensure_ascii=True, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__': raise SystemExit(main())
