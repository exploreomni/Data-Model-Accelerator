"""Compare independently frozen source observations with warehouse and Omni.

The comparator performs no queries and emits no row values. Imported captures
establish local consistency only; a trusted observer must authenticate execution.
"""
import argparse
from decimal import Decimal
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ae_common import hash_json, load_json, require, _json_bytes
from delivery_assurance import SCOPES, validate_bindings

SHA = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,100}\Z')
TYPES = {'number', 'string', 'boolean', 'date'}
CONTEXT = {'snapshot_sha256', 'timezone', 'parameters_sha256', 'persona_sha256'}
BASE_KEYS = {'id','kind','subject_kind','subject_id','scenario','context'}
DATA_KEYS = {'queries','columns','grain','ordered','allow_null_grain','tolerances','expected_metrics','truncated'}
INVARIANTS = {'duplicate_keys','orphan_keys','tenant_violations','join_input_rows','join_output_rows'}


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _ids(value):
    return type(value) is list and all(type(x) is str and ID.fullmatch(x) for x in value) and len(value) == len(set(value))


def _context(value):
    require(type(value) is dict and set(value) == CONTEXT, 'Complete comparison context required')
    require(all(type(value[k]) is str and SHA.fullmatch(value[k]) for k in CONTEXT - {'timezone'}),
            'Snapshot, parameters and persona hashes required')
    try:
        require(type(value['timezone']) is str, 'Explicit timezone required')
        ZoneInfo(value['timezone'])
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Supported explicit timezone required') from None


def validate_plan(plan):
    require(type(plan) is dict and type(plan.get('schema_version')) is int and plan['schema_version'] == 1
            and plan.get('kind') == 'migration_parity_plan', 'Versioned parity plan required')
    require(set(plan) == {'schema_version','kind','migration_scope','bindings','baseline_sha256','inventory',
                          'scenario_requirements','cases','review'}, 'Unknown parity plan fields')
    validate_bindings(plan['bindings'])
    require(plan['migration_scope'] in SCOPES and type(plan['baseline_sha256']) is str
            and SHA.fullmatch(plan['baseline_sha256']), 'Scope and frozen baseline required')
    inv = plan['inventory']
    require(type(inv) is dict and set(inv) == {'data_tiles','text_tiles','filter_ids'}
            and all(_ids(v) for v in inv.values()) and inv['data_tiles'], 'Explicit selected inventory required')
    require(not set(inv['data_tiles']) & set(inv['text_tiles']), 'Data/text inventory overlap')
    cases = plan['cases']
    require(type(cases) is list and 0 < len(cases) <= 1000, 'Bounded nonempty comparison cases required')
    identities, data, interactions, scenarios = set(), set(), set(), {}
    for case in cases:
        require(type(case) is dict and case.get('kind') in ('data','interaction')
                and set(case) == BASE_KEYS | (DATA_KEYS if case['kind'] == 'data' else set()), 'Invalid comparison case')
        require(all(type(case[k]) is str and ID.fullmatch(case[k]) for k in ('id','subject_id','scenario')),
                'Opaque comparison identifiers required')
        require(case['id'] not in identities and case['subject_kind'] in ('tile','filter'), 'Duplicate or invalid case')
        identities.add(case['id']); _context(case['context'])
        subjects = inv['data_tiles'] + inv['text_tiles'] if case['subject_kind'] == 'tile' else inv['filter_ids']
        require(case['subject_id'] in subjects, 'Comparison subject is outside selected inventory')
        if case['kind'] == 'interaction':
            interactions.add((case['subject_kind'], case['subject_id'])); continue
        require(case['subject_kind'] == 'tile' and case['subject_id'] in inv['data_tiles'], 'Data case needs a selected data tile')
        data.add(case['subject_id']); scenarios.setdefault(case['subject_id'],set()).add(case['scenario'])
        require(type(case['queries']) is dict and set(case['queries']) == {'source','warehouse','omni'}
                and all(type(x) is str and SHA.fullmatch(x) for x in case['queries'].values()), 'Frozen per-system query hashes required')
        cols = case['columns']
        require(type(cols) is dict and cols and len(cols) <= 200 and all(type(k) is str and ID.fullmatch(k)
                and v in TYPES for k,v in cols.items()), 'Canonical row schema required')
        require(_ids(case['grain']) and set(case['grain']) <= set(cols), 'Explicit row grain required')
        require(all(type(case[k]) is bool for k in ('ordered','allow_null_grain','truncated')), 'Explicit row behavior required')
        require(type(case['tolerances']) is dict and set(case['tolerances']) <= set(cols), 'Invalid tolerance fields')
        for col, tol in case['tolerances'].items():
            require(cols[col] == 'number' and type(tol) is dict and set(tol) == {'absolute','relative','reason'}
                    and all(_number(tol[k]) and tol[k] >= 0 for k in ('absolute','relative'))
                    and type(tol['reason']) is str and tol['reason'].strip(), 'Predeclared numeric tolerance and basis required')
        require(type(case['expected_metrics']) is dict and all(type(k) is str and ID.fullmatch(k)
                and _number(v) for k,v in case['expected_metrics'].items()), 'Explicit invariant metrics required')
        metrics = case['expected_metrics']
        require(INVARIANTS <= set(metrics) and all(type(metrics[k]) is int and metrics[k] >= 0 for k in INVARIANTS)
                and metrics['duplicate_keys'] == metrics['tenant_violations'] == 0,
                'Grain, orphan, tenant and join population invariants are required')
    require(data == set(inv['data_tiles']), 'Every selected data tile requires a comparison')
    requirements = plan['scenario_requirements']
    require(type(requirements) is dict and set(requirements) == data, 'Scenario requirements must cover each data tile')
    for tile, expected in requirements.items():
        require(_ids(expected) and 'baseline' in expected and set(expected) <= scenarios[tile], 'Required scenarios are missing')
    if plan['migration_scope'] == 'full_dashboard':
        require(interactions >= {('tile',t) for t in inv['data_tiles'] + inv['text_tiles']}
                | {('filter',f) for f in inv['filter_ids']}, 'Every selected tile and filter requires interaction evidence')
    review = plan['review']
    require(type(review) is dict and review.get('status') == 'approved'
            and type(review.get('reference')) is str and review['reference'].strip()
            and review.get('plan_sha256') == hash_json({k:v for k,v in plan.items() if k != 'review'}),
            'Freeze and review the independent comparison plan first')
    return plan


def _capture(capture, origin, ids):
    require(type(capture) is dict and type(capture.get('schema_version')) is int and capture['schema_version'] == 1
            and capture.get('kind') == 'migration_observations' and capture.get('origin') == origin, 'Invalid observation capture')
    require(set(capture) == {'schema_version','kind','origin','provenance','independent_of_candidate','reference','cases'},
            'Unknown observation capture fields')
    require(capture['provenance'] in ('source_observed','operator_defined','synthetic','native_observed')
            and type(capture['independent_of_candidate']) is bool
            and type(capture['reference']) is str and capture['reference'].strip(), 'Observation provenance required')
    require(type(capture['cases']) is dict and set(capture['cases']) <= ids, 'Unexpected observation cases')


def _rows(case, observation):
    require(type(observation) is dict and set(observation) == {'context','rows','metrics','truncated'}, 'Invalid data observation')
    require(type(observation['rows']) is list and len(observation['rows']) <= 100000, 'Bounded observation rows required')
    require(type(observation['metrics']) is dict and observation['metrics'] == case['expected_metrics']
            and all(_number(v) for v in observation['metrics'].values()), 'invariant_mismatch')
    require(type(observation['truncated']) is bool and observation['truncated'] == case['truncated'], 'truncation_mismatch')
    indexed, keys = {}, []
    for row in observation['rows']:
        require(type(row) is dict and set(row) == set(case['columns']), 'row_schema_mismatch')
        for name, kind in case['columns'].items():
            value = row[name]
            require(value is None or kind == 'number' and _number(value) or kind in ('string','date') and type(value) is str
                    or kind == 'boolean' and type(value) is bool, 'row_type_mismatch')
            if kind == 'date' and value is not None:
                from datetime import date
                try: require(date.fromisoformat(value).isoformat() == value, 'row_date_mismatch')
                except ValueError: raise ValueError('row_date_mismatch') from None
        require(case['allow_null_grain'] or all(row[x] is not None for x in case['grain']), 'null_grain')
        key = _json_bytes([row[x] for x in case['grain']])
        require(key not in indexed, 'duplicate_grain')
        indexed[key] = row; keys.append(key)
    return indexed, keys


def _equal(left, right, tolerance):
    if left is None or right is None: return left is right
    if not _number(left) or not _number(right): return type(left) is type(right) and left == right
    a,b = Decimal(str(left)),Decimal(str(right))
    return abs(a-b) <= max(Decimal(str(tolerance.get('absolute',0))), abs(a) * Decimal(str(tolerance.get('relative',0))))


def evaluate(plan, baseline, warehouse=None, omni=None):
    validate_plan(plan)
    require(hash_json(baseline) == plan['baseline_sha256'], 'Frozen baseline changed')
    ids = {case['id'] for case in plan['cases']}
    _capture(baseline, 'source', ids)
    require(baseline['independent_of_candidate'] is True and set(baseline['cases']) == ids,
            'Complete independent baseline required; candidate output cannot be its own oracle')
    captures = {'source':baseline,'warehouse':warehouse,'omni':omni}
    for name, capture in captures.items():
        if capture is not None: _capture(capture, name, ids)
    outcomes = []
    for index, case in enumerate(plan['cases']):
        issues, counts, prepared = [], {}, {}
        lanes = ['source','warehouse'] + (['omni'] if plan['migration_scope'] != 'model_only' else [])
        if case['kind'] == 'interaction': lanes = ['source','omni']
        for lane in lanes:
            capture = captures[lane]
            obs = capture['cases'].get(case['id']) if capture else None
            if obs is None:
                issues.append({'lane':lane,'code':'observation_missing','status':'pending'});continue
            context = dict(case['context'])
            if case['kind'] == 'data': context['query_sha256'] = case['queries'][lane]
            if type(obs) is not dict or obs.get('context') != context:
                issues.append({'lane':lane,'code':'context_mismatch','status':'failed'});continue
            try:
                if case['kind'] == 'data':
                    prepared[lane] = _rows(case,obs); counts[lane] = len(obs['rows'])
                else:
                    require(set(obs) == {'context','value'},'invalid_interaction')
                    _json_bytes(obs['value']); prepared[lane] = obs['value']
            except (ValueError, TypeError, RecursionError, OverflowError):
                issues.append({'lane':lane,'code':'invalid_rows_or_invariants' if case['kind']=='data' else 'invalid_interaction','status':'failed'})
        if 'source' in prepared:
            for lane in sorted(set(prepared) - {'source'}):
                mismatch = False
                if case['kind'] == 'interaction':
                    mismatch = _json_bytes(prepared[lane]) != _json_bytes(prepared['source'])
                else:
                    expected, order = prepared['source']; actual, actual_order = prepared[lane]
                    mismatch = set(actual) != set(expected) or case['ordered'] and order != actual_order
                    if not mismatch:
                        mismatch = any(not _equal(row[col], actual[key][col], case['tolerances'].get(col,{}))
                                       for key,row in expected.items() for col in case['columns'])
                if mismatch: issues.append({'lane':lane,'code':'behavior_mismatch','status':'failed'})
        status = 'failed' if any(i['status']=='failed' for i in issues) else 'pending' if issues else 'passed'
        outcomes.append({'case_index':index,'kind':case['kind'],'status':status,'row_counts':counts,'issues':issues})
    status = 'failed' if any(r['status']=='failed' for r in outcomes) else 'pending' if any(r['status']=='pending' for r in outcomes) else 'locally_consistent'
    return {'schema_version':1,'kind':'migration_parity_report','status':status,'plan_sha256':hash_json(plan),
            'bindings':dict(plan['bindings']),'baseline_sha256':plan['baseline_sha256'],
            'capture_sha256':{k:hash_json(v) if v is not None else None for k,v in captures.items()},
            'cases':outcomes,'native_verified':False,'evidence_authenticated':False,'acceptance_ready':False,
            'assurance':'Local comparison of supplied observations only. Native execution, rendered UI, observer independence and business approval require separate authenticated evidence.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--warehouse',type=Path);p.add_argument('--omni',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv)
    try:
        result=evaluate(load_json(args.plan),load_json(args.baseline),load_json(args.warehouse) if args.warehouse else None,
                        load_json(args.omni) if args.omni else None)
        from omni_native import _private_file
        _private_file(args.output,result)
        print(json.dumps({'status':result['status'],'native_verified':False}))
        return 0 if result['status']=='locally_consistent' else 1
    except (ValueError,TypeError,KeyError,OSError,RecursionError,OverflowError):
        print(json.dumps({'status':'blocked','code':'parity.invalid_input'}));return 1


if __name__ == '__main__': raise SystemExit(main())
