"""Synthetic exact-state and persona checks; no warehouse or Omni calls."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import security_contract as security
from ae_common import hash_json


def fixture():
    bindings={k:'a'*64 for k in ('source','catalogue','candidate','target','policy','scope')}
    destination={'warehouse':'snowflake','environment':'development','identity':{'account':'SYNTHETIC','database':'DEMO',
        'omni_instance':'https://synthetic.omniapp.co','omni_model_id':'model-fixture','omni_connection_id':'connection-fixture','omni_branch_id':'branch-fixture'}}
    resources=[]
    for identity,kind in (('table','warehouse'),('topic','omni_topic'),('document','omni_document')):
        resources.append({'id':identity,'kind':kind,'namespace':{'id':'synthetic-'+identity},
            'principals':{'users':['subject-user'],'groups':[]},'allowed_actions':sorted(security.REQUIRED_PATHS[kind]),
            'row_policy_sha256':'b'*64,'columns':{'amount':{'classification':'INTERNAL','mode':'allow','policy_sha256':None,
            'metadata_visible':False,'inherited_from':[identity]}},'metadata_visible':False,
            'inheritance':{'new_columns':'deny','policy_sha256':'c'*64}})
    current={'schema_version':1,'kind':'security_state','bindings':bindings,'destination':destination,'resources':resources}
    candidate=copy.deepcopy(current);readback=copy.deepcopy(current)
    contract={'schema_version':1,'kind':'security_contract','migration_scope':'full_dashboard','bindings':bindings,
        'warehouse':'snowflake','framework':'dbt','destination':destination,'current_sha256':security.state_hash(current),
        'candidate_sha256':security.state_hash(candidate),'snapshot_sha256':'d'*64,
        'personas':{'analyst':{'principal_id':'subject-user','groups':['analysts'],'attributes':{'tenant':'e'*64},
                             'required_attributes':['tenant'],'unexpected_groups':['unexpected_group']}},'cases':[],'review':{}}
    for resource in resources:
        for path in sorted(security.REQUIRED_PATHS[resource['kind']]):
            for scenario in ('positive','negative','missing_attribute','unexpected_group'):
                identity=resource['id']+'-'+path+'-'+scenario
                allowed=scenario=='positive'
                contract['cases'].append({'id':identity,'resource_id':resource['id'],'persona_id':'analyst','path':path,
                    'scenario':scenario,'probe_sha256':hash_json(identity),'expected':{'decision':'allow' if allowed else 'deny',
                    'row_scope_sha256':'f'*64 if allowed else None,'columns':['amount'] if allowed else [],'masked_columns':[],
                    'metadata_visible':False,'canary_visible':False}})
    seal(contract,current,candidate)
    observations={'schema_version':1,'kind':'security_observations','contract_sha256':hash_json(contract),
        'state_sha256':security.state_hash(candidate),'bindings':copy.deepcopy(bindings),'destination':copy.deepcopy(destination),
        'cases':{case['id']:{'context':security.expected_context(contract,case),'result':copy.deepcopy(case['expected'])} for case in contract['cases']}}
    return contract,current,candidate,readback,observations


def seal(contract,current,candidate):
    contract['current_sha256']=security.state_hash(current);contract['candidate_sha256']=security.state_hash(candidate)
    contract['review']={'status':'approved','reference':'synthetic-security-review','contract_sha256':security.review_hash(contract)}


class SecurityContractTests(unittest.TestCase):
    def test_exact_existing_controls_and_all_paths_are_local_only(self):
        result=security.evaluate_access(*fixture())
        self.assertEqual(result['status'],'locally_consistent',result)
        for key in ('native_verified','evidence_authenticated','live_qualified','protected_deployment_allowed','policy_writes_performed'):
            self.assertFalse(result[key])
        self.assertEqual(result['cases_compared'],36)

    def test_missing_evidence_and_missing_persona_case_remain_pending(self):
        c,current,candidate,readback,observations=fixture()
        self.assertEqual(security.evaluate_access(c,current,candidate)['status'],'pending')
        del observations['cases'][c['cases'][0]['id']]
        self.assertEqual(security.evaluate_access(c,current,candidate,readback,observations)['status'],'pending')

    def test_omitted_negative_missing_attribute_group_or_path_rejects_plan(self):
        for scenario in ('negative','missing_attribute','unexpected_group'):
            c,current,candidate,_,_=fixture();c['cases']=[case for case in c['cases'] if case['scenario']!=scenario]
            seal(c,current,candidate)
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):security.validate_contract(c,current,candidate)

    def test_wrong_persona_group_attribute_destination_or_probe_fails(self):
        for key,value in (('principal_id','other'),('groups',['unexpected_group']),('attributes',{}),
                          ('destination_sha256','0'*64),('probe_sha256','0'*64)):
            args=list(fixture());args[4]['cases'][args[0]['cases'][0]['id']]['context'][key]=value
            with self.subTest(key=key):self.assertEqual(security.evaluate_access(*args)['status'],'failed')

    def test_canary_or_forbidden_export_result_fails_without_echo(self):
        args=list(fixture());case=next(c for c in args[0]['cases'] if c['path']=='omni_export' and c['scenario']=='negative')
        args[4]['cases'][case['id']]['result']['canary_visible']=True
        self.assertEqual(security.evaluate_access(*args)['status'],'failed')
        args[4]['cases'][case['id']]['result']['untrusted_value']='SYNTHETIC_PHI_CANARY'
        result=security.evaluate_access(*args)
        self.assertNotIn('SYNTHETIC_PHI_CANARY',json.dumps(result))

    def test_policy_target_or_candidate_drift_blocks(self):
        for lane in (1,2,3):
            args=list(fixture());args[lane]['resources'][0]['row_policy_sha256']='0'*64
            with self.subTest(lane=lane):self.assertEqual(security.evaluate_access(*args)['status'],'blocked')

    def test_nonweakening_rejects_row_mask_metadata_grants_and_inheritance(self):
        _,current,candidate,_,_=fixture()
        changes=[lambda r:r.update(row_policy_sha256=None),lambda r:r['principals']['users'].append('unapproved'),
                 lambda r:r.update(metadata_visible=True),lambda r:r['inheritance'].update(policy_sha256='0'*64),
                 lambda r:r['columns']['amount'].update(metadata_visible=True),
                 lambda r:r['columns']['amount'].update(inherited_from=[]),
                 lambda r:r['columns'].update({'new_field':{'classification':'PUBLIC','mode':'allow','policy_sha256':None,
                                                    'metadata_visible':True,'inherited_from':[]}})]
        for change in changes:
            altered=copy.deepcopy(candidate);change(altered['resources'][0])
            with self.subTest(change=change):self.assertTrue(security._nonweakening(current,altered))
        current['resources'][0]['columns']['amount'].update(mode='mask',policy_sha256='a'*64)
        candidate=copy.deepcopy(current);candidate['resources'][0]['columns']['amount']['policy_sha256']='b'*64
        self.assertTrue(security._nonweakening(current,candidate))

    def test_even_restrictive_policy_changes_need_qualified_provisioning(self):
        c,current,candidate,_,_=fixture()
        candidate['resources'][0]['columns']['new_field']={'classification':'UNKNOWN','mode':'deny','policy_sha256':'e'*64,
             'metadata_visible':False,'inherited_from':['table']}
        seal(c,current,candidate)
        result=security.evaluate_access(c,current,candidate)
        self.assertEqual(result['status'],'blocked')
        self.assertEqual(result['findings'][0]['code'],'security.policy_provisioning_unqualified')
        self.assertIn('security owner',result['handoff'])

    def test_imported_native_claim_is_not_authority(self):
        args=list(fixture());args[4]['native_verified']=True
        self.assertEqual(security.evaluate_access(*args)['status'],'blocked')

    def test_hidden_column_metadata_cannot_be_frozen_as_visible(self):
        c,current,candidate,_,_=fixture()
        for state in (current,candidate):state['resources'][0]['metadata_visible']=True
        case=next(x for x in c['cases'] if x['resource_id']=='table' and x['scenario']=='positive')
        case['expected']['metadata_visible']=True
        seal(c,current,candidate)
        with self.assertRaisesRegex(ValueError,'expected_metadata'):security.validate_contract(c,current,candidate)

    def test_all_binding_changes_and_stale_review_rejected(self):
        for key in ('source','catalogue','candidate','target','policy','scope'):
            args=list(fixture());args[0]['bindings']=dict(args[0]['bindings'],**{key:'0'*64})
            with self.subTest(key=key):self.assertEqual(security.evaluate_access(*args)['status'],'blocked')


if __name__=='__main__':unittest.main()
