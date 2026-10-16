"""Evidence, parser safety, and CLI boundaries independent of vendor fixtures."""
import importlib.util
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import os

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from source_adapters.base import Report, read_json, read_yaml, validate_files
from source_adapters.sql import parse_sql
from source_adapters.registry import validate
from run_source_adapter import collect


class ContractTests(unittest.TestCase):
    def test_duplicate_json_and_nonfinite_rejected(self):
        for text in ('{"id":1,"id":2}', '{"value":NaN}', '{"value":Infinity}'):
            with self.assertRaises(ValueError):
                read_json(text)

    def test_paths_and_bytes_are_bounded(self):
        for path in ('../x.sql', '/x.sql', 'a/../b.sql', 'a\\b.sql', 'a//b.sql', 'x\x00.sql', 'a/' * 48 + 'x.sql'):
            with self.assertRaises(ValueError):
                validate_files({path: 'select 1'})

    def test_collector_limits_directory_depth_before_recursing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'a/b/c').mkdir(parents=True)
            with patch('run_source_adapter.MAX_DEPTH', 3):
                with self.assertRaisesRegex(ValueError, 'source.path_depth_limit'):
                    collect(root)

    def test_staging_cannot_alias_case_unicode_or_file_directory_paths(self):
        for files in ({'Project.hex.yaml': 'A', 'project.hex.yaml': 'B'},
                      {'café.yml': 'A', 'cafe\u0301.yml': 'B'},
                      {'Dir/a.sql': 'A', 'dir/b.sql': 'B'},
                      {'a': 'A', 'a/b': 'B'}, {'a/b': 'B', 'a': 'A'}):
            with self.assertRaises(ValueError):
                validate_files(files)

    @unittest.skipUnless(importlib.util.find_spec('yaml'), 'Optional YAML parser')
    def test_yaml_aliases_duplicates_and_code_rejected(self):
        for text in ('a: 1\na: 2', 'a: &x [1]\nb: *x', '!!python/object/apply:os.system ["false"]'):
            with self.assertRaises(ValueError):
                read_yaml(text)

    def test_every_file_is_accounted_and_gaps_downgrade_coverage(self):
        r = Report('test', {'a.sql': 'select 1', 'unknown.bin': 'opaque'})
        r.cover('a.sql')
        r.gap('a.sql', 'test.unbound', 'Unknown binding')
        out = r.finish()
        validate(out, r.files)
        self.assertEqual([x['status'] for x in out['source_files']], ['partial', 'unsupported'])
        self.assertEqual(out['export_completeness'], 'not_established')
        self.assertFalse(out['execution_performed'])

    def test_contract_rejects_forged_evidence_and_execution(self):
        r = Report('test', {'a.sql': 'select 1'})
        r.object('a.sql', '$', 'query', 'one')
        pristine = copy.deepcopy(r.finish())
        out = copy.deepcopy(pristine)
        out['objects'][0]['evidence']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            validate(out, r.files)
        out = copy.deepcopy(pristine)
        out['execution_performed'] = True
        with self.assertRaises(ValueError):
            validate(out, r.files)
        out = copy.deepcopy(pristine)
        out['export_completeness'] = 'complete'
        with self.assertRaises(ValueError):
            validate(out, r.files)

    def test_collector_excludes_credentials_symlinks_and_binary(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / 'a.sql').write_text('select 1')
            (root / 'profiles.yml').write_text('password: secret')
            (root / 'blob.pbix').write_bytes(b'\x00\xff')
            (root / 'link.sql').symlink_to(root / 'a.sql')
            files, gaps = collect(root)
            self.assertEqual(files, {'a.sql': 'select 1'})
            self.assertEqual(len(gaps), 3)

    def test_directory_replaced_by_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d).resolve()
            root, outside = base / 'input', base / 'outside'
            (root / 'sub').mkdir(parents=True)
            outside.mkdir()
            (outside / 'private.sql').write_text('secret source')
            actual_open = os.open
            swapped = [False]
            def changing_open(path, flags, *args, **kwargs):
                if path == 'sub' and kwargs.get('dir_fd') is not None and not swapped[0]:
                    swapped[0] = True
                    (root / 'sub').rename(root / 'old')
                    (root / 'sub').symlink_to(outside, target_is_directory=True)
                return actual_open(path, flags, *args, **kwargs)
            with patch('run_source_adapter.os.open', side_effect=changing_open):
                with self.assertRaises(OSError):
                    collect(root)
            self.assertTrue(swapped[0])

    def test_gap_cannot_be_promoted_to_parsed(self):
        r = Report('test', {'a.sql': 'select 1'})
        r.gap('a.sql', 'test.missing', 'Missing context')
        out = r.finish()
        out['source_files'][0]['status'] = 'parsed'
        with self.assertRaises(ValueError):
            validate(out, r.files)

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQL parser')
    def test_cte_alias_is_not_physical_lineage(self):
        text = 'create view gold.sales as with scoped as (select id from raw.sales) select id from scoped'
        r = Report('bigquery', {'a.sql': text})
        parse_sql(r, 'a.sql', text, 'bigquery')
        out = r.finish()
        self.assertEqual([x['target'] for x in out['dependencies']], ['raw.sales'])
        self.assertEqual(out['objects'][0]['name'], 'gold.sales')
        self.assertEqual(out['expressions'][0]['text'], text)
        validate(out, r.files)

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQL parser')
    def test_embedded_queries_have_distinct_locations_and_keep_filter_and_join(self):
        r = Report('bigquery', {'a.json': '{}'})
        for i in range(2):
            parse_sql(r, 'a.json', 'select a.id from raw.a a join raw.b b on a.id=b.id where a.tenant_id=7', 'bigquery', locator='$.queries[%d]' % i)
        out = r.finish()
        self.assertEqual(len(out['objects']), 2)
        self.assertEqual(len({v['id'] for v in out['expressions']}), len(out['expressions']))
        self.assertEqual(sum(x['details'].get('expression_kind') == 'Where' for x in out['expressions']), 2)

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQL parser')
    def test_declared_keys_are_retained_without_claiming_enforcement(self):
        sql = 'CREATE TABLE fact_orders (id INT PRIMARY KEY, customer_id INT, FOREIGN KEY (customer_id) REFERENCES dim_customer(id))'
        r = Report('snowflake', {'a.sql': sql})
        parse_sql(r, 'a.sql', sql, 'snowflake')
        out = r.finish()
        key = next(o for o in out['objects'] if o['kind'] == 'column' and o['name'] == 'id')
        self.assertTrue(key['details']['primary_key_declared'])
        fk = next(d for d in out['dependencies'] if d['details']['kind'] == 'foreign_key')
        self.assertEqual(fk['details']['source_columns'], ['customer_id'])
        self.assertEqual(fk['details']['target_columns'], ['id'])
        self.assertEqual(fk['details']['enforcement'], 'not_verified')

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQL parser')
    def test_databricks_file_format_paths_are_not_catalogue_relations(self):
        for text in ('SELECT id FROM delta.`/mnt/raw/orders`', 'SELECT id FROM parquet.`s3://synthetic-bucket/orders`'):
            r = Report('databricks', {'a.sql': text})
            parse_sql(r, 'a.sql', text, 'databricks')
            out = r.finish()
            self.assertFalse(out['dependencies'])
            self.assertIn('sql.external_resource', {g['code'] for g in out['gaps']})
            self.assertEqual(out['expressions'][0]['text'], text)

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQL parser')
    def test_count_star_is_not_unexpanded_column_projection(self):
        r = Report('bigquery', {'a.sql': 'SELECT COUNT(*) FROM raw.orders'})
        parse_sql(r, 'a.sql', r.files['a.sql'], 'bigquery')
        self.assertFalse(any(g['code'] == 'sql.wildcard' for g in r.finish()['gaps']))

    def test_unknown_dialect_and_templates_never_claim_interpretation(self):
        for text, dialect in [('select 1', None), ('select * from {{ ref("x") }}', 'snowflake')]:
            r = Report('test', {'a.sql': text})
            parse_sql(r, 'a.sql', text, dialect)
            out = r.finish()
            self.assertTrue(out['gaps'])
            self.assertEqual(out['source_files'][0]['status'], 'partial')
            self.assertEqual(out['objects'], [])

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQL parser')
    def test_unsupported_ddl_and_dynamic_relations_have_gaps_without_logs(self):
        for text in ('CREATE SCHEMA analytics', 'CREATE SEQUENCE seq1', 'CREATE VIEW dst AS TABLE sensitive_source',
                     'CREATE TABLE dst LIKE src', 'CREATE TABLE dst CLONE src', "SELECT * FROM IDENTIFIER('raw.a')"):
            with self.subTest(text=text):
                r = Report('snowflake', {'a.sql': text})
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    parse_sql(r, 'a.sql', text, 'snowflake')
                self.assertEqual(stderr.getvalue(), '')
                self.assertTrue(r.finish()['gaps'])


if __name__ == '__main__':
    unittest.main()
