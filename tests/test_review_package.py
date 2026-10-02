"""Synthetic manifest tests; these files are not customer approval evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from test_catalogue import make_fixture


SCRIPT = Path(__file__).resolve().parents[1] / "skills/data-model-accelerator/scripts/verify_review_package.py"
SPEC = importlib.util.spec_from_file_location("review_checker", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ReviewPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        artifacts = []
        for role in sorted(checker.ROLES):
            content = ("Synthetic unit-test artifact: " + role).encode()
            (self.root / (role + ".txt")).write_bytes(content)
            artifacts.append({"id": role, "role": role, "path": role + ".txt", "sha256": hashlib.sha256(content).hexdigest()})
        self.package = {
            "schema_version": 1,
            "source_snapshot_sha256": next(a["sha256"] for a in artifacts if a["role"] == "source_inventory"),
            "target": {"framework": "fixture", "warehouse": "SQLite", "versions": "local-test", "environment": "local-only"},
            "artifacts": artifacts,
            "required_test_ids": sorted(checker.LOCAL_CATEGORIES),
            "tests": [{"id": c, "category": c, "scope": "local", "status": "pass", "artifact_id": "test_evidence"} for c in sorted(checker.LOCAL_CATEGORIES)],
            "not_applicable": [], "unresolved_blockers": [],
        }
        self.manifest = self.root / "review-package.json"
        self.catalogue_path, self.bindings_path = make_fixture(self.root / "catalogue")
        self.package["warehouse_catalogues"] = [{"catalogue_artifact_id": "raw-catalogue", "bindings_artifact_id": "raw-bindings", "max_age_hours": 24}]
        self.refresh_catalogue_artifacts(sync_source=True)
        self.add_documentation_fixture()

    def replace_artifact_json(self, aid, body):
        artifact = next(a for a in self.package["artifacts"] if a["id"] == aid)
        content = json.dumps(body).encode()
        (self.root / artifact["path"]).write_bytes(content)
        artifact["sha256"] = hashlib.sha256(content).hexdigest()

    def add_documentation_fixture(self):
        self.model_inventory = {"schema_version": 1, "kind": "data_model_inventory", "models": [
            {"model_id": layer + ".invoices", "physical_name": "FIXTURE." + layer + ".invoices",
             "layer": layer, "columns": ["tenant_id", "invoice_id"]} for layer in ("bronze", "silver", "gold")]}
        self.replace_artifact_json("model_spec", self.model_inventory)
        self.dictionary = {"schema_version": 1, "kind": "data_dictionary",
            "model_inventory_sha256": next(a["sha256"] for a in self.package["artifacts"] if a["id"] == "model_spec"),
            "models": [{"model_id": model["model_id"], "description": "Synthetic invoice identifiers",
                "grain": "One fixture invoice per tenant", "columns": [{
                    "name": name, "description": "Synthetic source identifier", "data_type": "VARCHAR",
                    "nullability": "Logical required; physical enforcement unverified", "key_role": "Composite identity",
                    "source": "Fixture input", "transformation": "Identity", "units": "Identifier",
                    "classification": "Synthetic", "validation": "Fixture grain test"} for name in model["columns"]]}
                for model in self.model_inventory["models"]]}
        self.replace_artifact_json("data_dictionary", self.dictionary)
        readable = b"# Synthetic unit fixture dictionary\nTenant and invoice identifiers at each layer.\n"
        (self.root / "dictionary.md").write_bytes(readable)
        self.package["artifacts"].append({"id": "dictionary-readable", "role": "data_dictionary",
            "path": "dictionary.md", "sha256": hashlib.sha256(readable).hexdigest()})
        self.package["model_documentation"] = {"inventory_artifact_id": "model_spec",
            "dictionary_artifact_id": "data_dictionary", "readable_dictionary_artifact_id": "dictionary-readable", "layers": [
                {"layer": layer, "document_artifact_id": "layer_documentation", "erd_artifact_id": "erd",
                 "model_ids": [layer + ".invoices"]} for layer in ("bronze", "silver", "gold")]}

    def refresh_catalogue_artifacts(self, sync_source=False):
        catalogue = json.loads(self.catalogue_path.read_text())
        bindings = json.loads(self.bindings_path.read_text())
        bindings["catalogue_sha256"] = hashlib.sha256(self.catalogue_path.read_bytes()).hexdigest()
        if sync_source:
            bindings["source_snapshot_sha256"] = self.package["source_snapshot_sha256"]
        self.bindings_path.write_text(json.dumps(bindings))
        new_artifacts = [("raw-catalogue", "warehouse_catalogue", self.catalogue_path),
                         ("raw-bindings", "catalogue_bindings", self.bindings_path)]
        for index, extraction in enumerate(catalogue["extractions"]):
            if extraction.get("artifact_path"):
                new_artifacts.append(("raw-export-" + str(index), "catalogue_evidence", self.catalogue_path.parent / extraction["artifact_path"]))
        ids = {item[0] for item in new_artifacts}
        self.package["artifacts"] = [a for a in self.package["artifacts"] if a["id"] not in ids]
        for aid, role, path in new_artifacts:
            self.package["artifacts"].append({"id": aid, "role": role, "path": str(path.relative_to(self.root)),
                                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    def verify(self, stage="local"):
        self.manifest.write_text(json.dumps(self.package))
        return checker.verify(self.manifest, stage)

    def test_complete_declared_local_evidence(self):
        self.assertEqual(self.verify(), [])

    def test_changed_code_invalidates_evidence_integrity(self):
        (self.root / "code.txt").write_text("changed after tests")
        self.assertTrue(any("Artifact changed" in e for e in self.verify()))

    def test_missing_and_skipped_checks_do_not_pass(self):
        self.package["tests"].pop()
        self.package["tests"][0]["status"] = "skipped"
        errors = self.verify()
        self.assertTrue(any("result missing" in e for e in errors))
        self.assertTrue(any("not passed" in e for e in errors))

    def test_deleting_category_from_denominator_does_not_pass(self):
        self.package["tests"] = [t for t in self.package["tests"] if t["category"] != "security"]
        self.package["required_test_ids"].remove("security")
        self.assertTrue(any("category: security" in e for e in self.verify()))

    def test_local_results_cannot_establish_target_validation(self):
        errors = self.verify("target")
        self.assertTrue(any("Unqualified target.environment" in e for e in errors))
        self.assertTrue(any("target_execution" in e for e in errors))

    def test_target_scoped_evidence_can_be_complete(self):
        self.package["target"]["environment"] = "synthetic-dev"
        catalogue = json.loads(self.catalogue_path.read_text())
        catalogue["origin"] = "provided_export"
        self.catalogue_path.write_text(json.dumps(catalogue))
        self.refresh_catalogue_artifacts()
        for test in self.package["tests"]:
            test["scope"] = "target"
        for c in checker.TARGET_CATEGORIES:
            self.package["required_test_ids"].append(c)
            self.package["tests"].append({"id": c, "category": c, "scope": "target", "status": "pass", "artifact_id": "test_evidence"})
        self.assertEqual(self.verify("target"), [])

    def test_escaped_and_symlinked_artifacts_rejected(self):
        artifact = self.package["artifacts"][0]
        artifact["path"] = "../outside.txt"
        self.assertTrue(any("within bundle" in e for e in self.verify()))
        (self.root / "link.txt").symlink_to(self.root / "code.txt")
        artifact["path"] = "link.txt"
        self.assertTrue(any("symlink" in e for e in self.verify()))

    def test_duplicate_json_keys_rejected(self):
        self.manifest.write_text('{"schema_version":1,"schema_version":1}')
        self.assertTrue(any("Duplicate JSON key" in e for e in checker.verify(self.manifest)))

    def test_invalid_shapes_report_errors(self):
        self.package["tests"][0]["artifact_id"] = []
        self.package["artifacts"][0]["role"] = []
        self.assertTrue(self.verify())

    def test_blockers_prevent_completeness(self):
        self.package["unresolved_blockers"] = ["Metric owner has not selected a definition"]
        self.assertTrue(any("Unresolved blockers" in e for e in self.verify()))

    def test_only_history_replay_allow_documented_inapplicability(self):
        self.package["not_applicable"] = [{"category": "security", "rationale": "No time", "artifact_id": "decisions"}]
        self.assertTrue(any("Invalid not_applicable" in e for e in self.verify()))

    def test_missing_specialist_dispatch_blocks_even_with_passing_declared_tests(self):
        self.package["specialist_dispatch_artifact_id"] = "not-returned"
        self.assertTrue(any("Specialist dispatch" in e for e in self.verify()))

    def test_specialist_source_evidence_is_actually_inspected(self):
        content = json.dumps({"schema_version": 1, "inventory_path": "missing-inventory.json", "tasks": []}).encode()
        (self.root / "dispatch.json").write_bytes(content)
        self.package["artifacts"].append({"id": "dispatch", "role": "lineage", "path": "dispatch.json", "sha256": hashlib.sha256(content).hexdigest()})
        self.package["specialist_dispatch_artifact_id"] = "dispatch"
        self.assertTrue(any("Cannot verify specialist handoff" in e for e in self.verify()))

    def test_complete_specialist_bundle_rechecks_actual_source_integrity(self):
        source = self.root / "original-source"
        source.mkdir()
        (source / "project.yml").write_text("name: synthetic")
        source_hash = hashlib.sha256((source / "project.yml").read_bytes()).hexdigest()
        inventory = {"schema_version": 1, "repository": {"root": str(source)},
                     "assets": [{"asset_id": "project", "path": "project.yml", "sha256": source_hash, "status": "readable"}], "gaps": []}
        content = json.dumps(inventory).encode()
        (self.root / "source_inventory.txt").write_bytes(content)
        snapshot = hashlib.sha256(content).hexdigest()
        next(a for a in self.package["artifacts"] if a["role"] == "source_inventory")["sha256"] = snapshot
        self.package["source_snapshot_sha256"] = snapshot
        dispatch = {"schema_version": 1, "source_snapshot_sha256": snapshot, "inventory_path": "source_inventory.txt", "status": "planned",
                    "tasks": [{"task_id": "config", "asset_ids": ["project"], "result_path": "specialist.json"}]}
        result = {"schema_version": 1, "task_id": "config", "source_snapshot_sha256": snapshot,
                  "asset_coverage": [{"asset_id": "project", "status": "parsed", "reason": "Metadata-only fixture; no business models"}],
                  "objects": [], "rules": [], "unresolved_references": [], "gaps": []}
        for aid, path, body in (("dispatch", "dispatch.json", dispatch), ("specialist", "specialist.json", result)):
            data = json.dumps(body).encode()
            (self.root / path).write_bytes(data)
            self.package["artifacts"].append({"id": aid, "role": "lineage", "path": path, "sha256": hashlib.sha256(data).hexdigest()})
        self.package["specialist_dispatch_artifact_id"] = "dispatch"
        self.refresh_catalogue_artifacts(sync_source=True)
        self.assertEqual(self.verify(), [])
        (source / "project.yml").write_text("name: changed_after_extraction")
        self.assertTrue(any("Specialist extraction is incomplete" in e for e in self.verify()))

    def test_removing_dispatch_association_cannot_downgrade_specialist_package(self):
        self.test_complete_specialist_bundle_rechecks_actual_source_integrity()
        del self.package["specialist_dispatch_artifact_id"]
        self.assertTrue(any("Specialist dispatch association" in e for e in self.verify()))

    def test_orphaned_specialist_result_still_requires_dispatch(self):
        self.test_complete_specialist_bundle_rechecks_actual_source_integrity()
        del self.package["specialist_dispatch_artifact_id"]
        self.package["artifacts"] = [a for a in self.package["artifacts"] if a["id"] != "dispatch"]
        self.assertTrue(any("Specialist dispatch association" in e for e in self.verify()))

    def test_removing_catalogue_requirement_does_not_pass(self):
        del self.package["warehouse_catalogues"]
        self.assertTrue(any("warehouse_catalogues" in e for e in self.verify()))

    def test_raw_metadata_exports_must_be_included_as_hashed_artifacts(self):
        self.package["artifacts"] = [a for a in self.package["artifacts"] if a["role"] != "catalogue_evidence"]
        self.assertTrue(any("raw metadata exports" in e for e in self.verify()))

    def test_catalogue_binding_cannot_use_another_repository_snapshot(self):
        bindings = json.loads(self.bindings_path.read_text())
        bindings["source_snapshot_sha256"] = "0" * 64
        self.bindings_path.write_text(json.dumps(bindings))
        self.refresh_catalogue_artifacts()
        self.assertTrue(any("different repository snapshot" in e for e in self.verify()))

    def test_catalogue_binding_is_checked_beyond_artifact_hashes(self):
        bindings = json.loads(self.bindings_path.read_text())
        bindings["references"][0]["column_paths"] = [["not_a_real_column"]]
        self.bindings_path.write_text(json.dumps(bindings))
        self.refresh_catalogue_artifacts()
        self.assertTrue(any("catalogue context is incomplete" in e for e in self.verify()))

    def test_stale_catalogue_cannot_pass_review(self):
        catalogue = json.loads(self.catalogue_path.read_text())
        catalogue["captured_at"] = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        self.catalogue_path.write_text(json.dumps(catalogue))
        self.refresh_catalogue_artifacts()
        self.assertTrue(any("catalogue context is incomplete" in e for e in self.verify()))

    def test_synthetic_catalogue_cannot_establish_target_validation(self):
        self.assertTrue(any("Synthetic catalogue" in e for e in self.verify("target")))

    def test_catalogue_freshness_bound_must_be_explicit(self):
        del self.package["warehouse_catalogues"][0]["max_age_hours"]
        self.assertTrue(self.verify())

    def test_documentation_association_is_required(self):
        del self.package["model_documentation"]
        self.assertTrue(any("model_documentation" in e for e in self.verify()))

    def test_dictionary_is_required_despite_erd_and_model_spec(self):
        self.package["artifacts"] = [a for a in self.package["artifacts"] if a["id"] != "data_dictionary"]
        self.assertTrue(any("data_dictionary" in e for e in self.verify()))

    def test_readable_dictionary_cannot_be_omitted_or_aliased_to_json(self):
        association = self.package["model_documentation"]
        del association["readable_dictionary_artifact_id"]
        self.package["artifacts"] = [a for a in self.package["artifacts"] if a["id"] != "dictionary-readable"]
        (self.root / "dictionary.md").unlink()
        self.assertTrue(any("hashed data_dictionary" in e for e in self.verify()))
        association["readable_dictionary_artifact_id"] = "data_dictionary"
        self.assertTrue(any("separate rendering" in e for e in self.verify()))

    def test_all_three_layer_documents_are_required(self):
        self.package["model_documentation"]["layers"].pop(1)
        self.assertTrue(any("bronze, silver and gold" in e for e in self.verify()))

    def test_each_layer_requires_a_real_erd_artifact(self):
        self.package["model_documentation"]["layers"][0]["erd_artifact_id"] = "code"
        self.assertTrue(any("hashed erd" in e for e in self.verify()))

    def test_empty_layer_document_cannot_pass_with_correct_hash(self):
        artifact = next(a for a in self.package["artifacts"] if a["id"] == "layer_documentation")
        (self.root / artifact["path"]).write_bytes(b"  \n")
        artifact["sha256"] = hashlib.sha256(b"  \n").hexdigest()
        self.assertTrue(any("Documentation artifact is empty" in e for e in self.verify()))

    def test_dictionary_cannot_omit_columns_even_with_fresh_hash(self):
        self.dictionary["models"][0]["columns"].pop()
        self.replace_artifact_json("data_dictionary", self.dictionary)
        self.assertTrue(any("column coverage differs" in e for e in self.verify()))

    def test_dictionary_cannot_duplicate_models_or_columns(self):
        self.dictionary["models"][0]["columns"].append(self.dictionary["models"][0]["columns"][0])
        self.dictionary["models"].append(self.dictionary["models"][0])
        self.replace_artifact_json("data_dictionary", self.dictionary)
        errors = self.verify()
        self.assertTrue(any("Duplicate dictionary model" in e for e in errors))
        self.assertTrue(any("Duplicate dictionary column" in e for e in errors))

    def test_dictionary_requires_lineage_and_null_policy(self):
        del self.dictionary["models"][0]["columns"][0]["source"]
        self.dictionary["models"][1]["columns"][0]["nullability"] = ""
        self.replace_artifact_json("data_dictionary", self.dictionary)
        self.assertTrue(any("required definition/lineage/quality fields" in e for e in self.verify()))

    def test_dictionary_version_cannot_lag_model_changes(self):
        self.model_inventory["models"][0]["columns"].append("new_column")
        self.replace_artifact_json("model_spec", self.model_inventory)
        self.assertTrue(any("different model inventory version" in e for e in self.verify()))

    def test_layer_documentation_cannot_claim_wrong_models(self):
        self.package["model_documentation"]["layers"][0]["model_ids"] = ["gold.invoices"]
        self.assertTrue(any("Layer documentation coverage differs" in e for e in self.verify()))

    def test_documentation_invalid_shapes_report_errors(self):
        self.model_inventory["models"][0]["columns"] = [{"name": "not-a-string"}]
        self.replace_artifact_json("model_spec", self.model_inventory)
        self.assertTrue(any("column denominator" in e for e in self.verify()))


if __name__ == "__main__":
    unittest.main()
