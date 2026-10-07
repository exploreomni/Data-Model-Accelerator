"""Execute reviewed bundled dbt candidates with a disclosed DuckDB overlay.

This runner accepts bundled synthetic cases only. It executes reviewed Jinja and
macros using actual dbt; it is neither an arbitrary repository sandbox nor a
Snowflake acceptance test. Source candidate files are never edited.
"""
import argparse
from collections import Counter
import copy
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import duckdb
import yaml
from verify_dbt_evidence import snapshot_project, expected_nodes, verify as verify_evidence

SKILL = Path(__file__).resolve().parents[1]
BASE_CHECKS = ('native_build_all_nodes', 'independent_fact_rows', 'development_schema_isolation',
               'documented_column_coverage', 'source_candidate_unchanged')
POWERBI_CHECKS = ('repeat_build', 'identical_replay', 'late_correction', 'tombstone',
                 'conflicting_version_rejected', 'raw_schema_drift_rejected',
                 'recovery_from_failed_build')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def hashes(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def normalize(value):
    if isinstance(value, dict):
        return {str(k).lower(): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def ordered(rows):
    return sorted(normalize(rows), key=lambda r: (r['tenant_id'], r['invoice_id']))


def verify_file_pins(repo, manifest_path, paths):
    """Reject accidental fixture drift before executing any of its dbt macros."""
    document = json.loads(manifest_path.read_text())
    pins = {item['path']: item['sha256'] for item in document['artifacts']}
    if len(pins) != len(document['artifacts']):
        raise ValueError('Duplicate fixture artifact pin')
    for path in paths:
        if path.resolve() != path.absolute():
            raise ValueError('Symlinked/noncanonical fixture input')
        name = path.relative_to(repo).as_posix()
        if name not in pins or digest(path) != pins[name]:
            raise ValueError('Bundled fixture changed from reviewed pin: ' + name)
    return digest(manifest_path)


def prepare(case_name, output):
    case = SKILL / 'examples' / (case_name + '-omni-e2e')
    source = case / 'target/dbt'
    input_paths = [case / 'input/raw-data.json', case / 'input/repo/adjustments.csv', case / 'expected/expected_rows.json']
    fixture_pin = verify_file_pins(case, case / 'fixture-pins.json',
        [p for p in source.rglob('*') if p.is_file()] + input_paths)
    project = output / 'project'
    shutil.copytree(source, project)
    # Two explicitly reviewed dialect differences, not a general translator.
    overlay = []
    for path in sorted(project.rglob('*.sql')):
        before = path.read_text()
        after, number_count = re.subn(r'\bNUMBER\(38,\s*0\)', 'DECIMAL(38,0)', before)
        after, date_count = re.subn(r"TO_CHAR\(VALID_FROM, 'YYYY-MM-DD'\)", "STRFTIME(VALID_FROM, '%Y-%m-%d')", after)
        after, month_count = re.subn(r"TO_CHAR\(m.INVOICE_MONTH, 'YYYY-MM-DD'\)", "STRFTIME(m.INVOICE_MONTH, '%Y-%m-%d')", after)
        if before != after:
            path.write_text(after)
            overlay.append({'path': path.relative_to(project).as_posix(), 'original_sha256': hashlib.sha256(before.encode()).hexdigest(), 'overlay_sha256': digest(path), 'number_to_decimal': number_count, 'iso_date_format': date_count, 'iso_month_format': month_count})
    project_name = yaml.safe_load((project / 'dbt_project.yml').read_text())['profile']
    sources = yaml.safe_load((project / 'models/sources.yml').read_text())['sources']
    database = sources[0]['database']
    if not re.fullmatch(r'DMA_[A-Z]+', database):
        raise ValueError('Unexpected bundled database identity')
    db_path = output / (database + '.duckdb')
    profiles = output / 'profiles'
    profiles.mkdir()
    profile = {project_name: {'target': 'qualification', 'outputs': {'qualification': {
        'type': 'duckdb', 'path': str(db_path), 'schema': 'DMA_QA', 'threads': 1,
        'settings': {'autoinstall_known_extensions': False, 'autoload_known_extensions': False},
    }}}}
    (profiles / 'profiles.yml').write_text(yaml.safe_dump(profile))
    raw = json.loads((case / 'input/raw-data.json').read_text())
    with (case / 'input/repo/adjustments.csv').open() as stream:
        adjustments = list(csv.DictReader(stream))
    for row in adjustments:
        row['ADJUSTMENT_CENTS'] = int(row['ADJUSTMENT_CENTS'])
    state = dict(case=case, project=project, output=output, profiles=profiles,
                 db_path=db_path, sources=sources, raw=raw, adjustments=adjustments,
                 original_hashes=hashes(source), overlay_hashes=hashes(project))
    write_json(output / 'overlay.json', {'origin': 'synthetic', 'fixture_manifest_sha256': fixture_pin, 'original_project_hashes': state['original_hashes'], 'executed_project_hashes': state['overlay_hashes'], 'changes': overlay,
        'scope': 'Native dbt Core/DuckDB with two explicit SQL substitutions; Snowflake remains unverified.'})
    write_json(output / 'input-pins.json', {p.relative_to(case).as_posix(): digest(p) for p in [case / 'input/raw-data.json', case / 'input/repo/adjustments.csv', case / 'expected/expected_rows.json']})
    return state


def load_raw(state, raw, adjustments):
    con = duckdb.connect(str(state['db_path']), config={'autoinstall_known_extensions': False, 'autoload_known_extensions': False})
    try:
        con.execute('CREATE SCHEMA IF NOT EXISTS RAW')
        for source in state['sources']:
            for table in source['tables']:
                name = table['identifier']
                columns = [(c['name'], c['data_type']) for c in table['columns']]
                for field, kind in columns:
                    if not re.fullmatch('[A-Z_]+', field) or not re.fullmatch(r'[A-Za-z0-9(), ]+', kind):
                        raise ValueError('Unexpected bundled column contract')
                con.execute('CREATE OR REPLACE TABLE RAW.' + name + ' (' + ','.join('"' + k + '" ' + t for k, t in columns) + ')')
                data = adjustments if name == 'ADJUSTMENTS' else raw[name]
                if data:
                    con.executemany('INSERT INTO RAW.' + name + ' VALUES (' + ','.join('?' for _ in columns) + ')', [[row[k] for k, _ in columns] for row in data])
    finally:
        con.close()


def dbt(state, label, command='build', extra=()):
    artifact = state['output'] / label
    artifact.mkdir()
    args = [str(Path(sys.executable).parent / 'dbt'), '--no-use-colors', '--no-send-anonymous-usage-stats', '--no-partial-parse', command,
        '--project-dir', str(state['project']), '--profiles-dir', str(state['profiles']),
        '--target', 'qualification', '--target-path', str(artifact / 'target'), '--log-path', str(artifact / 'logs'), *extra]
    before = hashes(state['project'])
    project_snapshot = snapshot_project(state['project'])
    con = duckdb.connect(str(state['db_path']), read_only=True)
    raw_snapshot = {}
    for source in state['sources']:
        for table in source['tables']:
            cur = con.execute('SELECT * FROM RAW.' + table['identifier'])
            raw_snapshot[table['identifier']] = {'columns': [c[0] for c in cur.description], 'rows': normalize(cur.fetchall())}
    con.close()
    write_json(artifact / 'raw-snapshot.json', raw_snapshot)
    started = datetime.now(timezone.utc).isoformat()
    env = dict(os.environ, DBT_SEND_ANONYMOUS_USAGE_STATS='false', DO_NOT_TRACK='1')
    try:
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=120)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
        code = 124
        stdout = decoded(error.stdout)
        stderr = decoded(error.stderr) + '\ndbt exceeded bounded local test timeout\n'
    finished = datetime.now(timezone.utc).isoformat()
    (artifact / 'stdout.txt').write_text(stdout)
    (artifact / 'stderr.txt').write_text(stderr)
    results_path = artifact / 'target/run_results.json'
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    manifest_path = artifact / 'target/manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    summary = {'command': command, 'exit_code': code, 'status_counts': dict(Counter(r['status'] for r in results.get('results', []))),
        'project_unchanged': before == hashes(state['project']), 'invocation_id': results.get('metadata', {}).get('invocation_id'),
        'manifest_sha256': digest(manifest_path) if manifest_path.exists() else None,
        'run_results_sha256': digest(results_path) if results_path.exists() else None,
        'failed_nodes': [{'unique_id': r['unique_id'], 'status': r['status'], 'failures': r.get('failures')} for r in results.get('results', []) if r['status'] not in ('success', 'pass')]}
    if command == 'build':
        expected = {uid for uid, node in manifest.get('nodes', {}).items() if node['resource_type'] in ('model', 'test', 'seed', 'snapshot') and node.get('config', {}).get('materialized') != 'ephemeral'}
        observed = [r['unique_id'] for r in results.get('results', [])]
        summary['denominator'] = len(expected)
        summary['complete_success'] = bool(expected) and set(observed) == expected and len(observed) == len(expected) and not summary['failed_nodes'] and code == 0 and summary['project_unchanged']
        if state.get('preflight') and manifest_path.exists() and results_path.exists():
            preflight_path = artifact / 'preflight-manifest.json'
            shutil.copyfile(state['preflight'], preflight_path)
            receipt = {'schema_version': 1, 'kind': 'native_dbt_build_evidence', 'project_root': str(state['project']),
                'validation_scope': 'local', 'expected_adapter_type': 'duckdb', 'expected_dbt_version': '1.12.4', 'expected_target_name': 'qualification',
                'project_snapshot': project_snapshot, 'expected_node_ids': expected_nodes(json.loads(preflight_path.read_text())),
                'execution': {'exit_code': code, 'started_at': started, 'finished_at': finished},
                'preflight_manifest': {'path': 'preflight-manifest.json', 'sha256': digest(preflight_path)},
                'manifest': {'path': 'target/manifest.json', 'sha256': digest(manifest_path)},
                'run_results': {'path': 'target/run_results.json', 'sha256': digest(results_path)}}
            write_json(artifact / 'receipt.json', receipt)
            verification = verify_evidence(artifact / 'receipt.json')
            write_json(artifact / 'evidence-verification.json', verification)
            summary['evidence_complete'] = verification['evidence_complete']
            summary['evidence_errors'] = verification['errors']
            summary['complete_success'] = summary['complete_success'] and verification['evidence_complete']
        else:
            summary['complete_success'] = False
    write_json(artifact / 'summary.json', summary)
    print(label + ': ' + json.dumps({k: v for k, v in summary.items() if k in ('exit_code', 'status_counts', 'complete_success')}), flush=True)
    return summary


def facts(state):
    con = duckdb.connect(str(state['db_path']), read_only=True)
    try:
        cur = con.execute('SELECT * FROM DMA_QA_GOLD.FCT_INVOICES')
        return ordered([dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()])
    finally:
        con.close()


def customer_months_match(actual, expected):
    """Compare all frozen Hex monthly fields plus two independently derived fields."""
    if not isinstance(actual, list) or not isinstance(expected, list) or len(actual) != len(expected):
        return False
    try:
        def identity(row, month):
            return row['tenant_id'], row['customer_id'], row[month]
        lookup = {identity(row, 'month'): row for row in expected}
        if len(lookup) != len(expected) or len({identity(row, 'invoice_month') for row in actual}) != len(actual):
            return False
        for row in actual:
            key = identity(row, 'invoice_month')
            wanted = lookup[key]
            if set(row) != (set(wanted) - {'month'}) | {'invoice_month', 'customer_month_key', 'outstanding_cents'}:
                return False
            if any(row['invoice_month' if name == 'month' else name] != value for name, value in wanted.items()):
                return False
            if row['customer_month_key'] != '|'.join(key) or row['outstanding_cents'] != wanted['net_cents'] - wanted['paid_cents']:
                return False
        return True
    except (KeyError, TypeError):
        return False


def column_coverage(state):
    inventory_path = state['case'] / 'documentation/model-inventory.json'
    inventory = json.loads(inventory_path.read_text())
    dictionary_path = state['case'] / 'documentation/data-dictionary.json'
    dictionary = json.loads(dictionary_path.read_text())
    definitions = {model['model_id']: {column['name'] for column in model['columns']} for model in dictionary['models']}
    con = duckdb.connect(str(state['db_path']), read_only=True)
    rows = con.execute("SELECT table_schema,table_name,column_name FROM information_schema.columns WHERE table_schema IN ('RAW','DMA_QA_SILVER','DMA_QA_GOLD') ORDER BY ordinal_position").fetchall()
    con.close()
    observed = {}
    for schema, table, column in rows:
        observed.setdefault((schema, table), []).append(column)
    comparisons = []
    expected_relations = set()
    for model in inventory['models']:
        _, schema, table = model['physical_name'].split('.')
        local_schema = 'DMA_QA_' + schema if schema in ('SILVER', 'GOLD') else schema
        identity = (local_schema, table)
        expected_relations.add(identity)
        actual = observed.get(identity)
        comparisons.append({'model_id': model['model_id'], 'expected_columns': model['columns'], 'actual_columns': actual,
            'passed': actual == model['columns'] and set(actual or []) == definitions.get(model['model_id'])})
    result = {'inventory_sha256': digest(inventory_path), 'dictionary_sha256': digest(dictionary_path),
        'dictionary_inventory_bound': dictionary['model_inventory_sha256'] == digest(inventory_path),
        'model_count': len(comparisons), 'column_count': sum(len(row['expected_columns']) for row in comparisons),
        'complete_relation_inventory': set(observed) == expected_relations, 'models': comparisons}
    result['passed'] = result['dictionary_inventory_bound'] and result['complete_relation_inventory'] and all(row['passed'] for row in comparisons)
    write_json(state['output'] / 'baseline/column-coverage.json', result)
    return result['passed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=['hex', 'tableau', 'powerbi'], default=['powerbi'])
    args = parser.parse_args()
    if len(args.cases) != len(set(args.cases)):
        parser.error('Each case can be selected only once')
    output = args.output.resolve()
    if output.exists() or output == SKILL or SKILL in output.parents:
        parser.error('Output must be a new directory outside the skill')
    output.mkdir(parents=True)
    check_ids = [name + ':' + check for name in args.cases for check in BASE_CHECKS]
    if 'powerbi' in args.cases:
        check_ids += ['powerbi:' + check for check in POWERBI_CHECKS]
    if 'hex' in args.cases:
        check_ids += ['hex:independent_customer_month_rows']
    checks = {name: {'id': name, 'passed': False, 'detail': 'not executed'} for name in check_ids}
    def check(name, passed, detail=None):
        if name not in checks:
            raise ValueError('Unregistered check ' + name)
        checks[name] = {'id': name, 'passed': bool(passed), 'detail': detail}
    for case_name in args.cases:
        state = prepare(case_name, output / case_name)
        load_raw(state, state['raw'], state['adjustments'])
        preflight = dbt(state, 'preflight', command='parse')
        if preflight['exit_code'] != 0:
            continue
        state['preflight'] = state['output'] / 'preflight/target/manifest.json'
        first = dbt(state, 'baseline')
        check(case_name + ':native_build_all_nodes', first.get('complete_success'))
        if not first.get('complete_success'):
            continue
        expected_path = state['case'] / 'expected/expected_rows.json'
        expected_document = json.loads(expected_path.read_text())
        expected = expected_document.get('invoices', expected_document.get('fct_invoices'))
        if expected is None:
            raise ValueError('Expected independent invoice rows missing')
        if case_name == 'hex':
            # The older independent oracle calls the date field "month" and
            # leaves the fixture's composite display key to its stated contract.
            expected = [dict({k: v for k, v in row.items() if k != 'month'},
                invoice_month=row['month'], invoice_key=row['tenant_id'] + '|' + row['invoice_id']) for row in expected]
        baseline = facts(state)
        check(case_name + ':independent_fact_rows', baseline == ordered(expected))
        write_json(state['output'] / 'baseline/fact_rows.json', baseline)
        con = duckdb.connect(str(state['db_path']), read_only=True)
        schemas = {row[0] for row in con.execute('SELECT schema_name FROM information_schema.schemata').fetchall()}
        con.close()
        check(case_name + ':development_schema_isolation', {'DMA_QA_SILVER', 'DMA_QA_GOLD'} <= schemas and not {'SILVER', 'GOLD'} & schemas)
        check(case_name + ':documented_column_coverage', column_coverage(state))
        check(case_name + ':source_candidate_unchanged', hashes(state['case'] / 'target/dbt') == state['original_hashes'])
        if case_name == 'hex':
            con = duckdb.connect(str(state['db_path']), read_only=True)
            cursor = con.execute('SELECT * FROM DMA_QA_GOLD.FCT_CUSTOMER_MONTH ORDER BY TENANT_ID,CUSTOMER_ID,INVOICE_MONTH')
            monthly = normalize([dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()])
            con.close()
            write_json(state['output'] / 'baseline/customer-month-rows.json', monthly)
            check('hex:independent_customer_month_rows', customer_months_match(monthly, expected_document['customer_months']))
        if case_name != 'powerbi':
            continue
        repeat = dbt(state, 'repeat')
        check('powerbi:repeat_build', repeat.get('complete_success') and facts(state) == baseline)
        replay = copy.deepcopy(state['raw'])
        for table in ('INVOICE_CDC', 'PAYMENT_CDC', 'CUSTOMER_HISTORY'):
            replay[table] *= 2
        load_raw(state, replay, state['adjustments'])
        duplicate = dbt(state, 'duplicate_replay')
        check('powerbi:identical_replay', duplicate.get('complete_success') and facts(state) == baseline)
        changed = copy.deepcopy(state['raw'])
        current = max((r for r in changed['INVOICE_CDC'] if r['TENANT_ID'] == 'A' and r['INVOICE_ID'] == 'I1'), key=lambda r: r['SEQUENCE'])
        correction = dict(current, SEQUENCE=current['SEQUENCE'] + 10, AMOUNT_CENTS=current['AMOUNT_CENTS'] + 123)
        changed['INVOICE_CDC'].append(correction)
        expected_changed = copy.deepcopy(baseline)
        for row in expected_changed:
            if (row['tenant_id'], row['invoice_id']) == ('A', 'I1'):
                for key in ('amount_cents', 'net_cents', 'outstanding_cents'):
                    row[key] += 123
        load_raw(state, changed, state['adjustments'])
        late = dbt(state, 'late_correction')
        check('powerbi:late_correction', late.get('complete_success') and facts(state) == expected_changed)
        # I6 is a draft with no dependent payment or adjustment in this fixture.
        deleted = copy.deepcopy(changed)
        current_draft = max((r for r in deleted['INVOICE_CDC'] if r['TENANT_ID'] == 'A' and r['INVOICE_ID'] == 'I6'), key=lambda r: r['SEQUENCE'])
        deleted['INVOICE_CDC'].append(dict(current_draft, SEQUENCE=current_draft['SEQUENCE'] + 10, IS_DELETED=True))
        load_raw(state, deleted, state['adjustments'])
        tombstone = dbt(state, 'tombstone')
        check('powerbi:tombstone', tombstone.get('complete_success') and facts(state) == [r for r in expected_changed if (r['tenant_id'], r['invoice_id']) != ('A', 'I6')])
        bad = copy.deepcopy(state['raw'])
        conflict = dict(bad['INVOICE_CDC'][0])
        conflict['AMOUNT_CENTS'] += 1
        bad['INVOICE_CDC'].append(conflict)
        load_raw(state, bad, state['adjustments'])
        failed = dbt(state, 'conflicting_version')
        check('powerbi:conflicting_version_rejected', failed['exit_code'] != 0 and any(r['unique_id'].endswith('.source_version_conflicts') and r['status'] == 'fail' for r in failed['failed_nodes']))
        load_raw(state, state['raw'], state['adjustments'])
        con = duckdb.connect(str(state['db_path']))
        con.execute('ALTER TABLE RAW.INVOICE_CDC DROP COLUMN AMOUNT_CENTS')
        con.close()
        drift = dbt(state, 'raw_schema_drift')
        drift_text = (state['output'] / 'raw_schema_drift/stdout.txt').read_text()
        check('powerbi:raw_schema_drift_rejected', drift['exit_code'] != 0 and any(r['status'] == 'error' for r in drift['failed_nodes']) and 'AMOUNT_CENTS' in drift_text)
        load_raw(state, state['raw'], state['adjustments'])
        recovered = dbt(state, 'recovery', extra=['--full-refresh'])
        check('powerbi:recovery_from_failed_build', recovered.get('complete_success') and facts(state) == baseline)
        check('powerbi:source_candidate_unchanged', hashes(state['case'] / 'target/dbt') == state['original_hashes'])
    report = {'schema_version': 1, 'origin': 'synthetic', 'captured_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'Native local dbt/DuckDB build qualification; explicit dialect overlay. No Snowflake, Omni, source-native or production approval claim.',
        'versions': {key: importlib.metadata.version(key) for key in ('dbt-core', 'dbt-duckdb', 'duckdb', 'PyYAML')},
        'checks': list(checks.values()), 'passed': sum(c['passed'] for c in checks.values()), 'total': len(checks),
        'status': 'pass' if checks and all(c['passed'] for c in checks.values()) else 'fail'}
    write_json(output / 'report.json', report)
    print(json.dumps({'status': report['status'], 'passed': report['passed'], 'total': report['total']}))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
