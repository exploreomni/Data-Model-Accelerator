"""Failure-path and semantic regression tests for the bundled SQLite example."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "data-model-accelerator" / "scripts" / "validate_example.py"
SPEC = importlib.util.spec_from_file_location("validate_example", SCRIPT)
example = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(example)


class ValidationExampleTests(unittest.TestCase):
    def copy_fixture(self, directory):
        destination = Path(directory) / "examples"
        shutil.copytree(example.EXAMPLES_DIR, destination)
        return destination

    def test_golden_export_and_all_negative_probes_execute(self):
        report = example.run_validation()
        self.assertEqual(report["status"], "passed", report)
        self.assertTrue(report["all_checks_executed"])
        self.assertEqual([r["id"] for r in report["checks"]], list(example.EXPECTED_CHECK_IDS))
        self.assertEqual(report["checks_executed"], 23)
        self.assertEqual(sum(r["id"].startswith("mutation_") for r in report["checks"]), 5)

    def test_corrupt_expected_row_fails_even_if_overall_cents_do_not_change(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.copy_fixture(directory)
            path = fixture / "expected_saas_export.json"
            expected = json.loads(path.read_text())
            # Reassign money across invoices while preserving both overall totals.
            expected["final_rows"][0][6] += 100
            expected["final_rows"][1][6] -= 100
            path.write_text(json.dumps(expected))
            report = example.run_validation(fixture)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["all_checks_executed"])
        self.assertIn("final_rows_match_export", [r["id"] for r in report["checks"] if r["status"] == "failed"])

    def test_dropped_filter_breaks_candidate_despite_unfiltered_match(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.copy_fixture(directory)
            path = fixture / "report_rows.sql"
            path.write_text(path.read_text().replace(
                "AND (:segment IS NULL OR segment = :segment)", "AND 1 = 1"))
            report = example.run_validation(fixture)
        by_id = {check["id"]: check for check in report["checks"]}
        self.assertEqual(report["status"], "failed")
        self.assertEqual(by_id["final_rows_match_export"]["status"], "passed")
        self.assertEqual(by_id["filter_context_matches_contract"]["status"], "failed")

    def test_conflicting_duplicate_source_version_blocks_sql(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.copy_fixture(directory)
            path = fixture / "source_fixture.json"
            source = json.loads(path.read_text())
            source["invoice_deliveries"][2][-1] = 6100
            path.write_text(json.dumps(source))
            with patch.object(example, "database", side_effect=AssertionError("SQL must not execute")) as create:
                report = example.run_validation(fixture)
            create.assert_not_called()
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["all_checks_executed"])
        self.assertIn("Invalid source fixture", report["error"])
        self.assertEqual(next(r for r in report["checks"] if r["id"] == "source_event_consistency")["status"], "failed")

    def test_overlapping_customer_history_blocks_sql(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.copy_fixture(directory)
            path = fixture / "source_fixture.json"
            source = json.loads(path.read_text())
            source["customer_history"][0][-1] = "2026-02-02"
            path.write_text(json.dumps(source))
            report = example.run_validation(fixture)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(next(r for r in report["checks"] if r["id"] == "source_history_nonoverlap")["status"], "failed")

    def test_orphan_temporal_dimension_fails_relationship_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.copy_fixture(directory)
            path = fixture / "source_fixture.json"
            source = json.loads(path.read_text())
            source["customer_history"] = [row for row in source["customer_history"] if row[:2] != ["A", "C2"]]
            path.write_text(json.dumps(source))
            report = example.run_validation(fixture)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(next(r for r in report["checks"] if r["id"] == "source_to_gold_relationship")["status"], "failed")

    def test_missing_input_is_failure_with_missing_check_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.copy_fixture(directory)
            (fixture / "expected_saas_export.json").unlink()
            report = example.run_validation(fixture)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks_executed"], 0)
        self.assertFalse(report["all_checks_executed"])
        self.assertEqual(len(report["missing_checks"]), 23)
        self.assertIn("expected_saas_export.json", report["error"])

    def test_cli_from_another_directory_writes_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "report.json"
            result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                                    cwd=directory, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text())
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["all_checks_executed"])
        self.assertIn("Local synthetic SQLite evidence only", result.stdout)
        self.assertTrue(any("not warehouse authorization" in limitation for limitation in report["limitations"]))

    def test_cli_nonzero_for_missing_input_and_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            # Relocate only this script and its owned fixture to test actual CLI exits.
            package = Path(directory) / "data-model-accelerator"
            scripts = package / "scripts"
            scripts.mkdir(parents=True)
            relocated = scripts / "validate_example.py"
            shutil.copyfile(SCRIPT, relocated)
            shutil.copytree(example.EXAMPLES_DIR, package / "examples")
            fixture_path = package / "examples" / "expected_saas_export.json"
            expected = json.loads(fixture_path.read_text())
            expected["final_rows"][0][4] = "Incorrect customer identity"
            fixture_path.write_text(json.dumps(expected))
            mismatch = subprocess.run([sys.executable, str(relocated)], capture_output=True, text=True, check=False)
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("final_rows_match_export", mismatch.stderr)
            fixture_path.unlink()
            missing = subprocess.run([sys.executable, str(relocated)], capture_output=True, text=True, check=False)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("Missing required bundled example input", missing.stderr)

    def test_missing_registered_check_cannot_report_success(self):
        original = example.Checks.check

        def skip_one(self, check_id, action):
            if check_id != "final_groups_match_export":
                original(self, check_id, action)

        with patch.object(example.Checks, "check", skip_one):
            report = example.run_validation()
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["all_checks_executed"])
        self.assertEqual(report["missing_checks"], ["final_groups_match_export"])


if __name__ == "__main__":
    unittest.main()
