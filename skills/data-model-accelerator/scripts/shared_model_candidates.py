"""Propose reusable models across a supplied dashboard inventory.

Contract equality is a candidate heuristic, never semantic equivalence proof.
Unknown definitions and non-additive metrics cannot become aggregate passes.
"""
import copy

from ae_common import hash_json, require
from engagement_stages import fields, identifier, ids, text

CONTEXT = ('population', 'filters', 'time', 'currency', 'history', 'security')
UNKNOWN = {'', 'unknown', 'tbd', 'unresolved'}


def _contract(value):
    fields(value, {'base_entity', 'grain', 'dimensions', 'population', 'filters',
                   'time', 'currency', 'history', 'security', 'measures', 'rule_ids'})
    text(value['base_entity'])
    for key in ('grain', 'dimensions', 'rule_ids'): ids(value[key])
    require(type(value['filters']) is list and len(value['filters']) <= 100, 'Invalid filter inventory')
    for item in value['filters']: text(item)
    for key in CONTEXT:
        if key != 'filters': text(value[key])
    require(type(value['measures']) is list and 0 < len(value['measures']) <= 200, 'Explicit measure inventory required')
    require(all(type(row) is dict for row in value['measures']), 'Measures must be objects')
    ids([row.get('id') for row in value['measures']])
    for row in value['measures']:
        fields(row, {'id', 'expression', 'aggregation', 'additivity'})
        text(row['expression'])
        require(row['aggregation'] in {'sum', 'count', 'count_distinct', 'ratio', 'window', 'min', 'max', 'other'}, 'Unsupported aggregation classification')
        require(row['additivity'] in {'additive', 'semi_additive', 'non_additive', 'unknown'}, 'Unknown additivity')
    return value


def validate(request):
    fields(request, {'schema_version', 'assets'}, {'existing_models'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported portfolio request')
    require(type(request['assets']) is list and 0 < len(request['assets']) <= 2000, 'Bounded dashboard inventory required')
    require(all(type(row) is dict for row in request['assets']), 'Assets must be objects')
    ids([row.get('id') for row in request['assets']])
    for row in request['assets']:
        fields(row, {'id', 'name', 'domain', 'model_ids', 'evidence_refs', 'contract'})
        text(row['name']); text(row['domain']); ids(row['model_ids']); ids(row['evidence_refs'], nonempty=True)
        _contract(row['contract'])
    existing = request.get('existing_models', [])
    require(type(existing) is list and len(existing) <= 2000, 'Invalid existing model inventory')
    require(all(type(row) is dict for row in existing), 'Existing models must be objects')
    ids([row.get('id') for row in existing])
    for row in existing:
        fields(row, {'id', 'name', 'evidence_refs', 'contract'})
        text(row['name']); ids(row['evidence_refs'], nonempty=True); _contract(row['contract'])
    from guided_workflow import _secrets
    _secrets(request)
    return copy.deepcopy(request)


def _known(contract):
    return (bool(contract['grain']) and contract['base_entity'].strip().lower() not in UNKNOWN
            and all(contract[key].strip().lower() not in UNKNOWN for key in CONTEXT if key != 'filters')
            and all(item.strip().lower() not in UNKNOWN for item in contract['filters'])
            and all(m['expression'].strip().lower() not in UNKNOWN for m in contract['measures']))


def _signature(contract):
    # Sort set-like declarations, but never normalize formulas or infer equivalence.
    return {key: sorted(contract[key]) if key in {'grain', 'dimensions', 'filters', 'rule_ids'} else contract[key]
            for key in ('base_entity', 'grain', *CONTEXT, 'rule_ids')}


def propose(request):
    request = validate(request)
    groups, candidates, coverage = {}, [], []
    for asset in request['assets']:
        contract = asset['contract']
        if not _known(contract):
            coverage.append({'asset_id': asset['id'], 'name': asset['name'], 'model_ids': asset['model_ids'],
                             'disposition': 'needs_decision', 'candidate_id': None,
                             'reason': 'Grain, population, time, currency, history, security or expression remains unknown.'})
            continue
        groups.setdefault(hash_json(_signature(contract)), []).append(asset)
    for signature, group in sorted(groups.items()):
        representative = group[0]['contract']
        dimensions = sorted({d for a in group for d in a['contract']['dimensions']})
        candidate_id = 'shared.' + signature[:16]
        measures = {}
        for asset in group:
            for measure in asset['contract']['measures']:
                measures.setdefault(measure['id'], []).append(measure)
        conflict = any(len({hash_json(row) for row in rows}) > 1 for rows in measures.values())
        additive = not conflict and all(row['additivity'] == 'additive' and row['aggregation'] in {'sum', 'count'}
                                       for rows in measures.values() for row in rows)
        reuse = [row['id'] for row in request.get('existing_models', [])
                 if _signature(row['contract']) == _signature(representative)
                 and set(dimensions) <= set(row['contract']['dimensions'])
                 and all(any(m == existing for existing in row['contract']['measures'])
                         for rows in measures.values() for m in rows)]
        if conflict:
            disposition, reason = 'needs_decision', 'The same measure ID has different expressions or aggregation semantics.'
        elif reuse:
            disposition, reason = 'reuse_candidate', 'An existing model has the same declared context and required measures; verify physical and behavioral compatibility.'
        elif len(group) < 2:
            disposition, reason = 'keep_separate', 'No other supplied dashboard has the same declared grain and population contract.'
        elif additive:
            disposition, reason = 'shared_aggregate_candidate', 'Shared declared grain/context and additive sum/count measures; validate every consumer before materializing.'
        else:
            disposition, reason = 'shared_detail_candidate', 'Reuse detailed facts and dimensions; distinct counts, ratios, windows or other non-additive measures remain query-time logic.'
        row = {'id': candidate_id, 'disposition': disposition, 'reason': reason,
               'asset_ids': [a['id'] for a in group], 'domains': sorted({a['domain'] for a in group}),
               'model_ids': sorted({m for a in group for m in a['model_ids']}),
               'grain': representative['grain'], 'dimensions': dimensions,
               'measure_ids': sorted(measures), 'rule_ids': representative['rule_ids'],
               'existing_model_ids': reuse, 'evidence_refs': sorted({e for a in group for e in a['evidence_refs']}),
               'required_checks': ['population', 'grain_and_fanout', 'filters_and_drilldown', 'security', 'source_target_parity']}
        candidates.append(row)
        for asset in group:
            coverage.append({'asset_id': asset['id'], 'name': asset['name'], 'model_ids': asset['model_ids'],
                             'disposition': disposition, 'candidate_id': candidate_id, 'reason': reason})
    return {'schema_version': 1, 'kind': 'shared_model_candidates', 'input_sha256': hash_json(request),
            'status': 'needs_decision' if any(r['disposition'] == 'needs_decision' for r in coverage) else 'proposed',
            'asset_count': len(request['assets']), 'covered_assets': len(coverage),
            'candidates': candidates, 'coverage': sorted(coverage, key=lambda r: r['asset_id']),
            'qualification': 'Recommendations from supplied contracts. Matching names or totals do not prove equivalence. No design approval, code execution or measured performance saving.'}


def register(state, request, run_dir):
    from migration_review import store
    from business_rules import scope_bindings, read, applies
    from engagement_stages import entity_bindings
    request = validate(request)
    known_rules = {r['id'] for r in read(state)['rules']}
    known_models = {m['id'] for m in (state['workflow'].get('design') or {}).get('entities', [])}
    for asset in request['assets']:
        require(set(asset['model_ids']) <= known_models, 'Portfolio references unknown models')
        require(set(asset['contract']['rule_ids']) <= known_rules, 'Portfolio references unknown business rules')
        for rule in read(state)['rules']:
            if rule['id'] in asset['contract']['rule_ids'] and asset['model_ids']:
                require(any(applies(rule, model) for model in state['workflow']['design']['entities']
                            if model['id'] in asset['model_ids']), 'Portfolio rule does not apply to its model scope')
    report = propose(request)
    selected = sorted({m for a in request['assets'] for m in a['model_ids']})
    store(state, 'portfolio', {'request': request, 'report': report,
                              'source': state['inputs']['source']['fingerprint'],
                              'entities': entity_bindings(state, selected) if selected else {},
                              'rules': scope_bindings(state)}, run_dir)


def summary(state, allowed_models=None):
    from migration_review import load
    from business_rules import scope_bindings
    from engagement_stages import entity_bindings
    value = load(state, 'portfolio')
    if value is None: return {'status': 'unassessed', 'candidates': [], 'coverage': []}
    report = copy.deepcopy(value['report'])
    require(report == propose(value['request']), 'Portfolio recommendations differ from their input')
    current_rules = scope_bindings(state)
    source_stale = value['source'] != state['inputs']['source']['fingerprint']
    selected = {m for a in value['request']['assets'] for m in a['model_ids']}
    known = {m['id'] for m in (state['workflow'].get('design') or {}).get('entities', [])}
    current_entities = entity_bindings(state, sorted(selected & known)) if selected & known else {}
    allowed = set(allowed_models) if allowed_models is not None else None
    for row in report['coverage']:
        row['freshness'] = 'stale' if source_stale or any(value['rules'].get(m) != current_rules.get(m)
            or value.get('entities', {}).get(m) != current_entities.get(m) for m in row['model_ids']) else 'current'
    for candidate in report['candidates']:
        candidate['freshness'] = 'stale' if any(r['freshness'] == 'stale' for r in report['coverage']
                                              if r['asset_id'] in candidate['asset_ids']) else 'current'
    if any(row['freshness'] == 'stale' for row in report['coverage']): report['status'] = 'stale'
    if allowed is not None:
        report['coverage'] = [r for r in report['coverage'] if r['model_ids'] and set(r['model_ids']) <= allowed]
        permitted_assets = {r['asset_id'] for r in report['coverage']}
        report['candidates'] = [r for r in report['candidates'] if set(r['asset_ids']) <= permitted_assets]
        report['asset_count'] = report['covered_assets'] = len(report['coverage'])
    return report
