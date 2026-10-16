"""Synthetic provenance cases; no SQL execution or native acceptance claims."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import authoring_provenance as provenance
from authoring_evidence import summarize

SQLGLOT = importlib.util.find_spec('sqlglot') is not None
YAML = importlib.util.find_spec('yaml') is not None


class ProvenanceFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        self.candidate = self.root / 'candidate'; self.candidate.mkdir()

    def write(self, root, path, text):
        target = root / path; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def contract(self, path, columns=None):
        return {'schema_version': 1, 'kind': 'authoring_contract', 'mode': 'provisional',
            'bindings': {'source_sha256': 'a'*64, 'design_sha256': 'b'*64, 'catalogue_sha256': None},
            'models': [{'id': 'orders', 'path': path, 'depends_on': None, 'columns': columns}],
            'assumptions': [], 'provenance': []}

    def scan(self, root, path):
        return provenance.scan_literals(root, [path], 'snowflake')

    def evidence(self, occurrence):
        return {'path': occurrence['path'], 'sha256': occurrence['file_sha256'],
                'span': occurrence['span'], 'field': occurrence['field'],
                'expression_sha256': occurrence['expression_sha256']}

    def check(self, contract, path):
        return provenance.check_provenance(self.candidate, self.source, contract, [path], 'snowflake')


class CSVProvenanceTests(ProvenanceFixture):
    def test_preserved_seed_cells_require_the_same_row_context(self):
        value = 'id,label\n1,Active\n2,Inactive\n'
        self.write(self.source, 'seed.csv', value); self.write(self.candidate, 'seed.csv', value)
        contract = self.contract('seed.csv')
        actual = self.scan(self.candidate, 'seed.csv')['occurrences']
        source = self.scan(self.source, 'seed.csv')['occurrences']
        contract['provenance'] = [{'occurrence_id': a['id'], 'classification': 'preserved', 'source': self.evidence(b)}
                                  for a, b in zip(actual, source)]
        findings, hashes = self.check(contract, 'seed.csv')
        self.assertEqual(summarize(findings)['status'], 'passed')
        self.assertEqual(hashes, {'seed.csv': source[0]['file_sha256']})
        # Same label exists, but for another key. A source-wide string search
        # would falsely accept this modified population.
        self.write(self.candidate, 'seed.csv', 'id,label\n9,Active\n')
        occurrence = self.scan(self.candidate, 'seed.csv')['occurrences'][1]
        contract['provenance'] = [{'occurrence_id': occurrence['id'], 'classification': 'preserved',
                                   'source': self.evidence(source[1])}]
        self.assertIn('failed', [f['status'] for f in self.check(contract, 'seed.csv')[0]])

    def test_guessed_redacted_seed_is_not_grounded(self):
        self.write(self.source, 'seed.csv', 'id,label\n1,[REDACTED]\n')
        self.write(self.candidate, 'seed.csv', 'id,label\n1,Private Business Label\n')
        actual = self.scan(self.candidate, 'seed.csv')['occurrences'][1]
        source = self.scan(self.source, 'seed.csv')['occurrences'][1]
        contract = self.contract('seed.csv')
        contract['provenance'] = [{'occurrence_id': actual['id'], 'classification': 'preserved', 'source': self.evidence(source)}]
        findings, _ = self.check(contract, 'seed.csv')
        self.assertIn('failed', [f['status'] for f in findings])
        self.assertNotIn('Private Business Label', json.dumps(findings))
        contract['provenance'][0] = {'occurrence_id': actual['id'], 'classification': 'proposed'}
        self.assertEqual(summarize(self.check(contract, 'seed.csv')[0])['status'], 'not_run')

    def test_csv_quoted_multiline_and_repeated_cells_have_exact_spans(self):
        value = 'id,label\r\n1,"A, B"\r\n2,"line\none"\r\n3,"A, B"\r\n'
        self.write(self.candidate, 'seed.csv', value)
        scanned = self.scan(self.candidate, 'seed.csv')
        self.assertEqual(len(scanned['occurrences']), 6)
        self.assertEqual(len({x['id'] for x in scanned['occurrences']}), 6)
        self.assertEqual(value[scanned['occurrences'][1]['span']['start']:scanned['occurrences'][1]['span']['end']], '"A, B"')
        self.assertEqual(scanned['occurrences'][1]['value_sha256'], scanned['occurrences'][5]['value_sha256'])
        self.assertNotEqual(scanned['occurrences'][1]['expression_sha256'], scanned['occurrences'][5]['expression_sha256'])

    def test_bad_csv_and_unavailable_format_keep_file_denominators(self):
        self.write(self.candidate, 'seed.csv', 'id,label\n1,one,extra\n')
        self.write(self.candidate, 'model.py', 'print("not executed")')
        result = provenance.scan_literals(self.candidate, ['seed.csv', 'model.py'], 'snowflake')
        self.assertEqual(len(result['files']), 2)
        self.assertEqual([x['status'] for x in result['findings']], ['unsupported', 'unsupported'])

    def test_missing_provenance_and_technical_label_cannot_pass_seed(self):
        self.write(self.candidate, 'seed.csv', 'id,label\n1,Active\n')
        contract = self.contract('seed.csv')
        self.assertEqual(summarize(self.check(contract, 'seed.csv')[0])['status'], 'not_run')
        occurrence = self.scan(self.candidate, 'seed.csv')['occurrences'][1]
        contract['provenance'] = [{'occurrence_id': occurrence['id'], 'classification': 'technical'}]
        self.assertIn('technical_classification_contradicted', [f['code'] for f in self.check(contract, 'seed.csv')[0]])

    def test_decision_reference_is_not_authenticated_provenance(self):
        self.write(self.candidate, 'seed.csv', 'label\nNew Label\n')
        occurrence = self.scan(self.candidate, 'seed.csv')['occurrences'][0]
        contract = self.contract('seed.csv')
        contract['provenance'] = [{'occurrence_id': occurrence['id'], 'classification': 'proposed',
            'decision': {'reference': 'review/decision-1', 'status': 'host_reported_reviewed'}}]
        findings, _ = self.check(contract, 'seed.csv')
        self.assertEqual(summarize(findings)['status'], 'not_run')
        self.assertIn('decision_reference_host_reported', [f['code'] for f in findings])
        contract['provenance'][0]['decision']['status'] = 'authenticated'
        self.assertEqual(summarize(self.check(contract, 'seed.csv')[0])['status'], 'failed')

    def test_paths_symlinks_and_bounds_do_not_read_outside_root(self):
        self.write(self.source, 'seed.csv', 'id\n1\n')
        (self.candidate / 'link.csv').symlink_to(self.source / 'seed.csv')
        with self.assertRaises(ValueError): self.scan(self.candidate, '../source/seed.csv')
        result = self.scan(self.candidate, 'link.csv')
        self.assertEqual(result['files'], {})
        self.assertEqual(result['findings'][0]['status'], 'unsupported')
        self.write(self.candidate, 'seed.csv', 'id\n1\n')
        with patch.object(provenance, 'MAX_BYTES', 2):
            self.assertEqual(self.scan(self.candidate, 'seed.csv')['findings'][0]['status'], 'unsupported')

    def test_stale_and_escaping_source_evidence_fail(self):
        self.write(self.source, 'seed.csv', 'id\n1\n'); self.write(self.candidate, 'seed.csv', 'id\n1\n')
        a = self.scan(self.candidate, 'seed.csv')['occurrences'][0]
        b = self.scan(self.source, 'seed.csv')['occurrences'][0]
        for change in ('hash', 'span', 'escape'):
            contract = self.contract('seed.csv')
            evidence = self.evidence(b)
            if change == 'hash': evidence['sha256'] = '0'*64
            elif change == 'span': evidence['span'] = {'start': 0, 'end': 1}
            else: evidence['path'] = '../candidate/seed.csv'
            contract['provenance'] = [{'occurrence_id': a['id'], 'classification': 'preserved', 'source': evidence}]
            with self.subTest(change=change):
                self.assertEqual(summarize(self.check(contract, 'seed.csv')[0])['status'], 'failed')


@unittest.skipUnless(SQLGLOT, 'SQLGlot is optional; SQL provenance coverage unavailable')
class SQLProvenanceTests(ProvenanceFixture):
    def test_inventory_covers_string_number_date_boolean_null_without_echo(self):
        sql = "SELECT 'private-value' AS status, -17 AS amount, DATE '2024-01-01' AS d, TRUE AS b, NULL AS n"
        self.write(self.candidate, 'model.sql', sql)
        result = self.scan(self.candidate, 'model.sql')
        self.assertEqual({r['kind'] for r in result['occurrences']}, {'string', 'number', 'date', 'boolean', 'null'})
        self.assertTrue(all(r['supported'] and r['reachable'] for r in result['occurrences']))
        self.assertNotIn('private-value', json.dumps(result))
        self.assertNotIn('2024-01-01', json.dumps(result))

    def test_count_one_and_date_granularity_only_are_technical(self):
        self.write(self.candidate, 'model.sql', "SELECT COUNT(1) AS n, DATE_TRUNC('month', ordered_at) AS m FROM orders")
        self.assertEqual(summarize(self.check(self.contract('model.sql'), 'model.sql')[0])['status'], 'passed')
        self.write(self.candidate, 'model.sql', "SELECT 1 AS customer_type, 'month' AS status, COUNT(2) AS n FROM orders")
        scanned = self.scan(self.candidate, 'model.sql')
        self.assertFalse(any(r['technical'] for r in scanned['occurrences']))
        contract = self.contract('model.sql')
        contract['provenance'] = [{'occurrence_id': r['id'], 'classification': 'technical'} for r in scanned['occurrences']]
        self.assertEqual(sum(f['status'] == 'failed' for f in self.check(contract, 'model.sql')[0]), 3)

    def test_preserved_expression_with_same_field_is_verified(self):
        sql = "SELECT CASE WHEN code = 'A' THEN 'Active' ELSE 'Other' END AS status FROM orders"
        self.write(self.source, 'original.sql', sql); self.write(self.candidate, 'model.sql', sql)
        actual = self.scan(self.candidate, 'model.sql')['occurrences']; sources = self.scan(self.source, 'original.sql')['occurrences']
        contract = self.contract('model.sql')
        contract['provenance'] = [{'occurrence_id': a['id'], 'classification': 'preserved', 'source': self.evidence(b)}
                                  for a, b in zip(actual, sources)]
        self.assertEqual(summarize(self.check(contract, 'model.sql')[0])['status'], 'passed')

    def test_same_literal_wrong_field_or_context_is_rejected(self):
        self.write(self.source, 'original.sql', "SELECT 'Active' AS status, 'Active' AS region FROM orders")
        self.write(self.candidate, 'model.sql', "SELECT 'Active' AS status FROM orders")
        actual = self.scan(self.candidate, 'model.sql')['occurrences'][0]
        sources = self.scan(self.source, 'original.sql')['occurrences']
        contract = self.contract('model.sql')
        contract['provenance'] = [{'occurrence_id': actual['id'], 'classification': 'preserved', 'source': self.evidence(sources[1])}]
        self.assertEqual(summarize(self.check(contract, 'model.sql')[0])['status'], 'failed')
        self.write(self.candidate, 'model.sql', "SELECT CASE WHEN code = 'B' THEN 'Active' END AS status FROM orders")
        actual = self.scan(self.candidate, 'model.sql')['occurrences'][1]
        contract['provenance'] = [{'occurrence_id': actual['id'], 'classification': 'preserved', 'source': self.evidence(sources[0])}]
        self.assertIn('failed', [f['status'] for f in self.check(contract, 'model.sql')[0]])

    def test_dead_cte_unused_projection_and_comment_cannot_supply_evidence(self):
        self.write(self.source, 'original.sql', "WITH dead AS (SELECT 'Active' AS status), live AS (SELECT 'Active' AS status, id FROM orders) SELECT id FROM live -- 'Active'\n")
        sources = self.scan(self.source, 'original.sql')['occurrences']
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(not r['reachable'] for r in sources))
        self.write(self.candidate, 'model.sql', "SELECT 'Active' AS status FROM orders")
        actual = self.scan(self.candidate, 'model.sql')['occurrences'][0]
        for source in sources:
            contract = self.contract('model.sql')
            contract['provenance'] = [{'occurrence_id': actual['id'], 'classification': 'preserved', 'source': self.evidence(source)}]
            self.assertEqual(summarize(self.check(contract, 'model.sql')[0])['status'], 'failed')

    def test_live_cte_projection_is_preservable(self):
        self.write(self.source, 'original.sql', "WITH live AS (SELECT 'Active' AS status FROM orders) SELECT status FROM live")
        self.write(self.candidate, 'model.sql', "SELECT 'Active' AS status FROM orders")
        actual = self.scan(self.candidate, 'model.sql')['occurrences'][0]
        source = self.scan(self.source, 'original.sql')['occurrences'][0]
        self.assertTrue(source['reachable'])
        contract = self.contract('model.sql')
        contract['provenance'] = [{'occurrence_id': actual['id'], 'classification': 'preserved', 'source': self.evidence(source)}]
        self.assertEqual(summarize(self.check(contract, 'model.sql')[0])['status'], 'passed')

    def test_dbt_static_calls_mask_without_executing_and_dynamic_is_unsupported(self):
        text = "SELECT 'A' AS status FROM {{ ref('orders') }} JOIN {{ source('raw', 'users') }} u ON u.id = d.id"
        masked, calls, gaps = provenance.mask_static_dbt_sql(text)
        self.assertEqual(len(masked), len(text)); self.assertEqual(gaps, [])
        self.assertEqual([(x['name'], x['arguments']) for x in calls], [('ref', ['orders']), ('source', ['raw', 'users'])])
        self.write(self.candidate, 'model.sql', "SELECT 'A' AS status FROM {{ ref('orders') }}")
        self.assertEqual(self.scan(self.candidate, 'model.sql')['findings'][0]['status'], 'passed')
        for sql in ("SELECT {{ custom_macro() }} AS x, 'A' AS status", "{% if flag %}SELECT 'A'{% endif %}", "SELECT '{{ ref(\"orders\") }}' AS x"):
            self.write(self.candidate, 'model.sql', sql)
            result = self.scan(self.candidate, 'model.sql')
            self.assertEqual(result['findings'][0]['status'], 'unsupported')

    def test_unknown_dialect_invalid_sql_and_ambiguous_scope_are_not_passes(self):
        for text, dialect in [("SELECT 'A' AS status", None), ('SELECT FROM', 'snowflake'),
                              ("SELECT CASE WHEN id = 1 THEN 'A' END AS status FROM a JOIN b ON a.id=b.id", 'snowflake')]:
            self.write(self.candidate, 'model.sql', text)
            result = provenance.scan_literals(self.candidate, ['model.sql'], dialect)
            self.assertIn('unsupported', [f['status'] for f in result['findings']])

    def test_static_ref_placeholders_cannot_shadow_native_relations(self):
        import sqlglot
        from sqlglot import exp
        text = ('WITH D0 AS (SELECT id FROM raw.d1) SELECT a.id FROM '
                '{{ ref("customers") }} a JOIN D0 b ON a.id=b.id '
                'JOIN raw."d2" c ON a.id=c.id JOIN {{ source("raw", "users") }} u ON a.id=u.id')
        masked, calls, gaps = provenance.mask_static_dbt_sql(text)
        self.assertFalse(gaps); self.assertEqual(len(masked), len(text))
        identifiers = {call['identifier'] for call in calls}
        self.assertEqual(len(identifiers), 2)
        self.assertFalse(identifiers & {'d0', 'd1', 'd2'})
        tables = list(sqlglot.parse_one(masked, read='snowflake').find_all(exp.Table))
        native = {table.name for table in tables if table.name not in identifiers}
        self.assertEqual(native, {'D0', 'd1', 'd2'})

    def test_derived_contract_alone_does_not_launder_invented_business_label(self):
        self.write(self.candidate, 'model.sql', "SELECT 'Invented Label' AS status")
        occurrence = self.scan(self.candidate, 'model.sql')['occurrences'][0]
        contract = self.contract('model.sql', ['status']); contract['mode'] = 'reviewed_candidate'
        contract['models'][0]['expressions'] = {'status': "'Invented Label'"}
        contract['provenance'] = [{'occurrence_id': occurrence['id'], 'classification': 'derived',
                                   'expression_sha256': occurrence['expression_sha256']}]
        self.assertEqual(summarize(self.check(contract, 'model.sql')[0])['status'], 'not_run')
        contract['models'][0]['expressions']['status'] = "'Different Label'"
        self.assertEqual(summarize(self.check(contract, 'model.sql')[0])['status'], 'failed')

    def test_duplicate_unknown_and_stale_occurrence_ids_fail(self):
        self.write(self.candidate, 'model.sql', "SELECT 'A' AS status")
        occurrence = self.scan(self.candidate, 'model.sql')['occurrences'][0]
        contract = self.contract('model.sql')
        row = {'occurrence_id': occurrence['id'], 'classification': 'proposed'}
        contract['provenance'] = [row, copy.deepcopy(row)]
        self.assertEqual(summarize(self.check(contract, 'model.sql')[0])['status'], 'failed')
        contract['provenance'] = [row]
        self.write(self.candidate, 'model.sql', "SELECT 'B' AS status")
        self.assertEqual(summarize(self.check(contract, 'model.sql')[0])['status'], 'failed')


@unittest.skipUnless(YAML and SQLGLOT, 'PyYAML and SQLGlot are optional; Omni provenance coverage unavailable')
class OmniProvenanceTests(ProvenanceFixture):
    def test_sql_and_filter_values_have_hash_only_exact_scalar_locations(self):
        text = "dimensions:\n  status:\n    sql: CASE WHEN ${code} = 'A' THEN 'Active' ELSE 'Other' END\nmeasures:\n  active_orders:\n    sql: COUNT(1)\n    filters:\n      status:\n        is: [Active, Pending]\n      amount:\n        greater_than: 100\n"
        self.write(self.source, 'orders.view', text); self.write(self.candidate, 'orders.view', text)
        actual = self.scan(self.candidate, 'orders.view')['occurrences']
        source = self.scan(self.source, 'orders.view')['occurrences']
        self.assertEqual(len(actual), 7)
        self.assertTrue(all(r['supported'] for r in actual))
        self.assertEqual(sum(r['technical'] for r in actual), 1)
        self.assertNotIn('Active', json.dumps(self.scan(self.candidate, 'orders.view')))
        sql_row = actual[0]
        scalar = text[sql_row['span']['start']:sql_row['span']['end']]
        self.assertEqual(scalar[sql_row['span']['value_start']:sql_row['span']['value_end']], "'A'")
        contract = self.contract('orders.view')
        contract['provenance'] = [{'occurrence_id': a['id'], 'classification': 'preserved', 'source': self.evidence(b)}
                                  for a, b in zip(actual, source) if not a['technical']]
        self.assertEqual(summarize(self.check(contract, 'orders.view')[0])['status'], 'passed')

    def test_same_filter_value_in_unrelated_field_cannot_substantiate(self):
        original = 'measures:\n  orders:\n    filters:\n      region:\n        is: Active\n'
        target = original.replace('region:', 'status:')
        self.write(self.source, 'orders.view.yaml', original)
        self.write(self.candidate, 'orders.view.yaml', target)
        actual = self.scan(self.candidate, 'orders.view.yaml')['occurrences'][0]
        source = self.scan(self.source, 'orders.view.yaml')['occurrences'][0]
        contract = self.contract('orders.view.yaml')
        contract['provenance'] = [{'occurrence_id': actual['id'], 'classification': 'preserved', 'source': self.evidence(source)}]
        self.assertEqual(summarize(self.check(contract, 'orders.view.yaml')[0])['status'], 'failed')

    def test_unsupported_filter_and_dynamic_sql_remain_in_denominator(self):
        text = 'measures:\n  orders:\n    sql: "{{ arbitrary_macro() }}"\n    filters:\n      status:\n        native_custom_operator: PrivateValue\n'
        self.write(self.candidate, 'orders.view', text)
        result = self.scan(self.candidate, 'orders.view')
        self.assertIn('unsupported', [f['status'] for f in result['findings']])
        self.assertEqual(len(result['occurrences']), 1)
        self.assertFalse(result['occurrences'][0]['supported'])
        self.assertEqual(summarize(self.check(self.contract('orders.view'), 'orders.view')[0])['status'], 'unsupported')
        self.assertNotIn('PrivateValue', json.dumps(result))

    def test_yaml_unsafe_tags_duplicates_and_aliases_are_never_evaluated(self):
        for text in ('dimensions: &x {status: {sql: "1"}}\ncopy: *x',
                     'dimensions: {}\ndimensions: {}',
                     'value: !!python/object/apply:os.system ["echo never"]'):
            self.write(self.candidate, 'orders.view', text)
            with self.subTest(text=text):
                result = self.scan(self.candidate, 'orders.view')
                self.assertEqual(result['findings'][0]['status'], 'unsupported')


if __name__ == '__main__': unittest.main()
