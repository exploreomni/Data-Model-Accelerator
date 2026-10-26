"""Deterministic pre-review SQL checks on synthetic dbt models; nothing is compiled or executed."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import sql_contracts as sc

STG = """WITH s_datasource AS (
    SELECT * FROM {{ source('shop', 'orders') }}
),
renamed_and_cast AS (
    SELECT
        CAST(id AS STRING) AS order_natural_key,
        CAST(customer_id AS STRING) AS order_customer_natural_key,
        LOWER(CAST(status AS STRING)) AS order_status, -- comment with a.fake_column
        CAST(created_at AS TIMESTAMP) AS order_created_ts
    FROM s_datasource
),
final AS (SELECT * FROM renamed_and_cast)
SELECT * FROM final
"""
CUSTOMER = """WITH s_customer AS (SELECT * FROM {{ source('shop', 'customers') }}),
final AS (
    SELECT
        CAST(id AS STRING) AS customer_natural_key,
        LOWER(TRIM(email)) AS customer_email
    FROM s_customer
    WHERE is_test = FALSE
)
SELECT * FROM final
"""
INT_ORDER = """WITH s_order AS (SELECT * FROM {{ ref('stg_shop__orders') }}),
s_customer AS (SELECT * FROM {{ ref('int_shop__customer') }}),
final AS (
    SELECT
        s_order.order_natural_key,
        {{ dbt_utils.generate_surrogate_key(['s_customer.customer_email']) }} AS customer_hashed_natural_key,
        s_order.order_statuss AS order_status,
        IF(s_order.order_status = 'shipped', TRUE, FALSE) AS order_is_shipped,
        s_order.order_status IN ('cancelled', 'refunded') AS order_is_reversed
    FROM s_order
    LEFT JOIN s_customer
        ON s_order.order_customer_natural_key = s_customer.customer_natural_key
)
SELECT * FROM final
"""
WH_ORDER = """WITH s_order AS (SELECT * FROM {{ ref('int_shop__order') }}),
final AS (
    SELECT
        {{ dbt_utils.generate_surrogate_key(['order_natural_key']) }} AS order_pk,
        {{ dbt_utils.generate_surrogate_key(['customer_hashed_natural_key']) }} AS customer_fk,
        order_natural_key,
        MD5(customer_hashed_natural_key) AS customer_hashed_natural_key
    FROM s_order
)
SELECT * FROM final
"""
WH_CUSTOMER = """WITH s_customer AS (SELECT * FROM {{ ref('int_shop__customer') }}),
final AS (
    SELECT
        {{ dbt_utils.generate_surrogate_key(['customer_natural_key']) }} AS customer_pk,
        customer_natural_key
    FROM s_customer
)
SELECT * FROM final
"""
UPSTREAM_ONLY = """SELECT CAST(id AS STRING) AS region_natural_key, name AS region_name FROM {{ source('shop', 'regions') }}"""
USES_UPSTREAM = """WITH s_region AS (SELECT * FROM {{ ref('stg_shop__regions') }}),
final AS (SELECT s_region.region_natural_key, s_region.region_code FROM s_region)
SELECT * FROM final
"""


class SqlContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.candidate, self.upstream = root / 'candidate', root / 'upstream'
        files = {'staging/stg_shop__orders.sql': STG, 'integration/int_shop__customer.sql': CUSTOMER,
                 'integration/int_shop__order.sql': INT_ORDER, 'warehouse/wh_shop__order_fct.sql': WH_ORDER,
                 'warehouse/wh_shop__customer_dim.sql': WH_CUSTOMER, 'warehouse/wh_shop__region_dim.sql': USES_UPSTREAM}
        for rel, text in files.items():
            p = self.candidate / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        (self.upstream / 'staging').mkdir(parents=True)
        (self.upstream / 'staging/stg_shop__regions.sql').write_text(UPSTREAM_ONLY)
        # An upstream copy of a candidate model is shadowed by the candidate version.
        (self.upstream / 'staging/stg_shop__orders.sql').write_text('SELECT 1 AS unrelated')

    def report(self, contract=None):
        return sc.run([self.candidate, self.upstream], contract)

    def codes(self, report, code):
        return [f for f in report['findings'] if f['code'] == code]

    def test_missing_columns_are_found_through_ctes_refs_and_upstream(self):
        r = self.report()
        missing = {(f['model'], f['reference']) for f in self.codes(r, 'column.missing')}
        self.assertIn(('int_shop__order', 's_order.order_statuss'), missing)
        self.assertIn(('wh_shop__region_dim', 's_region.region_code'), missing)
        self.assertNotIn(('int_shop__order', 's_customer.customer_email'), missing)  # read from a macro argument
        self.assertFalse(any('fake_column' in ref for _, ref in missing))  # comments are ignored
        self.assertEqual('failed', r['status'])
        self.assertGreater(r['coverage']['verified'], 0)

    def test_star_over_unresolvable_relation_is_a_gap_not_an_empty_model(self):
        p = self.candidate / 'staging/stg_shop__dedup.sql'
        p.write_text("WITH d AS (SELECT * FROM ({{ pleo_dbt_common.dedup('x', 'y DESC', 'z') }}))\nSELECT * FROM d\n")
        (self.candidate / 'integration/int_shop__dedup.sql').write_text(
            "WITH s AS (SELECT * FROM {{ ref('stg_shop__dedup') }})\nSELECT s.anything FROM s\n")
        r = self.report()
        self.assertIn('stg_shop__dedup', r['models_with_unresolved_outputs'])
        self.assertFalse(any(f['model'] == 'int_shop__dedup' for f in self.codes(r, 'column.missing')))

    def test_key_contracts_and_divergent_definitions(self):
        contract = {'schema_version': 1, 'keys': [
            {'id': 'customer', 'column': 'customer_hashed_natural_key', 'models': ['int_shop__order', 'wh_shop__customer_dim'],
             'pattern': r'generate_surrogate_key|customer_email'},
            {'id': 'order', 'column': 'order_natural_key', 'models': ['wh_shop__order_fct'], 'pattern': r'^md5\('}]}
        r = self.report(contract)
        self.assertEqual([('wh_shop__customer_dim', 'customer_hashed_natural_key')],
                         [(f['model'], f['column']) for f in self.codes(r, 'key.missing')])
        self.assertEqual(['wh_shop__order_fct'], [f['model'] for f in self.codes(r, 'key.construction_mismatch')])
        divergent = self.codes(r, 'key.divergent_definition')
        self.assertEqual(['customer_hashed_natural_key'], [f['column'] for f in divergent])
        self.assertEqual(2, len(divergent[0]['definitions']))

    def test_foreign_key_population_needs_an_acknowledgement(self):
        fk = {'model': 'wh_shop__order_fct', 'column': 'customer_fk', 'target_model': 'wh_shop__customer_dim',
              'target_column': 'customer_pk'}
        r = self.report({'schema_version': 1, 'foreign_keys': [fk]})
        finding = self.codes(r, 'fk.population_unconfirmed')
        self.assertEqual(1, len(finding))
        self.assertTrue(any('is_test = FALSE' in f for f in finding[0]['target_filters']))
        r = self.report({'schema_version': 1, 'foreign_keys': [dict(fk, population_resolution='Test customers place no orders.')]})
        self.assertFalse(self.codes(r, 'fk.population_unconfirmed'))
        r = self.report({'schema_version': 1, 'foreign_keys': [dict(fk, target_column='customer_id')]})
        self.assertEqual(1, len(self.codes(r, 'fk.column_missing')))

    def test_literals_are_checked_against_known_values(self):
        r = self.report({'schema_version': 1, 'known_values': {'order_status': ['shipped', 'cancelled', 'refunded [ticket]']}})
        unknown = self.codes(r, 'literal.unknown_value')
        self.assertEqual(['refunded'], [f['value_preview'] for f in unknown])
        r = self.report()
        self.assertTrue(self.codes(r, 'literal.unverified'))
        self.assertFalse(self.codes(r, 'literal.unknown_value'))

    def test_cli_writes_report_and_prints_one_line(self):
        out = Path(self.tmp.name) / 'report.json'
        run = subprocess.run([sys.executable, str(SCRIPTS / 'sql_contracts.py'), '--models', str(self.candidate),
                              '--upstream', str(self.upstream), '--output', str(out)], capture_output=True, text=True)
        self.assertEqual(1, run.returncode)
        self.assertEqual(1, len(run.stdout.strip().splitlines()))
        self.assertIn('sql contracts: failed', run.stdout)
        self.assertEqual('sql_contract_check', json.loads(out.read_text())['kind'])
        again = subprocess.run([sys.executable, str(SCRIPTS / 'sql_contracts.py'), '--models', str(self.candidate),
                                '--output', str(out)], capture_output=True, text=True)
        self.assertNotEqual(0, again.returncode)  # never overwrites a report

    def test_bad_contract_is_rejected(self):
        with self.assertRaises(ValueError):
            self.report({'schema_version': 2})
        with self.assertRaises(ValueError):
            self.report({'schema_version': 1, 'keys': [{'column': 'x'}]})


if __name__ == '__main__':
    unittest.main()
