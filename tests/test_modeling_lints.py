"""Modeling-standard lints: classification by grain, duplicated grains, placement, level-mixing fallbacks,
topic reach and semantic description language. Inputs are synthetic page data."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import modeling_lints as lints

HAS_YAML = importlib.util.find_spec('yaml') is not None


def page():
    """Two own-domain gold tables reached by one topic, one other-domain table, no findings."""
    return {
        'meta': {'domain': 'billing'},
        'models': [
            {'id': 'wh_billing__invoice_fct', 'layer': 'gold', 'domain': 'billing', 'grain': 'One row per invoice.',
             'cols': [['invoice_pk', 'string', 'PK', ''], ['customer_fk', 'string', 'FK', ''], ['net_amount', 'numeric', '', '']]},
            {'id': 'wh_billing__customer_dim', 'layer': 'gold', 'domain': 'billing', 'grain': 'One row per customer.',
             'cols': [['customer_pk', 'string', 'PK', ''], ['customer_segment', 'string', '', '']]},
            {'id': 'wh_crm__account_dim', 'layer': 'gold', 'domain': 'crm', 'cols': [['account_pk', 'string', 'PK', '']]},
            {'id': 'int_billing__invoice', 'layer': 'silver', 'domain': 'billing', 'cols': []}],
        'topics': [{'topic': 'invoices', 'base_model_ids': ['wh_billing__invoice_fct'],
                    'nodes': [{'view_id': 'invoices', 'model_ids': ['wh_billing__invoice_fct']},
                              {'view_id': 'customers', 'model_ids': ['wh_billing__customer_dim']}]}],
        'decisions': [],
        'files': [{'path': '02_dbt/models/warehouse/wh_billing__invoice_fct.sql',
                   'content': 'select invoice_pk, customer_fk, gross - discount as net_amount from x\n'},
                  {'path': '03_omni/model/views/invoices.view',
                   'content': 'table_name: wh_billing__invoice_fct\ndescription: One row per invoice.\n'
                              'dimensions:\n  net_amount:\n    label: Net Amount\n    description: Gross less discount.\n'}]}


def lint(value, name):
    return [f for f in lints.lint_page(value)['findings'] if f['lint'] == name]


class ModelingLintTests(unittest.TestCase):
    @unittest.skipUnless(HAS_YAML, 'Optional YAML parser unavailable')
    def test_clean_page_passes(self):
        report = lints.lint_page(page())
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['findings'], [])
        self.assertEqual([r['count'] for r in lints.static_rows(report)], [0] * len(lints.LINTS))

    def test_dimension_keyed_by_a_period_is_flagged_and_history_dimensions_are_not(self):
        value = page()
        value['models'].append({'id': 'wh_billing__customer_monthly_dim', 'layer': 'gold', 'domain': 'billing',
                                'grain': 'One row per customer per month.',
                                'cols': [['customer_month_pk', 'string', 'PK', ''], ['customer_segment', 'string', '', '']]})
        value['models'].append({'id': 'wh_billing__customer_scd_dim', 'layer': 'gold', 'domain': 'billing',
                                'cols': [['customer_valid_from_pk', 'string', 'PK', '']]})
        value['topics'][0]['nodes'] += [{'view_id': v, 'model_ids': [v]} for v in ('wh_billing__customer_monthly_dim', 'wh_billing__customer_scd_dim')]
        found = lint(value, 'period_keyed_dimension')
        self.assertEqual([f['models'] for f in found], [['wh_billing__customer_monthly_dim']])
        self.assertIn('periodic snapshot', found[0]['message'])
        self.assertFalse(found[0]['gate'])
        value['decisions'].append({'id': 'D-1', 'area': 'Classification', 'status': 'assumed',
                                   'models': ['wh_billing__customer_monthly_dim']})
        self.assertEqual(lint(value, 'period_keyed_dimension')[0]['resolved_by'], 'D-1')

    def test_same_grain_tables_repeating_columns_need_a_decision_naming_both(self):
        value = page()
        cols = [['customer_pk', 'string', 'PK', '']] + [[c, 'string', '', ''] for c in ('segment', 'plan', 'region', 'size')]
        value['models'] = [m for m in value['models'] if m['id'] != 'wh_billing__customer_dim']
        value['models'] += [{'id': 'wh_billing__customer_dim', 'layer': 'gold', 'domain': 'billing', 'grain': 'One row per customer.', 'cols': cols},
                            {'id': 'wh_billing__customer_xa', 'layer': 'gold', 'domain': 'billing', 'grain': 'one row per customer',
                             'cols': cols + [['mrr', 'numeric', '', '']]}]
        value['topics'][0]['nodes'].append({'view_id': 'x', 'model_ids': ['wh_billing__customer_xa']})
        found = lint(value, 'same_grain_overlap')
        self.assertEqual(len(found), 1)
        self.assertEqual(set(found[0]['models']), {'wh_billing__customer_dim', 'wh_billing__customer_xa'})
        self.assertEqual(lints.lint_page(value)['status'], 'fail')
        value['decisions'].append({'id': 'D-2', 'area': 'Same grain', 'status': 'answered', 'models': ['wh_billing__customer_dim']})
        self.assertIsNone(lint(value, 'same_grain_overlap')[0]['resolved_by'], 'A decision must name both tables')
        value['decisions'][0]['models'].append('wh_billing__customer_xa')
        self.assertEqual(lints.lint_page(value)['status'], 'pass')

    def test_open_decisions_do_not_resolve_findings(self):
        value = page()
        value['topics'][0]['nodes'].pop()
        value['decisions'].append({'id': 'OQ-1', 'area': 'Topic exemption', 'status': 'open', 'models': ['wh_billing__customer_dim']})
        self.assertIsNone(lint(value, 'gold_without_topic')[0]['resolved_by'])

    @unittest.skipUnless(HAS_YAML, 'Optional YAML parser unavailable')
    def test_placement_flags_stored_ratios_and_query_time_fixed_rules(self):
        value = page()
        value['files'][0]['content'] = ('select invoice_pk,\n  safe_divide(paid, gross) as paid_rate,\n'
                                        '  count(distinct customer_fk) over () as n -- not a ratio / nullif(\n from x\n')
        value['files'][1]['content'] += ('  size_band:\n    sql: case when ${net_amount} < 10 then \'s\' when ${net_amount} < 100 then \'m\' '
                                         'when ${net_amount} < 1000 then \'l\' else \'xl\' end\n'
                                         '  amount_rank:\n    sql: rank() over (order by ${net_amount})\n')
        found = lint(value, 'placement')
        self.assertEqual(len(found), 3)
        self.assertIn('ratio and distinct count', found[0]['message'])
        self.assertEqual({f['message'].split(' ')[0] for f in found[1:]}, {'invoices.size_band', 'invoices.amount_rank'})
        self.assertEqual(found[1]['models'], ['wh_billing__invoice_fct'])
        self.assertEqual(lints.lint_page(value)['status'], 'pass', 'Placement is advisory')

    def test_fallbacks_mixing_levels_are_banned_unless_a_decision_is_cited(self):
        value = page()
        sql = ('select\n  coalesce(industry.description_2, industry.industry_description) as industry_lvl_2,\n'
               '  coalesce(a.code_1, b.code_1) as same_level,\n  coalesce(a.amount, 0) as amount,\n'
               '  ifnull(nace.level_2_name, nace.level_4_name) as mixed\nfrom x\n')
        value['files'].append({'path': '02_dbt/models/warehouse/wh_billing__industry.sql', 'content': sql})
        found = lint(value, 'level_mixing_fallback')
        self.assertEqual([(f['line'], f['resolved_by']) for f in found], [(2, None), (5, None)])
        self.assertEqual(lints.lint_page(value)['status'], 'fail')
        value['decisions'] = [{'id': 'D-7', 'status': 'assumed', 'area': 'Definition', 'models': []}]
        value['files'][-1]['content'] = sql.replace('as industry_lvl_2,', 'as industry_lvl_2,  -- D-7: legacy fallback kept')
        value['files'][-1]['content'] = value['files'][-1]['content'].replace('as mixed', 'as mixed -- D-99 is not recorded')
        found = lint(value, 'level_mixing_fallback')
        self.assertEqual([f['resolved_by'] for f in found], ['D-7', None])

    def test_every_own_domain_gold_table_must_be_reached_or_exempted(self):
        value = page()
        value['topics'][0]['nodes'].pop()
        found = lint(value, 'gold_without_topic')
        self.assertEqual([f['models'] for f in found], [['wh_billing__customer_dim']], 'Other-domain tables are their owner\'s concern')
        self.assertEqual(lints.lint_page(value)['status'], 'fail')
        value['decisions'].append({'id': 'D-3', 'area': 'Topic exemption', 'status': 'answered', 'models': ['wh_billing__customer_dim']})
        self.assertEqual(lints.lint_page(value)['status'], 'pass')
        with self.assertRaisesRegex(ValueError, 'Modeling gate failed'):
            lints.require_gate(lints.lint_page(dict(value, decisions=[])))

    @unittest.skipUnless(HAS_YAML, 'Optional YAML parser unavailable')
    def test_semantic_descriptions_reject_migration_language(self):
        value = page()
        bad = {'Ported from the Looker explore.': 'legacy BI tool', 'Same as the legacy field.': 'legacy reference',
               'Kept for the migration.': 'migration note', 'Provisional until approved.': 'provisional status',
               'Used on dashboard 575.': 'dashboard or tile number', 'See DATA-1234.': 'ticket ID',
               'Matches the hippocampus model.': 'legacy system name'}
        for text, label in bad.items():
            with self.subTest(text=text):
                value['files'][1]['content'] = f'table_name: t\ndimensions:\n  a:\n    description: "{text}"\n'
                value['meta']['legacy_terms'] = ['hippocampus']
                found = lint(value, 'description_language')
                self.assertEqual(len(found), 1)
                self.assertIn(label, found[0]['message'])
        for text in ('Dates follow ISO-8601.', 'Spend in the 12 months to date.', 'Customer looks up an order.'):
            with self.subTest(text=text):
                value['files'][1]['content'] = f'table_name: t\ndescription: "{text}"\n# Ported from Looker: comments are not descriptions\n'
                self.assertEqual(lint(value, 'description_language'), [])

    @unittest.skipUnless(HAS_YAML, 'Optional YAML parser unavailable')
    def test_command_line_reports_and_exits_non_zero_on_a_failed_gate(self):
        value = page()
        value['topics'][0]['nodes'].pop()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'page.json'
            path.write_text(json.dumps(value))
            out = Path(temp) / 'report.json'
            with redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(lints.main([str(path), '--output', str(out)]), 1)
            self.assertIn('Gold tables not reached by a topic: 1 open', printed.getvalue())
            self.assertEqual(json.loads(out.read_text())['status'], 'fail')
            path.write_text(json.dumps(page()))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(lints.main([str(path)]), 0)


if __name__ == '__main__':
    unittest.main()
