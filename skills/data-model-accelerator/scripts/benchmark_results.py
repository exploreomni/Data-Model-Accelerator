"""Compare independently supplied candidate exports with a frozen analyst baseline.

This checks evidence and values, not authentication, query execution or approval.
Every frozen case stays in the denominator. No SQL or candidate code is executed.
"""
import argparse
from decimal import Decimal, localcontext
from pathlib import Path
import sys

from ae_common import hash_file, hash_json, load_json, require, snapshot, write_json
from freeze_benchmark import (_bound_json, _decimal, _export_path, _fields, _sha,
                              _text, validate_rows, verify_baseline)


def _key(row, case):
    return tuple(_decimal(row[name]) if case['columns'][name]['type'] == 'decimal' else row[name]
                 for name in case['keys'])


def _equal(expected, actual, column):
    if expected is None or actual is None:
        return expected is actual
    if column['type'] not in ('integer', 'decimal'):
        return type(expected) is type(actual) and expected == actual
    # Inputs are already strictly typed. Preserve all bounded decimal digits,
    # including large exponents and subtraction of nearly equal large values.
    with localcontext() as context:
        context.prec = 4096
        left, right = Decimal(expected), Decimal(actual)
        tolerance = max(Decimal(column['abs_tolerance']), Decimal(column['rel_tolerance']) * abs(left))
        return abs(left - right) <= tolerance


def _case(case, expected, actual, base):
    result = {'id': case['id'], 'category': case['category'], 'passed': False, 'errors': [],
              'missing_keys': 0, 'extra_keys': 0, 'value_mismatches': 0, 'details': []}
    try:
        require(actual is not None, 'Missing candidate case')
        require(hash_json(case['context']) == hash_json(actual['context']), 'Execution context mismatch')
        receipt = actual['result']
        _fields(receipt, ('path', 'sha256', 'query_id'))
        _text(receipt['query_id'], 'candidate query_id')
        path = _export_path(receipt['path'], base)
        require(path != Path(case['expected']['path']), 'Candidate must have a separate result receipt')
        exported, _ = _bound_json(path, receipt['sha256'])
        _fields(exported, ('rows',))
        rows = validate_rows(exported['rows'], case['columns'], case['keys'])
        left = {_key(row, case): row for row in expected}
        right = {_key(row, case): row for row in rows}
        missing, extra = left.keys() - right.keys(), right.keys() - left.keys()
        result.update(missing_keys=len(missing), extra_keys=len(extra))
        # Iterate source/export order, not mixed-type key ordering.
        for key, row in left.items():
            if key not in right:
                if len(result['details']) < 100:
                    result['details'].append({'kind': 'missing_key', 'key': {name: row[name] for name in case['keys']}})
                continue
            for name, definition in case['columns'].items():
                if not _equal(row[name], right[key][name], definition):
                    result['value_mismatches'] += 1
                    if len(result['details']) < 100:
                        result['details'].append({'kind': 'value_mismatch', 'key': {name: row[name] for name in case['keys']},
                                                  'column': name, 'expected': row[name], 'actual': right[key][name]})
        for key, row in right.items():
            if key in extra and len(result['details']) < 100:
                result['details'].append({'kind': 'extra_key', 'key': {name: row[name] for name in case['keys']}})
        if missing or extra or result['value_mismatches']:
            result['errors'].append('Candidate keys or values differ from frozen expectations')
        result['passed'] = not result['errors']
    except (ValueError, OSError, UnicodeError) as error:
        result['errors'].append(str(error))
    result['details_truncated'] = (result['missing_keys'] + result['extra_keys'] + result['value_mismatches']) > len(result['details'])
    return result


def compare(baseline_path, actual_path, project):
    baseline = verify_baseline(baseline_path)
    actual_path = Path(actual_path).absolute()
    actual, digest = _bound_json(actual_path)
    _fields(actual, ('schema_version', 'baseline_sha256', 'candidate_sha256', 'analyst_id', 'cases'))
    require(type(actual['schema_version']) is int and actual['schema_version'] == 1, 'Unsupported actual schema_version')
    require(_sha(actual['baseline_sha256']) == baseline['baseline_sha256'], 'Frozen baseline association mismatch')
    candidate = snapshot(project)
    require(_sha(actual['candidate_sha256']) == candidate['sha256'], 'Candidate project drift')
    require(_text(actual['analyst_id'], 'analyst_id') == baseline['contract']['analyst_id'], 'Independent analyst identity mismatch')
    cases = baseline['contract']['cases']
    ids = {case['id'] for case in cases}
    require(type(actual['cases']) is list, 'Candidate cases must be a list')
    indexed = {}
    for case in actual['cases']:
        _fields(case, ('id', 'context', 'result'))
        case_id = _text(case['id'], 'case id')
        require(case_id in ids and case_id not in indexed, 'Duplicate or unknown candidate case')
        indexed[case_id] = case
    results = [_case(case, baseline['expected_rows'][case['id']], indexed.get(case['id']), actual_path.parent) for case in cases]
    require(snapshot(project) == candidate and hash_file(actual_path) == digest, 'Candidate/evidence changed during comparison')
    # Recheck all original baseline receipts after comparison as well.
    require(verify_baseline(baseline_path)['baseline_sha256'] == baseline['baseline_sha256'], 'Baseline changed during comparison')
    categories = {}
    for name in ('compatibility', 'correctness'):
        selected = [case for case in results if case['category'] == name]
        passed = sum(case['passed'] for case in selected)
        categories[name] = {'expected': len(selected), 'passed': passed, 'failed': len(selected) - passed}
    passed = sum(case['passed'] for case in results)
    return {'schema_version': 1, 'kind': 'accuracy_benchmark', 'passed': passed == len(results),
            'baseline_sha256': baseline['baseline_sha256'], 'candidate_sha256': candidate['sha256'],
            'actual_sha256': digest, 'analyst_id': actual['analyst_id'],
            'coverage': {'expected_cases': len(results), 'observed_cases': len(indexed),
                         'passed_cases': passed, 'failed_cases': len(results) - passed},
            'categories': categories, 'cases': results,
            'limitations': ['Supplied query receipts and identities are self-attested; this tool does not execute or authenticate queries.',
                            'Coverage is limited to the frozen cases and their declared context. A pass is not human approval or proof of undeclared behavior.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'actual', 'project', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(args.project.resolve() not in args.output.absolute().parents, 'Benchmark output must stay outside candidate project')
        report = compare(args.baseline, args.actual, args.project)
        write_json(args.output, report)
        print(('PASS' if report['passed'] else 'FAIL') + ': ' + str(report['coverage']))
        return 0 if report['passed'] else 1
    except (ValueError, OSError, UnicodeError) as error:
        print('Benchmark refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
