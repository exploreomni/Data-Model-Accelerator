"""Require explicit source-value coverage in the independent frozen benchmark.

The analyst declares preserved target fields before engineering. This verifies
coverage and values; it cannot infer completeness or authenticate their origin.
"""
from ae_common import hash_file, require
from benchmark_results import compare
from freeze_benchmark import _bound_json, _decimal, _fields, _sha, _text, verify_baseline


def verify(contract_path, baseline_path, actual_path, inventory_path, project):
    contract, contract_hash = _bound_json(contract_path)
    _fields(contract, ('schema_version', 'kind', 'source_revision', 'catalogue_sha256',
                      'baseline_sha256', 'preserved_fields'))
    require(type(contract['schema_version']) is int and contract['schema_version'] == 1
            and contract['kind'] == 'source_value_contract', 'Invalid source-value contract')
    baseline = verify_baseline(baseline_path)
    require(_sha(contract['baseline_sha256']) == baseline['baseline_sha256'], 'Source-value baseline mismatch')
    for key in ('source_revision', 'catalogue_sha256'):
        require(contract[key] == baseline['contract'][key], 'Source-value context mismatch: ' + key)
    inventory, inventory_hash = _bound_json(inventory_path)
    require(inventory.get('kind') == 'data_model_inventory', 'Invalid source-value model inventory')
    models = {}
    for model in inventory.get('models', []):
        mid = _text(model.get('model_id'), 'model_id')
        require(mid not in models, 'Duplicate source-value model')
        models[mid] = set(model['columns'])
    cases = {case['id']: case for case in baseline['contract']['cases']}
    fields = contract['preserved_fields']
    require(type(fields) is list and fields, 'Independent source-value field coverage is required')
    seen, coverage = set(), []
    for field in fields:
        _fields(field, ('model_id', 'model_column', 'case_id', 'case_column', 'source_reference'))
        for key, value in field.items():
            _text(value, key)
        pair = (field['model_id'], field['model_column'])
        require(pair not in seen, 'Duplicate source-value field binding')
        seen.add(pair)
        require(pair[0] in models and pair[1] in models[pair[0]], 'Source-value field is absent from model inventory')
        case = cases.get(field['case_id'])
        require(case is not None and field['case_column'] in case['columns'], 'Source-value case/column absent from frozen baseline')
        # Allow neither approximate identifier conservation nor hidden precision relaxation.
        spec = case['columns'][field['case_column']]
        require(all(_decimal(spec.get(tolerance, '0')) == 0 for tolerance in ('abs_tolerance', 'rel_tolerance')),
                'Preserved source values require exact comparisons')
        coverage.append(dict(field))
    benchmark = compare(baseline_path, actual_path, project)
    require(hash_file(contract_path) == contract_hash and hash_file(inventory_path) == inventory_hash, 'Source-value contract changed')
    selected = {field['case_id'] for field in fields}
    passed = {case['id']: case['passed'] for case in benchmark['cases']}
    return {'schema_version': 1, 'kind': 'source_value_verification',
            'passed': benchmark['passed'] and all(passed[cid] for cid in selected),
            'candidate_sha256': benchmark['candidate_sha256'], 'baseline_sha256': baseline['baseline_sha256'],
            'contract_sha256': contract_hash, 'inventory_sha256': inventory_hash,
            'fields': coverage, 'required_cases': sorted(selected), 'benchmark': benchmark,
            'limitations': ['Coverage and raw-source derivation are analyst declarations; require independent review before freezing.',
                            'Only declared preserved fields are covered; transformations and omitted fields need separate cases.']}
