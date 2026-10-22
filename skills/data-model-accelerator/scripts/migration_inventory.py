"""Cumulative requested migration scope, independent of selected target models.

Register rows and references are supplied metadata, never mapping or approval
authority. Only explicit crosswalk IDs can reuse the existing alignment ledger.
"""
import copy
import hashlib
from pathlib import Path

from ae_common import hash_json, require
from engagement_stages import fields, identifier, ids, text
from review_assurance import load_document

KINDS = {'model', 'ownership', 'ticket', 'explore', 'dashboard'}
MAX_ROWS = 20000
CATEGORIES = ('replacement_mapping', 'upstream_only', 'missing_evidence', 'missing_target', 'explicit_exclusion')
QUALIFICATION = ('Requested scope from supplied registers only. Metadata, evidence references and exclusion '
                 'decisions are host-declared, not authenticated approval or parity. Accounted means an '
                 'explicit replacement association or exclusion decision; upstream dependencies never count '
                 'as replacements. Tables and consumers retain separate denominators.')


def object_id(source_namespace, native_id):
    return 'inventory.' + hash_json([source_namespace, native_id])


def occurrence_id(register_id, row_id):
    return 'occurrence.' + hash_json([register_id, row_id])


def _safe(value):
    from design_coverage import _safe as validate_metadata
    validate_metadata(value)


def _rows(rows, label):
    require(type(rows) is list and len(rows) <= MAX_ROWS and all(type(r) is dict for r in rows), 'Invalid bounded ' + label)
    ids([r.get('id') for r in rows])
    return rows


def _refs(values):
    require(type(values) is list and len(values) <= 256 and len(values) == len(set(values)), 'Invalid evidence references')
    for value in values: text(value)


def _validate(request):
    fields(request, {'schema_version', 'registers'}, {'exclusions'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported inventory schema')
    _safe(request)
    count = 0
    for register in _rows(request['registers'], 'registers'):
        fields(register, {'id', 'kind', 'evidence_refs', 'rows'})
        require(register['kind'] in KINDS, 'Unknown inventory register kind'); _refs(register['evidence_refs'])
        for row in _rows(register['rows'], 'register rows'):
            fields(row, {'id', 'source_namespace', 'native_id', 'domain_ids', 'evidence_refs'},
                   {'legacy_table_id', 'consumer_id', 'metadata'})
            text(row['source_namespace']); text(row['native_id']); ids(row['domain_ids']); _refs(row['evidence_refs'])
            for key in ('legacy_table_id', 'consumer_id'):
                if key in row: identifier(row[key])
            require('legacy_table_id' not in row or 'consumer_id' not in row, 'A row cannot crosswalk both a table and a consumer')
            if 'metadata' in row: require(type(row['metadata']) is dict, 'Row metadata must be an object')
            count += 1
    require(count <= MAX_ROWS, 'Combined migration occurrences exceed the bounded inventory limit')
    for row in _rows(request.get('exclusions', []), 'exclusions'):
        fields(row, {'id', 'source_namespace', 'native_id', 'domain_ids', 'reason', 'review_reference'})
        text(row['source_namespace']); text(row['native_id']); ids(row['domain_ids'])
        require(row['domain_ids'], 'Exclusion needs an explicit domain scope')
        text(row['reason']); text(row['review_reference'])


def read(state):
    ledger = state.get('workflow', {}).get('migration_inventory')
    if ledger is None: return None
    fields(ledger, {'schema_version', 'document', 'prior_scope'})
    require(ledger['schema_version'] == 1 and type(ledger['prior_scope']) is dict, 'Invalid migration inventory state')
    doc = load_document(ledger['document'])
    fields(doc, {'schema_version', 'kind', 'request', 'omitted_occurrence_ids'})
    require(doc['schema_version'] == 1 and doc['kind'] == 'migration_inventory', 'Invalid retained migration inventory')
    _validate(doc['request']); ids(doc['omitted_occurrence_ids']); _safe(doc)
    return doc


def _objects(doc):
    objects = {}
    omitted = set(doc['omitted_occurrence_ids'])
    for register in doc['request']['registers']:
        for row in register['rows']:
            key = object_id(row['source_namespace'], row['native_id'])
            entry = objects.setdefault(key, {'id': key, 'source_namespace': row['source_namespace'],
                'native_id': row['native_id'], 'domain_ids': set(), 'legacy_table_ids': set(),
                'consumer_ids': set(), 'register_ids': set(), 'occurrences': []})
            entry['domain_ids'].update(row['domain_ids'] or ['unassigned']); entry['register_ids'].add(register['id'])
            for singular, plural in (('legacy_table_id', 'legacy_table_ids'), ('consumer_id', 'consumer_ids')):
                if singular in row: entry[plural].add(row[singular])
            oid = occurrence_id(register['id'], row['id'])
            entry['occurrences'].append({'id': oid, 'register_id': register['id'], 'register_kind': register['kind'],
                'row_id': row['id'], 'evidence_refs': sorted(set(register['evidence_refs'] + row['evidence_refs'])),
                'metadata': copy.deepcopy(row.get('metadata', {})), 'omitted_from_latest_import': oid in omitted})
    for entry in objects.values():
        for key in ('domain_ids', 'legacy_table_ids', 'consumer_ids', 'register_ids'): entry[key] = sorted(entry[key])
        entry['occurrences'].sort(key=lambda x: x['id'])
    return objects


def _domain_models(state, domain):
    from legacy_alignment import _domain_models as models
    if domain == 'unassigned':
        return {m['id'] for m in (state.get('workflow', {}).get('design') or {}).get('entities', [])}
    return models(state, domain)


def register(state, request, run_dir=None):
    """Add observations; omitted rows persist and identities cannot be reassigned."""
    import guided_workflow as guided
    require(type(state.get('workflow')) is dict, 'Adopt stages before recording migration inventory')
    _validate(request); previous = read(state)
    current = copy.deepcopy(request); current.setdefault('exclusions', [])
    incoming_ids = {occurrence_id(r['id'], row['id']) for r in current['registers'] for row in r['rows']}
    if previous:
        registers = {r['id']: r for r in current['registers']}
        for old in previous['request']['registers']:
            if old['id'] not in registers:
                current['registers'].append(copy.deepcopy(old)); continue
            new = registers[old['id']]
            require(new['kind'] == old['kind'], 'Register identity cannot change kind')
            new['evidence_refs'] = sorted(set(new['evidence_refs'] + old['evidence_refs']))
            rows = {r['id']: r for r in new['rows']}
            for prior in old['rows']:
                if prior['id'] not in rows: new['rows'].append(copy.deepcopy(prior)); continue
                row = rows[prior['id']]
                require(all(row[k] == prior[k] for k in ('source_namespace', 'native_id')), 'Occurrence identity cannot be reassigned')
                row['domain_ids'] = sorted(set(row['domain_ids'] + prior['domain_ids']))
                row['evidence_refs'] = sorted(set(row['evidence_refs'] + prior['evidence_refs']))
                for key in ('legacy_table_id', 'consumer_id'):
                    if key in prior: row.setdefault(key, prior[key])
        exclusions = {r['id']: r for r in current['exclusions']}
        for old in previous['request'].get('exclusions', []):
            if old['id'] not in exclusions: current['exclusions'].append(copy.deepcopy(old))
            else: require(exclusions[old['id']] == old, 'Exclusion decision identity cannot be rewritten')
    current['registers'].sort(key=lambda r: r['id']); current['exclusions'].sort(key=lambda r: r['id'])
    for reg in current['registers']:
        reg['rows'].sort(key=lambda r: r['id']); reg['evidence_refs'].sort()
        for row in reg['rows']:
            row['domain_ids'].sort(); row['evidence_refs'].sort()
    _validate(current)
    all_ids = {occurrence_id(r['id'], row['id']) for r in current['registers'] for row in r['rows']}
    doc = {'schema_version': 1, 'kind': 'migration_inventory', 'request': current,
           'omitted_occurrence_ids': sorted(all_ids - incoming_ids)}
    objects = _objects(doc)
    for row in current['exclusions']:
        key = object_id(row['source_namespace'], row['native_id'])
        require(key in objects and set(row['domain_ids']) <= set(objects[key]['domain_ids']), 'Exclusion references unknown requested scope')
    _safe(doc)
    ledger = state['workflow'].get('migration_inventory') or {}
    if run_dir is None:
        require(ledger.get('document'), 'A run directory is required for the first inventory registration')
        run_dir = Path(ledger['document']['path']).parent.parent
    run = guided._path(run_dir); folder = run / 'migration-inventory'
    from source_roots import ensure_output
    ensure_output(state, run); ensure_output(state, folder)
    require(not folder.is_symlink(), 'Inventory directory cannot be a symlink')
    raw = guided._bytes(doc); digest = hashlib.sha256(raw).hexdigest()
    ref = {'path': str(folder / (digest + '.json')), 'sha256': digest, 'bytes': len(raw)}
    folder.mkdir(exist_ok=True)
    if Path(ref['path']).exists(): require(load_document(ref) == doc, 'Retained inventory differs')
    else: guided._atomic_write(Path(ref['path']), raw, replace=False)
    prior_scope = copy.deepcopy(ledger.get('prior_scope', {}))
    for row in objects.values():
        for domain in row['domain_ids']:
            for model in _domain_models(state, domain):
                prior_scope[model] = sorted(set(prior_scope.get(model, [])) | {domain})
    state['workflow']['migration_inventory'] = {'schema_version': 1, 'document': ref, 'prior_scope': prior_scope}
    return summarize(state)


def domain_binding(state, domain_id):
    """Raw scoped material only: never depend on the plan being authored."""
    doc = read(state)
    if doc is None: return None
    rows = [r for r in _objects(doc).values() if domain_id in r['domain_ids']]
    exclusions = [r for r in doc['request']['exclusions'] if domain_id in r['domain_ids']]
    return hash_json({'rows': rows, 'exclusions': exclusions})


def known_consumers(state, domain_id):
    doc = read(state)
    if doc is None: return {}
    return {key: {'id': key, 'label': row['native_id'], 'model_ids': []}
            for row in _objects(doc).values() if domain_id in row['domain_ids'] for key in row['consumer_ids']}


def _reconciliation(state, domain_id):
    from legacy_alignment import public_summary, reconciliation_summary
    domains = (public_summary(state) or {}).get('domains', [])
    domain = next((d for d in domains if d['domain_id'] == domain_id),
                  {'domain_id': domain_id, 'model_ids': sorted(_domain_models(state, domain_id)),
                   'baseline_status': 'not_supplied', 'mappings': []})
    lineage = None; consumers = None; current = False
    plans = state.get('workflow', {}).get('migration_planning') or {}
    if domain_id in plans.get('domains', {}):
        from migration_planning import _load, _binding
        try:
            plan = _load(state, domain_id)
            if plan:
                current = plan['binding'] == _binding(state, domain_id, plan['request'])
                lineage = copy.deepcopy(plan['request']['source_lineage'])
                consumers = copy.deepcopy(plan['request']['consumers'])
                for row in lineage['edges'] + consumers:
                    row['evidence_labels'] = [e['label'] for e in row['evidence_refs']]
        except (OSError, ValueError, KeyError, TypeError): pass
    return reconciliation_summary(domain, source_lineage=lineage, consumers=consumers,
                                  known_consumers=list(known_consumers(state, domain_id).values()), evidence_current=current)


def _counts(rows):
    return {'requested': len(rows), 'accounted': sum(r['accounted'] for r in rows),
            'unresolved': sum(not r['accounted'] for r in rows),
            **{key: sum(r['classification'] == key for r in rows) for key in CATEGORIES}}


def summarize(state, selected=None):
    if state.get('workflow', {}).get('migration_inventory') is None: return None
    try:
        doc = read(state); objects = _objects(doc)
        domain_ids = sorted({d for row in objects.values() for d in row['domain_ids']})
        selected = None if selected is None else set(selected)
        if selected is not None:
            domain_ids = [d for d in domain_ids if _domain_models(state, d) & selected or d == 'unassigned' and selected]
        domains = []
        for domain_id in domain_ids:
            reconciliation = _reconciliation(state, domain_id)
            tables = {r['table_id']: r for r in reconciliation['items'] if r['kind'] == 'table'}
            consumers = {r['id']: r for r in reconciliation['consumers']}
            rows = []
            for obj in objects.values():
                if domain_id not in obj['domain_ids']: continue
                matches = [tables[key] for key in obj['legacy_table_ids'] if key in tables]
                matches += [consumers[key] for key in obj['consumer_ids'] if key in consumers]
                conflicts = len(obj['legacy_table_ids']) + len(obj['consumer_ids']) > 1
                evidence = matches[0] if len(matches) == 1 and not conflicts else {}
                classification = evidence.get('classification', 'missing_evidence')
                requirements = list(evidence.get('requirements', []))
                if not evidence: requirements.append('resolve_crosswalk_conflict' if conflicts else 'supply_explicit_evidence_crosswalk')
                exclusions = [e for e in doc['request']['exclusions'] if domain_id in e['domain_ids']
                              and object_id(e['source_namespace'], e['native_id']) == obj['id']]
                if exclusions and classification == 'replacement_mapping':
                    classification = 'missing_evidence'; requirements.append('resolve_conflicting_dispositions')
                elif exclusions:
                    classification = 'explicit_exclusion'; requirements = []
                accounted = classification == 'replacement_mapping' or (classification == 'explicit_exclusion' and
                    (bool(exclusions) or evidence.get('review_statuses') == ['accepted']))
                # Public projection omits arbitrary metadata and reference contents.
                occurrences = [{k: v for k, v in o.items() if k not in {'metadata', 'evidence_refs'}} |
                               {'evidence_reference_count': len(o['evidence_refs'])} for o in obj['occurrences']]
                rows.append({k: copy.deepcopy(v) for k, v in obj.items() if k != 'occurrences'} |
                    {'kind': 'consumer' if obj['consumer_ids'] else 'table', 'classification': classification,
                     'accounted': accounted, 'model_ids': sorted(evidence.get('model_ids', [])),
                     'requirements': sorted(set(requirements)), 'exclusion_ids': [e['id'] for e in exclusions],
                     'occurrences': occurrences})
            rows.sort(key=lambda r: r['id'])
            disclosed = rows if selected is None else [r for r in rows if
                set(r['model_ids']) <= selected and 'unassigned' not in r['domain_ids']
                and set(r['domain_ids']) <= set(domain_ids)]
            domain_models = _domain_models(state, domain_id)
            domains.append({'domain_id': domain_id, 'model_ids': sorted(domain_models if selected is None else domain_models & selected),
                            'counts': _counts(rows), 'by_kind': {k: _counts([r for r in rows if r['kind'] == k])
                                                              for k in ('table', 'consumer')}, 'rows': disclosed,
                            'omitted_detail_rows': len(rows) - len(disclosed)})
        return {'schema_version': 1, 'status': 'unassessed' if not objects else
                'partial' if any(d['counts']['unresolved'] for d in domains) else 'accounted',
                'inventory_sha256': state['workflow']['migration_inventory']['document']['sha256'],
                'domains': domains, 'qualification': QUALIFICATION}
    except (OSError, ValueError, KeyError, TypeError):
        return {'schema_version': 1, 'status': 'unavailable', 'domains': [], 'qualification': QUALIFICATION}


def scope_bindings(state):
    ledger = state.get('workflow', {}).get('migration_inventory')
    if ledger is None: return {}
    try:
        doc = read(state); domains = {d for r in _objects(doc).values() for d in r['domain_ids']}
        associations = copy.deepcopy(ledger['prior_scope'])
        for domain in domains:
            for model in _domain_models(state, domain): associations[model] = sorted(set(associations.get(model, [])) | {domain})
        bindings = {d: domain_binding(state, d) for d in domains}
        return {model: hash_json({d: bindings.get(d) for d in ds}) for model, ds in associations.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {model: hash_json({'unavailable': True, 'domains': ds}) for model, ds in ledger.get('prior_scope', {}).items()}


def gaps(state, selected):
    summary = summarize(state, selected)
    if summary is None: return []
    if summary['status'] == 'unavailable': return ['Migration inventory evidence is unavailable; re-register the retained scope.']
    if summary['status'] == 'unassessed': return ['Migration inventory has no supplied requested scope.']
    return ['Migration inventory: ' + d['domain_id'] + ' has ' + str(d['counts']['unresolved']) +
            ' requested items without replacement evidence or an explicit exclusion decision.'
            for d in summary['domains'] if d['counts']['unresolved']]
