"""Synthetic read-only readiness checks; never execute repository content."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import platform_readiness as readiness


class PlatformReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def assess(self, framework='dbt', warehouse='snowflake', **options):
        return readiness.assess_repository(self.repo, framework, warehouse, **options)

    def ids(self, result):
        return {item['id'] for item in result['findings']}

    def test_raw_only_csv_has_metadata_but_no_native_or_business_authority(self):
        path = self.write('raw/orders.csv', 'id,amount,note\n001,9.001,PRIVATE_SENTINEL\n')
        result = self.assess(None, None)
        self.assertEqual([s['type'] for s in result['detected_sources']], ['raw_csv'])
        item = result['raw_csv_inventory'][0]
        self.assertEqual(item['row_count'], 1)
        self.assertEqual(item['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(item['source_owner'], 'raw_csv')
        self.assertTrue(item['metadata_complete'])
        self.assertFalse(item['native_types_verified'])
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertEqual(result['selection'], {'framework': None, 'warehouse': None})
        self.assertFalse(result['execution_performed'])
        self.assertIn('source.raw_csv_snapshot', self.ids(result))
        self.assertNotIn('source.unrecognized', self.ids(result))

    def test_dbt_seed_csv_owned_by_actual_project_and_cell_content_never_routes(self):
        self.write('project/dbt_project.yml', 'name: demo\nseed-paths: [custom]\n')
        self.write('project/custom/seed.csv', 'value\n"adapter: snowflake"\n')
        result = self.assess()
        self.assertEqual([s['type'] for s in result['detected_sources']], ['dbt'])
        self.assertEqual(result['raw_csv_inventory'][0]['source_owner'], 'dbt')
        self.assertNotIn('adapter: snowflake', json.dumps(result))

    def test_csv_invalid_utf8_duplicate_headers_and_ragged_rows_block_complete_inventory(self):
        self.write('duplicate.csv', 'id,id\n1,2\n')
        self.write('ragged.csv', 'id,value\n1\n')
        (self.repo / 'encoding.csv').write_bytes(b'id\n\xff')
        result = self.assess()
        self.assertFalse(result['coverage']['complete'])
        reasons = {g['reason'] for g in result['coverage']['gaps']}
        self.assertTrue({'raw_csv_duplicate_headers', 'raw_csv_ragged_rows', 'raw_csv_unsupported_encoding'} <= reasons)
        self.assertEqual(result['capabilities']['execution']['status'], 'blocked')
        self.assertEqual([s['type'] for s in result['detected_sources']], ['raw_csv'])

    def test_csv_size_and_symlink_bounds_are_not_bypassed(self):
        self.write('large.csv', 'id\n' + 'x\n' * 30)
        outside = self.root / 'outside.csv'
        outside.write_text('id\nPRIVATE_OUTSIDE\n')
        (self.repo / 'linked.csv').symlink_to(outside)
        result = self.assess(max_file_bytes=8)
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual([x['path'] for x in result['raw_csv_inventory']], ['large.csv', 'linked.csv'])
        self.assertTrue(all(x['sha256'] is None and x['row_count'] is None and not x['metadata_complete']
                            for x in result['raw_csv_inventory']))
        self.assertEqual([s['type'] for s in result['detected_sources']], ['raw_csv'])
        self.assertTrue({'file_size_limit', 'symlink_not_followed'} <= {g['reason'] for g in result['coverage']['gaps']})
        self.assertNotIn('PRIVATE_OUTSIDE', json.dumps(result))

    def test_mixed_multidomain_project_reports_configuration_without_execution(self):
        self.write('commerce/dbt_project.yml', "name: commerce\nflags:\n  maximum_seed_size_mib: 2\non-run-start: '{{ dangerous() }}'\nrequire-dbt-version: '>=1.11'\n")
        self.write('commerce/packages.yml', 'packages:\n  - package: some/package\n')
        self.write('commerce/models/orders.sql', "{{ config(materialized='incremental', incremental_strategy='merge', post_hook='dangerous') }}\nselect {{ var('day') }} from {{ ref('source') }} where {{ env_var('DBT_ENV_SECRET_TOKEN') }}\n{% if is_incremental() %} where changed {% endif %}\n")
        self.write('commerce/macros/run.sql', "{% macro dangerous() %}{{ run_query('delete from t') }}{{ adapter.dispatch('f') }}{% endmacro %}")
        self.write('commerce/models/schema.yml', 'unit_tests:\n  - name: example\nfunctions:\n  - name: f\n')
        self.write('commerce/snapshots/history.yml', 'snapshots:\n  - name: history\n')
        self.write('commerce/.github/workflows/ci.yml', 'run: dbt build --select modified --defer --state old\n')
        self.write('finance/databricks.yml', 'bundle:\n  name: finance\n')
        self.write('reporting/workflow_settings.yaml', 'defaultProject: example\ndefaultDataset: reporting\n')
        before = {str(p.relative_to(self.repo)): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        with patch('subprocess.run', side_effect=AssertionError('must never execute')):
            result = self.assess()
        expected = {'dbt.flags', 'dbt.hooks', 'dbt.packages', 'dbt.vars', 'dbt.environment', 'dbt.incremental',
                    'dbt.dispatch', 'dbt.introspection', 'dbt.unit_tests', 'dbt.functions', 'dbt.snapshots', 'dbt.macros', 'dbt.selection'}
        self.assertTrue(expected <= self.ids(result))
        self.assertEqual({s['type'] for s in result['detected_sources']}, {'dbt', 'databricks', 'bigquery', 'generic_sql'})
        self.assertEqual(result['selection'], {'framework': 'dbt', 'warehouse': 'snowflake'})
        self.assertEqual(result['capabilities']['generation']['status'], 'agent_assisted')
        self.assertEqual(result['capabilities']['execution']['status'], 'blocked')
        self.assertFalse(result['execution_performed'])
        self.assertFalse(result['native_semantics_parsed'])
        self.assertNotIn('dangerous()', json.dumps(result))
        self.assertEqual(before, {str(p.relative_to(self.repo)): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()})

    def test_sources_never_choose_framework_or_warehouse(self):
        self.write('dbt_project.yml', 'name: example\n')
        result = self.assess(None, None)
        self.assertEqual(result['selection'], {'framework': None, 'warehouse': None})
        self.assertEqual({q['id'] for q in result['questions']}, {'framework', 'warehouse'})
        self.assertEqual(result['capabilities']['generation']['status'], 'needs_selection')

    def test_gcp_is_question_not_bigquery_alias(self):
        self.write('query.sql', 'select 1')
        result = self.assess('native_sql', 'gcp')
        self.assertEqual(result['selection']['warehouse'], 'gcp')
        self.assertEqual(result['questions'][0]['id'], 'warehouse')
        self.assertEqual(result['capabilities']['generation']['status'], 'needs_selection')
        self.assertNotIn('bigquery', {s['type'] for s in result['detected_sources']})

    def test_native_choices_never_claim_execution_qualification(self):
        self.write('query.sql', 'select 1')
        for framework in ('dbt', 'native_sql'):
            for warehouse in readiness.WAREHOUSES:
                result = self.assess(framework, warehouse)
                self.assertEqual(result['capabilities']['generation']['status'], 'agent_assisted')
                self.assertEqual(result['capabilities']['execution']['status'], 'requires_operator_validation')
                self.assertFalse(result['execution_performed'])

    def test_coalesce_requires_complete_native_contract_not_sql(self):
        self.write('query.sql', 'select 1')
        for warehouse in ('snowflake', 'databricks', 'bigquery'):
            result = self.assess('coalesce', warehouse)
            self.assertEqual(result['capabilities']['generation']['status'], 'requires_contract')
            self.assertIn('coalesce.native_contract', self.ids(result))
        self.write('native/Nodes/node.yml', 'id: native-node\nfileVersion: 1\n')
        self.write('native/data.yml', 'fileVersion: 1\n')
        self.write('native/locations.yml', 'locations: []\n')
        contract = {'warehouse': 'snowflake', 'project_format_version': '1', 'representative_paths': ['native/Nodes/node.yml'],
                    'node_ids': ['native-node'], 'column_ids': ['column-id'], 'node_types': ['stage'],
                    'storage_mappings': {'source': {'database': 'DEV', 'schema': 'SOURCE'}}}
        result = self.assess('coalesce', 'snowflake', coalesce_contract=contract)
        self.assertIn('coalesce', {s['type'] for s in result['detected_sources']})
        self.assertEqual(result['capabilities']['generation']['status'], 'agent_assisted')
        self.assertEqual(result['capabilities']['execution']['status'], 'requires_operator_validation')
        contract['representative_paths'] = ['../unread.yml']
        self.assertEqual(self.assess('coalesce', 'snowflake', coalesce_contract=contract)['capabilities']['generation']['status'], 'requires_contract')

    def test_new_warehouses_have_static_signals_and_no_inferred_cloud_identity(self):
        for warehouse in ('redshift', 'clickhouse', 'motherduck'):
            self.write(warehouse + '.yml', 'warehouse: ' + warehouse + '\n')
        self.write('local.yml', 'type: duckdb\n')
        result = self.assess(None, None)
        self.assertEqual({s['type'] for s in result['detected_sources']},
                         {'redshift', 'clickhouse', 'motherduck'})
        self.assertEqual(result['selection'], {'framework': None, 'warehouse': None})
        self.assertEqual(next(q['choices'] for q in result['questions'] if q['id'] == 'warehouse'), list(readiness.WAREHOUSES))
        self.assertFalse(result['execution_performed'])

    def test_coalesce_new_warehouses_cannot_be_unblocked_by_a_contract(self):
        self.write('native/node.yml', 'id: native-node\n')
        for warehouse in ('redshift', 'clickhouse', 'motherduck'):
            contract = {'warehouse': warehouse, 'project_format_version': '1',
                        'representative_paths': ['native/node.yml'], 'node_ids': ['node'],
                        'column_ids': ['column'], 'node_types': ['stage'], 'storage_mappings': {'SRC': {}}}
            result = self.assess('coalesce', warehouse, coalesce_contract=contract)
            self.assertEqual(result['capabilities']['generation']['status'], 'unsupported')
            self.assertEqual(result['capabilities']['execution']['status'], 'blocked')
            self.assertIn('platform.unsupported_pairing', self.ids(result))
            self.assertFalse(result['platform_pairing']['native_qualified'])

    def test_credentials_never_opened_or_hashed(self):
        self.write('dbt_project.yml', 'name: example\n')
        for path in ('profiles.yml', 'profiles.production.yml', '.env', '.env.local', '.aws/config', '.databrickscfg', '.netrc', 'service_account.json', 'private-key.pem'):
            self.write(path, 'ULTRA_SECRET_SENTINEL')
        original = readiness._read_regular_file
        observed = []
        def safe_read(fd, name, maximum):
            observed.append(name)
            self.assertNotIn(name, {'profiles.yml', 'profiles.production.yml', '.env', '.env.local', 'config', '.databrickscfg', '.netrc', 'service_account.json', 'private-key.pem'})
            return original(fd, name, maximum)
        with patch.object(readiness, '_read_regular_file', side_effect=safe_read):
            result = self.assess()
        self.assertEqual(observed, ['dbt_project.yml'])
        self.assertNotIn('ULTRA_SECRET_SENTINEL', json.dumps(result))
        before = result['source_fingerprint']
        self.write('profiles.yml', 'DIFFERENT_SECRET')
        self.assertEqual(before, self.assess()['source_fingerprint'])
        self.assertIn('security.credentials_excluded', self.ids(result))
        with self.assertRaises(ValueError):
            self.assess(include_paths=['profiles.yml'])

    def test_content_fingerprint_portable_stable_and_sensitive_to_equal_size_drift(self):
        path = self.write('query.sql', 'select 1')
        before = self.assess()['source_fingerprint']
        os.utime(path, (1000000000, 1000000000))
        self.assertEqual(before, self.assess()['source_fingerprint'])
        copied = self.root / 'copy'
        shutil.copytree(self.repo, copied)
        self.assertEqual(before, readiness.assess_repository(copied, 'coalesce', 'bigquery')['source_fingerprint'])
        self.write('query.sql', 'select 2')
        self.assertNotEqual(before, self.assess()['source_fingerprint'])

    def test_symlinks_and_ancestor_symlinks_not_followed(self):
        external = self.root / 'external'
        external.mkdir()
        (external / 'secret.sql').write_text('NEVER_READ_ME')
        (self.repo / 'linked').symlink_to(external, target_is_directory=True)
        (self.repo / 'file.sql').symlink_to(external / 'secret.sql')
        result = self.assess()
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(result['coverage']['scanned_files'], 0)
        self.assertEqual(len(result['coverage']['gaps']), 2)
        self.assertNotIn('NEVER_READ_ME', json.dumps(result))
        alias = self.root / 'alias'
        alias.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(ValueError):
            readiness.assess_repository(alias, 'dbt', 'snowflake')

    def test_each_limit_retains_explicit_incomplete_coverage(self):
        self.write('a.sql', 'select 1')
        self.write('b.sql', 'select 2')
        self.write('nested/deep/c.sql', 'select 3')
        for options, reason in [({'max_files': 1}, 'file_count_limit'), ({'max_file_bytes': 1}, 'file_size_limit'),
                                ({'max_total_bytes': 9}, 'total_byte_limit'), ({'max_entries': 1}, 'directory_entry_limit'),
                                ({'max_depth': 1}, 'depth_limit')]:
            with self.subTest(reason=reason):
                result = self.assess(**options)
                self.assertFalse(result['source_fingerprint']['complete'])
                self.assertIn(reason, {gap['reason'] for gap in result['coverage']['gaps']})
                self.assertEqual(result['capabilities']['assessment']['status'], 'partial')
                self.assertIn('coverage.incomplete', self.ids(result))

    def test_unreadable_file_preserved_as_gap_without_error_contents(self):
        self.write('read.sql', 'select 1')
        with patch.object(readiness, '_read_regular_file', side_effect=PermissionError('SECRET_ERROR_CONTENT')):
            result = self.assess()
        self.assertEqual(result['coverage']['gaps'], [{'path': 'read.sql', 'reason': 'unreadable_or_changed_path'}])
        self.assertNotIn('SECRET_ERROR_CONTENT', json.dumps(result))

    def test_manifest_exclusion_opt_in_and_version_provenance(self):
        self.write('dbt_project.yml', 'name: example\n')
        self.write('target/manifest.json', json.dumps({'metadata': {'dbt_schema_version': 'https://schemas.getdbt.com/dbt/manifest/v12.json', 'dbt_version': '1.11.0', 'adapter_type': 'snowflake'}}))
        result = self.assess()
        self.assertFalse(result['coverage']['complete'])
        result = self.assess(include_paths=['target/manifest.json'])
        self.assertTrue(result['coverage']['complete'])
        self.assertTrue({'dbt.artifact_version', 'dbt.artifact_provenance'} <= self.ids(result))
        self.assertIn('requested_include_not_observed', {g['reason'] for g in self.assess(include_paths=['missing.json'])['coverage']['gaps']})

    def test_generated_file_include_does_not_read_siblings(self):
        self.write('target/manifest.json', '{}')
        self.write('target/large.sql', 'TOO_LARGE_TO_READ' * 10)
        result = self.assess(include_paths=['target/manifest.json'], max_file_bytes=20)
        self.assertTrue(result['coverage']['complete'])
        self.assertEqual(result['coverage']['scanned_files'], 1)
        self.assertIn({'path': 'target/large.sql', 'reason': 'generated_evidence_not_selected'}, result['coverage']['exclusions'])

    def test_file_swapped_to_symlink_between_stat_and_open_is_not_read(self):
        victim = self.write('query.sql', 'select 1')
        external = self.root / 'outside.sql'
        external.write_text('OUTSIDE_SENTINEL')
        original = readiness._read_regular_file
        def swap(fd, name, maximum):
            victim.unlink()
            victim.symlink_to(external)
            return original(fd, name, maximum)
        with patch.object(readiness, '_read_regular_file', side_effect=swap):
            result = self.assess()
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(result['coverage']['scanned_files'], 0)
        self.assertNotIn('OUTSIDE_SENTINEL', json.dumps(result))

    def test_manifest_dependencies_identified_without_source_project(self):
        self.write('manifest.json', json.dumps({'metadata': {'dbt_version': '1.12.4',
            'dbt_schema_version': 'https://schemas.getdbt.com/dbt/manifest/v12.json', 'project_name': 'demo', 'adapter_type': 'snowflake'},
            'nodes': {'model.external.x': {'package_name': 'external'}}, 'unit_tests': {'unit_test.x': {}}}))
        result = self.assess()
        self.assertTrue({'dbt.packages', 'dbt.unit_tests', 'dbt.artifact_provenance'} <= self.ids(result))
        self.assertEqual(result['capabilities']['execution']['status'], 'blocked')

    def test_generic_sql_never_guesses_snowflake(self):
        self.write('query.sql', 'select * from t qualify row_number() over () = 1;')
        result = self.assess()
        self.assertEqual([s['type'] for s in result['detected_sources']], ['generic_sql'])

    def test_invalid_options_and_paths_are_rejected(self):
        for options in ({'max_files': True}, {'max_depth': 0}, {'unknown': 1}, {'include_paths': ['../escape']}, {'include_paths': ['.git/config']}, {'include_paths': ['a/../b']}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.assess(**options)
        with self.assertRaises(ValueError):
            self.assess('unknown', 'snowflake')
        with self.assertRaises(ValueError):
            self.assess('dbt', 'gcp_bigquery')


if __name__ == '__main__':
    unittest.main()
