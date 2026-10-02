"""Independent synthetic Hex replay QA; optional local engines, no native services.

Expected data was frozen from the scenario, raw data and manual CSV before the
author read the candidate implementation. SQL and Python mutations are confined
to temporary copies of this invented fixture.
"""
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator'
CASE = SKILL / 'examples/hex-omni-e2e'
sys.path.insert(0, str(SKILL / 'scripts'))
OPTIONAL = all(importlib.util.find_spec(name) for name in
               ('duckdb', 'pandas', 'sqlglot', 'yaml', 'jsonschema'))
if OPTIONAL:
    import hex_execution as execution
    import hex_source
    import yaml


@unittest.skipUnless(OPTIONAL, 'Optional Hex E2E dependencies are required')
class HexExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.adjustments = execution.load_inputs(CASE)
        cls.graph = hex_source.inspect_repo(CASE / 'input/repo')
        cls.expected = json.loads((CASE / 'expected/expected_reports.json').read_text())
        cls.expected_rows = json.loads((CASE / 'expected/expected_rows.json').read_text())
        cls.context = json.loads((CASE / 'target/omni/report-context.json').read_text())
        spec = importlib.util.spec_from_file_location('independent_hex_oracle', CASE / 'expected/oracle.py')
        cls.oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.oracle)

    def temporary_case(self):
        temporary = tempfile.TemporaryDirectory(prefix='dma-hex-qa-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'case'
        shutil.copytree(CASE / 'input', root / 'input')
        shutil.copytree(CASE / 'target', root / 'target')
        return root

    def mutate_native(self, root, filename, mutate):
        path = root / 'input/repo' / filename
        document = yaml.safe_load(path.read_text())
        mutate(document)
        path.write_text(yaml.safe_dump(document, sort_keys=False))
        return hex_source.inspect_repo(root / 'input/repo')

    def assert_values(self, actual, expected, path='result'):
        if isinstance(expected, dict):
            self.assertIsInstance(actual, dict, path)
            self.assertEqual(set(actual), set(expected), path)
            for key in expected:
                self.assert_values(actual[key], expected[key], path + '.' + key)
        elif isinstance(expected, list):
            self.assertIsInstance(actual, list, path)
            self.assertEqual(len(actual), len(expected), path)
            for index, (left, right) in enumerate(zip(actual, expected)):
                self.assert_values(left, right, path + '[' + str(index) + ']')
        elif path.endswith('payment_rate') and expected is not None:
            self.assertIsNotNone(actual, path)
            self.assertLessEqual(abs(Decimal(str(actual)) - Decimal(str(expected))), Decimal('1e-12'), path)
        else:
            if type(expected) is int:
                self.assertIs(type(actual), int, path + ': cents/counts must remain integers')
            self.assertEqual(actual, expected, path)

    def reports_from_models(self, con, parameters=None, root=CASE):
        omni = execution.OmniSubset(root / 'target/omni')
        context = json.loads((root / 'target/omni/report-context.json').read_text())
        parameters = execution.parameters(parameters, context['defaults'])
        return {role: omni.report(con, role, parameters, context['reports'][role])[0]
                for role in ('revenue', 'retention', 'executive')}

    def model_rows(self, con, model, expected):
        frame, _ = execution.sql_frame(con, 'SELECT * FROM DMA_HEX.GOLD.' + model)
        actual = execution.rows(frame)
        fields = set(expected[0])
        result = []
        for row in actual:
            row['month'] = row.pop('invoice_month')
            if model == 'FCT_CUSTOMER_MONTH':
                for key in ('has_invoice', 'has_paid_invoice'):
                    self.assertIn(row[key], (0, 1))
                    row[key] = bool(row[key])
            self.assertTrue(fields <= set(row))
            result.append({key: row[key] for key in fields})
        keys = ('tenant_id', 'invoice_id') if model == 'FCT_INVOICES' else ('tenant_id', 'customer_id', 'month')
        identities = [tuple(row[key] for key in keys) for row in result]
        self.assertEqual(len(identities), len(set(identities)), 'Target grain/fanout')
        return sorted(result, key=lambda row: tuple(row[key] for key in keys))

    def test_all_13_source_and_omni_scenarios_match_frozen_oracle(self):
        self.assertEqual(len(self.expected['scenarios']), 13)
        with execution.connection(self.raw, self.adjustments) as con:
            compiled = execution.build_models(con, CASE / 'target/dbt')
            self.assertEqual(len(compiled), 7)
            for scenario in self.expected['scenarios']:
                with self.subTest(scenario=scenario['scenario_id']):
                    source, _, _ = execution.replay_source(CASE, self.graph, self.raw, self.adjustments, scenario['parameters'])
                    self.assert_values(source, scenario['outputs'])
                    self.assert_values(self.reports_from_models(con, scenario['parameters']), scenario['outputs'])

    def test_all_invoice_and_customer_month_rows_match(self):
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            for model, key in (('FCT_INVOICES', 'invoices'), ('FCT_CUSTOMER_MONTH', 'customer_months')):
                self.assertEqual(len(self.expected_rows[key]), 10)
                self.assert_values(self.model_rows(con, model, self.expected_rows[key]), self.expected_rows[key])

    def test_every_native_cell_is_executed_or_retained(self):
        self.assertEqual(self.graph['counts']['cells'], 24)
        _, intermediate, traces = execution.replay_source(CASE, self.graph, self.raw, self.adjustments)
        self.assertEqual(set(intermediate), {'revenue', 'retention', 'executive'})
        executed = set()
        for item in intermediate.values():
            executed.update(item['executed_cell_ids'])
            identities = [(row['tenant_id'], row['invoice_id']) for row in item['enriched']]
            self.assertEqual(len(identities), 10)
            self.assertEqual(len(set(identities)), 10)
        self.assertEqual(executed, {cell['id'] for cell in self.graph['cells']})
        self.assertTrue(any(t.get('status') == 'config_preserved_native_rendering_unavailable' for t in traces))
        self.assertEqual(len(intermediate['revenue']['retained_what_if_values']), 4)

    def test_five_invalid_or_denied_contexts_rejected(self):
        self.assertEqual(len(self.expected['error_scenarios']), 5)
        for scenario in self.expected['error_scenarios']:
            with self.subTest(scenario=scenario['scenario_id']):
                with self.assertRaises(execution.HexExecutionError):
                    execution.replay_source(CASE, self.graph, self.raw, self.adjustments, scenario['parameters'])

    def test_exact_replay_and_arrival_shuffle_preserve_rows_and_reports(self):
        raw = copy.deepcopy(self.raw)
        for table in ('INVOICE_CDC', 'PAYMENT_CDC', 'CUSTOMER_HISTORY'):
            raw[table] += copy.deepcopy(raw[table])
            random.Random(20260910).shuffle(raw[table])
        source, _, _ = execution.replay_source(CASE, self.graph, raw, self.adjustments)
        self.assert_values(source, self.expected['scenarios'][0]['outputs'])
        with execution.connection(raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            self.assert_values(self.model_rows(con, 'FCT_INVOICES', self.expected_rows['invoices']), self.expected_rows['invoices'])
            self.assert_values(self.reports_from_models(con), self.expected['scenarios'][0]['outputs'])

    def test_cents_beyond_float_exactness_preserved(self):
        adjustments = copy.deepcopy(self.adjustments)
        adjustments[0]['ADJUSTMENT_CENTS'] = 9007199254740993
        expected = self.oracle.calculate(self.raw, adjustments)
        source, intermediate, _ = execution.replay_source(CASE, self.graph, self.raw, adjustments)
        invoice = next(row for row in intermediate['revenue']['enriched'] if row['tenant_id'] == 'A' and row['invoice_id'] == 'I1')
        self.assertEqual(invoice['adjustment_cents'], 9007199254740993)
        self.assert_values(source, {key: expected[key] for key in ('revenue', 'retention', 'executive')})
        with execution.connection(self.raw, adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            self.assert_values(self.model_rows(con, 'FCT_INVOICES', expected['invoices']), expected['invoices'])

    def test_integer_overflow_is_rejected_or_stays_exact(self):
        adjustments = copy.deepcopy(self.adjustments)
        adjustments[0]['ADJUSTMENT_CENTS'] = 9223372036854775800
        expected = self.oracle.calculate(self.raw, adjustments)
        try:
            source, _, _ = execution.replay_source(CASE, self.graph, self.raw, adjustments)
        except execution.HexExecutionError as error:
            self.assertRegex(str(error).lower(), 'overflow|range|integer|cents')
        else:
            self.assert_values(source, {key: expected[key] for key in ('revenue', 'retention', 'executive')})

    def test_present_empty_adjustment_export_means_zero_adjustment(self):
        expected = self.oracle.calculate(self.raw, [])
        source, _, _ = execution.replay_source(CASE, self.graph, self.raw, [])
        self.assert_values(source, {key: expected[key] for key in ('revenue', 'retention', 'executive')})
        with execution.connection(self.raw, []) as con:
            execution.build_models(con, CASE / 'target/dbt')
            self.assert_values(self.model_rows(con, 'FCT_INVOICES', expected['invoices']), expected['invoices'])

    def test_overpayment_preserves_negative_balance(self):
        raw = copy.deepcopy(self.raw)
        raw['PAYMENT_CDC'].append({'TENANT_ID': 'A', 'PAYMENT_ID': 'P3', 'INVOICE_ID': 'I2', 'PAID_CENTS': 12000, 'IS_DELETED': False, 'SEQUENCE': 99})
        expected = self.oracle.calculate(raw, self.adjustments)
        source, intermediate, _ = execution.replay_source(CASE, self.graph, raw, self.adjustments)
        invoice = next(row for row in intermediate['revenue']['enriched'] if row['tenant_id'] == 'A' and row['invoice_id'] == 'I2')
        self.assertEqual(invoice['outstanding_cents'], -3000)
        self.assert_values(source, {key: expected[key] for key in ('revenue', 'retention', 'executive')})

    def test_invalid_raw_contracts_fail_before_sql(self):
        mutations = []
        raw = copy.deepcopy(self.raw); raw['INVOICE_CDC'][0]['AMOUNT_CENTS'] = None; mutations.append(('null cents', raw, self.adjustments))
        raw = copy.deepcopy(self.raw); conflict = copy.deepcopy(raw['INVOICE_CDC'][0]); conflict['AMOUNT_CENTS'] += 1; raw['INVOICE_CDC'].append(conflict); mutations.append(('CDC conflict', raw, self.adjustments))
        raw = copy.deepcopy(self.raw); overlap = copy.deepcopy(raw['CUSTOMER_HISTORY'][0]); overlap['SEGMENT'] = 'Other'; raw['CUSTOMER_HISTORY'].append(overlap); mutations.append(('history overlap', raw, self.adjustments))
        raw = copy.deepcopy(self.raw); raw['CUSTOMER_HISTORY'] = [row for row in raw['CUSTOMER_HISTORY'] if not (row['TENANT_ID'] == 'A' and row['CUSTOMER_ID'] == 'C2')]; mutations.append(('temporal orphan', raw, self.adjustments))
        adjustments = copy.deepcopy(self.adjustments); adjustments.append(copy.deepcopy(adjustments[0])); mutations.append(('adjustment duplicate', self.raw, adjustments))
        adjustments = copy.deepcopy(self.adjustments); adjustments[0]['INVOICE_ID'] = 'Missing'; mutations.append(('adjustment orphan', self.raw, adjustments))
        for label, raw, adjustments in mutations:
            with self.subTest(mutation=label), self.assertRaises(execution.HexExecutionError):
                execution.connection(raw, adjustments)

    def test_external_sql_denied_by_parser_and_connection(self):
        with tempfile.TemporaryDirectory(prefix='dma-hex-sentinel-') as temp:
            marker = Path(temp) / 'sentinel.csv'; marker.write_text('value\n17\n')
            sql = "SELECT * FROM READ_CSV('" + str(marker) + "')"
            with execution.connection(self.raw, self.adjustments) as con:
                with self.assertRaises(execution.HexExecutionError):
                    execution.sql_frame(con, sql)
                with self.assertRaisesRegex(Exception, 'disabled|permission|external'):
                    con.execute(sql).fetchall()

    def test_unsafe_python_has_no_side_effect(self):
        with tempfile.TemporaryDirectory(prefix='dma-hex-python-') as temp:
            marker = Path(temp) / 'must-not-exist'
            for source in ("open(" + repr(str(marker)) + ", 'w').write('x')", 'import os\nx = os.environ', "import pandas as pd\nx = pd.read_csv('/etc/passwd')", 'x = globals()[name]'):
                with self.subTest(source=source), self.assertRaises(execution.HexExecutionError):
                    execution.PythonSubset({}, self.adjustments).run(source)
                self.assertFalse(marker.exists())

    def test_cross_tenant_python_merge_rejected(self):
        import pandas as pd
        env = {'left': pd.DataFrame([{'TENANT_ID': 'A', 'INVOICE_ID': 'I1'}]), 'right': pd.DataFrame(self.adjustments)}
        with self.assertRaisesRegex(execution.HexExecutionError, 'tenant/invoice'):
            execution.PythonSubset(env, self.adjustments).run('result = left.merge(right, on=["INVOICE_ID"], how="left", validate="many_to_one")')

    def test_dbt_hooks_rejected(self):
        with self.assertRaises(execution.HexExecutionError):
            execution.render_dbt("{{ config(materialized='table', pre_hook='delete from x') }} SELECT 1")

    def test_duplicate_dbt_model_identity_rejected(self):
        root = self.temporary_case()
        shutil.copyfile(root / 'target/dbt/models/gold/fct_invoices.sql', root / 'target/dbt/models/silver/fct_invoices.sql')
        with execution.connection(self.raw, self.adjustments) as con, self.assertRaises(execution.HexExecutionError):
            execution.build_models(con, root / 'target/dbt')

    def test_changed_dbt_destination_rejected(self):
        root = self.temporary_case(); path = root / 'target/dbt/models/gold/fct_invoices.sql'
        source = path.read_text(); self.assertIn("alias='FCT_INVOICES'", source)
        path.write_text(source.replace("alias='FCT_INVOICES'", "alias='WRONG_FACT'"))
        with execution.connection(self.raw, self.adjustments) as con, self.assertRaisesRegex(execution.HexExecutionError, 'destination/config'):
            execution.build_models(con, root / 'target/dbt')

    def test_quoted_physical_case_mismatch_rejected(self):
        with self.assertRaises(execution.HexExecutionError):
            execution.checked_sql('SELECT * FROM "dma_hex"."raw"."invoice_cdc"', execution.RAW_RELATIONS)

    def test_quoted_physical_column_case_mismatch_rejected(self):
        with self.assertRaises(execution.HexExecutionError):
            execution.checked_sql('SELECT "amount_cents" FROM DMA_HEX.RAW.INVOICE_CDC', execution.RAW_RELATIONS)

    def test_omitted_revenue_calculation_rejected(self):
        root = self.temporary_case()
        def remove_calculation(document):
            document['cells'] = [cell for cell in document['cells'] if cell.get('cellLabel') != 'Monthly summary']
        graph = self.mutate_native(root, 'revenue.hex.yaml', remove_calculation)
        self.assertTrue(any(gap['kind'] == 'unbound_variable' for gap in graph['gaps']))
        with self.assertRaisesRegex(execution.HexExecutionError, 'unresolved static'):
            execution.replay_source(root, graph, self.raw, self.adjustments)

    def test_changed_native_connection_and_missing_component_rejected(self):
        root = self.temporary_case()
        def change_connection(document):
            document['cells'][0]['config']['dataConnectionId'] = '22222222-2222-4222-8222-222222222222'
            document['sharedAssets']['dataConnections'][0]['dataConnectionId'] = '22222222-2222-4222-8222-222222222222'
        graph = self.mutate_native(root, 'shared-revenue.hex.yaml', change_connection)
        self.assertTrue(graph['static_coverage_complete'])
        with self.assertRaisesRegex(execution.HexExecutionError, 'connection binding'):
            execution.replay_source(root, graph, self.raw, self.adjustments)
        (root / 'input/repo/shared-revenue.hex.yaml').unlink()
        graph = hex_source.inspect_repo(root / 'input/repo')
        with self.assertRaisesRegex(execution.HexExecutionError, 'unresolved static'):
            execution.replay_source(root, graph, self.raw, self.adjustments)

    def test_source_join_mutation_caught_by_grain_and_reports(self):
        root = self.temporary_case()
        def mutate(document):
            source = document['cells'][0]['config']['source']
            self.assertIn('i.TENANT_ID = p.TENANT_ID AND ', source)
            document['cells'][0]['config']['source'] = source.replace('i.TENANT_ID = p.TENANT_ID AND ', '')
        graph = self.mutate_native(root, 'shared-revenue.hex.yaml', mutate)
        self.assertTrue(graph['static_coverage_complete'])
        source, intermediate, _ = execution.replay_source(root, graph, self.raw, self.adjustments)
        identities = [(row['tenant_id'], row['invoice_id']) for row in intermediate['revenue']['enriched']]
        self.assertGreater(len(identities), len(set(identities)), 'Mutation must reach the intended fanout')
        with self.assertRaises(AssertionError):
            self.assert_values(source, self.expected['scenarios'][0]['outputs'])

    def test_target_join_mutation_caught_by_invoice_grain(self):
        root = self.temporary_case(); path = root / 'target/dbt/models/gold/fct_invoices.sql'
        source = path.read_text(); self.assertIn('i.TENANT_ID = p.TENANT_ID AND ', source)
        path.write_text(source.replace('i.TENANT_ID = p.TENANT_ID AND ', ''))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            with self.assertRaisesRegex(AssertionError, 'Target grain/fanout'):
                self.model_rows(con, 'FCT_INVOICES', self.expected_rows['invoices'])

    def test_canceling_adjustment_errors_do_not_hide_in_total(self):
        adjustments = copy.deepcopy(self.adjustments)
        first = next(row for row in adjustments if row['TENANT_ID'] == 'A' and row['INVOICE_ID'] == 'I1')
        first['ADJUSTMENT_CENTS'] += 100
        adjustments.append({'TENANT_ID': 'A', 'INVOICE_ID': 'I3', 'ADJUSTMENT_CENTS': -100, 'REASON': 'deliberate QA mutation'})
        source, _, _ = execution.replay_source(CASE, self.graph, self.raw, adjustments)
        expected = self.expected['scenarios'][0]['outputs']
        self.assertEqual(sum(row['net_cents'] for row in source['revenue']), sum(row['net_cents'] for row in expected['revenue']))
        with self.assertRaises(AssertionError):
            self.assert_values(source, expected)

    def test_omni_changed_metric_and_filter_caught(self):
        root = self.temporary_case(); path = root / 'target/omni/invoices.view'
        view = yaml.safe_load(path.read_text())
        view['measures']['payment_rate']['sql'] = '${paid_cents_total} / NULLIF(${revenue_cents} + 1, 0)'
        path.write_text(yaml.safe_dump(view, sort_keys=False))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            actual = self.reports_from_models(con, root=root)
            with self.assertRaises(AssertionError):
                self.assert_values(actual, self.expected['scenarios'][0]['outputs'])
            context_path = root / 'target/omni/report-context.json'
            context = json.loads(context_path.read_text())
            context['reports']['retention']['filters'].pop('invoices.net_cents')
            context_path.write_text(json.dumps(context))
            actual = self.reports_from_models(con, root=root)
            self.assertGreater(len(actual['retention']), len(self.expected['scenarios'][0]['outputs']['retention']))

    def test_omni_access_contract_change_rejected(self):
        root = self.temporary_case(); path = root / 'target/omni/billing.topic'
        document = yaml.safe_load(path.read_text()); document.pop('access_filters')
        path.write_text(yaml.safe_dump(document, sort_keys=False))
        with self.assertRaisesRegex(execution.HexExecutionError, 'tenant access'):
            execution.OmniSubset(root / 'target/omni')

    def test_omni_cross_tenant_join_caught_by_reports(self):
        root = self.temporary_case(); path = root / 'target/omni/relationships'
        relationships = yaml.safe_load(path.read_text())
        target = next(item for item in relationships if item['join_to_view'] == 'customer_month')
        clause = '${invoices.tenant_id} = ${customer_month.tenant_id} AND '
        self.assertIn(clause, target['on_sql'])
        target['on_sql'] = target['on_sql'].replace(clause, '')
        path.write_text(yaml.safe_dump(relationships, sort_keys=False))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            actual = self.reports_from_models(con, root=root)
            self.assertGreater(sum(row['invoice_count'] for row in actual['revenue']),
                               sum(row['invoice_count'] for row in self.expected['scenarios'][0]['outputs']['revenue']))
            with self.assertRaises(AssertionError):
                self.assert_values(actual, self.expected['scenarios'][0]['outputs'])


if __name__ == '__main__':
    unittest.main()
