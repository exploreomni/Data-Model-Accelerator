"""Renderer contract checks; local DuckDB evidence is not MotherDuck acceptance."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/data-model-accelerator/scripts'))
from metadata_sql import render_comment, render_tag, read_queries, WAREHOUSES

HAS_SQLGLOT = importlib.util.find_spec('sqlglot') is not None
HAS_DUCKDB = importlib.util.find_spec('duckdb') is not None


def relation(warehouse, kind='table', name='orders'):
    return {'namespace': ['database'] if warehouse == 'clickhouse' else ['database', 'schema'], 'name': name, 'kind': kind}


def tag(warehouse):
    return {'id': 'sensitivity', 'name': ['governance', 'tags', 'sensitivity'] if warehouse == 'snowflake' else ['sensitivity'],
            'value': 'INTERNAL', 'policy_effects': 'none_verified', 'evidence_reference': 'synthetic-policy-preflight'}


class MetadataSQLTests(unittest.TestCase):
    def test_comment_syntax_matches_each_platform(self):
        expected = {
            'snowflake': 'COMMENT ON TABLE "database"."schema"."orders" IS \'Approved\';',
            'databricks': "COMMENT ON TABLE `database`.`schema`.`orders` IS 'Approved';",
            'bigquery': "ALTER TABLE `database`.`schema`.`orders` SET OPTIONS (description = 'Approved');",
            'redshift': 'COMMENT ON TABLE "schema"."orders" IS \'Approved\';',
            'clickhouse': "ALTER TABLE `database`.`orders` MODIFY COMMENT 'Approved';",
            'motherduck': 'COMMENT ON TABLE "database"."schema"."orders" IS \'Approved\';',
        }
        for warehouse, sql in expected.items():
            with self.subTest(warehouse=warehouse):
                self.assertEqual(render_comment(warehouse, relation(warehouse), None, 'Approved'), sql)
                column = render_comment(warehouse, relation(warehouse), 'order_id', 'Approved')
                self.assertIn('COLUMN', column)

    @unittest.skipUnless(HAS_SQLGLOT, 'SQLGlot is installed in the full metadata verification environment')
    def test_payloads_remain_one_literal_and_one_statement_in_each_dialect(self):
        from sqlglot import Dialect, TokenType
        # Independently tokenize syntax; no SQL is sent to remote services.
        values = ["O'Brien", 'C:\\new\\tax', 'line one\nline two\r\ntab\t終端 🕸',
                  "\\'; DROP TABLE victim; -- $$ {{ evil() }}", "' ; SELECT 1; /* quoted */ \\"]
        for warehouse in WAREHOUSES:
            dialect = 'duckdb' if warehouse == 'motherduck' else warehouse
            tokenizer = Dialect.get_or_raise(dialect).tokenizer()
            for value in values:
                with self.subTest(warehouse=warehouse, value=value):
                    sql = render_comment(warehouse, relation(warehouse), 'order_id', value)
                    tokens = tokenizer.tokenize(sql)
                    self.assertEqual(sum(t.token_type == TokenType.SEMICOLON for t in tokens), 1)
                    self.assertEqual([t.text for t in tokens if t.token_type == TokenType.STRING], [value])

    @unittest.skipUnless(HAS_SQLGLOT, 'SQLGlot is installed in the full metadata verification environment')
    def test_identifier_injection_stays_inside_one_quoted_component(self):
        from sqlglot import Dialect, TokenType
        for warehouse in WAREHOUSES:
            dialect = 'duckdb' if warehouse == 'motherduck' else warehouse
            name = 'orders`"; DROP TABLE victim; -- \\結'
            rel = relation(warehouse, name=name)
            if warehouse == 'bigquery':
                with self.assertRaisesRegex(ValueError, 'escaped identifiers'):
                    render_comment(warehouse, rel, 'column', 'safe')
                continue
            sql = render_comment(warehouse, rel, 'column`"; SELECT 2; -- \\名', 'safe')
            tokens = Dialect.get_or_raise(dialect).tokenizer().tokenize(sql)
            self.assertEqual(sum(t.token_type == TokenType.SEMICOLON for t in tokens), 1, warehouse)
            quoted = [t.text for t in tokens if t.token_type == TokenType.IDENTIFIER]
            self.assertIn(name, quoted, warehouse)
            self.assertIn('column`"; SELECT 2; -- \\名', quoted, warehouse)

    def test_platform_view_and_column_boundaries(self):
        for warehouse in WAREHOUSES - {'clickhouse'}:
            rel = relation(warehouse, 'view')
            expected_keyword = 'TABLE' if warehouse == 'databricks' else 'VIEW'
            self.assertIn(expected_keyword, render_comment(warehouse, rel, None, 'View definition'))
            if warehouse != 'motherduck':
                self.assertIn('COLUMN', render_comment(warehouse, rel, 'id', 'View field'))
        for warehouse, kind, column in [('clickhouse', 'view', None), ('motherduck', 'view', 'id'),
                                         ('redshift', 'late_binding_view', 'id'), ('snowflake', 'external', None),
                                         ('bigquery', 'ephemeral', None)]:
            with self.assertRaises(ValueError):
                render_comment(warehouse, relation(warehouse, kind), column, 'Unsupported')

    def test_none_removal_is_exact_or_explicitly_unsupported(self):
        for warehouse in ('databricks', 'bigquery', 'redshift', 'motherduck'):
            self.assertIn('NULL', render_comment(warehouse, relation(warehouse), 'id', None))
        self.assertEqual(render_comment('snowflake', relation('snowflake'), None, None),
                         'ALTER TABLE "database"."schema"."orders" UNSET COMMENT;')
        self.assertIn('MODIFY COLUMN "id" UNSET COMMENT', render_comment('snowflake', relation('snowflake'), 'id', None))
        for warehouse, kind, column in [('snowflake', 'view', 'id'), ('clickhouse', 'table', None), ('clickhouse', 'table', 'id')]:
            with self.assertRaises(ValueError):
                render_comment(warehouse, relation(warehouse, kind), column, None)
        self.assertTrue(render_comment('clickhouse', relation('clickhouse'), None, '').endswith("MODIFY COMMENT '';"))

    def test_bigquery_top_level_view_columns_supported_nested_fields_refused(self):
        sql = render_comment('bigquery', relation('bigquery', 'view'), 'total', 'Approved total')
        self.assertEqual(sql, "ALTER VIEW `database`.`schema`.`orders` ALTER COLUMN `total` SET OPTIONS (description = 'Approved total');")
        for column in (['record', 'field'], 'record.field'):
            with self.assertRaisesRegex(ValueError, 'Nested'):
                render_comment('bigquery', relation('bigquery'), column, 'Not supported')
        with self.assertRaisesRegex(ValueError, '1024'):
            render_comment('bigquery', relation('bigquery'), 'column', 'a' * 1025)
        sql = render_comment('bigquery', relation('bigquery', name='注文'), '購入者 名前', 'Reviewed')
        self.assertIn('ALTER COLUMN `購入者 名前`', sql)

    def test_invalid_types_namespace_and_control_characters_fail_closed(self):
        for warehouse in WAREHOUSES:
            for change in ({'namespace': []}, {'namespace': ['one', 'two', 'three']}, {'name': ''},
                           {'name': 'bad\nname'}, {'name': ' bad'}, {'kind': 'TABLE; DROP DATABASE x'},
                           {'name': 'bad\x00name'}, {'name': '\ud800'}):
                rel = relation(warehouse)
                rel.update(change)
                with self.assertRaises(ValueError):
                    render_comment(warehouse, rel, None, 'safe')
            for value in (False, 3, {}, [], 'bad\x00comment', 'bad\udfff', 'a' * 16001):
                with self.assertRaises(ValueError):
                    render_comment(warehouse, relation(warehouse), None, value)
            with self.assertRaisesRegex(ValueError, 'Nested'):
                render_comment(warehouse, relation(warehouse), ['id'], 'safe')
        with self.assertRaises(ValueError):
            render_comment('guessed', relation('motherduck'), None, 'safe')

    def test_snowflake_tags_use_exact_namespace_and_one_assignment(self):
        rel = relation('snowflake', 'view')
        self.assertEqual(render_tag('snowflake', rel, 'id', tag('snowflake')),
            'ALTER VIEW "database"."schema"."orders" MODIFY COLUMN "id" SET TAG "governance"."tags"."sensitivity" = \'INTERNAL\';')
        candidate = tag('snowflake')
        candidate['name'][0] = 'SNOWFLAKE'
        with self.assertRaisesRegex(ValueError, 'Preview'):
            render_tag('snowflake', rel, None, candidate)

    def test_databricks_tags_do_not_serialize_multiple_columns_or_infer_security(self):
        self.assertEqual(render_tag('databricks', relation('databricks'), 'id', tag('databricks')),
                         "ALTER TABLE `database`.`schema`.`orders` ALTER COLUMN `id` SET TAGS ('sensitivity' = 'INTERNAL');")
        self.assertIn('ALTER VIEW', render_tag('databricks', relation('databricks', 'view'), None, tag('databricks')))
        with self.assertRaisesRegex(ValueError, 'view-column'):
            render_tag('databricks', relation('databricks', 'view'), 'id', tag('databricks'))
        for field, value in [('name', ['not.valid']), ('value', ' untrimmed'), ('value', ''), ('policy_effects', 'unknown'),
                             ('policy_effects', 'policy_bound'), ('evidence_reference', None)]:
            candidate = tag('databricks')
            candidate[field] = value
            with self.assertRaises(ValueError):
                render_tag('databricks', relation('databricks'), None, candidate)
        for warehouse in WAREHOUSES - {'snowflake', 'databricks'}:
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                render_tag(warehouse, relation(warehouse), None, tag('databricks'))

    @unittest.skipUnless(HAS_SQLGLOT, 'SQLGlot is installed in the full metadata verification environment')
    def test_tag_payload_is_a_single_decoded_literal(self):
        from sqlglot import Dialect, TokenType
        for warehouse in ('snowflake', 'databricks'):
            candidate = tag(warehouse)
            candidate['value'] = "O'Brien\\new\n'; DROP TABLE victim; -- 終"
            sql = render_tag(warehouse, relation(warehouse), 'id', candidate)
            tokens = Dialect.get_or_raise(warehouse).tokenizer().tokenize(sql)
            self.assertEqual(sum(t.token_type == TokenType.SEMICOLON for t in tokens), 1)
            self.assertEqual([t.text for t in tokens if t.token_type == TokenType.STRING][-1], candidate['value'])

    @unittest.skipUnless(HAS_SQLGLOT, 'SQLGlot is installed in the full metadata verification environment')
    def test_read_queries_scope_exact_relation_and_all_columns(self):
        from sqlglot import Dialect, TokenType
        for warehouse in WAREHOUSES:
            rel = relation(warehouse, name="O'Brien; --")
            rows = read_queries(warehouse, rel)
            self.assertEqual(len(rows), len({q['id'] for q in rows}))
            self.assertTrue({'relation', 'columns'} <= {q['id'] for q in rows})
            for query in rows:
                self.assertEqual(set(query), {'id', 'sql', 'purpose'})
                self.assertTrue(query['sql'].startswith('SELECT '))
                tokens = Dialect.get_or_raise('duckdb' if warehouse == 'motherduck' else warehouse).tokenizer().tokenize(query['sql'])
                self.assertEqual(sum(t.token_type == TokenType.SEMICOLON for t in tokens), 1)
            columns = next(q['sql'] for q in rows if q['id'] == 'columns')
            self.assertNotIn('LIMIT ', columns)
            self.assertNotIn(' IN (', columns)
            self.assertNotIn('column_name = ', columns.split(' WHERE ')[-1])

    def test_snowflake_both_tag_functions_use_table_domain_even_for_views(self):
        rows = {q['id']: q for q in read_queries('snowflake', relation('snowflake', 'view'))}
        for identity in ('relation_tags', 'column_tags'):
            self.assertTrue(rows[identity]['sql'].endswith(", 'TABLE'));"))
            self.assertIn('"database"."INFORMATION_SCHEMA".', rows[identity]['sql'])
            self.assertIn('SELECT *', rows[identity]['sql'])
        self.assertIn('TAG_REFERENCES_ALL_COLUMNS', rows['column_tags']['sql'])

    def test_databricks_reads_explicit_system_assignments_separately(self):
        rows = {q['id']: q for q in read_queries('databricks', relation('databricks'))}
        self.assertIn('system.information_schema.table_tags', rows['relation_tags']['sql'])
        self.assertIn('system.information_schema.column_tags', rows['column_tags']['sql'])
        self.assertNotIn('tag_name =', rows['column_tags']['sql'])
        self.assertIn('not an ABAC', rows['relation_tags']['purpose'])

    def test_redshift_current_database_preflight_is_separate_and_readback_scoped(self):
        rows = {q['id']: q for q in read_queries('redshift', relation('redshift'))}
        self.assertIn("'database' AS expected_database_name", rows['current_database']['sql'])
        self.assertIn("current_database() = 'database'", rows['columns']['sql'])
        self.assertIn('LEFT JOIN pg_catalog.pg_description', rows['columns']['sql'])
        self.assertNotIn('svv_', rows['columns']['sql'].lower())

    def test_bigquery_relation_without_description_is_not_lost_and_nested_coverage_visible(self):
        rows = {q['id']: q for q in read_queries('bigquery', relation('bigquery'))}
        before_where, after_where = rows['relation']['sql'].split(' WHERE ')
        self.assertIn("o.option_name = 'description'", before_where)
        self.assertNotIn('option_name', after_where)
        self.assertIn('COLUMNS AS c LEFT JOIN', rows['columns']['sql'])
        self.assertIn('observed_description_path', rows['columns']['sql'])
        self.assertIn('field_path != column_name', rows['nested_fields']['sql'])

    def test_rendering_does_not_mutate_bindings_or_tag_evidence(self):
        rel, assignment = relation('snowflake'), tag('snowflake')
        original = copy.deepcopy((rel, assignment))
        render_tag('snowflake', rel, 'id', assignment)
        render_comment('snowflake', rel, None, 'approved')
        read_queries('snowflake', rel)
        self.assertEqual((rel, assignment), original)

    def test_readback_exposes_incarnation_candidates_without_claiming_identity(self):
        expected = {'snowflake': ('CREATED', 'LAST_DDL'), 'databricks': ('created', 'last_altered'),
                    'bigquery': ('creation_time',), 'redshift': ('relation_oid',), 'clickhouse': ('uuid',), 'motherduck': ('table_oid',)}
        for warehouse, fields in expected.items():
            query = next(q for q in read_queries(warehouse, relation(warehouse)) if q['id'] == 'relation')
            for field in fields:
                self.assertIn(field, query['sql'])
            self.assertTrue(any(marker in query['purpose'] for marker in ('qualified', 'qualification', 'unknown incarnation')))
        columns = next(q['sql'] for q in read_queries('redshift', relation('redshift')) if q['id'] == 'columns')
        self.assertIn('JOIN pg_catalog.pg_type', columns)
        self.assertIn('ty.typname AS data_type', columns)


@unittest.skipUnless(HAS_DUCKDB, 'DuckDB is installed in the full metadata verification environment')
class LocalDuckDBReadbackTests(unittest.TestCase):
    def test_literal_roundtrip_full_namespace_and_independent_column_denominator(self):
        import duckdb
        db = duckdb.connect(':memory:')
        self.addCleanup(db.close)
        db.execute("ATTACH ':memory:' AS catalog")
        db.execute('CREATE SCHEMA catalog.gold')
        db.execute('CREATE TABLE catalog.gold."orders" ("order_id" INTEGER, "unplanned_column" VARCHAR)')
        rel = {'namespace': ['catalog', 'gold'], 'name': 'orders', 'kind': 'table'}
        value = "Approved O'Brien\\source\n行; DROP TABLE orders; -- 🕸"
        db.execute(render_comment('motherduck', rel, None, value))
        db.execute(render_comment('motherduck', rel, 'order_id', value))
        queries = {q['id']: q['sql'] for q in read_queries('motherduck', rel)}
        actual = db.execute(queries['relation']).fetchone()
        self.assertEqual(actual[:3], ('catalog', 'gold', 'orders'))
        self.assertIsInstance(actual[3], int)
        self.assertEqual(actual[-1], value)
        columns = db.execute(queries['columns']).fetchall()
        self.assertEqual([c[3] for c in columns], ['order_id', 'unplanned_column'])
        self.assertEqual(columns[0][-1], value)
        self.assertIsNone(columns[1][-1])
        db.execute(render_comment('motherduck', rel, 'order_id', None))
        self.assertIsNone(db.execute(queries['columns']).fetchone()[-1])
        db.execute(render_comment('motherduck', rel, None, None))
        self.assertIsNone(db.execute(queries['relation']).fetchone()[-1])

    def test_quoted_physical_identity_cannot_redirect_or_execute_payload(self):
        import duckdb
        db = duckdb.connect(':memory:')
        self.addCleanup(db.close)
        name = 'x"; DROP TABLE victim; --'
        column = 'id"; SELECT 1; --'
        quote = lambda s: '"' + s.replace('"', '""') + '"'
        db.execute('CREATE TABLE victim (id INTEGER)')
        db.execute('CREATE TABLE ' + quote(name) + ' (' + quote(column) + ' INTEGER)')
        rel = {'namespace': ['memory', 'main'], 'name': name, 'kind': 'table'}
        db.execute(render_comment('motherduck', rel, column, "x'; DROP TABLE victim; --"))
        columns = next(q['sql'] for q in read_queries('motherduck', rel) if q['id'] == 'columns')
        self.assertEqual(db.execute(columns).fetchone()[-1], "x'; DROP TABLE victim; --")
        self.assertEqual(db.execute('SELECT count(*) FROM victim').fetchone()[0], 0)

    def test_view_comment_and_visible_columns_have_distinct_supported_boundaries(self):
        import duckdb
        db = duckdb.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE VIEW example AS SELECT 1 AS id')
        rel = {'namespace': ['memory', 'main'], 'name': 'example', 'kind': 'view'}
        db.execute(render_comment('motherduck', rel, None, 'Approved view'))
        rows = {q['id']: q['sql'] for q in read_queries('motherduck', rel)}
        self.assertEqual(db.execute(rows['relation']).fetchone()[-1], 'Approved view')
        self.assertEqual(db.execute(rows['columns']).fetchone()[3], 'id')
        with self.assertRaisesRegex(ValueError, 'view-column'):
            render_comment('motherduck', rel, 'id', 'Unsupported')


if __name__ == '__main__':
    unittest.main()
