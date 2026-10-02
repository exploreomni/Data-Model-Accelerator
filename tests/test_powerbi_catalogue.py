"""Independent Power BI catalogue identity, metadata and receipt regressions.

These tests copy only packaged source inputs and RAW DDL. No oracle, expected
results or native warehouse runtime is used. The catalogue caller still owns
alignment of the supplied canonical source snapshot hash with its inventory.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1] / "skills/data-model-accelerator"
sys.path.insert(0, str(SKILL / "scripts"))
OPTIONAL = all(importlib.util.find_spec(name) for name in
               ("yaml", "sqlglot", "duckdb", "pandas", "jsonschema", "referencing"))
if OPTIONAL:
    from powerbi_catalogue import build_catalogue, normalize_receipts, _ddl_columns, PINNED_EXPORTS
    from verify_catalogue import verify

CASE = SKILL / "examples/powerbi-omni-e2e"
MODEL = "input/repo/Billing.SemanticModel/model.bim"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(OPTIONAL, "Optional Power BI E2E dependencies are required")
class PowerBICatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.case = Path(self.tmp.name) / "case"
        shutil.copytree(CASE / "input", self.case / "input")
        shutil.copytree(CASE / "target/snowflake", self.case / "target/snowflake")
        self.out = Path(self.tmp.name) / "output"

    def read(self, path):
        return json.loads((self.case / path).read_text())

    def write(self, path, value):
        (self.case / path).write_text(json.dumps(value, indent=2) + "\n")

    def build(self):
        return build_catalogue(self.case, self.out, "a" * 64)

    def native(self):
        return (self.read("input/catalogue/exports/objects.json")["rows"],
                self.read("input/catalogue/exports/columns.json")["rows"],
                _ddl_columns(self.case))

    def outputs(self, result):
        return (json.loads(Path(result["catalogue_path"]).read_text()),
                json.loads(Path(result["bindings_path"]).read_text()))

    def replace_m(self, before, after):
        """Change native partition expressions without changing model schema."""
        model = self.read(MODEL)
        matches = 0
        for table in model["model"]["tables"]:
            for partition in table["partitions"]:
                source = partition["source"]
                expression = source["expression"]
                was_list = isinstance(expression, list)
                text = "\n".join(expression) if was_list else expression
                matches += text.count(before)
                changed = text.replace(before, after)
                source["expression"] = changed.split("\n") if was_list else changed
        self.assertGreater(matches, 0, "Mutation must reach an actual M partition")
        self.write(MODEL, model)

    def verify_changed(self, result, catalogue, bindings):
        """Rehash deliberate changes to test content validation, not stale hashes."""
        path = Path(result["catalogue_path"])
        path.write_text(json.dumps(catalogue, indent=2) + "\n")
        bindings["catalogue_sha256"] = sha(path)
        binding_path = Path(result["bindings_path"])
        binding_path.write_text(json.dumps(bindings, indent=2) + "\n")
        return verify(path, binding_path)

    def test_complete_scope_is_four_objects_twenty_three_physical_columns(self):
        result = self.build()
        report = result["verification"]
        catalogue, bindings = self.outputs(result)
        self.assertTrue(report["catalogue_context_complete"])
        self.assertEqual((report["counts"]["objects"], report["counts"]["columns"],
                          report["counts"]["resolved_references"]), (4, 23, 4))
        self.assertEqual({obj["identity"]["name"] for obj in catalogue["objects"]},
                         {"INVOICE_CDC", "PAYMENT_CDC", "CUSTOMER_HISTORY", "ADJUSTMENTS"})
        invoice = next(obj for obj in catalogue["objects"] if obj["identity"]["name"] == "INVOICE_CDC")
        columns = {column["path"][0]: column for column in invoice["columns"]}
        self.assertEqual(columns["INVOICE_DATE"]["data_type"], "VARCHAR")
        self.assertEqual(columns["AMOUNT_CENTS"]["data_type"], "NUMBER(38,0)")
        self.assertTrue(all(column["nullable"] for obj in catalogue["objects"] for column in obj["columns"]))
        self.assertTrue(all(set(obj["metadata_status"].values()) == {"unknown"} for obj in catalogue["objects"]))
        self.assertFalse(report["native_metadata_consistency"]["native_warehouse_execution"])
        self.assertTrue(all(ref["namespace"] == {"platform_instance": "DMA_POWERBI_SYNTHETIC",
                                                  "catalog": "DMA_POWERBI", "schema": "RAW"}
                            for ref in bindings["references"]))

    def test_current_pbip_model_and_csv_hashes_and_caller_snapshot_boundary(self):
        model_path = self.case / MODEL
        model_path.write_bytes(model_path.read_bytes() + b"\n")
        result = self.build()
        _, bindings = self.outputs(result)
        assets = {asset["path"]: asset for asset in bindings["source_assets"]}
        self.assertEqual(len(assets), 12)
        self.assertIn("Billing.pbip", assets)
        self.assertIn("Billing.SemanticModel/model.bim", assets)
        self.assertIn("adjustments.csv", assets)
        for name, asset in assets.items():
            self.assertEqual(asset["sha256"], sha(self.case / "input/repo" / name))
        self.assertEqual(bindings["source_snapshot_sha256"], "a" * 64)
        self.assertIn("Caller supplies canonical inventory hash", bindings["source_snapshot_binding_note"])
        self.assertTrue(all("Billing.SemanticModel/model.bim#" in ref["source_reference"]
                            for ref in bindings["references"]))
        for bad_hash in (None, "not-a-hash", "A" * 64):
            with self.subTest(hash=bad_hash), self.assertRaisesRegex(ValueError, "source snapshot SHA-256 required"):
                build_catalogue(self.case, self.out, bad_hash)

    def test_csv_landing_receipt_binds_changed_bytes_and_header_only_capture(self):
        path = self.case / "input/repo/adjustments.csv"
        path.write_text(path.read_text().replace("service_credit", "reviewed_credit"))
        for header_only in (False, True):
            with self.subTest(header_only=header_only):
                if header_only:
                    path.write_text("TENANT_ID,INVOICE_ID,ADJUSTMENT_CENTS,REASON\n")
                catalogue, bindings = self.outputs(self.build())
                landing = next(ref for ref in bindings["references"]
                               if ref["source_kind"] == "proposed_governed_csv_landing")
                self.assertEqual(landing["source_file_path"], "adjustments.csv")
                self.assertEqual(landing["source_file_sha256"], sha(path))
                self.assertEqual(catalogue["input_evidence"]["csv_sha256"], sha(path))
                self.assertEqual([ref["source_kind"] for ref in bindings["references"]].count("powerbi_m_native_query"), 3)
                self.assertIn("not an existing deployed table", landing["evidence"])
                self.assertTrue(all("not expression-level column lineage" in ref["column_binding_basis"]
                                    for ref in bindings["references"]))
                if header_only:
                    self.assertEqual(catalogue["input_evidence"]["row_counts"]["ADJUSTMENTS"], 0)

    def test_wrong_account_warehouse_and_database_in_m_are_rejected(self):
        original = self.read(MODEL)
        for before, after, error in (
            ('"DMA_POWERBI_SYNTHETIC"', '"OTHER_ACCOUNT"', "account/warehouse"),
            ('"SYNTHETIC_LOCAL_ONLY"', '"OTHER_WAREHOUSE"', "account/warehouse"),
            ('Name="DMA_POWERBI"', 'Name="OTHER_DATABASE"', "account/database"),
        ):
            with self.subTest(binding=before):
                self.write(MODEL, original)
                self.replace_m(before, after)
                with self.assertRaisesRegex(ValueError, error):
                    self.build()

    def test_m_native_sql_requires_exact_qualified_allowed_relations(self):
        original = self.read(MODEL)
        for replacement in ("OTHER_DATABASE.RAW.INVOICE_CDC", "DMA_POWERBI.PRIVATE.INVOICE_CDC",
                            "INVOICE_CDC", "DMA_POWERBI.RAW.NOT_REVIEWED"):
            with self.subTest(relation=replacement):
                self.write(MODEL, original)
                self.replace_m("DMA_POWERBI.RAW.INVOICE_CDC", replacement)
                with self.assertRaisesRegex(ValueError, "source|Source|relation|Relation"):
                    self.build()

    def test_native_metadata_inventory_and_required_fields_cannot_be_omitted(self):
        objects, columns, ddl = self.native()
        with self.assertRaisesRegex(ValueError, "object inventory incomplete"):
            normalize_receipts(objects[:-1], columns, ddl)
        with self.assertRaisesRegex(ValueError, "does not exactly match"):
            normalize_receipts(objects, columns[:-1], ddl)
        for required in ("COLUMN_NAME", "DATA_TYPE", "ORDINAL_POSITION", "IS_NULLABLE"):
            with self.subTest(field=required):
                changed = copy.deepcopy(columns)
                del changed[0][required]
                with self.assertRaisesRegex(ValueError, "metadata shape mismatch"):
                    normalize_receipts(objects, changed, ddl)

    def test_native_type_precision_null_case_and_order_drift_fail(self):
        objects, columns, ddl = self.native()
        numeric = next(i for i, column in enumerate(columns) if column["DATA_TYPE"] == "NUMBER")
        changes = [(0, "DATA_TYPE", "BOOLEAN"), (0, "IS_NULLABLE", "NO"),
                   (0, "IS_NULLABLE", None), (0, "COLUMN_NAME", "tenant_id"),
                   (0, "ORDINAL_POSITION", 2), (0, "ORDINAL_POSITION", True),
                   (numeric, "NUMERIC_PRECISION", 20), (numeric, "NUMERIC_SCALE", 2),
                   (numeric, "NUMERIC_PRECISION", None)]
        for index, field, value in changes:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(columns)
                changed[index][field] = value
                with self.assertRaises(ValueError):
                    normalize_receipts(objects, changed, ddl)
        changed = copy.deepcopy(columns)
        changed[0], changed[1] = changed[1], changed[0]
        with self.assertRaisesRegex(ValueError, "ordinal order mismatch"):
            normalize_receipts(objects, changed, ddl)

    def test_same_name_wrong_namespace_duplicate_and_view_are_not_accepted(self):
        objects, columns, ddl = self.native()
        for field, value in (("TABLE_CATALOG", "OTHER_DATABASE"), ("TABLE_SCHEMA", "PRIVATE"),
                             ("TABLE_NAME", objects[0]["TABLE_NAME"].lower()), ("TABLE_TYPE", "VIEW")):
            with self.subTest(field=field):
                changed = copy.deepcopy(objects)
                changed[0][field] = value
                with self.assertRaises(ValueError):
                    normalize_receipts(changed, columns, ddl)
        with self.assertRaisesRegex(ValueError, "Duplicate/unknown"):
            normalize_receipts(objects + [objects[0]], columns, ddl)
        with self.assertRaisesRegex(ValueError, "Duplicate native column"):
            normalize_receipts(objects, columns + [columns[0]], ddl)
        changed = copy.deepcopy(columns)
        changed[0]["TABLE_SCHEMA"] = "PRIVATE"
        with self.assertRaisesRegex(ValueError, "column namespace mismatch"):
            normalize_receipts(objects, changed, ddl)

    def test_receipt_bytes_and_original_capture_preserved_tampering_and_repin_fail(self):
        before = {relative: (self.case / "input/catalogue" / relative).read_bytes()
                  for relative in PINNED_EXPORTS}
        catalogue, _ = self.outputs(self.build())
        for relative, data in before.items():
            self.assertEqual((self.out / relative).read_bytes(), data)
            self.assertEqual(json.loads(data)["captured_at"], catalogue["source_receipt_captured_at"])
        path = self.case / "input/catalogue/exports/columns.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "Pinned synthetic export hash mismatch"):
            self.build()
        provenance = self.read("input/catalogue/provenance.json")
        provenance["exports"]["exports/columns.json"] = sha(path)
        self.write("input/catalogue/provenance.json", provenance)
        with self.assertRaisesRegex(ValueError, "pins differ from the reviewed synthetic receipts"):
            self.build()

    def test_receipt_context_missing_export_and_bootstrap_drift_fail(self):
        original = self.read("input/catalogue/provenance.json")
        for field in ("platform_instance", "connection_id", "catalog", "schema", "location"):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed["context"][field] = "OTHER"
                self.write("input/catalogue/provenance.json", changed)
                with self.assertRaisesRegex(ValueError, "provenance/account/connection context"):
                    self.build()
        self.write("input/catalogue/provenance.json", original)
        path = self.case / "target/snowflake/00_raw_contract.sql"
        path.write_text(path.read_text().replace("AMOUNT_CENTS NUMBER(38,0)", "AMOUNT_CENTS NUMBER(38,0) NOT NULL"))
        with self.assertRaisesRegex(ValueError, "does not exactly match"):
            self.build()
        (self.case / "input/catalogue/exports/columns.json").unlink()
        with self.assertRaisesRegex(ValueError, "Pinned synthetic export hash mismatch"):
            self.build()

    def test_missing_malformed_and_orphan_csv_assets_fail(self):
        path = self.case / "input/repo/adjustments.csv"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()
        for content in ("", "TENANT_ID,INVOICE_ID,ADJUSTMENT_CENTS\n",
                        "INVOICE_ID,TENANT_ID,ADJUSTMENT_CENTS,REASON\n"):
            with self.subTest(content=content):
                path.write_text(content)
                with self.assertRaisesRegex(ValueError, "CSV column inventory/order mismatch"):
                    self.build()
        path.write_bytes(original)
        (self.case / "input/repo/unreferenced-adjustments.csv").write_bytes(original)
        with self.assertRaisesRegex(ValueError, "source graph has unresolved static errors"):
            self.build()

    def test_raw_missing_column_and_invalid_scalar_type_are_rejected(self):
        original = self.read("input/raw-data.json")
        changed = copy.deepcopy(original)
        del changed["INVOICE_CDC"][0]["CUSTOMER_ID"]
        self.write("input/raw-data.json", changed)
        with self.assertRaisesRegex(ValueError, "Raw fixture column inventory mismatch"):
            self.build()
        changed = copy.deepcopy(original)
        changed["INVOICE_CDC"][0]["AMOUNT_CENTS"] = "12000"
        self.write("input/raw-data.json", changed)
        with self.assertRaisesRegex(ValueError, "Raw integer value required"):
            self.build()

    def test_unsupported_native_sql_reader_and_omitted_raw_table_fail(self):
        original = self.read(MODEL)
        self.replace_m("DMA_POWERBI.RAW.INVOICE_CDC", "READ_CSV('/private/tmp/not-a-fixture.csv')")
        with self.assertRaisesRegex(ValueError, "source|Source|SQL|relation"):
            self.build()
        self.write(MODEL, original)
        # Still parseable and in scope, but no partition now references ADJUSTMENTS.
        self.replace_m("DMA_POWERBI.RAW.ADJUSTMENTS", "DMA_POWERBI.RAW.INVOICE_CDC")
        with self.assertRaisesRegex(ValueError, "raw source inventory mismatch"):
            self.build()

    def test_missing_csv_binding_or_rebound_unknown_column_blocks_completeness(self):
        result = self.build()
        catalogue, bindings = self.outputs(result)
        changed = copy.deepcopy(bindings)
        changed["references"] = [r for r in changed["references"]
                                 if r["source_kind"] != "proposed_governed_csv_landing"]
        report = self.verify_changed(result, catalogue, changed)
        self.assertFalse(report["catalogue_context_complete"])
        self.assertTrue(any("Expected source reference omitted" in e for e in report["errors"]))
        changed = copy.deepcopy(catalogue)
        changed["objects"][0]["columns"].pop()
        report = self.verify_changed(result, changed, copy.deepcopy(bindings))
        self.assertFalse(report["catalogue_context_complete"])
        self.assertTrue(any("column paths" in e for e in report["errors"]))

    def test_rebound_same_name_binding_ambiguity_and_export_tamper_fail(self):
        result = self.build()
        catalogue, bindings = self.outputs(result)
        for field, value in (("platform_instance", "OTHER_ACCOUNT"), ("catalog", "OTHER_DATABASE"),
                             ("schema", "PRIVATE")):
            with self.subTest(field=field):
                changed = copy.deepcopy(bindings)
                changed["references"][0]["namespace"][field] = value
                report = self.verify_changed(result, catalogue, changed)
                self.assertFalse(report["catalogue_context_complete"])
                self.assertTrue(any("does not" in e for e in report["errors"]))
        changed = copy.deepcopy(bindings)
        changed["references"][0]["status"] = "ambiguous"
        report = self.verify_changed(result, catalogue, changed)
        self.assertFalse(report["catalogue_context_complete"])
        self.assertTrue(any("ambiguous" in gap for gap in report["gaps"]))
        self.verify_changed(result, catalogue, bindings)
        path = self.out / "exports/columns.json"
        path.write_bytes(path.read_bytes() + b"\n")
        report = verify(Path(result["catalogue_path"]), Path(result["bindings_path"]))
        self.assertFalse(report["catalogue_context_complete"])
        self.assertTrue(any("Extraction artifact hash mismatch" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
