"""Boundary tests for specialist result integrity; not real vendor parsing tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/data-model-accelerator/scripts/verify_specialist_results.py"
SPEC = importlib.util.spec_from_file_location("specialist_checker", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class SpecialistResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.run = self.root / "run"
        self.repo.mkdir()
        self.run.mkdir()
        (self.run / "results").mkdir()
        self.assets, self.tasks, self.results = [], [], {}
        for vendor, content in (("dbt", "select gross, paid from invoices"), ("looker", "measure: payment_rate { sql: ${paid_sum} / ${gross_sum} ;; }")):
            path = vendor + ".txt"
            (self.repo / path).write_text(content)
            aid = vendor + "-asset"
            self.assets.append({"asset_id": aid, "path": path, "sha256": hashlib.sha256(content.encode()).hexdigest(), "status": "readable", "source_types": [vendor]})
            self.tasks.append({"task_id": vendor, "source_type": vendor, "project_root": ".", "asset_ids": [aid], "result_path": "results/" + vendor + ".json"})
            oid = vendor + ":object"
            self.results[vendor] = {
                "schema_version": 1, "task_id": vendor, "source_snapshot_sha256": None,
                "asset_coverage": [{"asset_id": aid, "status": "parsed", "reason": "Synthetic test expression extracted"}],
                "objects": [{"object_id": oid, "native_id": None, "kind": "model", "name": "synthetic", "evidence": [{"asset_id": aid, "locator": "line 1"}], "grain": {"status": "unknown", "description": "Not established"}}],
                "rules": [{"rule_id": vendor + ":rule", "kind": "expression", "language": vendor,
                           "expression": content, "output_object_id": oid, "input_refs": [],
                           "context": {"evaluation_grain": "unknown", "filters": "unknown", "security": "unknown"},
                           "evidence": [{"asset_id": aid, "locator": "line 1"}],
                           "placement_candidate": {"destination": "unresolved", "rationale": "Requires shared model review"}}],
                "unresolved_references": [], "gaps": [],
            }
        self.inventory = {"schema_version": 1, "repository": {"root": str(self.repo)}, "assets": self.assets, "exclusions": [], "gaps": []}
        self.inventory_path = self.run / "inventory.json"
        self.inventory_path.write_text(json.dumps(self.inventory))
        self.snapshot = checker.digest(self.inventory_path)
        for result in self.results.values():
            result["source_snapshot_sha256"] = self.snapshot
        self.plan = {"schema_version": 1, "source_snapshot_sha256": self.snapshot, "inventory_path": "inventory.json", "status": "planned", "tasks": self.tasks}
        self.plan_path = self.run / "dispatch-plan.json"

    def check(self, omit=None):
        self.plan_path.write_text(json.dumps(self.plan))
        for vendor, result in self.results.items():
            if vendor != omit:
                (self.run / "results" / (vendor + ".json")).write_text(json.dumps(result))
        return checker.verify(self.plan_path)

    def test_complete_mixed_results_retain_context_without_approving_placement(self):
        report = self.check()
        self.assertTrue(report["extraction_complete"], report)
        self.assertEqual(report["tasks_returned"], 2)
        self.assertEqual(report["rules_returned"], 2)
        self.assertIn("does not establish", report["limitation"])

    def test_missing_specialist_does_not_pass(self):
        report = self.check(omit="looker")
        self.assertFalse(report["extraction_complete"])
        self.assertEqual(report["tasks_returned"], 1)

    def test_json_dashboard_cannot_claim_parsed_without_canonical_extraction(self):
        payload = {'id': 'd1', 'title': 'Example', 'dashboard_elements': [
            {'id': 't1', 'type': 'text', 'body_text': 'Review notes'}],
            'dashboard_filters': [], 'dashboard_layouts': []}
        source = self.repo / 'dashboard.json'
        source.write_text(json.dumps(payload))
        asset = self.assets[1]
        asset.update(path='dashboard.json', sha256=checker.digest(source))
        self.inventory_path.write_text(json.dumps(self.inventory))
        self.plan['source_snapshot_sha256'] = checker.digest(self.inventory_path)
        for result in self.results.values():
            result['source_snapshot_sha256'] = self.plan['source_snapshot_sha256']
        self.assertTrue(any('Missing canonical dashboard' in e for e in self.check()['errors']))
        canonical = checker.parse_dashboard(payload)
        self.results['looker']['dashboard_contracts'] = {'looker-asset': canonical}
        report = self.check()
        self.assertFalse(report['errors'], report)
        self.assertFalse(report['extraction_complete'])
        canonical['tiles'] = []
        self.assertTrue(any('differs from source' in e for e in self.check()['errors']))

    def test_changed_source_invalidates_dispatch(self):
        (self.repo / "dbt.txt").write_text("select an_unreviewed_metric")
        report = self.check()
        self.assertTrue(any("Source asset changed" in e for e in report["errors"]))

    def test_changed_inventory_or_stale_result_invalidates_handoff(self):
        self.results["looker"]["source_snapshot_sha256"] = "0" * 64
        report = self.check()
        self.assertTrue(any("Stale specialist" in e for e in report["errors"]))
        self.inventory_path.write_text(json.dumps(self.inventory, indent=2))
        self.assertTrue(any("Inventory changed" in e for e in self.check()["errors"]))

    def test_omitted_assigned_file_and_out_of_scope_evidence_are_rejected(self):
        self.results["dbt"]["asset_coverage"] = []
        self.results["dbt"]["objects"][0]["evidence"][0]["asset_id"] = "looker-asset"
        errors = self.check()["errors"]
        self.assertTrue(any("omitted" in e for e in errors))
        self.assertTrue(any("out-of-scope" in e for e in errors))

    def test_dangling_resolved_reference_rejected(self):
        self.results["dbt"]["rules"][0]["input_refs"] = [{"reference": "missing", "status": "resolved", "object_id": "not-real"}]
        self.assertTrue(any("nonexistent object" in e for e in self.check()["errors"]))

    def test_explicit_cross_task_reference_can_resolve(self):
        self.results["looker"]["rules"][0]["input_refs"] = [{"reference": "qualified_relation", "status": "resolved", "object_id": "dbt:object"}]
        self.assertTrue(self.check()["extraction_complete"])

    def test_unresolved_reference_remains_gap(self):
        self.results["looker"]["rules"][0]["input_refs"] = [{"reference": "missing", "status": "unresolved"}]
        self.results["looker"]["unresolved_references"] = [{"reference": "missing", "reason": "Absent from repo"}]
        report = self.check()
        self.assertFalse(report["extraction_complete"])
        self.assertTrue(any("unresolved source" in e for e in report["gaps"]))

    def test_context_free_translation_is_incomplete(self):
        self.results["looker"]["rules"][0]["context"] = {"sql": "sum(value)"}
        self.assertTrue(any("evaluation context" in e for e in self.check()["errors"]))

    def test_id_collision_is_not_silently_deduplicated(self):
        self.results["looker"]["objects"][0]["object_id"] = "dbt:object"
        self.results["looker"]["rules"][0]["output_object_id"] = "dbt:object"
        self.assertTrue(any("collision" in e for e in self.check()["errors"]))

    def test_partial_assets_and_incomplete_inventory_prevent_completeness(self):
        self.plan["status"] = "incomplete"
        self.results["dbt"]["asset_coverage"][0]["status"] = "partial"
        report = self.check()
        self.assertFalse(report["extraction_complete"])
        self.assertGreaterEqual(len(report["gaps"]), 2)

    def test_binary_cannot_be_claimed_parsed(self):
        self.assets[0]["status"] = "unsupported_binary"
        self.inventory_path.write_text(json.dumps(self.inventory))
        snapshot = checker.digest(self.inventory_path)
        self.plan["source_snapshot_sha256"] = snapshot
        for result in self.results.values():
            result["source_snapshot_sha256"] = snapshot
        self.assertTrue(any("Binary/unreadable artifact" in e for e in self.check()["errors"]))

    def test_planner_read_limit_is_preserved_by_verifier(self):
        self.assets[0]["status"] = "unreadable_limit"
        self.assets[0]["sha256"] = None
        self.inventory_path.write_text(json.dumps(self.inventory))
        snapshot = checker.digest(self.inventory_path)
        self.plan["source_snapshot_sha256"] = snapshot
        for result in self.results.values():
            result["source_snapshot_sha256"] = snapshot
        report = self.check()
        self.assertFalse(report["extraction_complete"])
        self.assertTrue(any("no bounded content hash" in e for e in report["gaps"]))

    def test_result_path_escape_and_source_symlink_rejected(self):
        self.tasks[0]["result_path"] = "../outside.json"
        (self.repo / "dbt.txt").unlink()
        (self.repo / "dbt.txt").symlink_to(self.repo / "looker.txt")
        report = self.check()
        self.assertFalse(report["extraction_complete"])
        self.assertTrue(any("Path leaves" in e for e in report["errors"]))
        self.assertTrue(any("Symlink" in e for e in report["errors"]))

    def test_relocated_source_root_symlink_is_rejected_even_with_identical_content(self):
        relocated = self.root / "relocated-source"
        self.repo.rename(relocated)
        self.repo.symlink_to(relocated, target_is_directory=True)
        report = self.check()
        self.assertFalse(report["extraction_complete"])
        self.assertTrue(any("Symlink in stored source root" in e for e in report["errors"]))

    def test_relocated_source_ancestor_symlink_is_rejected(self):
        original = self.root / "container"
        original.mkdir()
        self.repo.rename(original / "repo")
        self.repo = original / "repo"
        self.inventory["repository"]["root"] = str(self.repo)
        self.inventory_path.write_text(json.dumps(self.inventory))
        snapshot = checker.digest(self.inventory_path)
        self.plan["source_snapshot_sha256"] = snapshot
        for result in self.results.values():
            result["source_snapshot_sha256"] = snapshot
        relocated = self.root / "relocated-container"
        original.rename(relocated)
        original.symlink_to(relocated, target_is_directory=True)
        report = self.check()
        self.assertFalse(report["extraction_complete"])
        self.assertTrue(any("redirected ancestor" in e for e in report["errors"]))

    def test_invalid_shapes_return_structured_failure(self):
        self.results["dbt"]["rules"][0]["context"] = []
        self.results["dbt"]["objects"][0]["native_id"] = {}
        report = self.check()
        self.assertFalse(report["extraction_complete"])
        self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
