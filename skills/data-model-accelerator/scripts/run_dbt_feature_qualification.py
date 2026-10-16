"""Qualify synthetic dbt 2.0.8 metadata features with preinstalled runtimes.

No installation, login, warehouse build, or customer input is performed. The
output is a new private directory outside this checkout. Native failures are
expected fixtures and must identify the exact failed check and resource.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from dbt_feature_delivery import prepare_features
from dbt_information_schema import _load_duckdb, read_information_schema
from dbt_native_lint import _run, lint_native
from dbt_runtime import driver_contract, observed_version, runtime_identity
from source_adapters.base import read_json
from source_adapters.filesystem import _open_directory, new_json_output, read_assigned

REPOSITORY = Path(__file__).resolve().parents[3]
VERSION = '2.0.8'
PROJECT = 'dma_feature_qualification'
CHECKS = ('dma_model_descriptions', 'dma_public_model_owners')
CHECK_IDS = {'check.' + PROJECT + '.' + name for name in CHECKS}
MODEL_IDS = {'model.' + PROJECT + '.customers', 'model.' + PROJECT + '.internal_model'}
OFFENDER = 'model.' + PROJECT + '.customers'
SCENARIOS = {'passing': None, 'missing_description': CHECKS[0], 'missing_public_owner': CHECKS[1]}
EXPECTED_CANDIDATES = {'dbt_project.yml.fragment', 'checks/dma_model_descriptions.sql',
                       'checks/dma_public_model_owners.sql', 'checks/_dma_checks.yml'}


def _require(condition, code):
    if not condition:
        raise ValueError('dbt.feature_qualification.' + code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, raw):
    """Create only new private files within the controlled output directory."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw.encode('utf-8') if isinstance(raw, str) else raw)


def _save_json(path, value):
    with new_json_output(path) as write:
        write(value)


def _new_output(value):
    raw = os.fspath(value)
    path = Path(raw).absolute()
    _require('..' not in Path(raw).parts and path.parent.resolve(strict=True) == path.parent,
             'canonical_output_required')
    _require(not path.is_relative_to(REPOSITORY), 'external_output_required')
    parent, _ = _open_directory(path.parent)
    try:
        os.mkdir(path.name, mode=0o700, dir_fd=parent)
    finally:
        os.close(parent)
    _require(path.resolve(strict=True) == path and stat.S_IMODE(path.stat().st_mode) == 0o700,
             'private_output_required')
    return path


def _driver_bytes(path, contract):
    """Read the pinned preinstalled driver without following any path links."""
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, 'canonical_driver_required')
    directory, _ = _open_directory(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= 256 * 1024 * 1024, 'driver_size_or_type')
        raw = stream.read(256 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) == before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns,
             'driver_changed')
    _require(_sha(raw) == contract['sha256'], 'driver_pin_mismatch')
    return raw


def _snapshot(root):
    files, total = {}, 0
    for current, directories, names in os.walk(root, followlinks=False):
        for name in directories:
            _require(not (Path(current) / name).is_symlink(), 'source_symlink')
        for name in sorted(names):
            relative = (Path(current) / name).relative_to(root).as_posix()
            _require(len(files) < 64, 'source_file_limit')
            raw = read_assigned(root, relative)
            total += len(raw)
            _require(total <= 32 * 1024 * 1024, 'source_byte_limit')
            files[relative] = _sha(raw)
    return files


def _read_json(path):
    return read_json(read_assigned(path.parent, path.name).decode('utf-8'))


def _verify_manifest(manifest):
    nodes = manifest.get('nodes')
    _require(isinstance(nodes, dict), 'invalid_manifest')
    actual = {uid: node for uid, node in nodes.items() if node.get('resource_type') == 'check'}
    _require(set(actual) == CHECK_IDS, 'check_manifest_denominator')
    _require({uid for uid, node in nodes.items() if node.get('resource_type') == 'model'} == MODEL_IDS,
             'model_manifest_denominator')
    for uid, node in actual.items():
        config = node.get('config', {})
        _require(node.get('unique_id') == uid and config.get('enabled') is True
                 and config.get('severity') == 'ERROR', 'disabled_or_nonerror_check')
    _require(not any(uid in manifest.get('disabled', {}) for uid in CHECK_IDS), 'disabled_expected_check')
    return sorted(actual)


def _verify_results(rows, expected_failure):
    _require(isinstance(rows, list) and len(rows) == len(CHECK_IDS), 'check_result_denominator')
    seen = set()
    for row in rows:
        _require(isinstance(row, dict), 'invalid_check_result')
        uid = row.get('unique_id')
        _require(uid in CHECK_IDS and uid not in seen, 'unexpected_or_duplicate_check_result')
        seen.add(uid)
        fails = expected_failure is not None and uid == 'check.' + PROJECT + '.' + expected_failure
        _require(row.get('status') == ('fail' if fails else 'pass')
                 and type(row.get('failures')) is int and row['failures'] == (1 if fails else 0),
                 'unexpected_check_result')


def _verify_check_output(code, stdout, stderr, expected_failure):
    text, errors = stdout.decode('utf-8'), stderr.decode('utf-8')
    outcomes = re.findall(r'^\s*(Passed|Failed)\s+\[\s*[0-9.]+s\]\s+check\s+([A-Za-z0-9_]+)\s*$', text, re.M)
    _require(len(outcomes) == 2 and {name for _, name in outcomes} == set(CHECKS), 'check_output_denominator')
    for status, name in outcomes:
        _require(status == ('Failed' if name == expected_failure else 'Passed'), 'unexpected_check_outcome')
    if expected_failure is None:
        _require(code == 0 and '[error]' not in errors.lower(), 'passing_check_failed')
        return {'source': 'run_results_and_console', 'outcomes': dict((name, status) for status, name in outcomes)}
    _require(code == 1, 'negative_fixture_exit')
    diagnostics = re.findall(r"check '([^']+)' failed with (\d+) violation\(s\)", errors)
    _require(diagnostics == [(expected_failure, '1')], 'negative_fixture_violation_count')
    ids = re.findall(r'[│|]\s*(model\.[^\s│|]+)\s*[│|]', errors)
    _require(ids == [OFFENDER] and errors.lower().count('[error]') == 1, 'negative_fixture_resource')
    return {'source': 'exact_console_outcomes_and_failure_diagnostic',
            'outcomes': dict((name, status) for status, name in outcomes),
            'failed_check_id': 'check.' + PROJECT + '.' + expected_failure,
            'violations': 1, 'violating_resource_ids': ids}


def _command(executable, verb, project, profiles, target, distribution):
    args = [str(executable), verb, '--no-version-check', '--no-send-anonymous-usage-stats', '--no-manage-state',
            '--project-dir', str(project), '--profiles-dir', str(profiles), '--target', 'local',
            '--target-path', str(target), '--log-path', str(target / 'logs'), '--write-json', '--generate-info-schema']
    if verb == 'check':
        args += ['--static-analysis', 'baseline' if distribution == 'dbt' else 'off']
    return args


def _execute(command, home, base, label):
    code, stdout, stderr = _run(command, home, timeout=45)
    _write(base / (label + '.stdout.txt'), stdout)
    _write(base / (label + '.stderr.txt'), stderr)
    return code, stdout, stderr


def _scenario(root, scenario, expected_failure, candidates, executable, distribution, driver, contract):
    base = root / scenario
    project, profiles, home = base / 'project', base / 'profiles', base / 'home'
    for directory in (project / 'models', project / 'checks', profiles, home):
        directory.mkdir(parents=True, mode=0o700)
    _write(home / contract['cache_relative_path'], driver)
    config = ('name: ' + PROJECT + '\nversion: 1.0.0\nconfig-version: 2\nprofile: dma_features\n'
              'model-paths: [models]\ncheck-paths: [checks]\n' + candidates['dbt_project.yml.fragment'])
    _write(project / 'dbt_project.yml', config)
    for name, content in candidates.items():
        if name.startswith('checks/'):
            _write(project / name, content)
    _write(project / 'models/customers.sql', 'select 1 as customer_id\n')
    _write(project / 'models/internal_model.sql', 'select 2 as another_id\n')
    description = '""' if scenario == 'missing_description' else 'A documented public model.'
    group = '' if scenario == 'missing_public_owner' else '      group: analytics\n'
    schema = ('version: 2\ngroups:\n  - name: analytics\n    owner:\n      name: Synthetic Analytics Owner\n'
              'models:\n  - name: customers\n    description: ' + description + '\n'
              '    config:\n      access: public\n' + group +
              '    columns:\n      - name: customer_id\n        description: Synthetic identifier.\n        data_type: integer\n'
              '  - name: internal_model\n    description: A documented internal model.\n')
    _write(project / 'models/schema.yml', schema)
    warehouse = base / 'warehouse.duckdb'
    _write(profiles / 'profiles.yml', 'dma_features:\n  target: local\n  outputs:\n    local:\n'
           '      type: duckdb\n      path: ' + json.dumps(str(warehouse)) + '\n      threads: 1\n')
    source = _snapshot(project)
    parse_target, check_target = base / 'parse', base / 'check'
    code, _, _ = _execute(_command(executable, 'parse', project, profiles, parse_target, distribution), home, base, 'parse')
    _require(code == 0, 'parse_failed')
    enabled = _verify_manifest(_read_json(parse_target / 'manifest.json'))
    snapshot = parse_target / 'info_schema/v1'
    before_metadata = _snapshot(snapshot)
    normalized = read_information_schema(snapshot, stage='parse')
    _require({row['unique_id'] for row in normalized['models']} == MODEL_IDS, 'metadata_model_denominator')
    _require(any(row['node_unique_id'] == OFFENDER and row['column_name'] == 'customer_id'
                 and row['data_type_declared'] == 'integer' for row in normalized['columns']), 'metadata_declared_column')
    _require(normalized['evidence_stage'] == 'metadata_only' and not normalized['execution_performed']
             and normalized['warehouse_validation'] == 'not_run', 'metadata_overclaims')
    _require(before_metadata == _snapshot(snapshot), 'metadata_source_changed')
    _save_json(base / 'normalized-metadata.json', normalized)
    code, stdout, stderr = _execute(_command(executable, 'check', project, profiles, check_target, distribution), home, base, 'check')
    outcome = _verify_check_output(code, stdout, stderr, expected_failure)
    results_path = check_target / 'run_results.json'
    if expected_failure is None or results_path.exists():
        results = _read_json(results_path)
        _require(results.get('args', {}).get('which') == 'check', 'wrong_result_command')
        _verify_results(results.get('results'), expected_failure)
    _require(_snapshot(project) == source, 'project_source_changed')
    _require(not warehouse.exists() and not Path(str(warehouse) + '.wal').exists(), 'unexpected_warehouse_created')
    _driver_bytes(home / contract['cache_relative_path'], contract)
    # The retained evidence needs the driver pin, not three large duplicate
    # binaries. Only this newly created private copy is removed.
    (home / contract['cache_relative_path']).unlink()
    return {'scenario': scenario, 'status': 'passed', 'enabled_error_check_ids': enabled,
            'check_exit_code': code, 'outcome_evidence': outcome,
            'project_source_sha256': source, 'source_unchanged': True, 'warehouse_created': False,
            'information_schema': {'version': 1, 'file_count': len(before_metadata),
                                   'model_ids': sorted(MODEL_IDS), 'declared_columns': len(normalized['columns']),
                                   'source_unchanged': True, 'evidence_stage': normalized['evidence_stage']}}


def _lint_cases(root, executable, selection):
    if selection['distribution'] == 'dbt_oss':
        return {'status': 'unsupported', 'execution_performed': False,
                'reason': 'Native lint is unavailable in the dbt-oss distribution.'}
    cases = []
    for name, body in (('clean', b'SELECT 1 AS id\n'), ('violating', b'select 1 as id\n')):
        source = root / ('lint_' + name)
        source.mkdir(mode=0o700)
        _write(source / 'model.sql', body)
        manifest = {'schema_version': 1, 'kind': 'sql_lint_manifest', 'expected_execution_units': ['model'],
                    'files': [{'path': 'model.sql', 'sha256': _sha(body), 'role': 'model_sql', 'format': 'sql',
                               'execution_units': ['model'], 'source_paths': []}]}
        before = _snapshot(source)
        report = lint_native(source, manifest, selection, 'duckdb', executable=executable, execute=True)
        _require(report['execution_performed'] and len(report['files']) == 1, 'lint_missing_execution_or_file')
        row = report['files'][0]
        _require(row['path'] == 'model.sql' and row['sha256'] == _sha(body), 'lint_wrong_source')
        if name == 'clean':
            _require(report['status'] == 'passed' and row['status'] == 'checked' and not row['violations'], 'clean_lint_failed')
        else:
            _require(report['status'] == 'failed' and row['status'] == 'failed'
                     and {v['code'] for v in row['violations']} == {'CP01'}, 'violating_lint_false_pass')
        _require(_snapshot(source) == before, 'lint_source_changed')
        _save_json(root / ('lint_' + name + '.json'), report)
        cases.append({'case': name, 'expected_outcome_confirmed': True, 'native_status': report['status'],
                      'source_unchanged': True, 'violation_codes': sorted({v['code'] for v in row['violations']})})
    return {'status': 'passed', 'execution_performed': True, 'cases': cases}


def qualify(distribution, executable, driver_path, output, *, execute=False):
    _require(distribution in ('dbt', 'dbt_oss'), 'unsupported_distribution')
    selection = {'distribution': distribution, 'version': VERSION}
    report = {'schema_version': 1, 'kind': 'native_dbt_feature_qualification', 'selection': selection,
              'status': 'not_run', 'execution_performed': False, 'warehouse_validation': 'not_run',
              'scope': 'synthetic_local_checks_information_schema_and_distribution_specific_lint',
              'limitations': ['Synthetic local qualification only; no target-warehouse, data, security or business acceptance.',
                             'Checks inspect metadata; they do not establish data correctness or warehouse execution.',
                             'Runtime hashes associate local bytes; they do not authenticate the publisher.']}
    if not execute:
        return report
    _load_duckdb()  # Fail before native execution when the optional reader is absent.
    identity = runtime_identity(executable, selection)
    contract = driver_contract()
    driver = _driver_bytes(driver_path, contract)
    prepared = prepare_features({**selection, 'features': ['checks', 'information_schema']}, 'duckdb')
    _require({item['path'] for item in prepared['files']} == EXPECTED_CANDIDATES, 'candidate_denominator')
    _require(all(_sha(item['content'].encode()) == item['sha256'] for item in prepared['files']), 'candidate_hash')
    candidates = {item['path']: item['content'] for item in prepared['files']}
    root = _new_output(output)
    report.update(runtime_identity=identity, driver={key: contract[key] for key in ('adapter', 'version', 'platform', 'sha256')},
                  candidate_sha256={item['path']: item['sha256'] for item in prepared['files']}, scenarios=[])
    try:
        probe_home = root / 'probe_home'; probe_home.mkdir(mode=0o700)
        report['execution_performed'] = True
        code, version, _ = _execute([str(executable), '--version'], probe_home, root, 'version')
        _require(code == 0, 'version_probe_failed')
        report['observed_runtime'] = observed_version(version.decode('utf-8'), selection)
        for scenario, failure in SCENARIOS.items():
            report['scenarios'].append(_scenario(root, scenario, failure, candidates, executable,
                                                 distribution, driver, contract))
        report['native_lint'] = _lint_cases(root, executable, selection)
        _require(runtime_identity(executable, selection) == identity, 'runtime_changed')
        _require(_sha(_driver_bytes(driver_path, contract)) == contract['sha256'], 'driver_changed')
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error) if str(error).startswith('dbt.feature_qualification.') else 'qualification_step_failed:' + type(error).__name__
    _save_json(root / 'report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', required=True, choices=('dbt', 'dbt_oss'))
    parser.add_argument('--dbt', required=True, type=Path)
    parser.add_argument('--driver', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New private evidence directory outside this checkout')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = qualify(args.distribution, args.dbt, args.driver, args.output, execute=args.execute)
        print(json.dumps({'status': report['status'], 'execution_performed': report['execution_performed'],
                          'error': report.get('error')}, sort_keys=True))
        return 0 if report['status'] in ('passed', 'not_run') else 1
    except (ValueError, OSError):
        print('dbt.feature_qualification.failed_preflight', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
