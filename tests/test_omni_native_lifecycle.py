"""Exact lifecycle requests retain the existing isolated, signed native boundary."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_contract
import omni_inventory
import omni_lifecycle as lifecycle
import omni_native as native
import test_omni_lifecycle as fixtures
import test_omni_native_independent as helpers


@unittest.skipUnless(helpers.RUNTIME, 'Pinned optional semantic/deployment dependencies required')
class NativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        # Compose its private fixture helpers without inheriting any test methods.
        self.h = helpers.NativeIndependentTests(methodName='runTest')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.contract,self.before,self.after,self.observed = fixtures.fixture()
        files,desired,context,target,_ = fixtures.inputs()
        self.h.target = target; self.h.remote = helpers.Remote(target,files)
        self.h.policy['destinations']['dev'] = target; self.h.save_policy()
        self.h.request.update(operation='update_and_validate', target=target, files=desired,
                              context=context, expected_remote=self.h.remote.expected())
        self.seal()
        guard = patch('omni_native.HTTPSOmniTransport',side_effect=AssertionError('Live calls forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def seal(self):
        fixtures.reseal(self.contract,self.before,self.after,self.observed)
        self.h.request['lifecycle'] = lifecycle.prepare_request(self.contract,self.before,self.after,self.observed)

    def approval(self):
        envelope = self.h.approval()
        envelope['payload']['claims']['preflight']['lifecycle_assessment_sha256'] = self.h.request['lifecycle']['assessment_sha256']
        return self.h.sign(envelope['payload'])

    def run_native(self, approval=None): return self.h.run_native(approval=approval)

    def test_exact_signed_request_stays_simulated_and_lifecycle_unauthenticated(self):
        receipt=self.run_native(self.approval())
        self.assertEqual(receipt['status'],'simulated_passed',receipt)
        self.assertEqual(receipt['lifecycle']['status'],'passed')
        self.assertFalse(receipt['lifecycle']['imported_evidence_authenticated'])
        self.assertFalse(receipt['lifecycle']['native_verified'])
        verified=native.verify_receipt(self.h.request,receipt,hashlib.sha256(self.h.policy_path.read_bytes()).hexdigest())
        self.assertEqual(verified['status'],'integrity_verified',verified)
        self.assertFalse(verified['authenticated'])
        altered=copy.deepcopy(receipt);altered['lifecycle']['native_verified']=True
        self.assertEqual(native.verify_receipt(self.h.request,altered,receipt['policy_sha256'])['status'],'failed')

    def test_legacy_observation_discloses_unassessed_lifecycle(self):
        self.h.request.pop('lifecycle');self.h.request['operation']='validate'
        self.h.request['files']=copy.deepcopy(self.h.remote.files)
        receipt=self.run_native()
        self.assertEqual(receipt['status'],'simulated_passed')
        self.assertEqual(receipt['lifecycle']['status'],'unassessed')
        self.assertFalse(receipt['lifecycle']['native_verified'])

    def test_signed_approval_must_explicitly_bind_lifecycle(self):
        receipt=self.run_native(self.h.approval())
        self.assertEqual(receipt['code'],'authorization.lifecycle_preflight_required',receipt)
        self.assertEqual(self.h.remote.calls,[])

    def test_follower_unknown_or_missing_route_never_calls_transport(self):
        for mode,evidence in (('git_follower','a'*64),('unknown','a'*64),('native',None)):
            self.contract['route'].update(mode=mode,evidence_sha256=evidence);self.seal()
            receipt=self.run_native(self.approval())
            self.assertEqual(receipt['code'],'lifecycle.preflight_not_passed',receipt)
            self.assertEqual(self.h.remote.calls,[])

    def test_stale_assessment_or_new_candidate_is_rejected_before_transport(self):
        self.h.request['lifecycle']['assessment_sha256']='0'*64
        receipt=self.run_native(self.approval())
        self.assertEqual(receipt['code'],'lifecycle.assessment_changed')
        self.seal();self.h.request['files']['fleet.view'] += '# changed after review\n'
        receipt=self.run_native(self.approval())
        self.assertEqual(receipt['code'],'lifecycle.native_binding_mismatch')
        self.assertEqual(self.h.remote.calls,[])

    def test_physical_catalogue_and_selected_principal_must_match(self):
        original=copy.deepcopy(self.contract)
        self.contract['environment']['physical_resolution'][0]['namespace']['table']='MISMATCH'
        self.seal();receipt=self.run_native(self.approval())
        self.assertEqual(receipt['code'],'lifecycle.physical_catalogue_mismatch',receipt)
        self.contract=original
        self.contract['cases'][0]['principal_id']=helpers.uid(99)
        self.seal();receipt=self.run_native(self.approval())
        self.assertEqual(receipt['code'],'lifecycle.selected_principal_mismatch')
        self.assertEqual(self.h.remote.calls,[])

    def test_imported_false_baseline_cannot_reach_a_write(self):
        files=lifecycle._files(self.before);files['fleet.view'] += '# fabricated previous bytes\n'
        self.before=omni_inventory.inspect_model(files);self.seal()
        receipt=self.run_native(self.approval())
        self.assertEqual(receipt['code'],'lifecycle.remote_baseline_mismatch',receipt)
        self.assertFalse(any(call['method']!='GET' for call in self.h.remote.calls))

    def test_queryviews_and_qualified_paths_supported_but_urls_and_traversal_rejected(self):
        request=copy.deepcopy(self.h.request);request.pop('lifecycle')
        request['files']['summary.query.view']='query:\n  base_view: fleet\n  topic: fleet\n  fields:\n    fleet.journeys: journeys\ndimensions:\n  journeys: {}\n'
        self.assertEqual(omni_contract.check_model(request['files'],request['context'])['status'],'passed')
        native.validate_request(request)
        request['files']['views/fleet.view.yaml']=request['files'].pop('fleet.view')
        native.validate_request(request)
        for path in ('../fleet.view','/fleet.view','https://other.invalid/fleet.view','views//fleet.view','views/./fleet.view','views\\fleet.view'):
            changed=copy.deepcopy(request);changed['files'][path]=changed['files'].pop('views/fleet.view.yaml')
            with self.subTest(path=path),self.assertRaisesRegex(native.AdapterError,'request.native_file'):
                native.validate_request(changed)

    def test_changed_lifecycle_pins_invalidate_existing_signed_approval(self):
        approval=self.approval()
        self.contract['route']['evidence_sha256']='9'*64;self.seal()
        receipt=self.run_native(approval)
        self.assertEqual(receipt['code'],'authorization.attestation_invalid')
        self.assertEqual(self.h.remote.calls,[])

    def test_query_lane_must_cover_exact_selected_query_and_timezone(self):
        self.contract['operation']='query'
        self.h.request.update(operation='query',query_mode='plan',timezone='UTC',
            query={'modelId':self.h.target['model_id'],'table':'fleet','fields':['fleet.journeys'],'limit':10})
        self.h.remote.files=copy.deepcopy(self.h.request['files'])
        self.h.request['expected_remote']=self.h.remote.expected()
        self.contract['bindings']['expected_remote_sha256']=omni_contract.canonical_hash(self.h.request['expected_remote'])
        self.seal();native.validate_request(self.h.request)
        self.h.request['query']['limit']=1
        receipt=self.run_native(self.approval())
        self.assertEqual(receipt['code'],'lifecycle.selected_query_case_missing')
        self.assertEqual(self.h.remote.calls,[])

    def test_partial_two_file_write_timeout_reconciles_without_duplicate(self):
        desired=copy.deepcopy(self.h.request['files']);desired['other.view'] += 'description: Reviewed second file\n'
        self.h.request['files']=desired;self.after=omni_inventory.inspect_model(desired);self.seal()
        original=self.h.remote.request;writes=[]
        def transport(method,path,params=None,body=None):
            if method=='POST' and path.endswith('/yaml'):
                writes.append(body['fileName'])
                result=original(method,path,params,body)
                if len(writes)==2: raise native.TransportError('transport.synthetic_timeout',uncertain=True)
                return result
            return original(method,path,params,body)
        with patch.object(self.h.remote,'request',side_effect=transport):
            first=self.run_native(self.approval())
            self.assertEqual(first['status'],'pending',first)
            self.assertEqual(len(writes),2)
            second=self.run_native(self.approval())
        self.assertEqual(second['status'],'simulated_passed',second)
        self.assertEqual(len(writes),2)

    def test_rate_limit_never_retries_automatically_or_echoes_provider_message(self):
        self.h.remote.write_error=native.TransportError('transport.rate_limited',status=429)
        receipt=self.run_native(self.approval())
        self.assertEqual(receipt['status'],'pending',receipt)
        self.assertEqual(sum(c['method']=='POST' for c in self.h.remote.calls),1)
        self.assertEqual(self.h.remote.files,lifecycle._files(self.before))


if __name__=='__main__':unittest.main()
