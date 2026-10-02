#!/usr/bin/env python3
"""Compare independent observed metadata with expected state, then logical parity.

Deterministic comparison does not authenticate an export. The deployment runner
requires an independent signed acceptance bound to these exact observations.
"""
import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from ae_common import hash_json, load_json, require, write_json, _path
from metadata_contract import verify_contract
from metadata_observation import validate_observation, shape_discrepancies, physical_union


def verify_metadata(contract, observation, *, phase=None, release_id=None):
    verify_contract(contract)
    validate_observation(contract, observation)
    require(phase in (None, 'target_metadata', 'source_metadata'), 'Unknown metadata verification phase')
    if release_id is not None:
        require(observation['release_id'] == release_id, 'Metadata readback release differs')
    required = [r for r in contract['resources'] if r['disposition'] == 'required'
                and (phase is None or (r['resource_type'] == 'source') == (phase == 'source_metadata'))]
    issues = list(contract['blockers']) + shape_discrepancies(contract, observation)
    if not required:
        issues.append('No required resources in this verification scope; coverage cannot pass')
    rows = {r['id']: r for r in observation['resources']}
    definitions = {tuple(t['name']): t for t in observation['governance']}
    comments_matched, columns_matched, tags_matched = 0, 0, 0
    normalized = []

    def compare_tags(wanted, actual, label):
        nonlocal tags_matched
        result = []
        for tag in wanted:
            direct = [t for t in actual if t['name'] == tag['name'] and t['application'] == 'direct']
            if not direct or direct[0]['value'] != tag['value']:
                issues.append(label + ': missing or incorrect direct tag ' + tag['id'])
            else:
                tags_matched += 1
            governance = definitions.get(tuple(tag['name']))
            if governance is None or governance['policy_effects'] != 'none_verified':
                issues.append(label + ': tag governance/security effects unverified for ' + tag['id'])
            elif governance['allowed_values'] is not None and tag['value'] not in governance['allowed_values']:
                issues.append(label + ': tag value outside current governance definition')
            result.append({'id': tag['id'], 'value': direct[0]['value'] if direct else None, 'application': 'direct' if direct else None})
        return sorted(result, key=lambda x:x['id'])

    for resource in required:
        row = rows.get(resource['id'])
        if row is None:
            continue
        if row['comment'] != resource['description']:
            issues.append(resource['id'] + ': relation comment missing, empty or different')
        else:
            comments_matched += 1
        record = {'id': resource['id'], 'kind': resource['relation']['kind'], 'description': row['comment'],
                  'tags': compare_tags(resource['tags'], row['tags'], resource['id']), 'columns': []}
        columns = {c['name']:c for c in row['columns']}
        for column in resource['columns']:
            found = columns.get(column['name'])
            if found is None:
                continue
            label = resource['id'] + '.' + column['name']
            if found['comment'] != column['description']:
                issues.append(label + ': column comment missing, empty or different')
            else:
                columns_matched += 1
            record['columns'].append({'id':column['id'], 'data_type':found['data_type'], 'description':found['comment'],
                'tags':compare_tags(column['tags'],found['tags'],label), 'sensitivity':column['sensitivity']})
        record['columns'].sort(key=lambda c:c['id'])
        normalized.append(record)
    union = None
    if required and not shape_discrepancies(contract, observation):
        union = physical_union(contract, observation)
        if not union['passed']:
            issues.extend(union['errors'])
    issues = sorted(set(issues))
    result = {'schema_version':1, 'kind':'warehouse_metadata_verification',
        'passed':not issues, 'status':'expected_state_matched' if not issues else 'discrepancies',
        'phase':phase, 'contract_sha256':contract['contract_sha256'],
        'dictionary_sha256':contract['dictionary_sha256'], 'observation_sha256':observation['observation_sha256'],
        'target':contract['configuration']['target'], 'release_id':observation['release_id'],
        'candidate_sha256':contract['configuration']['candidate_sha256'],
        'collection_origin':observation['collection']['origin'], 'issues':issues, 'physical_schema':union,
        'counts':{'selected_resources':len(contract['resources']), 'required_resources':len(required),
                  'observed_required_resources':sum(r['id'] in rows for r in required),
                  'excluded_resources':sum(r['disposition']!='required' for r in contract['resources']),
                  'other_phase_resources':sum(r['disposition']=='required' for r in contract['resources'])-len(required),
                  'expected_columns':sum(len(r['columns']) for r in required),
                  'observed_columns':sum(len(rows[r['id']]['columns']) for r in required if r['id'] in rows),
                  'matching_relation_comments':comments_matched, 'matching_column_comments':columns_matched,
                  'matching_direct_tag_assignments':tags_matched,
                  'observed_tag_associations':sum(len(r['tags'])+sum(len(c['tags']) for c in r['columns']) for r in observation['resources'])},
        'exclusions':[{'id':r['id'],'disposition':r['disposition'],'reason':r['reason']} for r in contract['resources'] if r['disposition']!='required'],
        'normalized':sorted(normalized,key=lambda r:r['id']),
        'assurance':'Deterministic expected-state comparison only. Observation provenance, live execution and customer acceptance require independent authority.'}
    result['verification_sha256'] = hash_json(result)
    return result


def compare_environments(left_contract, left_observation, right_contract, right_observation, *, exceptions=()):
    for contract, observed in ((left_contract,left_observation),(right_contract,right_observation)):
        validate_observation(contract,observed,now=datetime.now(timezone.utc),max_age_seconds=900)
    left = verify_metadata(left_contract,left_observation)
    right = verify_metadata(right_contract,right_observation)
    require(left['passed'] and right['passed'], 'Each environment must match its expected metadata before parity')
    require(left['dictionary_sha256'] == right['dictionary_sha256'], 'Environment dictionaries differ; review a shared logical contract')
    require(left['candidate_sha256'] == right['candidate_sha256'], 'Environment candidate bindings differ; a separately approved release mapping is required')
    require(left_contract['configuration']['warehouse'] == right_contract['configuration']['warehouse'], 'Cross-warehouse type parity needs a separately qualified mapping')
    require(left_contract['configuration']['environment'] != right_contract['configuration']['environment'], 'Parity requires distinct environments')
    require(type(exceptions) in (list,tuple), 'Parity exceptions must be explicit')
    a,b = copy.deepcopy(left['normalized']),copy.deepcopy(right['normalized'])
    used = set()
    for item in exceptions:
        require(type(item) is dict and set(item)=={'resource_id','column_id','tag_id','reason','review_reference'}, 'Invalid parity exception')
        require(item['tag_id'] not in ('sensitivity','key_roles'), 'Classification and key differences are not environment exceptions')
        require(all(type(item[k]) is str and item[k].strip() for k in ('resource_id','tag_id','reason','review_reference')), 'Parity exception needs a reviewed reason')
        key=(item['resource_id'],item['column_id'],item['tag_id'])
        require(key not in used,'Duplicate parity exception');used.add(key)
        values=[]
        for side in (a,b):
            row=next((r for r in side if r['id']==item['resource_id']),None)
            require(row is not None,'Parity exception resource absent')
            if item['column_id'] is not None:
                row=next((c for c in row['columns'] if c['id']==item['column_id']),None)
            require(row is not None,'Parity exception column absent')
            tag=next((t for t in row['tags'] if t['id']==item['tag_id']),None)
            require(tag is not None,'Parity exception tag absent')
            values.append(tag['value']);tag['value']='<reviewed environment value>'
        require(values[0]!=values[1],'Unused parity exception')
    result={'schema_version':1,'kind':'warehouse_metadata_parity','passed':a==b,
            'comparison_scope':'metadata_only','release_parity_verified':False,
            'candidate_sha256':left['candidate_sha256'],
            'left_release_id':left['release_id'],'right_release_id':right['release_id'],
            'left_verification_sha256':left['verification_sha256'],'right_verification_sha256':right['verification_sha256'],
            'exceptions':list(exceptions),'issues':[] if a==b else ['Logical metadata differs after approved environment mapping'],
            'assurance':'Fresh supplied observations match a shared candidate metadata contract. Live provenance, promotion and release parity require independent signed authority.'}
    result['parity_sha256']=hash_json(result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('contract','observation','output'):
        parser.add_argument('--'+field,required=True,type=Path)
    parser.add_argument('--phase',choices=('target_metadata','source_metadata'))
    parser.add_argument('--release-id')
    args=parser.parse_args(argv)
    try:
        output=_path(args.output,must_exist=False);require(not output.exists(),'Verification output must be a new file')
        result=verify_metadata(load_json(args.contract),load_json(args.observation),phase=args.phase,release_id=args.release_id)
        write_json(output,result);print(json.dumps({'passed':result['passed'],'counts':result['counts'],'issues':result['issues']}))
        return 0 if result['passed'] else 1
    except (ValueError,OSError) as error:
        print('Metadata verification refused: '+str(error),file=sys.stderr);return 1


if __name__=='__main__':
    sys.exit(main())
