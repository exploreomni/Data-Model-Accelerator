"""Conservative routing, coverage, safety and determinism for source dispatch."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/data-model-accelerator/scripts/plan_specialists.py"
SPEC = importlib.util.spec_from_file_location("plan_specialists", SCRIPT)
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


class SpecialistPlannerTests(unittest.TestCase):
    def test_standalone_dashboard_json_is_structurally_routed(self):
        self.write('arbitrary.json', json.dumps({'id': 'd1', 'title': 'Example',
            'dashboard_elements': [{'id': 't1', 'type': 'text', 'body_text': 'Notes'}],
            'dashboard_filters': [], 'dashboard_layouts': []}))
        self.write('generic.json', '{"id":"other","title":"Generic"}')
        _, inventory, _ = self.plan()
        assets = {a['path']: a for a in inventory['assets']}
        self.assertEqual(assets['arbitrary.json']['source_types'], ['looker'])
        self.assertEqual(assets['generic.json']['source_types'], ['unknown'])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "source"
        self.repo.mkdir()

    def write(self, relative, content):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
        return path

    def plan(self, name="output", **kwargs):
        kwargs.setdefault("inspect_git", False)
        output = self.base / name
        result = planner.plan_repository(self.repo, output, **kwargs)
        inventory = json.loads((output / "inventory.json").read_text())
        return result, inventory, output

    def test_new_warehouse_explicit_profiles_route_without_native_parse_claim(self):
        self.write('model.sql', 'select 1 as value')
        for warehouse in ('redshift', 'clickhouse', 'motherduck'):
            plan, inventory, _ = self.plan(name=warehouse, source_profiles=[warehouse + ':.'])
            self.assertEqual(inventory['assets'][0]['source_types'], [warehouse])
            self.assertEqual(plan['tasks'][0]['source_type'], warehouse)
            self.assertFalse(plan['coverage']['native_semantics_parsed'])

    def test_raw_csv_routes_to_snapshot_specialist_without_exposing_cells(self):
        data = b'id,amount\n001,PRIVATE_VALUE\n002,0.100001\n'
        self.write('raw/sales/orders.csv', data)
        plan, inventory, output = self.plan()
        self.assertEqual(plan['status'], 'planned')
        self.assertEqual([t['source_type'] for t in plan['tasks']], ['raw_csv'])
        asset = inventory['assets'][0]
        self.assertEqual(asset['raw_csv']['row_count'], 2)
        self.assertEqual(asset['raw_csv']['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(asset['raw_csv']['sha256'], asset['sha256'])
        self.assertFalse(plan['coverage']['native_semantics_parsed'])
        self.assertNotIn('PRIVATE_VALUE', json.dumps(inventory))
        prompt = (output / plan['tasks'][0]['prompt_path']).read_text()
        self.assertIn('raw-csv-source-contract.md', prompt)
        self.assertNotIn('PRIVATE_VALUE', prompt)

    def test_csv_keeps_dbt_project_ownership_even_outside_default_seed_folder(self):
        self.write('transform/dbt_project.yml', 'name: actual\nseed-paths: [fixtures]\n')
        self.write('transform/fixtures/orders.csv', 'id\n1\n')
        self.write('outside/orders.csv', 'id\n1\n')
        plan, inventory, _ = self.plan()
        assets = {a['path']: a for a in inventory['assets']}
        self.assertEqual(assets['transform/fixtures/orders.csv']['source_types'], ['dbt'])
        self.assertEqual(assets['transform/fixtures/orders.csv']['project_roots'], ['transform'])
        self.assertEqual(assets['outside/orders.csv']['source_types'], ['raw_csv'])
        self.assertEqual(assets['transform/fixtures/orders.csv']['raw_csv']['row_count'], 1)

    def test_csv_malformed_and_unreadable_metadata_preserve_routing_and_gaps(self):
        self.write('duplicate.csv', 'id,id\n1,2\n')
        self.write('ragged.csv', 'id,name\n1\n')
        self.write('encoding.csv', b'id\n\xff')
        plan, inventory, _ = self.plan()
        self.assertEqual(plan['status'], 'incomplete')
        self.assertEqual({t['source_type'] for t in plan['tasks']}, {'raw_csv'})
        kinds = {g['kind'] for g in inventory['gaps']}
        self.assertTrue({'raw_csv_duplicate_headers', 'raw_csv_ragged_rows', 'raw_csv_unsupported_encoding'} <= kinds)
        limited, metadata, _ = self.plan(name='limited', max_file_bytes=3)
        self.assertEqual(limited['status'], 'incomplete')
        self.assertTrue(all(a['sha256'] is None for a in metadata['assets']))
        self.assertEqual({t['source_type'] for t in limited['tasks']}, {'raw_csv'})

    def test_mixed_native_projects_route_by_project_not_file(self):
        self.write("transform/dbt_project.yml", "name: finance\nconfig-version: 2\n")
        self.write("transform/models/accounts.sql", "select * from raw_accounts")
        self.write("transform/models/orders.sql", "select * from raw_orders")
        self.write("looker/manifest.lkml", 'project_name: "analytics"')
        self.write("looker/models/revenue.model.lkml", 'connection: "warehouse"')
        self.write("looker/views/orders.view.lkml", "view: orders { sql_table_name: analytics.orders ;; }")
        self.write("bi/Sales.pbip", '{"version":"1.0","artifacts":[{"report":{"path":"Sales.Report"}}]}')
        self.write("bi/Sales.Report/definition.pbir", '{"version":"4.0","datasetReference":{"byPath":{"path":"../Sales.SemanticModel"}}}')
        self.write("bi/Sales.SemanticModel/definition.pbism", '{"version":"4.0"}')
        self.write("bi/Sales.SemanticModel/definition/tables/Orders.tmdl", "table Orders\n    column OrderId\n")
        plan, inventory, output = self.plan()
        self.assertEqual(plan["status"], "planned", inventory["gaps"])
        self.assertEqual({(t["source_type"], t["project_root"]) for t in plan["tasks"]},
                         {("dbt", "transform"), ("looker", "looker"), ("powerbi", "bi")})
        self.assertEqual(plan["coverage"]["selected_assets"], 10)
        self.assertEqual(plan["coverage"]["assigned_unique_assets"], 10)
        self.assertEqual(plan["review_roles"], ["warehouse_architect", "semantic_architect", "independent_qa"])
        self.assertEqual(inventory["repository"]["root"], str(self.repo.resolve()))
        self.assertFalse((output / "results").exists())
        for task in plan["tasks"]:
            prompt = (output / task["prompt_path"]).read_text()
            self.assertIn('"schema_version": 1', prompt)
            self.assertIn("source-specialists.md", prompt)
            self.assertIn("semantic-placement.md", prompt)
            self.assertIn("native_id", prompt)
            self.assertIn("Never modify sources", prompt)
            self.assertIn(plan["source_snapshot_sha256"], prompt)
            self.assertIn(str(output / task["result_path"]), prompt)

    def test_generic_sql_and_data_formats_do_not_prove_vendor(self):
        self.write("snowflake_query.sql", "SELECT DATE_TRUNC('month', created_at) FROM orders;")
        self.write("models.yml", "models:\n  - name: accounts\n")
        self.write("model.bim", '{"model":{"tables":[]}}')
        self.write("tables/Account.tmdl", "table Account\n")
        self.write("workbook.json", '{"pages":[],"title":"Sigma report"}')
        plan, inventory, _ = self.plan()
        assets = {a["path"]: a for a in inventory["assets"]}
        self.assertEqual(assets["snowflake_query.sql"]["source_types"], ["generic_sql"])
        for name in ("models.yml", "model.bim", "tables/Account.tmdl", "workbook.json"):
            self.assertEqual(assets[name]["source_types"], ["unknown"])
        self.assertEqual(plan["status"], "incomplete")
        self.assertEqual(len(plan["tasks"]), 2)

    def test_databricks_dataform_and_native_explicit_sources_route_independently(self):
        self.write("lake/databricks.yml", "bundle:\n  name: lake\nresources:\n  jobs: {}\n")
        self.write("lake/src/model.sql", "select 1")
        self.write("bq/workflow_settings.yaml", "defaultProject: sample\ndefaultDataset: warehouse\n")
        self.write("bq/definitions/orders.sqlx", "config { type: 'table' } select 1")
        self.write("bq/includes/constants.js", "module.exports = {};")
        self.write("legacy/dataform.json", '{"warehouse":"bigquery","defaultSchema":"analytics"}')
        self.write("legacy/model.sqlx", "select 1")
        self.write("native/query.sql", "select 1")
        self.write("unresolved.sql", "select * from example qualify row_number() over () = 1")
        plan, inventory, output = self.plan(source_profiles=["bigquery:native"])
        by_path = {a["path"]: a["source_types"] for a in inventory["assets"]}
        self.assertEqual(by_path["lake/src/model.sql"], ["databricks"])
        self.assertEqual(by_path["bq/definitions/orders.sqlx"], ["bigquery"])
        self.assertEqual(by_path["bq/includes/constants.js"], ["bigquery"])
        self.assertEqual(by_path["legacy/model.sqlx"], ["bigquery"])
        self.assertEqual(by_path["native/query.sql"], ["bigquery"])
        self.assertEqual(by_path["unresolved.sql"], ["generic_sql"])
        self.assertFalse(plan["coverage"]["native_semantics_parsed"])
        self.assertEqual(plan["coverage"]["specialists_executed"], 0)
        for task in plan["tasks"]:
            self.assertIn("not evidence that any specialist has executed", (output / task["prompt_path"]).read_text())

    def test_incomplete_platform_markers_and_sqlx_do_not_invent_vendor(self):
        self.write("lake/databricks.yml", "name: example\n")
        self.write("bq/workflow_settings.yaml", "name: example\n")
        self.write("other/dataform.json", '{"warehouse":"another-engine"}')
        self.write("unresolved.sqlx", "select 1")
        plan, inventory, _ = self.plan()
        self.assertFalse({"snowflake", "databricks", "bigquery"} & {t["source_type"] for t in plan["tasks"]})
        self.assertEqual(next(a for a in inventory["assets"] if a["path"] == "unresolved.sqlx")["source_types"], ["generic_sql"])

    def test_binary_packages_are_hashed_not_extracted(self):
        self.write("report.pbix", b"PK\x03\x04fake archive with SELECT secret")
        self.write("dashboard.twbx", b"PK\x03\x04not a real zip")
        self.write("data.hyper", b"\x00binaryextract")
        self.write("loose.sql", "select 1")
        plan, inventory, output = self.plan()
        assets = {a["path"]: a for a in inventory["assets"]}
        self.assertEqual(assets["report.pbix"]["source_types"], ["powerbi"])
        self.assertEqual(assets["dashboard.twbx"]["source_types"], ["tableau"])
        self.assertEqual(assets["loose.sql"]["source_types"], ["generic_sql"])
        self.assertEqual(plan["coverage"]["status_counts"]["unsupported_binary"], 3)
        self.assertEqual(plan["status"], "incomplete")
        self.assertEqual(len(list(output.rglob("*.pbix"))), 0)
        self.assertTrue(all(a["sha256"] for a in inventory["assets"]))

    def test_explicit_profiles_preserve_shared_assignments_and_evidence(self):
        self.write("shared/revenue.sql", "select revenue from source_table")
        plan, inventory, _ = self.plan(source_profiles=["dbt:shared", "looker:shared"])
        self.assertEqual({t["source_type"] for t in plan["tasks"]}, {"dbt", "looker"})
        self.assertEqual(plan["coverage"]["assigned_unique_assets"], 1)
        self.assertEqual(plan["coverage"]["task_asset_assignments"], 2)
        self.assertEqual(plan["coverage"]["shared_assets"], 1)
        self.assertEqual(plan["status"], "incomplete")
        self.assertTrue(all(e["kind"] == "explicit_user_source_profile" for e in inventory["assets"][0]["classification_evidence"]))

    def test_two_projects_of_same_source_remain_partitioned(self):
        for prefix in ("finance", "product"):
            self.write(prefix + "/dbt_project.yml", "name: " + prefix)
            self.write(prefix + "/models/core.sql", "select 1")
        plan, _, _ = self.plan()
        self.assertEqual({(t["source_type"], t["project_root"]) for t in plan["tasks"]},
                         {("dbt", "finance"), ("dbt", "product")})
        self.assertTrue(all(len(t["asset_ids"]) == 2 for t in plan["tasks"]))

    def test_nested_dbt_marker_uses_nearest_native_project(self):
        self.write("dbt_project.yml", "name: outer")
        self.write("nested/dbt_project.yml", "name: inner")
        self.write("nested/models/a.sql", "select 1")
        plan, inventory, _ = self.plan()
        asset = next(a for a in inventory["assets"] if a["path"] == "nested/models/a.sql")
        self.assertEqual(asset["project_roots"], ["nested"])
        self.assertEqual(len(plan["tasks"]), 2)

    def test_verified_native_signatures_and_standalone_scope(self):
        self.write("co/data.yml", "fileVersion: 2\nplatformKind: Snowflake\n")
        self.write("co/locations.yml", "locations: []")
        self.write("co/nodes/account.sql", "-- @id: abc\n-- @nodeType: Base\nselect 1")
        self.write("sf/snowflake.yml", "definition_version: 2\nentities:\n  app: {}\n")
        self.write("sf/warehouse.sql", "select 1")
        self.write("notebooks/example.hex.yaml", "schemaVersion: 1\nhexId: example\ncells: []")
        self.write("notebooks/unrelated.yaml", "name: unrelated")
        self.write("exports/sigma.json", json.dumps({"dataModelId":"id","documentVersion":1,"schemaVersion":1,"pages":[]}))
        self.write("exports/other.json", '{"hello":"world"}')
        plan, inventory, _ = self.plan()
        by_path = {a["path"]: a["source_types"] for a in inventory["assets"]}
        self.assertEqual(by_path["co/nodes/account.sql"], ["coalesce"])
        self.assertEqual(by_path["sf/warehouse.sql"], ["snowflake"])
        self.assertEqual(by_path["notebooks/example.hex.yaml"], ["hex"])
        self.assertEqual(by_path["exports/sigma.json"], ["sigma"])
        self.assertEqual(by_path["notebooks/unrelated.yaml"], ["unknown"])
        self.assertEqual(by_path["exports/other.json"], ["unknown"])

    def test_credentials_dependencies_and_symlinks_are_not_read(self):
        self.write("query.sql", "select 1")
        self.write(".env", "NEVER_DISCLOSE=top-secret-sentinel")
        self.write("profiles.yml", "password: top-secret-sentinel")
        self.write("service-account.json", '{"private_key":"top-secret-sentinel"}')
        self.write("node_modules/private/query.sql", "top-secret-sentinel")
        external = self.base / "external"
        external.mkdir()
        (external / "outside.sql").write_text("top-secret-sentinel")
        os.symlink(external, self.repo / "linked_directory")
        os.symlink(external / "outside.sql", self.repo / "linked.sql")
        plan, inventory, output = self.plan()
        self.assertEqual([a["path"] for a in inventory["assets"]], ["query.sql"])
        self.assertEqual(len(inventory["exclusions"]), 6)
        serialized = "".join(p.read_text() for p in output.rglob("*") if p.is_file())
        self.assertNotIn("top-secret-sentinel", serialized)
        self.assertEqual(plan["coverage"]["read_bytes"], len("select 1"))

    def test_deterministic_manifest_and_asset_ids_change_with_content(self):
        self.write("query.sql", "select 1")
        first, inventory1, out1 = self.plan("first")
        second, inventory2, out2 = self.plan("second")
        self.assertEqual((out1 / "inventory.json").read_bytes(), (out2 / "inventory.json").read_bytes())
        self.assertEqual((out1 / "dispatch-plan.json").read_bytes(), (out2 / "dispatch-plan.json").read_bytes())
        self.assertEqual(first["source_snapshot_sha256"], hashlib.sha256((out1 / "inventory.json").read_bytes()).hexdigest())
        self.write("query.sql", "select 2")
        third, inventory3, _ = self.plan("third")
        self.assertNotEqual(first["source_snapshot_sha256"], third["source_snapshot_sha256"])
        self.assertNotEqual(inventory1["assets"][0]["asset_id"], inventory3["assets"][0]["asset_id"])

    def test_output_safety_and_existing_output_never_overwritten(self):
        self.write("query.sql", "select 1")
        with self.assertRaises(planner.PlanningError):
            planner.plan_repository(self.repo, self.repo / "analysis", inspect_git=False)
        self.assertFalse((self.repo / "analysis").exists())
        _, _, output = self.plan()
        before = (output / "inventory.json").read_bytes()
        with self.assertRaises(planner.PlanningError):
            planner.plan_repository(self.repo, output, inspect_git=False)
        self.assertEqual(before, (output / "inventory.json").read_bytes())
        self.assertFalse((output / "results").exists())

    def test_output_symlink_into_input_is_rejected(self):
        self.write("query.sql", "select 1")
        os.symlink(self.repo, self.base / "output-link")
        with self.assertRaises(planner.PlanningError):
            self.plan("output-link")

    def test_bounded_file_count_is_explicitly_incomplete(self):
        for name in ("a.sql", "b.sql", "c.sql"):
            self.write(name, "select 1")
        plan, inventory, _ = self.plan(max_files=2)
        self.assertEqual(plan["status"], "incomplete")
        self.assertEqual(len(inventory["assets"]), 2)
        self.assertTrue(plan["coverage"]["limits_hit"])
        self.assertTrue(any(g["kind"] == "file_count_limit" for g in inventory["gaps"]))
        self.assertEqual(plan["coverage"]["assigned_unique_assets"], 2)

    def test_byte_limits_preserve_unreadable_assets_without_invented_hashes(self):
        self.write("a.sql", "select 1")
        self.write("b.sql", "select " + "x" * 100)
        plan, inventory, _ = self.plan(max_file_bytes=16)
        second = inventory["assets"][1]
        self.assertEqual(second["status"], "unreadable_limit")
        self.assertIsNone(second["sha256"])
        self.assertIn("no content hash", second["asset_id_basis"])
        self.assertEqual(plan["coverage"]["hashed_assets"], 1)
        self.assertEqual(plan["coverage"]["assigned_unique_assets"], 2)
        plan2, inventory2, _ = self.plan("total-bound", max_total_bytes=8)
        self.assertTrue(any(g["kind"] == "total_read_limit" for g in inventory2["gaps"]))
        self.assertLessEqual(plan2["coverage"]["read_bytes"], 8)

    def test_missing_and_remote_powerbi_dependencies_stay_gaps(self):
        self.write("local/Report.Report/definition.pbir", '{"datasetReference":{"byPath":{"path":"../Missing.SemanticModel"}}}')
        self.write("remote/Report.Report/definition.pbir", '{"datasetReference":{"byConnection":{"connectionString":"secret-connection-value"}}}')
        plan, inventory, output = self.plan()
        self.assertEqual(plan["status"], "incomplete")
        kinds = {g["kind"] for g in inventory["gaps"]}
        self.assertTrue({"missing_reference", "remote_reference"}.issubset(kinds))
        self.assertNotIn("secret-connection-value", (output / "inventory.json").read_text())

    def test_source_profile_validation(self):
        self.write("query.sql", "select 1")
        for value in ("snowflake:../source", "nonexistent:.", "sigma:missing", "dbt:/absolute"):
            with self.subTest(value=value), self.assertRaises(planner.PlanningError):
                self.plan(source_profiles=[value])
        plan, inventory, _ = self.plan(source_profiles=["snowflake:."])
        self.assertEqual(inventory["assets"][0]["source_types"], ["snowflake"])
        self.assertEqual(plan["tasks"][0]["project_root"], ".")

    @unittest.skipUnless(shutil.which("git"), "Git not installed")
    def test_non_git_fixture_has_explicit_repository_status(self):
        self.write("query.sql", "select 1")
        _, inventory, _ = self.plan(inspect_git=True)
        self.assertEqual(inventory["repository"]["status"], "non_git")
        self.assertIsNone(inventory["repository"]["commit"])
        self.assertIsNone(inventory["repository"]["dirty"])

    def test_cli_exit_codes_for_planned_incomplete_and_hard_error(self):
        self.write("query.sql", "select 1")
        command = [sys.executable, str(SCRIPT), str(self.repo), "--no-git"]
        planned = subprocess.run(command + ["--output", str(self.base / "planned")], capture_output=True, text=True, check=False)
        self.assertEqual(planned.returncode, 0, planned.stderr)
        repeated = subprocess.run(command + ["--output", str(self.base / "planned")], capture_output=True, text=True, check=False)
        self.assertEqual(repeated.returncode, 1)
        self.write("unknown.json", "{}")
        incomplete = subprocess.run(command + ["--output", str(self.base / "incomplete")], capture_output=True, text=True, check=False)
        self.assertEqual(incomplete.returncode, 2, incomplete.stderr)
        self.assertIn("no specialists executed", incomplete.stdout)

    def test_unreadable_source_is_preserved_and_hard_failure(self):
        self.write("query.sql", "select 1")
        with patch.object(planner.os, "open", side_effect=PermissionError("Denied")):
            plan, inventory, _ = self.plan()
        self.assertEqual(plan["coverage"]["hard_errors"], 1)
        self.assertEqual(inventory["assets"][0]["status"], "unreadable")
        self.assertIsNone(inventory["assets"][0]["sha256"])
        self.assertEqual(plan["coverage"]["assigned_unique_assets"], 1)

    def test_generated_dbt_evidence_is_gap_unless_explicitly_selected(self):
        self.write("dbt_project.yml", "name: project")
        self.write("models/a.sql", "select 1")
        self.write("target/manifest.json", json.dumps({"metadata":{"dbt_schema_version":"https://schemas.getdbt.com/dbt/manifest/v12.json"},"nodes":{},"sources":{}}))
        self.write("target/unneeded.sql", "select 2")
        default, inventory, _ = self.plan()
        self.assertEqual(default["status"], "incomplete")
        self.assertTrue(any(g["kind"] == "compiled_artifacts_excluded" for g in inventory["gaps"]))
        included, inventory2, _ = self.plan("included", include_paths=["target/manifest.json"])
        self.assertEqual(included["status"], "planned", inventory2["gaps"])
        manifest = next(a for a in inventory2["assets"] if a["path"] == "target/manifest.json")
        self.assertEqual(manifest["source_types"], ["dbt"])
        self.assertEqual(manifest["project_roots"], ["."])
        self.assertNotIn("target/unneeded.sql", {a["path"] for a in inventory2["assets"]})
        profiled, inventory3, _ = self.plan("profiled", source_profiles=["dbt:target"])
        self.assertIn("target/manifest.json", {a["path"] for a in inventory3["assets"]})
        self.assertTrue(inventory3["explicit_include_paths"])

    def test_admin_exclusions_and_business_context_keep_meaningful_scope(self):
        self.write("dbt/dbt_project.yml", "name: demo")
        self.write("dbt/README.md", "Revenue means a human decision; unresolved.")
        self.write("dbt/models/python_model.py", "raise RuntimeError('must never run')")
        self.write("dbt/analysis/check.ipynb", '{"cells":[]}')
        self.write("dbt/node_modules/danger.py", "raise RuntimeError('must never read')")
        self.write(".gitignore", "private")
        self.write("LICENSE", "Administrative license")
        plan, inventory, _ = self.plan(source_profiles=["dbt:dbt"])
        self.assertEqual(plan["status"], "planned", inventory["gaps"])
        self.assertEqual(len(inventory["assets"]), 4)
        self.assertTrue(all(a["source_types"] == ["dbt"] for a in inventory["assets"]))
        self.assertEqual({e["reason"] for e in inventory["exclusions"]}, {"administrative_file_excluded", "dependency_or_generated_directory"})


if __name__ == "__main__":
    unittest.main()
