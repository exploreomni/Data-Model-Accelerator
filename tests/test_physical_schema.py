"""Independent schema observations reject mutually consistent bad documentation."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from ae_common import snapshot, write_json
from verify_physical_schema import reconcile, verify


class PhysicalSchemaTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {'schema_version': 1, 'kind': 'data_model_inventory', 'models': [
            {'model_id': 'gold.lines', 'physical_name': 'DB.gold.lines', 'columns': ['line_id', 'product_id', 'cost']},
            {'model_id': 'bronze.lines', 'physical_name': 'DB.bronze.lines', 'columns': ['id', 'product_id', 'cost']}]}
        self.observed = {'schema_version': 1, 'kind': 'physical_schema_observation', 'candidate_sha256': 'a' * 64,
                         'origin': 'provided_export', 'validation_scope': 'local', 'adapter_type': 'duckdb',
                         'captured_at': '2026-01-01T00:00:00Z', 'identifier_policy': 'exact',
                         'scope': ['DB.bronze', 'DB.gold'], 'relations': [
                             {k: copy.deepcopy(v) for k, v in m.items() if k in ('physical_name', 'columns')}
                             for m in self.inventory['models']]}

    def check(self):return reconcile(self.inventory, self.observed, 'a' * 64)

    def test_full_observed_denominator_passes(self):
        self.assertTrue(self.check()['passed'])
        self.assertEqual(self.check()['columns'], 6)

    def test_consistent_dictionary_inventory_omission_cannot_hide_real_column(self):
        self.inventory['models'][0]['columns'].remove('cost')
        report = self.check()
        self.assertFalse(report['passed'])
        self.assertIn('cost', report['errors'][0])

    def test_whole_model_omission_and_undeclared_relations_fail(self):
        self.inventory['models'].pop()
        self.assertFalse(self.check()['passed'])

    def test_missing_physical_relation_and_column_fail(self):
        self.observed['relations'][0]['columns'].remove('cost')
        self.assertFalse(self.check()['passed'])
        self.observed['relations'].pop()
        self.assertFalse(self.check()['passed'])

    def test_exact_quoted_case_sensitive_names_are_not_folded(self):
        self.observed['relations'][0]['columns'][1] = 'Product_ID'
        self.assertFalse(self.check()['passed'])
        self.observed['relations'][0]['physical_name'] = 'DB.gold."lines"'
        self.assertFalse(self.check()['passed'])

    def test_duplicate_columns_relations_models_and_invalid_scope_rejected(self):
        mutations = [lambda d: d['relations'][0]['columns'].append('cost'),
                     lambda d: d['relations'].append(copy.deepcopy(d['relations'][0])),
                     lambda d: d.update(scope=[]), lambda d: d.update(identifier_policy='lower'),
                     lambda d: d.update(origin='declared'), lambda d: d.update(candidate_sha256='b' * 64),
                     lambda d: d.update(schema_version=True), lambda d: d.update(captured_at='bad')]
        original = copy.deepcopy(self.observed)
        for mutate in mutations:
            self.observed = copy.deepcopy(original);mutate(self.observed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):self.check()
        self.observed = original
        self.inventory['models'][1]['model_id'] = self.inventory['models'][0]['model_id']
        with self.assertRaises(ValueError):self.check()

    def test_file_binding_and_project_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve();project = root/'candidate';project.mkdir()
            (project/'dbt_project.yml').write_text('name: fixture\nconfig-version: 2\n')
            self.observed['candidate_sha256'] = snapshot(project)['sha256']
            write_json(root/'inventory.json', self.inventory);write_json(root/'observed.json', self.observed)
            report = verify(root/'inventory.json', root/'observed.json', project)
            self.assertTrue(report['passed'])
            (project/'dbt_project.yml').write_text('name: changed\n')
            with self.assertRaises(ValueError):verify(root/'inventory.json', root/'observed.json', project)


if __name__ == '__main__':unittest.main()
