"""Mocked official response shapes and real local signing; no live qualification."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import migration_collectors as collectors
import omni_native as native
from ae_common import hash_json
import test_omni_native_independent as fixtures


class BigQueryRemote:
    def __init__(self):
        self.calls=[]
        self.payload={'jobComplete':True,'totalRows':'1','totalBytesBilled':'100',
                      'schema':{'fields':[{'name':'total','type':'INTEGER'}]},'rows':[{'f':[{'v':'7'}]}]}
    def query(self,project,body):
        self.calls.append((project,copy.deepcopy(body)))
        return json.dumps(self.payload).encode()


@unittest.skipUnless(fixtures.RUNTIME,'Optional SQL/crypto dependencies required')
class MigrationCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.candidate=self.root/'candidate';self.candidate.mkdir()
        self.key=fixtures.Ed25519PrivateKey.generate()
        public=self.key.public_key().public_bytes(fixtures.Encoding.Raw,fixtures.PublicFormat.Raw)
        self.target={'project_id':'fixture-project','location':'US','principal_id':'synthetic-service','environment':'development'}
        self.policy={'schema_version':1,'kind':'deployment_runner_policy','runner_id':'parity-test','mode':'simulation',
                     'allowed_actions':['deploy_development'],'destinations':{'dev':self.target},'state_root':str(self.root/'private-state'),
                     'issuers':{'test':{'public_key':base64.b64encode(public).decode(),'actors':['reviewer'],'purposes':['deployment_approval']}},
                     'max_attestation_age_seconds':3600,'revoked_ids':[]}
        self.policy_path=self.root/'policy.json';self.save_policy()
        self.bq={'schema_version':1,'kind':'migration_bigquery_request','run_id':'bq-test','destination_id':'dev','target':self.target,
                 'sql':'SELECT SUM(amount) AS total FROM `fixture-project.raw.orders`',
                 'allowed_tables':['fixture-project.raw.orders'],'maximum_bytes_billed':1000,'max_rows':100,'timeout_ms':1000}
        self.remote=BigQueryRemote()
        self.network=patch('socket.socket.connect',side_effect=AssertionError('Unexpected network'));self.network.start();self.addCleanup(self.network.stop)

    def save_policy(self):
        self.policy_path.write_text(json.dumps(self.policy));self.policy_path.chmod(0o600)

    def sign(self,bindings,preflight):
        now=datetime.now(timezone.utc)
        payload={'schema_version':1,'kind':'deployment_attestation','purpose':'deployment_approval','mode':'simulation',
                 'issuer':'test','actor':'reviewer','id':'test-approval','review_reference':'synthetic-review',
                 'issued_at':(now-timedelta(minutes=1)).isoformat(),'expires_at':(now+timedelta(minutes=5)).isoformat(),
                 'bindings':bindings,'claims':{'preflight':preflight}}
        return {'payload':payload,'signature':base64.b64encode(self.key.sign(fixtures.canonical(payload))).decode()}

    def approval(self):
        preflight={k:True for k in ('principal_namespace_verified','read_only_query','synthetic_data_only','isolated_destination','cost_limit_verified')}
        preflight['target_sha256']=hash_json(self.target)
        return self.sign(collectors.bigquery_bindings(self.bq,hash_json(self.policy)),preflight)

    def run_bq(self,approval=None):
        return collectors.collect_bigquery(self.bq,policy_path=self.policy_path,candidate_root=self.candidate,approval=approval,transport=self.remote)

    def omni(self):
        target={'instance_url':'https://synthetic-native.omniapp.co','model_id':fixtures.uid(1),'branch_id':fixtures.uid(2),
                'connection_id':fixtures.uid(3),'environment_connection_id':fixtures.uid(3),'principal_id':fixtures.uid(5),'environment':'development'}
        remote=fixtures.Remote(target,fixtures.candidate())
        remote.query_reply=native.Response(200,b'[{"fleet.journeys":7}]','application/json')
        self.policy['destinations']['dev']=target;self.save_policy()
        request={'schema_version':1,'kind':'omni_native_request','run_id':'omni-test','operation':'query','destination_id':'dev',
                 'target':target,'files':fixtures.candidate(),'context':fixtures.context(),'warning_policy':'fail',
                 'expected_remote':remote.expected(),'commit_message':'Synthetic query test','query_mode':'execute','timezone':'UTC',
                 'query':{'modelId':target['model_id'],'table':'fleet','fields':['fleet.journeys'],'limit':10}}
        preflight={k:True for k in ('principal_namespace_verified','permissions_verified','existing_destination_approved','synthetic_data_only','isolated_destination','branch_exclusive')}
        preflight.update(target_sha256=hash_json(target),audience_sha256='c'*64,access_policy_sha256='d'*64,evidence_sha256='e'*64,
                         evidence_reference='synthetic-access',effective_timezone='UTC')
        approval=self.sign(native.request_bindings(request,hash_json(self.policy)),preflight)
        return request,remote,approval

    def test_bigquery_exact_signed_bounded_body_and_no_raw_summary(self):
        result=self.run_bq(self.approval())
        self.assertEqual(result['status'],'collected',result)
        self.assertEqual(result['execution_mode'],'simulation');self.assertFalse(result['native_verified'])
        body=self.remote.calls[0][1]
        self.assertEqual(body['maximumBytesBilled'],'1000');self.assertEqual(body['maxResults'],100)
        self.assertEqual(body['timeoutMs'],1000);self.assertEqual(body['jobTimeoutMs'],'1000');self.assertFalse(body['useLegacySql'])
        self.assertNotIn('payload',collectors.public_summary(result));self.assertNotIn('query',collectors.public_summary(result))
        journal=next((self.root/'private-state').glob('*.json'))
        self.assertEqual(journal.stat().st_mode & 0o777,0o600);self.assertNotIn('rows',json.loads(journal.read_text()))
        again=self.run_bq(self.approval());self.assertEqual(again['status'],'blocked');self.assertEqual(len(self.remote.calls),1)

    def test_unsigned_stale_or_wrong_destination_never_submits(self):
        self.assertEqual(self.run_bq()['status'],'blocked');self.assertFalse(self.remote.calls)
        approval=self.approval();self.bq['maximum_bytes_billed']=999
        self.assertEqual(self.run_bq(approval)['status'],'blocked');self.assertFalse(self.remote.calls)
        self.bq['destination_id']='unknown'
        self.assertEqual(self.run_bq(self.approval())['status'],'blocked');self.assertFalse(self.remote.calls)

    def test_bigquery_sql_readonly_scope_and_bounds_fail_before_transport(self):
        for sql in ('DELETE FROM `fixture-project.raw.orders` WHERE TRUE',
                    'SELECT * FROM `fixture-project.raw.outside`',
                    "SELECT * FROM EXTERNAL_QUERY('remote','delete from x')",'SELECT remote.udf(1)',
                    'SELECT 1; SELECT 2','SELECT * FROM orders'):
            with self.subTest(sql=sql):
                self.bq['sql']=sql
                with self.assertRaises(ValueError):collectors.validate_bigquery_request(self.bq)
        self.assertFalse(self.remote.calls)

    def test_bigquery_pending_and_pagination_never_pass_or_retry(self):
        for index,payload in enumerate(({'jobComplete':False,'jobReference':{'jobId':'fixture'}},
                                      dict(self.remote.payload,pageToken='more',totalRows='2'))):
            self.bq['run_id']='bq-'+str(index);self.remote.payload=payload
            result=self.run_bq(self.approval());self.assertIn(result['status'],('pending','unsupported'))
        self.assertEqual(len(self.remote.calls),2)

    def test_omni_reuses_authority_snapshots_and_private_json_capture(self):
        request,remote,approval=self.omni()
        result=collectors.collect_omni(request,policy_path=self.policy_path,candidate_root=self.candidate,approval=approval,transport=remote)
        self.assertEqual(result['status'],'collected',result);self.assertFalse(result['native_verified'])
        self.assertEqual(result['payload'],[{'fleet.journeys':7}]);self.assertEqual(result['remote_before'],result['remote_after'])
        calls=[c for c in remote.calls if c['method']=='POST']
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['path'],'/api/v1/query/run')
        self.assertEqual(calls[0]['body'],collectors.omni_body(request));self.assertFalse(result['evidence_authenticated'])
        again=collectors.collect_omni(request,policy_path=self.policy_path,candidate_root=self.candidate,approval=approval,transport=remote)
        self.assertEqual(again['status'],'blocked');self.assertEqual(sum(c['method']=='POST' for c in remote.calls),1)

    def test_omni_missing_authority_and_snapshot_drift_discard_rows(self):
        request,remote,approval=self.omni()
        blocked=collectors.collect_omni(request,policy_path=self.policy_path,candidate_root=self.candidate,transport=remote)
        self.assertEqual(blocked['status'],'blocked');self.assertFalse(remote.calls)
        original=remote.request
        def changed(method,path,params=None,body=None):
            result=original(method,path,params=params,body=body)
            if path=='/api/v1/query/run':remote.schema_generation+=1
            return result
        remote.request=changed
        result=collectors.collect_omni(request,policy_path=self.policy_path,candidate_root=self.candidate,approval=approval,transport=remote)
        self.assertEqual(result['status'],'blocked');self.assertNotIn('payload',result)

    def test_omni_limit_reached_is_not_a_complete_comparison(self):
        request,remote,approval=self.omni()
        remote.query_reply=native.Response(200,json.dumps([{'fleet.journeys':i} for i in range(10)]).encode(),'application/json')
        result=collectors.collect_omni(request,policy_path=self.policy_path,candidate_root=self.candidate,approval=approval,transport=remote)
        self.assertEqual(result['status'],'unsupported');self.assertTrue(result['truncated'])

    def test_actual_bigquery_http_adapter_uses_fixed_tls_endpoint_and_bounds(self):
        class Response(io.BytesIO): status=200
        with patch.dict(os.environ,{'BIGQUERY_ACCESS_TOKEN':'synthetic-token'}):client=collectors.HTTPSBigQueryTransport(timeout=2)
        with patch.object(client.opener,'open',return_value=Response(b'{"jobComplete":false}')) as opened:
            raw=client.query('fixture-project',collectors.bigquery_body(self.bq))
        call=opened.call_args
        self.assertEqual(call.args[0].full_url,'https://bigquery.googleapis.com/bigquery/v2/projects/fixture-project/queries')
        self.assertEqual(call.kwargs['timeout'],2);self.assertEqual(json.loads(raw),{'jobComplete':False})


if __name__=='__main__':unittest.main()
