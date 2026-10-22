"""Scoped domain reconciliation in the guided workflow; no automatic approval."""
import copy
import re

from ae_common import hash_json, require
from engagement_stages import fields, ids, text, _source_hash, _pointer
from design_consistency import assess_design, reconcile_proposals
from review_assurance import records, save, save_document, load_document

DIMENSIONS = {'currency', 'time', 'population', 'security', 'history', 'grain', 'keys'}


def _scope_index(designs):
    """Index diagnostic ownership once, retaining original and merged positions."""
    def identity(collection, row):
        keys = ('from', 'to', 'kind', 'role') if collection == 'relationships' else ('id',)
        return hash_json([row.get(key) for key in keys])

    index = {'merged': {}, 'claims': {}, 'names': {}, 'all_ids': []}
    all_ids = set()
    for collection in ('entities', 'decisions', 'relationships'):
        merged, known, claims = [], set(), {}
        for position, doc in enumerate(designs):
            for row in doc.get(collection, []):
                key = identity(collection, row)
                claims.setdefault(key, []).append(row)
                if position == 0 or key not in known:
                    merged.append(row)
                known.add(key)
                if collection == 'entities':
                    all_ids.add(row['id'])
                    name = hash_json([row.get('name'), row.get('layer')])
                    index['names'].setdefault(name, set()).add(row['id'])
        index['merged'][collection] = merged
        index['claims'][collection] = claims
    index['all_ids'] = sorted(all_ids)
    index['identity'] = identity
    return index


def _scope(finding, designs, index=None):
    index = index if index is not None else _scope_index(designs)
    match = re.match(r'^/(entities|decisions|relationships)/(\d+)(?:/|$)', finding.get('path', ''))
    if match:
        collection = match[1]
        proposal_index = finding.get('proposal_index')
        if type(proposal_index) is int and 0 <= proposal_index < len(designs):
            # Keep malformed duplicate rows at their original diagnostic index.
            values = designs[proposal_index].get(collection, [])
        else:
            values = index['merged'][collection]
        if int(match[2]) < len(values):
            row = values[int(match[2])]
            if collection == 'entities':
                if finding.get('code') == 'duplicate_model_name':
                    return sorted(index['names'][hash_json([row.get('name'), row.get('layer')])])
                return [row['id']]
            claims = index['claims'][collection][index['identity'](collection, row)]
            return sorted({model for claim in claims for model in
                           (claim['model_ids'] if collection == 'decisions' else [claim['from'], claim['to']])})
    return list(index['all_ids'])


def _checks(designs):
    result = reconcile_proposals(designs)
    scope_index = _scope_index(designs)
    for kind in ('findings', 'unknowns'):
        for row in result[kind]:
            row['model_ids'] = _scope(row, designs, scope_index)
    return result


def _inputs(state, designs):
    import guided_workflow as guided
    catalogue = state['inputs'].get('catalogue')
    data = None
    if catalogue and catalogue.get('available'):
        try:
            data = guided._nonsecret_json(catalogue['path'])[0]
        except (ValueError, OSError):
            pass
    files, result = {}, {}
    for design in designs:
        for model in design['entities']:
            for path in model['source_paths']:
                if path not in files:
                    try:
                        files[path] = _source_hash(state, path)
                    except (ValueError, OSError):
                        files[path] = 'unavailable'
            binding = {'source': {p: files[p] for p in model['source_paths']} if model['source_paths']
                       else state['inputs']['source']['fingerprint'],
                       'catalogue': {p: _pointer(data, p) for p in model['catalogue_pointers']}
                       if model['catalogue_pointers'] and data is not None else catalogue}
            result.setdefault(model['id'], set()).add(hash_json(binding))
    return {key: hash_json(sorted(values)) for key, values in result.items()}


def _shared_rules(proposals):
    grouped, findings, unknowns = {}, [], []
    for proposal in proposals:
        models = {m['id'] for m in proposal['design']['entities']}
        require(type(proposal['shared_rules']) is list and len(proposal['shared_rules']) <= 20000, 'Invalid shared rules')
        ids([row.get('id') for row in proposal['shared_rules']])
        for row in proposal['shared_rules']:
            fields(row, {'id', 'dimension', 'value', 'model_ids', 'evidence_refs'})
            require(row['dimension'] in DIMENSIONS, 'Unknown shared-rule dimension')
            text(row['value']); ids(row['model_ids'], models, True); ids(row['evidence_refs'])
            grouped.setdefault(row['id'], []).append(copy.deepcopy(row))
    for key, rows in grouped.items():
        scope = sorted({m for row in rows for m in row['model_ids']})
        dimensions_differ = len({row['dimension'] for row in rows}) > 1
        unknown = not dimensions_differ and any(row['value'].strip().lower() in {'unknown', 'tbd', 'unresolved'} for row in rows)
        if unknown or any((row['dimension'], row['value']) != (rows[0]['dimension'], rows[0]['value']) for row in rows):
            item = {'code': 'shared_rule_unknown' if unknown else 'shared_rule_conflict', 'model_ids': scope,
                    'message': 'Shared rule ' + key + (' remains unknown.' if unknown else ' has contradictory assertions; no winner selected.')}
            (unknowns if unknown else findings).append(item)
    return grouped, findings, unknowns


def register(state, request, run_dir):
    import engagement_stages as stages
    fields(request, {'schema_version', 'proposals'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported reconciliation schema')
    proposals = request['proposals']
    require(type(proposals) is list and 0 < len(proposals) <= 100, 'Provide one to 100 domain proposals')
    ids([p.get('id') for p in proposals])
    for proposal in proposals:
        fields(proposal, {'id', 'design', 'shared_rules'})
        doc = proposal['design']
        fields(doc, {'schema_version', 'id', 'revision', 'entities', 'relationships', 'assets', 'decisions', 'existing_models'})
        require(type(doc['entities']) is list and doc['entities'] and all(type(e) is dict for e in doc['entities']),
                'Proposals require an entity inventory')
        for entity in doc['entities']:
            require(type(entity.get('source_paths')) is list and type(entity.get('catalogue_pointers')) is list,
                    'Proposal entities require explicit input slices')
    # The reconciler allows cross-domain endpoints to resolve in the union.
    designs = [p['design'] for p in proposals]
    result = _checks(designs)
    rules, conflicts, unknowns = _shared_rules(proposals)
    result['findings'].extend(conflicts); result['unknowns'].extend(unknowns)
    result['status'] = 'conflicts' if result['findings'] else 'consistent'
    merged = result.pop('design') if not result['findings'] else None
    result.pop('design', None)
    old = state['workflow']['design']
    if merged is not None:
        merged = stages.validate_design(merged)
        require(not old or (merged['id'] == old['id'] and merged['revision'] > old['revision']),
                'Keep design identity and advance its revision')
    document = {'schema_version': 1, 'kind': 'reconciliation', 'proposals': copy.deepcopy(proposals),
                'rules': rules, 'result': result, 'input_bindings': _inputs(state, designs),
                'canonical': merged}
    save_document(state, 'reconciliation', document, run_dir)
    record = records(state)['reconciliation']
    record.update(mode='proposals', model_ids=sorted(document['input_bindings']))
    save(state, 'reconciliation', record)
    if merged is not None:
        stages.import_design(state, merged)
    else:
        refresh(state)
    return summarize(state)


def on_import(state):
    record = records(state)['reconciliation']
    if record is None or record.get('mode') != 'proposals':
        save(state, 'reconciliation', {'schema_version': 1, 'kind': 'reconciliation', 'mode': 'canonical'})
    refresh(state)


def _evaluate(state):
    record = records(state)['reconciliation']
    if record is None:
        return {'status': 'unassessed', 'findings': [], 'unknowns': []}
    doc = state.get('workflow', {}).get('design')
    canonical = assess_design(doc) if doc else {'findings': [], 'unknowns': []}
    scope_index = _scope_index([doc]) if doc else _scope_index([])
    findings = [{**f, 'model_ids': _scope(f, [doc], scope_index)} for f in canonical['findings']]
    unknowns = [{**f, 'model_ids': _scope(f, [doc], scope_index)} for f in canonical['unknowns']]
    stale, rules, proposal_hashes, assertions = [], {}, [], {}
    if record.get('mode') == 'proposals':
        try:
            value = load_document(record['document'])
            designs = [p['design'] for p in value['proposals']]
            current = _inputs(state, designs)
            for proposal in value['proposals']:
                for entity in proposal['design']['entities']:
                    assertions.setdefault(entity['id'], []).append({'proposal_id': proposal['id'],
                        'entity_sha256': hash_json(entity), 'current_inputs': current.get(entity['id'])})
            stale = sorted(key for key, digest in value['input_bindings'].items() if current.get(key) != digest)
            findings.extend(value['result']['findings']); unknowns.extend(value['result']['unknowns'])
            rules = value['rules']
            proposal_hashes = value['result']['proposal_sha256']
            if value['canonical'] and doc:
                expected = {e['id']: e for e in value['canonical']['entities']}
                actual = {e['id']: e for e in doc['entities']}
                stale = sorted(set(stale) | {key for key in expected if actual.get(key) != expected[key]})
                for collection in ('relationships', 'decisions', 'existing_models'):
                    def identity(row):
                        return row.get('id', hash_json([row.get(k) for k in ('from', 'to', 'kind', 'role')]))
                    previous = {identity(row): row for row in value['canonical'][collection]}
                    current_rows = {identity(row): row for row in doc[collection]}
                    for key in set(previous) | set(current_rows):
                        if previous.get(key) == current_rows.get(key):
                            continue
                        changed = [row for row in (previous.get(key), current_rows.get(key)) if row]
                        if collection == 'relationships':
                            affected = {r[side] for r in changed for side in ('from', 'to')}
                        elif collection == 'decisions':
                            affected = {m for r in changed for m in r['model_ids']}
                        else:
                            affected = {m['id'] for m in [*expected.values(), *actual.values()]
                                        if (m.get('reuse') or {}).get('existing_id') == key}
                        stale = sorted(set(stale) | affected)
        except (OSError, ValueError, KeyError, TypeError):
            stale = record.get('model_ids', [])
            findings.append({'code': 'reconciliation_unavailable', 'model_ids': stale,
                             'message': 'Proposal evidence is missing or changed; re-register the affected proposals.'})
    if stale:
        findings.append({'code': 'proposal_inputs_stale', 'model_ids': stale,
                         'message': 'Proposal inputs or canonical entities changed; reconcile the affected proposals again.'})
    return {'status': 'stale' if stale else 'conflicts' if findings else 'consistent',
            'findings': findings, 'unknowns': unknowns, 'rules': rules, 'assertions': assertions,
            'proposal_sha256': proposal_hashes, 'canonical_sha256': doc.get('sha256') if doc else None,
            'qualification': 'Structural and declared shared-rule agreement only. Unknown meanings remain unknown. No native validation or approval is inferred.'}


def refresh(state):
    record = records(state)['reconciliation']
    if record is not None:
        record['assessment'] = _evaluate(state)
        save(state, 'reconciliation', record)


def summarize(state):
    result = _evaluate(state)
    return {k: v for k, v in result.items() if k not in {'rules', 'assertions'}}


def scope_bindings(state):
    result = _evaluate(state)
    models = {e['id']: hash_json(e) for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}
    affected = {m for finding in result['findings'] for m in finding['model_ids']}
    grouped = {key: copy.deepcopy(rows) for key, rows in result.get('assertions', {}).items()
               if key in affected or any(row['entity_sha256'] != models.get(key) for row in rows)}
    for rows in result.get('rules', {}).values():
        for row in rows:
            for key in row['model_ids']:
                grouped.setdefault(key, []).append(row)
    for finding in result['findings']:
        for key in finding['model_ids']:
            grouped.setdefault(key, []).append(finding)
    return {key: hash_json(rows) for key, rows in grouped.items()}


def gaps(state, selected):
    result = _evaluate(state)
    rows = result['findings'] + [r for r in result['unknowns'] if r.get('code') == 'shared_rule_unknown']
    return [row['message'] for row in rows if set(row['model_ids']) & set(selected)]
