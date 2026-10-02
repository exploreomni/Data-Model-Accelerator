"""Synthetic contract fixtures; no real warehouse metadata or connector access."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/data-model-accelerator/scripts/verify_catalogue.py"
SPEC = importlib.util.spec_from_file_location("catalogue_checker", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def make_fixture(root, provider="snowflake", origin="synthetic", now=None):
    """Return (catalogue_path, bindings_path) for an explicit synthetic fixture.

    Changing the origin argument exercises a declaration, not real provenance.
    The caller may replace source_snapshot_sha256 before registering the bundle.
    """
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "exports").mkdir(exist_ok=True)
    captured = now if now is not None else datetime.now(timezone.utc)
    raw = {
        "objects": [{"catalog": "Billing", "schema": "Raw", "name": "Invoices", "object_type": "TABLE"}],
        "columns": [{"object": "Invoices", "path": ["InvoiceId"], "data_type": "VARCHAR", "nullable": False},
                    {"object": "Invoices", "path": ["Payload", "Amount"], "data_type": "DECIMAL(18,2)", "nullable": None}],
    }
    extractions = []
    for component, rows in raw.items():
        path = root / "exports" / (component + ".json")
        path.write_text(json.dumps(rows) + "\n")
        extractions.append({"extraction_id": "extract-" + component, "scope_id": "scope-1",
                            "component": component, "status": "complete", "artifact_path": path.relative_to(root).as_posix(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "query_id": None,
                            "pagination_complete": True})
    catalogue = {"schema_version": 1, "kind": "warehouse_raw_catalogue", "provider": provider,
        "origin": origin, "captured_at": captured.isoformat(),
        "context": {"platform_instance": "synthetic-instance", "principal": "synthetic-metadata-reader",
                    "scope": [{"scope_id": "scope-1", "catalog": "Billing", "schema": "Raw", "location": "synthetic-region"}]},
        "coverage": {"status": "complete_for_visible_scope", "gaps": []}, "extractions": extractions,
        "objects": [{"object_id": "object-1", "scope_id": "scope-1",
                     "identity": {"catalog": "Billing", "schema": "Raw", "name": "Invoices"},
                     "object_type": "TABLE",
                     "columns": [{"path": ["InvoiceId"], "data_type": "VARCHAR", "nullable": False},
                                 {"path": ["Payload", "Amount"], "data_type": "DECIMAL(18,2)", "nullable": None}],
                     "metadata_status": {field: "unknown" for field in checker.METADATA_FIELDS},
                     "evidence": [{"extraction_id": "extract-objects", "locator": "$[0]"},
                                  {"extraction_id": "extract-columns", "locator": "$[0:2]"}]}]}
    catalogue_path = root / "catalogue.json"
    catalogue_path.write_text(json.dumps(catalogue, indent=2) + "\n")
    bindings = {"schema_version": 1, "kind": "warehouse_catalogue_bindings",
                "catalogue_sha256": hashlib.sha256(catalogue_path.read_bytes()).hexdigest(),
                "source_snapshot_sha256": "a" * 64, "expected_reference_ids": ["repo-ref-1"],
                "references": [{"reference_id": "repo-ref-1", "source_reference": "billing.invoice_current",
                                "status": "resolved", "object_id": "object-1",
                                "column_paths": [["InvoiceId"], ["Payload", "Amount"]],
                                "namespace": {"platform_instance": "synthetic-instance", "catalog": "Billing", "schema": "Raw"},
                                "evidence": "Synthetic explicit namespace/object/column mapping for contract validation; no live discovery."}]}
    bindings_path = root / "bindings.json"
    bindings_path.write_text(json.dumps(bindings, indent=2) + "\n")
    return catalogue_path, bindings_path


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.now = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
        self.reset()

    def reset(self):
        self.catalogue_path, self.bindings_path = make_fixture(self.root, now=self.now)
        self.catalogue = json.loads(self.catalogue_path.read_text())
        self.bindings = json.loads(self.bindings_path.read_text())

    def save(self, rebind=True):
        self.catalogue_path.write_text(json.dumps(self.catalogue, indent=2) + "\n")
        if rebind:
            self.bindings["catalogue_sha256"] = hashlib.sha256(self.catalogue_path.read_bytes()).hexdigest()
        self.bindings_path.write_text(json.dumps(self.bindings, indent=2) + "\n")

    def verify(self, **kwargs):
        kwargs.setdefault("now", self.now)
        return checker.verify(self.catalogue_path, self.bindings_path, **kwargs)

    def assertIncomplete(self, report, message=None):
        self.assertFalse(report["catalogue_context_complete"], report)
        if message:
            self.assertTrue(any(message in item for item in report["errors"] + report["gaps"]), report)

    def test_complete_declared_scope_preserves_synthetic_label_and_counts(self):
        report = self.verify()
        self.assertTrue(report["catalogue_context_complete"], report)
        self.assertEqual(report["origin"], "synthetic")
        self.assertEqual(report["counts"], {"scopes":1,"extractions":2,"objects":1,"columns":2,"expected_references":1,"references":1,"resolved_references":1})
        self.assertEqual(report["catalogue_sha256"], self.bindings["catalogue_sha256"])
        self.assertEqual(report["source_snapshot_sha256"], "a" * 64)
        self.assertTrue(any("not live warehouse evidence" in item for item in report["limitations"]))

    def test_all_providers_and_declared_origins_use_same_exact_contract(self):
        for provider in sorted(checker.PROVIDERS):
            for origin in ("synthetic", "provided_export", "live_metadata"):
                with self.subTest(provider=provider, origin=origin):
                    paths = make_fixture(self.root / (provider + "-" + origin), provider, origin, self.now)
                    result = checker.verify(*paths, now=self.now)
                    self.assertTrue(result["catalogue_context_complete"], result)
                    self.assertEqual(result["origin"], origin)

    def test_unknown_and_partial_enrichment_are_limitations_not_structural_gaps(self):
        self.catalogue["objects"][0]["metadata_status"]["security"] = "partial"
        self.save()
        result = self.verify()
        self.assertTrue(result["catalogue_context_complete"], result)
        self.assertFalse(result["gaps"])
        self.assertTrue(any("security=partial" in item for item in result["limitations"]))

    def test_optional_enrichment_failure_does_not_erase_complete_core_exports(self):
        # Failed enrichment carries a hashed error receipt, never business metadata.
        # A later missing optional receipt is nonblocking only for this helper's
        # structural scope; the review bundle must still register that receipt.
        receipt = self.root / "exports/statistics-error.json"
        receipt.write_text('{"status":"failed","error":"Synthetic metadata permission denied"}\n')
        optional = deepcopy(self.catalogue["extractions"][0])
        optional.update(extraction_id="optional-stats", component="statistics", status="failed", pagination_complete=False,
                        artifact_path="exports/statistics-error.json", sha256=hashlib.sha256(receipt.read_bytes()).hexdigest())
        self.catalogue["extractions"].append(optional)
        self.save()
        result = self.verify()
        self.assertTrue(result["catalogue_context_complete"], result)
        self.assertTrue(any("optional-stats" in item for item in result["limitations"]))
        optional["artifact_path"] = "exports/missing-optional.json"
        self.catalogue["extractions"][-1] = optional
        self.save()
        result = self.verify()
        self.assertTrue(result["catalogue_context_complete"], result)
        self.assertTrue(any("artifact is missing" in item for item in result["limitations"]))
        self.assertTrue(any("complete review bundle" in item for item in result["limitations"]))

    def test_visibility_status_and_declared_coverage_gaps_block(self):
        for status in ("partial", "unavailable"):
            self.catalogue["coverage"]["status"] = status
            self.save()
            self.assertIncomplete(self.verify(), "visibility")
        self.catalogue["coverage"] = {"status":"complete_for_visible_scope","gaps":["one schema was denied"]}
        self.save()
        self.assertIncomplete(self.verify(), "blocking gap")

    def test_required_components_need_exports_and_pagination(self):
        for component in ("objects", "columns"):
            with self.subTest(component=component):
                self.reset()
                self.catalogue["extractions"] = [e for e in self.catalogue["extractions"] if e["component"] != component]
                self.save()
                self.assertIncomplete(self.verify(), "lacks a complete hash-verified " + component)
        self.reset()
        self.catalogue["extractions"][1]["pagination_complete"] = False
        self.save()
        self.assertIncomplete(self.verify(), "not complete/paginated")

    def test_missing_required_export_and_changed_export_hash_are_errors(self):
        path = self.root / "exports/columns.json"
        path.unlink()
        self.assertIncomplete(self.verify(), "artifact is missing")
        self.reset()
        path.write_text("[]\n")
        self.assertIncomplete(self.verify(), "artifact hash mismatch")

    def test_missing_objects_or_column_fields_cannot_pass(self):
        del self.catalogue["objects"][0]["columns"]
        self.save()
        self.assertIncomplete(self.verify(), ".columns must be an array")
        self.reset()
        del self.catalogue["objects"]
        self.save()
        self.assertIncomplete(self.verify(), "catalogue.objects must be an array")
        self.reset()
        self.catalogue["objects"] = []
        self.save()
        self.assertIncomplete(self.verify(), "references missing object")

    def test_empty_columns_cannot_be_hidden_by_a_table_only_binding(self):
        self.catalogue["objects"][0]["columns"] = []
        self.bindings["references"][0]["column_paths"] = []
        self.save()
        result = self.verify()
        self.assertIncomplete(result, "no declared columns")
        self.assertEqual(result["counts"]["resolved_references"], 0)

    def test_exact_namespace_and_column_case_are_enforced(self):
        for field, wrong in (("platform_instance","other-instance"),("catalog","billing"),("schema","raw")):
            self.reset()
            self.bindings["references"][0]["namespace"][field] = wrong
            self.save()
            result = self.verify()
            self.assertIncomplete(result, "namespace" if field != "platform_instance" else "platform_instance")
            self.assertEqual(result["counts"]["resolved_references"], 0)
        self.reset()
        self.bindings["references"][0]["column_paths"] = [["invoiceid"]]
        self.save()
        self.assertIncomplete(self.verify(), "case-mismatched column")
        self.assertEqual(self.catalogue["objects"][0]["identity"]["name"], "Invoices")
        self.assertEqual(self.catalogue["objects"][0]["columns"][0]["path"], ["InvoiceId"])

    def test_nested_column_path_and_unknown_object_binding(self):
        self.bindings["references"][0]["column_paths"] = [["Payload", "Missing"]]
        self.save()
        self.assertIncomplete(self.verify(), "column paths")
        self.bindings["references"][0]["object_id"] = "nonexistent"
        self.save()
        self.assertIncomplete(self.verify(), "missing object")

    def test_duplicate_ids_and_physical_identities_are_rejected(self):
        cases = [
            ("scope", lambda c: c["context"]["scope"].append(deepcopy(c["context"]["scope"][0]))),
            ("extraction_id", lambda c: c["extractions"].append(deepcopy(c["extractions"][0]))),
            ("object_id", lambda c: c["objects"].append(deepcopy(c["objects"][0]))),
            ("column path", lambda c: c["objects"][0]["columns"].append(deepcopy(c["objects"][0]["columns"][0]))),
        ]
        for message, change in cases:
            with self.subTest(message=message):
                self.reset(); change(self.catalogue); self.save()
                self.assertIncomplete(self.verify(), "Duplicate")
        self.reset()
        duplicate = deepcopy(self.catalogue["objects"][0]); duplicate["object_id"] = "object-2"
        self.catalogue["objects"].append(duplicate); self.save()
        self.assertIncomplete(self.verify(), "Duplicate physical object identity")

    def test_duplicate_omitted_and_undeclared_references_are_rejected(self):
        self.bindings["references"].append(deepcopy(self.bindings["references"][0])); self.save()
        self.assertIncomplete(self.verify(), "Duplicate reference_id")
        self.reset(); self.bindings["references"] = []; self.save()
        self.assertIncomplete(self.verify(), "omitted")
        self.reset(); self.bindings["references"][0]["reference_id"] = "not-declared"; self.save()
        self.assertIncomplete(self.verify(), "Undeclared")
        self.reset(); self.bindings["expected_reference_ids"].append("repo-ref-1"); self.save()
        self.assertIncomplete(self.verify(), "Duplicate expected")

    def test_unresolved_and_ambiguous_bindings_remain_gaps(self):
        for status in ("unresolved", "ambiguous"):
            self.bindings["references"][0]["status"] = status
            self.bindings["references"][0].pop("object_id", None)
            self.save()
            result = self.verify()
            self.assertIncomplete(result, "Source binding is " + status)
            self.assertEqual(result["counts"]["resolved_references"], 0)

    def test_stale_future_naive_and_invalid_capture_timestamps(self):
        cases = [((self.now-timedelta(hours=25)).isoformat(), "stale"),
                 ((self.now+timedelta(minutes=6)).isoformat(), "future"),
                 (self.now.replace(tzinfo=None).isoformat(), "timezone"),
                 ("not-a-timestamp", "ISO8601")]
        for timestamp, message in cases:
            self.catalogue["captured_at"] = timestamp; self.save()
            self.assertIncomplete(self.verify(), message)
        self.catalogue["captured_at"] = (self.now+timedelta(minutes=5)).isoformat(); self.save()
        self.assertTrue(self.verify()["catalogue_context_complete"])
        self.catalogue["captured_at"] = self.now.isoformat().replace("+00:00", "Z"); self.save()
        self.assertTrue(self.verify()["catalogue_context_complete"])

    def test_max_age_and_now_configuration_are_validated(self):
        for age in (0, -1, float("nan"), float("inf"), True):
            self.assertIncomplete(self.verify(max_age_hours=age), "max_age_hours")
        self.assertIncomplete(self.verify(now=self.now.replace(tzinfo=None)), "now must")
        self.catalogue["captured_at"] = (self.now-timedelta(hours=25)).isoformat(); self.save()
        self.assertTrue(self.verify(max_age_hours=26)["catalogue_context_complete"])

    def test_catalogue_hash_and_source_hash_are_validated_without_claiming_source_authenticity(self):
        self.bindings["catalogue_sha256"] = "0" * 64; self.save(rebind=False)
        self.assertIncomplete(self.verify(), "catalogue hash")
        self.reset(); self.bindings["source_snapshot_sha256"] = "wrong"; self.save()
        self.assertIncomplete(self.verify(), "source_snapshot_sha256")
        self.bindings["source_snapshot_sha256"] = "b" * 64; self.save()
        result = self.verify()
        self.assertTrue(result["catalogue_context_complete"], result)
        self.assertEqual(result["source_snapshot_sha256"], "b" * 64)
        self.assertTrue(any("alignment" in text for text in result["limitations"]))

    def test_export_escape_and_symlink_are_rejected(self):
        self.catalogue["extractions"][0]["artifact_path"] = "../outside.json"; self.save()
        self.assertIncomplete(self.verify(), "beneath catalogue")
        self.reset()
        target = self.root / "exports/objects.json"
        backup = self.root / "original-objects.json"
        target.rename(backup); target.symlink_to(backup)
        self.assertIncomplete(self.verify(), "Symlink")

    def test_selected_input_symlink_and_redirected_ancestor_are_rejected(self):
        alias = self.root / "catalogue-alias.json"; alias.symlink_to(self.catalogue_path)
        self.assertIncomplete(checker.verify(alias, self.bindings_path, now=self.now), "symlink")
        subfolder = self.root / "subfolder"
        paths = make_fixture(subfolder, now=self.now)
        relocated = self.root / "relocated"
        subfolder.rename(relocated); subfolder.symlink_to(relocated, target_is_directory=True)
        self.assertIncomplete(checker.verify(*paths, now=self.now), "ancestor")

    def test_each_object_requires_same_scope_objects_and_columns_evidence(self):
        self.catalogue["objects"][0]["evidence"].pop(); self.save()
        self.assertIncomplete(self.verify(), "lacks complete columns extraction evidence")
        self.reset(); self.catalogue["objects"][0]["evidence"][1]["extraction_id"] = "unknown"; self.save()
        self.assertIncomplete(self.verify(), "missing extraction")
        self.reset(); self.catalogue["objects"][0]["identity"]["schema"] = "other"; self.save()
        self.assertIncomplete(self.verify(), "exact declared scope")
        self.reset(); self.catalogue["extractions"][1]["scope_id"] = "not-declared"; self.save()
        self.assertIncomplete(self.verify(), "missing scope")

    def test_empty_visible_schema_is_allowed_alongside_a_bound_scope(self):
        self.catalogue["context"]["scope"].append({"scope_id":"empty-scope","catalog":"Billing","schema":"Empty","location":"synthetic-region"})
        empty = self.root / "exports/empty.json"; empty.write_text("[]\n")
        for component in ("objects","columns"):
            self.catalogue["extractions"].append({"extraction_id":"empty-"+component,"scope_id":"empty-scope","component":component,"status":"complete","artifact_path":"exports/empty.json","sha256":hashlib.sha256(empty.read_bytes()).hexdigest(),"query_id":None,"pagination_complete":True})
        self.save()
        result = self.verify()
        self.assertTrue(result["catalogue_context_complete"], result)
        self.assertEqual(result["counts"]["scopes"], 2)
        self.assertEqual(result["counts"]["objects"], 1)

    def test_catalogue_only_selection_remains_incomplete_until_references_selected(self):
        self.bindings["expected_reference_ids"] = []; self.bindings["references"] = []; self.save()
        self.assertIncomplete(self.verify(), "nonempty expected_reference_ids")

    def test_strict_json_types_and_duplicate_keys(self):
        self.catalogue["schema_version"] = True; self.save()
        self.assertIncomplete(self.verify(), "integer 1")
        self.reset(); self.catalogue["objects"][0]["columns"][0]["nullable"] = 1; self.save()
        self.assertIncomplete(self.verify(), "nullable must")
        self.reset(); self.catalogue["extractions"][0]["pagination_complete"] = 1; self.save()
        self.assertIncomplete(self.verify(), "pagination_complete must")
        self.catalogue_path.write_text('{"schema_version":1,"schema_version":1}')
        self.assertIncomplete(self.verify(), "Duplicate JSON key")

    def test_cli_returns_json_and_nonzero_for_incomplete_context(self):
        catalogue, bindings = make_fixture(self.root / "cli")
        command = [sys.executable, str(SCRIPT), str(catalogue), str(bindings)]
        good = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertTrue(json.loads(good.stdout)["catalogue_context_complete"])
        (catalogue.parent / "exports/columns.json").unlink()
        bad = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(bad.returncode, 1)
        self.assertFalse(json.loads(bad.stdout)["catalogue_context_complete"])


if __name__ == "__main__":
    unittest.main()
