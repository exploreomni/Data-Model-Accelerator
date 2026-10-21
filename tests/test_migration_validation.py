"""Synthetic export-to-scorecard workflow; no source execution or network."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import migration_validation as workflow
from ae_common import hash_json
import test_migration_parity as fixtures


def fixture(scope='model_semantic', draft=False):
    plan,*captures=fixtures.fixture(scope)
    queries={lane:{'text':'independent '+lane+' query','parameters':{'period':'baseline'}} for lane in ('source','warehouse','omni')}
    for c in plan['cases']:
        if c['kind']=='data':
            c['queries']={lane:hash_json(query) for lane,query in queries.items()}
    requests=[]
    for capture in captures:
        request={k:copy.deepcopy(capture[k]) for k in ('schema_version','origin','provenance','independent_of_candidate','reference')}
        request['cases']=[]
        for c in plan['cases']:
            obs=copy.deepcopy(capture['cases'][c['id']])
            item={'case_id':c['id'],'format':'json_rows' if c['kind']=='data' else 'interaction',
                  'payload':obs.get('rows',obs.get('value')),'context':obs['context'],
                  'reference':'synthetic-export','captured_at':'2026-10-20T12:00:00+00:00','gaps':[]}
            if c['kind']=='data':
                item['context']['query_sha256']=c['queries'][capture['origin']]
                item.update(query=queries[capture['origin']],columns=c['columns'],metrics=obs['metrics'],metrics_reference='independent-fixture-audit',truncated=False)
                capture['cases'][c['id']]['context']=item['context']
            request['cases'].append(item)
        requests.append(request)
    plan['baseline_sha256']=hash_json(captures[0]);fixtures.freeze(plan)
    if draft: plan['review']={'status':'pending'};plan['baseline_sha256']='0'*64
    rows=[{'subject_kind':'tile' if x not in plan['inventory']['filter_ids'] else 'filter','subject_id':x,
           'dashboard_id':'operations','dashboard_label':'Operations','source_label':x.title(),
           'model_ids':['fact_orders'] if x=='orders' else [],'topic_ids':['orders'] if x=='orders' else [],'status':'mapped','gaps':[]}
          for x in plan['inventory']['data_tiles']+plan['inventory']['text_tiles']+plan['inventory']['filter_ids']]
    document=workflow.prepare({'schema_version':1,'plan':plan,'crosswalk':rows})
    if not draft:
        document=workflow.freeze(document,workflow.import_capture(document,requests[0]),'Explicit synthetic review')
    return document, requests


class MigrationValidationTests(unittest.TestCase):
    def test_draft_capture_freeze_and_three_lane_scorecard(self):
        document,requests=fixture('full_dashboard',True)
        source,warehouse,omni=[workflow.import_capture(document,r) for r in requests]
        self.assertEqual(workflow.evaluate(document,source)['status'],'pending')
        frozen=workflow.freeze(document,source,'Explicit synthetic analyst review')
        report=workflow.evaluate(frozen,source,warehouse,omni,current_bindings=frozen['plan']['bindings'])
        self.assertEqual(report['counts'],{'pass':3,'fail':0,'pending':0,'unsupported':0})
        for key in ('native_verified','evidence_authenticated','acceptance_ready'): self.assertFalse(report[key])
        self.assertNotIn('revenue',json.dumps(report)); self.assertIn('Operations',workflow.render_markdown(report))

    def test_deliberate_mismatch_and_stale_binding(self):
        document,requests=fixture()
        requests[2]['cases'][0]['payload'][1]['revenue']=99
        captures=[workflow.import_capture(document,r) for r in requests]
        self.assertEqual(workflow.evaluate(document,*captures,current_bindings=document['plan']['bindings'])['status'],'fail')
        current=dict(document['plan']['bindings'],candidate='f'*64)
        result=workflow.evaluate(document,*captures,current_bindings=current)
        self.assertTrue(result['stale']); self.assertEqual(result['status'],'fail')

    def test_own_oracle_and_tampered_capture_rejected(self):
        document,requests=fixture();requests[0]['independent_of_candidate']=False
        with self.assertRaises(ValueError):workflow.import_capture(document,requests[0])
        document,requests=fixture();capture=workflow.import_capture(document,requests[0])
        capture['capture']['cases']['orders-baseline']['rows'][1]['revenue']=10
        with self.assertRaises(ValueError):workflow.evaluate(document,capture)

    def test_unsupported_python_r_filter_evidence_stays_visible(self):
        document,requests=fixture()
        requests[0]['cases'][0]['gaps']=[{'code':k,'status':'unsupported','reference':'export-cannot-establish-runtime'} for k in ('python.runtime','r.runtime','filters.effective')]
        captures=[workflow.import_capture(document,r) for r in requests]
        document=workflow.freeze(document,captures[0],'Review acknowledges remaining runtime gaps')
        result=workflow.evaluate(document,*captures,current_bindings=document['plan']['bindings'])
        self.assertEqual(result['status'],'unsupported')
        self.assertIn('python.runtime',workflow.render_markdown(result))

    def test_periscope_csv_preserves_null_and_declared_column_rename(self):
        document,requests=fixture();item=requests[0]['cases'][0]
        item.update(format='periscope_csv',payload='Date,Amount\n2026-03-08,\\N\n2026-03-09,100\n',null_token='\\N',column_map={'Date':'day','Amount':'revenue'})
        result=workflow.import_capture(document,requests[0])
        self.assertEqual(result['capture']['cases']['orders-baseline']['rows'][0]['revenue'],None)
        self.assertEqual(result['capture']['cases']['orders-baseline']['rows'][1]['revenue'],100)
        item['payload']='Date,Date\n2026-03-08,100\n'
        with self.assertRaises(ValueError):workflow.import_capture(document,requests[0])

    def test_exact_context_queries_schema_truncation_and_bounds(self):
        for mutation in (
            lambda i:i['context'].update(timezone='UTC'), lambda i:i['query'].update(text='changed'),
            lambda i:i.update(columns={'wrong':'number'}),lambda i:i.update(truncated=True),
            lambda i:i.update(payload=[{'day':'2026-03-09','revenue':1}]*1001)):
            document,requests=fixture();mutation(requests[1]['cases'][0])
            with self.assertRaises(ValueError):workflow.import_capture(document,requests[1])

    def test_bigquery_response_full_schema_and_precision(self):
        document,requests=fixture();item=requests[1]['cases'][0]
        response={'jobComplete':True,'totalRows':'2','schema':{'fields':[{'name':'day','type':'DATE'},{'name':'revenue','type':'NUMERIC'}]},
                  'rows':[{'f':[{'v':'2026-03-08'},{'v':None}]},{'f':[{'v':'2026-03-09'},{'v':'100'}]}]}
        item.update(format='bigquery_query_response',payload=response)
        self.assertEqual(workflow.import_capture(document,requests[1])['capture']['cases']['orders-baseline']['rows'][1]['revenue'],100)
        for patch in ({'pageToken':'more'},{'jobComplete':False},{'totalRows':'3'}):
            item['payload']=dict(response,**patch)
            with self.assertRaises(ValueError):workflow.import_capture(document,requests[1])
        with self.assertRaises(ValueError):workflow._number('0.123456789123456789123')

    def test_omni_json_fields_and_limit_cannot_fake_complete_result(self):
        document,requests=fixture();item=requests[2]['cases'][0]
        query={'query':{'fields':['orders.day','orders.revenue'],'limit':3},'resultType':'json','formatResults':False}
        document['plan']['cases'][0]['queries']['omni']=hash_json(query);fixtures.freeze(document['plan'])
        document=workflow.prepare({k:document[k] for k in ('schema_version','plan','crosswalk')})
        item.update(format='omni_json',query=query,request_limit=3,column_map={'orders.day':'day','orders.revenue':'revenue'},
                    payload=[{'orders.day':'2026-03-08','orders.revenue':None},{'orders.day':'2026-03-09','orders.revenue':100}])
        item['context']['query_sha256']=hash_json(query)
        workflow.import_capture(document,requests[2])
        item['payload'].append({'orders.day':'2026-03-10','orders.revenue':0})
        with self.assertRaises(ValueError):workflow.import_capture(document,requests[2])

    def test_frozen_baseline_includes_runtime_gap_provenance(self):
        document,requests=fixture()
        requests[0]['cases'][0]['gaps']=[{'code':'python.runtime','status':'unsupported','reference':'unexecuted-source'}]
        captures=[workflow.import_capture(document,r) for r in requests]
        document=workflow.freeze(document,captures[0],'Review acknowledges runtime gap')
        requests[0]['cases'][0]['gaps']=[]
        changed=workflow.import_capture(document,requests[0])
        result=workflow.evaluate(document,changed,*captures[1:],current_bindings=document['plan']['bindings'])
        self.assertEqual(result['status'],'fail')
        self.assertIn('frozen_baseline_document_changed',str(result))

    def test_existing_comparator_and_model_only_unchanged(self):
        self.assertEqual(fixtures.parity.evaluate(*fixtures.fixture())['status'],'locally_consistent')
        document,requests=fixture('model_only')
        captures=[workflow.import_capture(document,r) for r in requests[:2]]
        self.assertEqual(workflow.evaluate(document,*captures,current_bindings=document['plan']['bindings'])['status'],'pass')
        self.assertEqual(workflow.evaluate(document,*captures)['status'],'pending')

    def test_model_only_extra_ui_inventory_is_visible_but_not_required(self):
        document,requests=fixture('model_only')
        plan=copy.deepcopy(document['plan']);plan['inventory']['text_tiles']=['note'];fixtures.freeze(plan)
        crosswalk=copy.deepcopy(document['crosswalk'])
        crosswalk.append(dict(crosswalk[0],subject_id='note',source_label='Note',model_ids=[],topic_ids=[],status='pending'))
        document=workflow.prepare({'schema_version':1,'plan':plan,'crosswalk':crosswalk})
        captures=[workflow.import_capture(document,r) for r in requests[:2]]
        document=workflow.freeze(document,captures[0],'Model-only scope review')
        result=workflow.evaluate(document,*captures,current_bindings=plan['bindings'])
        self.assertEqual(result['status'],'pass')
        self.assertFalse(result['crosswalk'][1]['required'])

    def test_reload_rejects_contradictory_metrics_and_format_metadata(self):
        mutations=[
            lambda ev:ev['metrics'].update(join_output_rows=999),
            lambda ev:ev.update(metrics_reference=''),
            lambda ev:ev.update(format='periscope_csv'),
            lambda ev:ev.update(format='unsupported_export'),
            lambda ev:ev.update(column_map={'day':'day','revenue':'day'}),
            lambda ev:ev.pop('payload'),
        ]
        for mutate in mutations:
            document,requests=fixture()
            captures=[workflow.import_capture(document,r) for r in requests]
            changed=captures[1]
            mutate(changed['evidence']['orders-baseline'])
            changed['capture_document_sha256']=hash_json({k:v for k,v in changed.items() if k!='capture_document_sha256'})
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                workflow.evaluate(document,*captures,current_bindings=document['plan']['bindings'])

    def test_reload_rejects_row_limit_even_when_both_copies_and_hashes_match(self):
        document,requests=fixture();captures=[workflow.import_capture(document,r) for r in requests]
        changed=captures[1];ev=changed['evidence']['orders-baseline'];obs=changed['capture']['cases']['orders-baseline']
        rows=[{'day':'2026-03-09','revenue':i} for i in range(1001)]
        ev['payload']=rows;obs['rows']=copy.deepcopy(rows);ev['payload_sha256']=hash_json(rows)
        changed['capture_document_sha256']=hash_json({k:v for k,v in changed.items() if k!='capture_document_sha256'})
        with self.assertRaisesRegex(ValueError,'row_limit'):
            workflow.evaluate(document,*captures,current_bindings=document['plan']['bindings'])

    def test_reload_replays_omni_limit_and_exact_request_semantics(self):
        document,requests=fixture();item=requests[2]['cases'][0]
        query={'query':{'fields':['orders.day','orders.revenue'],'limit':3},'resultType':'json','formatResults':False}
        document['plan']['cases'][0]['queries']['omni']=hash_json(query);fixtures.freeze(document['plan'])
        document=workflow.prepare({k:document[k] for k in ('schema_version','plan','crosswalk')})
        item.update(format='omni_json',query=query,request_limit=3,column_map={'orders.day':'day','orders.revenue':'revenue'},
                    payload=[{'orders.day':'2026-03-08','orders.revenue':None},{'orders.day':'2026-03-09','orders.revenue':100}])
        item['context']['query_sha256']=hash_json(query)
        captures=[workflow.import_capture(document,r) for r in requests]
        document=workflow.freeze(document,captures[0],'Explicit synthetic review')
        for limit in (2,1001):
            changed=copy.deepcopy(captures[2]);changed['evidence']['orders-baseline']['request_limit']=limit
            changed['capture_document_sha256']=hash_json({k:v for k,v in changed.items() if k!='capture_document_sha256'})
            with self.assertRaises(ValueError):
                workflow.evaluate(document,*captures[:2],changed,current_bindings=document['plan']['bindings'])
        changed=copy.deepcopy(captures[2]);ev=changed['evidence']['orders-baseline']
        ev['payload'].append({'orders.day':'2026-03-10','orders.revenue':0})
        changed['capture']['cases']['orders-baseline']['rows'].append({'day':'2026-03-10','revenue':0})
        ev['payload_sha256']=hash_json(ev['payload'])
        changed['capture_document_sha256']=hash_json({k:v for k,v in changed.items() if k!='capture_document_sha256'})
        with self.assertRaisesRegex(ValueError,'omni_limit_reached'):
            workflow.evaluate(document,*captures[:2],changed,current_bindings=document['plan']['bindings'])

    def test_reload_replays_bigquery_completion_and_schema(self):
        document,requests=fixture();item=requests[1]['cases'][0]
        item.update(format='bigquery_query_response',payload={'jobComplete':True,'totalRows':'2',
            'schema':{'fields':[{'name':'day','type':'DATE'},{'name':'revenue','type':'NUMERIC'}]},
            'rows':[{'f':[{'v':'2026-03-08'},{'v':None}]},{'f':[{'v':'2026-03-09'},{'v':'100'}]}]})
        captures=[workflow.import_capture(document,r) for r in requests]
        for mutation in (lambda p:p.update(pageToken='more'),
                         lambda p:p['schema']['fields'][0].update(type='TIMESTAMP')):
            changed=copy.deepcopy(captures[1]);ev=changed['evidence']['orders-baseline'];mutation(ev['payload'])
            ev['payload_sha256']=hash_json(ev['payload'])
            changed['capture_document_sha256']=hash_json({k:v for k,v in changed.items() if k!='capture_document_sha256'})
            with self.assertRaises(ValueError):
                workflow.evaluate(document,captures[0],changed,captures[2],current_bindings=document['plan']['bindings'])

    def test_cli_private_rows_no_stdout_disclosure_and_no_overwrite(self):
        document,requests=fixture()
        requests[0]['cases'][0]['payload'][0]['day']='PRIVATE_ROW_CANARY'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();path=root/'workflow.json';path.write_text(json.dumps(document))
            request=root/'request.json';request.write_text(json.dumps(requests[0]))
            out=root/'output.json'
            command=[sys.executable,str(Path(workflow.__file__)),'capture','--workflow',str(path),'--request',str(request),'--output',str(out)]
            bad=subprocess.run(command,capture_output=True,text=True)
            self.assertNotIn('PRIVATE_ROW_CANARY',bad.stdout+bad.stderr);self.assertFalse(out.exists())
            requests[0]['cases'][0]['payload'][0]['day']='2026-03-08';request.write_text(json.dumps(requests[0]))
            done=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(done.returncode,0,done.stdout);self.assertEqual(out.stat().st_mode & 0o777,0o600)
            again=subprocess.run(command,capture_output=True,text=True);self.assertNotEqual(again.returncode,0)


if __name__=='__main__':unittest.main()
