"""Real local metadata tests using synthetic receipts, not native-build claims."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))

from ae_common import hash_file, snapshot
import capture_duckdb_schema as collector
from test_dbt_evidence import make_fixture
from verify_engagement import physical_denominator

HAS_DUCKDB = importlib.util.find_spec('duckdb') is not None
if HAS_DUCKDB:
    import duckdb


@unittest.skipUnless(HAS_DUCKDB, 'Optional local DuckDB dependency is not installed')
class DuckdbSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dma-schema-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.receipt_path = make_fixture(self.root)
        self.receipt = json.loads(self.receipt_path.read_text())
        self.project = self.root / 'project'
        self.database = self.root / 'qualification.duckdb'
        for name in ('preflight_manifest', 'manifest'):
            self.mutate_artifact(name, self.populate_native_relations)
        self.receipt_path.write_text(json.dumps(self.receipt))
        with duckdb.connect(str(self.database)) as connection:
            connection.execute('create schema "Raw ""Inbound"')
            connection.execute('create table "Raw ""Inbound"."Invoice ""Archive" ("Source ID" integer, amount decimal(18,4))')
            connection.execute('create table "Fact ""Daily" ("Invoice ID" integer, "Undocumented Note" varchar)')
            connection.execute('insert into "Fact ""Daily" values (17, \'unchanged source value\')')
            connection.execute('create table currencies (currency varchar)')
            connection.execute('create table history (invoice_id integer)')
        self.source_relation = '"qualification"."Raw ""Inbound"."Invoice ""Archive"'
        self.fact_relation = '"qualification"."main"."Fact ""Daily"'

    @staticmethod
    def populate_native_relations(manifest):
        manifest['nodes']['model.billing.fact']['alias'] = 'Fact "Daily'
        source = manifest['sources']['source.billing.raw.invoices']
        source.update(resource_type='source', database='qualification', schema='Raw "Inbound',
                      identifier='Invoice "Archive', source_name='raw', loader='',
                      config={'enabled': True})

    def mutate_artifact(self, name, mutate):
        path = self.root / self.receipt[name]['path']
        value = json.loads(path.read_text())
        mutate(value)
        path.write_text(json.dumps(value))
        self.receipt[name]['sha256'] = hash_file(path)

    def capture(self):
        return collector.capture(self.database, self.receipt_path, self.project)

    def test_exact_quoted_names_and_all_observed_columns(self):
        report = self.capture()
        relations = {item['physical_name']: item['columns'] for item in report['relations']}
        self.assertEqual(relations, {
            self.source_relation: ['Source ID', 'amount'],
            self.fact_relation: ['Invoice ID', 'Undocumented Note'],
            '"qualification"."main"."currencies"': ['currency'],
            '"qualification"."main"."history"': ['invoice_id'],
        })
        self.assertEqual(report['identifier_policy'], 'exact')
        self.assertEqual(report['origin'], 'executed_metadata')
        self.assertEqual(report['validation_scope'], 'local')
        self.assertEqual(report['candidate_sha256'], snapshot(self.project)['sha256'])
        self.assertEqual(report['native_receipt_sha256'], hash_file(self.receipt_path))
        self.assertEqual(report['scope'], ['"qualification"."Raw ""Inbound"', '"qualification"."main"'])
        self.assertNotIn('"qualification"."main"."stg_invoice"', relations)

    def test_unexpected_table_is_retained_for_downstream_denominator_check(self):
        with duckdb.connect(str(self.database)) as connection:
            connection.execute('create table "Unexpected Table" (extra_id integer)')
        report = self.capture()
        relations = {item['physical_name']: item['columns'] for item in report['relations']}
        self.assertEqual(relations['"qualification"."main"."Unexpected Table"'], ['extra_id'])
        manifest = json.loads((self.root / 'manifest.json').read_text())
        self.assertEqual(set(relations) - physical_denominator(manifest), {'"qualification"."main"."Unexpected Table"'})

    def test_missing_database_is_not_created(self):
        missing = self.root / 'missing.duckdb'
        with patch.object(duckdb, 'connect', side_effect=AssertionError('Missing database must be rejected before connection')):
            with self.assertRaisesRegex(ValueError, 'Missing file'):
                collector.capture(missing, self.receipt_path, self.project)
        self.assertFalse(missing.exists())

    def test_missing_relation_is_observably_absent_not_filled_from_manifest(self):
        with duckdb.connect(str(self.database)) as connection:
            connection.execute('drop table "Fact ""Daily"')
        report = self.capture()
        actual = {item['physical_name'] for item in report['relations']}
        manifest = json.loads((self.root / 'manifest.json').read_text())
        self.assertEqual(physical_denominator(manifest) - actual, {self.fact_relation})
        self.assertNotIn(self.fact_relation, actual)

    def test_native_failure_rejected_before_connecting(self):
        self.mutate_artifact('run_results', lambda result: result['results'][0].update(status='error'))
        self.receipt_path.write_text(json.dumps(self.receipt))
        with patch.object(duckdb, 'connect', side_effect=AssertionError('Failed build must not connect')):
            with self.assertRaisesRegex(ValueError, 'Native build must pass'):
                self.capture()

    def test_column_bound_rejects_instead_of_returning_partial_observation(self):
        with patch.object(collector, 'MAX_COLUMNS', 1):
            with self.assertRaisesRegex(ValueError, 'exceeded bound; no partial export'):
                self.capture()

    def test_capture_is_read_only_and_leaves_database_bytes_and_rows_unchanged(self):
        before = hash_file(self.database)
        with patch.object(duckdb, 'connect', wraps=duckdb.connect) as connect:
            self.capture()
        connect.assert_called_once_with(str(self.database), read_only=True, config={'enable_external_access': False})
        self.assertEqual(before, hash_file(self.database))
        with duckdb.connect(str(self.database), read_only=True) as connection:
            self.assertEqual(connection.execute('select * from "Fact ""Daily"').fetchall(), [(17, 'unchanged source value')])


if __name__ == '__main__':
    unittest.main()
