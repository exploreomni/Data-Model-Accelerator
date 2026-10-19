"""Pinned existing-model ownership and disposition; never native acceptance.

Wildcard selectors resolve only against the explicitly supplied inventory. An
evidence reference records a claim, not authenticated compatibility or approval.
"""
import copy
from fnmatch import fnmatchcase

from ae_common import hash_json, require
from engagement_stages import DIMENSIONS, SHA, fields, identifier, ids, text
from review_assurance import records, save, save_document, load_document

DISPOSITIONS = {'reuse', 'extend', 'replace', 'defer', 'undetermined', 'out_of_scope'}
REUSE_ACTIONS = {'reuse', 'extend', 'replace'}


def _rows(value, label):
    require(type(value) is list and len(value) <= 20000 and all(type(row) is dict for row in value),
            label + ' must be a bounded object list')
    return value


def _context(state):
    from mapping_coverage import read as read_coverage
    design = state.get('workflow', {}).get('design') or {}
    existing = {row['id']: row for row in design.get('existing_models', [])}
    models = {row['id']: row for row in design.get('entities', [])}
    try:
        coverage = read_coverage(state)
        requirements = coverage['requirements'] if coverage else {}
    except (OSError, ValueError, KeyError, TypeError):
        requirements = None
    return existing, models, requirements


def _linked(models, existing_id):
    return {key for key, model in models.items()
            if (model.get('reuse') or {}).get('existing_id') == existing_id}


def _bindings(existing_id, assignment, context):
    existing, models, requirements = context
    related = set(assignment['model_ids']) | _linked(models, existing_id)
    return {'existing': hash_json(existing[existing_id]) if existing_id in existing else None,
            'models': {key: hash_json(models[key]) if key in models else None for key in sorted(related)},
            'requirements': {key: hash_json(requirements[key]) if requirements is not None and key in requirements
                             else 'unavailable' for key in assignment['requirement_ids']}}


def register(state, request, run_dir):
    fields(request, {'schema_version', 'inventory', 'assignments'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported reuse schema')
    require(type(state.get('workflow')) is dict, 'Adopt stages before recording reuse evidence')
    context = _context(state)
    existing, models, requirements = context
    inventory, native_ids = {}, set()
    for row in _rows(request['inventory'], 'inventory'):
        fields(row, {'existing_id', 'namespace', 'native_id', 'snapshot_sha256'})
        key = identifier(row['existing_id'])
        text(row['namespace']); text(row['native_id'])
        require(key in existing and key not in inventory, 'Unknown or duplicate existing inventory ID')
        native = (row['namespace'], row['native_id'])
        require(native not in native_ids, 'Duplicate namespace/native identity')
        require(type(row['snapshot_sha256']) is str and SHA.fullmatch(row['snapshot_sha256'])
                and row['snapshot_sha256'] == hash_json(existing[key]), 'Existing model snapshot differs')
        native_ids.add(native)
        inventory[key] = copy.deepcopy(row)
    require(set(inventory) == set(existing), 'Inventory must include exactly all canonical existing models')
    domains = {model['domain'] for model in models.values()}
    domains.update(row['domain'] for row in (requirements or {}).values())
    assignments = {}
    for row in _rows(request['assignments'], 'assignments'):
        fields(row, {'existing_ids', 'owner_domain', 'disposition', 'model_ids', 'requirement_ids',
                     'evidence_refs', 'rationale'}, {'review_reference'})
        patterns = row['existing_ids']
        require(type(patterns) is list and 0 < len(patterns) <= 20000, 'Existing IDs require bounded selectors')
        selected = set()
        for pattern in patterns:
            text(pattern)
            matches = {key for key in inventory if fnmatchcase(key, pattern)}
            require(matches, 'Existing selector matches no pinned inventory IDs')
            selected.update(matches)
        owner = row['owner_domain']
        require(owner is None or (type(owner) is str and owner in domains), 'Unknown ownership domain')
        disposition = row['disposition']
        require(type(disposition) is str and disposition in DISPOSITIONS, 'Unknown reuse disposition')
        ids(row['model_ids'], models)
        ids(row['requirement_ids'], requirements or {})
        ids(row['evidence_refs']); text(row['rationale'])
        if 'review_reference' in row:
            text(row['review_reference'])
        if disposition == 'out_of_scope':
            text(row.get('review_reference'))
        if disposition in REUSE_ACTIONS:
            for model_id in row['model_ids']:
                model = models[model_id]
                require((model.get('reuse') or {}).get('existing_id') in selected
                        and model['disposition'] == disposition, 'Reuse assignment contradicts canonical model binding')
        for key in sorted(selected):
            linked = _linked(models, key)
            if disposition in REUSE_ACTIONS:
                require(linked and all(models[model_id]['disposition'] == disposition for model_id in linked),
                        'Reuse disposition requires matching canonical reuse models')
                affected = linked
            else:
                affected = linked | set(row['model_ids'])
            normalized = {**copy.deepcopy(row), 'existing_ids': [key], 'model_ids': sorted(affected)}
            for field in ('requirement_ids', 'evidence_refs'):
                normalized[field] = sorted(normalized[field])
            require(key not in assignments or assignments[key] == normalized,
                    'Conflicting ownership or disposition for existing model')
            assignments[key] = normalized
    for key in inventory:
        assignments.setdefault(key, {'existing_ids': [key], 'owner_domain': None, 'disposition': 'undetermined',
            'model_ids': sorted(_linked(models, key)), 'requirement_ids': [], 'evidence_refs': [],
            'rationale': 'No owner or disposition was recorded for this pinned existing model.'})
    document = {'schema_version': 1, 'kind': 'reuse', 'inventory': inventory,
                'inventory_sha256': hash_json(inventory), 'assignments': assignments,
                'assignment_requests': copy.deepcopy(request['assignments']),
                'bindings': {key: _bindings(key, row, context) for key, row in assignments.items()},
                'names': {key: existing[key]['name'] for key in inventory}}
    scope = _scope_bindings(document, context)
    save_document(state, 'reuse', document, run_dir)
    record = records(state)['reuse']
    record['scope_bindings'] = scope
    save(state, 'reuse', record)
    return summarize(state)


def read(state):
    record = records(state)['reuse']
    if record is None:
        return None
    value = load_document(record['document'])
    require(type(value) is dict and type(value.get('schema_version')) is int
            and value['schema_version'] == 1 and value.get('kind') == 'reuse', 'Unsupported reuse document')
    require(all(type(value.get(key)) is dict for key in ('inventory', 'assignments', 'bindings', 'names')),
            'Invalid reuse document')
    require(value.get('inventory_sha256') == hash_json(value['inventory'])
            and set(value['inventory']) == set(value['assignments']) == set(value['bindings']) == set(value['names']),
            'Reuse inventory or assignment binding differs')
    return value


def _scope_bindings(value, context):
    grouped = {}
    for key, row in value['assignments'].items():
        current = _bindings(key, row, context)
        for model_id in current['models']:
            grouped.setdefault(model_id, {})[key] = {'inventory': value['inventory'][key],
                'assignment': row, 'current_bindings': current}
    return {key: hash_json(rows) for key, rows in grouped.items()}


def scope_bindings(state):
    """Invalidate affected scopes on unavailable evidence; never close draft access."""
    try:
        value = read(state)
        return _scope_bindings(value, _context(state)) if value is not None else {}
    except (OSError, ValueError, KeyError, TypeError):
        record = records(state)['reuse'] or {}
        return {key: 'unavailable:' + digest for key, digest in record.get('scope_bindings', {}).items()}


def _compatibility(assignment, model_ids, models):
    if assignment['disposition'] not in REUSE_ACTIONS or not assignment['evidence_refs'] or not model_ids:
        return 'unknown'
    for key in model_ids:
        dimensions = (models.get(key, {}).get('reuse') or {}).get('dimensions', {})
        if set(dimensions) != DIMENSIONS or any(
                row.get('status') not in {'compatible', 'change_required'} or not row.get('evidence_refs')
                for row in dimensions.values()):
            return 'unknown'
    return 'evidence_recorded'


def summarize(state):
    value = read(state)
    if value is None:
        return {'status': 'unassessed'}
    context = _context(state)
    existing, models, _ = context
    counts = {'total': len(value['inventory']), 'unassigned': 0,
              'by_disposition': {key: 0 for key in sorted(DISPOSITIONS)}}
    rows, stale = [], 0
    for key, assignment in sorted(value['assignments'].items()):
        current = _bindings(key, assignment, context)
        freshness = 'current' if current == value['bindings'][key] else 'stale'
        stale += freshness == 'stale'
        counts['unassigned'] += assignment['owner_domain'] is None
        counts['by_disposition'][assignment['disposition']] += 1
        model_ids = sorted(current['models'])
        rows.append({'name': value['names'][key], 'existing_id': key,
            'owner_domain': assignment['owner_domain'], 'disposition': assignment['disposition'],
            'model_ids': model_ids, 'requirement_ids': assignment['requirement_ids'],
            'compatibility': _compatibility(assignment, model_ids, models) if freshness == 'current' else 'unknown',
            'freshness': freshness, 'rationale': assignment['rationale']})
    added = sorted(set(existing) - set(value['inventory']))
    removed = sorted(set(value['inventory']) - set(existing))
    return {'status': 'stale' if stale or added or removed else 'recorded', 'unit': 'pinned_existing_models',
            'counts': counts, 'stale': stale, 'canonical_total': len(existing),
            'uninventoried_existing_ids': added, 'removed_existing_ids': removed,
            'rows': rows[:500], 'omitted_detail_rows': max(0, len(rows) - 500),
            'native_compatibility': 'not_validated', 'review_authority': 'host_reported_not_authenticated',
            'qualification': 'Ownership and disposition describe supplied canonical inventory only. Evidence recorded is not validated compatibility. Exclusion references do not establish authenticated approval, native accuracy or deployment authority.'}
