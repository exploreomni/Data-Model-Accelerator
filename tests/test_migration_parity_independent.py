"""Independent logistics parity counterexamples, with literal expected behavior."""
import copy
import json
import os
import subprocess
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import migration_parity as parity
from ae_common import hash_json


def seal(plan, baseline):
    plan['baseline_sha256'] = hash_json(baseline)
    plan['review'] = {'status':'approved','reference':'synthetic-independent-review',
                     'plan_sha256':hash_json({k:v for k,v in plan.items() if k != 'review'})}


def fixture(scope='full_dashboard'):
    context={'snapshot_sha256':'1'*64,'timezone':'America/Chicago','parameters_sha256':'2'*64,'persona_sha256':'3'*64}
    metrics={'duplicate_keys':0,'orphan_keys':0,'tenant_violations':0,'join_input_rows':2,'join_output_rows':2}
    data={'id':'shipment-baseline','kind':'data','subject_kind':'tile','subject_id':'shipments','scenario':'baseline',
          'context':copy.deepcopy(context),'queries':{'source':'4'*64,'warehouse':'5'*64,'omni':'6'*64},
          'columns':{'parcel':'string','delay':'number','shipped_on':'date'},'grain':['parcel'],'ordered':True,
          'allow_null_grain':False,'tolerances':{'delay':{'absolute':0.01,'relative':0,'reason':'Approved rounding to cents'}},
          'expected_metrics':metrics,'truncated':False}
    interactions=[{'id':identity+'-ui','kind':'interaction','subject_kind':kind,'subject_id':identity,
                   'scenario':'render-and-filter','context':copy.deepcopy(context)}
                  for identity,kind in (('shipments','tile'),('footnote','tile'),('period','filter'))]
    cases=[data]+(interactions if scope=='full_dashboard' else [])
    plan={'schema_version':1,'kind':'migration_parity_plan','migration_scope':scope,
          'bindings':{key:'a'*64 for key in ('source','catalogue','candidate','target','policy','scope')},
          'baseline_sha256':'b'*64,'inventory':{'data_tiles':['shipments'],'text_tiles':['footnote'],'filter_ids':['period']},
          'scenario_requirements':{'shipments':['baseline']},'cases':cases,'review':{}}
    captures=[]
    for lane in ('source','warehouse','omni'):
        observations={data['id']:{'context':dict(context,query_sha256=data['queries'][lane]),
            'rows':[{'parcel':'private-parcel-A','delay':12.0,'shipped_on':'2026-03-08'},
                    {'parcel':'private-parcel-B','delay':8.0,'shipped_on':'2026-03-09'}],
            'metrics':copy.deepcopy(metrics),'truncated':False}}
        for case in interactions if scope=='full_dashboard' else []:
            observations[case['id']]={'context':copy.deepcopy(context),
                'value':{'visible':True,'rendered_text_digest':'c'*64,'display_order':['shipments','footnote'],
                         'filter_effect':{'includes_today':False,'start_inclusive':True}}}
        captures.append({'schema_version':1,'kind':'migration_observations','origin':lane,
                         'provenance':'source_observed' if lane=='source' else 'native_observed',
                         'independent_of_candidate':lane=='source','reference':'synthetic-independent-'+lane,
                         'cases':observations})
    seal(plan,captures[0])
    return (plan,*captures)


class IndependentParityTests(unittest.TestCase):
    def test_matching_three_lanes_are_local_consistency_only(self):
        args=fixture();result=parity.evaluate(*args)
        self.assertEqual(result['status'],'locally_consistent')
        for key in ('native_verified','evidence_authenticated','acceptance_ready'):self.assertFalse(result[key])
        self.assertNotIn('private-parcel',json.dumps(result))
        self.assertEqual(len(result['cases']),4)

    def test_matching_grand_totals_do_not_hide_different_population(self):
        plan,source,warehouse,omni=fixture()
        warehouse['cases']['shipment-baseline']['rows'][0]['parcel']='private-other-A'
        warehouse['cases']['shipment-baseline']['rows'][1]['parcel']='private-other-B'
        self.assertEqual(parity.evaluate(plan,source,warehouse,omni)['status'],'failed')

    def test_duplicate_grain_and_fanout_fail_even_when_metrics_claim_safe(self):
        for lane in (2,3):
            args=list(fixture());rows=args[lane]['cases']['shipment-baseline']['rows'];rows.append(copy.deepcopy(rows[0]))
            with self.subTest(lane=lane):self.assertEqual(parity.evaluate(*args)['status'],'failed')

    def test_wrong_orphan_tenant_and_join_observations_fail(self):
        for metric in ('orphan_keys','tenant_violations','join_output_rows'):
            args=list(fixture());args[3]['cases']['shipment-baseline']['metrics'][metric]+=1
            with self.subTest(metric=metric):self.assertEqual(parity.evaluate(*args)['status'],'failed')

    def test_null_is_not_zero(self):
        plan,source,warehouse,omni=fixture()
        source['cases']['shipment-baseline']['rows'][0]['delay']=None
        warehouse['cases']['shipment-baseline']['rows'][0]['delay']=None
        omni['cases']['shipment-baseline']['rows'][0]['delay']=0
        seal(plan,source)
        self.assertEqual(parity.evaluate(plan,source,warehouse,omni)['status'],'failed')

    def test_null_grain_is_explicit_and_still_unique(self):
        plan,source,warehouse,omni=fixture()
        for capture in (source,warehouse,omni):capture['cases']['shipment-baseline']['rows'][0]['parcel']=None
        seal(plan,source)
        self.assertEqual(parity.evaluate(plan,source,warehouse,omni)['status'],'failed')
        plan['cases'][0]['allow_null_grain']=True;seal(plan,source)
        self.assertEqual(parity.evaluate(plan,source,warehouse,omni)['status'],'locally_consistent')

    def test_order_is_preserved_when_declared(self):
        plan,source,warehouse,omni=fixture();omni['cases']['shipment-baseline']['rows'].reverse()
        self.assertEqual(parity.evaluate(plan,source,warehouse,omni)['status'],'failed')
        plan['cases'][0]['ordered']=False;seal(plan,source)
        self.assertEqual(parity.evaluate(plan,source,warehouse,omni)['status'],'locally_consistent')

    def test_predeclared_numeric_tolerance_and_stale_review(self):
        plan,source,warehouse,omni=fixture();omni['cases']['shipment-baseline']['rows'][0]['delay']=12.005
        self.assertEqual(parity.evaluate(plan,source,warehouse,omni)['status'],'locally_consistent')
        omni['cases']['shipment-baseline']['rows'][0]['delay']=12.02
        self.assertEqual(parity.evaluate(plan,source,warehouse,omni)['status'],'failed')
        plan['cases'][0]['tolerances']['delay']['absolute']=1
        with self.assertRaises(ValueError):parity.evaluate(plan,source,warehouse,omni)

    def test_snapshot_timezone_parameter_persona_and_query_drift_fail(self):
        for key in ('snapshot_sha256','timezone','parameters_sha256','persona_sha256','query_sha256'):
            args=list(fixture());args[3]['cases']['shipment-baseline']['context'][key]='UTC' if key=='timezone' else 'f'*64
            with self.subTest(context_key=key):self.assertEqual(parity.evaluate(*args)['status'],'failed')

    def test_row_limit_truncation_cannot_silently_change(self):
        args=list(fixture());args[3]['cases']['shipment-baseline']['truncated']=True
        self.assertEqual(parity.evaluate(*args)['status'],'failed')

    def test_equal_day_totals_do_not_replace_ui_filter_or_layout_evidence(self):
        for case_id,key,value in (('period-ui','filter_effect',{'includes_today':True,'start_inclusive':True}),
                                  ('footnote-ui','rendered_text_digest','d'*64),
                                  ('shipments-ui','display_order',['footnote','shipments'])):
            args=list(fixture());args[3]['cases'][case_id]['value'][key]=value
            with self.subTest(case=case_id):self.assertEqual(parity.evaluate(*args)['status'],'failed')

    def test_missing_omni_row_and_interaction_observation_remain_pending(self):
        for case_id in ('shipment-baseline','period-ui','footnote-ui'):
            args=list(fixture());del args[3]['cases'][case_id]
            with self.subTest(case=case_id):self.assertEqual(parity.evaluate(*args)['status'],'pending')
        plan,source,warehouse,_=fixture()
        self.assertEqual(parity.evaluate(plan,source,warehouse)['status'],'pending')

    def test_missing_selected_tile_filter_and_mandatory_scenario_reject_plan(self):
        for change in ('text','filter','scenario','data'):
            plan,source,warehouse,omni=fixture()
            if change=='text':plan['cases']=[c for c in plan['cases'] if c['subject_id']!='footnote']
            elif change=='filter':plan['cases']=[c for c in plan['cases'] if c['subject_id']!='period']
            elif change=='scenario':plan['scenario_requirements']['shipments'].append('dst-boundary')
            else:plan['inventory']['data_tiles'].append('undelivered-tile')
            seal(plan,source)
            with self.subTest(change=change),self.assertRaises(ValueError):parity.evaluate(plan,source,warehouse,omni)

    def test_source_cannot_be_self_oracle_or_changed_after_freeze(self):
        plan,source,warehouse,omni=fixture();source['independent_of_candidate']=False;seal(plan,source)
        with self.assertRaises(ValueError):parity.evaluate(plan,source,warehouse,omni)
        plan,source,warehouse,omni=fixture();source['cases']['shipment-baseline']['rows'][0]['delay']=99
        with self.assertRaises(ValueError):parity.evaluate(plan,source,warehouse,omni)

    def test_model_scope_does_not_falsely_require_omni(self):
        plan,source,warehouse,_=fixture('model_only')
        self.assertEqual(parity.evaluate(plan,source,warehouse)['status'],'locally_consistent')

    def test_report_is_deterministic_across_process_hash_seeds(self):
        program = "import sys,json;sys.path.insert(0,'tests');from test_migration_parity_independent import fixture,parity;a=list(fixture());a[2]['cases']['shipment-baseline']['rows'][0]['delay']=44;a[3]['cases']['shipment-baseline']['rows'][0]['delay']=55;print(json.dumps(parity.evaluate(*a),sort_keys=True))"
        results=[]
        for seed in ('1','2'):
            result=subprocess.run([sys.executable,'-B','-c',program],cwd=Path(__file__).resolve().parents[1],
                env=dict(os.environ,PYTHONHASHSEED=seed),capture_output=True,text=True,check=True)
            results.append(result.stdout)
        self.assertEqual(results[0],results[1])

    def test_invalid_types_dates_nan_and_missing_fields_fail_without_values(self):
        for change in ('bool','date','nan','missing'):
            args=list(fixture());row=args[3]['cases']['shipment-baseline']['rows'][0]
            if change=='bool':row['delay']=True
            elif change=='date':row['shipped_on']='2026-02-30'
            elif change=='nan':row['delay']=float('nan')
            else:del row['parcel']
            with self.subTest(change=change):
                try:
                    result=parity.evaluate(*args)
                except ValueError:continue
                self.assertEqual(result['status'],'failed')
                self.assertNotIn('private-parcel',json.dumps(result))


if __name__=='__main__':unittest.main()
