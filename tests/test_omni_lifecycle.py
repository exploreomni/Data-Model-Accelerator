"""Lifecycle declarations stay unqualified until independently observed and signed."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_contract
import omni_inventory
import omni_lifecycle as lifecycle
import test_omni_native_independent as helpers


def inputs():
    files = helpers.candidate()
    files['other.view'] = 'catalog: ANALYTICS\nschema: GOLD\ntable_name: OTHER\ndimensions:\n  id:\n    sql: \'"ID"\'\n'
    context = helpers.context()
    context['bindings']['other'] = {'namespace': {'database':'ANALYTICS','schema':'GOLD','table':'OTHER'},
                                  'columns': {'ID':'number'}, 'evidence_sha256':'c'*64}
    target = {'instance_url':'https://synthetic-lifecycle.omniapp.co', 'model_id':helpers.uid(1),
              'branch_id':helpers.uid(2), 'connection_id':helpers.uid(3),
              'environment_connection_id':helpers.uid(3), 'principal_id':helpers.uid(5), 'environment':'development'}
    desired = dict(files); desired['fleet.view'] += 'description: Reviewed synthetic candidate\n'
    return files, desired, context, target, helpers.Remote(target, files).expected()


def reseal(contract, before, after, observed):
    contract['bindings'].update(baseline_inventory_sha256=before['inventory_sha256'],
        candidate_inventory_sha256=after['inventory_sha256'],
        baseline_files_sha256=omni_contract.canonical_hash(lifecycle._files(before)),
        candidate_files_sha256=omni_contract.canonical_hash(lifecycle._files(after)))
    if contract['environment']['dbt']:
        contract['environment']['dbt']['refresh']['physical_resolution_sha256'] = omni_contract.canonical_hash(contract['environment']['physical_resolution'])
    observed['contract_sha256'] = omni_contract.canonical_hash(contract)
    for name,inventory in (('baseline',before),('candidate',after)):
        if observed[name] is not None:
            observed[name]['inventory_sha256'] = inventory['inventory_sha256']
            observed[name]['content_inventory_sha256'] = omni_contract.canonical_hash(contract['content_inventory'])
    for case in contract['cases']:
        if case['id'] in observed['cases']:
            observed['cases'][case['id']].update(case_sha256=omni_contract.canonical_hash(case),
                target_sha256=contract['bindings']['target_sha256'], candidate_sha256=contract['bindings']['candidate_files_sha256'],
                context_sha256=contract['bindings']['context_sha256'])


def fixture():
    files, desired, context, target, expected = inputs()
    before = omni_inventory.inspect_model(files)
    after = omni_inventory.inspect_model(desired)
    pins = lifecycle.contract_bindings(before, after, context, target, expected, 'f'*64)
    physical = [{'node_id':'authored:view:'+name, 'namespace':copy.deepcopy(binding['namespace']),
                 'environment':'development','built':True,'synthetic':True,'evidence_sha256':'d'*64}
                for name,binding in sorted(context['bindings'].items())]
    contract = {'schema_version':1,'kind':'omni_lifecycle_contract','operation':'update_and_validate',
        'bindings':pins,'route':{'mode':'git_leader','evidence_sha256':'d'*64,'attached_content_ids':['draft-a']},
        'environment':{'warehouse':'snowflake','environment':'development','connection_id':target['connection_id'],
            'environment_connection_id':target['environment_connection_id'],'catalogue_sha256':context['catalogue_sha256'],
            'physical_resolution':physical,'dbt':{'environment_id':'synthetic-dbt-dev','manifest_sha256':'e'*64,
                'build':{'status':'completed','environment_id':'synthetic-dbt-dev','manifest_sha256':'e'*64,'evidence_sha256':'1'*64},
                'refresh':{'status':'completed','environment_id':'synthetic-dbt-dev','manifest_sha256':'e'*64,
                    'build_evidence_sha256':'1'*64,'physical_resolution_sha256':omni_contract.canonical_hash(physical),'evidence_sha256':'2'*64},
                'deferral':{'enabled':False,'production_fallback_acknowledged':False,'fallback_nodes':[]}}},
        'content_inventory':{'complete':True,'expected_ids':['draft-a'],'items':[{'id':'draft-a','definition_sha256':'3'*64,
            'dependencies':['authored:topic:fleet'],'attached_to_branch':True}], 'evidence_sha256':'4'*64},'cases':[]}
    query = {'modelId':target['model_id'],'table':'fleet','fields':['fleet.journeys'],'limit':10}
    for name,lane,outcome in (('compile','native_compilation','pass'),('execute','query_execution','pass'),
                              ('allowed','access','pass'),('missing-attribute','access','deny')):
        contract['cases'].append({'id':name,'lane':lane,'node_ids':['authored:topic:fleet'], 'principal_id':target['principal_id'],
            'path':'omni_query','query_sha256':omni_contract.canonical_hash(query),'attributes_sha256':omni_contract.canonical_hash(name),
            'timezone':'UTC','expected':{'outcome':outcome,'row_count':0 if lane!='native_compilation' and outcome=='pass' else None,
                'population_sha256':omni_contract.canonical_hash([]) if lane!='native_compilation' and outcome=='pass' else None}})
    observed = {'schema_version':1,'kind':'omni_lifecycle_observations','contract_sha256':None,
        'baseline':{'inventory_sha256':None,'content_inventory_sha256':None,'evidence_sha256':'5'*64,'complete':True,'issues':[]},
        'candidate':{'inventory_sha256':None,'content_inventory_sha256':None,'evidence_sha256':'6'*64,'complete':True,'issues':[]},'cases':{}}
    for case in contract['cases']:
        observed['cases'][case['id']] = {'case_sha256':None,'target_sha256':None,'candidate_sha256':None,
            'context_sha256':None,'evidence_sha256':'7'*64,'actual':copy.deepcopy(case['expected'])}
    reseal(contract,before,after,observed)
    return contract,before,after,observed


@unittest.skipUnless(omni_contract.yaml is not None, 'Pinned YAML runtime required')
class LifecycleTests(unittest.TestCase):
    def setUp(self): self.contract,self.before,self.after,self.observed = fixture()

    def assess(self):
        return lifecycle.assess_lifecycle(self.contract,self.before,self.after,self.observed)

    def seal(self): reseal(self.contract,self.before,self.after,self.observed)

    def codes(self): return {f['code'] for f in self.assess()['findings']}

    def add_issue(self, lane, *, node='authored:view:fleet', fingerprint='8'*64):
        self.observed[lane]['issues'].append({'fingerprint_sha256':fingerprint,'node_ids':[node],'content_ids':[],'severity':'error'})

    def test_consistent_zero_population_is_only_local_evidence(self):
        report = self.assess()
        self.assertEqual(report['status'],'passed',report)
        self.assertEqual(report['preflight_status'],'passed')
        self.assertTrue(all(v['status']=='passed' for v in report['lanes'].values()))
        for flag in ('native_verified','security_verified','deployment_authorized','imported_evidence_authenticated'):
            self.assertIs(report[flag],False)
        self.assertIn(omni_contract.canonical_hash('authored:topic:fleet'),report['affected_node_sha256'])
        self.assertEqual(report['affected_content_sha256'],[omni_contract.canonical_hash('draft-a')])

    def test_new_and_affected_baseline_errors_block_but_unrelated_unchanged_remains(self):
        self.add_issue('candidate')
        self.assertIn('lifecycle.new_content_failure',self.codes())
        self.add_issue('baseline')
        self.assertIn('lifecycle.affected_baseline_failure',self.codes())
        for lane in ('baseline','candidate'):
            self.observed[lane]['issues'][0]['node_ids']=['authored:view:other']
        report=self.assess();self.assertEqual(report['status'],'passed',report)
        self.assertEqual(report['unrelated_baseline_issue_sha256'],['8'*64])

    def test_known_affected_failure_cannot_disappear_without_postscan(self):
        self.add_issue('baseline');self.observed['candidate']=None
        self.assertEqual(self.assess()['preflight_status'],'failed')
        self.assertIn('lifecycle.affected_baseline_failure',self.codes())

    def test_resolved_baseline_failure_requires_complete_candidate_scan(self):
        self.add_issue('baseline')
        self.assertEqual(self.assess()['status'],'passed')
        self.observed['candidate']['complete']=False
        self.assertEqual(self.assess()['preflight_status'],'pending')

    def test_deleted_nodes_preserve_old_reverse_dependencies(self):
        desired=lifecycle._files(self.after)
        del desired['fleet.view']
        self.after=omni_inventory.inspect_model(desired)
        self.contract['environment']['physical_resolution']=[r for r in self.contract['environment']['physical_resolution'] if r['node_id']=='authored:view:other']
        self.seal();report=self.assess()
        self.assertIn(omni_contract.canonical_hash('authored:topic:fleet'),report['affected_node_sha256'])
        self.assertNotEqual(report['preflight_status'],'passed')

    def test_query_view_output_dependencies_propagate(self):
        source='query:\n  base_view: fleet\n  topic: fleet\n  fields:\n    fleet.journeys: journeys\ndimensions:\n  journeys: {}\n'
        for attr in ('before','after'):
            files=lifecycle._files(getattr(self,attr));files['summary.query.view']=source
            setattr(self,attr,omni_inventory.inspect_model(files))
        self.seal();report=self.assess()
        self.assertIn(omni_contract.canonical_hash('authored:view:summary/field:journeys'),report['affected_node_sha256'])

    def test_tampered_inventory_rehashed_graph_cannot_shrink_closure(self):
        self.after['dependencies']=[]
        self.after['inventory_sha256']=omni_contract.canonical_hash({k:v for k,v in self.after.items() if k!='inventory_sha256'})
        self.contract['bindings']['candidate_inventory_sha256']=self.after['inventory_sha256']
        self.seal()
        self.assertIn('lifecycle.inventory_reparse_mismatch',self.codes())

    def test_follower_blocks_updates_and_unknown_route_is_pending(self):
        self.contract['route']['mode']='git_follower';self.seal()
        self.assertIn('lifecycle.follower_read_only',self.codes())
        self.contract['operation']='validate';self.seal()
        self.assertEqual(self.assess()['preflight_status'],'passed')
        self.contract['route']['mode']='unknown';self.seal()
        self.assertEqual(self.assess()['preflight_status'],'pending')

    def test_missing_or_mismatched_build_refresh_environment_pins(self):
        original=copy.deepcopy(self.contract)
        for mutation in ('status','manifest','environment','chain','resolution'):
            self.contract=copy.deepcopy(original);dbt=self.contract['environment']['dbt']
            if mutation=='status':dbt['build']['status']='pending'
            if mutation=='manifest':dbt['refresh']['manifest_sha256']='0'*64
            if mutation=='environment':dbt['build']['environment_id']='another'
            if mutation=='chain':dbt['refresh']['build_evidence_sha256']='0'*64
            self.seal()
            if mutation=='resolution':
                dbt['refresh']['physical_resolution_sha256']='0'*64
                self.observed['contract_sha256']=omni_contract.canonical_hash(self.contract)
            with self.subTest(mutation=mutation):self.assertNotEqual(self.assess()['preflight_status'],'passed')

    def test_production_fallback_acknowledgement_cannot_expand_synthetic_dev_boundary(self):
        physical=self.contract['environment']['physical_resolution'][0]
        physical['environment']='production';physical['built']=False
        dbt=self.contract['environment']['dbt']
        dbt['deferral']={'enabled':True,'production_fallback_acknowledged':True,'fallback_nodes':[physical['node_id']]}
        self.seal()
        self.assertIn('lifecycle.production_resolution_requires_separate_qualification',self.codes())
        self.assertEqual(self.assess()['preflight_status'],'failed')

    def test_unbuilt_and_nonsynthetic_relations_never_silently_pass(self):
        physical=self.contract['environment']['physical_resolution'][0]
        physical['built']=False;self.seal()
        self.assertIn('lifecycle.deferral_resolution_unacknowledged',self.codes())
        physical['built']=True;physical['synthetic']=False;self.seal()
        self.assertIn('lifecycle.synthetic_development_only',self.codes())

    def test_omitted_attached_content_or_unresolved_content_is_not_complete(self):
        self.contract['route']['attached_content_ids']=[];self.seal()
        self.assertIn('lifecycle.attached_content_omitted',self.codes())
        self.contract['route']['attached_content_ids']=['draft-a']
        self.contract['content_inventory']['items'][0]['dependencies']=['authored:topic:missing'];self.seal()
        self.assertIn('lifecycle.content_dependency_unresolved',self.codes())

    def test_reference_scan_cannot_substitute_for_runtime_or_access(self):
        self.observed['cases']={}
        report=self.assess()
        self.assertEqual(report['preflight_status'],'passed')
        self.assertEqual(report['lanes']['reference_scan']['status'],'passed')
        self.assertEqual(report['status'],'pending')
        for lane in lifecycle.LANES[1:]:self.assertEqual(report['lanes'][lane]['status'],'pending')

    def test_population_and_negative_access_mismatches_block(self):
        self.observed['cases']['execute']['actual']['population_sha256']='0'*64
        self.assertIn('lifecycle.query_execution_case_failed',self.codes())
        self.observed['cases']['missing-attribute']['actual']={'outcome':'pass','row_count':0,'population_sha256':'0'*64}
        self.assertIn('lifecycle.access_case_failed',self.codes())

    def test_missing_negative_access_case_stays_pending(self):
        self.contract['cases']=[c for c in self.contract['cases'] if c['id']!='missing-attribute']
        self.observed['cases'].pop('missing-attribute');self.seal()
        self.assertEqual(self.assess()['lanes']['access']['status'],'pending')

    def test_imported_case_pin_or_lane_change_cannot_be_relabelled(self):
        self.observed['cases']['execute']['case_sha256']='0'*64
        self.assertIn('lifecycle.case_observation_binding',self.codes())
        self.contract['cases'][0]['expected']={'outcome':'pass','row_count':0,'population_sha256':'0'*64};self.seal()
        self.assertIn('lifecycle.compilation_not_execution',self.codes())

    def test_diagnostics_never_echo_provider_or_row_text(self):
        self.observed['candidate']['issues']=[{'provider_message':'SYNTHETIC_PHI_CANARY'}]
        report=self.assess()
        self.assertEqual(report['status'],'failed')
        self.assertNotIn('SYNTHETIC_PHI_CANARY',json.dumps(report))
        self.observed['candidate']['issues']=[]
        self.observed['cases']['execute']['actual']['row_count']='SYNTHETIC_PHI_CANARY'
        self.assertNotIn('SYNTHETIC_PHI_CANARY',json.dumps(self.assess()))

    def test_report_and_hash_are_deterministic(self):
        first=self.assess();self.assertEqual(first,self.assess())
        self.assertEqual(first['assessment_sha256'],omni_contract.canonical_hash({k:v for k,v in first.items() if k!='assessment_sha256'}))

    def test_cli_private_report_without_raw_inventory_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp).resolve()/'request.json';output=Path(tmp).resolve()/'report.json'
            source.write_text(json.dumps(dict(contract=self.contract,baseline_inventory=self.before,candidate_inventory=self.after,observations=self.observed)))
            command=[sys.executable,str(Path(lifecycle.__file__)), '--request',str(source),'--output',str(output)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(output.stat().st_mode & 0o777,0o600)
            self.assertNotIn('Reviewed synthetic candidate',output.read_text())
            original=output.read_bytes()
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(output.read_bytes(),original)


class LifecycleWithoutRuntimeTests(unittest.TestCase):
    def test_malformed_input_has_value_free_failure(self):
        result=lifecycle.assess_lifecycle({'unexpected':'SYNTHETIC_PHI_CANARY'},None,None)
        self.assertEqual(result['status'],'failed')
        self.assertNotIn('SYNTHETIC_PHI_CANARY',json.dumps(result))


if __name__=='__main__':unittest.main()
