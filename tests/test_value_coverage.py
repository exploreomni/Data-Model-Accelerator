"""Mandatory independent value cases cannot be replaced by passing native tests."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from ae_common import hash_file, load_json, write_json
from verify_value_coverage import verify
import test_benchmark_results as fixtures


class ValueCoverageTests(unittest.TestCase):
    prepare = fixtures.BenchmarkResultsTests.prepare
    save_actual = fixtures.BenchmarkResultsTests.save_actual
    def setUp(self):
        fixtures.BenchmarkResultsTests.setUp(self)
        self.prepare()
        baseline = load_json(self.baseline_path)
        self.inventory_path = self.root/'inventory.json'
        write_json(self.inventory_path, {'kind': 'data_model_inventory', 'models': [
            {'model_id': 'fact', 'columns': list(self.columns)}]})
        self.value_path = self.root/'values.json'
        self.value_contract = {'schema_version': 1, 'kind': 'source_value_contract',
                               'source_revision': baseline['contract']['source_revision'],
                               'catalogue_sha256': baseline['contract']['catalogue_sha256'],
                               'baseline_sha256': baseline['baseline_sha256'], 'preserved_fields': [
                                   {'model_id': 'fact', 'model_column': name, 'case_id': 'compat',
                                    'case_column': name, 'source_reference': 'source.raw.' + name}
                                   for name in ('amount', 'tax', 'label')]}
        write_json(self.value_path, self.value_contract)

    def coverage(self):return verify(self.value_path, self.baseline_path, self.actual_path, self.inventory_path, self.project)

    def test_preserved_values_have_explicit_case_and_field_denominator(self):
        result = self.coverage()
        self.assertTrue(result['passed']);self.assertEqual(len(result['fields']), 3)

    def test_wrong_attribution_and_consistent_amount_tax_fail(self):
        source = self.root/'actual-compat.json';original = load_json(source)
        for mutation in ({'label': 'wrong-existing-dimension'}, {'amount': '11.00', 'tax': '1.10'}):
            rows = copy.deepcopy(original);rows['rows'][0].update(mutation)
            source.write_text(json.dumps(rows))
            actual = load_json(self.actual_path)
            actual['cases'][0]['result']['sha256'] = hash_file(source)
            self.save_actual(actual)
            with self.subTest(mutation=mutation):self.assertFalse(self.coverage()['passed'])

    def test_missing_required_case_is_failure(self):
        actual = load_json(self.actual_path);actual['cases'] = actual['cases'][1:];self.save_actual(actual)
        self.assertFalse(self.coverage()['passed'])

    def test_empty_unknown_or_duplicate_field_binding_refused(self):
        original = copy.deepcopy(self.value_contract)
        for mode in ('empty', 'unknown', 'duplicate', 'context'):
            changed = copy.deepcopy(original)
            if mode == 'empty':changed['preserved_fields'] = []
            elif mode == 'unknown':changed['preserved_fields'][0]['case_column'] = 'missing'
            elif mode == 'duplicate':changed['preserved_fields'].append(changed['preserved_fields'][0])
            else:changed['source_revision'] = 'wrong'
            self.value_path.write_text(json.dumps(changed))
            with self.subTest(mode=mode), self.assertRaises(ValueError):self.coverage()


if __name__ == '__main__':unittest.main()
