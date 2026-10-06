"""Execute independent frozen arithmetic and negative controls, never Omni SQL.

SQLite validates these synthetic rows and an independent relational oracle. It
does not establish Omni compilation, symmetric aggregates or warehouse parity.
"""
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest

ROOT = Path(__file__).parent / 'fixtures/omni_modeler'
NUMERIC = {'line_count', 'sold_quantity', 'gross_cents', 'return_count', 'returned_quantity',
           'refund_cents', 'paid_gross_cents', 'paid_refund_cents', 'paid_net_cents',
           'quantity', 'unit_price_cents', 'shipping_cents', 'order_count',
           'paid_order_count', 'paid_shipping_cents'}
ORDER_SQL = '''WITH lines AS (
  SELECT order_id, COUNT(*) line_count, SUM(quantity) sold_quantity,
         SUM(quantity * unit_price_cents) gross_cents FROM order_lines GROUP BY order_id
), refunds AS (
  SELECT l.order_id, COUNT(*) return_count, SUM(r.quantity) returned_quantity,
         SUM(r.refund_cents) refund_cents
  FROM returns r JOIN order_lines l ON r.line_id = l.line_id GROUP BY l.order_id
)
SELECT o.order_id, COALESCE(l.line_count,0) line_count,
  COALESCE(l.sold_quantity,0) sold_quantity, COALESCE(l.gross_cents,0) gross_cents,
  COALESCE(r.return_count,0) return_count, COALESCE(r.returned_quantity,0) returned_quantity,
  COALESCE(r.refund_cents,0) refund_cents,
  CASE WHEN o.status='paid' THEN COALESCE(l.gross_cents,0) ELSE 0 END paid_gross_cents,
  CASE WHEN o.status='paid' THEN COALESCE(r.refund_cents,0) ELSE 0 END paid_refund_cents,
  CASE WHEN o.status='paid' THEN COALESCE(l.gross_cents,0)-COALESCE(r.refund_cents,0) ELSE 0 END paid_net_cents,
  b.label buyer_label, s.label seller_label, h.segment asof_segment
FROM orders o LEFT JOIN lines l ON o.order_id=l.order_id
LEFT JOIN refunds r ON o.order_id=r.order_id
LEFT JOIN parties b ON o.buyer_party_id=b.party_id
LEFT JOIN parties s ON o.seller_party_id=s.party_id
LEFT JOIN customer_history h ON o.customer_id=h.customer_id
  AND h.valid_from<=o.placed_on AND (o.placed_on<h.valid_to OR h.valid_to IS NULL)
'''
QUERY_SQL = '''SELECT customer_id, COUNT(*) order_count,
  SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) paid_order_count,
  SUM(shipping_cents) shipping_cents,
  SUM(CASE WHEN status='paid' THEN shipping_cents ELSE 0 END) paid_shipping_cents
  FROM orders GROUP BY customer_id'''


def read_json(path):
    return json.loads((ROOT / path).read_text())


def read_rows(path):
    with (ROOT / path).open(newline='') as handle:
        return [{key: None if value == '' else int(value) if key in NUMERIC else value
                 for key, value in row.items()} for row in csv.DictReader(handle)]


def rational(value):
    return None if value is None else Fraction(value['numerator'], value['denominator'])


class SemanticCorpusTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.contract = read_json('corpus.json')
        self.expected = read_json('expected/metrics.json')
        self.variants = read_json('expected/variants.json')
        for name, table in self.contract['tables'].items():
            rows = read_rows(table['path'])
            columns = list(rows[0])
            # Identifiers below are frozen test constants, never user SQL.
            self.db.execute('CREATE TABLE ' + name + ' (' + ','.join(
                column + (' INTEGER' if column in NUMERIC else ' TEXT') for column in columns) + ')')
            self.insert(name, rows)

    def insert(self, table, rows):
        self.db.executemany('INSERT INTO ' + table + ' VALUES (' + ','.join('?' for _ in rows[0]) + ')',
                            [tuple(row.values()) for row in rows])

    def rows(self, sql):
        return [dict(row) for row in self.db.execute(sql)]

    def assert_rows(self, actual, expected, key):
        self.assertEqual(len({r[key] for r in actual}), len(actual), 'Candidate contains duplicate keys')
        self.assertEqual({r[key]: r for r in actual}, {r[key]: r for r in expected})

    def totals(self):
        rows = self.rows(ORDER_SQL)
        return {field: sum(row[field] for row in rows) for field in NUMERIC if field in rows[0]}

    def test_frozen_files_are_unchanged(self):
        frozen = read_json('FROZEN_SHA256.json')
        records = frozen.get('files', frozen)
        for path, digest in records.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)

    def test_grains_and_foreign_keys(self):
        for name, table in self.contract['tables'].items():
            grain = ','.join(table['grain'])
            self.assertEqual(self.rows('SELECT ' + grain + ' FROM ' + name + ' GROUP BY ' + grain + ' HAVING COUNT(*)>1'), [])
            for field, target in table.get('foreign_keys', {}).items():
                other, key = target.split('.')
                self.assertEqual(self.rows('SELECT x.'+field+' FROM '+name+' x LEFT JOIN '+other+
                    ' y ON x.'+field+'=y.'+key+' WHERE y.'+key+' IS NULL'), [])

    def test_every_order_matches_independent_rows_including_empty_order(self):
        self.assert_rows(self.rows(ORDER_SQL), read_rows('expected/orders.csv'), 'order_id')
        totals = self.totals()
        for field, value in totals.items():
            if field in self.expected['totals']:
                self.assertEqual(value, self.expected['totals'][field], field)
        self.assertEqual(Fraction(totals['paid_refund_cents'], totals['paid_gross_cents']),
                         rational(self.expected['totals']['paid_refund_rate']))

    def test_buyer_seller_and_current_asof_are_distinct(self):
        rows = self.rows(ORDER_SQL)
        for field, expected in [('buyer_label','paid_gross_by_buyer'), ('seller_label','paid_gross_by_seller'),
                                ('asof_segment','paid_gross_by_asof_segment')]:
            grouped = {}
            for row in rows: grouped[row[field]] = grouped.get(row[field], 0) + row['paid_gross_cents']
            self.assertEqual(grouped, self.expected[expected])
        current = self.rows('SELECT h.segment, SUM(m.paid_gross_cents) amount FROM (' + ORDER_SQL +
            ') m JOIN orders o ON m.order_id=o.order_id JOIN customer_history h ON o.customer_id=h.customer_id '
            'AND h.valid_to IS NULL GROUP BY h.segment')
        self.assertEqual({r['segment']:r['amount'] for r in current}, self.expected['paid_gross_by_current_segment'])

    def test_measure_local_filters_preserve_control_population(self):
        rows = self.rows(QUERY_SQL)
        self.assert_rows(rows, read_rows('expected/query_orders_by_customer.csv'), 'customer_id')
        for row in rows:
            expected = self.expected['customer_metrics'][row['customer_id']]
            self.assertEqual(Fraction(row['paid_shipping_cents'], row['shipping_cents']), rational(expected['paid_shipping_share']))
        for row in self.rows("SELECT order_id, shipping_cents, CASE WHEN status='paid' THEN shipping_cents ELSE 0 END paid FROM orders"):
            actual = Fraction(row['paid'], row['shipping_cents']) if row['shipping_cents'] else None
            self.assertEqual(actual, rational(self.expected['paid_shipping_share_by_order'][row['order_id']]))
        wrong = self.rows(QUERY_SQL.replace('FROM orders GROUP', "FROM orders WHERE status='paid' GROUP"))
        with self.assertRaises(AssertionError): self.assert_rows(wrong, rows, 'customer_id')

    def test_fanout_distinct_and_ratio_negative_controls_fail(self):
        sentinels = self.expected['wrong_answer_sentinels']
        wrong = self.rows('SELECT COUNT(*) n, SUM(l.quantity*l.unit_price_cents) gross FROM orders o '
                         'LEFT JOIN order_lines l ON o.order_id=l.order_id LEFT JOIN returns r ON l.line_id=r.line_id')[0]
        self.assertEqual(wrong['n'], sentinels['unaggregated_orders_lines_returns_join_rows'])
        self.assertEqual(wrong['gross'], sentinels['naive_line_gross_after_return_fanout'])
        self.assertNotEqual(wrong['gross'], self.expected['totals']['gross_cents'])
        wrong_distinct = self.db.execute('SELECT SUM(DISTINCT quantity*unit_price_cents) FROM order_lines').fetchone()[0]
        self.assertEqual(wrong_distinct, sentinels['sum_distinct_line_amounts'])
        self.assertNotEqual(wrong_distinct, self.expected['totals']['gross_cents'])
        rates = [Fraction(r['paid_refund_cents'], r['paid_gross_cents']) for r in self.rows(ORDER_SQL) if r['paid_gross_cents']]
        self.assertEqual(sum(rates), rational(sentinels['sum_of_nonzero_paid_order_refund_rates']))
        self.assertNotEqual(sum(rates), rational(self.expected['totals']['paid_refund_rate']))

    def test_additional_return_changes_refunds_without_changing_gross(self):
        before = self.totals(); self.insert('returns', read_rows('data/extra_return_append.csv'))
        after = self.totals(); expected = self.variants['counterfactual_extra_return']
        for field in ('paid_gross_cents','paid_refund_cents','paid_net_cents'):
            self.assertEqual(after[field], expected['total_'+field])
        for field in ('gross_cents','line_count','sold_quantity'):
            self.assertEqual(after[field], before[field])

    def test_price_change_changes_gross_without_changing_refunds(self):
        before = self.totals(); row = read_rows('data/amount_change.csv')[0]
        self.db.execute('UPDATE order_lines SET unit_price_cents=? WHERE line_id=?', (row['unit_price_cents'],row['line_id']))
        after = self.totals(); expected = self.variants['counterfactual_amount_change']
        for field in ('gross_cents','paid_gross_cents','paid_refund_cents','paid_net_cents'):
            self.assertEqual(after[field], expected['total_'+field])
        self.assertEqual(after['refund_cents'], before['refund_cents'])

    def test_temporal_overlap_and_duplicate_dimension_block_grain(self):
        baseline = self.rows(ORDER_SQL)
        self.insert('customer_history', read_rows('data/overlap_history_append.csv'))
        with self.assertRaises(AssertionError): self.assert_rows(self.rows(ORDER_SQL), baseline, 'order_id')
        self.assertEqual(self.totals()['paid_gross_cents'], self.variants['temporal_overlap']['incorrect_total_if_overlap_silently_fans_out'])
        self.db.execute("DELETE FROM customer_history WHERE history_id='ha_bad'")
        self.db.execute("INSERT INTO parties VALUES ('pa','Duplicate')")
        with self.assertRaises(AssertionError): self.assert_rows(self.rows(ORDER_SQL), baseline, 'order_id')

    def test_query_limit_is_incomplete_and_sql_query_oracle_matches(self):
        limited = self.rows(QUERY_SQL + ' ORDER BY shipping_cents DESC, customer_id LIMIT 1')
        expected = self.variants['top_one_customer_shipping']
        self.assertEqual(limited, expected['expected_rows'])
        self.assertNotEqual(sum(r['shipping_cents'] for r in limited), expected['all_customer_shipping_cents'])
        returns = self.rows('SELECT l.order_id, COUNT(*) return_count, SUM(r.quantity) returned_quantity, '
            'SUM(r.refund_cents) refund_cents FROM returns r JOIN order_lines l ON r.line_id=l.line_id GROUP BY l.order_id')
        self.assert_rows(returns, read_rows('expected/query_returns_by_order.csv'), 'order_id')

    def test_bridge_requires_explicit_deduplication_and_allocation(self):
        self.db.executescript('CREATE TABLE tags(order_id TEXT, tag TEXT, weight INTEGER); '
            "INSERT INTO tags VALUES ('o11','A',1),('o11','B',1),('o12','A',2),('o12','A',2);")
        # Independently constructed holdout: equal allocation for o11, dedupe o12.
        allocated = self.rows('WITH weights AS (SELECT DISTINCT order_id,tag,weight FROM tags), '
            'denom AS (SELECT order_id,SUM(weight) weight FROM weights GROUP BY order_id) '
            'SELECT w.tag,SUM(m.paid_gross_cents*w.weight/d.weight) amount FROM ('+ORDER_SQL+
            ') m JOIN weights w ON m.order_id=w.order_id JOIN denom d ON w.order_id=d.order_id GROUP BY w.tag')
        self.assertEqual({r['tag']:r['amount'] for r in allocated}, {'A':5250,'B':1250})
        wrong = self.db.execute('SELECT SUM(m.paid_gross_cents) FROM ('+ORDER_SQL+') m JOIN tags t ON m.order_id=t.order_id').fetchone()[0]
        self.assertNotEqual(wrong, 6500)


if __name__ == '__main__':
    unittest.main()
