"""Bounded derived-view shape and privacy lineage, with no native execution."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import omni_contract as omni
import omni_query_views as query
from test_omni_contract import context,files


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None,'Pinned YAML/SQL runtime required')
class QueryViewTests(unittest.TestCase):
    def setUp(self):
        self.context=context();self.files=files()
        self.files['activity.topic']='base_view: events\njoins: {}\nfields: [all_views.*]\n'
        self.definition={'query':{'base_view':'events','topic':'activity','fields':{'events.tenant_id':'tenant','events.total':'value'}},
                         'dimensions':{'tenant':{},'value':{}}}

    def candidate(self):
        self.files['by_tenant.query.view']=omni.yaml.safe_dump(self.definition)
        return self.files

    def analyze(self):return query.analyze_query_views(self.candidate(),self.context)

    def test_modeled_query_is_not_bound_to_a_physical_table(self):
        result=self.analyze()
        self.assertEqual('passed',result['status'],result['findings'])
        self.assertIsNone(result['binding_origins']['by_tenant'])
        self.assertEqual({'tenant','value'},set(result['descriptors']['by_tenant']['outputs']))
        self.assertEqual('passed',omni.check_model(self.candidate(),self.context)['status'])
        self.assertFalse(result['native_verified'])

    def test_predicate_and_grouping_dependencies_propagate(self):
        self.definition['query']['filters']={'events.id':{'greater_than':5}}
        columns=self.analyze()['descriptors']['by_tenant']['outputs']['value']['physical_columns']
        self.assertEqual({'ID','VALUE','TENANT_ID'},{c['column'] for c in columns})

    def test_numeric_joined_grouping_is_population_dependency(self):
        self.files['peers.view']=self.files['events.view'].replace('table_name: EVENTS','table_name: PEERS')
        self.context['bindings']['peers']=copy.deepcopy(self.context['bindings']['events'])
        self.context['bindings']['peers']['namespace']['table']='PEERS'
        self.files['activity.topic']='''base_view: events
joins: {peers: {}}
relationships:
- {join_from_view: events, join_to_view: peers, join_type: left, relationship_type: many_to_one, on_sql: '${events.id} = ${peers.id}'}
'''
        self.definition['query']['fields']={'peers.value':'peer_group','events.total':'value'}
        self.definition['dimensions']={'peer_group':{},'value':{}}
        report=self.analyze();self.assertEqual('passed',report['status'],report['findings'])
        dependencies=report['descriptors']['by_tenant']['outputs']['value']['physical_columns']
        self.assertIn(('peers','VALUE'),{(v['view'],v['column']) for v in dependencies})

    def test_array_fields_with_one_pair_alias_are_supported(self):
        self.definition['query']['fields']=[{'events.tenant_id':'tenant'},{'events.total':'value'}]
        self.assertEqual('passed',self.analyze()['status'])

    def test_query_timeframes_resolve_enum_type_and_fiscal_context(self):
        for reference in ('events.id[time]','events.id[date]','events.count[date]','events.recorded_at[fiscal_year]'):
            self.definition['query']['fields']={reference:'value'};self.definition['dimensions']={'value':{}}
            self.assertEqual('failed',self.analyze()['status'],reference)
            self.assertNotEqual('passed',omni.check_model(self.candidate(),self.context)['status'])
        self.definition['query']['fields']={'events.recorded_at[date]':'value'}
        self.assertEqual('passed',self.analyze()['status'])

    def test_output_omitted_dimension_is_a_gap_not_physical_fabrication(self):
        self.definition['dimensions']['phantom']={}
        self.assertEqual('failed',self.analyze()['status'])
        self.assertNotEqual('passed',omni.check_model(self.candidate(),self.context)['status'])

    def test_derived_dimension_uses_real_query_output(self):
        self.definition['dimensions']['doubled']={'sql':'${value} * 2'}
        report=self.analyze();self.assertEqual('passed',report['status'],report['findings'])
        self.assertIn('VALUE',{v['column'] for v in report['field_lineage']['by_tenant.doubled']['physical_columns']})

    def test_raw_table_binding_to_derived_view_rejected(self):
        self.context['bindings']['by_tenant']=copy.deepcopy(self.context['bindings']['events'])
        self.assertEqual('failed',self.analyze()['status'])

    def test_query_topic_exclusion_and_ai_awareness_separate(self):
        self.files['activity.topic']='base_view: events\njoins: {}\nfields: [events.tenant_id]\n'
        self.assertEqual('failed',self.analyze()['status'])
        self.files['activity.topic']='base_view: events\njoins: {}\nai_fields: [events.id]\n'
        self.assertEqual('passed',self.analyze()['status'])

    def test_whitelist_implicit_dependency_is_visible_qualification_note(self):
        self.files['activity.topic']='base_view: events\njoins: {}\nfields: [events.tenant_id, events.total]\n'
        result=self.analyze()
        self.assertEqual('passed',result['status'])
        self.assertIn('events.value',result['descriptors']['by_tenant']['implicit_whitelist_dependencies'])
        self.assertEqual('native_qualification_required',result['descriptors']['by_tenant']['runtime_eligibility'])

    def test_limit_requires_sort_and_declares_incomplete_population(self):
        self.definition['query']['limit']=2
        self.assertEqual('unsupported',self.analyze()['status'])
        self.definition['query']['sorts']=[{'field':'events.total','desc':True}]
        result=self.analyze();self.assertEqual('unsupported',result['status'])
        self.assertFalse(result['descriptors']['by_tenant']['complete_population'])
        self.assertEqual('limited',result['descriptors']['by_tenant']['truncation'])

    def test_duplicate_outputs_and_cycles_fail(self):
        self.definition['query']['fields']=[{'events.total':'value'},{'events.count':'value'}]
        self.assertEqual('failed',self.analyze()['status'])
        self.definition['query']={'base_view':'by_tenant','fields':{'by_tenant.value':'value'}}
        self.assertEqual('failed',self.analyze()['status'])

    def test_sql_view_lineage_includes_predicate_group_and_count_population(self):
        self.definition={'sql':'SELECT e."TENANT_ID" AS tenant, COUNT(*) AS value FROM ${events} e WHERE e."VALUE" > 0 GROUP BY e."TENANT_ID"',
                         'dimensions':{'tenant':{},'value':{}}}
        report=self.analyze();self.assertEqual('passed',report['status'],report['findings'])
        self.assertEqual(set(self.context['bindings']['events']['columns']),{v['column'] for v in report['descriptors']['by_tenant']['outputs']['value']['physical_columns']})
        self.assertEqual('passed',omni.check_model(self.candidate(),self.context)['status'])

    def test_sql_writes_external_tables_and_opaque_shapes_never_pass(self):
        for sql in ('DELETE FROM events','SELECT * FROM ${events}', 'SELECT "ID" AS id FROM external',
                    'SELECT "ID" AS id FROM ${events}; DELETE FROM events',
                    'WITH x AS (SELECT * FROM ${events}) SELECT id AS id FROM x',
                    'SELECT "ID" AS id INTO other FROM ${events}',
                    'SELECT CUSTOM_FUNC("ID") AS id FROM ${events}'):
            self.definition={'sql':sql,'dimensions':{'id':{}}}
            self.assertNotEqual('passed',self.analyze()['status'],sql)

    def test_standalone_expression_rejects_extra_statement(self):
        view=omni._load(self.files['events.view']);view['dimensions']['id']['sql']='"ID"; SELECT 2'
        self.files['events.view']=omni.yaml.safe_dump(view)
        self.assertEqual('failed',self.analyze()['status'])

    def test_output_schema_and_context_changes_change_pins(self):
        first=self.analyze();self.definition['dimensions']['value']['label']='Reviewed'
        second=self.analyze();self.assertNotEqual(first['candidate_sha256'],second['candidate_sha256'])
        self.context['catalogue_sha256']='c'*64
        self.assertNotEqual(second['context_sha256'],self.analyze()['context_sha256'])

    def test_value_free_diagnostics_and_bounded_malformed_inputs(self):
        self.definition['query']['filters']={'events.id':{'greater_than':'SYNTHETIC_PRIVATE_MARKER'}}
        result=self.analyze();self.assertEqual('failed',result['status'])
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER',json.dumps(result['findings']))
        for bad in (None,[],True,{},'bad'):
            self.assertNotEqual('passed',query.analyze_query_views(self.candidate(),bad)['status'])


class QueryRuntimeTests(unittest.TestCase):
    def test_optional_runtime_is_pending(self):
        with patch.object(query,'yaml',None):
            self.assertEqual('unsupported',query.analyze_query_views(files(),context())['status'])


if __name__=='__main__':unittest.main()
