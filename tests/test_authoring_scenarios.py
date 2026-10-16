"""Representative static authoring journeys, distinct from native acceptance."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from test_authoring_evidence import contract
from authoring_quality import evaluate
from authoring_provenance import scan_literals


@unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQL parser')
class AuthoringScenarios(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        self.output = self.root / 'candidate'; self.output.mkdir()
        self.contract = contract(); self.contract.update(mode='reviewed_candidate', assumptions=[])
        self.contract['bindings']['catalogue_sha256'] = 'c' * 64
        self.model = self.contract['models'][0]
        self.model.update(depends_on=['table:orders'], expressions={'id': 'count(1)'})

    def run_sql(self, sql):
        (self.output / 'orders.sql').write_text(sql)
        return evaluate(self.output, self.source, self.contract, ['orders.sql'], 'snowflake')

    def test_routine_technical_constants_pass_static_only(self):
        receipt = self.run_sql('select count(1) as id from orders')
        self.assertEqual(receipt['status'], 'passed')
        self.assertIn('No native execution', receipt['authority'])

    def test_oversized_batch_remains_reviewable_with_explicit_coverage_gap(self):
        from authoring_provenance import MAX_FILES
        paths = ['model-%s.sql' % n for n in range(MAX_FILES + 1)]
        for path in paths: (self.output / path).write_text('select count(1) as id from orders')
        result = evaluate(self.output, self.source, self.contract, paths, 'snowflake')
        self.assertEqual(len(result['outputs']), len(paths))
        self.assertEqual(result['status'], 'unsupported')
        self.assertIn('authoring_batch_bound_exceeded', [f['code'] for f in result['findings']])

    def test_missing_catalogue_keeps_files_and_explicit_unknown(self):
        self.contract = contract(); self.contract['models'][0].update(depends_on=['table:orders'])
        receipt = self.run_sql('select count(1) as id from orders')
        self.assertEqual(receipt['status'], 'not_run')
        self.assertEqual(receipt['mode'], 'provisional')
        self.assertTrue((self.output / 'orders.sql').is_file())

    def test_derived_expression_requires_independent_definition(self):
        self.model['expressions'] = {'id': 'amount - refund'}
        good = self.run_sql('select amount - refund as id from orders')
        self.assertEqual(good['status'], 'passed')
        bad = self.run_sql('select amount + refund as id from orders')
        self.assertEqual(bad['status'], 'failed')
        self.assertIn('expression_differs', [f['code'] for f in bad['findings']])

    def test_nested_ctes_preserve_columns_without_claiming_grain(self):
        self.model.pop('expressions')
        receipt = self.run_sql('with first as (select order_id as id from orders), second as (select * from first) select * from second')
        self.assertEqual(receipt['status'], 'passed')
        self.assertNotIn('grain', [f['code'] for f in receipt['findings']])

    def test_redacted_business_value_cannot_be_restored_by_guess(self):
        (self.source / 'orders.sql').write_text("select '[REDACTED]' as id from orders")
        self.model.pop('expressions')
        self.run_sql("select 'GUESSED_SEGMENT' as id from orders")
        candidate = scan_literals(self.output, ['orders.sql'], 'snowflake')['occurrences'][0]
        original = scan_literals(self.source, ['orders.sql'], 'snowflake')['occurrences'][0]
        self.contract['provenance'] = [{'occurrence_id': candidate['id'], 'classification': 'preserved',
            'source': {'path': original['path'], 'sha256': original['file_sha256'],
                       'span': original['span'], 'field': original['field'],
                       'expression_sha256': original['expression_sha256']}}]
        receipt = evaluate(self.output, self.source, self.contract, ['orders.sql'], 'snowflake')
        self.assertEqual(receipt['status'], 'failed')
        self.assertNotIn('GUESSED_SEGMENT', str(receipt))

    @unittest.skipUnless(importlib.util.find_spec('yaml'), 'Optional YAML parser')
    def test_omni_slice_does_not_pretend_full_native_model_validation(self):
        self.model.update(path='orders.view.yaml', depends_on=None, columns=None)
        self.model.pop('expressions')
        (self.output / 'orders.view.yaml').write_text('measures:\n  total:\n    sql: COUNT(1)\n')
        result = evaluate(self.output, self.source, self.contract, ['orders.view.yaml'], 'snowflake')
        self.assertEqual(result['status'], 'unsupported')
        self.assertIn('model_conformance_format_unsupported', [f['code'] for f in result['findings']])


if __name__ == '__main__': unittest.main()
