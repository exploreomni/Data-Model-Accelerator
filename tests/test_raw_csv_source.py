"""Synthetic CSV metadata, bounded coverage and data-value non-disclosure."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from raw_csv_source import inspect_csv


class RawCsvSourceTests(unittest.TestCase):
    def codes(self, result):
        return {g['code'] for g in result['gaps']}

    def test_exact_bytes_headers_logical_rows_and_text_types_without_cell_values(self):
        data = b'\xef\xbb\xbfid,amount,note\r\n001,0.100001,"PRIVATE_SENTINEL\r\nsecond line"\r\n002,,"=dangerous()"\r\n'
        result = inspect_csv(data)
        self.assertTrue(result['metadata_complete'])
        self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(result['size_bytes'], len(data))
        self.assertEqual(result['row_count'], 2)
        self.assertEqual(result['columns'], [
            {'position': 1, 'name': 'id', 'data_type': 'text'},
            {'position': 2, 'name': 'amount', 'data_type': 'text'},
            {'position': 3, 'name': 'note', 'data_type': 'text'}])
        encoded = json.dumps(result)
        for cell in ('PRIVATE_SENTINEL', 'second line', '=dangerous()', '0.100001'):
            self.assertNotIn(cell, encoded)
        self.assertEqual(result['source_platform'], 'unknown')
        self.assertFalse(result['native_types_verified'])
        self.assertEqual(result, inspect_csv(data))

    def test_header_only_is_zero_rows_but_empty_file_lacks_header(self):
        header = inspect_csv(b'id,value\n')
        self.assertTrue(header['metadata_complete'])
        self.assertEqual(header['row_count'], 0)
        empty = inspect_csv(b'')
        self.assertIsNone(empty['row_count'])
        self.assertIn('missing_header', self.codes(empty))

    def test_malformed_headers_and_records_are_explicit_gaps(self):
        cases = [
            (b'id,id\n1,2\n', 'duplicate_headers'),
            (b'ID, id \n1,2\n', 'ambiguous_normalized_headers'),
            (b'id, \n1,2\n', 'blank_header'),
            (b'\n1,2\n', 'blank_header'),
            (b'id,value\n1\n2,3,4\n', 'ragged_rows'),
            (b'id,value\n1,"SECRET_UNCLOSED\n', 'csv_parse_error_or_runtime_field_limit'),
            (b'id\n\xff', 'unsupported_encoding'),
            (b'id\n\0', 'nul_byte'),
        ]
        for data, code in cases:
            with self.subTest(code=code):
                result = inspect_csv(data)
                self.assertFalse(result['metadata_complete'])
                self.assertIn(code, self.codes(result))
                self.assertNotIn('SECRET_UNCLOSED', json.dumps(result))
                self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
        ragged = inspect_csv(b'id,value\n1\n2,3,4\n')
        self.assertEqual(ragged['row_count'], 2)
        self.assertEqual(ragged['gaps'], [{'code': 'ragged_rows', 'count': 2}])

    def test_row_column_and_field_bounds_never_claim_complete_count(self):
        exact = inspect_csv(b'id\n1\n2\n', max_rows=2)
        self.assertTrue(exact['metadata_complete'])
        limited = inspect_csv(b'id\n1\n2\n3\n', max_rows=2)
        self.assertIsNone(limited['row_count'])
        self.assertEqual(limited['records_observed'], 2)
        self.assertIn('row_limit', self.codes(limited))
        columns = inspect_csv(b'a,b,c\n1,2,3\n', max_columns=2)
        self.assertEqual(columns['columns'], [])
        self.assertIn('column_limit', self.codes(columns))
        field = inspect_csv(b'id\nSECRET_LONG_VALUE\n', max_field_chars=4)
        self.assertIn('field_size_limit', self.codes(field))
        self.assertNotIn('SECRET_LONG_VALUE', json.dumps(field))

    def test_invalid_options_rejected(self):
        for options in ({'max_rows': True}, {'max_rows': 0}, {'max_columns': -1}, {'max_field_chars': 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                inspect_csv(b'id\n1\n', **options)
        with self.assertRaises(ValueError):
            inspect_csv('id\n1\n')


if __name__ == '__main__':
    unittest.main()
