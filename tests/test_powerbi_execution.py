"""Independent Power BI replay QA against the previously frozen raw-derived oracle.

Only synthetic temporary copies are mutated. Optional engines establish bounded
local behavior, never native Power BI, Snowflake, Omni or warehouse RLS approval.
"""
import copy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator'
CASE = SKILL / 'examples/powerbi-omni-e2e'
sys.path.insert(0, str(SKILL / 'scripts'))
OPTIONAL = all(importlib.util.find_spec(name) for name in
               ('duckdb', 'pandas', 'sqlglot', 'yaml', 'jsonschema', 'referencing'))
if OPTIONAL:
    import powerbi_execution as execution
    import powerbi_source as source
    from powerbi_languages import DAXSubset, LanguageError, evaluate_m
    import yaml


@unittest.skipUnless(OPTIONAL, 'Pinned optional Power BI E2E engines required')
class PowerBIExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.adjustments = execution.load_inputs(CASE)
        cls.expected = json.loads((CASE / 'expected/expected_reports.json').read_text())
        cls.facts = json.loads((CASE / 'expected/expected_rows.json').read_text())['invoices']
        cls.graph = source.inspect_repo(CASE / 'input/repo')
        cls.replay = execution.SourceReplay(CASE, cls.graph, cls.raw, cls.adjustments)
        spec = importlib.util.spec_from_file_location('independent_powerbi_oracle', CASE / 'expected/oracle.py')
        cls.oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.oracle)

    def temporary_case(self):
        temporary = tempfile.TemporaryDirectory(prefix='dma-powerbi-independent-qa-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'case'
        for directory in ('input', 'target'):
            shutil.copytree(CASE / directory, root / directory)
        return root

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
        elif path.endswith(('payment_rate', 'share_all_segments')) and expected is not None:
            self.assertIsNotNone(actual, path)
            self.assertLessEqual(abs(Decimal(str(actual)) - Decimal(str(expected))), Decimal('1e-12'), path)
        else:
            if type(expected) is int:
                self.assertTrue(type(actual) is int or isinstance(actual, Decimal), path + ': exact cents/count required')
            self.assertEqual(actual, expected, path)

    def expected_scenario(self, name):
        return next(scenario for scenario in self.expected['scenarios'] if scenario['name'] == name)

    def mutate_model(self, root, callback):
        path = root / 'input/repo/Billing.SemanticModel/model.bim'
        document = json.loads(path.read_text())
        callback(document['model'])
        path.write_text(json.dumps(document, indent=2) + '\n')
        return source.inspect_repo(root / 'input/repo')

    def source_change(self, callback, params=None):
        root = self.temporary_case()
        graph = self.mutate_model(root, callback)
        return execution.replay_source(root, graph, self.raw, self.adjustments, params)[0]

    @staticmethod
    def table(model, name):
        return next(table for table in model['tables'] if table['name'] == name)

    def change_measure(self, name, expression, params=None):
        def change(model):
            measure = next(m for m in self.table(model, 'Scenario')['measures'] if m['name'] == name)
            measure['expression'] = expression
        return self.source_change(change, params)

    def mutate_omni(self, root, filename, callback, is_json=False):
        path = root / 'target/omni' / filename
        value = json.loads(path.read_text()) if is_json else yaml.safe_load(path.read_text())
        callback(value)
        path.write_text(json.dumps(value, indent=2) if is_json else yaml.safe_dump(value, sort_keys=False))

    def test_frozen_oracle_hashes_unchanged(self):
        hashes = {
            'oracle.py': '4db3ebeb5a42d52322bcb382cca3872e39987acb503a6faf475ed4c9744ab05a',
            'expected_rows.json': 'f795bfd1535f33739cdb2a1fd621af9461f19657243f67c0cc0d9a95a7b86661',
            'expected_reports.json': 'a33ec4cb381f2623ad6c10f9cfc0bf65beccac0940d4783a38067988eb4abfe0',
            'oracle-notes.md': '1ae8a23f2700bd530a465d8fb972e28ec60b01168781a3bd82130c8cfe1ac9de',
        }
        for name, expected in hashes.items():
            self.assertEqual(hashlib.sha256((CASE / 'expected' / name).read_bytes()).hexdigest(), expected, name)

    def test_all_22_source_scenarios_match_frozen_oracle(self):
        self.assertEqual(len(self.expected['scenarios']), 22)
        for scenario in self.expected['scenarios']:
            with self.subTest(scenario=scenario['name']):
                actual, _, _ = self.replay.render(scenario['parameters'])
                self.assert_values(actual, scenario['outputs'])

    def test_all_22_target_scenarios_match_frozen_oracle(self):
        with execution.connection(self.raw, self.adjustments) as con:
            self.assertEqual(len(execution.build_models(con, CASE / 'target/dbt')), 6)
            omni = execution.OmniSubset(CASE / 'target/omni')
            for scenario in self.expected['scenarios']:
                for role, expected in scenario['outputs'].items():
                    with self.subTest(scenario=scenario['name'], visual=role):
                        rows, trace = omni.render(con, role, scenario['parameters'])
                        self.assert_values(rows, expected)
                        self.assertFalse(trace['native_omni_execution'])

    def test_all_gold_rows_and_source_field_coverage(self):
        self.assertEqual(len(self.facts), 10)
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            rows, _ = execution.query(con, 'SELECT * FROM DMA_POWERBI.GOLD.FCT_INVOICES ORDER BY TENANT_ID, INVOICE_ID')
            self.assert_values(rows, self.facts)
        _, intermediate, traces = self.replay.render()
        self.assert_values(intermediate['invoices'], [{key: row[key] for key in intermediate['projection']} for row in self.facts])
        self.assertEqual(len(intermediate['executed_columns']), 20)
        self.assertEqual(len(set(intermediate['executed_columns'])), 20)
        self.assertEqual(len(intermediate['executed_measures']), 9)
        self.assertEqual(len(intermediate['partition_traces']), 3)
        self.assertEqual(len(traces), 3)
        self.assertEqual(self.graph['counts']['schema_validated_files'], 10)
        self.assertIn('native_runtime_unverified', {gap['kind'] for gap in self.graph['gaps']})

    def test_all_16_invalid_contexts_rejected_on_both_paths(self):
        self.assertEqual(len(self.expected['invalid_scenarios']), 16)
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            omni = execution.OmniSubset(CASE / 'target/omni')
            for scenario in self.expected['invalid_scenarios']:
                with self.subTest(scenario=scenario['name']):
                    with self.assertRaises(execution.PowerBIExecutionError):
                        self.replay.render(scenario['parameters'])
                    with self.assertRaises(execution.PowerBIExecutionError):
                        omni.render(con, 'kpi_totals', scenario['parameters'])

    def test_empty_blank_zero_and_independently_changed_context(self):
        empty = self.replay.render({'start_date': '2026-04-01', 'end_date': '2026-05-01'})[0]
        self.assertEqual(empty['revenue_trend'], [])
        self.assertEqual(len(empty['kpi_totals']), 1)
        self.assertTrue(all(value is None for value in empty['kpi_totals'][0].values()))
        zero = self.replay.render({'start_date': '2026-02-20', 'end_date': '2026-02-21'})[0]['kpi_totals'][0]
        self.assertEqual(zero['revenue_cents'], 0)
        self.assertIsNone(zero['payment_rate'])
        draft_smb = self.replay.render({'status': 'draft', 'segment': 'SMB'})[0]['kpi_totals'][0]
        self.assertIsNone(draft_smb['revenue_cents'])
        self.assertEqual(draft_smb['all_segment_revenue_cents'], 6000)
        self.assertEqual(draft_smb['posted_revenue_cents'], 27000)
        self.assertIsNone(draft_smb['posted_intersection_cents'])

    def test_totals_recompute_without_summing_repeated_denominators(self):
        actual = self.replay.render()[0]
        self.assertEqual(sum(row['all_segment_revenue_cents'] for row in actual['segment_share']), 78000)
        self.assertEqual(actual['kpi_totals'][0]['all_segment_revenue_cents'], 39000)
        self.assertEqual(actual['kpi_totals'][0]['share_all_segments'], Decimal(1))
        self.assertNotEqual(sum(row['payment_rate'] for row in actual['revenue_trend']), actual['kpi_totals'][0]['payment_rate'])

    def test_dax_replace_mutated_to_intersection_is_observable(self):
        actual = self.change_measure('Posted Revenue Cents', 'CALCULATE([Revenue Cents],KEEPFILTERS(Invoices[Status]="posted"))', {'status': 'draft'})
        self.assertIsNone(actual['kpi_totals'][0]['posted_revenue_cents'])
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected_scenario('draft_a')['outputs'])

    def test_dax_intersection_mutated_to_replace_is_observable(self):
        actual = self.change_measure('Posted Intersection Cents', 'CALCULATE([Revenue Cents],Invoices[Status]="posted")', {'status': 'draft'})
        self.assertEqual(actual['kpi_totals'][0]['posted_intersection_cents'], 39000)
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected_scenario('draft_a')['outputs'])

    def test_dax_removed_all_segment_context_is_observable(self):
        actual = self.change_measure('All Segment Revenue Cents', '[Revenue Cents]', {'segment': 'SMB'})
        self.assertEqual(actual['kpi_totals'][0]['all_segment_revenue_cents'], 27000)
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected_scenario('segment_smb_a')['outputs'])

    def test_dax_changed_multiselect_alternate_is_observable(self):
        actual = self.change_measure('Scenario Revenue Cents', '[Revenue Cents] * SELECTEDVALUE(Scenario[Multiplier],2)', {'multipliers': []})
        self.assertEqual(actual['kpi_totals'][0]['scenario_revenue_cents'], 78000)
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected_scenario('multipliers_none')['outputs'])

    def test_source_calculated_column_change_is_observable(self):
        def change(model):
            column = next(c for c in self.table(model, 'Invoices')['columns'] if c['name'] == 'Outstanding Cents')
            column['expression'] = 'Invoices[Net Cents] + Invoices[Paid Cents]'
        actual = self.source_change(change)
        self.assertEqual(actual['kpi_totals'][0]['outstanding_cents'], 61000)
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected_scenario('default_a')['outputs'])

    def test_source_m_null_fill_change_is_observable(self):
        def change(model):
            partition = self.table(model, 'Invoices')['partitions'][0]['source']
            before = 'if [ADJUSTMENT_CENTS] = null then 0 else'
            self.assertIn(before, partition['expression'])
            partition['expression'] = partition['expression'].replace(before, 'if [ADJUSTMENT_CENTS] = null then 1 else')
        actual = self.source_change(change)
        self.assertEqual(actual['kpi_totals'][0]['revenue_cents'], 39003)
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected_scenario('default_a')['outputs'])

    def test_source_missing_tenant_join_causes_observed_fanout(self):
        def change(model):
            partition = self.table(model, 'Invoices')['partitions'][0]['source']
            before = 'i.TENANT_ID = p.TENANT_ID AND i.INVOICE_ID = p.INVOICE_ID'
            self.assertIn(before, partition['expression'])
            partition['expression'] = partition['expression'].replace(before, 'i.INVOICE_ID = p.INVOICE_ID')
        with self.assertRaisesRegex(execution.PowerBIExecutionError, 'grain/fanout'):
            self.source_change(change)

    def test_target_missing_tenant_join_causes_observed_fanout(self):
        root = self.temporary_case()
        path = root / 'target/dbt/models/gold/fct_invoices.sql'
        before = 'i.TENANT_ID = p.TENANT_ID AND i.INVOICE_ID = p.INVOICE_ID'
        self.assertIn(before, path.read_text())
        path.write_text(path.read_text().replace(before, 'i.INVOICE_ID = p.INVOICE_ID'))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            rows, _ = execution.query(con, 'SELECT * FROM DMA_POWERBI.GOLD.FCT_INVOICES ORDER BY TENANT_ID, INVOICE_ID')
            self.assertGreater(len(rows), len(self.facts))
            keys = [(row['tenant_id'], row['invoice_id']) for row in rows]
            self.assertLess(len(set(keys)), len(keys))
            with self.assertRaises(AssertionError):
                self.assert_values(rows, self.facts)

    def test_source_unsupported_dax_does_not_return_cached_results(self):
        for expression in ('SUMX(Invoices,Invoices[Net Cents])', 'CALCULATE([Revenue Cents],REMOVEFILTERS(Customers[Tenant ID]))'):
            with self.subTest(expression=expression), self.assertRaises((LanguageError, execution.PowerBIExecutionError)):
                self.change_measure('All Segment Revenue Cents', expression)

    def test_source_relationship_and_role_mutations_rejected(self):
        mutations = [
            lambda model: model['relationships'][0].update(isActive=False),
            lambda model: model['relationships'][0].update(crossFilteringBehavior='bothDirections'),
            lambda model: model['relationships'][0].update(toCardinality='many'),
            lambda model: model['roles'][0]['tablePermissions'].pop(),
            lambda model: model['roles'][0]['tablePermissions'][0].update(filterExpression='Invoices[Tenant ID]="B"'),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index), self.assertRaises(execution.PowerBIExecutionError):
                self.source_change(mutation)

    def test_source_added_report_and_visual_filters_rejected(self):
        for surface in ('report', 'visual'):
            with self.subTest(surface=surface):
                root = self.temporary_case()
                report_path = root / 'input/repo/Billing.Report/definition/report.json'
                report = json.loads(report_path.read_text())
                extra = copy.deepcopy(report['filterConfig']['filters'][2]); extra['name'] = 'AdditionalStatus'
                if surface == 'report':
                    report['filterConfig']['filters'].append(extra)
                    report_path.write_text(json.dumps(report))
                else:
                    path = next((root / 'input/repo/Billing.Report').rglob('RevenueTrend/visual.json'))
                    visual = json.loads(path.read_text()); visual['filterConfig'] = {'filters': [extra]}
                    path.write_text(json.dumps(visual))
                graph = source.inspect_repo(root / 'input/repo')
                with self.assertRaises(execution.PowerBIExecutionError):
                    execution.SourceReplay(root, graph, self.raw, self.adjustments)

    def test_stale_source_graph_rejected_before_execution(self):
        root = self.temporary_case()
        graph = source.inspect_repo(root / 'input/repo')
        path = root / 'input/repo/adjustments.csv'; path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(execution.PowerBIExecutionError, 'Stale or altered'):
            execution.SourceReplay(root, graph, self.raw, self.adjustments)

    def test_omni_native_status_filter_mutation_changes_results(self):
        root = self.temporary_case()
        self.mutate_omni(root, 'invoices.view', lambda view: view['measures']['posted_revenue_cents']['filters']['invoices.status'].update(cancel_query_filter=False))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            rows, _ = execution.OmniSubset(root / 'target/omni').render(con, 'kpi_totals', {'status': 'draft'})
            self.assertIsNone(rows[0]['posted_revenue_cents'])
            with self.assertRaises(AssertionError):
                self.assert_values(rows, self.expected_scenario('draft_a')['outputs']['kpi_totals'])

    def test_omni_tenant_relationship_scope_and_blank_mutations_rejected(self):
        mutations = [
            ('billing.topic', lambda value: value['access_filters'].pop(), False),
            ('relationships', lambda value: value[0].update(on_sql='${invoices.customer_key} = ${customers.customer_key}'), False),
            ('report-context.json', lambda value: value['blank_contract'].update(empty_sum=0), True),
            ('report-context.json', lambda value: value['security'].update(ordinary_measure_filters_cannot_remove=[]), True),
        ]
        for filename, change, is_json in mutations:
            with self.subTest(filename=filename):
                root = self.temporary_case(); self.mutate_omni(root, filename, change, is_json)
                with self.assertRaises(execution.PowerBIExecutionError):
                    execution.OmniSubset(root / 'target/omni')

    def test_omni_lod_cannot_remove_tenant(self):
        root = self.temporary_case()
        self.mutate_omni(root, 'invoices.view', lambda value: value['measures']['all_segment_revenue_cents']['level_of_detail'].update(always_exclude=['invoices.tenant_id']))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            with self.assertRaisesRegex(execution.PowerBIExecutionError, 'LOD scope'):
                execution.OmniSubset(root / 'target/omni').render(con, 'kpi_totals')

    def test_omni_totals_cannot_be_visible_row_sum(self):
        root = self.temporary_case()
        self.mutate_omni(root, 'report-context.json', lambda value: value['reports']['kpi_totals'].update(totals='sum_visible_rows'), True)
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            with self.assertRaisesRegex(execution.PowerBIExecutionError, 'total row policy'):
                execution.OmniSubset(root / 'target/omni').render(con, 'kpi_totals')

    def test_omni_companion_context_parameter_and_security_drift_rejected(self):
        mutations = [
            lambda value: value['parameter_contract']['multipliers'].update(alternate=2),
            lambda value: value['security'].update(source_role_tables=['Invoices']),
            lambda value: value['measure_context_contracts']['invoices.all_segment_revenue_cents'].update(behavior='remove_security'),
            lambda value: value['measure_context_contracts']['invoices.posted_revenue_cents'].update(behavior='intersect_status'),
            lambda value: value['measure_context_contracts']['invoices.posted_intersection_cents'].update(preserve=[]),
        ]
        for index, change in enumerate(mutations):
            with self.subTest(mutation=index):
                root = self.temporary_case()
                self.mutate_omni(root, 'report-context.json', change, True)
                with self.assertRaisesRegex(execution.PowerBIExecutionError, 'contract|security mismatch'):
                    execution.OmniSubset(root / 'target/omni')

    def test_no_or_multiple_multiplier_values_use_one(self):
        normal = self.replay.render()[0]
        for selection in ([], [1, 2], [2, 1]):
            self.assert_values(self.replay.render({'multipliers': selection})[0], normal)
        doubled = self.replay.render({'multipliers': [2]})[0]
        self.assertEqual(doubled['kpi_totals'][0]['scenario_revenue_cents'], 78000)
        self.assertEqual(doubled['kpi_totals'][0]['revenue_cents'], 39000)

    def test_m_external_readers_and_wrong_account_never_call_query(self):
        calls = []
        expressions = ['File.Contents("/private/tmp/synthetic-sentinel")', 'Web.Contents("https://example.invalid")',
                       'Value.NativeQuery(Snowflake.Databases("OTHER_ACCOUNT", "SYNTHETIC_LOCAL_ONLY"){[Name="DMA_POWERBI",Kind="Database"]}[Data], "SELECT 1", null, [EnableFolding=true])']
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(LanguageError):
                evaluate_m(expression, lambda query: calls.append(query))
        self.assertEqual(calls, [])

    def test_sql_external_files_blocked_by_guard_and_engine(self):
        root = self.temporary_case(); sentinel = root / 'sentinel.csv'; sentinel.write_text('value\n42\n')
        statement = "SELECT * FROM READ_CSV('" + str(sentinel) + "')"
        with execution.connection(self.raw, self.adjustments) as con:
            with self.assertRaises(execution.PowerBIExecutionError):
                execution.query(con, statement)
            with self.assertRaises(Exception) as raised:
                con.execute(statement).fetchall()
            self.assertIn('disabled', str(raised.exception).lower())
        self.assertEqual(sentinel.read_text(), 'value\n42\n')

    def test_malformed_m_and_cyclic_dax_fail_explicitly(self):
        for expression in ('let A=1,A=2 in A', 'let A=[x=1,x=2] in A', 'let A=1 in A trailing', 'if 1 then 2 else 3'):
            with self.subTest(expression=expression), self.assertRaises(LanguageError):
                evaluate_m(expression, lambda sql: self.fail('Unexpected source query'))
        with self.assertRaises(LanguageError):
            DAXSubset([], {'A': '[B]', 'B': '[A]'}, []).measure('A', {})

    def test_replay_and_reordered_source_preserve_full_rows(self):
        raw = copy.deepcopy(self.raw)
        for key in ('INVOICE_CDC', 'PAYMENT_CDC', 'CUSTOMER_HISTORY'):
            raw[key] *= 2; random.Random(19).shuffle(raw[key])
        replay = execution.SourceReplay(CASE, self.graph, raw, self.adjustments)
        self.assert_values(replay.render()[0], self.expected_scenario('default_a')['outputs'])
        with execution.connection(raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            rows, _ = execution.query(con, 'SELECT * FROM DMA_POWERBI.GOLD.FCT_INVOICES ORDER BY TENANT_ID, INVOICE_ID')
            self.assert_values(rows, self.facts)

    def test_conflicting_cdc_overlap_orphan_and_extra_field_rejected(self):
        cases = []
        conflict = copy.deepcopy(self.raw); row = copy.deepcopy(conflict['INVOICE_CDC'][0]); row['AMOUNT_CENTS'] += 1; conflict['INVOICE_CDC'].append(row); cases.append(conflict)
        overlap = copy.deepcopy(self.raw); row = copy.deepcopy(overlap['CUSTOMER_HISTORY'][0]); row['SEGMENT'] = 'Conflict'; overlap['CUSTOMER_HISTORY'].append(row); cases.append(overlap)
        orphan = copy.deepcopy(self.raw)
        for row in orphan['PAYMENT_CDC']:
            if row['TENANT_ID'] == 'A' and row['PAYMENT_ID'] == 'P1': row['INVOICE_ID'] = 'ABSENT'
        cases.append(orphan)
        extra = copy.deepcopy(self.raw); extra['INVOICE_CDC'][0]['UNPARSED_BUSINESS_RULE'] = 'ignore'; cases.append(extra)
        for index, raw in enumerate(cases):
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                execution.connection(raw, self.adjustments)

    def test_large_exact_cents_and_repeating_ratio_against_independent_oracle(self):
        raw = copy.deepcopy(self.raw)
        invoice = copy.deepcopy(next(r for r in raw['INVOICE_CDC'] if r['TENANT_ID'] == 'A' and r['INVOICE_ID'] == 'I1'))
        invoice.update(SEQUENCE=99, AMOUNT_CENTS=1003); raw['INVOICE_CDC'].append(invoice)
        payment = copy.deepcopy(next(r for r in raw['PAYMENT_CDC'] if r['TENANT_ID'] == 'A' and r['PAYMENT_ID'] == 'P1'))
        payment.update(SEQUENCE=99, PAID_CENTS=9000000000000000001); raw['PAYMENT_CDC'].append(payment)
        params = {'start_date': '2026-01-15', 'end_date': '2026-01-16'}
        expected = self.oracle.calculate(raw, self.adjustments, params)
        expected_reports = {k: expected[k] for k in ('revenue_trend', 'segment_share', 'kpi_totals')}
        self.assert_values(execution.replay_source(CASE, self.graph, raw, self.adjustments, params)[0], expected_reports)
        with execution.connection(raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt'); omni = execution.OmniSubset(CASE / 'target/omni')
            for role, rows in expected_reports.items():
                self.assert_values(omni.render(con, role, params)[0], rows)
        self.assertEqual(expected['kpi_totals'][0]['paid_cents'], 9000000000000003001)
        self.assertLess(expected['kpi_totals'][0]['outstanding_cents'], 0)

    def test_header_only_adjustments_preserve_nullable_source_and_zero_target(self):
        expected = self.oracle.calculate(self.raw, [])
        replay = execution.SourceReplay(CASE, self.graph, self.raw, [])
        self.assertTrue(all(row[('Invoices', 'Adjustment Cents')] is None for row in replay.tables['Invoices']))
        actual, intermediate, _ = replay.render()
        self.assert_values(actual, {k: expected[k] for k in actual})
        with execution.connection(self.raw, []) as con:
            execution.build_models(con, CASE / 'target/dbt')
            rows, _ = execution.query(con, 'SELECT * FROM DMA_POWERBI.GOLD.FCT_INVOICES ORDER BY TENANT_ID, INVOICE_ID')
            self.assert_values(rows, expected['invoices'])
        self.assertEqual(len(intermediate['invoices']), 10)


if __name__ == '__main__':
    unittest.main()
