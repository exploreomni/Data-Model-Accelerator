"""Static semantics exercise arbitrary domains; no live native qualification."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import omni_contract as omni


def context(warehouse='snowflake'):
    namespace={'database':'ANALYTICS','schema':'GOLD','table':'EVENTS'}
    if warehouse=='databricks': namespace={'catalog':'analytics','schema':'gold','table':'events'}
    if warehouse=='bigquery': namespace={'project':'synthetic-project','dataset':'gold','table':'events'}
    if warehouse=='clickhouse': namespace={'database':'analytics','table':'events'}
    return {'schema_version':1,'kind':'omni_model_context','warehouse':warehouse,'environment':'development',
            'catalogue_sha256':'a'*64,'bindings':{'events':{'namespace':namespace,
                'columns':{'ID':'number','RECORDED_AT':'timestamp','VALUE':'number','TENANT_ID':'string'},
                'evidence_sha256':'b'*64}},'inherited_views':{},'default_catalog':None,
            'user_attributes':['tenant_id'],'access_grants':[]}


def files():
    return {'events.view':'''catalog: ANALYTICS
schema: GOLD
table_name: EVENTS
dimensions:
  id:
    sql: '"ID"'
    primary_key: true
  recorded_at:
    sql: '"RECORDED_AT"'
    timeframes: [raw, date, week]
  value:
    sql: '"VALUE"'
  tenant_id:
    sql: '"TENANT_ID"'
measures:
  count:
    aggregate_type: count
  total:
    sql: ${value}
    aggregate_type: sum
  average:
    sql: ${total} / NULLIF(${count}, 0)
    format: '0.0%'
''', 'activity.topic':'''base_view: events
joins: {}
fields:
  - events.recorded_at[date]
  - events.total
access_filters:
  - field: events.tenant_id
    user_attribute: tenant_id
'''}


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None,'Pinned PyYAML and sqlglot runtime required')
class OmniContractTests(unittest.TestCase):
    def check(self,candidate=None,binding=None):
        return omni.check_model(files() if candidate is None else candidate,context() if binding is None else binding)

    def test_valid_candidate_is_local_not_native_or_security_evidence(self):
        result=self.check()
        self.assertEqual(result['status'],'passed',result)
        self.assertFalse(result['native_verified']); self.assertFalse(result['security_verified'])
        self.assertEqual(result['candidate_sha256'],omni.canonical_hash(files()))
        self.assertEqual(result,self.check())

    def test_each_warehouse_uses_its_explicit_namespace(self):
        for warehouse in omni.DIALECTS:
            binding=context(warehouse); candidate=files(); ns=binding['bindings']['events']['namespace']
            view=omni.yaml.safe_load(candidate['events.view'])
            view['catalog']=ns.get('database',ns.get('catalog',ns.get('project')))
            view['table_name']=ns['table']
            if 'schema' in ns or 'dataset' in ns: view['schema']=ns.get('schema',ns.get('dataset'))
            else: view.pop('schema')
            if warehouse in ('databricks','bigquery','clickhouse'):
                for item in view['dimensions'].values(): item['sql']=item['sql'].replace('"','`')
            candidate['events.view']=omni.yaml.safe_dump(view)
            with self.subTest(warehouse=warehouse): self.assertEqual(self.check(candidate,binding)['status'],'passed')

    def test_namespace_and_exact_quoted_case_do_not_drift(self):
        candidate=files(); candidate['events.view']=candidate['events.view'].replace('catalog: ANALYTICS','catalog: OTHER')
        self.assertEqual(self.check(candidate)['status'],'failed')
        candidate=files(); candidate['events.view']=candidate['events.view'].replace('"VALUE"','"value"')
        self.assertEqual(self.check(candidate)['status'],'failed')

    def test_missing_context_never_passes_as_resolved(self):
        result=omni.check_model(files())
        self.assertNotEqual(result['status'],'passed')
        self.assertIn('context.required',[f['code'] for f in result['findings']])

    def test_measure_aggregate_and_dimension_parameter_placement(self):
        for before,after in [('aggregate_type: sum','aggregate_type: total'),
                              ('aggregate_type: sum','type: sum'),
                              ('primary_key: true','aggregate_type: sum')]:
            candidate=files(); candidate['events.view']=candidate['events.view'].replace(before,after)
            self.assertEqual(self.check(candidate)['status'],'failed')

    def test_nested_aggregate_sql_and_nested_measure_reference_fail(self):
        for sql in ('SUM(${value})','${count}'):
            candidate=files(); candidate['events.view']=candidate['events.view'].replace('sql: ${value}', 'sql: '+sql)
            self.assertEqual(self.check(candidate)['status'],'failed')

    def test_percentile_requires_numeric_percent_and_distinct_requires_key(self):
        candidate=files(); candidate['events.view']=candidate['events.view'].replace('aggregate_type: sum','aggregate_type: percentile')
        self.assertEqual(self.check(candidate)['status'],'failed')
        candidate['events.view']=candidate['events.view'].replace('aggregate_type: percentile','aggregate_type: percentile\n    percentile: 75')
        self.assertEqual(self.check(candidate)['status'],'passed')
        candidate['events.view']=candidate['events.view'].replace('aggregate_type: percentile','aggregate_type: sum_distinct_on')
        self.assertEqual(self.check(candidate)['status'],'failed')

    def test_relationship_edges_are_required_by_the_topic_join_tree(self):
        candidate=files(); binding=context(); candidate['groups.view']='catalog: ANALYTICS\nschema: GOLD\ntable_name: GROUPS\ndimensions:\n  id:\n    sql: \'"ID"\'\n'
        binding['bindings']['groups']=copy.deepcopy(binding['bindings']['events']); binding['bindings']['groups']['namespace']['table']='GROUPS'
        candidate['activity.topic']=candidate['activity.topic'].replace('joins: {}','joins:\n  groups: {}')
        self.assertEqual(self.check(candidate,binding)['status'],'failed')
        candidate['relationships']='''- join_from_view: events
  join_to_view: groups
  join_type: left
  relationship_type: many_to_one
  on_sql: ${events.id} = ${groups.id}
'''
        self.assertEqual(self.check(candidate,binding)['status'],'passed')
        candidate['relationships']=candidate['relationships'].replace('groups.id','groups.missing')
        self.assertEqual(self.check(candidate,binding)['status'],'failed')

    def test_access_filter_shape_and_user_attribute_resolution(self):
        for before,after in [('user_attribute: tenant_id','user_attribute: missing'),
                              ('field: events.tenant_id','field: events.count')]:
            candidate=files(); candidate['activity.topic']=candidate['activity.topic'].replace(before,after)
            self.assertEqual(self.check(candidate)['status'],'failed')

    def test_unknown_native_parameter_sql_template_and_function_do_not_pass(self):
        for sql in ('{{ unknown_macro }}','UNKNOWN_FUNCTION(${value})','__dma_ref_0'):
            candidate=files(); candidate['events.view']=candidate['events.view'].replace('sql: ${value}',"sql: '"+sql+"'")
            self.assertNotEqual(self.check(candidate)['status'],'passed')
        candidate=files(); candidate['model']='default_catalog: ANALYTICS\n'
        self.assertEqual(self.check(candidate)['status'],'unsupported')

    def test_parser_error_reports_never_include_raw_expressions(self):
        marker='DO_NOT_ECHO_SYNTHETIC_VALUE'
        candidate=files(); candidate['events.view']=candidate['events.view'].replace('sql: ${value}',"sql: 'SELECT "+marker+" FROM secret'")
        self.assertNotIn(marker,json.dumps(self.check(candidate)))

    def test_yaml_alias_duplicate_document_and_nonmapping_rejected(self):
        for value in ('label: one\nlabel: two','x: &a {}\ny: *a','{}\n---\n{}','[]'):
            result=self.check({'events.view':value})
            self.assertNotEqual(result['status'],'passed')

    def test_context_malformed_values_and_input_boundaries(self):
        for key in context():
            for bad in ([],{},None,True):
                if type(bad) is type(context()[key]) and bad==context()[key]: continue
                binding=context(); binding[key]=bad
                try: result=self.check(binding=binding)
                except Exception as error: self.fail('Unexpected exception for context '+key+': '+type(error).__name__)
                self.assertNotEqual(result['status'],'passed',key)
        self.assertEqual(self.check({'../events.view':'{}'})['status'],'failed')


class OmniRuntimeUnavailableTests(unittest.TestCase):
    def test_missing_yaml_runtime_never_passes(self):
        with patch.object(omni,'yaml',None):
            result=omni.check_model(files(),context())
        self.assertEqual(result['status'],'unsupported')
        self.assertFalse(result['native_verified'])

    @unittest.skipUnless(omni.yaml is not None,'PyYAML required to exercise SQL runtime absence')
    def test_missing_sql_runtime_never_passes(self):
        with patch.object(omni,'sqlglot',None):
            result=omni.check_model(files(),context())
        self.assertNotEqual(result['status'],'passed')
        self.assertIn('sql.runtime_or_dialect_unavailable',[f['code'] for f in result['findings']])


if __name__=='__main__': unittest.main()
