"""Real coordinator -> extraction -> downstream evidence contract, no live APIs."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from plan_specialists import plan_repository
from extract_specialist_task import extract, main
from verify_specialist_results import verify


class SourceRoutingTests(unittest.TestCase):
    def test_fabric_dotfile_owns_native_model_parts_without_duplicate_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            source = base / 'source'
            model = source / 'workspace/Sales.SemanticModel'
            model.mkdir(parents=True)
            (model / '.platform').write_text(json.dumps({'$schema': 'https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json', 'config': {'version': '2.0', 'logicalId': '11111111-2222-3333-4444-555555555555'}, 'metadata': {'type': 'SemanticModel', 'displayName': 'Sales'}}))
            (model / 'definition.pbism').write_text('{"version":"4.0"}')
            (model / 'model.bim').write_text('{"compatibilityLevel":1600,"model":{"tables":[]}}')
            plan = plan_repository(source, base / 'plan', inspect_git=False)
            self.assertEqual([(t['source_type'], t['project_root']) for t in plan['tasks']], [('fabric', 'workspace/Sales.SemanticModel')])
            self.assertEqual(len(plan['tasks'][0]['asset_ids']), 3)

    def test_native_coalesce_git_v3_project_does_not_require_platform_kind(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            source = base / 'source'
            (source / 'warehouse/nodes').mkdir(parents=True)
            (source / 'warehouse/data.yml').write_text('defaultStorageMapping: SOURCE_DATA\nfileVersion: 3\n')
            (source / 'warehouse/locations.yml').write_text('fileVersion: 1\nlocations: [SOURCE_DATA, TARGET_DB]\n')
            (source / 'warehouse/nodes/orders.yml').write_text('fileVersion: 1\nid: source-id\nname: ORDERS\ntype: Node\noperation:\n  name: ORDERS\n  version: 1\n  type: sourceInput\n  sqlType: Source\n  locationName: SOURCE_DATA\n  metadata:\n    columns: []\n')
            plan = plan_repository(source, base / 'plan', inspect_git=False)
            self.assertEqual([(t['source_type'], t['project_root']) for t in plan['tasks']], [('coalesce', 'warehouse')])
            self.assertEqual(len(plan['tasks'][0]['asset_ids']), 3)

    def test_explicit_root_does_not_duplicate_native_subfolder_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            source = base / 'source'
            (source / 'app').mkdir(parents=True)
            (source / 'app/a.fex').write_text('TABLE FILE sales\nSUM NET BY REGION\nEND\n')
            (source / 'app/a.mas').write_text('FILENAME=SALES, SUFFIX=SQLMSS, $\nSEGMENT=SALES, SEGTYPE=S0, $\nFIELDNAME=NET, ALIAS=NET, USAGE=D12.2, ACTUAL=D8, $\n')
            (source / 'app/a.acx').write_text('SEGNAME=SALES, TABLENAME=dbo.sales, CONNECTION=WH, $\n')
            run = base / 'plan'
            plan = plan_repository(source, run, source_profiles=['webfocus:.'],
                                   inspect_git=False, require_source_adapters=True)
            self.assertEqual(len(plan['tasks']), 1)
            self.assertEqual(plan['tasks'][0]['project_root'], '.')
            (run / 'results').mkdir()
            for task in plan['tasks']:
                result = extract(run / 'dispatch-plan.json', task['task_id'])
                (run / task['result_path']).write_text(json.dumps(result))
            self.assertEqual(verify(run / 'dispatch-plan.json')['errors'], [])

    def test_strong_native_markers_route_without_guessing_generic_sql(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            source = base / 'source'
            dashboard = source / 'cdt/dashboards/revenue.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/revenue.yaml'
            dashboard.parent.mkdir(parents=True)
            dashboard.write_text('display_name: Revenue\ndashboard_preferences: {settings: {owner: synthetic}}')
            (source / 'cdt/views/v').mkdir(parents=True)
            (source / 'cdt/views/v/v.sql').write_text('select 1')
            (source / 'gcp').mkdir()
            (source / 'gcp/table.json').write_text(json.dumps({'kind': 'bigquery#table', 'tableReference': {'projectId': 'p', 'datasetId': 'd', 'tableId': 't'}}))
            (source / 'etl.json').write_text('{"contentType":"domo/dataflow-actions","data":[]}')
            (source / 'unknown.sql').write_text('select 1')
            plan_repository(source, base / 'plan', inspect_git=False)
            inv = json.loads((base / 'plan/inventory.json').read_text())
            routes = {a['path']: a['source_types'] for a in inv['assets']}
            self.assertEqual(routes['cdt/views/v/v.sql'], ['periscope'])
            self.assertEqual(routes['gcp/table.json'], ['bigquery'])
            self.assertEqual(routes['etl.json'], ['domo'])
            self.assertEqual(routes['unknown.sql'], ['generic_sql'])


@unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Pinned SQL parser required')
class SourcePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'source'
        self.root.mkdir()
        (self.root / 'orders.sql').write_text('CREATE VIEW gold.orders AS SELECT order_id, tenant_id, amount FROM raw.orders WHERE deleted_at IS NULL')
        self.run = self.base / 'run'
        self.plan = plan_repository(self.root, self.run, source_profiles=['bigquery:.'], inspect_git=False,
                                    require_source_adapters=True)
        self.plan_path = self.run / 'dispatch-plan.json'
        self.task = self.plan['tasks'][0]
        (self.run / 'results').mkdir()
        self.result = extract(self.plan_path, self.task['task_id'])

    def verify_result(self, result):
        (self.run / self.task['result_path']).write_text(json.dumps(result))
        return verify(self.plan_path)

    def test_source_rules_reach_existing_model_review_contract(self):
        result = self.verify_result(self.result)
        self.assertEqual(result['errors'], [])
        self.assertGreater(result['objects_returned'], 0)
        self.assertGreater(result['rules_returned'], 0)
        self.assertFalse(result['extraction_complete'])
        self.assertTrue(any('WHERE deleted_at IS NULL' in r['expression'] for r in self.result['rules']))
        self.assertIn('raw.orders', {r['reference'] for r in self.result['unresolved_references']})
        self.assertTrue(all(r['placement_candidate']['destination'] == 'unresolved' for r in self.result['rules']))

    def test_omitted_or_changed_expression_rejected(self):
        for mutation in ('omit', 'change'):
            candidate = copy.deepcopy(self.result)
            if mutation == 'omit':
                candidate['rules'].pop()
            else:
                candidate['rules'][0]['expression'] = 'SELECT 1'
            self.assertTrue(self.verify_result(candidate)['errors'])

    def test_forged_parser_contract_rejected(self):
        candidate = copy.deepcopy(self.result)
        candidate['source_adapter_contract']['dependencies'] = []
        self.assertTrue(self.verify_result(candidate)['errors'])

    def test_required_contract_cannot_be_omitted(self):
        candidate = copy.deepcopy(self.result)
        del candidate['source_adapter_contract']
        self.assertTrue(any('Required source adapter contract omitted' in e
                            for e in self.verify_result(candidate)['errors']))

    def test_normalized_identity_and_dependencies_cannot_be_rewritten(self):
        for field in ('native_id', 'name', 'source_details'):
            candidate = copy.deepcopy(self.result)
            candidate['objects'][0][field] = 'forged'
            self.assertTrue(any('Source adapter object omitted or altered' in e
                                for e in self.verify_result(candidate)['errors']))
        candidate = copy.deepcopy(self.result)
        rule = next(r for r in candidate['rules'] if r['input_refs'])
        rule['input_refs'] = []
        self.assertTrue(any('Source adapter dependency omitted' in e
                            for e in self.verify_result(candidate)['errors']))

    def test_changed_source_requires_new_inventory(self):
        (self.root / 'orders.sql').write_text('SELECT 1')
        with self.assertRaises(ValueError):
            extract(self.plan_path, self.task['task_id'])

    def test_output_inside_source_rejected(self):
        output = self.root / 'generated.json'
        code = main(['--plan', str(self.plan_path), '--task', self.task['task_id'], '--output', str(output)])
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
