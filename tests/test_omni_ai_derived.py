"""AI definitions retain gold-column and population lineage through query views."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_ai_context as ai
import omni_contract as omni
from test_omni_ai_context import fixture, reviewed
from test_privacy_contract import approved_classification


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None, 'Pinned semantic runtime required')
class DerivedContextTests(unittest.TestCase):
    def prepare(self, sql=False):
        spec, inputs = fixture()
        definition = {'schema': 'GOLD', 'dimensions': {'posted_day': {}, 'net_total': {}},
                      'measures': {'total': {'sql': '${net_total}', 'aggregate_type': 'sum'}}}
        if sql:
            definition['sql'] = ('SELECT CAST("POSTED_AT" AS DATE) AS posted_day, SUM("AMOUNT") AS net_total '
                                 'FROM ${shipments} GROUP BY CAST("POSTED_AT" AS DATE)')
        else:
            definition['query'] = {'base_view': 'shipments', 'topic': 'shipments',
                                   'fields': {'shipments.posted_at[date]': 'posted_day', 'shipments.net_total': 'net_total'}}
        inputs['model_files']['daily.query.view'] = omni.yaml.safe_dump(definition)
        inputs['model_files']['daily.topic'] = 'base_view: daily\njoins: {}\nfields: [all_views.*]\nai_fields: [daily.total]\n'
        spec['topic'] = 'daily'
        old = spec['bindings'].pop('shipments.net_total')
        old['field_sha256'] = ai.digest(definition['measures']['total'])
        old['columns'].append({**old['columns'][0], 'column': 'POSTED_AT', 'column_id': 'mart_shipments.POSTED_AT'})
        spec['bindings']['daily.total'] = old
        for record in spec['definitions']: record['fields'] = ['daily.total']
        spec['pins'] = ai.input_pins(**inputs)
        return reviewed(spec), inputs

    def test_modeled_and_sql_outputs_trace_to_real_gold_columns(self):
        for sql in (False, True):
            spec, inputs = self.prepare(sql)
            result = ai.build_context(spec, **inputs)
            self.assertEqual(len(result['context']['approved_definitions']), 1)
            self.assertEqual(result['context']['topic_scope']['topic'], 'daily')
            self.assertFalse(result['context']['native_verified'])
            self.assertNotIn('daily', inputs['model_context']['bindings'])

    def test_omitting_grouping_population_column_fails(self):
        spec, inputs = self.prepare()
        spec['bindings']['daily.total']['columns'].pop()
        reviewed(spec)
        with self.assertRaises(ai.ContextError): ai.build_context(spec, **inputs)

    def test_sensitive_population_dependency_cannot_be_hidden_by_aggregation(self):
        spec, inputs = self.prepare()
        inputs['dictionary']['models'][0]['columns'][2]['privacy'] = approved_classification('RESTRICTED', ['PHI'])
        inputs['dictionary']['models'][0]['columns'][2]['sensitivity'] = 'RESTRICTED'
        spec['pins'] = ai.input_pins(**inputs); reviewed(spec)
        result = ai.build_context(spec, **inputs)
        self.assertEqual(result['context']['approved_definitions'], [])
        self.assertGreater(result['context']['withheld_definition_count'], 0)

    def test_topic_context_selection_cannot_be_ignored(self):
        spec, inputs = self.prepare()
        inputs['model_files']['daily.topic'] = 'base_view: daily\njoins: {}\nfields: [all_views.*]\nai_fields: [daily.posted_day]\n'
        spec['pins'] = ai.input_pins(**inputs); reviewed(spec)
        with self.assertRaises(ai.ContextError): ai.build_context(spec, **inputs)

    def test_server_context_patch_cannot_be_authored(self):
        spec, inputs = self.prepare()
        inputs['model_files']['daily.topic'] += 'ai_context_patch: inferred text\n'
        spec['pins'] = ai.input_pins(**inputs); reviewed(spec)
        with self.assertRaises(ai.ContextError): ai.build_context(spec, **inputs)

    def test_filter_operand_requires_classification_even_when_unprojected(self):
        spec, inputs = fixture()
        view = omni._load(inputs['model_files']['shipments.view'])
        view['measures']['net_total']['filters'] = {'id': {'is': 'synthetic-id'}}
        inputs['model_files']['shipments.view'] = omni.yaml.safe_dump(view)
        spec['bindings']['shipments.net_total']['field_sha256'] = ai.digest(view['measures']['net_total'])
        spec['pins'] = ai.input_pins(**inputs); reviewed(spec)
        with self.assertRaises(ai.ContextError): ai.build_context(spec, **inputs)
        column = spec['bindings']['shipments.net_total']['columns'][0]
        spec['bindings']['shipments.net_total']['columns'].append({**column, 'column': 'ID', 'column_id': 'mart_shipments.ID'})
        reviewed(spec)
        self.assertEqual(len(ai.build_context(spec, **inputs)['context']['approved_definitions']), 1)


if __name__ == '__main__':
    unittest.main()
