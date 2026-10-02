"""DB-API wire-type normalization without SQL execution or copied data."""
import copy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import export_results as export


def description(*names):
    return [(name, None, None, None, None, None, None) for name in names]


class ExportResultsTests(unittest.TestCase):
    def setUp(self):
        self.columns = {'id': {'type': 'integer', 'nullable': False},
                        'amount': {'type': 'decimal', 'nullable': True},
                        'observed': {'type': 'string', 'nullable': True},
                        'active': {'type': 'boolean', 'nullable': False}}
        self.description = description(*self.columns)

    def serialize(self, rows, columns=None, metadata=None, keys=None):
        return export.serialize_rows(self.description if metadata is None else metadata,
                                     rows, self.columns if columns is None else columns,
                                     ['id'] if keys is None else keys)

    def test_precision_nulls_boolean_and_reordered_dbapi_columns(self):
        columns = copy.deepcopy(self.columns)
        value = Decimal('123456789012345678901234567890.12345678901234567890123456789')
        rows = [(True, value, Decimal('7.000'), None), (False, None, 8, '  untouched text  ')]
        actual = self.serialize(iter(rows), metadata=description('active', 'amount', 'id', 'observed'))
        self.assertEqual(actual, [{'active': True, 'amount': str(value), 'id': 7, 'observed': None},
                                  {'active': False, 'amount': None, 'id': 8, 'observed': '  untouched text  '}])
        self.assertEqual(self.columns, columns)
        self.assertIs(rows[0][1], value)

    def test_decimal_normalization_preserves_scale_exponent_float_and_string(self):
        values = [Decimal('1.2300'), Decimal('1E+20'), Decimal('-0.0000'),
                  37.0, 0.1, 4, '7.8900', '1e-20']
        expected = ['1.2300', '1E+20', '-0.0000', '37.0', '0.1', '4', '7.8900', '1e-20']
        # A small arithmetic context must not round a fetched Decimal.
        with localcontext() as context:
            context.prec = 3
            rows = self.serialize((i, value, None, True) for i, value in enumerate(values))
        self.assertEqual([row['amount'] for row in rows], expected)
        self.assertTrue(all(type(row['amount']) is str for row in rows))

    def test_date_naive_and_offset_datetime_preserve_native_iso_values(self):
        values = [date(2024, 2, 29), datetime(2024, 2, 29, 3, 4, 5, 6007),
                  datetime(2024, 3, 1, 0, 15, 30, 123456,
                           tzinfo=timezone(timedelta(hours=5, minutes=45))),
                  datetime(2024, 1, 1, 23, 30, tzinfo=timezone(timedelta(hours=-7))),
                  datetime(2024, 1, 1, tzinfo=timezone.utc)]
        actual = self.serialize((i, None, value, False) for i, value in enumerate(values))
        self.assertEqual([row['observed'] for row in actual],
                         ['2024-02-29', '2024-02-29 03:04:05.006007',
                          '2024-03-01 00:15:30.123456+05:45',
                          '2024-01-01 23:30:00-07:00', '2024-01-01 00:00:00+00:00'])

    def test_integer_decimal_is_exact_and_float_string_boolean_are_rejected(self):
        value = Decimal('123456789012345678901234567890.000')
        with localcontext() as context:
            context.prec = 3
            actual = self.serialize([(value, None, None, True)])
        self.assertEqual(actual[0]['id'], 123456789012345678901234567890)
        for value in (37.0, '37', True, False, Decimal('37.1'),
                      Decimal('NaN'), Decimal('sNaN'), Decimal('Infinity')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.serialize([(value, None, None, True)])

    def test_nonfinite_boolean_and_invalid_decimal_values_are_rejected(self):
        values = [float('nan'), float('inf'), float('-inf'), Decimal('NaN'),
                  Decimal('sNaN'), Decimal('Infinity'), Decimal('-Infinity'),
                  True, False, 'NaN', 'Infinity', '1_000', ' 1', '',
                  Decimal('1e1001'), '9' * 129, object()]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.serialize([(1, value, None, True)])

    def test_booleans_and_strings_reject_coercion(self):
        for value in (0, 1, 'true', Decimal(1), 1.0):
            with self.subTest(active=value), self.assertRaises(ValueError):
                self.serialize([(1, None, None, value)])
        for value in (1, True, Decimal('2'), b'text', object()):
            with self.subTest(observed=value), self.assertRaises(ValueError):
                self.serialize([(1, None, value, True)])

    def test_nullability_and_composite_keys_use_existing_validator(self):
        for row in [(None, None, None, True), (1, None, None, None)]:
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'Unexpected null'):
                self.serialize([row])
        with self.assertRaisesRegex(ValueError, 'Duplicate composite key'):
            self.serialize([(1, None, None, True), (Decimal('1.0'), None, None, False)])
        columns = {'scope': {'type': 'string', 'nullable': False},
                   'id': {'type': 'decimal', 'nullable': False}}
        metadata = description('scope', 'id')
        actual = self.serialize([('a', Decimal('1.00')), ('b', 1.0)], columns, metadata, ['scope', 'id'])
        self.assertEqual(actual, [{'scope': 'a', 'id': '1.00'}, {'scope': 'b', 'id': '1.0'}])
        with self.assertRaisesRegex(ValueError, 'Duplicate composite key'):
            self.serialize([('a', Decimal('1.00')), ('a', 1.0)], columns, metadata, ['scope', 'id'])

    def test_empty_population_still_requires_exact_description_and_valid_contract(self):
        self.assertEqual(self.serialize(iter(())), [])
        invalid_descriptions = [description('id', 'amount', 'observed'),
                                description('id', 'amount', 'observed', 'active', 'extra'),
                                description('ID', 'amount', 'observed', 'active'),
                                description('id', 'amount', 'amount', 'active'),
                                description('id', 'amount', 'observed', 'other')]
        for metadata in invalid_descriptions:
            with self.subTest(description=metadata), self.assertRaises(ValueError):
                self.serialize([], metadata=metadata)
        for keys in ([], ['missing'], ['id', 'id']):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                self.serialize([], keys=keys)
        for columns in ({}, dict(self.columns, id={'type': 'integer', 'nullable': True}),
                        dict(self.columns, amount={'type': 'float', 'nullable': True}),
                        dict(self.columns, id={'type': 'integer', 'nullable': False, 'abs_tolerance': '1'})):
            with self.subTest(columns=columns), self.assertRaises(ValueError):
                self.serialize([], columns=columns)

    def test_invalid_contract_is_rejected_before_consuming_row_generator(self):
        def rows():
            self.fail('Invalid key contract must be rejected before reading data')
            yield (1, None, None, True)
        with self.assertRaises(ValueError):
            self.serialize(rows(), keys=['unknown'])

    def test_malformed_description_and_rows_do_not_silently_zip_or_drop_columns(self):
        for metadata in (None, 'id', {'id': None}, [(), ('amount',), ('observed',), ('active',)],
                         [(1,), ('amount',), ('observed',), ('active',)],
                         ['id', ('amount',), ('observed',), ('active',)]):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                export.serialize_rows(metadata, [], self.columns, ['id'])
        for row in ((1, None, None), (1, None, None, True, 'extra'),
                    {'id': 1, 'amount': None, 'observed': None, 'active': True},
                    '1234', {1, 2, 3, 4}, None):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.serialize([row])
        for rows in (None, 'rows', {}, set()):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.serialize(rows)

    def test_generator_is_fully_consumed_and_late_failure_is_not_hidden(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate composite key'):
            self.serialize((row for row in [(1, '2', None, True), (1, '3', None, True)]))
        def incomplete_rows():
            yield (1, None, None, True)
            raise RuntimeError('source fetch failed')
        with self.assertRaisesRegex(RuntimeError, 'source fetch failed'):
            self.serialize(incomplete_rows())

    def test_row_bound_rejects_overflow_instead_of_returning_partial_population(self):
        consumed = []
        def rows():
            for i in range(5):
                consumed.append(i)
                yield (i, None, None, True)
        with patch.object(export, 'MAX_ROWS', 2):
            self.assertEqual(len(self.serialize([(0, None, None, True), (1, None, None, True)])), 2)
            with self.assertRaisesRegex(ValueError, 'not truncated'):
                self.serialize(rows())
        self.assertEqual(consumed, [0, 1, 2])

    def test_infinite_row_width_is_bounded_and_not_silently_truncated(self):
        consumed = []
        def values():
            while True:
                consumed.append(1)
                yield 1
        with self.assertRaisesRegex(ValueError, 'width'):
            self.serialize([values()])
        self.assertEqual(len(consumed), len(self.columns) + 1)


if __name__ == '__main__':
    unittest.main()
