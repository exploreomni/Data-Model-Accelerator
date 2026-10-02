"""Native full-project dbt-duckdb validation of the reviewed synthetic candidate."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from evaluator import ROOT, validate_raw, load_raw, connect, evaluate, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verifier', type=Path, default=ROOT.parents[2] / 'scripts/verify_dbt_evidence.py')
    args = parser.parse_args()
    runtime = ROOT / 'runtime'
    runtime.mkdir(exist_ok=True)
    evidence = ROOT / 'evidence'
    native_dir = evidence / 'native-build'
    native_dir.mkdir(parents=True, exist_ok=True)
    raw = json.loads((ROOT.parent / 'input/raw-data.json').read_text())
    tables = validate_raw(raw)
    db = runtime / 'DMA_RETAIL.duckdb'
    if db.exists():
        db.unlink()
    con = connect(db)
    load_raw(con, tables)
    con.close()
    # This reviewed verifier is a read-only evidence dependency, not customer code.
    helper = args.verifier.resolve(strict=True)
    sys.path.insert(0, str(helper.parent))
    from verify_dbt_evidence import snapshot_project, expected_nodes, verify
    snapshot = snapshot_project(ROOT / 'dbt')
    env = dict(os.environ, DBT_SEND_ANONYMOUS_USAGE_STATS='false', DO_NOT_TRACK='1', DMA_RETAIL_DB_PATH=str(db))
    prefix = [str(Path(sys.executable).parent / 'dbt'), '--no-use-colors', '--log-path', str(runtime / 'logs')]
    common = ['--project-dir', str(ROOT / 'dbt'), '--profiles-dir', str(ROOT / 'profiles'), '--target', 'local', '--target-path', str(runtime / 'dbt-target'), '--no-partial-parse']
    checks = []

    def run(name, args):
        started = datetime.now(timezone.utc).isoformat()
        cmd = prefix + args + common
        result = subprocess.run(cmd, env=env, text=True, capture_output=True, cwd=ROOT, timeout=120)
        finished = datetime.now(timezone.utc).isoformat()
        (native_dir / (name + '.txt')).write_text(result.stdout + result.stderr)
        record = {'id': name, 'command': cmd, 'exit_code': result.returncode, 'started_at': started, 'finished_at': finished, 'status': 'pass' if result.returncode == 0 else 'fail', 'evidence': 'native-build/' + name + '.txt'}
        checks.append(record)
        if result.returncode:
            raise RuntimeError(name + ' failed; retained diagnostics in ' + record['evidence'])
        return record

    def association(source, dest):
        shutil.copyfile(source, native_dir / dest)
        return {'path': dest, 'sha256': hashlib.sha256((native_dir / dest).read_bytes()).hexdigest()}

    run('native_preflight', ['parse'])
    preflight = association(runtime / 'dbt-target/manifest.json', 'preflight-manifest.json')
    expected = expected_nodes(json.loads((native_dir / preflight['path']).read_text()))
    build = run('native_full_build', ['build'])
    receipt = {
        'schema_version': 1, 'kind': 'native_dbt_build_evidence',
        'project_root': str(ROOT / 'dbt'), 'validation_scope': 'local',
        'expected_adapter_type': 'duckdb', 'expected_dbt_version': '1.12.4',
        'expected_target_name': 'local', 'project_snapshot': snapshot,
        'expected_node_ids': expected,
        'execution': {k: build[k] for k in ('exit_code', 'started_at', 'finished_at')},
        'preflight_manifest': preflight,
        'manifest': association(runtime / 'dbt-target/manifest.json', 'manifest.json'),
        'run_results': association(runtime / 'dbt-target/run_results.json', 'run-results.json')
    }
    receipt_path = native_dir / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    verified = verify(receipt_path)
    (native_dir / 'verification.json').write_text(json.dumps(verified, indent=2) + '\n')
    if not verified['evidence_complete']:
        raise RuntimeError('Native evidence association failed: ' + repr(verified['errors']))
    run('native_analysis_compile', ['compile', '--select', 'retail_fulfillment_summary'])
    compiled = runtime / 'dbt-target/compiled/retail_candidate/analyses/retail_fulfillment_summary.sql'
    association(compiled, 'report-analysis.sql')
    con = connect(db)
    gold = rows(con, 'SELECT * FROM DMA_RETAIL.GOLD.FCT_ORDER_LINE_FULFILLMENT ORDER BY TENANT_ID,ORDER_ID,LINE_ID')
    report = rows(con, 'SELECT * FROM (' + compiled.read_text() + ') r ORDER BY ORDER_MONTH,PRODUCT_ID')
    if con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='REPORTS'").fetchall():
        raise RuntimeError('Report context materialized upstream')
    con.close()
    native = {'gold': gold, 'report': report}
    if native != evaluate(raw, {}):
        raise RuntimeError('Native dbt output differs from template evaluator')
    (evidence / 'native-dbt-output.json').write_text(json.dumps(native, indent=2) + '\n')
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'environment': 'isolated native dbt-duckdb full build; no Snowflake/Omni execution', 'versions': {n: importlib.metadata.version(n) for n in ['dbt-core', 'dbt-duckdb', 'duckdb', 'jinja2']}, 'checks': checks, 'build_counts': verified['counts'], 'native_vs_evaluator': 'pass', 'report_placement': 'pass: downstream compiled analysis; no REPORTS model/relation', 'evidence_helper': {'path': str(helper), 'sha256': hashlib.sha256(helper.read_bytes()).hexdigest()}}
    (evidence / 'native-dbt-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
