"""Independent Tableau simulation QA against the previously frozen oracle.

The author derived expected artifacts from scenario/raw/CSV before inspecting
source or target code. All mutations are local synthetic temporary copies.
"""
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

SKILL = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator'
CASE = SKILL / 'examples/tableau-omni-e2e'
sys.path.insert(0, str(SKILL / 'scripts'))
OPTIONAL = all(importlib.util.find_spec(name) for name in ('duckdb', 'pandas', 'sqlglot', 'yaml', 'jsonschema'))
if OPTIONAL:
    import tableau_execution as execution
    import tableau_source
    import yaml


@unittest.skipUnless(OPTIONAL, 'Optional Tableau E2E engines are required')
class TableauExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.adjustments = execution.load_inputs(CASE)
        cls.expected = json.loads((CASE / 'expected/expected_reports.json').read_text())
        cls.facts = json.loads((CASE / 'expected/expected_rows.json').read_text())['invoices']
        cls.graph = tableau_source.inspect_repo(CASE / 'input/repo')
        spec = importlib.util.spec_from_file_location('independent_tableau_oracle', CASE / 'expected/oracle.py')
        cls.oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.oracle)

    def temporary_case(self):
        temporary = tempfile.TemporaryDirectory(prefix='dma-tableau-qa-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'case'
        for directory in ('input', 'target', 'documentation'):
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
        elif path.endswith(('payment_rate', 'share_of_month')) and expected is not None:
            self.assertIsNotNone(actual, path)
            self.assertLessEqual(abs(Decimal(str(actual)) - Decimal(str(expected))), Decimal('1e-12'), path)
        else:
            if type(expected) is int:
                self.assertTrue(type(actual) is int or isinstance(actual, Decimal), path + ': integer or exact Decimal cents required')
            self.assertEqual(actual, expected, path)

    def model_facts(self, con):
        rows, _ = execution.query(con, 'SELECT * FROM DMA_TABLEAU.GOLD.FCT_INVOICES ORDER BY TENANT_ID, INVOICE_ID')
        keys = [(row['tenant_id'], row['invoice_id']) for row in rows]
        self.assertEqual(len(keys), len(set(keys)), 'Invoice grain/fanout')
        return rows

    def test_16_omni_scenarios_match_frozen_oracle(self):
        self.assertEqual(len(self.expected['scenarios']), 16)
        with execution.connection(self.raw, self.adjustments) as con:
            self.assertEqual(len(execution.build_models(con, CASE / 'target/dbt')), 6)
            omni = execution.OmniSubset(CASE / 'target/omni')
            for scenario in self.expected['scenarios']:
                for role, expected in scenario['outputs'].items():
                    with self.subTest(scenario=scenario['scenario_id'], role=role):
                        rows, trace = omni.report(con, role, scenario['parameters'])
                        self.assert_values(rows, expected)
                        self.assertFalse(trace['native_omni_execution'])

    def test_10_full_gold_facts_match(self):
        self.assertEqual(len(self.facts), 10)
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            self.assert_values(self.model_facts(con), self.facts)

    def test_all_eight_invalid_contexts_rejected(self):
        self.assertEqual(len(self.expected['error_scenarios']), 8)
        for scenario in self.expected['error_scenarios']:
            with self.subTest(scenario=scenario['scenario_id']), self.assertRaises(execution.TableauExecutionError):
                execution.parameters(scenario['parameters'])

    def test_all_16_source_scenarios_match_frozen_oracle(self):
        for scenario in self.expected['scenarios']:
            with self.subTest(scenario=scenario['scenario_id']):
                actual, _, _ = execution.replay_source(CASE, self.graph, self.raw, self.adjustments, scenario['parameters'])
                self.assert_values(actual, scenario['outputs'])

    def test_source_inventory_field_and_intermediate_coverage(self):
        counts = self.graph['counts']
        self.assertEqual((counts['workbooks'], counts['worksheets'], counts['fields'], counts['calculations'], counts['parameters']), (1, 3, 29, 15, 5))
        self.assertTrue(self.graph['static_coverage_complete'])
        self.assertFalse(self.graph['native_runtime_validated'])
        _, intermediate, traces = execution.replay_source(CASE, self.graph, self.raw, self.adjustments)
        self.assertEqual(set(intermediate['executed_field_ids']), {field['id'] for field in self.graph['fields']})
        self.assertEqual(len(traces), 3)
        expected = [{name: row[name] for name in intermediate['projection']} for row in self.facts]
        self.assert_values(intermediate['invoices'], expected)

    def rewrite_native(self, root, change_workbook=None, change_datasource=None):
        workbook_path = root / 'input/repo/billing.twb'
        workbook = ET.parse(workbook_path)
        if change_workbook:
            change_workbook(workbook.getroot())
        if change_datasource:
            change_datasource(workbook.getroot().find("datasources/datasource[@name='federated.billing']"))
            tds_path = root / 'input/repo/billing.tds'; tds = ET.parse(tds_path)
            change_datasource(tds.getroot()); tds.write(tds_path, encoding='utf-8', xml_declaration=True)
        workbook.write(workbook_path, encoding='utf-8', xml_declaration=True)
        return tableau_source.inspect_repo(root / 'input/repo')

    def test_source_context_and_dimension_order_mutation_caught(self):
        root = self.temporary_case()
        def swap_context(workbook):
            sheet = workbook.find("worksheets/worksheet[@name='Customer Value']")
            for selected in sheet.findall('table/view/filter'):
                selected.set('context', 'true' if 'Segment Selection' in selected.get('column') else 'false')
        graph = self.rewrite_native(root, change_workbook=swap_context)
        self.assertTrue(graph['static_coverage_complete'])
        actual, _, _ = execution.replay_source(root, graph, self.raw, self.adjustments, {'segment': 'SMB'})
        self.assertEqual(actual['customer_value'][0]['fixed_customer_revenue_cents'], 11000)
        expected = next(s for s in self.expected['scenarios'] if s['scenario_id'] == 'segment_smb_a')['outputs']
        with self.assertRaises(AssertionError):
            self.assert_values(actual, expected)

    def test_source_population_filter_omission_caught(self):
        root = self.temporary_case()
        def remove_posted(datasource):
            filters = [node for node in datasource.findall('filter') if 'Posted Population' in node.get('column', '')]
            self.assertEqual(len(filters), 1)
            datasource.remove(filters[0])
        graph = self.rewrite_native(root, change_datasource=remove_posted)
        self.assertTrue(graph['static_coverage_complete'])
        actual, _, _ = execution.replay_source(root, graph, self.raw, self.adjustments)
        mark = next(row for row in actual['revenue_trend'] if row['month'] == '2026-02-01' and row['segment'] == 'Enterprise')
        self.assertEqual(mark['revenue_cents'], 13000, 'Draft must actually enter the defective population')
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected['scenarios'][0]['outputs'])

    def test_source_table_calculation_partition_mutation_caught(self):
        root = self.temporary_case()
        def add_month_address(workbook):
            sheet = workbook.find("worksheets/worksheet[@name='Revenue Share']")
            table_calc = sheet.find(".//column-instance[@column='[Revenue Share]']/table-calc")
            self.assertIsNotNone(table_calc)
            ET.SubElement(table_calc, 'order', {'field': '[federated.billing].[Invoice Month]'})
        graph = self.rewrite_native(root, change_workbook=add_month_address)
        self.assertTrue(graph['static_coverage_complete'])
        actual, _, _ = execution.replay_source(root, graph, self.raw, self.adjustments)
        self.assertLess(abs(actual['revenue_share'][0]['share_of_month'] - Decimal(5000) / Decimal(39000)), Decimal('1e-12'))
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected['scenarios'][0]['outputs'])

    def test_source_formula_mutation_executes_and_fails_parity(self):
        root = self.temporary_case()
        before, after = '[Amount Cents] + ZN([Adjustment Cents])', '[Amount Cents] - ZN([Adjustment Cents])'
        def replace_formulas(node):
            for calculation in node.iter('calculation'):
                if calculation.get('formula') == before:
                    calculation.set('formula', after)
        # Update all workbook field copies and the TDS mirror so the test reaches
        # changed calculation semantics, not an unrelated mirror/copy failure.
        graph = self.rewrite_native(root, change_workbook=replace_formulas, change_datasource=replace_formulas)
        self.assertTrue(graph['static_coverage_complete'])
        actual, intermediate, _ = execution.replay_source(root, graph, self.raw, self.adjustments)
        self.assertEqual(intermediate['invoices'][0]['net_cents'], 13000)
        with self.assertRaises(AssertionError):
            self.assert_values(actual, self.expected['scenarios'][0]['outputs'])

    def test_tds_drift_stops_source_replay(self):
        root = self.temporary_case(); path = root / 'input/repo/billing.tds'
        tree = ET.parse(path)
        tree.getroot().find("column[@name='[Net Cents]']/calculation").set('formula', '[Amount Cents]')
        tree.write(path, encoding='utf-8', xml_declaration=True)
        graph = tableau_source.inspect_repo(root / 'input/repo')
        self.assertTrue(any(gap['kind'] == 'tds_mirror_drift' for gap in graph['gaps']))
        with self.assertRaisesRegex(execution.TableauExecutionError, 'static gaps'):
            execution.replay_source(root, graph, self.raw, self.adjustments)

    def test_stale_source_snapshot_rejected_before_replay(self):
        root = self.temporary_case()
        graph = tableau_source.inspect_repo(root / 'input/repo')
        path = root / 'input/repo/billing.tds'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(execution.TableauExecutionError, 'Stale or out-of-scope source asset'):
            execution.replay_source(root, graph, self.raw, self.adjustments)

    def test_package_is_read_only_matching_mirror(self):
        package = tableau_source.inspect_package(CASE / 'input/packages/billing.twbx', CASE / 'input/repo')
        self.assertTrue(package['safe']); self.assertTrue(package['matches_repo'])
        self.assertFalse(package['extracted']); self.assertFalse(package['errors']); self.assertFalse(package['gaps'])
        self.assertEqual({member['path'] for member in package['members']}, {'billing.twb', 'billing.tds', 'adjustments.csv'})
        self.assertEqual(self.graph['counts']['workbooks'], 1)

    def test_archive_traversal_and_symlink_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory(prefix='dma-tableau-archive-') as temporary:
            root = Path(temporary)
            for kind in ('traversal', 'symlink'):
                path = root / (kind + '.twbx')
                with zipfile.ZipFile(path, 'w') as archive:
                    entry = zipfile.ZipInfo('../must-not-exist.twb' if kind == 'traversal' else 'linked.twb')
                    if kind == 'symlink':
                        entry.external_attr = (0o120777 << 16)
                    archive.writestr(entry, '<workbook/>')
                result = tableau_source.inspect_package(path)
                self.assertFalse(result['safe']); self.assertTrue(result['errors']); self.assertFalse(result['extracted'])
                self.assertIn('Unsafe archive member' if kind == 'traversal' else 'Symlink/special', result['errors'][0])
            self.assertFalse((root.parent / 'must-not-exist.twb').exists())

    def native_fields_and_rows(self, con, case=CASE):
        # This fixture is reviewed synthetic XML. The production-facing parser
        # has its own security/coverage tests; this helper does not parse archives.
        tree = ET.parse(case / 'input/repo/billing.twb')
        datasource = tree.getroot().find("datasources/datasource[@name='federated.billing']")
        remote = {record.findtext('local-name'): record.findtext('remote-name')
                  for record in datasource.findall('.//metadata-record')}
        fields = {}
        for column in datasource.findall('column'):
            name = column.get('name')
            spec = {'id': name, 'remote_name': remote.get(name)}
            calculation = column.find('calculation')
            if calculation is not None:
                spec['formula'] = calculation.get('formula')
            fields[name[1:-1]] = spec
        sql = datasource.find(".//relation[@type='text']").text
        rows, _ = execution.query(con, sql, execution.RAW_RELATIONS)
        return fields, rows

    def test_native_custom_sql_and_row_calculations_match_facts(self):
        with execution.connection(self.raw, self.adjustments) as con:
            fields, rows = self.native_fields_and_rows(con)
            self.assertEqual(len(rows), 10)
            formula = execution.TableauFormula(fields, execution.parameters(), rows)
            actual = []
            names = ('tenant_id', 'invoice_id', 'customer_id', 'invoice_date', 'status', 'segment', 'amount_cents', 'paid_cents')
            for row in rows:
                actual.append(dict({name: row[name] for name in names},
                                   net_cents=formula.value('[Net Cents]', rows, row),
                                   outstanding_cents=formula.value('[Outstanding Cents]', rows, row),
                                   invoice_month=formula.value('[Invoice Month]', rows, row)))
            wanted = [{name: row[name] for name in actual[0]} for row in self.facts]
            self.assert_values(sorted(actual, key=lambda row: (row['tenant_id'], row['invoice_id'])), wanted)
            self.assertTrue(any(row['adjustment_cents'] is None for row in rows), 'Must exercise source ZN over missing adjustment')

    def test_native_fixed_order_is_observable(self):
        with execution.connection(self.raw, self.adjustments) as con:
            fields, rows = self.native_fields_and_rows(con)
        context = [row for row in rows if row['tenant_id'] == 'A' and row['status'] == 'posted' and '2026-01-01' <= row['invoice_date'] < '2026-03-01']
        selected = [row for row in context if row['segment'] == 'SMB' and row['customer_id'] == 'C1']
        correct = execution.TableauFormula(fields, execution.parameters({'segment': 'SMB'}), context)
        self.assertEqual(correct.value('[Displayed Fixed Customer Net]', selected), 18000)
        wrong = execution.TableauFormula(fields, execution.parameters({'segment': 'SMB'}), [row for row in context if row['segment'] == 'SMB'])
        self.assertEqual(wrong.value('[Displayed Fixed Customer Net]', selected), 11000)

    def test_fixed_segment_cancellation_mutation_caught(self):
        root = self.temporary_case(); path = root / 'target/omni/invoices.view'
        view = yaml.safe_load(path.read_text())
        view['dimensions']['fixed_customer_revenue_cents']['level_of_detail'].pop('filters')
        path.write_text(yaml.safe_dump(view, sort_keys=False))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            actual, _ = execution.OmniSubset(root / 'target/omni').report(con, 'customer_value', {'segment': 'SMB'})
            self.assertEqual(actual[0]['fixed_customer_revenue_cents'], 11000)
            expected = next(s for s in self.expected['scenarios'] if s['scenario_id'] == 'segment_smb_a')['outputs']['customer_value']
            with self.assertRaises(AssertionError):
                self.assert_values(actual, expected)

    def test_fixed_wrong_customer_scope_caught(self):
        root = self.temporary_case(); path = root / 'target/omni/invoices.view'
        view = yaml.safe_load(path.read_text())
        view['dimensions']['fixed_customer_revenue_cents']['level_of_detail']['fixed'] = ['tenant_id']
        path.write_text(yaml.safe_dump(view, sort_keys=False))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            actual, _ = execution.OmniSubset(root / 'target/omni').report(con, 'customer_value')
            self.assertEqual(actual[0]['fixed_customer_revenue_cents'], 39000)
            with self.assertRaises(AssertionError):
                self.assert_values(actual, self.expected['scenarios'][0]['outputs']['customer_value'])

    def test_fixed_population_cancellation_rejected(self):
        root = self.temporary_case(); path = root / 'target/omni/invoices.view'
        view = yaml.safe_load(path.read_text())
        view['dimensions']['fixed_customer_revenue_cents']['level_of_detail']['filters']['tenant_id'] = {'is': '', 'cancel_query_filter': True}
        path.write_text(yaml.safe_dump(view, sort_keys=False))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            with self.assertRaisesRegex(execution.TableauExecutionError, 'population/context/access'):
                execution.OmniSubset(root / 'target/omni').report(con, 'customer_value')

    def test_window_all_month_partition_mutation_caught(self):
        root = self.temporary_case(); path = root / 'target/omni/report-context.json'
        context = json.loads(path.read_text()); share = context['reports']['revenue_share']['presentation'][0]
        share['partition_by'] = []; share['address_by'] = ['month', 'segment']
        path.write_text(json.dumps(context))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            actual, _ = execution.OmniSubset(root / 'target/omni').report(con, 'revenue_share')
            self.assertLess(abs(actual[0]['share_of_month'] - Decimal(5000) / Decimal(39000)), Decimal('1e-12'))
            with self.assertRaises(AssertionError):
                self.assert_values(actual, self.expected['scenarios'][0]['outputs']['revenue_share'])

    def test_contradictory_context_metadata_rejected(self):
        root = self.temporary_case(); path = root / 'target/omni/report-context.json'
        context = json.loads(path.read_text()); selected = context['reports']['customer_value']
        selected['context_order'] = ['datasource_population', 'segment_dimension', 'fixed_lod', 'date_context', 'mark_aggregation', 'presentation']
        selected['filter_roles']['context'] = ['segment']
        path.write_text(json.dumps(context))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            with self.assertRaises(execution.TableauExecutionError):
                execution.OmniSubset(root / 'target/omni').report(con, 'customer_value', {'segment': 'SMB'})

    def test_exact_large_cents_preserved(self):
        adjustments = copy.deepcopy(self.adjustments); adjustments[0]['ADJUSTMENT_CENTS'] = 9007199254740993
        expected = self.oracle.calculate(self.raw, adjustments)
        with execution.connection(self.raw, adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            self.assert_values(self.model_facts(con), expected['invoices'])
            actual, _ = execution.OmniSubset(CASE / 'target/omni').report(con, 'revenue_trend')
            self.assert_values(actual, expected['revenue_trend'])

    def test_large_ratio_meets_tolerance_or_rejects_precision_limit(self):
        raw = copy.deepcopy(self.raw)
        raw['PAYMENT_CDC'].append({'TENANT_ID': 'A', 'PAYMENT_ID': 'P3', 'INVOICE_ID': 'I2', 'PAID_CENTS': 9007199254740993, 'IS_DELETED': False, 'SEQUENCE': 99})
        expected = self.oracle.calculate(raw, self.adjustments)['revenue_trend']
        with execution.connection(raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            try:
                actual, _ = execution.OmniSubset(CASE / 'target/omni').report(con, 'revenue_trend')
            except ValueError as error:
                self.assertRegex(str(error).lower(), 'precision|tolerance|magnitude')
            else:
                self.assert_values(actual, expected)

    def test_replay_shuffle_and_header_only_adjustments(self):
        raw = copy.deepcopy(self.raw)
        for table in ('INVOICE_CDC', 'PAYMENT_CDC', 'CUSTOMER_HISTORY'):
            raw[table] = list(reversed(raw[table] + copy.deepcopy(raw[table])))
        for adjustments in (self.adjustments, []):
            with self.subTest(empty_adjustments=not adjustments), execution.connection(raw, adjustments) as con:
                execution.build_models(con, CASE / 'target/dbt')
                self.assert_values(self.model_facts(con), self.oracle.calculate(raw, adjustments)['invoices'])

    def test_overpayment_and_negative_net_are_not_clamped(self):
        adjustments = copy.deepcopy(self.adjustments); adjustments[0]['ADJUSTMENT_CENTS'] = -13000
        expected = self.oracle.calculate(self.raw, adjustments)
        with execution.connection(self.raw, adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            actual = self.model_facts(con)
            self.assertEqual(actual[0]['net_cents'], -1000)
            self.assertEqual(actual[0]['outstanding_cents'], -11000)
            self.assert_values(actual, expected['invoices'])

    def test_target_tenant_join_fanout_caught(self):
        root = self.temporary_case(); path = root / 'target/dbt/models/gold/fct_invoices.sql'
        sql = path.read_text(); clause = 'i.TENANT_ID = p.TENANT_ID AND '
        self.assertIn(clause, sql); path.write_text(sql.replace(clause, ''))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            with self.assertRaisesRegex(AssertionError, 'Invoice grain/fanout'):
                self.model_facts(con)

    def test_unsupported_formula_and_recursive_refs_rejected(self):
        for formula in ('SCRIPT_REAL("x", [Amount Cents])', 'LOOKUP(SUM([Amount Cents]), -1)', 'RUNNING_SUM(SUM([Amount Cents]))', '[Net Cents]; open("/etc/passwd")'):
            with self.subTest(formula=formula), self.assertRaises(execution.TableauExecutionError):
                execution.FormulaParser(formula).parse()
        fields = {'A': {'formula': '[B]'}, 'B': {'formula': '[A]'}}
        with self.assertRaisesRegex(execution.TableauExecutionError, 'Cyclic'):
            execution.TableauFormula(fields, execution.parameters(), []).value('[A]', [])

    def test_external_sql_blocked_by_parser_and_connection(self):
        with tempfile.TemporaryDirectory(prefix='dma-tableau-sentinel-') as temporary:
            path = Path(temporary) / 'sentinel.csv'; path.write_text('n\n17\n')
            sql = "SELECT * FROM READ_CSV('" + str(path) + "')"
            with execution.connection(self.raw, self.adjustments) as con:
                with self.assertRaises(ValueError):
                    execution.query(con, sql)
                with self.assertRaisesRegex(Exception, 'external|disabled|permission'):
                    con.execute(sql).fetchall()

    def test_wrong_namespace_and_dbt_hooks_rejected(self):
        with execution.connection(self.raw, self.adjustments) as con:
            for sql in ('SELECT * FROM DMA_HEX.RAW.INVOICE_CDC', 'SELECT * FROM "dma_tableau"."raw"."invoice_cdc"', 'SELECT "amount_cents" FROM DMA_TABLEAU.RAW.INVOICE_CDC'):
                with self.subTest(sql=sql), self.assertRaises(ValueError):
                    execution.query(con, sql)
        with self.assertRaises(execution.TableauExecutionError):
            execution.render_dbt("{{ config(pre_hook='DELETE FROM X') }} SELECT 1")

    def test_documentation_matches_executed_model_and_column_inventory(self):
        from run_tableau_omni_e2e import documentation
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, CASE / 'target/dbt')
            result = documentation(CASE, con)
            self.assertEqual(result['models'], 10)
            self.assertGreater(result['columns'], 50)

    def test_paired_dictionary_inventory_omission_caught_against_execution(self):
        from run_tableau_omni_e2e import documentation
        root = self.temporary_case()
        inventory_path = root / 'documentation/model-inventory.json'
        dictionary_path = root / 'documentation/data-dictionary.json'
        inventory = json.loads(inventory_path.read_text()); dictionary = json.loads(dictionary_path.read_text())
        raw = next(model for model in inventory['models'] if model['model_id'] == 'DMA_TABLEAU.RAW.ADJUSTMENTS')
        raw['columns'].remove('REASON')
        documented = next(model for model in dictionary['models'] if model['model_id'] == raw['model_id'])
        documented['columns'] = [column for column in documented['columns'] if column['name'] != 'REASON']
        inventory_path.write_text(json.dumps(inventory))
        dictionary['model_inventory_sha256'] = execution.sha(inventory_path)
        dictionary_path.write_text(json.dumps(dictionary))
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            with self.assertRaisesRegex(AssertionError, 'Documented columns differ'):
                documentation(root, con)

    def test_missing_readable_dictionary_rejected(self):
        from run_tableau_omni_e2e import documentation
        root = self.temporary_case()
        (root / 'documentation/data-dictionary.md').write_text(' \n')
        with execution.connection(self.raw, self.adjustments) as con:
            execution.build_models(con, root / 'target/dbt')
            with self.assertRaisesRegex(AssertionError, 'readable|empty|nonempty'):
                documentation(root, con)


if __name__ == '__main__':
    unittest.main()
