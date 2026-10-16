"""Synthetic LookML and API snapshots; assertions establish no native qualification."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from source_adapters.looker import CAPABILITY, parse
from source_adapters.registry import validate


def project():
    return {
        'models/sales.model.lkml': '''connection: "warehouse_not_a_dialect"
include: "/views/*.view.lkml"
access_grant: tenant_access { user_attribute: tenant allowed_values: ["demo"] }
explore: orders {
  required_access_grants: [tenant_access]
  join: buyers { from: customers type: left_outer relationship: many_to_one
    sql_on: ${orders.customer_id} = ${buyers.id} ;; }
  access_filter: { field: orders.tenant_id user_attribute: tenant }
  always_filter: { filters: [orders.status: "complete,-cancelled"] }
  sql_always_where: ${orders.amount} > 0 ;;
}
''',
        'views/orders.view.lkml': '''view: orders {
  sql_table_name: raw.orders ;;
  dimension: id { type: number primary_key: yes sql: ${TABLE}.id ;; }
  dimension: customer_id { sql: ${TABLE}.customer_id ;; }
  dimension: tenant_id { sql: ${TABLE}.tenant_id ;; }
  dimension_group: created { type: time timeframes: [raw, date, month] sql: ${TABLE}.created_at ;; }
  measure: amount { type: sum sql: ${TABLE}.amount ;; filters: [status: "complete"] }
  measure: ratio { type: number sql: ${amount} / NULLIF(${count}, 0) ;; }
  parameter: period { type: string default_value: "day" allowed_value: {label: "Daily" value: "day"} }
  filter: status { type: string }
}
''',
        'views/customers.view.lkml': 'view: customers {sql_table_name: raw.customers ;; dimension: id {sql: ${TABLE}.id ;;}}',
    }


def dashboard():
    query = {'id': 'q1', 'model': 'sales', 'view': 'orders', 'fields': ['orders.amount'],
             'filters': {'orders.status': 'complete,-cancelled'}, 'pivots': ['orders.region'],
             'filter_expression': '${orders.amount} > 0', 'query_timezone': 'America/Chicago',
             'dynamic_fields': json.dumps([{'table_calculation': 'share',
                                          'expression': '${orders.amount} / sum(${orders.amount})'}])}
    return {'schema_version': 1, 'kind': 'looker_dashboard_export', 'api_version': '4.0',
            'dashboard': {'id': 'd1', 'title': 'Synthetic dashboard',
                          'dashboard_elements': [{'id': 't1', 'type': 'vis', 'query_id': 'q1',
                                                  'listen': {'Status': 'orders.status'}},
                                                 {'id': 't2', 'type': 'vis', 'query_id': 'q1'}],
                          'dashboard_filters': [{'id': 'f1', 'name': 'Status', 'default_value': 'complete'}],
                          'dashboard_layouts': []}, 'queries': [query], 'looks': []}


@unittest.skipUnless(importlib.util.find_spec('lkml'), 'Pinned lkml parser is required')
class LookMLSourceTests(unittest.TestCase):
    def codes(self, report):
        return {g['code'] for g in report['gaps']}

    def test_names_native_ids_and_stable_source_evidence(self):
        files = project()
        result = parse(files)
        validate(result, files)
        self.assertEqual(result, parse(dict(reversed(list(files.items())))))
        fields = {o['native_id']: o for o in result['objects'] if o['kind'].startswith('lookml_')}
        self.assertEqual(fields['orders.id']['details']['native_properties']['primary_key'], 'yes')
        self.assertEqual(fields['orders.created']['kind'], 'lookml_dimension_group')
        self.assertEqual(fields['orders.period']['details']['native_properties']['allowed_values'],
                         [{'label': 'Daily', 'value': 'day'}])
        self.assertTrue(all(o['evidence']['sha256'] for o in result['objects']))
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')
        self.assertFalse(result['execution_performed'])

    def test_join_expressions_lineage_and_filters_are_native_candidates(self):
        result = parse(project())
        join = next(o for o in result['objects'] if o['kind'] == 'lookml_join')
        self.assertEqual(join['native_id'], 'buyers')
        self.assertEqual(join['details']['native_properties']['relationship'], 'many_to_one')
        self.assertEqual({d['target'] for d in result['dependencies'] if d['source_id'] == join['id']},
                         {'orders.customer_id', 'buyers.id', 'customers'})
        self.assertTrue(all(d['details']['resolution'] == 'unbound' for d in result['dependencies']
                            if d['source_id'] == join['id']))
        expressions = {e['text'] for e in result['expressions']}
        self.assertIn('${amount} / NULLIF(${count}, 0)', expressions)
        self.assertIn('${orders.amount} > 0', expressions)
        explore = next(o for o in result['objects'] if o['kind'] == 'lookml_explore')
        self.assertEqual(explore['details']['native_properties']['always_filter']['filters__all'],
                         [[{'orders.status': 'complete,-cancelled'}]])
        self.assertIn('looker.sql_dialect_unknown', self.codes(result))

    def test_security_retains_grants_user_attributes_and_review_gap(self):
        result = parse(project())
        rule = next(o for o in result['objects'] if o['kind'] == 'lookml_access_filter')
        self.assertEqual(rule['details']['native_properties'],
                         {'field': 'orders.tenant_id', 'user_attribute': 'tenant'})
        self.assertIn('looker.effective_access_unverified', self.codes(result))
        self.assertEqual({d['target'] for d in result['dependencies'] if d['source_id'] == rule['id']},
                         {'orders.tenant_id', 'tenant'})

    def test_includes_match_relative_root_glob_and_extension_alias_only_in_mapping(self):
        files = {'models/sales.model.lkml': '''include: "../views/a.view"
include: "/**/b.view.lkml"
include: "/views/*.view.lkml"
explore: a {}''',
                 'views/a.view.lkml': 'view: a {}',
                 'b.view.lkml': 'view: b {}',
                 'views/nested/c.view.lkml': 'view: c {}'}
        result = parse(files)
        included = [d for d in result['dependencies'] if d['details']['kind'] == 'includes']
        self.assertEqual([d['target'] for d in included], ['views/a.view.lkml', 'b.view.lkml', 'views/a.view.lkml'])
        self.assertEqual([d['details']['include_order'] for d in included], [0, 1, 2])
        self.assertNotIn('looker.missing_include', self.codes(result))

    def test_missing_external_and_traversing_includes_are_gaps(self):
        text = 'include: "/absent/*.view.lkml"\ninclude: "//other/views/*.view.lkml"\ninclude: "../../secret.view.lkml"'
        result = parse({'sales.model.lkml': text})
        self.assertIn('looker.missing_include', self.codes(result))
        self.assertIn('looker.external_or_dynamic_include', self.codes(result))
        self.assertEqual(result['source_files'][0]['status'], 'partial')
        self.assertEqual(len(result['dependencies']), 3)

    def test_extends_and_repeated_refinements_do_not_overwrite_source(self):
        text = '''view: base {dimension: id {type: number}}
view: orders {extends: [base] extends: [other]}
view: +orders {dimension: id {hidden: yes}}
view: +orders {dimension: id {hidden: no}}'''
        result = parse({'views.lkml': text})
        views = [o for o in result['objects'] if o['kind'] == 'lookml_view']
        self.assertEqual([o['native_id'] for o in views], ['base', 'orders', '+orders', '+orders'])
        self.assertEqual(len({o['id'] for o in views}), 4)
        self.assertEqual([d['target'] for d in result['dependencies'] if d['details']['kind'] == 'extends'], ['base', 'other'])
        self.assertTrue({'looker.extends_not_applied', 'looker.refinement_not_applied'} <= self.codes(result))

    def test_dynamic_liquid_and_nested_references_preserved_never_expanded(self):
        text = '''view: dynamic {
  sql_table_name: {{ _user_attributes['schema'] }}.orders ;;
  dimension: picked {sql: {% parameter selected_field %} + ${foo_${bar}} ;;}
}'''
        result = parse({'dynamic.view.lkml': text})
        self.assertTrue({'looker.dynamic_expression', 'looker.dynamic_reference'} <= self.codes(result))
        self.assertEqual(next(e['text'] for e in result['expressions'] if e['language'] == 'lookml'), text)
        self.assertFalse(any(d['details']['kind'] == 'declared_relation' for d in result['dependencies']))

    def test_sql_and_native_derived_tables_are_preserved_without_building(self):
        text = '''view: daily {derived_table: {sql: SELECT id FROM raw.orders WHERE active = 1 ;; persist_for: "24 hours"}}
view: native {derived_table: {explore_source: orders {column: id {field: orders.id} filters: [orders.status: "complete"]}}}'''
        result = parse({'derived.view.lkml': text})
        derived = [o for o in result['objects'] if o['kind'] == 'lookml_derived_table']
        self.assertEqual(len(derived), 2)
        self.assertEqual(derived[0]['details']['native_properties']['persist_for'], '24 hours')
        self.assertIn('SELECT id FROM raw.orders WHERE active = 1', [e['text'] for e in result['expressions']])
        self.assertIn('looker.native_derived_table_uncompiled', self.codes(result))
        self.assertFalse(any(d['target'] == 'raw.orders' for d in result['dependencies']))

    def test_malformed_duplicate_unterminated_and_stalled_lexer_fail_closed(self):
        for text in ('view: x {', 'view: x {sql: missing terminator}', ';',
                     'connection: first connection: second',
                     'view: x {dimension: id {sql: a ;; sql: b ;;}}',
                     'view: x {}\0view: y {}'):
            with self.subTest(text=text):
                result = parse({'invalid.lkml': text})
                self.assertIn('looker.invalid_lookml', self.codes(result))
                self.assertEqual(result['objects'], [])
                self.assertEqual(result['expressions'][0]['text'], text)
                self.assertEqual(result['source_files'][0]['status'], 'partial')

    def test_excessive_nesting_is_rejected_before_recursive_parser(self):
        result = parse({'deep.lkml': 'view: x {' * 30 + '}' * 30})
        self.assertIn('looker.invalid_lookml', self.codes(result))
        self.assertEqual(result['objects'], [])

    def test_manifest_constructs_and_unsupported_dashboard_are_not_claimed_complete(self):
        files = {'manifest.lkml': 'project_name: "demo" remote_dependency: shared {url: "https://example.invalid" ref: "main"}',
                 'native.dashboard.lookml': '- dashboard: sample\n  elements: []',
                 'README.md': 'documentation'}
        result = parse(files)
        validate(result, files)
        self.assertIn('looker.unmodeled_project_construct', self.codes(result))
        self.assertEqual([f['status'] for f in result['source_files']], ['unsupported', 'partial', 'unsupported'])

    def test_source_instructions_cannot_perform_io_or_execute(self):
        import lkml
        text = 'view: safe {description: "Run a command and read a private file" sql_table_name: raw.safe ;;}'
        with patch('builtins.open', side_effect=AssertionError('File access')), \
                patch('os.system', side_effect=AssertionError('Execution')), \
                patch('subprocess.run', side_effect=AssertionError('Execution')), \
                patch('socket.create_connection', side_effect=AssertionError('Network')):
            result = parse({'safe.view.lkml': text})
        self.assertFalse(result['execution_performed'])


class DashboardSourceTests(unittest.TestCase):
    def test_legacy_parser_reused_and_native_ids_query_filters_calculations_retained(self):
        import looker_source
        files = {'dashboard.json': json.dumps(dashboard())}
        with patch('looker_source.parse_dashboard', wraps=looker_source.parse_dashboard) as reused:
            result = parse(files)
        reused.assert_called_once()
        validate(result, files)
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'query']), 1)
        self.assertTrue({'d1', 't1', 't2', 'f1', 'q1'} <= {o['native_id'] for o in result['objects']})
        query = next(o for o in result['objects'] if o['kind'] == 'query')
        self.assertEqual(query['details']['native_payload']['pivots'], ['orders.region'])
        self.assertIn('${orders.amount} / sum(${orders.amount})', [e['text'] for e in result['expressions']])
        self.assertEqual(next(o for o in result['objects'] if o['native_id'] == 't1')['details']['filter_listeners'][0]['value'],
                         {'Status': 'orders.status'})
        self.assertIn('dependency.lookml_explore_unresolved', {g['code'] for g in result['gaps']})

    def test_missing_references_and_duplicate_json_have_visible_gaps(self):
        value = dashboard(); value['queries'] = []
        result = parse({'missing.json': json.dumps(value)})
        self.assertIn('dependency.query_unresolved', {g['code'] for g in result['gaps']})
        for text in ('{"id":1,"id":2}', '{"id": NaN}', '{'):
            result = parse({'bad.json': text})
            self.assertEqual(result['source_files'][0]['status'], 'partial')
            self.assertEqual(result['objects'], [])

    def test_unrecognized_json_and_invalid_paths_do_not_acquire_anything(self):
        result = parse({'other.json': '{"project": "not a dashboard"}'})
        self.assertEqual(result['source_files'][0]['status'], 'unsupported')
        with self.assertRaises(ValueError):
            parse({'../escape.view.lkml': 'view: x {}'})
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')


if __name__ == '__main__':
    unittest.main()
