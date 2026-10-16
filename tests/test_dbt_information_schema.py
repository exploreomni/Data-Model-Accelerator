"""Synthetic offline format tests, not qualification of a native dbt v2 build."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import dbt_information_schema as reader

try:
    import duckdb
except ImportError:
    duckdb = None


class DependencyTests(unittest.TestCase):
    def test_dependency_is_optional_and_missing_error_is_actionable(self):
        with patch.object(reader.importlib, 'import_module', side_effect=ImportError('private-path')):
            with self.assertRaisesRegex(reader.InformationSchemaError, 'dependency_missing_install_requirements_dbt_metadata') as caught:
                reader._load_duckdb()
        self.assertNotIn('private-path', str(caught.exception))

    def test_drifted_decoder_version_is_not_silently_accepted(self):
        class OtherVersion:
            __version__ = '0.0.0'
        with patch.object(reader.importlib, 'import_module', return_value=OtherVersion()):
            with self.assertRaisesRegex(reader.InformationSchemaError, 'unsupported_duckdb_version'):
                reader._load_duckdb()

    def test_import_requires_no_duckdb_and_never_installs_it(self):
        script = "import sys; sys.path.insert(0, sys.argv[1]); sys.modules['duckdb'] = None; import dbt_information_schema; print('imported')"
        result = subprocess.run([sys.executable, '-S', '-c', script, str(SCRIPTS)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'imported')

    def test_footer_original_duplicate_names_rejected_before_renaming(self):
        class Footer:
            def execute(self, *args):
                return self

            def fetchmany(self, limit):
                return [('schema', 2), ('unique_id', None), ('UNIQUE_ID', None)]
        with self.assertRaisesRegex(reader.InformationSchemaError, 'duplicate_column'):
            reader._validate_parquet_schema(Footer(), 'unused')


@unittest.skipUnless(duckdb is not None and duckdb.__version__ == reader.DUCKDB_VERSION,
                     'Optional pinned DuckDB metadata dependency unavailable; Parquet coverage not run')
class InformationSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dma-dbt-information-schema-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.project = self.root / 'project'
        self.snapshot = self.project / 'target/info_schema/v1'
        self.snapshot.mkdir(parents=True)
        self.connection = duckdb.connect()
        self.addCleanup(self.connection.close)
        self.models()

    def table(self, name, columns, rows):
        self.connection.execute('DROP TABLE IF EXISTS fixture')
        self.connection.execute('CREATE TABLE fixture (' + ','.join('"' + name + '" ' + kind for name, kind in columns) + ')')
        if rows:
            self.connection.executemany('INSERT INTO fixture VALUES (' + ','.join('?' for _ in columns) + ')', rows)
        destination = self.snapshot / (name + '.parquet')
        destination.unlink(missing_ok=True)
        self.connection.execute('COPY fixture TO ? (FORMAT PARQUET)', [str(destination)])
        return destination

    def models(self, rows=None):
        return self.table('dbt.models', [(n, 'VARCHAR') for n in (
            'unique_id', 'name', 'resource_type', 'original_file_path', 'database_name',
            'schema_name', 'description', 'materialized', 'raw_code', 'config')], rows or [
                ('model.demo.customers', 'customers', 'model', 'models/customers.sql', 'analytics',
                 'mart', 'Customer records', 'table', 'select raw_secret from source', '{"password":"hidden-value"}'),
                ('model.demo.orders', 'orders', 'model', 'models/orders.sql', 'analytics',
                 'mart', 'Order records', 'view', '{{ unsafe_macro() }}', '{}'),
            ])

    def metadata(self):
        self.table('dbt.node_columns', [(n, 'VARCHAR') for n in (
            'node_unique_id', 'column_name', 'data_type_declared', 'data_type', 'description')], [
                ('model.demo.customers', 'id', 'integer', 'BIGINT', 'Customer key'),
                ('model.demo.orders', 'customer_id', None, 'BIGINT', 'Customer dependency'),
            ])
        self.table('dbt.edges', [('parent_unique_id', 'VARCHAR'), ('child_unique_id', 'VARCHAR')], [
            ('model.demo.customers', 'model.demo.orders')])
        self.table('dbt.column_lineage', [(n, 'VARCHAR') for n in (
            'from_node_unique_id', 'from_column_name', 'to_node_unique_id', 'to_column_name', 'lineage_kind')], [
                ('model.demo.customers', 'id', 'model.demo.orders', 'customer_id', 'copy')])

    def runtime(self, command='build', invocation='invocation-a'):
        self.table('dbt_rt.invocations', [('invocation_id', 'VARCHAR'), ('command', 'VARCHAR'),
                                         ('dbt_version', 'VARCHAR'), ('args', 'VARCHAR'), ('vars_override', 'VARCHAR')], [
            (invocation, command, '2.0.0', '--vars hidden-secret', '{"password":"hidden-value"}')])
        self.table('dbt_rt.run_results', [('unique_id', 'VARCHAR'), ('invocation_id', 'VARCHAR'),
                                         ('status', 'VARCHAR'), ('execution_time', 'DOUBLE'), ('message', 'VARCHAR')], [
            ('model.demo.orders', invocation, 'success', 1.25, 'password: hidden-value')])

    def read(self, stage='unknown'):
        return reader.read_information_schema(self.snapshot, source_root=self.project, stage=stage)

    def reject(self, suffix):
        with self.assertRaisesRegex(reader.InformationSchemaError, suffix):
            self.read()

    def test_normalizes_metadata_hashes_and_explicit_validation_limits(self):
        self.metadata(); self.runtime()
        report = self.read('build')
        self.assertEqual(report['models'][0]['name'], 'customers')
        self.assertEqual(report['columns'][1]['node_unique_id'], 'model.demo.orders')
        self.assertEqual(report['columns'][1]['data_type'], 'BIGINT')
        self.assertEqual(report['column_lineage'][0]['lineage_kind'], 'copy')
        self.assertEqual(report['runtime']['run_results'][0]['execution_time'], 1.25)
        self.assertEqual(report['evidence_stage'], 'runtime_metadata')
        self.assertFalse(report['stage_verified'])
        self.assertFalse(report['execution_performed'])
        self.assertEqual(report['warehouse_validation'], 'not_run')
        self.assertEqual(report['native_validation'], 'not_run')
        self.assertEqual(report['coverage']['export_completeness'], 'not_established')
        self.assertEqual(report['models'][0]['evidence']['locator'], 'row:1')
        for source in report['source_files']:
            self.assertEqual(source['sha256'], hashlib.sha256((self.snapshot / source['path']).read_bytes()).hexdigest())
        self.assertNotIn('foreign_key', json.dumps(report))
        self.assertEqual(report['coverage']['unresolved_node_ids'], [])

    def test_parse_never_exposes_compiled_or_runtime_claims(self):
        self.metadata(); self.runtime()
        report = self.read('parse')
        self.assertEqual(report['evidence_stage'], 'metadata_only')
        self.assertEqual(report['columns'][0]['data_type_declared'], 'integer')
        self.assertNotIn('data_type', report['columns'][0])
        self.assertEqual(report['column_lineage'], [])
        self.assertEqual(report['runtime'], {'invocations': [], 'run_results': []})
        self.assertEqual(len(report['coverage']['suppressed_tables']), 3)
        self.assertTrue(report['coverage']['compiled_fields_suppressed'])

    def test_build_declaration_alone_remains_metadata_only(self):
        report = self.read('build')
        self.assertEqual(report['evidence_stage'], 'metadata_only')
        self.assertFalse(report['stage_verified'])
        self.assertIn('dbt_rt.run_results', report['coverage']['missing_tables'])

    def test_native_aliases_preserved_and_normalized_without_guessing(self):
        self.table('dbt.node_columns', [(n, 'VARCHAR') for n in (
            'unique_id', 'column_name', 'declared_type', 'inferred_type', 'catalog_type', 'data_type')], [
                ('model.demo.orders', 'amount', 'numeric', 'DECIMAL(9,2)', None, 'DECIMAL(9,2)')])
        report = self.read('compile')
        column = report['columns'][0]
        self.assertEqual(column['unique_id'], column['node_unique_id'])
        self.assertEqual(column['declared_type'], column['data_type_declared'])
        self.assertEqual(report['evidence_stage'], 'compiled_metadata')
        parsed = self.read('parse')['columns'][0]
        self.assertNotIn('inferred_type', parsed)
        self.assertNotIn('catalog_type', parsed)

    def test_observed_public_v1_lineage_and_type_names_are_preserved(self):
        self.table('dbt.node_columns', [(n, 'VARCHAR') for n in (
            'node_unique_id', 'column_name', 'data_type_declared', 'data_type_inferred', 'data_type_actual', 'data_type')], [
                ('model.demo.customers', 'id', 'integer', 'INTEGER', None, 'INTEGER'),
                ('model.demo.orders', 'customer_id', 'integer', 'INTEGER', None, 'INTEGER')])
        self.table('dbt.column_lineage', [(n, 'VARCHAR') for n in (
            'parent_node_unique_id', 'parent_column_name', 'child_node_unique_id', 'child_column_name', 'evolution')], [
                ('model.demo.customers', 'id', 'model.demo.orders', 'customer_id', 'copy')])
        report = self.read('compile')
        row = report['column_lineage'][0]
        self.assertEqual(row['from_node_unique_id'], row['parent_node_unique_id'])
        self.assertEqual(row['to_column_name'], row['child_column_name'])
        self.assertEqual(row['evolution'], 'copy')
        self.assertEqual(report['columns'][0]['data_type_inferred'], 'INTEGER')
        self.assertEqual(report['coverage']['unresolved_columns'], [])
        parsed = self.read('parse')
        self.assertNotIn('data_type_inferred', parsed['columns'][0])
        self.assertNotIn('data_type_actual', parsed['columns'][0])

    def test_inner_schema_version_cannot_contradict_v1_directory(self):
        self.table('dbt.project', [('project_name', 'VARCHAR'), ('schema_version', 'BIGINT')], [('demo', 2)])
        self.reject('unsupported_schema_version')

    def test_lineage_alias_conflicts_rejected(self):
        self.table('dbt.column_lineage', [(n, 'VARCHAR') for n in (
            'parent_node_unique_id', 'parent_column_name', 'child_node_unique_id', 'child_column_name', 'from_node_unique_id')], [
                ('model.demo.customers', 'id', 'model.demo.orders', 'customer_id', 'model.other.customers')])
        self.reject('conflicting_lineage_identity')

    def test_missing_and_unknown_files_explicit_and_secret_fields_excluded(self):
        self.runtime()
        for table in ('dbt.project_vars', 'dbt.project_env_vars', 'dbt_rt.adapter_queries'):
            self.table(table, [('secret', 'VARCHAR')], [('password: hidden-value',)])
        (self.snapshot / 'views.sql').write_text("COPY (SELECT 1) TO '/tmp/must-not-run'")
        report = self.read()
        serialized = json.dumps(report)
        for secret in ('hidden-value', 'hidden-secret', 'raw_secret', 'unsafe_macro', 'must-not-run'):
            self.assertNotIn(secret, serialized)
        self.assertEqual(sum(f['status'] == 'excluded_not_allowlisted' for f in report['source_files']), 4)
        self.assertIn('dbt.node_columns', report['coverage']['missing_tables'])

    def test_sensitive_allowed_description_rejected_without_echo(self):
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR'), ('description', 'VARCHAR')], [
            ('model.demo.customers', 'customers', 'api_key: VERY_PRIVATE_VALUE')])
        with self.assertRaisesRegex(reader.InformationSchemaError, 'sensitive_or_unscannable_metadata') as caught:
            self.read()
        self.assertNotIn('VERY_PRIVATE_VALUE', str(caught.exception))

    def test_allowed_description_encoded_secret_is_detected(self):
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR'), ('description', 'VARCHAR')], [
            ('model.demo.customers', 'customers', 'data:text/plain;base64,cGFzc3dvcmQ6IHByaXZhdGUtdmFsdWU=')])
        self.reject('sensitive_or_unscannable_metadata')

    def test_unrecognized_command_line_never_leaks_vars(self):
        self.runtime(command='build --vars password: PRIVATE_VALUE')
        report = self.read()
        self.assertNotIn('PRIVATE_VALUE', json.dumps(report))
        self.assertNotIn('command', report['runtime']['invocations'][0])

    def test_empty_tables_are_distinct_from_missing(self):
        self.table('dbt.edges', [('parent_unique_id', 'VARCHAR'), ('child_unique_id', 'VARCHAR')], [])
        report = self.read()
        self.assertIn('dbt.edges', report['coverage']['empty_tables'])
        self.assertNotIn('dbt.edges', report['coverage']['missing_tables'])

    def test_unresolved_references_reported_and_not_invented(self):
        self.table('dbt.edges', [('parent_unique_id', 'VARCHAR'), ('child_unique_id', 'VARCHAR')], [
            ('source.unknown.raw.events', 'model.demo.orders')])
        self.runtime()
        (self.snapshot / 'dbt_rt.invocations.parquet').unlink()
        report = self.read()
        self.assertEqual(report['coverage']['unresolved_node_ids'], ['source.unknown.raw.events'])
        self.assertEqual(report['coverage']['unresolved_invocation_ids'], ['invocation-a'])
        self.assertEqual(len(report['sources']), 0)

    def test_missing_column_lineage_endpoints_are_gaps(self):
        self.metadata()
        (self.snapshot / 'dbt.node_columns.parquet').unlink()
        report = self.read()
        self.assertEqual(len(report['coverage']['unresolved_columns']), 2)

    def test_mixed_invocations_explicit_and_not_merged(self):
        self.runtime()
        self.table('dbt_rt.invocations', [('invocation_id', 'VARCHAR'), ('command', 'VARCHAR')], [
            ('invocation-a', 'build'), ('invocation-b', 'run')])
        self.assertTrue(self.read()['coverage']['mixed_invocations'])

    def test_parse_invocation_cannot_have_runtime_results(self):
        self.runtime(command='parse')
        self.reject('parse_invocation_has_run_results')

    def test_unknown_stage_with_parse_invocation_cannot_claim_compiled_metadata(self):
        self.metadata(); self.runtime(command='parse')
        (self.snapshot / 'dbt_rt.run_results.parquet').unlink()
        self.reject('parse_invocation_has_compiled_metadata')

    def test_duplicate_resource_and_runtime_identifiers_rejected(self):
        row = ('model.demo.orders', 'orders')
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR')], [row, row])
        self.reject('duplicate_identity')
        self.models(); self.runtime()
        self.table('dbt_rt.run_results', [('unique_id', 'VARCHAR'), ('invocation_id', 'VARCHAR')], [
            ('model.demo.orders', 'invocation-a'), ('model.demo.orders', 'invocation-a')])
        self.reject('duplicate_identity')

    def test_cross_resource_conflicts_rejected(self):
        self.table('dbt.sources', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR')], [('model.demo.orders', 'orders')])
        self.reject('conflicting_resource_identity')

    def test_conflicting_aliases_rejected(self):
        self.table('dbt.node_columns', [('unique_id', 'VARCHAR'), ('node_unique_id', 'VARCHAR'), ('column_name', 'VARCHAR')], [
            ('model.demo.orders', 'model.demo.customers', 'id')])
        self.reject('conflicting_column_node_id')

    def test_missing_required_column_null_id_and_nested_values_rejected(self):
        self.table('dbt.models', [('name', 'VARCHAR')], [('orders',)])
        self.reject('missing_required_column')
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR')], [(None, 'orders')])
        self.reject('missing_required_value')
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR'), ('description', 'STRUCT(secret VARCHAR)')], [
            ('model.demo.orders', 'orders', {'secret': 'hidden'})])
        self.reject('invalid_column_type')

    def test_nan_negative_runtime_and_boolean_numeric_rejected(self):
        self.runtime()
        for value in (float('nan'), float('inf'), -1.0):
            self.table('dbt_rt.run_results', [('unique_id', 'VARCHAR'), ('invocation_id', 'VARCHAR'), ('execution_time', 'DOUBLE')], [
                ('model.demo.orders', 'invocation-a', value)])
            self.reject('invalid_number')
        self.table('dbt_rt.run_results', [('unique_id', 'VARCHAR'), ('invocation_id', 'VARCHAR'), ('execution_time', 'BOOLEAN')], [
            ('model.demo.orders', 'invocation-a', True)])
        self.reject('invalid_column_type')

    def test_path_traversal_remote_and_symlink_sources_rejected(self):
        for bad in ('https://example.invalid/v1', str(self.snapshot / '..' / 'v1')):
            with self.assertRaises(reader.InformationSchemaError):
                reader.read_information_schema(bad)
        alias = self.root / 'v1'; alias.symlink_to(self.snapshot)
        with self.assertRaises(reader.InformationSchemaError):
            reader.read_information_schema(alias)
        (self.snapshot / 'linked.parquet').symlink_to(self.snapshot / 'dbt.models.parquet')
        self.reject('unsafe_file')

    def test_source_boundary_and_metadata_traversal_rejected(self):
        elsewhere = self.root / 'elsewhere'; elsewhere.mkdir()
        with self.assertRaisesRegex(reader.InformationSchemaError, 'snapshot_outside_source'):
            reader.read_information_schema(self.snapshot, source_root=elsewhere)
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR'), ('original_file_path', 'VARCHAR')], [
            ('model.demo.orders', 'orders', '../../profiles.yml')])
        self.reject('unsafe_metadata_path')

    def test_version_mismatch_and_nested_directory_rejected(self):
        new = self.snapshot.with_name('v2'); self.snapshot.rename(new)
        with self.assertRaisesRegex(reader.InformationSchemaError, 'unsupported_version_directory'):
            reader.read_information_schema(new)
        new.rename(self.snapshot)
        (self.snapshot / 'nested').mkdir()
        self.reject('unsafe_file')

    def test_malformed_and_forged_parquet_rejected_with_safe_errors(self):
        path = self.snapshot / 'dbt.models.parquet'
        for raw in (b'password: NEVER_ECHO_THIS', b'PAR1bad!' + struct.pack('<I', 4) + b'PAR1',
                    b'PAR1bad!' + struct.pack('<I', reader.MAX_FOOTER_BYTES + 1) + b'PAR1'):
            path.write_bytes(raw)
            with self.assertRaises(reader.InformationSchemaError) as caught:
                self.read()
            self.assertNotIn('NEVER_ECHO_THIS', str(caught.exception))

    def test_row_file_byte_and_expanded_bounds(self):
        with patch.object(reader, 'MAX_ROWS', 1):
            self.reject('row_limit')
        with patch.object(reader, 'MAX_FILES', 0):
            self.reject('file_limit')
        with patch.object(reader, 'MAX_TOTAL_BYTES', 1):
            self.reject('byte_limit')
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR'), ('description', 'VARCHAR')], [
            ('model.demo.orders', 'orders', 'a' * 100000)])
        with patch.object(reader, 'MAX_EXPANDED_BYTES', 1000):
            self.reject('expanded_byte_limit')

    def test_oversized_projected_json_rejected_even_if_parquet_is_tiny(self):
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR')], [
            ('model.demo.item' + str(i), 'item') for i in range(100)])
        self.assertLess((self.snapshot / 'dbt.models.parquet').stat().st_size, 8000)
        with patch.object(reader, 'MAX_PROJECTED_BYTES', 8000):
            self.reject('projected_byte_limit')

    def test_oversized_allowed_value_and_lists_rejected(self):
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR'), ('description', 'VARCHAR')], [
            ('model.demo.orders', 'orders', 'x' * (reader.MAX_VALUE_BYTES + 1))])
        self.reject('value_limit')
        self.table('dbt.models', [('unique_id', 'VARCHAR'), ('name', 'VARCHAR'), ('tags', 'VARCHAR[]')], [
            ('model.demo.orders', 'orders', ['tag'] * (reader.MAX_LIST_ITEMS + 1))])
        self.reject('invalid_list_or_limit')

    def test_decoder_cannot_read_other_paths_or_load_extensions(self):
        raw = (self.snapshot / 'dbt.models.parquet').read_bytes()
        with reader._decoder(duckdb, raw) as (connection, path):
            for setting in ('enable_external_access', 'autoload_known_extensions', 'autoinstall_known_extensions'):
                self.assertFalse(connection.execute("SELECT current_setting(?)", [setting]).fetchone()[0])
            with self.assertRaises(Exception):
                connection.execute('SELECT * FROM read_parquet(?)', [str(self.snapshot / 'dbt.models.parquet')]).fetchall()
            with self.assertRaises(Exception):
                connection.execute('SELECT * FROM read_parquet(?)', ['https://example.invalid/data.parquet']).fetchall()
            with self.assertRaises(Exception):
                connection.execute("SET enable_external_access = true")

    def test_source_bytes_and_permissions_unchanged_by_success_or_failure(self):
        before = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in self.snapshot.iterdir()}
        self.read()
        with patch.object(reader, 'MAX_ROWS', 1):
            self.reject('row_limit')
        after = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in self.snapshot.iterdir()}
        self.assertEqual(before, after)

    def test_scan_receipt_binds_exact_pre_receipt_projection_format(self):
        report = self.read()
        scan = report.pop('sensitivity_scan')
        self.assertEqual(scan['projection_sha256'], hashlib.sha256(reader._output_bytes(report)).hexdigest())
        self.assertEqual(scan['scope'], 'exact_projection_before_scan_receipt')

    def test_cli_writes_exclusive_private_output_outside_source(self):
        out = self.root / 'metadata.json'
        args = [str(self.snapshot), '--source-root', str(self.project), '--output', str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(reader.main(args), 0)
        original = out.read_bytes()
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        self.assertEqual(json.loads(original)['kind'], 'dbt_information_schema')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(reader.main(args), 1)
        self.assertEqual(out.read_bytes(), original)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(reader.main(args[:-1] + [str(self.project / 'must-not-write.json')]), 1)
        self.assertFalse((self.project / 'must-not-write.json').exists())

    def test_cli_failure_leaves_no_output_and_missing_dependency_is_honest(self):
        out = self.root / 'metadata.json'
        args = [str(self.snapshot), '--source-root', str(self.project), '--output', str(out)]
        error = io.StringIO()
        with patch.object(reader.importlib, 'import_module', side_effect=ImportError()), contextlib.redirect_stderr(error):
            self.assertEqual(reader.main(args), 1)
        self.assertIn('dependency_missing', error.getvalue())
        self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
