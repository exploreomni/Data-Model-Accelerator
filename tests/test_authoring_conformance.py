import copy
from pathlib import Path
import tempfile
import unittest
from test_authoring_evidence import contract
from authoring_conformance import check_conformance

try:
    import sqlglot
except ImportError:
    sqlglot = None


@unittest.skipUnless(sqlglot, 'Optional SQL parser')
class ConformanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.contract = contract()
        self.contract['models'][0]['depends_on'] = []

    def check(self, sql):
        (self.root/'orders.sql').write_text(sql)
        return check_conformance(self.root, self.contract, ['orders.sql'], 'snowflake')

    def test_cte_star_is_resolved_and_physical_star_is_not_guessed(self):
        good = self.check('with a as (select 1 as id) select * from a')
        self.assertIn('output_columns_match', [r['code'] for r in good])
        bad = self.check('select * from raw_orders')
        self.assertIn('output_projection_unsupported', [r['code'] for r in bad])

    def test_drift_and_expression_contract_are_observable_in_both_modes(self):
        for mode in ('provisional', 'reviewed_candidate'):
            self.contract['mode'] = mode
            self.contract['models'][0]['expressions'] = {'id': 'coalesce(order_id, 0)'}
            rows = self.check('select coalesce(order_id, 99) as id from orders')
            self.assertIn('expression_differs', [r['code'] for r in rows])
            self.assertIn('dependencies_differ', [r['code'] for r in rows])

    def test_unknown_contract_and_template_remain_gaps(self):
        self.contract['models'][0].update(columns=None, depends_on=None)
        rows = self.check('select id from raw_orders')
        self.assertEqual(sum(r['status'] == 'not_run' for r in rows), 2)
        rows = self.check("select {{ unknown_macro() }} as id")
        self.assertEqual(rows[0]['status'], 'unsupported')

    def test_actual_cycle_detected_and_dead_cte_not_a_dependency(self):
        second = copy.deepcopy(self.contract['models'][0]); second.update(id='customers', path='customers.sql')
        self.contract['models'].append(second)
        (self.root/'orders.sql').write_text("select id from {{ ref('customers') }}")
        (self.root/'customers.sql').write_text("select id from {{ ref('orders') }}")
        rows = check_conformance(self.root, self.contract, ['orders.sql','customers.sql'], 'snowflake')
        self.assertEqual(sum(r['code'] == 'observed_dependency_cycle' for r in rows), 2)
        rows = self.check('with dead as (select id from hidden) select 1 as id')
        self.assertIn('dependencies_match', [r['code'] for r in rows])

    def test_no_short_name_binding_for_package_qualified_ref(self):
        self.contract['models'][0]['depends_on'] = ['ref:external.customers']
        rows = self.check("select id from {{ ref('external', 'customers') }}")
        self.assertIn('dependencies_match', [r['code'] for r in rows])

    def test_version_and_spacing_preserve_canonical_dependency_without_short_name_binding(self):
        self.contract['models'][0]['depends_on'] = ['ref:orders@version=2']
        rows = self.check("select id from {{ ref (\n 'orders', v = 2\n) }}")
        self.assertIn('dependencies_match', [r['code'] for r in rows])
        self.assertNotIn('observed_dependency_cycle', [r['code'] for r in rows])
        self.contract['models'][0]['depends_on'] = ['ref:orders@version=1']
        rows = self.check("select id from {{ref('orders',version=2)}}")
        self.assertIn('dependencies_differ', [r['code'] for r in rows])

    def test_cte_column_aliases_and_qualified_star_modifiers_never_false_pass(self):
        for sql in ('with x(new_id) as (select id from raw) select * from x',
                    'with x as (select id, hidden from raw) select x.* exclude(hidden) from x'):
            rows = self.check(sql)
            self.assertIn('output_projection_unsupported', [r['code'] for r in rows])
            self.assertNotIn('output_columns_match', [r['code'] for r in rows])

    def test_real_placeholder_named_table_remains_dependency(self):
        self.contract['models'][0]['depends_on'] = ['ref:customers']
        rows = self.check("select a.id from {{ ref('customers') }} a join raw.d0 b on a.id=b.id")
        self.assertIn('dependencies_differ', [r['code'] for r in rows])


if __name__ == '__main__': unittest.main()
