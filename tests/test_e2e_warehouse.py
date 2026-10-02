"""Bounded fixture execution guards and raw replay contracts; no oracle reads."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/data-model-accelerator/scripts'
CASE = ROOT / 'skills/data-model-accelerator/examples/looker-omni-e2e'
try:
    import duckdb
    import lkml
    import sqlglot
    import yaml
    SPEC = importlib.util.spec_from_file_location('e2e_warehouse', SCRIPTS / 'e2e_warehouse.py')
    warehouse = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(warehouse)
    SEMANTIC_SPEC = importlib.util.spec_from_file_location('e2e_semantics', SCRIPTS / 'e2e_semantics.py')
    semantics = importlib.util.module_from_spec(SEMANTIC_SPEC)
    SEMANTIC_SPEC.loader.exec_module(semantics)
except ImportError:
    warehouse = None


@unittest.skipUnless(warehouse is not None, 'Warehouse probes require the optional pinned simulation dependencies')
class WarehouseFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.case = self.root / 'case'
        # Only source and candidate inputs are needed; expected results are never
        # opened or copied by these focused tests.
        shutil.copytree(CASE / 'input', self.case / 'input')
        shutil.copytree(CASE / 'target', self.case / 'target')
        self.raw = json.loads((self.case / 'input/raw-data.json').read_text())

    def build(self, raw=None):
        connection = warehouse.build(self.case, raw)
        self.addCleanup(connection.close)
        return connection

    def test_packaged_source_target_and_compiled_reports_execute_with_guards(self):
        connection = self.build()
        self.assertTrue(warehouse.fact_rows(connection))
        source = semantics.compile_looker(self.case / 'input/repo', {'tenant': 'A', 'group_by': ['segment']})
        target = semantics.compile_omni(self.case / 'target/omni', {'tenant': 'A', 'group_by': ['segment']})
        self.assertEqual(warehouse.query_rows(connection, source), warehouse.query_rows(connection, target))
        _, _, graph = warehouse.load_source(self.case / 'input/repo')
        self.assertEqual(graph['source_connection'], 'synthetic_billing_snowflake')
        self.assertEqual(graph['connection_binding']['platform_instance'], 'synthetic-snowflake-account')
        self.assertEqual(set(map(tuple, graph['physical_inputs'])), warehouse.RAW_RELATIONS)

    def test_read_csv_in_extra_create_statement_is_rejected_before_execution(self):
        sentinel = self.root / 'outside-case-sentinel.csv'
        sentinel.write_text('secret\noutside_case_value\n')
        extra = self.case / 'target/snowflake/99_external.sql'
        extra.write_text("CREATE OR REPLACE TABLE DMA_SIM.GOLD.FCT_INVOICES AS SELECT * FROM READ_CSV('" + str(sentinel) + "');")
        with self.assertRaisesRegex(warehouse.FixtureContractError, 'function.*ReadCSV'):
            self.build()

    def test_documentation_inventory_covers_executed_models_and_columns(self):
        connection = self.build()
        rows = connection.execute("""SELECT table_catalog, table_schema, table_name, column_name
            FROM information_schema.columns WHERE table_catalog = 'DMA_SIM'
            AND table_schema IN ('BRONZE', 'SILVER', 'GOLD')""").fetchall()
        observed = {}
        # This fixture uses unquoted Snowflake physical identifiers; DuckDB keeps
        # their authored case, whereas the native target folds it to uppercase.
        # This checks object/column coverage, not native type/null enforcement.
        for catalog, schema, table, column in rows:
            observed.setdefault('.'.join((catalog, schema, table)).upper(), set()).add(column.upper())
        inventory = json.loads((CASE / 'documentation/model-inventory.json').read_text())
        documented = {model['physical_name']: set(model['columns']) for model in inventory['models']}
        self.assertEqual(documented, observed)
        self.assertEqual(len(observed), 10)
        self.assertEqual(sum(len(columns) for columns in observed.values()), 79)

    def test_named_external_readers_and_anonymous_functions_are_rejected(self):
        queries = [
            "SELECT * FROM READ_CSV('/private/tmp/sentinel.csv')",
            "SELECT * FROM READ_PARQUET('/private/tmp/sentinel.parquet')",
            "SELECT * FROM READ_JSON('/private/tmp/sentinel.json')",
            "SELECT * FROM READ_TEXT('/private/tmp/sentinel.txt')",
            "SELECT * FROM GLOB('/private/tmp/*')",
            "SELECT CURRENT_SETTING('enable_external_access')",
            "SELECT MYSTERY(1)",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                with self.assertRaises(warehouse.FixtureContractError):
                    warehouse.to_duckdb(sql)

    def test_connection_blocks_external_reads_and_automatic_extensions_independently(self):
        sentinel = self.root / 'outside-case-sentinel.csv'
        sentinel.write_text('secret\noutside_case_value\n')
        connection = self.build()
        for setting in ('enable_external_access', 'autoinstall_known_extensions', 'autoload_known_extensions'):
            self.assertIs(connection.execute('SELECT current_setting(?)', [setting]).fetchone()[0], False)
        # Intentionally bypass the SQL adapter here to exercise DuckDB's own
        # external-access backstop on the returned local connection.
        with self.assertRaises(duckdb.Error):
            connection.execute('SELECT * FROM read_csv(?)', [str(sentinel)]).fetchall()

    def test_file_tables_unqualified_relations_and_unrelated_namespaces_fail(self):
        for relation in ("'/private/tmp/sentinel.csv'", '"/private/tmp/sentinel.csv"',
                         'FCT_INVOICES', 'GOLD.FCT_INVOICES', 'OTHER.GOLD.FCT_INVOICES',
                         'DMA_SIM.SECRETS.FCT_INVOICES', 'DMA_SIM.GOLD.UNRELATED',
                         '"dma_sim"."gold"."fct_invoices"'):
            with self.subTest(relation=relation):
                with self.assertRaises(warehouse.FixtureContractError):
                    warehouse.to_duckdb('SELECT * FROM ' + relation)

    def test_only_visible_ctes_can_supply_unqualified_relations(self):
        connection = self.build()
        sql = 'WITH local AS (SELECT * FROM DMA_SIM.GOLD.FCT_INVOICES) SELECT COUNT(*) AS n FROM local'
        self.assertEqual(warehouse.query_rows(connection, sql)[0]['n'], len(warehouse.fact_rows(connection)))
        for sql in (
            'WITH local AS (SELECT * FROM missing) SELECT * FROM local',
            'WITH local AS (SELECT * FROM local) SELECT * FROM local',
            'WITH a AS (SELECT * FROM b), b AS (SELECT 1) SELECT * FROM a',
            'SELECT * FROM local, (WITH local AS (SELECT 1) SELECT * FROM local) nested',
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(warehouse.FixtureContractError):
                    warehouse.to_duckdb(sql)

    def test_create_scope_options_and_other_statements_fail_closed(self):
        for sql in (
            'CREATE TABLE unrelated AS SELECT 1',
            'CREATE TABLE DMA_SIM.GOLD.UNRELATED AS SELECT 1',
            'CREATE TABLE OTHER.GOLD.FCT_INVOICES AS SELECT 1',
            'CREATE SCHEMA DMA_SIM.SECRETS',
            'CREATE DATABASE OTHER',
            'CREATE VIEW DMA_SIM.GOLD.FCT_INVOICES AS SELECT 1',
            'CREATE TEMP TABLE DMA_SIM.GOLD.FCT_INVOICES AS SELECT 1',
            'CREATE TABLE DMA_SIM.GOLD.FCT_INVOICES (v VARCHAR DEFAULT CURRENT_SETTING(\'home_directory\'))',
            'DROP TABLE DMA_SIM.GOLD.FCT_INVOICES',
            "COPY DMA_SIM.GOLD.FCT_INVOICES TO '/private/tmp/output.csv'",
            "ATTACH '/private/tmp/database.db' AS secret",
            'SET enable_external_access = true',
            'SELECT 1; SELECT 2',
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(warehouse.FixtureContractError):
                    warehouse.to_duckdb(sql)
        connection = self.build()
        with self.assertRaisesRegex(warehouse.FixtureContractError, 'read-only'):
            warehouse.query_rows(connection, 'CREATE OR REPLACE TABLE DMA_SIM.GOLD.FCT_INVOICES AS SELECT 1')

    def test_identical_history_replays_do_not_multiply_gold_rows(self):
        original = warehouse.fact_rows(self.build())
        repeated = deepcopy(self.raw)
        repeated['customer_history'] += deepcopy(repeated['customer_history']) * 2
        report = warehouse.validate_raw(repeated)
        self.assertEqual(report['replayed_history_rows'], len(self.raw['customer_history']) * 2)
        self.assertEqual(report['distinct_history_rows'], len(self.raw['customer_history']))
        self.assertEqual(warehouse.fact_rows(self.build(repeated)), original)

    def test_different_history_payload_on_same_interval_is_still_rejected(self):
        conflict = deepcopy(self.raw)
        changed = deepcopy(conflict['customer_history'][0])
        changed['segment'] = 'Conflicting segment'
        conflict['customer_history'].append(changed)
        with self.assertRaisesRegex(warehouse.FixtureContractError, 'Overlapping customer history'):
            warehouse.validate_raw(conflict)

    def test_lookml_connection_mismatch_is_rejected_by_source_loading_and_build(self):
        model = self.case / 'input/repo/models/billing.model.lkml'
        model.write_text(model.read_text().replace('synthetic_billing_snowflake', 'different_warehouse_instance'))
        for operation in (lambda: warehouse.load_source(self.case / 'input/repo'), lambda: self.build()):
            with self.assertRaisesRegex(warehouse.FixtureContractError, 'connection.*fixed'):
                operation()

    def test_catalogue_platform_and_object_namespace_must_match_fixed_connection(self):
        catalogue_path = self.case / 'input/catalogue/warehouse-catalogue.json'
        original = json.loads(catalogue_path.read_text())
        warehouse.catalogue_context(self.case, self.root / 'baseline-binding', 'a' * 64)
        mutations = [
            lambda c: c['context'].update(platform_instance='different-snowflake-account'),
            lambda c: c['context']['scope'][0].update(schema='OTHER'),
            lambda c: c['objects'][0]['identity'].update(catalog='OTHER'),
        ]
        for mutate in mutations:
            changed = deepcopy(original)
            mutate(changed)
            catalogue_path.write_text(json.dumps(changed))
            with self.assertRaises(warehouse.FixtureContractError):
                warehouse.catalogue_context(self.case, self.root / 'mutated-binding', 'a' * 64)

    def test_source_sql_cannot_add_unqualified_or_external_relations(self):
        view = self.case / 'input/repo/views/invoice_chaos.view.lkml'
        original = view.read_text()
        for source in ('BILLING_INVOICE_CDC', "READ_CSV('/private/tmp/sentinel.csv')", 'DMA_SIM.GOLD.FCT_INVOICES'):
            view.write_text(original.replace('DMA_SIM.BRONZE.BILLING_INVOICE_CDC', source))
            with self.subTest(source=source):
                with self.assertRaises(warehouse.FixtureContractError):
                    warehouse.load_source(self.case / 'input/repo')

    def test_raw_column_names_cannot_supply_sql_identifiers(self):
        changed = deepcopy(self.raw)
        changed['invoice_cdc'][0]['injected_column'] = 'x'
        with self.assertRaisesRegex(warehouse.FixtureContractError, 'column inventory'):
            warehouse.validate_raw(changed)


if __name__ == '__main__':
    unittest.main()
