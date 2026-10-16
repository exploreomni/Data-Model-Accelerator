"""Offline comparison of every supplied attempt against a frozen authoring oracle.

``compare(suite, runs)`` verifies the suite pin, contract/source files, packet and
host observations, then recomputes authoring checks. It launches nothing and
never changes model defaults. A match means the configured findings/statuses
matched; it is not business acceptance, verified model execution or a winner.
Missing usage remains unknown. Token categories are never added to each other.
"""
import copy
import argparse
import json
from pathlib import Path

from ae_common import _path, hash_file, hash_json, load_json, require, safe_relative, write_json
from agent_execution import record_execution, ID, SHA, USAGE_FIELDS
from authoring_evidence import capture, fields, validate_contract, STATUSES
from authoring_quality import evaluate, checker_version
from authoring_provenance import MAX_BYTES, MAX_TOTAL, MAX_FILES

CASE_FIELDS = {'id', 'packet_sha256', 'contract_path', 'contract_sha256', 'source_root',
               'source_files', 'dialect', 'paths', 'required_findings', 'allowed_statuses'}
MAX_CASES, MAX_VARIANTS, MAX_ATTEMPTS = 32, 16, 256


def _id(value):
    require(type(value) is str and ID.fullmatch(value), 'Invalid benchmark identity')


def _sha(value):
    require(type(value) is str and SHA.fullmatch(value), 'Invalid benchmark pin')


def _path_value(value, directory=False):
    require(type(value) is str and 0 < len(value) <= 8192, 'Invalid benchmark path')
    result = _path(value)
    if directory: require(result.is_dir(), 'Benchmark directory required')
    return result


def _list(value, minimum, maximum):
    require(type(value) is list and minimum <= len(value) <= maximum, 'Invalid benchmark denominator')


def _sources(case):
    root = _path_value(case['source_root'], directory=True)
    size = 0
    for relative in case['source_files']:
        path = _path(root / safe_relative(relative))
        require(path.is_file() and path.stat().st_size <= MAX_BYTES, 'Invalid benchmark source file bound')
        size += path.stat().st_size
    require(size <= MAX_TOTAL, 'Benchmark source byte bound exceeded')
    require(capture(root, list(case['source_files'])) == case['source_files'], 'Frozen benchmark sources changed')
    return root


def _contract(case):
    path = _path_value(case['contract_path'])
    require(hash_file(path) == case['contract_sha256'], 'Frozen benchmark contract changed')
    contract = validate_contract(load_json(path, max_bytes=MAX_BYTES))
    require(hash_file(path) == case['contract_sha256'], 'Benchmark contract changed while reading')
    require(all(model['path'] is None or model['path'] in case['paths'] for model in contract['models']),
            'Benchmark contract model outside candidate paths')
    for entry in contract['provenance']:
        if 'source' in entry:
            source = entry['source']
            require(type(source) is dict and type(source.get('path')) is str and source.get('path') in case['source_files']
                    and source.get('sha256') == case['source_files'][source['path']],
                    'Benchmark provenance source is not frozen')
    return contract


def _suite(suite):
    fields(suite, ('schema_version', 'kind', 'cases'))
    require(type(suite['schema_version']) is int and suite['schema_version'] == 1
            and suite['kind'] == 'agent_benchmark_suite', 'Unsupported benchmark suite')
    _list(suite['cases'], 1, MAX_CASES)
    cases = {}
    for case in suite['cases']:
        fields(case, CASE_FIELDS); _id(case['id'])
        require(case['id'] not in cases, 'Duplicate benchmark case')
        cases[case['id']] = case
        _sha(case['packet_sha256']); _sha(case['contract_sha256'])
        require(type(case['dialect']) is str and 0 < len(case['dialect']) <= 64, 'Invalid benchmark dialect')
        require(type(case['source_files']) is dict and len(case['source_files']) <= MAX_FILES,
                'Invalid benchmark source inventory')
        for path, digest in case['source_files'].items(): safe_relative(path); _sha(digest)
        _list(case['paths'], 1, MAX_FILES)
        for path in case['paths']: safe_relative(path)
        require(len(case['paths']) == len(set(case['paths'])), 'Duplicate benchmark output path')
        _list(case['allowed_statuses'], 1, len(STATUSES))
        require(all(type(status) is str and status in STATUSES for status in case['allowed_statuses'])
                and len(set(case['allowed_statuses'])) == len(case['allowed_statuses']), 'Invalid allowed statuses')
        _list(case['required_findings'], 1, 256)
        seen = set()
        for row in case['required_findings']:
            fields(row, ('code', 'status', 'model_id'))
            require(type(row['code']) is str and 0 < len(row['code']) <= 256, 'Invalid expected finding')
            require(type(row['status']) is str and row['status'] in STATUSES, 'Invalid expected finding status')
            if row['model_id'] is not None: _id(row['model_id'])
            key = (row['code'], row['status'], row['model_id'])
            require(key not in seen, 'Duplicate expected finding'); seen.add(key)
        _sources(case); _contract(case)
    return cases


def _runs(runs, suite_sha, cases):
    fields(runs, ('schema_version', 'kind', 'suite_sha256', 'variants'))
    require(type(runs['schema_version']) is int and runs['schema_version'] == 1
            and runs['kind'] == 'agent_benchmark_runs', 'Unsupported benchmark runs')
    _sha(runs['suite_sha256']); require(runs['suite_sha256'] == suite_sha, 'Benchmark suite pin differs')
    _list(runs['variants'], 2, MAX_VARIANTS)
    variants, total = set(), 0
    for variant in runs['variants']:
        fields(variant, ('id', 'cases')); _id(variant['id'])
        require(variant['id'] not in variants, 'Duplicate benchmark variant'); variants.add(variant['id'])
        _list(variant['cases'], len(cases), len(cases)); seen = set()
        for case in variant['cases']:
            fields(case, ('id', 'attempts')); _id(case['id'])
            require(case['id'] in cases and case['id'] not in seen, 'Missing or duplicate variant case')
            seen.add(case['id']); _list(case['attempts'], 1, 10)
            total += len(case['attempts'])
            for attempt in case['attempts']:
                fields(attempt, ('artifact_root', 'execution'))
                fields(attempt['execution'], ('packet_dir', 'request'))
        require(seen == set(cases), 'Variant case denominator differs')
    require(total <= MAX_ATTEMPTS, 'Benchmark attempt bound exceeded')


def compare(suite, runs):
    """Return all recomputed attempts; malformed or stale inputs raise ValueError."""
    suite, runs = copy.deepcopy(suite), copy.deepcopy(runs)
    cases = _suite(suite); suite_sha = hash_json(suite); _runs(runs, suite_sha, cases)
    version, identities, variants = checker_version(), set(), []
    for variant in runs['variants']:
        results, usage_values = [], {key: [] for key in USAGE_FIELDS}
        for selected in variant['cases']:
            case, attempts = cases[selected['id']], []
            for number, attempt in enumerate(selected['attempts'], 1):
                source_root, contract = _sources(case), _contract(case)
                root = _path_value(attempt['artifact_root'], directory=True)
                host = record_execution(_path_value(attempt['execution']['packet_dir'], directory=True),
                                        attempt['execution']['request'])
                require(host['packet_sha256'] == case['packet_sha256'], 'Attempt context differs from benchmark case')
                identity = (host['task_id'], host['run_id'])
                require(identity not in identities, 'Host run counted more than once'); identities.add(identity)
                checked = evaluate(root, source_root, contract, case['paths'], case['dialect'])
                _sources(case); _contract(case)
                require(checked['checker_sha256'] == version == checker_version(), 'Benchmark checker changed')
                require(all(case['source_files'].get(path) == digest for path, digest in checked['source_evidence'].items()),
                        'Benchmark consumed an unpinned provenance source')
                actual = {(row['code'], row['status'], row['model_id']) for row in checked['findings']}
                missing = [row for row in case['required_findings']
                           if (row['code'], row['status'], row['model_id']) not in actual]
                disallowed = sorted({row['status'] for row in checked['findings']} - set(case['allowed_statuses']))
                attempts.append({'attempt': number, 'matches_expected': not missing and not disallowed,
                    'status': checked['status'], 'dialect': checked['dialect'],
                    'missing_required_findings': missing, 'disallowed_statuses': disallowed,
                    'findings': checked['findings'], 'coverage': {'outputs': len(checked['outputs']),
                    'findings': checked['total'], 'counts': checked['counts']},
                    'outputs': checked['outputs'], 'execution': host})
                for key in USAGE_FIELDS: usage_values[key].append(host['usage'][key])
            results.append({'id': case['id'], 'first_pass_match': attempts[0]['matches_expected'],
                'final_match': attempts[-1]['matches_expected'], 'attempt_count': len(attempts),
                'repair_count': len(attempts)-1, 'attempts': attempts})
        variants.append({'id': variant['id'], 'case_count': len(results), 'cases': results,
            'first_pass_matches': sum(row['first_pass_match'] for row in results),
            'final_matches': sum(row['final_match'] for row in results),
            'attempt_count': sum(row['attempt_count'] for row in results),
            'repair_count': sum(row['repair_count'] for row in results),
            'host_reported_usage_totals': {key: sum(values) if all(value is not None for value in values) else None
                                         for key, values in usage_values.items()},
            'usage_known_attempt_counts': {key: sum(value is not None for value in values)
                                          for key, values in usage_values.items()}})
    return {'schema_version': 1, 'kind': 'agent_benchmark_report', 'suite_sha256': suite_sha,
        'checker_sha256': version, 'case_count': len(cases), 'variant_count': len(variants), 'variants': variants,
        'attempt_count': sum(row['attempt_count'] for row in variants),
        'repair_count': sum(row['repair_count'] for row in variants),
        'qualification': 'Frozen-oracle static comparison only. Host model identity, effort, context isolation and usage '
                         'are unverified observations; missing observations remain unknown. No winner, price, routing '
                         'change, native acceptance or approval is established.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        suite = load_json(args.suite, max_bytes=MAX_BYTES)
        runs = load_json(args.runs, max_bytes=2*MAX_BYTES)
        output = _path(args.output, must_exist=False)
        require(not output.exists() and output.parent.is_dir(), 'New benchmark report file required')
        report = compare(suite, runs)
        protected = [_path_value(case['source_root'], directory=True) for case in suite['cases']]
        protected += [_path_value(attempt['execution']['packet_dir'], directory=True)
                      for variant in runs['variants'] for case in variant['cases'] for attempt in case['attempts']]
        require(all(root not in output.parents for root in protected), 'Report cannot be written into source or packet inputs')
        write_json(output, report)
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, RecursionError):
        parser.exit(2, 'Benchmark blocked; inspect schema, immutable pins, scoped files and host observations locally.\n')
    matched = all(case['final_match'] for variant in report['variants'] for case in variant['cases'])
    print(json.dumps({key: report[key] for key in ('case_count', 'variant_count', 'attempt_count', 'repair_count')}
                     | {'all_final_rubrics_match': matched}))
    return 0 if matched else 1


if __name__ == '__main__': raise SystemExit(main())
