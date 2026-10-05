"""Real local review export with synthetic plans; no execution or approval."""
import base64
from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import deployment_review as review_export
import deployment_workflow as deployment
import guided_workflow as workflow
from test_guided_workflow import collector
from disclosure_fixtures import synthetic_disclosure


class DeploymentReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source';self.source.mkdir()
        (self.source / 'orders.csv').write_text('id\n1\n')
        self.catalogue = self.root / 'catalogue.json';self.catalogue.write_text('{"objects":[{"name":"orders"}]}')
        self.run = self.root / 'engagement'
        patcher = patch.object(workflow, '_assess_repository', collector);patcher.start();self.addCleanup(patcher.stop)
        state = workflow.start_engagement(self.source, self.run,
            {'engagement_type':'new_model', 'priority_domain':'Orders', 'framework':'native_sql', 'warehouse':'snowflake',
             'semantic_target':'omni', 'migration_scope':'model_semantic', 'input_handling':'pre_sanitized',
             'deliverables':['implementation','documentation']}, catalogue=self.catalogue)
        self.candidate = self.root / 'candidate';self.candidate.mkdir()
        (self.candidate / 'model.sql').write_text('select 1 as id\n')
        (self.candidate / 'guide.md').write_text('Synthetic implementation guide.\n')
        (self.candidate / 'private.csv').write_text('DO_NOT_COPY_UNSELECTED_ROWS')
        self.review_path = self.root / 'original-review.json'
        review = {'schema_version':1, 'title':'Synthetic release', 'source_fingerprint':portal.source_fingerprint(state),
                  'context_sha256':portal.context_fingerprint(state), 'target':{'framework':'native_sql','warehouse':'snowflake'},
                  'models':[], 'relationships':[], 'validation':[],
                  'private_state':{'path':str(self.root),'note':'DO_NOT_COPY_UNKNOWN_REVIEW_FIELDS'},
                  'artifacts':[{'id':name,'path':name,'category':category,'audiences':['engineer'],
                                'sha256':hashlib.sha256((self.candidate/name).read_bytes()).hexdigest()}
                               for name,category in [('model.sql','implementation'),('guide.md','documentation'),('private.csv','sample_data')]]}
        review['disclosure'] = synthetic_disclosure([a['id'] for a in review['artifacts']])
        review['disclosure']['generated_evidence'] = {label:copy.deepcopy(review['disclosure']['presentation'])
            for label in ('plan','receipt','lint-manifest','lint-target','lint-configuration','lint-findings','lint-guide','quality')}
        self.review_path.write_text(json.dumps(review))
        state = workflow.record_handoff(self.run,self.review_path,self.candidate,audience='engineer')
        self.original_handoff = copy.deepcopy(next(e for e in state['evidence'] if e['kind']=='prepared_handoff'))
        self.original_review_bytes = self.review_path.read_bytes()
        self.policy_path = self.root / 'runner-policy.json'
        self.policy = {'schema_version':1,'kind':'deployment_runner_policy','runner_id':'synthetic','mode':'simulation',
            'allowed_actions':['publish_pr','deploy_development','promote'],
            'destinations':{'dev':{'adapter':'snowflake_sql','framework':'native_sql','warehouse':'snowflake',
                'environment':'development','namespace':{'database':'TEST_DB','schema':'GOLD'},'identity':'service_principal',
                'runtime_version':'fixture-1','base_url':'https://private-host.example.snowflakecomputing.com',
                'role':'MODELER','compute':'TEST_WH','auth_env':{'token':'PRIVATE_RUNNER_TOKEN_REFERENCE'}}},
            'issuers':{'test':{'public_key':base64.b64encode(b'p'*32).decode(),'purposes':['deployment_approval'], 'actors':['fixture']}},
            'journal_key_env':'TEST_DEPLOYMENT_REVIEW_JOURNAL','state_root':str(self.root/'private-runner-state')}
        self.policy_path.write_text(json.dumps(self.policy));self.policy_path.chmod(0o600)
        self.plan_path=self.root/'private-plan.json'
        self.plan=deployment.create_plan(self.run,{'schema_version':1,'action':'deploy_development','destination_id':'dev',
            'release_id':'release-fixture','commit_sha':'a'*40,'artifacts':[{'path':'model.sql','role':'model_sql'}],
            'impact':['Creates the reviewed development model.'],'recovery':['Restore the pinned prior model version.'],
            'required_checks':sorted(deployment.REQUIRED_CHECKS|{'semantic'})},self.policy_path,self.plan_path)
        self.output=self.root/'review-export'

    def export(self, **kwargs):
        return review_export.export_review(self.plan_path,self.policy_path,self.output,**kwargs)

    def payload(self):
        page=(self.output/'START_HERE.html').read_text()
        return json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])

    def test_export_is_separate_portable_non_authority_and_context_bound(self):
        with patch.object(deployment,'submit',side_effect=AssertionError('no submit')), patch.object(deployment,'observe',side_effect=AssertionError('no remote polling')):
            result=self.export()
        payload=self.payload();projection=payload['deployment']
        self.assertEqual(projection['plan']['sha256'],self.plan['plan_sha256'])
        self.assertEqual(projection['target']['semantic_target'],'omni')
        self.assertEqual(projection['plan']['files'][0]['version'],'a'*40)
        self.assertEqual(projection['plan']['files'][0]['operation'],'model_sql')
        self.assertEqual(projection['handoff']['manifest_sha256'],self.plan['bindings']['handoff_manifest_sha256'])
        self.assertEqual(portal.verify_delivery(result['package'])['context_sha256'],self.plan['bindings']['context_sha256'])
        self.assertEqual(self.review_path.read_bytes(),self.original_review_bytes)
        state=workflow.load_engagement(self.run)
        self.assertEqual([e for e in state['evidence'] if e['kind']=='prepared_handoff'],[self.original_handoff])
        self.assertNotIn('deployment_review',state)
        self.assertEqual((self.output/'artifacts/model.sql').read_bytes(),(self.candidate/'model.sql').read_bytes())
        self.assertFalse((self.output/'artifacts/private.csv').exists())
        self.assertFalse((self.output/'state.json').exists())
        self.assertIn('No approval or execution',result['authority'])
        with zipfile.ZipFile(result['package']) as z:
            self.assertEqual(z.read('START_HERE.html'),(self.output/'START_HERE.html').read_bytes())
            self.assertIn('03_Validation/deployment/deployment-plan-review.json',z.namelist())
            contents=b'\n'.join(z.read(name) for name in z.namelist())
        for private in [str(self.root).encode(),b'private-host.example',b'PRIVATE_RUNNER_TOKEN_REFERENCE',b'DO_NOT_COPY']:
            self.assertNotIn(private,contents)
        extended=json.loads((self.output/'review.json').read_text())
        self.assertNotIn('private_state',extended)
        self.assertNotIn('private.csv',[a['path'] for a in extended['artifacts']])

    def sealed_record(self, **changes):
        record={'schema_version':1,'kind':'deployment_execution','operation_id':'d'*32,'plan_sha256':self.plan['plan_sha256'],
                'target_sha256':deployment.digest(self.plan['target']),'policy_sha256':self.plan['policy_sha256'],
                'mode':'simulation','state':'verification_pending','operations':[],
                'snapshot':str(self.root/'PRIVATE_SNAPSHOT'),'approval':{'private':'DO_NOT_COPY_SIGNED_AUTHORITY'}}
        record.update(changes)
        root=deployment._root(self.policy)
        # Deliberately malformed authenticated fixture journals exercise export
        # validation. Production transitions now refuse to create these records.
        record['history'] = [{'sequence': 1, 'event': 'synthetic_fixture'}]
        sealed = deployment._seal(record, self.policy)
        deployment._write(root/'operations'/record['operation_id']/'state.json', sealed)
        deployment._write(root/'active.json', deployment._seal({
            'operation_id': record['operation_id'], 'state': record['state'],
            'revision': 1, 'record_sha256': deployment.digest(sealed)}, self.policy))
        locator=self.root/'receipt-locator.json'
        locator.write_text(json.dumps({'operation_id':record['operation_id'],'state':'FAKE_DEPLOYED','password':'DO_NOT_COPY_LOCATOR'}))
        return locator,root/'operations'/record['operation_id']/'state.json'

    def test_receipt_uses_authenticated_current_status_not_supplied_claims(self):
        with patch.dict(os.environ,{'TEST_DEPLOYMENT_REVIEW_JOURNAL':'j'*40}):
            locator,_=self.sealed_record()
            self.export(receipt=locator)
        projection=self.payload()['deployment']
        self.assertEqual(projection['receipts'][0]['status'],'verification_pending')
        self.assertEqual(projection['receipts'][0]['scope'],'simulation')
        self.assertEqual(projection['plan']['sha256'],self.plan['plan_sha256'])
        self.assertFalse(any(choice['available'] for choice in projection['choices']))
        self.assertIn('acceptance',projection['next_action'].lower())
        with zipfile.ZipFile(self.output/'deployment-review.zip') as z:
            self.assertIn('03_Validation/deployment/deployment-receipt-review.json',z.namelist())
            body=b'\n'.join(z.read(name) for name in z.namelist())
        for value in [b'FAKE_DEPLOYED',b'DO_NOT_COPY',b'PRIVATE_SNAPSHOT',b'journal_hmac']:
            self.assertNotIn(value,body)

    def test_forged_or_other_plan_receipt_is_rejected(self):
        with patch.dict(os.environ,{'TEST_DEPLOYMENT_REVIEW_JOURNAL':'j'*40}):
            locator,path=self.sealed_record(plan_sha256='b'*64)
            with self.assertRaisesRegex(ValueError,'different deployment plan'):self.export(receipt=locator)
            body=json.loads(path.read_text());body['state']='deployed_verified';path.write_text(json.dumps(body))
            with self.assertRaisesRegex(ValueError,'journal integrity'):self.export(receipt=locator)
        self.assertFalse(self.output.exists())

    def test_receipt_target_policy_and_mode_must_match_exact_plan(self):
        with patch.dict(os.environ,{'TEST_DEPLOYMENT_REVIEW_JOURNAL':'j'*40}):
            for field,value in [('target_sha256','c'*64),('policy_sha256','c'*64),('mode','live')]:
                with self.subTest(field=field):
                    locator,_=self.sealed_record(**{field:value,'operation_id':hashlib.sha256(field.encode()).hexdigest()[:32]})
                    with self.assertRaisesRegex(ValueError,'target, policy or mode'):self.export(receipt=locator)
        self.assertFalse(self.output.exists())

    def test_artifact_source_policy_and_plan_drift_block_before_output(self):
        for kind in ('artifact','source','policy','plan'):
            with self.subTest(kind=kind):
                path={'artifact':self.candidate/'model.sql','source':self.source/'orders.csv','policy':self.policy_path,'plan':self.plan_path}[kind]
                original=path.read_bytes()
                path.write_bytes(original+b'\n' if kind!='plan' else original.replace(b'release-fixture',b'release-changed'))
                if kind=='policy':
                    changed=json.loads(original);changed['runner_id']='changed';path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):self.export()
                self.assertFalse(self.output.exists());path.write_bytes(original)
                # Fresh test case state is required after genuine source drift.
                if kind in ('artifact','source'):
                    state=workflow.resume_engagement(self.run)
                    if state['status']!='handoff_prepared':
                        workflow.record_handoff(self.run,self.review_path,self.candidate,audience='engineer')

    def test_existing_or_protected_output_is_never_overwritten(self):
        self.output.mkdir();(self.output/'keep.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError,'new output directory'):self.export()
        self.assertEqual((self.output/'keep.txt').read_text(),'keep')
        with self.assertRaisesRegex(ValueError,'protected'):
            review_export.export_review(self.plan_path,self.policy_path,self.candidate/'new-export')

    def test_internal_paths_in_curated_text_are_rejected_without_rewriting(self):
        changed=copy.deepcopy(self.plan);changed['impact']=[str(self.candidate)+'/model.sql']
        changed['plan_sha256']=deployment.envelope_digest(changed,'plan_sha256')
        self.plan_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'internal path'):self.export()
        self.assertFalse(self.output.exists())

    def test_cli_uses_installed_policy_and_returns_actionable_missing_policy(self):
        error=io.StringIO()
        with patch.dict(os.environ,{},clear=True),redirect_stderr(error):
            self.assertEqual(review_export.main(['--plan',str(self.plan_path),'--output',str(self.output)]),2)
        self.assertIn('DMA_RUNNER_POLICY',error.getvalue())
        output=io.StringIO()
        with patch.dict(os.environ,{'DMA_RUNNER_POLICY':str(self.policy_path)}),redirect_stdout(output):
            self.assertEqual(review_export.main(['--plan',str(self.plan_path),'--output',str(self.output)]),0)
        self.assertEqual(json.loads(output.getvalue())['status'],'deployment_review_exported')


if __name__=='__main__':
    unittest.main()
