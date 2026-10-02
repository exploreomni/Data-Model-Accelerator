"""Independent expected-versus-actual comparison; no native execution claims."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import ae_common as common
import freeze_benchmark as frozen
import benchmark_results as benchmark


def row(tenant='A', row_id=1, amount='10.00', tax='1.00', label=None, active=True):
    return {'tenant': tenant, 'id': row_id, 'amount': amount, 'tax': tax, 'label': label, 'active': active}


class BenchmarkResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'dbt_project.yml').write_text('name: candidate\nconfig-version: 2\n')
        self.baseline_path = self.root / 'baseline.json'
        self.actual_path = self.root / 'actual.json'
        self.contract_path = self.root / 'contract.json'
        self.columns = {'tenant': {'type': 'string', 'nullable': False},
                        'id': {'type': 'integer', 'nullable': False},
                        'amount': {'type': 'decimal', 'nullable': False},
                        'tax': {'type': 'decimal', 'nullable': False},
                        'label': {'type': 'string', 'nullable': True},
                        'active': {'type': 'boolean', 'nullable': False}}
        self.expected = {'compat': [row(), row(tenant='B', amount='20.00')],
                         'correct': [row(amount='9.50')]}
        self.context = {'timezone': 'America/Chicago', 'watermark': '2026-09-23T00:00:00Z',
                        'principal': 'test-analyst', 'currency': 'USD',
                        'filters': {'minimum': 1, 'status': ['paid', 'pending']}}

    def prepare(self, actual_rows=None):
        cases = []
        for case_id, expected_rows in self.expected.items():
            path = self.root / ('expected-' + case_id + '.json')
            common.write_json(path, {'rows': expected_rows})
            case = {'id': case_id, 'category': 'compatibility' if case_id == 'compat' else 'correctness',
                    'context': copy.deepcopy(self.context), 'keys': ['tenant', 'id'],
                    'columns': copy.deepcopy(self.columns),
                    'expected': {'path': path.name, 'sha256': common.hash_file(path), 'query_id': 'source-' + case_id}}
            if case_id == 'correct':
                case['decision'] = {'id': 'approved-correction', 'approved_by': 'business-owner', 'reason': 'Accepted corrected definition'}
            cases.append(case)
        contract = {'schema_version': 1, 'analyst_id': 'independent-analyst', 'source_revision': 'source-1',
                    'catalogue_sha256': 'a' * 64, 'cases': cases}
        common.write_json(self.contract_path, contract)
        baseline = frozen.freeze(self.contract_path, self.baseline_path)
        actual = {'schema_version': 1, 'baseline_sha256': baseline['baseline_sha256'],
                  'candidate_sha256': common.snapshot(self.project)['sha256'],
                  'analyst_id': contract['analyst_id'], 'cases': []}
        for case in cases:
            case_id = case['id']
            rows = copy.deepcopy((self.expected if actual_rows is None else actual_rows)[case_id])
            path = self.root / ('actual-' + case_id + '.json')
            common.write_json(path, {'rows': rows})
            actual['cases'].append({'id': case_id, 'context': copy.deepcopy(case['context']),
                                    'result': {'path': path.name, 'sha256': common.hash_file(path), 'query_id': 'candidate-' + case_id}})
        common.write_json(self.actual_path, actual)
        return actual

    def save_actual(self, actual):
        self.actual_path.write_text(json.dumps(actual))

    def compare(self):
        return benchmark.compare(self.baseline_path, self.actual_path, self.project)

    def case(self, report, case_id='compat'):
        return next(case for case in report['cases'] if case['id'] == case_id)

    def assert_failed_case(self, report, case_id='compat'):
        case = self.case(report, case_id)
        self.assertFalse(case['passed'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['coverage']['expected_cases'], 2)
        self.assertEqual(report['coverage']['passed_cases'], 1)
        self.assertEqual(report['coverage']['failed_cases'], 1)
        return case

    def test_both_categories_compound_keys_and_reordered_rows_pass(self):
        actual = copy.deepcopy(self.expected)
        actual['compat'].reverse()
        self.prepare(actual)
        report = self.compare()
        self.assertTrue(report['passed'])
        self.assertEqual(report['kind'], 'accuracy_benchmark')
        self.assertEqual(report['coverage'], {'expected_cases': 2, 'observed_cases': 2, 'passed_cases': 2, 'failed_cases': 0})
        self.assertEqual(report['categories'], {'compatibility': {'expected': 1, 'passed': 1, 'failed': 0},
                                              'correctness': {'expected': 1, 'passed': 1, 'failed': 0}})
        self.assertEqual(report['actual_sha256'], common.hash_file(self.actual_path))
        self.assertEqual(report['candidate_sha256'], common.snapshot(self.project)['sha256'])

    def test_missing_case_counts_as_failure_without_narrowing_denominator(self):
        actual = self.prepare()
        actual['cases'] = [actual['cases'][0]]
        self.save_actual(actual)
        report = self.compare()
        case = self.assert_failed_case(report, 'correct')
        self.assertTrue(case['errors'])
        self.assertEqual(report['coverage']['observed_cases'], 1)
        self.assertEqual(report['categories']['correctness'], {'expected': 1, 'passed': 0, 'failed': 1})

    def test_empty_actual_case_list_cannot_vacuously_pass(self):
        actual = self.prepare()
        actual['cases'] = []
        self.save_actual(actual)
        report = self.compare()
        self.assertFalse(report['passed'])
        self.assertEqual(report['coverage'], {'expected_cases': 2, 'observed_cases': 0, 'passed_cases': 0, 'failed_cases': 2})

    def test_unknown_and_duplicate_case_ids_are_global_errors(self):
        original = self.prepare()
        for mode in ('unknown', 'duplicate'):
            actual = copy.deepcopy(original)
            extra = copy.deepcopy(actual['cases'][0])
            if mode == 'unknown':
                extra['id'] = 'unreviewed'
            actual['cases'].append(extra)
            self.save_actual(actual)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.compare()

    def test_missing_and_extra_composite_keys_are_counted(self):
        actual = copy.deepcopy(self.expected)
        actual['compat'][1]['tenant'] = 'C'
        self.prepare(actual)
        case = self.assert_failed_case(self.compare())
        self.assertEqual(case['missing_keys'], 1)
        self.assertEqual(case['extra_keys'], 1)
        self.assertEqual(case['value_mismatches'], 0)

    def test_empty_expected_and_actual_rows_pass(self):
        self.expected['compat'] = []
        self.prepare()
        self.assertTrue(self.compare()['passed'])

    def test_empty_expected_with_unexpected_row_fails(self):
        self.expected['compat'] = []
        actual = copy.deepcopy(self.expected)
        actual['compat'] = [row()]
        self.prepare(actual)
        case = self.assert_failed_case(self.compare())
        self.assertEqual(case['extra_keys'], 1)

    def test_duplicate_actual_keys_fail_without_affecting_other_case(self):
        actual = copy.deepcopy(self.expected)
        actual['compat'].append(copy.deepcopy(actual['compat'][0]))
        self.prepare(actual)
        self.assertTrue(self.assert_failed_case(self.compare())['errors'])

    def test_context_bool_integer_coercion_and_currency_drift_fail(self):
        original = self.prepare()
        for mode in ('typed_filter', 'currency', 'timezone', 'principal', 'watermark'):
            actual = copy.deepcopy(original)
            context = actual['cases'][0]['context']
            if mode == 'typed_filter':
                context['filters']['minimum'] = True
            else:
                context[mode] = 'changed'
            self.save_actual(actual)
            with self.subTest(mode=mode):
                self.assertTrue(self.assert_failed_case(self.compare())['errors'])

    def test_decimal_representation_equivalence_and_tolerance_boundary(self):
        self.columns['amount']['abs_tolerance'] = '0.01'
        actual = copy.deepcopy(self.expected)
        actual['compat'][0]['amount'] = '10.0100'
        actual['compat'][1]['amount'] = '2e1'
        actual['correct'][0]['tax'] = '1.000'
        self.prepare(actual)
        self.assertTrue(self.compare()['passed'])

    def test_relative_tolerance_uses_absolute_expected_value_and_max(self):
        self.columns['amount'].update(abs_tolerance='0.25', rel_tolerance='0.1')
        self.expected['compat'] = [row(amount='-100'), row(tenant='B', amount='0')]
        actual = copy.deepcopy(self.expected)
        actual['compat'][0]['amount'] = '-90'
        actual['compat'][1]['amount'] = '0.25'
        self.prepare(actual)
        self.assertTrue(self.compare()['passed'])

    def test_tiny_difference_outside_tolerance_is_preserved(self):
        self.columns['amount']['abs_tolerance'] = '0.000000000000000000000000000005'
        self.expected['compat'][0]['amount'] = '1'
        actual = copy.deepcopy(self.expected)
        actual['compat'][0]['amount'] = '1.00000000000000000000000000001'
        self.prepare(actual)
        self.assertEqual(self.assert_failed_case(self.compare())['value_mismatches'], 1)

    def test_decimal_cancellation_does_not_round_outside_difference_into_tolerance(self):
        self.columns['amount']['abs_tolerance'] = '10000000000000000000000000000'
        self.expected['compat'][0]['amount'] = '-10000000000000000000000000000'
        actual = copy.deepcopy(self.expected)
        actual['compat'][0]['amount'] = '1'
        self.prepare(actual)
        self.assertEqual(self.assert_failed_case(self.compare())['value_mismatches'], 1)

    def test_null_and_numeric_zero_are_different(self):
        self.columns['amount']['nullable'] = True
        self.expected['compat'][0]['amount'] = None
        actual = copy.deepcopy(self.expected)
        actual['compat'][0]['amount'] = '0'
        self.prepare(actual)
        case = self.assert_failed_case(self.compare())
        self.assertEqual(case['value_mismatches'], 1)
        self.assertTrue(any(detail.get('column') == 'amount' for detail in case['details']))

    def test_row_schema_null_key_and_type_errors_are_failed_cases(self):
        original = self.prepare()
        original_rows = copy.deepcopy(self.expected['compat'])
        variants = [dict(original_rows[0], amount=10.0), dict(original_rows[0], id=True),
                    dict(original_rows[0], id=None), dict(original_rows[0], active=1),
                    dict(original_rows[0], amount='NaN'), dict(original_rows[0], extra='unreviewed'),
                    {key: value for key, value in original_rows[0].items() if key != 'label'}]
        for changed_row in variants:
            actual = copy.deepcopy(original)
            path = self.root / 'actual-compat.json'
            path.write_text(json.dumps({'rows': [changed_row, original_rows[1]]}))
            actual['cases'][0]['result']['sha256'] = common.hash_file(path)
            self.save_actual(actual)
            with self.subTest(row=changed_row):
                self.assertTrue(self.assert_failed_case(self.compare())['errors'])

    def test_changed_actual_export_is_case_failure(self):
        self.prepare()
        (self.root / 'actual-compat.json').write_text('{"rows":[]}')
        self.assertTrue(self.assert_failed_case(self.compare())['errors'])

    def test_changed_source_export_invalidates_global_baseline(self):
        self.prepare()
        (self.root / 'expected-compat.json').write_text('{"rows":[]}')
        with self.assertRaises(ValueError):
            self.compare()

    def test_changed_baseline_and_candidate_pins_are_global_errors(self):
        original = self.prepare()
        for field in ('baseline_sha256', 'candidate_sha256'):
            actual = copy.deepcopy(original)
            actual[field] = 'f' * 64
            self.save_actual(actual)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.compare()

    def test_candidate_file_drift_is_global_error(self):
        self.prepare()
        (self.project / 'dbt_project.yml').write_text('name: changed\n')
        with self.assertRaises(ValueError):
            self.compare()

    def test_wrong_analyst_and_unknown_top_level_fields_are_global_errors(self):
        original = self.prepare()
        for mutation in (lambda a: a.update(analyst_id='different-analyst'),
                         lambda a: a.update(unreviewed=True), lambda a: a.update(schema_version=True)):
            actual = copy.deepcopy(original)
            mutation(actual)
            self.save_actual(actual)
            with self.assertRaises(ValueError):
                self.compare()

    def test_full_cell_mismatch_count_survives_detail_cap(self):
        self.expected['compat'] = [row(row_id=index, amount='0', tax='0') for index in range(120)]
        actual = copy.deepcopy(self.expected)
        for item in actual['compat']:
            item.update(amount='1', tax='1')
        self.prepare(actual)
        case = self.assert_failed_case(self.compare())
        self.assertEqual(case['value_mismatches'], 240)
        self.assertLessEqual(len(case['details']), 100)
        self.assertGreater(len(case['details']), 0)
        for detail in case['details']:
            self.assertTrue({'key', 'column', 'expected', 'actual'} <= set(detail))


    def test_cli_pass_fail_exit_codes_and_external_new_output(self):
        self.prepare()
        output = self.root / 'report.json'
        args = ['--baseline', str(self.baseline_path), '--actual', str(self.actual_path),
                '--project', str(self.project), '--output', str(output)]
        self.assertEqual(benchmark.main(args), 0)
        self.assertTrue(common.load_json(output)['passed'])
        self.assertEqual(benchmark.main(args), 1)
        args[-1] = str(self.project / 'report.json')
        self.assertEqual(benchmark.main(args), 1)
        actual = common.load_json(self.actual_path)
        actual['cases'] = []
        self.save_actual(actual)
        args[-1] = str(self.root / 'failed.json')
        self.assertEqual(benchmark.main(args), 1)
        self.assertEqual(common.load_json(args[-1])['coverage']['failed_cases'], 2)


if __name__ == '__main__':
    unittest.main()
