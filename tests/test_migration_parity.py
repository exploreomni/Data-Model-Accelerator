"""Source values are frozen independently from any generated SQL."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import migration_parity as parity
from ae_common import hash_json
from delivery_assurance import BINDINGS


def fixture(scope='model_semantic'):
    context={'snapshot_sha256':'1'*64,'timezone':'America/Chicago','parameters_sha256':'2'*64,'persona_sha256':'3'*64}
    metrics={'duplicate_keys':0,'orphan_keys':0,'tenant_violations':0,'join_input_rows':2,'join_output_rows':2}
    case={'id':'orders-baseline','kind':'data','subject_kind':'tile','subject_id':'orders','scenario':'baseline',
          'context':context,'queries':{'source':'4'*64,'warehouse':'5'*64,'omni':'6'*64},
          'columns':{'day':'date','revenue':'number'},'grain':['day'],'ordered':True,'allow_null_grain':False,
          'tolerances':{},'expected_metrics':metrics,'truncated':False}
    cases=[case]
    if scope=='full_dashboard':
        cases += [{'id':name+'-rendered','kind':'interaction','subject_kind':kind,'subject_id':name,
                   'scenario':'baseline','context':context} for name,kind in (('orders','tile'),('note','tile'),('period','filter'))]
    captures=[]
    for lane in ('source','warehouse','omni'):
        capture={'schema_version':1,'kind':'migration_observations','origin':lane,'provenance':'synthetic',
                 'independent_of_candidate':lane=='source','reference':'synthetic-independent-baseline','cases':{}}
        for c in cases:
            ctx=copy.deepcopy(context)
            if c['kind']=='data':
                ctx['query_sha256']=c['queries'][lane]
                obs={'context':ctx,'rows':[{'day':'2026-03-08','revenue':None},{'day':'2026-03-09','revenue':100}],
                     'metrics':copy.deepcopy(metrics),'truncated':False}
            else: obs={'context':ctx,'value':{'visible':True,'width':12,'filter_intersection':['90 days','30 days']}}
            capture['cases'][c['id']]=obs
        captures.append(capture)
    plan={'schema_version':1,'kind':'migration_parity_plan','migration_scope':scope,
          'bindings':{k:'a'*64 for k in BINDINGS},
          'baseline_sha256':hash_json(captures[0]),'inventory':{'data_tiles':['orders'],
          'text_tiles':['note'] if scope=='full_dashboard' else [],'filter_ids':['period'] if scope=='full_dashboard' else []},
          'scenario_requirements':{'orders':['baseline']},'cases':cases,'review':{}}
    freeze(plan)
    return plan,*captures


def freeze(plan):
    plan['review']={'status':'approved','reference':'synthetic-analyst-review',
                    'plan_sha256':hash_json({k:v for k,v in plan.items() if k!='review'})}


class ParityTests(unittest.TestCase):
    def test_consistency_is_not_authenticated_native_evidence(self):
        result=parity.evaluate(*fixture('full_dashboard'))
        self.assertEqual(result['status'],'locally_consistent')
        self.assertFalse(result['native_verified']);self.assertFalse(result['evidence_authenticated']);self.assertFalse(result['acceptance_ready'])

    def test_equal_total_different_population_fails(self):
        p,b,w,o=fixture();o['cases']['orders-baseline']['rows'][1]['day']='2026-03-10'
        self.assertEqual(parity.evaluate(p,b,w,o)['status'],'failed')

    def test_duplicate_null_order_truncation_and_invariant_changes_fail(self):
        mutations=[lambda x:x['rows'].append(copy.deepcopy(x['rows'][1])),
                   lambda x:x['rows'][0].update(revenue=0),lambda x:x['rows'].reverse(),
                   lambda x:x.update(truncated=True),lambda x:x['metrics'].update(join_output_rows=3),
                   lambda x:x['metrics'].update(tenant_violations=1),lambda x:x['metrics'].update(orphan_keys=1)]
        for mutate in mutations:
            p,b,w,o=fixture();mutate(o['cases']['orders-baseline'])
            self.assertEqual(parity.evaluate(p,b,w,o)['status'],'failed')

    def test_all_context_dimensions_and_query_hash_are_bound(self):
        for key in ('snapshot_sha256','timezone','parameters_sha256','persona_sha256','query_sha256'):
            p,b,w,o=fixture();o['cases']['orders-baseline']['context'][key]='UTC' if key=='timezone' else 'f'*64
            self.assertEqual(parity.evaluate(p,b,w,o)['status'],'failed')

    def test_missing_target_pending_and_own_baseline_rejected(self):
        p,b,w,o=fixture();self.assertEqual(parity.evaluate(p,b)['status'],'pending')
        b['independent_of_candidate']=False;p['baseline_sha256']=hash_json(b);freeze(p)
        with self.assertRaises(ValueError):parity.evaluate(p,b,w,o)

    def test_expected_plan_and_baseline_immutable(self):
        p,b,w,o=fixture();p['cases'][0]['ordered']=False
        with self.assertRaises(ValueError):parity.evaluate(p,b,w,o)
        p,b,w,o=fixture();b['cases']['orders-baseline']['rows'][1]['revenue']=1
        with self.assertRaises(ValueError):parity.evaluate(p,b,w,o)

    def test_tolerance_only_from_frozen_reviewed_plan(self):
        p,b,w,o=fixture();o['cases']['orders-baseline']['rows'][1]['revenue']=100.001
        self.assertEqual(parity.evaluate(p,b,w,o)['status'],'failed')
        p['cases'][0]['tolerances']={'revenue':{'absolute':0.01,'relative':0,'reason':'Synthetic rounding convention'}};freeze(p)
        self.assertEqual(parity.evaluate(p,b,w,o)['status'],'locally_consistent')
        o['cases']['orders-baseline']['rows'][1]['revenue']=101
        self.assertEqual(parity.evaluate(p,b,w,o)['status'],'failed')

    def test_ui_or_filter_changes_not_hidden_by_equal_data(self):
        p,b,w,o=fixture('full_dashboard');o['cases']['period-rendered']['value']['filter_intersection']=['90 days']
        self.assertEqual(parity.evaluate(p,b,w,o)['status'],'failed')
        p,b,w,o=fixture('full_dashboard');del o['cases']['note-rendered']
        self.assertEqual(parity.evaluate(p,b,w,o)['status'],'pending')

    def test_selected_tile_and_scenario_denominators_enforced(self):
        p,b,w,o=fixture();p['inventory']['data_tiles'].append('missing');freeze(p)
        with self.assertRaises(ValueError):parity.evaluate(p,b,w,o)
        p,b,w,o=fixture();p['scenario_requirements']['orders'].append('date_boundary');freeze(p)
        with self.assertRaises(ValueError):parity.evaluate(p,b,w,o)

    def test_sensitive_row_values_never_emitted(self):
        p,b,w,o=fixture()
        o['cases']['orders-baseline']['rows'][0]['day']='SYNTHETIC_PHI_CANARY'
        result=parity.evaluate(p,b,w,o)
        self.assertNotIn('SYNTHETIC_PHI_CANARY',str(result));self.assertEqual(result['status'],'failed')

    def test_model_only_does_not_invent_omni_requirement(self):
        p,b,w,o=fixture('model_only')
        self.assertEqual(parity.evaluate(p,b,w)['status'],'locally_consistent')


if __name__=='__main__':unittest.main()
