"""Replay the frozen retail forward-test with independent expectations.

This is now a regression fixture. Its first authored trial withheld the oracle
from the candidate author; repeated runs are not new blind agent evaluations.
Only reviewed bundled Python/dbt files are executed. No external warehouse.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

SKILL = Path(__file__).resolve().parents[1]
CASE = SKILL / 'examples/dbt-retail-holdout'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def equal(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(actual) == set(expected) and all(equal(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(equal(a, e) for a, e in zip(actual, expected))
    if isinstance(expected, float):
        return type(actual) in (float, int) and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12)
    return type(actual) is type(expected) and actual == expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output == SKILL or SKILL in output.parents:
        parser.error('Use a new output directory outside the skill')
    pins = json.loads((CASE / 'holdout-pins.json').read_text())
    declared = {item['path'] for item in pins['files']}
    observed = {path.relative_to(CASE).as_posix() for path in CASE.rglob('*')
        if path.is_file() and '__pycache__' not in path.parts and path.name != 'holdout-pins.json'}
    if len(declared) != len(pins['files']) or observed != declared:
        raise ValueError('Frozen holdout file inventory changed')
    for item in pins['files']:
        path = CASE / item['path']
        if path.resolve() != path.absolute() or CASE not in path.resolve().parents or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Changed/noncanonical frozen holdout file: ' + item['path'])
    output.mkdir(parents=True)
    candidate = load_module('dma_retail_candidate', CASE / 'candidate/evaluator.py')
    oracle = load_module('dma_retail_oracle', CASE / 'expected/evaluate.py')
    expected = json.loads((CASE / 'expected/expected.json').read_text())
    raw = json.loads((CASE / 'input/raw-data.json').read_text())
    checks = []
    for group in ('valid_scenarios', 'valid_mutations'):
        for test in expected[group]:
            data = oracle.mutation(raw, test['name']) if group == 'valid_mutations' else copy.deepcopy(raw)
            try:
                actual = candidate.evaluate(data, test['params'])
                passed, error = equal(actual, test['expected']), None
            except Exception as exc:
                actual, passed, error = None, False, type(exc).__name__ + ': ' + str(exc)
            checks.append({'id': test['name'], 'passed': passed, 'expected': test['expected'], 'actual': actual, 'error': error})
    reasons = ('conflict', 'orphan', 'persona', 'authorization', 'status')
    for index, test in enumerate(expected['invalid_scenarios']):
        data = oracle.mutation(raw, test['mutation']) if test['mutation'] else copy.deepcopy(raw)
        try:
            actual = candidate.evaluate(data, test['params'])
            passed, error = False, 'Unexpected accepted outputs'
        except candidate.ValidationError as exc:
            actual, error = None, str(exc)
            passed = reasons[index] in error.lower()
        except Exception as exc:
            actual, passed, error = None, False, type(exc).__name__ + ': ' + str(exc)
        checks.append({'id': test['mutation'] or 'invalid_context_' + str(index), 'passed': passed, 'actual': actual, 'error': error})
    # Run a relocated copy: the fixture cannot pass by using an author's temp DB.
    working = output / 'working'
    shutil.copytree(CASE / 'candidate', working / 'candidate', ignore=shutil.ignore_patterns('runtime', '__pycache__', 'evidence', '_author.py'))
    shutil.copytree(CASE / 'input', working / 'input')
    command = [sys.executable, str(working / 'candidate/validate_local.py'), '--verifier', str(SKILL / 'scripts/verify_dbt_evidence.py')]
    try:
        native = subprocess.run(command, capture_output=True, text=True, timeout=180)
        code, stdout, stderr = native.returncode, native.stdout, native.stderr
    except subprocess.TimeoutExpired as exc:
        decode = lambda text: text.decode('utf-8', errors='replace') if isinstance(text, bytes) else text or ''
        code, stdout, stderr = 124, decode(exc.stdout), decode(exc.stderr) + '\nNative holdout timeout\n'
    (output / 'native-stdout.txt').write_text(stdout)
    (output / 'native-stderr.txt').write_text(stderr)
    counts = None
    native_evidence = working / 'candidate/evidence'
    if code == 0:
        details = json.loads((native_evidence / 'native-dbt-validation.json').read_text())
        counts = details['build_counts']
        native_output = json.loads((native_evidence / 'native-dbt-output.json').read_text())
        native_passed = equal(native_output, expected['valid_scenarios'][0]['expected'])
        # Check actual enabled native model inventory, not a prose placement claim.
        manifest = json.loads((native_evidence / 'native-build/manifest.json').read_text())
        enabled_models = {n['name'] for n in manifest['nodes'].values() if n['resource_type'] == 'model' and n['config'].get('enabled', True)}
        intended_models = set(json.loads((CASE / 'candidate/model-map.json').read_text()))
        placement_passed = enabled_models == intended_models and 'retail_fulfillment_summary' not in enabled_models
    else:
        native_passed = placement_passed = False
    checks.extend([
        {'id': 'relocated_native_dbt_build_and_independent_baseline', 'passed': native_passed, 'exit_code': code, 'counts': counts},
        {'id': 'report_context_stays_downstream', 'passed': placement_passed},
    ])
    if len(checks) != 15:
        raise ValueError('Frozen holdout test denominator changed')
    result = {'schema_version': 1, 'origin': 'synthetic', 'kind': 'retail_dbt_holdout_regression',
        'scope': 'One internal forward-test, now a regression; native dbt/DuckDB only. No Snowflake, Omni, host generalization or human approval.',
        'pins_sha256': hashlib.sha256((CASE / 'holdout-pins.json').read_bytes()).hexdigest(),
        'checks': checks, 'passed': sum(c['passed'] for c in checks), 'total': 15,
        'status': 'pass' if all(c['passed'] for c in checks) else 'fail'}
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'passed', 'total')}))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
