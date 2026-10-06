"""Core v2 authored tests; native and business evidence remain independent."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import omni_contract as omni
from test_omni_contract import files,context


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None,'Pinned YAML/SQL runtime required')
class CoreExpansionTests(unittest.TestCase):
    def setUp(self):
        self.files=files();self.context=context()
        self.view=omni._load(self.files['events.view'])
        self.topic=omni._load(self.files['activity.topic'])
        self.topic['fields']=['all_views.*']

    def check(self):
        self.files['events.view']=omni.yaml.safe_dump(self.view)
        self.files['activity.topic']=omni.yaml.safe_dump(self.topic)
        return omni.check_model(self.files,self.context)

    def test_filter_is_measure_local_and_literal_preserved(self):
        self.view['measures']['total']['filters']={'tenant_id':{'is':['synthetic-a','synthetic-b']}}
        result=self.check()
        self.assertEqual('passed',result['status'],result)
        self.assertNotIn('synthetic-a',json.dumps(result))
        self.assertNotIn('always_where_filters',self.topic)

    def test_bad_filter_reference_and_types_fail(self):
        for value in ({'missing':{'is':1}},{'count':{'is':1}}, {'value':{'greater_than':True}}, {'value':{'is':{'nested':'no'}}}):
            self.view['measures']['total']['filters']=value
            self.assertEqual('failed',self.check()['status'])

    def test_advanced_filter_remains_preserved_unsupported(self):
        self.view['measures']['total']['filters']={'value':{'query_structure':{}}}
        self.assertEqual('unsupported',self.check()['status'])

    def test_topic_alias_namespace_is_isolated(self):
        self.topic['views']={'historical':{'extends':['events'],'dimensions':{'id':{'label':'Historical identifier'}}}}
        self.topic['relationships']=[{'join_from_view':'events','join_to_view':'historical','join_type':'left',
              'relationship_type':'many_to_one','on_sql':'${events.id} = ${historical.id}'}]
        self.topic['joins']={'historical':{}}
        self.assertEqual('passed',self.check()['status'],self.check())
        self.files['other.topic']='base_view: historical\njoins: {}\n'
        self.assertEqual('failed',self.check()['status'])

    def test_topic_extends_overlay_and_cycle(self):
        self.files['child.topic']='extends: [activity]\nlabel: Child\n'
        self.assertEqual('passed',self.check()['status'])
        self.topic['extends']=['child']
        self.assertEqual('failed',self.check()['status'])

    def test_selector_precedence_not_text_order(self):
        self.topic['fields']=['events.id','-events.*','all_views.*']
        result=self.check()
        self.assertEqual('passed',result['status'])
        self.assertEqual(['events.id'],result['topic_scopes']['activity']['selections']['fields'])

    def test_tag_selector_and_excluded_measure_dependency(self):
        self.view['dimensions']['id']['tags']=['reviewed']
        self.topic['fields']=['tag:reviewed']
        self.assertEqual(['events.id'],self.check()['topic_scopes']['activity']['selections']['fields'])
        self.topic['fields']=['all_views.*','-events.value']
        self.assertIn('topic.excluded_dependency',[f['code'] for f in self.check()['findings']])

    def test_ai_awareness_exclusion_is_not_a_security_restriction(self):
        self.topic['ai_fields']=['all_views.*','-events.value']
        report=self.check()
        self.assertEqual('passed',report['status'],report)
        self.assertFalse(report['topic_scopes']['activity']['ai_fields_is_access_control'])

    def test_calendar_requires_fiscal_offset_and_rejects_dynamic(self):
        self.view['dimensions']['recorded_at']['timeframes']=['fiscal_year']
        self.assertEqual('failed',self.check()['status'])
        self.files['model']='fiscal_month_offset: -1\nweek_start_day: Monday\ndefault_timeframes: [raw, date]\n'
        self.assertEqual('passed',self.check()['status'])
        self.files['model']='fiscal_month_offset: "{{ attribute }}"\n'
        self.assertNotEqual('passed',self.check()['status'])

    def test_unknown_operational_model_settings_do_not_pass(self):
        for key in ('sql_preamble','cache_policies','custom_calendars','dynamic_schemas'):
            self.files['model']=key+': {}\n'
            self.assertEqual('unsupported',self.check()['status'])

    def test_malformed_scoped_shapes_never_raise(self):
        for bad in (None,[],True,{'x':[]},{'x':{'extends':True}}):
            self.topic['views']=bad
            self.assertNotEqual('passed',self.check()['status'])

    def test_versioned_and_native_unqualified(self):
        report=self.check()
        self.assertEqual('omni-static-v2-2026-10-05',report['contract_version'])
        self.assertFalse(report['native_verified'])
        self.assertFalse(report['security_verified'])


if __name__=='__main__':unittest.main()
