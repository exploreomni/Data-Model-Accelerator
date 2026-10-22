"""Source occurrence to requirement to target ledger, without semantic proof.

The denominator comes from retained adapter records, including repeated field
references, never from the subset that a specialist successfully mapped.
"""
import copy
from collections import Counter

from ae_common import hash_json, require
from engagement_stages import fields, ids, identifier, text, _source_hash
from review_assurance import records, save, save_document, load_document
from source_adapters.base import occurrence_id
from source_adapters.consolidation import merge_reports

STATUSES = {'mapped', 'unresolved', 'unsupported', 'excluded_by_review'}
BASES = {'expression_analysis', 'structural_binding', 'reviewed_definition', 'unassessed'}


def inventory(reports, expected_files):
    bundle = merge_reports(reports, expected_files=expected_files)
    result = {}
    contexts, objects, edges, source_hashes = {}, {}, {}, {}
    for report in bundle['source_contracts']:
        source = report['source']
        for item in report['source_files']:
            key = (source, item['path'])
            source_hashes[key] = item['sha256']
            edges.setdefault(key, set())
        for item in report['objects']:
            objects.setdefault((source, item['id']), set()).add((source, item['evidence']['path']))
    for report in bundle['source_contracts']:
        source = report['source']
        for category in ('objects', 'expressions', 'dependencies', 'gaps'):
            for item in report[category]:
                key = (source, item['evidence']['path'])
                contexts.setdefault(key, set()).add(hash_json(item))
                # Explicit ownership/parent links can cross file boundaries.
                # Keep their expressions and filters in one evidence context.
                details = item.get('details') or {}
                owner = item.get('object_id', item.get('source_id'))
                parent = details.get('parent_id') if type(details) is dict else None
                for reference in (owner, parent):
                    if type(reference) is str:
                        for other in objects.get((source, reference), set()):
                            edges[key].add(other)
                            edges[other].add(key)
                # Resolve only exact retained object IDs, never guessed names.
                if category == 'dependencies' and type(item.get('target')) is str:
                    edges[key].update(objects.get((source, item['target']), set()))
    contexts = {key: hash_json(sorted(values)) for key, values in contexts.items()}
    closures = {}
    memberships = 0
    for key in edges:
        seen, pending = set(), [key]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(edges[current] - seen)
        memberships += len(seen)
        require(memberships <= 1000000, 'Source context graph exceeds the bounded coverage limit')
        closures[key] = sorted(seen)
    for report in bundle['source_contracts']:
        for category in ('objects', 'expressions', 'dependencies'):
            ordinals = Counter()
            for item in report[category]:
                evidence = item['evidence']
                key = (evidence['path'], evidence['locator'])
                identity = item.get('occurrence_id') or occurrence_id(report['source'], category, *key, ordinals[key])
                ordinals[key] += 1
                context = closures[(report['source'], evidence['path'])]
                row = {'id': identity, 'source': report['source'], 'category': category,
                       'path': evidence['path'], 'locator': evidence['locator'],
                       'source_sha256': evidence['sha256'], 'record_sha256': hash_json(item),
                       'context_sha256': hash_json([[source, path, contexts.get((source, path))] for source, path in context]),
                       'context_paths': [path for _, path in context],
                       'context_source_sha256': {path: source_hashes[(source, path)] for source, path in context},
                       'owner_id': item.get('object_id', item.get('source_id', item.get('id'))),
                       'name': item.get('name', item.get('target', item.get('language', identity)))}
                require(identity not in result or result[identity] == row, 'Conflicting occurrence identity')
                result[identity] = row
    return result


def _rows(value, label):
    require(type(value) is list and len(value) <= 100000 and all(type(row) is dict for row in value),
            label + ' must be a bounded list')
    return value


def _targets(state, rows):
    models = {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}
    result = {}
    ids([row.get('id') for row in _rows(rows, 'targets')])
    for row in rows:
        fields(row, {'id', 'kind', 'model_id'}, {'column', 'semantic_object'})
        require(row['kind'] in {'warehouse', 'semantic'}, 'Unknown target kind')
        require(row['model_id'] in models, 'Target references an unknown model')
        if row['kind'] == 'warehouse':
            require(row.get('column') in {c['name'] for c in models[row['model_id']]['columns']},
                    'Target column is not in the canonical model')
        else:
            text(row.get('semantic_object'))
        result[row['id']] = copy.deepcopy(row)
    return result


def _model_bindings(state, targets):
    doc = state.get('workflow', {}).get('design') or {}
    models = {e['id']: e for e in doc.get('entities', [])}
    result = {}
    for row in targets.values():
        key = row['model_id']
        if key not in result:
            result[key] = hash_json({'model': models.get(key),
                'relationships': [r for r in doc.get('relationships', []) if key in (r['from'], r['to'])]})
    return result


def register(state, request, run_dir):
    fields(request, {'schema_version', 'expected_files', 'reports', 'requirements', 'targets', 'mappings'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported coverage schema')
    bundle = merge_reports(request['reports'], expected_files=request['expected_files'])
    occurrences = inventory(request['reports'], request['expected_files'])
    for item in bundle['source_files']:
        source = item['coverage']
        require(_source_hash(state, source['path']) == source['sha256'], 'Source bytes differ from adapter evidence')
    requirements = {}
    ids([row.get('id') for row in _rows(request['requirements'], 'requirements')])
    for row in request['requirements']:
        fields(row, {'id', 'description', 'domain'})
        text(row['description']); text(row['domain'])
        requirements[row['id']] = copy.deepcopy(row)
    targets = _targets(state, request['targets'])
    mappings = {}
    for row in _rows(request['mappings'], 'mappings'):
        fields(row, {'occurrence_id', 'requirement_ids', 'target_ids', 'status', 'basis', 'rationale'}, {'review_reference'})
        key = identifier(row['occurrence_id'])
        require(key in occurrences, 'Unknown source occurrence')
        require(key not in mappings, 'Duplicate occurrence mapping')
        ids(row['requirement_ids'], requirements); ids(row['target_ids'], targets)
        require(row['status'] in STATUSES and row['basis'] in BASES, 'Unsupported mapping status or basis; name-only matching is insufficient')
        text(row['rationale'])
        if row['status'] == 'mapped':
            require(row['requirement_ids'] and row['target_ids'] and row['basis'] != 'unassessed',
                    'Mapped occurrences require requirements, targets and an analysis basis')
        if row['status'] == 'excluded_by_review':
            text(row.get('review_reference'))
        mappings[key] = copy.deepcopy(row)
    for key in occurrences:
        mappings.setdefault(key, {'occurrence_id': key, 'requirement_ids': [], 'target_ids': [],
            'status': 'unresolved', 'basis': 'unassessed', 'rationale': 'No mapping recorded for this retained occurrence.'})
    document = {'schema_version': 1, 'kind': 'coverage', 'bundle': bundle,
                'expected_files': copy.deepcopy(request['expected_files']), 'occurrences': occurrences,
                'requirements': requirements, 'targets': targets, 'mappings': mappings,
                'model_bindings': _model_bindings(state, targets)}
    save_document(state, 'coverage', document, run_dir)
    record = records(state)['coverage']
    record['scope_bindings'] = _scope_bindings(document, state)
    save(state, 'coverage', record)
    return summarize(state)


def read(state):
    record = records(state)['coverage']
    if record is None:
        return None
    value = load_document(record['document'])
    require(value.get('schema_version') == 1 and value.get('kind') == 'coverage', 'Unsupported coverage document')
    return value


def scope_bindings(state):
    """Only materially mapped models change their authoring/review bindings."""
    try:
        value = read(state)
    except (OSError, ValueError, KeyError, TypeError):
        # Unavailable evidence invalidates its prior scope without blocking the
        # user's ability to request new provisional files or unrelated work.
        record = records(state)['coverage'] or {}
        return {key: 'unavailable:' + digest for key, digest in record.get('scope_bindings', {}).items()}
    if value is None:
        return {}
    return _scope_bindings(value, state)


def _scope_bindings(value, state):
    grouped = {}
    sources = {}
    for key, row in value['mappings'].items():
        occurrence = value['occurrences'][key]
        path = occurrence['path']
        context_paths = occurrence.get('context_paths', [path])
        if row['target_ids']:
            for context_path in context_paths:
                if context_path not in sources:
                    try:
                        sources[context_path] = _source_hash(state, context_path)
                    except (OSError, ValueError):
                        sources[context_path] = 'unavailable'
        for target_id in row['target_ids']:
            target = value['targets'][target_id]
            grouped.setdefault(target['model_id'], {})[key] = {
                'occurrence': occurrence, 'current_source_sha256': sources[path], 'mapping': row,
                'requirements': [value['requirements'][r] for r in row['requirement_ids']],
                'targets': [value['targets'][t] for t in row['target_ids']]}
            if 'context_paths' in occurrence:
                grouped[target['model_id']][key]['current_context_sha256'] = {p: sources[p] for p in context_paths}
    return {key: hash_json(rows) for key, rows in grouped.items()}


def summarize(state, *, detail_limit=500):
    require(detail_limit is None or type(detail_limit) is int and detail_limit >= 0, 'Invalid coverage detail limit')
    value = read(state)
    if value is None:
        return {'status': 'unassessed'}
    current_models = _model_bindings(state, value['targets'])
    paths = {}
    for source in value['expected_files']:
        try:
            paths[source['path']] = _source_hash(state, source['path'])
        except (OSError, ValueError):
            paths[source['path']] = None
    counts = {key: 0 for key in sorted(STATUSES | {'stale'})}
    groups = {}
    details = []
    for key, mapping in value['mappings'].items():
        occurrence = value['occurrences'][key]
        target_rows = [value['targets'][t] for t in mapping['target_ids']]
        context_sources = occurrence.get('context_source_sha256', {occurrence['path']: occurrence['source_sha256']})
        stale = (any(paths.get(path) != digest for path, digest in context_sources.items()) or
                 any(current_models.get(t['model_id']) != value['model_bindings'].get(t['model_id']) for t in target_rows))
        status = 'stale' if stale else mapping['status']
        counts[status] += 1
        domains = sorted({value['requirements'][r]['domain'] for r in mapping['requirement_ids']}) or ['unassigned']
        model_ids = sorted({t['model_id'] for t in target_rows})
        for domain in domains:
            group = groups.setdefault((occurrence['path'], domain), {'asset': occurrence['path'], 'domain': domain,
                'total': 0, **{s: 0 for s in counts}, 'model_ids': set()})
            group['total'] += 1; group[status] += 1; group['model_ids'].update(model_ids)
        details.append({'id': key, 'asset': occurrence['path'], 'name': occurrence['name'],
                        'domain': ', '.join(domains), 'domain_ids': domains, 'model_ids': model_ids, 'status': status,
                        'rationale': mapping['rationale']})
    summary = value['bundle']['coverage_summary']
    return {'status': 'stale' if counts['stale'] else 'recorded', 'unit': 'retained_source_occurrences',
            'counts': {'total': len(value['occurrences']), **counts}, 'supplied_files': summary,
            'requirements': len(value['requirements']), 'targets': len(value['targets']),
            'orphan_requirements': sorted(set(value['requirements']) - {r for m in value['mappings'].values() for r in m['requirement_ids']}),
            'export_completeness': 'not_established', 'native_parity': 'not_validated',
            'groups': [{**g, 'model_ids': sorted(g['model_ids'])} for _, g in sorted(groups.items())],
            'rows': details if detail_limit is None else details[:detail_limit],
            'omitted_detail_rows': 0 if detail_limit is None else max(0, len(details) - detail_limit),
            'qualification': 'Counts cover retained adapter objects, expressions and dependency occurrences, not all native fields. Mapped means an authored association; exclusions are host-attributed review claims. Full source semantics remain in the pinned evidence.'}


def detail_rows(state, selected=None):
    """Complete current rows, optionally restricted to explicit entity scope.

    Unresolved rows assigned to selected domains remain visible without targets.
    Cross-domain rows require all declared domains and targets to fit. Unassigned
    rows with no target cannot be safely attributed to a scoped disclosure and
    are retained only in the unrestricted ledger/export. No name inference.
    """
    rows = summarize(state, detail_limit=None).get('rows', [])
    if selected is None: return rows
    selected = set(selected); ids(sorted(selected))
    models = {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}
    require(selected <= set(models), 'Selected coverage model is unknown')
    labels = {models[key].get('domain', '').casefold() for key in selected}
    for domain in (state.get('workflow', {}).get('domain_journey') or {}).get('domains', []):
        if domain['id'].casefold() in labels or domain['name'].casefold() in labels:
            labels.update((domain['id'].casefold(), domain['name'].casefold()))
    kept = []
    for row in rows:
        domains = {d.casefold() for d in row['domain_ids'] if d != 'unassigned'}
        targets = set(row['model_ids'])
        if targets <= selected and (domains and domains <= labels or not domains and targets): kept.append(row)
    return kept
