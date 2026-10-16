"""Independent catalogue-shape expectations; no DuckDB connection or execution."""
import builtins
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/data-model-accelerator/scripts"))
from source_adapters.motherduck import CAPABILITY, parse
from source_adapters.registry import parse as registry_parse, validate


def exported(rows, path="metadata/nested/catalogue.json"):
    files = {path: json.dumps(rows)}
    result = parse(files)
    validate(result, files)
    return result


def codes(result):
    return {g["code"] for g in result["gaps"]}


class MotherDuckMetadataTests(unittest.TestCase):
    def test_invalid_oids_remain_raw_without_normalized_identity(self):
        for value in (True, [], {}, "12", -1):
            with self.subTest(value=value):
                rows = [{"table_name": "t", "table_oid": value, "has_primary_key": False},
                        {"database_name": "db", "database_oid": value, "type": "duckdb", "readonly": True}]
                result = exported(rows)
                self.assertIn("invalid_metadata", codes(result))
                self.assertTrue(all(o["native_id"] is None for o in result["objects"]))
                self.assertEqual(result["objects"][0]["details"]["raw_metadata"], rows[0])

    def test_unbound_constraint_has_reviewable_label_without_native_identity(self):
        result = exported([{"constraint_type": "CHECK"}, {"constraint_type": "CHECK", "constraint_name": {"bad": 1}}])
        self.assertIn("namespace_unresolved", codes(result))
        self.assertEqual(result["dependencies"], [])
        self.assertTrue(all(o["name"].startswith("Unbound constraint") and o["native_id"] is None for o in result["objects"]))

    def test_registry_contract_and_no_native_qualification(self):
        files = {"nested/info.json": json.dumps([{"table_catalog": "analytics", "table_schema": "main",
                                                  "table_name": "orders", "table_type": "BASE TABLE"}])}
        result = registry_parse("motherduck", files)
        validate(result, files)
        self.assertEqual(CAPABILITY["acquisition"], "supplied_exports")
        self.assertEqual(len(result["component_sha256"]), 64)
        self.assertFalse(result["execution_performed"])
        self.assertEqual(result["native_validation"], "not_run")
        self.assertEqual(result["export_completeness"], "not_established")
        self.assertEqual(result["source_files"][0]["status"], "partial")

    def test_native_table_and_column_evidence_retained(self):
        rows = [{"database_name": "sales.db", "schema_name": "my schema", "table_name": "orders",
                 "table_oid": 124, "has_primary_key": True, "comment": "Order grain declared",
                 "column_count": 2, "temporary": False},
                {"database_name": "sales.db", "schema_name": "my schema", "table_name": "orders",
                 "column_name": "id", "column_index": 0, "data_type": "BIGINT", "is_nullable": False,
                 "column_default": "nextval('order_sequence')", "comment": "Opaque identifier"},
                {"database_name": "sales.db", "schema_name": "my schema", "table_name": "orders",
                 "column_name": "payload", "data_type": "STRUCT(items DECIMAL(18,2)[], label VARCHAR)"}]
        result = exported(rows)
        table, column, payload = result["objects"]
        self.assertEqual(table["native_id"], "124")
        self.assertEqual(table["name"], '"sales.db"."my schema"."orders"')
        self.assertEqual(table["details"]["raw_metadata"], rows[0])
        self.assertEqual(table["details"]["oid_scope"], "export_snapshot_only")
        self.assertEqual(column["details"]["column_default"], "nextval('order_sequence')")
        self.assertEqual(column["details"]["comment"], "Opaque identifier")
        self.assertFalse(column["details"]["is_nullable"])
        self.assertEqual(payload["details"]["data_type"], rows[2]["data_type"])
        self.assertEqual(result["dependencies"][0]["details"]["target_components"], ["sales.db", "my schema", "orders"])
        self.assertIn("query_provenance_unresolved", codes(result))

    def test_information_schema_types_and_ordinals_preserve_native_values(self):
        rows = [{"table_catalog": "db", "table_schema": "main", "table_name": "v", "table_type": "VIEW"},
                {"table_catalog": "db", "table_schema": "main", "table_name": "v", "column_name": "amount",
                 "ordinal_position": 1, "column_default": "0.0", "is_nullable": "YES", "data_type": "DECIMAL(18,2)",
                 "numeric_precision": 18, "numeric_scale": 2}]
        result = exported(rows)
        self.assertEqual(result["objects"][0]["kind"], "view_catalogue_candidate")
        detail = result["objects"][1]["details"]
        self.assertEqual(detail["native_ordinal"], 1)
        self.assertEqual(detail["ordinal_field"], "ordinal_position")
        self.assertEqual(detail["is_nullable"], "YES")
        self.assertEqual(detail["raw_metadata"], rows[1])

    def test_missing_scope_is_not_inferred_from_filename(self):
        result = exported([{"table_name": "orders", "column_name": "id", "data_type": "INTEGER"}],
                          "prod/main/orders.json")
        self.assertEqual(result["objects"][0]["details"]["namespace_components"], [None, None, "orders"])
        self.assertEqual(result["dependencies"], [])
        self.assertIn("namespace_unresolved", codes(result))

    def test_primary_and_foreign_key_metadata_has_no_inferred_target_database(self):
        common = {"database_name": "remote", "schema_name": "sales", "table_name": "orders"}
        rows = [dict(common, constraint_type="PRIMARY KEY", constraint_name="orders_pk",
                     constraint_column_names=["id"], constraint_column_indexes=[0], constraint_text="PRIMARY KEY(id)"),
                dict(common, constraint_type="FOREIGN KEY", constraint_name="customer_fk",
                     constraint_column_names=["customer_id"], referenced_table="customers", referenced_column_names=["id"])]
        result = exported(rows)
        foreign = next(d for d in result["dependencies"] if d["details"]["kind"] == "foreign_key")
        self.assertEqual(foreign["target"], "customers")
        self.assertEqual(foreign["details"]["target_namespace"], "not_supplied")
        self.assertEqual(foreign["details"]["source_columns"], ["customer_id"])
        self.assertIn("foreign_key_namespace_unresolved", codes(result))
        self.assertEqual(result["objects"][0]["details"]["enforcement"], "not_verified")

    def test_information_schema_fk_is_incomplete_without_key_rows(self):
        result = exported([{"table_catalog": "db", "table_schema": "main", "table_name": "orders",
                            "constraint_name": "fk", "constraint_type": "FOREIGN KEY", "enforced": "YES"}])
        self.assertIn("foreign_key_incomplete", codes(result))
        self.assertFalse(any(d["details"]["kind"] == "foreign_key" for d in result["dependencies"]))

    def test_attachment_metadata_cannot_authenticate_cloud_placement(self):
        row = {"database_name": "shared_db", "database_oid": 10, "type": "motherduck", "readonly": True}
        result = exported([row])
        self.assertEqual(result["objects"][0]["details"]["raw_metadata"], row)
        self.assertEqual(result["objects"][0]["details"]["cloud_placement"], "unverified")
        self.assertIn("attachment_identity_unverified", codes(result))

    def test_unknown_fields_duplicate_rows_and_invalid_values_are_explicit(self):
        row = {"database_name": "db", "schema_name": "main", "table_name": "t", "column_name": "id",
               "data_type": "INTEGER", "column_index": -1, "is_nullable": "false", "column_default": [],
               "future_option": {"keep": True}}
        result = exported([row, row, None, {"database_name": "bad", "readonly": "yes", "type": "duckdb"}])
        self.assertTrue({"unknown_fields", "duplicate_identity", "invalid_ordinal", "invalid_nullability",
                         "invalid_default", "invalid_row", "invalid_database"} <= codes(result))
        self.assertEqual(result["objects"][0]["details"]["raw_metadata"], row)
        self.assertNotEqual(result["objects"][0]["id"], result["objects"][1]["id"])

    def test_unknown_envelope_query_rows_and_empty_export_never_imply_completeness(self):
        for rows, expected in [({"tables": []}, "unsupported_shape"), ([{"arbitrary_value": 3}], "unsupported_row"),
                               ([], "empty_export")]:
            with self.subTest(rows=rows):
                result = exported(rows)
                self.assertIn(expected, codes(result))
                self.assertEqual(result["objects"], [])
                self.assertEqual(result["export_completeness"], "not_established")

    def test_bad_json_and_unsupported_formats_accounted_for(self):
        files = {"a/b.json": '[{"table_name":"x","table_name":"y"}]', "c.json": '[NaN]',
                 "d.json": '{"broken":', "nested/file.parquet": "not opened"}
        result = parse(files)
        validate(result, files)
        self.assertTrue({"source.duplicate_key", "source.nonfinite_number", "source.invalid_json", "unsupported_format"} <= codes(result))
        self.assertEqual(len(result["source_files"]), 4)
        self.assertTrue(all(f["status"] == "unsupported" for f in result["source_files"]))

    def test_missing_optional_parser_retains_raw_sql_without_driver_import(self):
        real_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == "sqlglot" or name.startswith("sqlglot."):
                raise ImportError("simulated unavailable parser")
            if name in ("duckdb", "motherduck"):
                self.fail("Offline parser must not import a database driver")
            return real_import(name, *args, **kwargs)
        sql = "CREATE VIEW v AS SELECT id FROM cloud.sales.orders;"
        with patch("builtins.__import__", side_effect=guarded):
            result = parse({"view.sql": sql})
        self.assertIn("sql.parser_dependency_missing", codes(result))
        self.assertEqual(result["expressions"][0]["text"], sql)
        self.assertFalse(result["execution_performed"])


@unittest.skipUnless(importlib.util.find_spec("sqlglot"), "Pinned SQLGlot dependency required")
class MotherDuckSQLTests(unittest.TestCase):
    def test_native_view_dependencies_keep_attached_database_and_exclude_cte(self):
        sql = 'CREATE VIEW reporting.main.v AS WITH base AS (SELECT id FROM "cloud db".sales.orders) SELECT id FROM base;'
        row = {"database_name": "reporting", "schema_name": "main", "view_name": "v", "view_oid": 91,
               "comment": "Cross-database view", "sql": sql}
        result = exported([row])
        reads = [d for d in result["dependencies"] if d["details"]["kind"] == "reads_from"]
        self.assertEqual([d["target"] for d in reads], ['"cloud db".sales.orders'])
        self.assertEqual(reads[0]["source_id"], result["objects"][0]["id"])
        self.assertTrue(any(e["text"] == sql and e["evidence"]["locator"] == "$[0].sql" for e in result["expressions"]))
        self.assertIn("runtime_unverified", codes(result))

    def test_sql_ddl_type_defaults_and_constraints(self):
        sql = "CREATE TABLE local.main.orders (id BIGINT PRIMARY KEY, amount DECIMAL(18,2) DEFAULT 0, customer_id BIGINT REFERENCES local.main.customers(id));"
        result = parse({"schema/orders.sql": sql})
        columns = {o["name"]: o["details"] for o in result["objects"] if o["kind"] == "column"}
        self.assertEqual(columns["id"]["data_type"], "BIGINT")
        self.assertTrue(columns["id"]["primary_key_declared"])
        self.assertIn("DEFAULT 0", columns["amount"]["declaration"])
        fk = next(d for d in result["dependencies"] if d["details"]["kind"] == "foreign_key")
        self.assertEqual(fk["target"], "local.main.customers")
        self.assertEqual(fk["details"]["source_columns"], ["customer_id"])
        self.assertEqual(fk["details"]["target_columns"], ["id"])

    def test_implicit_file_reads_are_not_catalogue_tables(self):
        for source in ("'data.parquet'", "'s3://bucket/x.parquet'", '"data.parquet"'):
            result = parse({"read.sql": "CREATE VIEW v AS SELECT * FROM " + source})
            self.assertIn("sql.external_resource", codes(result))
            self.assertFalse(any(d["details"]["kind"] == "reads_from" for d in result["dependencies"]))

    def test_external_runtime_credentials_sharing_and_dynamic_sql_are_flagged(self):
        cases = [("SELECT * FROM read_parquet('s3://example-bucket/data.parquet')", "external_data"),
                 ("ATTACH 'md:shared_db'", "runtime_command"),
                 ("CREATE SECRET s (TYPE S3, KEY_ID 'SANITIZED')", "credentials_or_secrets"),
                 ("SELECT * FROM query('SELECT * FROM orders')", "dynamic_sql"),
                 ("GRANT SELECT ON db.main.orders TO analyst", "shared_permissions")]
        for sql, code in cases:
            with self.subTest(sql=sql):
                result = parse({"scripts/unsafe.sql": sql})
                self.assertIn(code, codes(result))
                self.assertFalse(result["execution_performed"])
                self.assertTrue(any(e["text"] == sql for e in result["expressions"]))
        external = parse({"x.sql": cases[0][0]})
        self.assertFalse(any("read_parquet" in d["target"] for d in external["dependencies"]))


if __name__ == "__main__":
    unittest.main()
