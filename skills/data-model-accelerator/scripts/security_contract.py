"""Exact access-state and persona comparison. No GRANT, policy writes or queries.

Imported readback and observations establish local consistency, never effective
security authentication. Changed opaque policy semantics stop for human review.
"""
import argparse
import copy
import json
from pathlib import Path
import re

from ae_common import hash_json, require, _json_bytes
from delivery_assurance import SCOPES, validate_bindings
from security_capabilities import capabilities

SHA = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
PATHS = {'warehouse_query','warehouse_metadata','omni_query','omni_dashboard','omni_drill','omni_export','omni_share','omni_cache'}
KINDS = {'warehouse','omni_topic','omni_document'}
REQUIRED_PATHS = {'warehouse': {'warehouse_query','warehouse_metadata'},
                  'omni_topic': {'omni_query','omni_drill','omni_cache'},
                  'omni_document': {'omni_dashboard','omni_export','omni_share','omni_cache'}}
IDENTITY = {'snowflake': {'account','database'}, 'databricks': {'workspace','metastore','catalog','runtime'},
            'bigquery': {'project','dataset','location'}, 'redshift': {'cluster_or_workgroup','database'},
            'clickhouse': {'server_version','engine','cluster','database'}, 'motherduck': {'organization','database'}}
CLASSIFICATION = {'PUBLIC':0,'INTERNAL':1,'CONFIDENTIAL':2,'RESTRICTED':3,'UNKNOWN':4}
MODES = {'allow':0,'mask':1,'deny':2}


def _sha(value): return type(value) is str and SHA.fullmatch(value) is not None

def _id(value): return type(value) is str and ID.fullmatch(value) is not None

def _ids(value): return type(value) is list and all(_id(x) for x in value) and len(value) == len(set(value))

def _bounded(value):
    from omni_contract import _bounded as check
    check(value)
    require(len(_json_bytes(value)) <= 8*1024*1024, 'security.input_bounds')


def state_hash(state):
    normalized = copy.deepcopy(state)
    normalized['resources'] = sorted(normalized['resources'], key=lambda row:row['id'])
    return hash_json(normalized)


def review_hash(contract): return hash_json({k:v for k,v in contract.items() if k!='review'})


def _destination(destination, warehouse, scope):
    require(type(destination) is dict and set(destination)=={'warehouse','environment','identity'}
            and destination['warehouse']==warehouse and destination['environment'] in ('development','production'), 'security.destination')
    identity=destination['identity']
    required=IDENTITY[warehouse] | (set() if scope=='model_only' else {'omni_instance','omni_model_id','omni_connection_id','omni_branch_id'})
    require(type(identity) is dict and required <= set(identity)
            and all(type(k) is str and _id(k) and type(v) is str and v.strip() for k,v in identity.items()), 'security.destination_identity')


def validate_state(state, contract):
    _bounded(state)
    require(type(state) is dict and set(state)=={'schema_version','kind','bindings','destination','resources'}
            and type(state['schema_version']) is int and state['schema_version']==1 and state['kind']=='security_state', 'security.state_schema')
    require(state['bindings']==contract['bindings'] and state['destination']==contract['destination'], 'security.state_binding')
    resources=state['resources']
    require(type(resources) is list and 0<len(resources)<=200, 'security.resource_inventory')
    seen=set()
    for resource in resources:
        require(type(resource) is dict and set(resource)=={'id','kind','namespace','principals','allowed_actions','row_policy_sha256',
                'columns','metadata_visible','inheritance'} and _id(resource['id']) and resource['id'] not in seen
                and resource['kind'] in KINDS, 'security.resource_schema')
        seen.add(resource['id'])
        require(type(resource['namespace']) is dict and resource['namespace']
                and all(type(k) is str and k and type(v) is str and v for k,v in resource['namespace'].items()), 'security.resource_namespace')
        principals=resource['principals']
        require(type(principals) is dict and set(principals)=={'users','groups'} and all(_ids(v) for v in principals.values()), 'security.principals')
        require(_ids(resource['allowed_actions']) and set(resource['allowed_actions']) <= REQUIRED_PATHS[resource['kind']], 'security.actions')
        require(resource['row_policy_sha256'] is None or _sha(resource['row_policy_sha256']), 'security.row_policy')
        require(type(resource['metadata_visible']) is bool and type(resource['inheritance']) is dict
                and set(resource['inheritance'])=={'new_columns','policy_sha256'}
                and resource['inheritance']['new_columns']=='deny' and _sha(resource['inheritance']['policy_sha256']), 'security.default_deny_inheritance')
        require(type(resource['columns']) is dict and len(resource['columns'])<=500, 'security.column_inventory')
        for name,column in resource['columns'].items():
            require(_id(name) and type(column) is dict and set(column)=={'classification','mode','policy_sha256','metadata_visible','inherited_from'}
                    and column['classification'] in CLASSIFICATION and column['mode'] in MODES
                    and type(column['metadata_visible']) is bool and _ids(column['inherited_from']), 'security.column_schema')
            require((column['mode']=='allow' and column['policy_sha256'] is None) or (column['mode']!='allow' and _sha(column['policy_sha256'])),
                    'security.column_policy')
            require(column['classification']!='UNKNOWN' or column['mode']=='deny', 'security.unknown_column_must_deny')
    for resource in resources:
        require(all(set(column['inherited_from'])<=seen for column in resource['columns'].values()), 'security.inheritance_unresolved')
    return state


def _expected(value, resource):
    require(type(value) is dict and set(value)=={'decision','row_scope_sha256','columns','masked_columns','metadata_visible','canary_visible'}
            and value['decision'] in ('allow','deny','masked') and _ids(value['columns']) and _ids(value['masked_columns'])
            and set(value['masked_columns'])<=set(value['columns'])<=set(resource['columns'])
            and type(value['metadata_visible']) is bool and value['canary_visible'] is False, 'security.expected_result')
    if value['decision']=='deny':
        require(value['row_scope_sha256'] is None and not value['columns'] and not value['masked_columns']
                and value['metadata_visible'] is False, 'security.denial_must_not_disclose')
    else:
        require(_sha(value['row_scope_sha256']) and all(resource['columns'][name]['mode']!='deny' for name in value['columns']),
                'security.expected_column_scope')
        require(set(value['masked_columns'])=={name for name in value['columns'] if resource['columns'][name]['mode']=='mask'}
                and (value['decision']=='masked')==bool(value['masked_columns']), 'security.expected_masks')
        require(not value['metadata_visible'] or resource['metadata_visible']
                and all(resource['columns'][name]['metadata_visible'] for name in value['columns']), 'security.expected_metadata')


def validate_contract(contract, current=None, candidate=None):
    _bounded(contract)
    required={'schema_version','kind','migration_scope','bindings','warehouse','framework','destination','current_sha256',
              'candidate_sha256','snapshot_sha256','personas','cases','review'}
    require(type(contract) is dict and set(contract)==required and type(contract['schema_version']) is int
            and contract['schema_version']==1 and contract['kind']=='security_contract', 'security.contract_schema')
    validate_bindings(contract['bindings'])
    require(contract['migration_scope'] in SCOPES,'security.scope')
    capabilities(contract['warehouse'],contract['framework'])
    _destination(contract['destination'],contract['warehouse'],contract['migration_scope'])
    require(all(_sha(contract[k]) for k in ('current_sha256','candidate_sha256','snapshot_sha256')), 'security.frozen_state_required')
    review=contract['review']
    require(type(review) is dict and set(review)=={'status','reference','contract_sha256'} and review['status']=='approved'
            and type(review['reference']) is str and review['reference'].strip() and review['contract_sha256']==review_hash(contract), 'security.review_stale')
    personas=contract['personas']
    require(type(personas) is dict and 0<len(personas)<=100,'security.personas')
    for identity,persona in personas.items():
        require(_id(identity) and type(persona) is dict and set(persona)=={'principal_id','groups','attributes','required_attributes','unexpected_groups'}
                and _id(persona['principal_id']) and _ids(persona['groups']) and _ids(persona['required_attributes'])
                and _ids(persona['unexpected_groups']) and persona['unexpected_groups']
                and not set(persona['groups']) & set(persona['unexpected_groups'])
                and type(persona['attributes']) is dict and all(_id(k) and _sha(v) for k,v in persona['attributes'].items())
                and set(persona['required_attributes'])<=set(persona['attributes']), 'security.persona_schema')
    cases=contract['cases'];seen=set()
    require(type(cases) is list and 0<len(cases)<=5000,'security.cases')
    for case in cases:
        require(type(case) is dict and set(case)=={'id','resource_id','persona_id','path','scenario','probe_sha256','expected'}
                and _id(case['id']) and case['id'] not in seen and _id(case['resource_id']) and case['persona_id'] in personas
                and case['path'] in PATHS and case['scenario'] in ('positive','negative','missing_attribute','unexpected_group')
                and _sha(case['probe_sha256']), 'security.case_schema')
        seen.add(case['id'])
        if case['scenario'] in ('negative','missing_attribute','unexpected_group'):
            require(type(case['expected']) is dict and case['expected'].get('decision')=='deny','security.negative_must_deny')
    if current is not None:
        validate_state(current,contract);require(state_hash(current)==contract['current_sha256'],'security.current_changed')
    if candidate is not None:
        validate_state(candidate,contract);require(state_hash(candidate)==contract['candidate_sha256'],'security.candidate_changed')
        resources={r['id']:r for r in candidate['resources']}
        kinds={r['kind'] for r in resources.values()}
        expected_kinds={'warehouse'} | (set() if contract['migration_scope']=='model_only' else {'omni_topic'}) | ({'omni_document'} if contract['migration_scope']=='full_dashboard' else set())
        require(kinds==expected_kinds,'security.scope_resource_coverage')
        covered=set()
        for case in cases:
            require(case['resource_id'] in resources,'security.case_resource')
            resource=resources[case['resource_id']];persona=personas[case['persona_id']]
            require(case['path'] in REQUIRED_PATHS[resource['kind']],'security.case_path')
            _expected(case['expected'],resource)
            if case['scenario']=='positive':
                # For permanently denied paths, a positive probe may explicitly
                # expect denial; every supported allowed path needs a real allow.
                granted=(persona['principal_id'] in resource['principals']['users']
                         or bool(set(persona['groups']) & set(resource['principals']['groups']))) and case['path'] in resource['allowed_actions']
                require((case['expected']['decision']!='deny')==granted,'security.positive_grant_mismatch')
            require(case['scenario']!='missing_attribute' or persona['required_attributes'],'security.missing_attribute_not_applicable')
            key=(case['resource_id'],case['persona_id'],case['path'],case['scenario'])
            require(key not in covered,'security.duplicate_scenario');covered.add(key)
        required_coverage={(r['id'],identity,path,scenario) for r in resources.values() for identity,persona in personas.items()
            for path in REQUIRED_PATHS[r['kind']] for scenario in ('positive','negative','unexpected_group')+ (('missing_attribute',) if persona['required_attributes'] else ())}
        require(covered==required_coverage,'security.persona_path_coverage_incomplete')
    return contract


def _nonweakening(current,candidate):
    issues=[];before={r['id']:r for r in current['resources']};after={r['id']:r for r in candidate['resources']}
    def issue(code,index): issues.append({'resource_index':index,'code':code})
    if not set(before)<=set(after):issues.append({'code':'security.existing_resource_removed'})
    for index,(identity,old) in enumerate(sorted(before.items())):
        new=after.get(identity)
        if new is None:continue
        if old['namespace']!=new['namespace'] or old['kind']!=new['kind']:issue('security.resource_identity_changed',index)
        if not set(new['allowed_actions'])<=set(old['allowed_actions']):issue('security.actions_expanded',index)
        if any(not set(new['principals'][k])<=set(old['principals'][k]) for k in ('users','groups')):issue('security.audience_expanded',index)
        if old['metadata_visible'] is False and new['metadata_visible']:issue('security.metadata_expanded',index)
        if old['row_policy_sha256'] is not None and old['row_policy_sha256']!=new['row_policy_sha256']:issue('security.row_policy_change_unproven',index)
        if old['inheritance']!=new['inheritance']:issue('security.inheritance_change_unproven',index)
        if not set(old['columns'])<=set(new['columns']):issue('security.existing_column_removed',index)
        for name,column in new['columns'].items():
            prior=old['columns'].get(name)
            if prior is None:
                if column['mode']!='deny' or column['metadata_visible']:issue('security.new_column_not_denied',index)
                continue
            if MODES[column['mode']]<MODES[prior['mode']]:issue('security.column_protection_reduced',index)
            if CLASSIFICATION[column['classification']]<CLASSIFICATION[prior['classification']]:issue('security.classification_reduced',index)
            if prior['metadata_visible'] is False and column['metadata_visible']:issue('security.column_metadata_expanded',index)
            if prior['mode']=='mask' and column['mode']=='mask' and prior['policy_sha256']!=column['policy_sha256']:issue('security.mask_change_unproven',index)
            if not set(prior['inherited_from'])<=set(column['inherited_from']):issue('security.inherited_control_removed',index)
    for identity in set(after)-set(before):
        resource=after[identity]
        if (resource['allowed_actions'] or resource['principals']['users'] or resource['principals']['groups'] or resource['metadata_visible']
                or any(c['mode']!='deny' or c['metadata_visible'] for c in resource['columns'].values())):
            issues.append({'code':'security.new_resource_not_denied'})
    return issues


def expected_context(contract,case):
    persona=contract['personas'][case['persona_id']]
    groups=set(persona['groups']);attributes=dict(persona['attributes'])
    if case['scenario']=='unexpected_group':groups.update(persona['unexpected_groups'])
    if case['scenario']=='missing_attribute':
        for name in persona['required_attributes']:attributes.pop(name)
    return {'principal_id':persona['principal_id'],'groups':sorted(groups),'attributes':attributes,
            'destination_sha256':hash_json(contract['destination']),'snapshot_sha256':contract['snapshot_sha256'],
            'probe_sha256':case['probe_sha256'],'resource_id':case['resource_id'],'path':case['path']}


def evaluate_access(contract,current,candidate,readback=None,observations=None):
    report={'schema_version':1,'kind':'security_evaluation_report','status':'blocked','findings':[],
            'native_verified':False,'evidence_authenticated':False,'live_qualified':False,'protected_deployment_allowed':False,
            'policy_writes_performed':False,'assurance':'Local comparison only. Exact native readback and effective persona execution need external authentication.'}
    try:
        validate_contract(contract,current,candidate)
        report.update(contract_sha256=hash_json(contract),bindings=copy.deepcopy(contract['bindings']),
                      destination_sha256=hash_json(contract['destination']),candidate_sha256=state_hash(candidate),
                      capabilities=capabilities(contract['warehouse'],contract['framework']))
        report['findings']=_nonweakening(current,candidate)
        if report['findings']:
            report['handoff']='Retain existing controls and obtain a reviewed, qualified policy migration; opaque policy changes are not proven safe.'
            return report
        if state_hash(current)!=state_hash(candidate):
            report['findings'].append({'code':'security.policy_provisioning_unqualified'})
            report['handoff']='Automatic policy writes are unsupported. Have the security owner apply reviewed controls, inspect the new existing state, and freeze a new contract before protected deployment.'
            return report
        if readback is None or observations is None:
            report.update(status='pending',findings=[{'code':'security.readback_or_persona_evidence_missing'}]);return report
        validate_state(readback,contract)
        require(state_hash(readback)==state_hash(candidate),'security.native_readback_mismatch')
        _bounded(observations)
        require(type(observations) is dict and set(observations)=={'schema_version','kind','contract_sha256','state_sha256','bindings','destination','cases'}
                and type(observations['schema_version']) is int and observations['schema_version']==1
                and observations['kind']=='security_observations' and observations['contract_sha256']==hash_json(contract)
                and observations['state_sha256']==state_hash(candidate) and observations['bindings']==contract['bindings']
                and observations['destination']==contract['destination'] and type(observations['cases']) is dict,
                'security.observations_binding')
        expected={c['id']:c for c in contract['cases']}
        require(set(observations['cases'])<=set(expected),'security.unexpected_observation')
        for index,case in enumerate(contract['cases']):
            observation=observations['cases'].get(case['id'])
            if observation is None:
                report['findings'].append({'case_index':index,'code':'security.observation_missing'});continue
            if type(observation) is not dict or set(observation)!={'context','result'} or observation['context']!=expected_context(contract,case):
                report['findings'].append({'case_index':index,'code':'security.persona_context_mismatch'});continue
            result=observation['result']
            if type(result) is not dict or result!=case['expected'] or type(result.get('canary_visible')) is not bool or type(result.get('metadata_visible')) is not bool:
                report['findings'].append({'case_index':index,'code':'security.effective_access_mismatch'})
        missing=all(f['code']=='security.observation_missing' for f in report['findings'])
        report.update(status='locally_consistent' if not report['findings'] else 'pending' if missing else 'failed',
                      readback_sha256=state_hash(readback),observations_sha256=hash_json(observations),cases_compared=len(contract['cases']))
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError) as error:
        code=str(error)
        if re.fullmatch(r'security\.[a-z_]+',code) is None: code='security.invalid_stale_or_unproven_input'
        report.update(status='blocked');report['findings'].append({'code':code})
    return report


def main(argv=None):
    from omni_native import _read,_json,_private_file
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('contract','current','candidate','readback','observations','output'):
        parser.add_argument('--'+name,type=Path,required=name in ('contract','current','candidate','output'))
    args=parser.parse_args(argv)
    try:
        read=lambda p:_json(_read(p)) if p else None
        result=evaluate_access(read(args.contract),read(args.current),read(args.candidate),read(args.readback),read(args.observations))
        _private_file(args.output,result);print(json.dumps({'status':result['status'],'native_verified':False}))
        return 0 if result['status']=='locally_consistent' else 1
    except (ValueError,TypeError,KeyError,OSError):
        print(json.dumps({'status':'blocked','code':'security.invalid_input'}));return 1


if __name__=='__main__':raise SystemExit(main())
