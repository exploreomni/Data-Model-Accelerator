"""Signed simulation: completed dbt build -> separately reviewed native metadata.

Only native transport is replaced. Source and original handoff stay unchanged.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import test_deployment_workflow as fixtures
import deployment_workflow as deploy
from deployment_adapters import validate_target
from metadata_release import target_binding, candidate_binding, CHECKS
from metadata_contract import build_contract
from plan_warehouse_metadata import plan_metadata
from test_warehouse_metadata_plan import observation
from test_metadata_contract import dictionary, configuration


@unittest.skipUnless(fixtures.Ed25519PrivateKey, 'Optional deployment cryptography unavailable')
class MetadataReleaseTests(unittest.TestCase):
    make_plan = fixtures.DeploymentWorkflowTests.make_plan
    write_policy = fixtures.DeploymentWorkflowTests.write_policy
    approvals = fixtures.DeploymentWorkflowTests.approvals
    sign = fixtures.DeploymentWorkflowTests.sign

    def make_handoff(self, name, **kwargs):
        return fixtures.DeploymentWorkflowTests.make_handoff(self,name,
            extra_answers={'metadata_policy':configuration()['metadata_policy']},**kwargs)

    def setUp(self):
        fixtures.DeploymentWorkflowTests.setUp(self)
        self.policy['destinations']['dev']['physical_destination'] = 'snowflake:synthetic-org:fixture'
        self.policy['destinations']['metadata'] = {'adapter':'snowflake_sql', 'framework':'native_sql', 'warehouse':'snowflake',
            'environment':'development', 'namespace':{'database':'TEST_DB','schema':'GOLD'},
            'identity':'synthetic-service','runtime_version':'synthetic-1','base_url':'https://fixture.snowflakecomputing.com',
            'role':'FIXTURE_ROLE','compute':'FIXTURE_WH','auth_env':{'token':'DMA_TEST_SNOWFLAKE_TOKEN'},
            'physical_destination':'snowflake:synthetic-org:fixture'}
        self.write_policy()
        config = configuration(); target = validate_target(self.policy['destinations']['metadata'])
        config['target'] = target_binding('metadata',target)
        config['catalogue_sha256'] = hashlib.sha256(self.catalogue.read_bytes()).hexdigest()
        config['resources'][0]['relation'] = {'namespace':['TEST_DB','GOLD'],'name':'orders','kind':'table'}
        config['resources'][0]['columns']['customer_id'] = 'order_id'
        from metadata_release import configuration_template
        extra={'metadata/dictionary.json':('documentation',json.dumps(dictionary()).encode()),
               'metadata/configuration-template.json':('documentation',json.dumps(configuration_template(config)).encode())}
        self.run,self.candidate,self.review=self.make_handoff('reviewed-build',extra_contents=extra)
        self.parent_path = self.root/'parent-plan.json'
        self.parent_plan = deploy.create_plan(self.run,self.request,self.policy_path,self.parent_path)
        model, approval = self.approvals(self.parent_plan)
        self.parent = deploy.submit(self.parent_path,self.policy_path,model,approval,
                                    transport=fixtures.ScriptedTransport(fixtures.dbt_response()))
        config['candidate_sha256'] = candidate_binding(self.parent_plan)
        self.contract = build_contract(dictionary(),config)
        before = observation(self.contract); before['release_id'] = self.parent_plan['id']
        from metadata_observation import seal
        self.metadata = plan_metadata(self.contract,seal(before))
        contents = {'metadata/metadata-plan.json':('documentation',json.dumps(self.metadata).encode())}
        selected = [{'path':'metadata/metadata-plan.json','role':'documentation'}]
        for i, operation in enumerate(self.metadata['operations']):
            path = 'metadata/%03d.sql'%i
            contents[path] = ('implementation',operation['sql'].encode())
            selected.append({'path':path,'role':'model_sql'})
        self.child_run,self.child_root,self.child_review = self.make_handoff('metadata',extra_contents=contents)
        self.child_request = {**self.request,'destination_id':'metadata','release_id':'synthetic-metadata','artifacts':selected,
            'metadata_phase':{'plan_artifact':'metadata/metadata-plan.json','parent_operation_id':self.parent['operation_id'],'phase':'target_metadata'}}
        self.child_path = self.root/'metadata-deployment-plan.json'
        self.child = deploy.create_plan(self.child_run,self.child_request,self.policy_path,self.child_path)

    def child_approvals(self, **changes):
        preflight = {k:self.child['metadata_phase'][k] for k in ('metadata_plan_sha256','contract_sha256','before_sha256','parent_plan_sha256','candidate_sha256')}
        preflight.update(parent_operation_id=self.parent['operation_id'], physical_build_verified=True,
            full_build_scope_verified=True,permissions_verified=True,policy_effects_verified=True,
            exclusive_change_window=True,lease_reference='synthetic-only-exclusive-window',
            lease_expires_at=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())
        preflight.update(changes)
        return self.sign('model_signoff',deploy.model_bindings(self.child)), self.sign('deployment_approval',
            deploy.approval_bindings(self.child),claims={'metadata_preflight':preflight})

    @staticmethod
    def response(native_id='synthetic-statement'):
        return {'status_code':200,'body':{'code':'090001','sqlState':'00000','statementHandle':native_id}}

    def test_parent_build_then_signed_native_metadata_phase(self):
        self.assertTrue(CHECKS <= set(self.child['required_checks']))
        self.assertEqual(self.child['review_target']['framework'],'dbt')
        self.assertEqual(self.child['target']['framework'],'native_sql')
        model,approval = self.child_approvals()
        transport = fixtures.ScriptedTransport(self.response('one'),self.response('two'))
        result = deploy.submit(self.child_path,self.policy_path,model,approval,transport=transport)
        self.assertEqual(result['state'],'verification_pending')
        self.assertEqual(len(transport.calls),2)
        self.assertTrue(all('/api/v2/statements' in call['url'] for call in transport.calls))
        self.assertEqual([call['body']['statement'] for call in transport.calls],[o['sql'] for o in self.metadata['operations']])
        self.assertEqual(deploy.load_plan(self.parent_path),self.parent_plan)

    def test_plain_native_sidecar_cannot_bypass_reviewed_framework(self):
        request = copy.deepcopy(self.child_request); request.pop('metadata_phase')
        with self.assertRaisesRegex(ValueError,'reviewed framework'):
            deploy.create_plan(self.child_run,request,self.policy_path,self.root/'bad.json')

    def test_missing_metadata_preflight_refuses_before_transport(self):
        model,approval = self.approvals(self.child); transport = fixtures.ScriptedTransport()
        with self.assertRaisesRegex(ValueError,'preflight'):
            deploy.submit(self.child_path,self.policy_path,model,approval,transport=transport)
        self.assertEqual(transport.calls,[])

    def test_expired_lease_refuses_before_transport(self):
        model,approval = self.child_approvals(lease_expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        with self.assertRaisesRegex(ValueError,'change window'):
            deploy.submit(self.child_path,self.policy_path,model,approval,transport=fixtures.ScriptedTransport())

    def test_changed_parent_or_candidate_binding_cannot_be_approved(self):
        model,approval = self.child_approvals(candidate_sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'binding differs'):
            deploy.submit(self.child_path,self.policy_path,model,approval,transport=fixtures.ScriptedTransport())

    def test_partial_unknown_outcome_is_recorded_and_never_resubmitted(self):
        model,approval = self.child_approvals(); transport = fixtures.ScriptedTransport(self.response('one'),TimeoutError('synthetic'))
        result = deploy.submit(self.child_path,self.policy_path,model,approval,transport=transport)
        self.assertEqual(result['state'],'unknown_remote_state')
        self.assertEqual(result['operations'][0]['receipt']['state'],'succeeded')
        with self.assertRaisesRegex(ValueError,'active|already submitted'):
            deploy.submit(self.child_path,self.policy_path,model,approval,transport=fixtures.ScriptedTransport())
        self.assertEqual(len(transport.calls),2)

    def test_changed_sql_artifact_blocks_dispatch(self):
        (self.child_root/'metadata/000.sql').write_text('DROP TABLE sensitive;')
        model,approval = self.child_approvals()
        with self.assertRaises(ValueError):
            deploy.submit(self.child_path,self.policy_path,model,approval,transport=fixtures.ScriptedTransport())

    def test_parent_recovery_cannot_release_an_uncertain_child_lock(self):
        model,approval=self.child_approvals()
        child=deploy.submit(self.child_path,self.policy_path,model,approval,
                           transport=fixtures.ScriptedTransport(self.response('one'),TimeoutError('synthetic')))
        parent=deploy.status(self.policy_path,self.parent['operation_id'])
        attestation=self.sign('deployment_recovery',deploy.recovery_bindings(parent,self.parent_plan),
            issuer='validation-service',claims={'remote_quiescent':True,'recovery_verified':True,
                'evidence_sha256':'a'*64,'evidence_reference':'synthetic://parent-only'})
        with self.assertRaisesRegex(ValueError,'active operation'):
            deploy.recover(self.policy_path,parent['operation_id'],attestation)
        current=deploy._read_record(deploy._root(self.policy)/'active.json',self.policy)
        self.assertEqual(current['operation_id'],child['operation_id'])
        self.assertEqual(current['state'],'unknown_remote_state')
        self.assertEqual(deploy.status(self.policy_path,parent['operation_id']),parent)

    def test_parent_must_be_successfully_built(self):
        from metadata_release import bind_phase
        root = deploy._root(self.policy)
        parent = deploy._load_record(root,self.parent['operation_id'],self.policy)
        parent['state'] = 'failed'; deploy._save_record(root,parent,self.policy,'synthetic_failure')
        with self.assertRaisesRegex(ValueError,'Parent native build'):
            deploy._plan_policy(self.child,self.policy)

    def test_child_rejects_prebuild_baseline_and_amended_parent_dictionary(self):
        from metadata_release import bind_phase
        from metadata_observation import seal
        for defect,expected in (('stale','after the parent build'),('dictionary','reviewed v2 dictionary')):
            value=copy.deepcopy(self.contract['dictionary'])
            if defect=='dictionary':
                value['models'][0]['description']='Unreviewed replacement definition'
            contract=build_contract(value,self.contract['configuration'])
            before=observation(contract);before['release_id']=self.parent_plan['id']
            if defect=='stale':
                before['observed_at']='2000-01-01T00:00:00+00:00'
            metadata=plan_metadata(contract,seal(before))
            (self.child_root/'metadata/metadata-plan.json').write_text(json.dumps(metadata))
            artifacts=[{'path':'metadata/metadata-plan.json','role':'documentation'}]
            artifacts.extend({'path':'metadata/%03d.sql'%i,'role':'model_sql','content':op['sql'],'sha256':op['sha256']}
                             for i,op in enumerate(metadata['operations']))
            with self.assertRaisesRegex(ValueError,expected):
                bind_phase(self.child_request['metadata_phase'],artifact_root=self.child_root,artifacts=artifacts,
                    target=self.child['target'],destination_id='metadata',policy=self.policy,
                    commit_sha=self.child['commit_sha'],source_bindings=self.child['bindings']['source_bindings'],reviewed_framework='dbt')

    def test_physical_destination_binding_is_required_and_exact(self):
        from metadata_release import same_physical_destination
        original = self.parent_plan['target']; native = self.child['target']
        for change in ({'physical_destination':'snowflake:another-account'}, {'physical_destination':None}):
            with self.assertRaisesRegex(ValueError,'physical_destination'):
                same_physical_destination({**original, **change}, native)
        with self.assertRaisesRegex(ValueError,'Native destination identity'):
            same_physical_destination({**native,'base_url':'https://other.snowflakecomputing.com'},native)

    def test_mutated_parent_artifact_cannot_redefine_frozen_expectations(self):
        from metadata_release import reviewed_contract
        changed=copy.deepcopy(self.contract['dictionary']);changed['models'][0]['description']='Changed after build'
        path=self.candidate/'metadata/dictionary.json';original=path.read_bytes()
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'Frozen metadata artifact changed'):
            reviewed_contract(self.parent_plan,build_contract(changed,self.contract['configuration']))
        path.write_bytes(original)
        template=self.candidate/'metadata/configuration-template.json'
        value=json.loads(template.read_text());value['resources'][0]['relation']['name']='replacement'
        template.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'Frozen metadata artifact changed'):
            reviewed_contract(self.parent_plan,self.contract)

    def test_independent_readback_is_recomputed_before_acceptance(self):
        from verify_warehouse_metadata import verify_metadata
        from metadata_observation import seal
        model,approval=self.child_approvals()
        result=deploy.submit(self.child_path,self.policy_path,model,approval,
                             transport=fixtures.ScriptedTransport(self.response('one'),self.response('two')))
        actual=observation(self.contract,expected=True);actual['release_id']=self.parent_plan['id'];actual=seal(actual)
        report=verify_metadata(self.contract,actual,phase='target_metadata',release_id=self.parent_plan['id'])
        checks=[{'id':name,'status':'passed','evidence_sha256':report['verification_sha256'] if name in CHECKS else 'a'*64,
                 'evidence_reference':'synthetic://independent-validation'} for name in self.child['required_checks']]
        bad=copy.deepcopy(actual);bad['resources'][0]['comment']='';bad=seal(bad)
        attestation=self.sign('deployment_acceptance',deploy.execution_bindings(result,self.child),
            claims={'checks':checks,'metadata_observation':bad})
        with self.assertRaisesRegex(ValueError,'readback failed'):
            deploy.accept(self.policy_path,result['operation_id'],attestation)
        recreated=copy.deepcopy(actual);recreated['resources'][0]['object_version']='different-incarnation';recreated=seal(recreated)
        attestation=self.sign('deployment_acceptance',deploy.execution_bindings(result,self.child),
            claims={'checks':checks,'metadata_observation':recreated})
        with self.assertRaisesRegex(ValueError,'incarnation changed'):
            deploy.accept(self.policy_path,result['operation_id'],attestation)
        attestation=self.sign('deployment_acceptance',deploy.execution_bindings(result,self.child),
            claims={'checks':checks,'metadata_observation':actual})
        accepted=deploy.accept(self.policy_path,result['operation_id'],attestation)
        self.assertEqual(accepted['state'],'simulation_verified')
        self.assertEqual(accepted['metadata_verification']['verification_sha256'],report['verification_sha256'])

    def test_live_metadata_requires_native_drift_collector(self):
        from metadata_release import verify_preflight
        from unittest.mock import patch
        _,approval=self.child_approvals()
        metadata=copy.deepcopy(self.metadata)
        metadata['before']['collection']['origin']='trusted_collector'
        with patch('metadata_release.revalidate',return_value=metadata):
            with self.assertRaisesRegex(ValueError,'native drift collector'):
                verify_preflight(self.child,{**self.policy,'mode':'live'},approval['payload']['claims'])

    def test_parent_acceptance_binds_original_metadata_obligations(self):
        from metadata_release import configuration_template
        from metadata_observation import seal
        from verify_warehouse_metadata import verify_metadata
        # Release the synthetic earlier build; create a separately frozen handoff.
        parent=deploy.status(self.policy_path,self.parent['operation_id'])
        recovery=self.sign('deployment_recovery',deploy.recovery_bindings(parent,self.parent_plan),
            issuer='validation-service',claims={'remote_quiescent':True,'recovery_verified':True,
                'evidence_sha256':'a'*64,'evidence_reference':'synthetic://recovery'})
        deploy.recover(self.policy_path,parent['operation_id'],recovery)
        config=copy.deepcopy(self.contract['configuration'])
        extra={'metadata/dictionary.json':('documentation',json.dumps(dictionary()).encode()),
               'metadata/configuration-template.json':('documentation',json.dumps(configuration_template(config)).encode())}
        run,_,_=self.make_handoff('full-metadata',extra_contents=extra)
        path=self.root/'full-build.json'
        plan=deploy.create_plan(run,{**self.request,'release_id':'full-metadata'},self.policy_path,path)
        self.assertTrue(plan['metadata_required'])
        model,approval=self.approvals(plan)
        result=deploy.submit(path,self.policy_path,model,approval,transport=fixtures.ScriptedTransport(fixtures.dbt_response()))
        config['candidate_sha256']=candidate_binding(plan)
        contract=build_contract(dictionary(),config)
        after=observation(contract,expected=True);after['release_id']=plan['id'];after=seal(after)
        report=verify_metadata(contract,after,release_id=plan['id'])
        checks=[{'id':name,'status':'passed','evidence_sha256':report['verification_sha256'] if name in CHECKS else 'a'*64,
                 'evidence_reference':'synthetic://readback'} for name in plan['required_checks']]
        claims={'checks':checks,'metadata_contract':contract,'metadata_observation':after,'metadata_full_build_scope_verified':True}
        changed=copy.deepcopy(config);changed['resources'][0]['relation']['name']='unreviewed_replacement'
        forged={**claims,'metadata_contract':build_contract(dictionary(),changed)}
        attestation=self.sign('deployment_acceptance',deploy.execution_bindings(result,plan),claims=forged)
        with self.assertRaisesRegex(ValueError,'reviewed template'):
            deploy.accept(self.policy_path,result['operation_id'],attestation)
        attestation=self.sign('deployment_acceptance',deploy.execution_bindings(result,plan),claims=claims)
        self.assertEqual(deploy.accept(self.policy_path,result['operation_id'],attestation)['state'],'simulation_verified')


if __name__ == '__main__':
    unittest.main()
