"""Strict native dbt receipt association tests with synthetic realistic artifacts.

These fixtures resemble documented artifacts; they do not claim a dbt process
or warehouse was executed. No optional dependencies are needed.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts/verify_dbt_evidence.py'
SPEC = importlib.util.spec_from_file_location('dbt_evidence_checker', SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def make_fixture(root):
    """Return receipt path with preflight, compiled and run artifacts under root."""
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    project = root / 'project'; project.mkdir()
    files = {
        'dbt_project.yml': 'name: billing\nversion: "1.0"\nconfig-version: 2\nprofile: qualification\n',
        'models/stg_invoice.sql': "{{ config(materialized='ephemeral') }}\nselect 1 as invoice_id\n",
        'models/fact.sql': "{{ config(materialized='table') }}\nselect invoice_id from {{ ref('stg_invoice') }}\n",
        'tests/grain.sql': "select invoice_id from {{ ref('fact') }} group by invoice_id having count(*) > 1\n",
        'models/schema.yml': 'version: 2\nmodels:\n  - name: fact\n    columns:\n      - name: invoice_id\n        data_tests: [not_null]\n',
        'models/sources.yml': 'version: 2\nsources:\n  - name: raw\n    tables:\n      - name: invoices\n',
        'macros/net.sql': '{% macro net(amount) %}{{ amount }}{% endmacro %}\n',
        'seeds/currencies.csv': 'currency\nUSD\nEUR\n',
        'snapshots/history.sql': "{% snapshot history %}\n{{ config(unique_key='invoice_id', strategy='check', check_cols='all') }}\nselect invoice_id from {{ ref('fact') }}\n{% endsnapshot %}\n",
    }
    for name, content in files.items():
        path = project / name; path.parent.mkdir(exist_ok=True, parents=True); path.write_text(content)
    started = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=2)
    iso = lambda offset: (started + timedelta(seconds=offset)).isoformat()
    metadata = {'dbt_schema_version': checker.MANIFEST_SCHEMA, 'dbt_version': checker.DBT_VERSION,
                'generated_at': iso(2), 'invocation_started_at': iso(1), 'invocation_id': '22222222-2222-4222-8222-222222222222',
                'adapter_type': 'duckdb', 'project_name': 'billing'}
    nodes = {}
    definitions = [
        ('model.billing.stg_invoice', 'model', 'models/stg_invoice.sql', {'materialized': 'ephemeral'}),
        ('model.billing.fact', 'model', 'models/fact.sql', {'materialized': 'table'}),
        ('seed.billing.currencies', 'seed', 'seeds/currencies.csv', {'materialized': 'seed'}),
        ('snapshot.billing.history', 'snapshot', 'snapshots/history.sql', {'materialized': 'snapshot'}),
        ('test.billing.grain', 'test', 'tests/grain.sql', {'severity': 'ERROR'}),
        ('test.billing.not_null_fact_invoice_id.abcdef', 'test', 'models/schema.yml', {'severity': 'ERROR'}),
    ]
    for uid, resource, path, config in definitions:
        text = files[path].strip()
        generic = path.endswith('.yml')
        raw = '{{ test_not_null(**_dbt_generic_test_kwargs) }}' if generic else text
        checksum = {'name': 'none', 'checksum': ''} if generic else {'name': 'sha256', 'checksum': hashlib.sha256((text if resource == 'seed' else ' '.join(text.split())).encode()).hexdigest()}
        node = {'unique_id': uid, 'resource_type': resource, 'package_name': 'billing',
                'original_file_path': path, 'checksum': checksum, 'raw_code': raw,
                'config': dict(config, enabled=True), 'compiled': resource != 'seed',
                'compiled_code': 'select 1 as invoice_id' if resource != 'seed' else None,
                'depends_on': {'nodes': [], 'macros': []}, 'database': 'qualification', 'schema': 'main', 'alias': uid.split('.')[2]}
        if generic:
            node['test_metadata'] = {'name': 'not_null', 'kwargs': {'model': "{{ ref('fact') }}", 'column_name': 'invoice_id'}, 'namespace': None}
        nodes[uid] = node
    manifest = {'metadata': metadata, 'nodes': nodes, 'sources': {
        'source.billing.raw.invoices': {'unique_id': 'source.billing.raw.invoices', 'package_name': 'billing', 'original_file_path': 'models/sources.yml', 'name': 'invoices', 'schema': 'RAW', 'created_at': 2}},
        'macros': {'macro.billing.net': {'unique_id': 'macro.billing.net', 'package_name': 'billing', 'original_file_path': 'macros/net.sql', 'macro_sql': files['macros/net.sql'].strip(), 'created_at': 2}}}
    preflight = copy.deepcopy(manifest)
    preflight['metadata'].update(invocation_id='11111111-1111-4111-8111-111111111111', generated_at=iso(-2), invocation_started_at=iso(-3))
    for node in preflight['nodes'].values():
        node['compiled'] = False; node.pop('compiled_code', None)
    # Creation timestamps change across fresh parses without changing semantics.
    for group in ('sources', 'macros'):
        for value in preflight[group].values(): value['created_at'] = 1
    expected = checker.expected_nodes(preflight)
    run_results = {'metadata': {'dbt_schema_version': checker.RESULTS_SCHEMA, 'dbt_version': checker.DBT_VERSION,
                              'invocation_id': metadata['invocation_id'], 'invocation_started_at': iso(1), 'generated_at': iso(10)},
                   'args': {'which': 'build', 'target': 'qualification', 'select': [], 'exclude': [], 'vars': {}, 'empty': False, 'defer': False},
                   'elapsed_time': 9.0, 'results': []}
    for uid in expected:
        node = nodes[uid]; test = node['resource_type'] == 'test'
        run_results['results'].append({'unique_id': uid, 'status': 'pass' if test else 'success',
            'timing': [{'name': 'execute', 'started_at': iso(3), 'completed_at': iso(8)}],
            'thread_id': 'Thread-1', 'execution_time': 5.0, 'adapter_response': {'_message': 'OK'},
            'message': None, 'failures': 0 if test else None, 'compiled': node['compiled'],
            'compiled_code': node['compiled_code'], 'relation_name': None, 'batch_results': None})
    snapshot = checker.snapshot_project(project); snapshot['captured_at'] = iso(-5)
    receipt = {'schema_version': 1, 'kind': 'native_dbt_build_evidence', 'project_root': str(project),
               'validation_scope': 'local', 'expected_adapter_type': 'duckdb', 'expected_dbt_version': checker.DBT_VERSION,
               'expected_target_name': 'qualification', 'project_snapshot': snapshot, 'expected_node_ids': expected,
               'execution': {'exit_code': 0, 'started_at': iso(0), 'finished_at': iso(12)}}
    for name, body in [('preflight_manifest', preflight), ('manifest', manifest), ('run_results', run_results)]:
        path = root / (name + '.json'); path.write_text(json.dumps(body, indent=2))
        receipt[name] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    path = root / 'receipt.json'; path.write_text(json.dumps(receipt, indent=2))
    return path


class DbtEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dma-dbt-evidence-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = make_fixture(self.root)
        self.receipt = json.loads(self.path.read_text())

    def check(self):
        self.path.write_text(json.dumps(self.receipt, indent=2))
        return checker.verify(self.path)

    def mutate(self, name, change, rehash=True):
        path = self.root / self.receipt[name]['path']
        value = json.loads(path.read_text()); change(value); path.write_text(json.dumps(value))
        if rehash:
            self.receipt[name]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def assert_incomplete(self, phrase=None):
        report = self.check(); self.assertFalse(report['evidence_complete'], report)
        if phrase: self.assertTrue(any(phrase in error for error in report['errors']), report)
        return report

    def test_full_native_receipt_matches_source_and_excludes_ephemeral_result(self):
        report = self.check()
        self.assertTrue(report['evidence_complete'], report)
        self.assertEqual(report['counts'], {'model': 1, 'seed': 1, 'snapshot': 1, 'test': 2, 'runnable_nodes': 5, 'project_files': 9})
        self.assertEqual(report['validation_scope'], 'local')
        self.assertIn('does not authenticate', ' '.join(report['limitations']))

    def test_warn_skip_fail_and_error_are_never_passes(self):
        for status in ('warn', 'skipped', 'fail', 'error', 'success'):
            with self.subTest(status=status):
                self.mutate('run_results', lambda data: next(r for r in data['results'] if r['unique_id'].startswith('test.')).update(status=status))
                self.assert_incomplete('did not pass')

    def test_pass_with_failures_or_boolean_failure_count_rejected(self):
        for failures in (1, None, False, -1):
            with self.subTest(failures=failures):
                self.mutate('run_results', lambda data: next(r for r in data['results'] if r['unique_id'].startswith('test.')).update(failures=failures))
                self.assert_incomplete('failures must be zero')

    def test_partial_results_missing_test_rejected(self):
        self.mutate('run_results', lambda data: data['results'].pop())
        self.assert_incomplete('denominator incomplete')

    def test_missing_from_both_denominators_cannot_hide_preflight_node(self):
        uid = self.receipt['expected_node_ids'].pop()
        self.mutate('run_results', lambda data: data.update(results=[r for r in data['results'] if r['unique_id'] != uid]))
        self.assert_incomplete('denominator mismatch')

    def test_duplicate_result_rejected(self):
        self.mutate('run_results', lambda data: data['results'].append(copy.deepcopy(data['results'][0])))
        self.assert_incomplete('Duplicate/unknown')

    def test_unknown_result_rejected(self):
        self.mutate('run_results', lambda data: data['results'][0].update(unique_id='model.other.surprise'))
        self.assert_incomplete('Duplicate/unknown')

    def test_empty_or_parse_output_rejected(self):
        self.mutate('run_results', lambda data: data['args'].update(which='parse'))
        self.assert_incomplete('dbt build')
        self.mutate('run_results', lambda data: (data['args'].update(which='build'), data.update(results=[])))
        self.assert_incomplete('empty')

    def test_selection_and_defer_never_claim_full_build(self):
        for option, value in [('select', ['fact']), ('exclude', ['grain']), ('selector', 'release'), ('resource_types', ['model']), ('state', '/prior'), ('vars', {'mode': 'other'}), ('empty', True), ('defer', True)]:
            with self.subTest(option=option):
                self.mutate('run_results', lambda data: data.update(args={'which': 'build', 'target': 'qualification', option: value}))
                self.assert_incomplete('build')

    def test_mismatched_invocations_rejected(self):
        self.mutate('run_results', lambda data: data['metadata'].update(invocation_id='unrelated'))
        self.assert_incomplete('invocation mismatch')

    def test_wrong_target_rejected(self):
        self.mutate('run_results', lambda data: data['args'].update(target='production'))
        self.assert_incomplete('target mismatch')

    def test_adapter_mismatch_and_local_duckdb_promotion_rejected(self):
        self.receipt['validation_scope'] = 'target'
        self.assert_incomplete('DuckDB')
        self.receipt['validation_scope'] = 'local'; self.receipt['expected_adapter_type'] = 'snowflake'
        self.assert_incomplete('adapter mismatch')

    def test_version_and_schema_mismatch_rejected(self):
        self.mutate('run_results', lambda data: data['metadata'].update(dbt_version='1.11.0'))
        self.assert_incomplete('version mismatch')

    def test_snapshot_taken_after_execution_rejected(self):
        self.receipt['project_snapshot']['captured_at'] = self.receipt['execution']['finished_at']
        self.assert_incomplete('chronology')

    def test_old_result_and_naive_timestamp_rejected(self):
        self.mutate('run_results', lambda data: data['metadata'].update(generated_at='2020-01-01T00:00:00Z'))
        self.assert_incomplete('Stale')
        self.mutate('run_results', lambda data: data['metadata'].update(generated_at='2020-01-01T00:00:00'))
        self.assert_incomplete('Naive')

    def test_nonzero_process_exit_rejected(self):
        self.receipt['execution']['exit_code'] = 1
        self.assert_incomplete('exit successfully')

    def test_changed_code_after_snapshot_rejected(self):
        (self.root / 'project/models/fact.sql').write_text('select 99 as invoice_id')
        self.assert_incomplete('drift')

    def test_rehashed_snapshot_cannot_hide_old_manifest_raw_code(self):
        path = self.root / 'project/models/fact.sql'; path.write_text('select 99 as invoice_id')
        next(f for f in self.receipt['project_snapshot']['files'] if f['path'] == 'models/fact.sql')['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assert_incomplete('checksum differs')

    def test_macro_yaml_and_config_drift_rejected(self):
        for name in ('macros/net.sql', 'models/schema.yml', 'models/sources.yml', 'dbt_project.yml'):
            with self.subTest(path=name):
                path = self.root / 'project' / name; original = path.read_bytes(); path.write_bytes(original + b'\n# changed\n')
                self.assert_incomplete('drift'); path.write_bytes(original)

    def test_added_and_removed_project_files_rejected(self):
        path = self.root / 'project/macros/new.sql'; path.write_text('{% macro surprise() %}1{% endmacro %}')
        self.assert_incomplete('drift'); path.unlink()
        self.receipt['project_snapshot']['files'].pop()
        self.assert_incomplete('drift')

    def test_manifest_semantics_cannot_change_after_preflight(self):
        self.mutate('manifest', lambda data: data['nodes']['model.billing.fact']['config'].update(materialized='view'))
        self.assert_incomplete('definition changed')

    def test_generic_test_definition_changes_caught_despite_checksum_none(self):
        uid = 'test.billing.not_null_fact_invoice_id.abcdef'
        self.mutate('manifest', lambda data: data['nodes'][uid]['test_metadata']['kwargs'].update(column_name='different'))
        self.assert_incomplete('definition changed')

    def add_native_test_wrapper(self):
        uid = 'macro.dbt.statement'
        macro = {'unique_id': uid, 'package_name': 'dbt', 'original_file_path': 'macros/etc/statement.sql', 'macro_sql': '{% macro statement() %}synthetic body{% endmacro %}'}
        for name in ('preflight_manifest', 'manifest'):
            self.mutate(name, lambda data: data['macros'].update({uid: copy.deepcopy(macro)}))
        self.mutate('manifest', lambda data: data['nodes']['test.billing.grain']['depends_on']['macros'].append(uid))

    def test_native_test_runtime_wrapper_addition_is_allowed(self):
        self.add_native_test_wrapper()
        self.assertTrue(self.check()['evidence_complete'])

    def test_changed_builtin_wrapper_does_not_qualify_as_runtime_only(self):
        self.add_native_test_wrapper()
        self.mutate('manifest', lambda data: data['macros']['macro.dbt.statement'].update(macro_sql='changed execution'))
        self.assert_incomplete('execution macro changed')

    def test_unknown_macro_or_source_dependency_addition_rejected(self):
        self.mutate('manifest', lambda data: data['nodes']['test.billing.grain']['depends_on']['nodes'].append('model.billing.unreviewed'))
        self.assert_incomplete('definition changed')
        self.mutate('manifest', lambda data: data['nodes']['test.billing.grain'].update(depends_on={'nodes': [], 'macros': ['macro.dbt.unknown']}))
        self.assert_incomplete('definition changed')

    def test_compile_only_timing_cannot_claim_successful_execution(self):
        self.mutate('run_results', lambda data: data['results'][0]['timing'][0].update(name='compile'))
        self.assert_incomplete('execution interval')

    def test_uncompiled_nodes_and_changed_executed_sql_rejected(self):
        self.mutate('manifest', lambda data: data['nodes']['model.billing.fact'].update(compiled=False))
        self.assert_incomplete('lacks compiled')
        self.mutate('manifest', lambda data: data['nodes']['model.billing.fact'].update(compiled=True))
        self.mutate('run_results', lambda data: next(r for r in data['results'] if r['unique_id'] == 'model.billing.fact').update(compiled_code='select 900'))
        self.assert_incomplete('Compiled execution code differs')

    def test_changed_raw_code_caught_even_if_source_checksum_unchanged(self):
        for name in ('preflight_manifest', 'manifest'):
            self.mutate(name, lambda data: data['nodes']['model.billing.fact'].update(raw_code='select changed'))
        self.assert_incomplete('raw_code differs')

    def test_raw_evidence_hash_drift_rejected(self):
        self.mutate('run_results', lambda data: data.update(elapsed_time=999), rehash=False)
        self.assert_incomplete('Changed evidence hash')

    def test_symlinked_evidence_project_and_escaped_paths_rejected(self):
        path = self.root / 'link.json'; path.symlink_to(self.root / 'manifest.json')
        self.receipt['manifest']['path'] = 'link.json'; self.assert_incomplete('Symlinked')
        self.receipt['manifest']['path'] = '../manifest.json'; self.assert_incomplete('within')
        self.receipt['manifest']['path'] = 'manifest.json'; link = self.root / 'project/macros/link.sql'; link.symlink_to(self.root / 'manifest.json')
        self.assert_incomplete('symlink')

    def test_credentials_are_not_read_or_copied_into_snapshot(self):
        (self.root / 'project/profiles.yml').write_text('password: synthetic-canary')
        report = self.assert_incomplete('Credential/profile')
        self.assertNotIn('synthetic-canary', json.dumps(report))

    def test_duplicate_json_and_invalid_shapes_fail_without_crashing(self):
        self.path.write_text('{"schema_version":1,"schema_version":1}')
        self.assertFalse(checker.verify(self.path)['evidence_complete'])
        self.receipt['expected_node_ids'] = {'invalid': True}
        self.assert_incomplete('Expected node IDs')

    def test_failed_microbatch_never_hides_behind_success_status(self):
        self.mutate('run_results', lambda data: data['results'][0].update(batch_results={'successful': [], 'failed': [['a', 'b']]}))
        self.assert_incomplete('microbatch failures')

    def test_cli_returns_success_and_nonzero_failure(self):
        command = [sys.executable, str(SCRIPT), str(self.path)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(json.loads(result.stdout)['evidence_complete'])
        self.receipt['execution']['exit_code'] = 1; self.path.write_text(json.dumps(self.receipt))
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)

    def test_relocated_identical_project_preserves_receipt_and_evidence(self):
        original = self.path.read_bytes()
        relocated = self.root / 'relocated'
        shutil.copytree(self.root / 'project', relocated)
        shutil.rmtree(self.root / 'project')
        report = checker.verify(self.path, project_root=relocated)
        self.assertTrue(report['evidence_complete'], report)
        self.assertEqual(report['declared_project_root'], self.receipt['project_root'])
        self.assertEqual(report['verified_project_root'], str(relocated))
        self.assertEqual(self.path.read_bytes(), original)
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.path), '--project-root', str(relocated)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_relocated_changed_project_does_not_rebase_hashes(self):
        relocated = self.root / 'relocated'; shutil.copytree(self.root / 'project', relocated)
        (relocated / 'models/fact.sql').write_text('select unreviewed from surprise')
        report = checker.verify(self.path, project_root=relocated)
        self.assertFalse(report['evidence_complete'])
        self.assertTrue(any('drift' in error for error in report['errors']))

    def test_relocation_never_rebases_evidence_associations(self):
        relocated = self.root / 'relocated'; shutil.copytree(self.root / 'project', relocated)
        (self.root / 'run_results.json').rename(relocated / 'run_results.json')
        report = checker.verify(self.path, project_root=relocated)
        self.assertFalse(report['evidence_complete'])


if __name__ == '__main__':
    unittest.main()
