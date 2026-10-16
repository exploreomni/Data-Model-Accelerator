"""Independent ClickHouse export expectations; no server or credentials used."""
import builtins
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/data-model-accelerator/scripts"))
from source_adapters.clickhouse import CAPABILITY, parse
from source_adapters.registry import parse as registry_parse, validate


def response(rows, **extra):
    keys = list(rows[0]) if rows and isinstance(rows[0], dict) else []
    return dict({"meta": [{"name": k, "type": "String"} for k in keys],
                 "data": rows, "rows": len(rows)}, **extra)


def export(value, path="snapshots/catalogue.json"):
    files = {path: json.dumps(value)}
    report = parse(files)
    validate(report, files)
    return report


def codes(report):
    return {g["code"] for g in report["gaps"]}


class ClickHouseMetadataTests(unittest.TestCase):
    def test_malformed_uuid_is_not_coerced_into_native_identity(self):
        for value in (True, 123, {'nested': 'id'}, ['id'], ''):
            result = export(response([{'database': 'd', 'name': 't', 'engine': 'MergeTree', 'uuid': value}]))
            self.assertIn('invalid_identity', codes(result))
            table = next(o for o in result['objects'] if o['kind'] == 'table_catalogue_candidate')
            self.assertIsNone(table['native_id'])
            self.assertEqual(table['details']['raw_metadata']['uuid'], value)

    def test_capability_and_registry_contract(self):
        self.assertEqual(CAPABILITY["acquisition"], "supplied_exports")
        files = {"exports/nested/query.json": json.dumps(response([{"value": 2}]))}
        result = registry_parse("clickhouse", files)
        validate(result, files)
        self.assertEqual(result["source"], "clickhouse")
        self.assertEqual(result["native_validation"], "not_run")
        self.assertEqual(result["export_completeness"], "not_established")
        self.assertFalse(result["execution_performed"])
        self.assertEqual(len(result["component_sha256"]), 64)

    def test_query_headers_are_never_physical_columns(self):
        source = response([{"name": "order_id", "type": "UInt64"}])
        result = export(source)
        self.assertEqual([o["kind"] for o in result["objects"]], ["query_result"])
        self.assertEqual(result["objects"][0]["details"]["query_result_schema"], source["meta"])
        self.assertFalse(result["objects"][0]["details"]["physical_schema_verified"])
        self.assertIn("query_provenance_unresolved", codes(result))
        self.assertEqual(result["dependencies"], [])

    def test_table_catalogue_candidates_keep_keys_engine_comments_and_unknowns(self):
        row = {"database": "analytics", "name": "events", "uuid": "opaque-id", "engine": "ReplacingMergeTree",
               "engine_full": "ReplacingMergeTree(version) ORDER BY id", "sorting_key": "id",
               "primary_key": "id", "partition_key": "toYYYYMM(created_at)", "comment": "Événements",
               "future_setting": {"keep": True}}
        result = export(response([row]))
        table = next(o for o in result["objects"] if o["kind"] == "table_catalogue_candidate")
        self.assertEqual(table["native_id"], "opaque-id")
        self.assertEqual(table["details"]["raw_metadata"], row)
        self.assertFalse(table["details"]["namespace_verified"])
        self.assertEqual(table["details"]["uniqueness"], "not_established")
        self.assertTrue({"query_provenance_unresolved", "key_not_uniqueness", "merge_runtime", "unknown_fields"} <= codes(result))
        self.assertTrue(any(e["text"] == "toYYYYMM(created_at)" for e in result["expressions"]))

    def test_columns_keep_default_materialized_alias_types_and_membership(self):
        rows = [{"database": "analytics", "table": "events", "name": name, "type": dtype,
                 "default_kind": kind, "default_expression": expr, "comment": "kept", "is_in_sorting_key": 1}
                for name, dtype, kind, expr in [
                    ("created_at", "DateTime64(3)", "DEFAULT", "now64(3)"),
                    ("day", "Date", "MATERIALIZED", "toDate(created_at)"),
                    ("label", "LowCardinality(String)", "ALIAS", "toString(day)"),
                    ("state", "AggregateFunction(sum, UInt64)", "", "")]]
        result = export(response(rows))
        columns = [o for o in result["objects"] if o["kind"] == "column_catalogue_candidate"]
        self.assertEqual([c["details"]["default_kind"] for c in columns], ["DEFAULT", "MATERIALIZED", "ALIAS", ""])
        self.assertEqual({e["text"] for e in result["expressions"][1:]}, {"now64(3)", "toDate(created_at)", "toString(day)"})
        self.assertTrue(all(d["target"] == "analytics.events" and d["details"]["resolution"] == "unresolved" for d in result["dependencies"]))
        self.assertIn("aggregate_state_runtime", codes(result))

    def test_describe_rows_have_no_invented_namespace(self):
        row = {"name": "nested.value", "type": "Nullable(String)", "default_type": "DEFAULT",
               "default_expression": "'unknown'", "comment": "kept", "codec_expression": "ZSTD(1)",
               "ttl_expression": "created_at + INTERVAL 7 DAY", "is_subcolumn": 1}
        result = export(response([row]), "database/table.json")
        column = next(o for o in result["objects"] if o["kind"] == "column_catalogue_candidate")
        self.assertIsNone(column["details"]["database"])
        self.assertIsNone(column["details"]["table"])
        self.assertEqual(result["dependencies"], [])
        self.assertIn("describe_namespace_unresolved", codes(result))
        self.assertEqual(column["details"]["raw_metadata"]["is_subcolumn"], 1)

    def test_metadata_dependency_direction_remains_labeled(self):
        row = {"database": "db", "name": "raw", "engine": "MergeTree",
               "dependencies_database": ["db"], "dependencies_table": ["mv"],
               "loading_dependencies_database": ["db"], "loading_dependencies_table": ["prior"]}
        result = export(response([row]))
        self.assertEqual({(d["target"], d["details"]["kind"]) for d in result["dependencies"]},
                         {("db.mv", "catalogue_dependent_view"), ("db.prior", "loading_dependency")})
        self.assertTrue(all(d["details"]["resolution"] == "unresolved" for d in result["dependencies"]))

    def test_materialized_and_distributed_runtime_are_explicit(self):
        rows = [{"database": "db", "name": "mv", "engine": "MaterializedView", "target_database": "db", "target_table": "rollup"},
                {"database": "db", "name": "remote", "engine": "Distributed", "engine_full": "Distributed(cluster, db, local)"}]
        result = export(response(rows))
        self.assertTrue({"materialized_view_runtime", "distributed_runtime"} <= codes(result))
        self.assertEqual(result["dependencies"][0]["target"], "db.rollup")

    def test_malformed_metadata_does_not_crash_or_invent_deps(self):
        rows = [{"database": "db", "name": "bad", "engine": [], "extra": 1},
                {"database": "db", "name": "ok", "engine": "Memory", "dependencies_database": ["db"], "dependencies_table": []},
                {"database": "db", "table": "t", "name": "id", "type": None}, 3]
        result = export(response(rows))
        self.assertTrue({"invalid_table", "invalid_dependency_pair", "invalid_column", "invalid_row"} <= codes(result))
        self.assertFalse(result["dependencies"])

    def test_json_errors_duplicates_unknown_envelopes_and_unsupported_format(self):
        for text, code in [("{", "source.invalid_json"), ('{"data":[],"data":[]}', "source.duplicate_key"),
                           ('{"data": NaN}', "source.nonfinite_number")]:
            with self.subTest(text=text):
                result = parse({"bad.json": text})
                self.assertIn(code, codes(result))
                self.assertEqual(result["expressions"][0]["text"], text)
                validate(result, {"bad.json": text})
        self.assertIn("invalid_response", codes(export({"source": "system.tables", "response": response([])})))
        self.assertIn("unsupported_format", codes(parse({"README.txt": "source evidence"})))

    def test_limits_empty_duplicate_identity_exception_and_count_gap(self):
        row = {"database": "db", "table": "t", "name": "id", "type": "UInt64"}
        result = export(response([row, row], rows_before_limit_at_least=10))
        self.assertTrue({"duplicate_identity", "limited_result"} <= codes(result))
        self.assertIn("empty_export", codes(export(response([]))))
        mismatch = response([row]); mismatch["rows"] = 9
        self.assertIn("row_count_mismatch", codes(export(mismatch)))
        failed = export(response([row], exception="Code: 1"))
        self.assertIn("query_exception", codes(failed))
        self.assertEqual([o["kind"] for o in failed["objects"]], ["query_result"])

    def test_repeatable_and_unsafe_paths(self):
        files = {"deep/catalogue.json": json.dumps(response([{"x": 1}]))}
        self.assertEqual(parse(files), parse(copy.deepcopy(files)))
        with self.assertRaisesRegex(ValueError, "source.unsafe_path"):
            parse({"../query.sql": "SELECT 1"})

    def test_missing_optional_parser_is_a_gap(self):
        original = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == "sqlglot" or name.startswith("sqlglot."):
                raise ImportError("deliberately absent")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=importing):
            result = parse({"query.sql": "SELECT id FROM db.orders"})
        self.assertIn("sql.parser_dependency_missing", codes(result))
        self.assertFalse(result["dependencies"])


@unittest.skipUnless(importlib.util.find_spec("sqlglot"), "Pinned SQLGlot dependency required")
class ClickHouseSqlTests(unittest.TestCase):
    def test_ddl_keeps_engine_keys_defaults_comments_and_no_uniqueness(self):
        sql = "CREATE TABLE db.events (id UInt64, label String DEFAULT 'n' COMMENT 'kept', day UInt64 MATERIALIZED id + 1, alias_id UInt64 ALIAS id) ENGINE = MergeTree PARTITION BY id ORDER BY id"
        files = {"ddl/events.sql": sql}
        result = parse(files); validate(result, files)
        relation = next(o for o in result["objects"] if o["kind"] == "relation")
        self.assertEqual(relation["name"], "db.events")
        self.assertIn("ORDER BY id", relation["details"]["properties"])
        self.assertIn("PARTITION BY id", relation["details"]["properties"])
        columns = [o for o in result["objects"] if o["kind"] == "column"]
        self.assertFalse(any(c["details"]["primary_key_declared"] for c in columns))
        self.assertTrue(all(c["details"]["uniqueness"] == "not_established" for c in columns))
        declarations = " ".join(c["details"]["declaration"] for c in columns)
        self.assertIn("MATERIALIZED", declarations)
        self.assertIn("ALIAS", declarations)
        self.assertIn("COMMENT 'kept'", declarations)
        self.assertEqual(result["expressions"][0]["text"], sql)

    def test_view_cte_dependencies_do_not_invent_physical_cte(self):
        sql = "CREATE VIEW db.summary AS WITH source_rows AS (SELECT id, amount FROM db.orders) SELECT id, sum(amount) AS total FROM source_rows WHERE amount > 0 GROUP BY id"
        result = parse({"queries/view.sql": sql})
        self.assertEqual({d["target"] for d in result["dependencies"]}, {"db.orders"})
        self.assertTrue(any(e["details"].get("output_name") == "total" for e in result["expressions"]))

    def test_native_metadata_sql_bound_to_candidate_and_raw_preserved(self):
        sql = "CREATE VIEW db.v AS SELECT id FROM db.source"
        row = {"database": "db", "name": "v", "engine": "View", "create_table_query": sql}
        result = export(response([row]))
        owner = next(o["id"] for o in result["objects"] if o["kind"] == "table_catalogue_candidate")
        self.assertEqual(result["dependencies"][0]["source_id"], owner)
        self.assertEqual(result["dependencies"][0]["target"], "db.source")
        self.assertTrue(any(e["text"] == sql for e in result["expressions"]))

    def test_malformed_dynamic_and_external_table_function_remain_unknown(self):
        self.assertIn("sql.parse_error", codes(parse({"bad.sql": "SELECT ("})))
        dynamic = parse({"dynamic.sql": "SELECT * FROM {{ source_table }}"})
        self.assertIn("sql.dynamic", codes(dynamic))
        self.assertFalse(dynamic["dependencies"])
        remote = parse({"remote.sql": "SELECT id FROM url('https://example.invalid/input', CSV, 'id UInt64')"})
        self.assertIn("sql.dynamic_relation", codes(remote))
        self.assertFalse(remote["dependencies"])


if __name__ == "__main__":
    unittest.main()
