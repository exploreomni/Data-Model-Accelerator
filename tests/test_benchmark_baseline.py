"""Expected-result provenance and type checks without candidate execution."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import ae_common as common
import freeze_benchmark as baseline


class BenchmarkBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.export = self.root / 'source.json'
        self.contract = self.root / 'contract.json'
        self.output = self.root / 'frozen.json'
        self.rows = [{'tenant': 'A', 'id': 1, 'amount': '12.30', 'active': True, 'label': None}]
        self.columns = {'tenant': {'type': 'string', 'nullable': False},
                        'id': {'type': 'integer', 'nullable': False},
                        'amount': {'type': 'decimal', 'nullable': False, 'abs_tolerance': '0.01'},
                        'active': {'type': 'boolean', 'nullable': False},
                        'label': {'type': 'string', 'nullable': True}}
        self.write_export(self.rows)
        case = {'id': 'existing_totals', 'category': 'compatibility',
                'context': {'timezone': 'America/Chicago', 'watermark': '2026-09-23T00:00:00Z',
                            'principal': 'analyst-test', 'currency': 'USD',
                            'filters': {'status': ['paid', 'pending'], 'minimum': 1, 'region': None}},
                'keys': ['tenant', 'id'], 'columns': self.columns,
                'expected': {'path': 'source.json', 'sha256': common.hash_file(self.export), 'query_id': 'source-query-1'}}
        self.spec = {'schema_version': 1, 'analyst_id': 'independent-analyst',
                     'source_revision': 'source-revision-1', 'catalogue_sha256': 'a' * 64,
                     'cases': [case]}

    def write_export(self, rows):
        self.export.write_text(json.dumps({'rows': rows}))

    def freeze(self):
        self.contract.write_text(json.dumps(self.spec))
        return baseline.freeze(self.contract, self.output)

    def refresh_receipt(self):
        self.spec['cases'][0]['expected']['sha256'] = common.hash_file(self.export)

    def rewrite_bundle(self, bundle):
        bundle['baseline_sha256'] = common.hash_json({key: value for key, value in bundle.items() if key != 'baseline_sha256'})
        self.output.write_text(json.dumps(bundle))

    def test_freeze_and_verify_preserve_expected_rows_and_context(self):
        bundle = self.freeze()
        self.assertEqual(baseline.verify_baseline(self.output), bundle)
        self.assertEqual(bundle['expected_rows'], {'existing_totals': self.rows})
        self.assertEqual(bundle['contract']['cases'][0]['context'], self.spec['cases'][0]['context'])
        self.assertEqual(bundle['contract_receipt']['sha256'], common.hash_file(self.contract))
        self.assertEqual(bundle['contract']['cases'][0]['expected']['path'], str(self.export))
        self.assertEqual(bundle['contract']['cases'][0]['columns']['id']['rel_tolerance'], '0')
        self.assertEqual(bundle['contract']['cases'][0]['columns']['amount']['abs_tolerance'], '0.01')
        self.assertEqual(common.load_json(self.export)['rows'], self.rows)

    def test_correctness_requires_explicit_decision(self):
        case = self.spec['cases'][0]
        case['category'] = 'correctness'
        with self.assertRaises(ValueError):
            self.freeze()
        case['decision'] = {'id': 'decision-1', 'approved_by': 'business-owner', 'reason': 'Remove duplicated revenue'}
        self.assertEqual(self.freeze()['contract']['cases'][0]['decision'], case['decision'])

    def test_empty_expected_population_is_valid_with_explicit_schema_and_keys(self):
        self.write_export([])
        self.refresh_receipt()
        self.assertEqual(self.freeze()['expected_rows']['existing_totals'], [])
        for keys in ([], ['absent'], ['id', 'id']):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                baseline.validate_rows([], self.columns, keys)

    def test_duplicate_and_numerically_equivalent_decimal_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate composite key'):
            baseline.validate_rows(self.rows + self.rows, self.columns, ['tenant', 'id'])
        columns = {'key': {'type': 'decimal', 'nullable': False}}
        with self.assertRaisesRegex(ValueError, 'Duplicate composite key'):
            baseline.validate_rows([{'key': '1.0'}, {'key': '1.00'}], columns, ['key'])

    def test_composite_keys_preserve_tenant_scope(self):
        rows = self.rows + [dict(self.rows[0], tenant='B')]
        self.assertEqual(baseline.validate_rows(rows, self.columns, ['tenant', 'id']), rows)

    def test_null_keys_and_nullable_key_declaration_rejected(self):
        for rows, columns in (([dict(self.rows[0], id=None)], self.columns),
                              ([], dict(self.columns, id={'type': 'integer', 'nullable': True}))):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                baseline.validate_rows(rows, columns, ['id'])

    def test_exact_columns_and_types_reject_silent_coercion(self):
        variants = [dict(self.rows[0], extra=1), {key: value for key, value in self.rows[0].items() if key != 'label'},
                    dict(self.rows[0], id=True), dict(self.rows[0], id='1'), dict(self.rows[0], amount=12.3),
                    dict(self.rows[0], active=1), dict(self.rows[0], amount=None), dict(self.rows[0], tenant=1)]
        for row in variants:
            with self.subTest(row=row), self.assertRaises(ValueError):
                baseline.validate_rows([row], self.columns, ['tenant', 'id'])

    def test_nonfinite_malformed_and_extreme_decimal_strings_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1_000', ' 1', '1e1001', '1e-1001', '9' * 129, ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                baseline.validate_rows([dict(self.rows[0], amount=value)], self.columns, ['tenant', 'id'])

    def test_tolerances_validate_types_bounds_sign_and_numeric_placement(self):
        for value in ('-0.01', 'NaN', '1e1001', 0, True):
            columns = copy.deepcopy(self.columns)
            columns['amount']['abs_tolerance'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                baseline.validate_columns(columns)
        columns = copy.deepcopy(self.columns)
        columns['tenant']['abs_tolerance'] = '0'
        with self.assertRaises(ValueError):
            baseline.validate_columns(columns)
        columns = copy.deepcopy(self.columns)
        columns['id']['rel_tolerance'] = '0.01'
        with self.assertRaisesRegex(ValueError, 'Key tolerances must be zero'):
            baseline.validate_rows([], columns, ['id'])

    def test_unknown_fields_missing_context_and_invalid_identities_rejected(self):
        mutations = [lambda s: s.update(schema_version=True), lambda s: s.update(catalogue_sha256='bad'),
                     lambda s: s.update(analyst_id=' '), lambda s: s.update(source_revision=''),
                     lambda s: s.update(candidate_results='not accepted'), lambda s: s.update(cases=[]),
                     lambda s: s['cases'][0].update(category='candidate'),
                     lambda s: s['cases'][0].update(unrecognized=True),
                     lambda s: s['cases'][0]['context'].pop('principal'),
                     lambda s: s['cases'][0]['context'].update(timezone_typo='UTC'),
                     lambda s: s['cases'][0]['context'].update(filters={'nested': {'unexpected': True}}),
                     lambda s: s['cases'][0]['context'].update(filters={'': 'empty name'}),
                     lambda s: s['cases'][0]['expected'].update(query_id=''),
                     lambda s: s['cases'][0]['columns']['amount'].update(absolute_tolerance='1'),
                     lambda s: s['cases'][0]['columns']['amount'].update(nullable=1)]
        original = copy.deepcopy(self.spec)
        for mutate in mutations:
            self.spec = copy.deepcopy(original)
            mutate(self.spec)
            with self.subTest(spec=self.spec), self.assertRaises(ValueError):
                self.freeze()
            self.assertFalse(self.output.exists())

    def test_duplicate_cases_and_duplicate_json_keys_rejected(self):
        self.spec['cases'].append(copy.deepcopy(self.spec['cases'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate case id'):
            self.freeze()
        self.contract.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            baseline.freeze(self.contract, self.output)

    def test_export_receipt_hash_mismatch_rejected_before_freeze(self):
        self.export.write_text('{"rows": []}')
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            self.freeze()
        self.assertFalse(self.output.exists())

    def test_source_export_and_contract_drift_rejected(self):
        self.freeze()
        original_export = self.export.read_bytes()
        self.write_export([])
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            baseline.verify_baseline(self.output)
        self.export.write_bytes(original_export)
        self.contract.write_text(self.contract.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            baseline.verify_baseline(self.output)

    def test_bundle_digest_detects_changes(self):
        bundle = self.freeze()
        bundle['expected_rows']['existing_totals'][0]['amount'] = '99'
        self.output.write_text(json.dumps(bundle))
        with self.assertRaisesRegex(ValueError, 'digest changed'):
            baseline.verify_baseline(self.output)

    def test_rehashed_tampering_still_reconciles_rows_and_contract_to_receipts(self):
        original = self.freeze()
        for target in ('rows', 'contract'):
            bundle = copy.deepcopy(original)
            if target == 'rows':
                bundle['expected_rows']['existing_totals'][0]['id'] = True
            else:
                bundle['contract']['cases'][0]['columns']['amount']['abs_tolerance'] = '100'
            self.rewrite_bundle(bundle)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'differs? from'):
                baseline.verify_baseline(self.output)

    def test_invalid_timestamp_rejected_even_after_rehash(self):
        bundle = self.freeze()
        bundle['created_at'] = '2026-09-23T00:00:00'
        self.rewrite_bundle(bundle)
        with self.assertRaisesRegex(ValueError, 'must be UTC'):
            baseline.verify_baseline(self.output)

    def test_symlink_export_rejected(self):
        link = self.root / 'linked.json'
        link.symlink_to(self.export)
        self.spec['cases'][0]['expected']['path'] = 'linked.json'
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.freeze()

    def test_cli_freeze_verify_and_overwrite_refusal(self):
        self.contract.write_text(json.dumps(self.spec))
        command = [sys.executable, str(SCRIPTS / 'freeze_benchmark.py'), '--contract', str(self.contract), '--output', str(self.output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.output.read_bytes()
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(self.output.read_bytes(), before)
        verify = [sys.executable, str(SCRIPTS / 'freeze_benchmark.py'), '--verify', str(self.output)]
        self.assertEqual(subprocess.run(verify, capture_output=True).returncode, 0)
        self.assertNotEqual(subprocess.run(verify + ['--output', str(self.root / 'other.json')], capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
