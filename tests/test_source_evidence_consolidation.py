"""Synthetic lossless source-evidence regressions; no native semantics asserted."""
import copy
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from extract_specialist_task import to_specialist
from source_adapters.base import Report, sha
from source_adapters.registry import validate
from source_adapters.looker import parse as parse_looker
from source_adapters.dbt import parse as parse_dbt


def evidence(text='select ' + 'long_expression_' * 100, path='models/orders.sql'):
    report = Report('dbt', {path: text})
    owner = report.object(path, '$model', 'model', 'orders', native_id='model.synthetic.' + 'id_' * 120)
    report.expression(path, '$model.raw_code', 'dbt:sql+jinja', text, owner,
                      filters={'status': ['complete', 'pending']}, population='active customers only',
                      currency_time={'currency': 'EUR', 'fx_basis': 'first day of month',
                                     'timezone': 'America/Chicago'}, future_metadata={'retain': [1, None, False]})
    report.cover(path)
    return report.finish()


def merge(reports, **kwargs):
    return importlib.import_module('source_adapters.consolidation').merge_reports(reports, **kwargs)


class LosslessEvidenceTests(unittest.TestCase):
    def test_occurrence_survives_content_change_and_keeps_existing_content_identity(self):
        first, changed = evidence(), evidence('select changed')
        a, b = first['expressions'][0], changed['expressions'][0]
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(a['occurrence_id'], b['occurrence_id'])
        self.assertEqual(a['content_sha256'], sha(a['text']))
        self.assertNotEqual(a['evidence']['sha256'], b['evidence']['sha256'])

    def test_specialist_bridge_keeps_all_expression_details(self):
        report = evidence()
        result = to_specialist(report, 'task', 'snapshot', {'models/orders.sql': 'asset'})
        self.assertEqual(result['rules'][0]['source_details'], report['expressions'][0]['details'])
        self.assertEqual(result['rules'][0]['source_occurrence_id'], report['expressions'][0]['occurrence_id'])
        self.assertEqual(result['rules'][0]['expression'], report['expressions'][0]['text'])
        self.assertEqual(result['objects'][0]['native_id'], report['objects'][0]['native_id'])

    def test_merge_is_lossless_idempotent_order_independent_and_detached(self):
        a, b = evidence(), evidence('select other', 'models/other.sql')
        a['future_contract_metadata'] = {'keep': 'population, filter, currency and time'}
        bundle = merge([b, a, copy.deepcopy(a)])
        self.assertEqual(bundle, merge([a, b]))
        self.assertEqual(len(bundle['expressions']), 2)
        self.assertIn(a, bundle['source_contracts'])
        self.assertEqual(next(x for x in bundle['expressions'] if x['id'] == a['expressions'][0]['id']),
                         a['expressions'][0])
        bundle['expressions'][0]['details']['filters']['status'].append('mutated')
        self.assertEqual(a['expressions'][0]['details']['filters']['status'], ['complete', 'pending'])

    def test_merge_rejects_changed_source_and_duplicate_identity_conflicts(self):
        a = evidence()
        with self.assertRaisesRegex(ValueError, 'source.conflicting_file'):
            merge([a, evidence('select revision')])
        altered = copy.deepcopy(a)
        altered['expressions'][0]['details']['currency_time']['currency'] = 'USD'
        with self.assertRaisesRegex(ValueError, 'source.conflicting_record'):
            merge([a, altered])

    def test_explicit_file_denominator_includes_missing_scope_without_parity_claim(self):
        report = evidence()
        expected = [{'source': 'dbt', 'path': 'models/orders.sql', 'sha256': report['source_files'][0]['sha256']},
                    {'source': 'dbt', 'path': 'models/missing.sql', 'sha256': sha('select missing')}]
        bundle = merge([report], expected_files=expected)
        coverage = bundle['coverage_summary']
        self.assertEqual(coverage['unit'], 'supplied_source_files')
        self.assertEqual(coverage['expected'], 2)
        self.assertEqual(coverage['observed'], 1)
        self.assertEqual(coverage['missing'], 1)
        self.assertEqual(bundle['export_completeness'], 'not_established')
        self.assertEqual(bundle['semantic_mapping'], 'not_assessed')

    def test_old_schema_one_report_remains_accepted(self):
        report = evidence()
        for category in ('objects', 'expressions', 'dependencies', 'gaps'):
            for row in report[category]:
                row.pop('occurrence_id', None)
                row.pop('content_sha256', None)
        report.pop('coverage_summary', None)
        validate(report, {'models/orders.sql': report['expressions'][0]['text']})
        self.assertEqual(merge([report])['source_contracts'], [report])

    def test_repeated_reference_occurrences_are_not_collapsed(self):
        report = Report('looker', {'orders.view.lkml': '${amount} + ${amount}'})
        owner = report.object('orders.view.lkml', '$measure', 'measure', 'twice')
        for unused in range(2):
            report.dependency('orders.view.lkml', '$measure.sql', owner, 'amount', resolution='unbound')
        result = report.finish()
        self.assertEqual(len({x['occurrence_id'] for x in result['dependencies']}), 2)
        self.assertEqual(len(merge([result])['dependencies']), 2)

    def test_finish_does_not_change_gap_deduplication(self):
        report = Report('dbt', {'model.sql': 'select 1'})
        report.gap('model.sql', 'synthetic', 'Still unresolved')
        first = copy.deepcopy(report.finish())
        report.gap('model.sql', 'synthetic', 'Still unresolved')
        self.assertEqual(first, report.finish())

    def test_forged_occurrences_and_expression_hashes_are_rejected(self):
        for field in ('occurrence_id', 'content_sha256'):
            report = evidence()
            report['expressions'][0][field] = 'forged'
            with self.assertRaises(ValueError):
                validate(report, {'models/orders.sql': report['expressions'][0]['text']})
            with self.assertRaises(ValueError):
                merge([report])

    @unittest.skipUnless(importlib.util.find_spec('lkml'), 'Pinned lkml parser is required')
    def test_long_lookml_measure_filters_and_dashboard_dynamic_fields_are_preserved(self):
        long_sql = '${TABLE}.amount /* ' + 'source-token-' * 150 + ' */'
        view = 'view: orders { measure: revenue { type: sum sql: ' + long_sql + ' ;; filters: [status: "complete,-refunded"] } }'
        calculation = '${orders.revenue} /* ' + 'calculation-' * 150 + ' */'
        native_id = 'dashboard-' + 'identity-' * 50
        query = {'id': 'query', 'model': 'sales', 'view': 'orders', 'fields': ['orders.revenue'],
                 'query_timezone': 'America/Chicago', 'filters': {'orders.status': 'complete'},
                 'dynamic_fields': json.dumps([{'table_calculation': 'net', 'expression': calculation},
                                                {'measure': 'filtered_revenue', 'based_on': 'orders.revenue',
                                                 'filters': {'orders.status': 'complete'}}])}
        dashboard = {'id': native_id, 'title': 'Synthetic',
                     'dashboard_elements': [{'id': 'tile', 'type': 'vis', 'query': query}],
                     'dashboard_filters': [], 'dashboard_layouts': []}
        files = {'orders.view.lkml': view, 'dashboard.json': json.dumps(dashboard)}
        report = parse_looker(files)
        validate(report, files)
        measure = next(x for x in report['objects'] if x['kind'] == 'lookml_measure')
        self.assertEqual(measure['details']['native_properties']['filters__all'], [[{'status': 'complete,-refunded'}]])
        self.assertIn(long_sql, [x['text'] for x in report['expressions']])
        self.assertIn(calculation, [x['text'] for x in report['expressions']])
        self.assertIn(native_id, [x['native_id'] for x in report['objects']])
        query_object = next(x for x in report['objects'] if x['kind'] == 'query')
        self.assertEqual(query_object['details']['native_payload'], query)
        merged = merge([report])
        self.assertEqual(merged['source_contracts'], [report])

    def test_authored_dbt_ref_whitespace_retains_literal_without_claiming_runtime_lineage(self):
        text = "-- comment {{ ref('not_a_dependency') }}\nselect * from {{ ref ('orders') }}\n" + '/*' + 'long-source-' * 100 + '*/'
        report = parse_dbt({'models/inert.sql': text})
        self.assertIn(text, [x['text'] for x in report['expressions']])
        self.assertEqual([row['target'] for row in report['dependencies']], ['ref:orders'])
        dependency = report['dependencies'][0]
        self.assertEqual(dependency['details']['resolution'], 'unbound_literal_declaration')
        self.assertIsNone(dependency['details']['target_object_id'])
        self.assertEqual(dependency['details']['effective_runtime_dependency'], 'not_verified')
        span = dependency['details']['literal_reference']['span']
        self.assertEqual(text[span['start']:span['end']], "{{ ref ('orders') }}")
        self.assertIn('dbt.literal_reference_unbound', {x['code'] for x in report['gaps']})
        self.assertIn('dbt.jinja_unrendered', {x['code'] for x in report['gaps']})
        self.assertFalse(report['execution_performed'])


if __name__ == '__main__':
    unittest.main()
