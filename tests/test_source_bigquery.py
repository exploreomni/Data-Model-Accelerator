"""Independent expected BigQuery source evidence; never contacts Google Cloud."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/data-model-accelerator/scripts"))
from source_adapters.bigquery import parse


def table(name="orders"):
    return {
        "kind": "bigquery#table", "id": "warehouse-prod:sales." + name,
        "tableReference": {"projectId": "warehouse-prod", "datasetId": "sales", "tableId": name},
        "type": "TABLE", "schema": {"fields": [
            {"name": "order_id", "type": "INTEGER", "mode": "REQUIRED"},
            {"name": "created_at", "type": "TIMESTAMP", "defaultValueExpression": "CURRENT_TIMESTAMP()"},
            {"name": "items", "type": "RECORD", "mode": "REPEATED", "fields": [
                {"name": "sku", "type": "STRING", "description": "Stock identifier"},
                {"name": "price", "type": "NUMERIC", "precision": "12", "scale": "2"}]},
        ]}, "timePartitioning": {"type": "DAY", "field": "created_at"},
        "clustering": {"fields": ["order_id"]}, "requirePartitionFilter": True,
    }


def action(name, kind, body):
    return {"target": {"database": "warehouse-prod", "schema": "sales", "name": name},
            "canonicalTarget": {"database": "warehouse-base", "schema": "sales", "name": name},
            "filePath": "definitions/" + name + ".sqlx", kind: body}


def export(value, name="metadata.json"):
    return parse({name: json.dumps(value)})


def codes(result):
    return {gap["code"] for gap in result["gaps"]}


class BigQueryMetadataTests(unittest.TestCase):
    def test_nested_repeated_partition_and_ids(self):
        result = export(table())
        objects = result["objects"]
        physical = next(o for o in objects if o["kind"] == "table")
        self.assertEqual(physical["name"], "warehouse-prod.sales.orders")
        self.assertEqual(physical["native_id"], "warehouse-prod:sales.orders")
        self.assertEqual(physical["details"]["project_id"], "warehouse-prod")
        self.assertEqual(physical["details"]["time_partitioning"], {"type": "DAY", "field": "created_at"})
        self.assertEqual(physical["details"]["clustering"], {"fields": ["order_id"]})
        fields = {o["name"]: o for o in objects if o["kind"] == "field"}
        self.assertEqual(set(fields), {"order_id", "created_at", "items", "items.sku", "items.price"})
        self.assertEqual(fields["items"]["details"]["mode"], "REPEATED")
        self.assertEqual(fields["items.price"]["details"]["field_path"], ["items", "price"])
        self.assertEqual(fields["items.price"]["evidence"]["locator"], "$.schema.fields[2].fields[1]")
        self.assertEqual(result["expressions"][0]["text"], "CURRENT_TIMESTAMP()")
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["export_completeness"], "not_established")
        self.assertFalse(result["execution_performed"])

    def test_declared_foreign_key_reference_is_not_invented(self):
        resource = table()
        resource["tableConstraints"] = {"foreignKeys": [{"name": "customer_fk",
            "referencedTable": {"projectId": "warehouse-prod", "datasetId": "crm", "tableId": "customers"},
            "columnReferences": [{"referencingColumn": "customer_id", "referencedColumn": "id"}]}]}
        result = export(resource)
        dependency = result["dependencies"][0]
        self.assertEqual(dependency["target"], "warehouse-prod.crm.customers")
        self.assertEqual(dependency["details"]["raw_metadata"]["columnReferences"][0]["referencingColumn"], "customer_id")
        self.assertIn("unresolved_dependency", codes(result))

    def test_unknown_fields_retained_with_gap(self):
        resource = table()
        resource["futureFeature"] = {"expression": "retain exactly"}
        resource["schema"]["fields"][0]["newRule"] = "raw policy"
        result = export(resource)
        physical = next(o for o in result["objects"] if o["kind"] == "table")
        self.assertEqual(physical["details"]["raw_metadata"]["futureFeature"], {"expression": "retain exactly"})
        self.assertIn("unknown_fields", codes(result))
        self.assertEqual(result["source_files"][0]["status"], "partial")

    def test_bad_shapes_and_missing_refs_fail_visibly(self):
        fixtures = [None, 1, {"tables": 4, "totalItems": 5}, {"tables": [False]},
                    {"kind": "bigquery#table", "tableReference": {"datasetId": "sales"}},
                    {"routineType": "PROCEDURE", "definitionBody": "SELECT 1"}]
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                result = export(fixture)
                self.assertTrue(result["gaps"])
                self.assertEqual(result["source_files"][0]["status"], "partial")

    def test_duplicate_json_keys_are_rejected(self):
        result = parse({"bad.json": '{"tables": [], "tables": []}'})
        self.assertEqual(codes(result), {"invalid_json"})
        self.assertEqual(result["objects"], [])

    def test_bad_json_rejected(self):
        self.assertEqual(codes(parse({"bad.json": "{"})), {"invalid_json"})

    def test_pagination_never_becomes_complete(self):
        result = export({"tables": [table()], "nextPageToken": "opaque-token", "totalItems": 7})
        self.assertTrue({"pagination_incomplete", "collection_count_mismatch"} <= codes(result))
        self.assertEqual(result["export_completeness"], "not_established")
        page = next(o for o in result["objects"] if o["kind"] == "export_page")
        self.assertEqual(page["details"]["raw_metadata"]["nextPageToken"], "opaque-token")

    def test_list_projection_gaps(self):
        result = export({"tables": [{"tableReference": table()["tableReference"], "type": "VIEW"}],
                         "routines": [{"routineReference": {"projectId": "p", "datasetId": "d", "routineId": "f"},
                                       "routineType": "SCALAR_FUNCTION", "language": "SQL"}]})
        self.assertTrue({"missing_schema", "missing_sql"} <= codes(result))

    def test_sqlx_is_preserved_without_compilation(self):
        sqlx = 'config { type: "table" }\nSELECT * FROM ${ref("orders")}'
        result = parse({"definitions/test.sqlx": sqlx})
        self.assertEqual(result["expressions"][0]["text"], sqlx)
        self.assertEqual(codes(result), {"compilation_required"})
        self.assertFalse(result["dependencies"])

    def test_non_sql_routine_source_preserved(self):
        routine = {"routineReference": {"projectId": "p", "datasetId": "d", "routineId": "f"},
                   "routineType": "SCALAR_FUNCTION", "language": "JAVASCRIPT",
                   "definitionBody": "return x + 1;", "arguments": [{"name": "x", "dataType": {"typeKind": "INT64"}}]}
        result = export(routine)
        self.assertEqual(result["expressions"][0]["text"], "return x + 1;")
        self.assertEqual(result["objects"][0]["details"]["raw_metadata"]["arguments"], routine["arguments"])
        self.assertIn("non_sql_routine", codes(result))

    def test_legacy_view_never_parsed_as_google_sql(self):
        resource = table("legacy")
        resource.update(type="VIEW", view={"query": "SELECT x FROM [project:dataset.source]"})
        result = export(resource)
        self.assertIn("legacy_sql_unresolved", codes(result))
        self.assertEqual(result["expressions"][-1]["language"], "bigquery_legacy")
        self.assertEqual(result["dependencies"], [])

    def test_empty_exports_and_duplicate_identities(self):
        self.assertIn("empty_export", codes(export({"tables": []})))
        self.assertIn("duplicate_identity", codes(export([table(), table()])))

    def test_dataform_unknown_action_preserved(self):
        result = export({"compilationResultActions": [action("note", "notebook", {"contents": "never execute"})]})
        self.assertIn("unsupported_action", codes(result))
        note = next(o for o in result["objects"] if o["kind"] == "dataform_notebook")
        self.assertEqual(note["details"]["raw_metadata"]["notebook"]["contents"], "never execute")


@unittest.skipUnless(importlib.util.find_spec("sqlglot"), "Pinned SQLGlot dependency required")
class BigQuerySqlTests(unittest.TestCase):
    def test_sql_has_project_dataset_lineage_and_expressions(self):
        sql = "CREATE TABLE `prod.gold.revenue` AS SELECT customer_id, SUM(amount) AS revenue FROM `prod.raw.orders` WHERE amount > 0 GROUP BY customer_id"
        result = parse({"models/revenue.sql": sql})
        self.assertIn("prod.raw.orders", {d["target"].replace("`", "") for d in result["dependencies"]})
        self.assertEqual(result["expressions"][0]["text"], sql)
        self.assertTrue(any(e["details"].get("output_name") == "revenue" for e in result["expressions"]))

    def test_view_sql_bound_to_metadata_owner(self):
        resource = table("summary")
        resource.update(type="VIEW", view={"useLegacySql": False, "query": "SELECT order_id FROM `warehouse-prod.sales.orders`"})
        result = export(resource)
        owner = next(o["id"] for o in result["objects"] if o["kind"] == "table")
        self.assertTrue(all(d["source_id"] == owner for d in result["dependencies"]))
        self.assertTrue(any(e["evidence"]["locator"] == "$.view.query" for e in result["expressions"]))

    def test_compiled_dataform_multiple_sql_expressions_and_dependencies(self):
        source = action("orders", "declaration", {"relationDescriptor": {"description": "Provided source"}})
        relation = action("order_totals", "relation", {
            "relationType": "INCREMENTAL_TABLE", "dependencyTargets": [source["target"]],
            "selectQuery": "SELECT order_id, SUM(amount) AS total FROM `warehouse-prod.sales.orders` GROUP BY order_id",
            "preOperations": ["SELECT 1 AS setup"], "postOperations": ["SELECT 2 AS done"],
            "partitionExpression": "DATE(created_at)", "clusterExpressions": ["order_id"],
            "relationDescriptor": {"columns": [{"path": ["items", "sku"], "description": "SKU"}]},
            "incrementalTableConfig": {"incrementalSelectQuery": "SELECT order_id, amount FROM `warehouse-prod.sales.orders` WHERE amount > 0",
                                       "uniqueKeyParts": ["order_id"], "updatePartitionFilter": "created_at >= CURRENT_DATE()"}})
        result = export({"compilationResultActions": [source, relation]})
        obj = next(o for o in result["objects"] if o["kind"] == "dataform_relation")
        self.assertEqual(obj["details"]["raw_metadata"]["canonicalTarget"]["database"], "warehouse-base")
        self.assertEqual(obj["details"]["source_file"], "definitions/order_totals.sqlx")
        declared = [d for d in result["dependencies"] if d["details"].get("relation") == "dataform_dependency"]
        self.assertEqual([d["target"] for d in declared], ["warehouse-prod.sales.orders"])
        self.assertNotIn("unresolved_dependency", codes(result))
        raw = [e for e in result["expressions"] if e["details"].get("interpretation") == "preserved_original"]
        self.assertEqual(len(raw), 4)
        self.assertEqual(len({e["id"] for e in raw}), 4)
        self.assertTrue(all(e["evidence"]["path"] == "metadata.json" for e in raw))
        self.assertTrue(any(e["text"] == "DATE(created_at)" for e in result["expressions"]))

    def test_dataform_omitted_action_reference_and_page(self):
        relation = action("summary", "relation", {"selectQuery": "SELECT 1 AS result", "dependencyTargets": [
            {"database": "p", "schema": "d", "name": "omitted"}]})
        result = export({"compilationResultActions": [relation], "nextPageToken": "next"})
        self.assertTrue({"unresolved_dependency", "pagination_incomplete"} <= codes(result))

    def test_dynamic_sql_not_expanded(self):
        sql = "EXECUTE IMMEDIATE CONCAT('SELECT x FROM ', input_table)"
        result = parse({"dynamic.sql": sql})
        self.assertEqual(result["expressions"][0]["text"], sql)
        self.assertIn("dynamic_sql_unresolved", codes(result))
        self.assertEqual(result["dependencies"], [])

    def test_repeatable_output_and_invalid_sql(self):
        fixture = {"query.sql": "SELECT order_id FROM `p.d.orders`"}
        self.assertEqual(parse(fixture), parse(copy.deepcopy(fixture)))
        self.assertIn("sql.parse_error", codes(parse({"bad.sql": "SELECT ("})))


if __name__ == "__main__":
    unittest.main()
