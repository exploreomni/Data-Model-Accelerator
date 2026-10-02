#!/usr/bin/env python3
"""Generate reviewed metadata differences and one-statement native SQL units.

No network or warehouse mutations. Comments are planned after the build against
an observed physical schema; new/missing objects require a new observation.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from ae_common import hash_json, load_json, require, write_json, _path
from metadata_contract import build_contract, verify_contract
from metadata_observation import shape_discrepancies, validate_observation


PRIVILEGES = {
    'snowflake': ['USAGE on the exact database and schema; object ownership for COMMENT.',
                  'For selected custom tags: authorized APPLY on each named tag plus the applicable object privileges.',
                  'Governance owner discovers definitions, allowed values, masking/propagation and edition. No grants are emitted.'],
    'databricks': ['Unity Catalog USE CATALOG and USE SCHEMA; table MODIFY or view ownership for comments.',
                   'Selected tags require APPLY TAG on the object and ASSIGN for governed tags; inspect ABAC policy effects.'],
    'bigquery': ['bigquery.tables.get and bigquery.tables.update on each selected relation; jobs.create in the execution project.',
                 'Column policy tags and Preview governance tags are outside this informational metadata route.'],
    'redshift': ['Connect to the exact database; COMMENT requires object ownership or a qualifying administrator.',
                 'AWS IAM authorizes the Data API separately; AWS resource tags are not column classifications.'],
    'clickhouse': ['Scoped ALTER COMMENT and ALTER MODIFY COLUMN privileges as required by the selected server version.',
                   'Observe the selected replica; coordinate separate cluster/replica qualification.'],
    'motherduck': ['Authenticated access to the exact remote database and authorization to change the selected objects.',
                   'Qualify server/extension version and object dependency restrictions remotely.'],
}


def plan_metadata(contract, before):
    from metadata_sql import render_comment, render_tag, read_queries
    verify_contract(contract)
    validate_observation(contract, before)
    warehouse = contract['configuration']['warehouse']
    blockers = list(contract['blockers']) + shape_discrepancies(contract, before)
    observed = {r['id']: r for r in before['resources']}
    definitions = {tuple(t['name']): t for t in before['governance']}
    operations, unchanged, governance = [], [], []
    queries = []

    def add(resource, column, kind, old, new, sql, tag=None):
        identity = {'resource_id': resource['id'], 'column_id': column['id'] if column else None,
                    'kind': kind, 'tag_id': tag['id'] if tag else None}
        if old == new:
            unchanged.append(identity)
            return
        sql = sql.rstrip('\n') + '\n'
        sql_hash = hashlib.sha256(sql.encode()).hexdigest()
        operations.append({'id': 'metadata-' + hash_json(identity)[:24], **identity,
            'phase': 'source_metadata' if resource['resource_type'] == 'source' else 'target_metadata',
            'relation': resource['relation'], 'column': column['name'] if column else None,
            'tag': tag, 'before': old, 'after': new,
            'object_version': observed[resource['id']]['object_version'],
            'sql': sql, 'sha256': sql_hash})

    for resource in contract['resources']:
        if resource['disposition'] != 'required':
            continue
        actual = observed.get(resource['id'])
        if actual is None or actual['relation'] != resource['relation']:
            continue
        try:
            queries += [{'resource_id': resource['id'], **q} for q in read_queries(warehouse, resource['relation'])]
            add(resource, None, 'comment', actual['comment'], resource['description'],
                render_comment(warehouse, resource['relation'], None, resource['description']))
            pairs = [(None, resource['tags'], actual['tags'])]
            columns = {c['name']: c for c in actual['columns']}
            for column in resource['columns']:
                found = columns.get(column['name'])
                if found is None:
                    continue
                add(resource, column, 'comment', found['comment'], column['description'],
                    render_comment(warehouse, resource['relation'], column['name'], column['description']))
                pairs.append((column, column['tags'], found['tags']))
            for column, desired, current in pairs:
                for tag in desired:
                    definition = definitions.get(tuple(tag['name']))
                    if definition is None:
                        governance.append({'name': tag['name'], 'requested_value': tag['value'],
                                           'action': 'Governance owner must provision/review this tag separately, then recollect.'})
                        blockers.append(resource['id'] + ': governance definition is missing: ' + '.'.join(tag['name']))
                    elif definition['policy_effects'] != 'none_verified':
                        blockers.append(resource['id'] + ': tag policy effects are unknown or security-bearing')
                    elif definition['allowed_values'] is not None and tag['value'] not in definition['allowed_values']:
                        blockers.append(resource['id'] + ': tag value conflicts with the governed definition')
                    # Effective/inherited values do not prove the required direct assignment.
                    direct = [t['value'] for t in current if t['name'] == tag['name'] and t['application'] == 'direct']
                    add(resource, column, 'tag', direct[0] if direct else None, tag['value'],
                        render_tag(warehouse, resource['relation'], column['name'] if column else None, tag), tag)
        except ValueError as error:
            blockers.append(resource['id'] + ': ' + str(error))
    result = {'schema_version': 1, 'kind': 'warehouse_metadata_plan',
              'contract': copy.deepcopy(contract), 'before': copy.deepcopy(before),
              'contract_sha256': contract['contract_sha256'], 'before_sha256': before['observation_sha256'],
              'status': 'blocked' if blockers else 'ready' if operations else 'no_op',
              'automatic_live_dispatch': 'blocked_pending_authenticated_native_drift_collector',
              'operations': operations, 'unchanged': unchanged, 'blockers': sorted(set(blockers)),
              'governance_requests': governance, 'read_queries': queries,
              'privilege_requirements': PRIVILEGES[warehouse],
              'phases': ['governance_readiness', 'framework_build', 'target_metadata', 'source_metadata', 'readback', 'consumer_handoff'],
              'counts': {'resources_selected': len(contract['resources']),
                         'resources_required': sum(r['disposition'] == 'required' for r in contract['resources']),
                         'resources_excluded': sum(r['disposition'] != 'required' for r in contract['resources']),
                         'comment_writes': sum(o['kind'] == 'comment' for o in operations),
                         'direct_tag_writes': sum(o['kind'] == 'tag' for o in operations),
                         'native_statements': len(operations), 'unchanged_assignments': len(unchanged)},
              'qualification': 'Candidate SQL and structural checks only. The release coordinator requires destination-bound authorization, fresh independently attested preflight and readback.'}
    result['plan_sha256'] = hash_json(result)
    return result


def verify_plan(plan):
    require(type(plan) is dict and plan.get('kind') == 'warehouse_metadata_plan', 'Invalid metadata plan')
    require(plan.get('plan_sha256') == hash_json({k:v for k,v in plan.items() if k != 'plan_sha256'}), 'Metadata plan changed')
    require(plan_metadata(plan['contract'], plan['before']) == plan, 'Metadata plan differs from canonical projection')
    return plan


def check_preconditions(plan, current, *, completed=(), now=None, max_age_seconds=900):
    """Recheck touched values and object incarnation before any remaining writes.

    Completed IDs come from the authenticated runner journal, never caller claims.
    This is optimistic detection, not an atomic lock: an external exclusive change
    window/lease and post-write readback remain required for automatic execution.
    """
    verify_plan(plan)
    require(not plan['blockers'], 'Blocked metadata plan cannot execute')
    contract = plan['contract']
    validate_observation(contract, current, now=now, max_age_seconds=max_age_seconds)
    issues = shape_discrepancies(contract, current)
    rows = {r['id']: r for r in current['resources']}
    all_ids = {o['id'] for o in plan['operations']}
    require(set(completed) <= all_ids, 'Unknown completed operation ID')
    require(current['governance'] == plan['before']['governance'], 'Governance definition/policy drift requires a new plan')
    baseline = {r['id']: copy.deepcopy(r) for r in plan['before']['resources']}
    for operation in plan['operations']:
        if operation['id'] not in completed:
            continue
        row = baseline[operation['resource_id']]
        field = row if operation['column'] is None else next(c for c in row['columns'] if c['name'] == operation['column'])
        if operation['kind'] == 'comment':
            field['comment'] = operation['after']
        else:
            field['tags'] = [t for t in field['tags'] if not (t['name'] == operation['tag']['name'] and t['application'] == 'direct')]
            field['tags'].append({'name': operation['tag']['name'], 'value': operation['after'], 'application': 'direct'})
    def normalized(row):
        row = copy.deepcopy(row)
        row['tags'] = sorted(row['tags'], key=hash_json)
        row['columns'] = sorted(row['columns'], key=lambda c: c['name'])
        for column in row['columns']:
            column['tags'] = sorted(column['tags'], key=hash_json)
        return row
    for resource in contract['resources']:
        key = resource['id']
        if resource['disposition'] == 'required' and key in rows and key in baseline and normalized(rows[key]) != normalized(baseline[key]):
            issues.append(key + ': concurrent metadata drift or recreated object; full baseline no longer matches')
    for operation in plan['operations']:
        row = rows.get(operation['resource_id'])
        if row is None:
            continue
        if row['object_version'] != operation['object_version']:
            issues.append(operation['id'] + ': object was recreated or changed')
        field = row
        if operation['column'] is not None:
            field = next((c for c in row['columns'] if c['name'] == operation['column']), None)
        if field is None:
            continue
        if operation['kind'] == 'comment':
            value = field['comment']
        else:
            direct = [t['value'] for t in field['tags'] if t['name'] == operation['tag']['name'] and t['application'] == 'direct']
            value = direct[0] if direct else None
        expected = operation['after'] if operation['id'] in completed else operation['before']
        if value != expected:
            issues.append(operation['id'] + ': concurrent metadata drift; do not overwrite')
    require(not issues, '; '.join(issues))
    return {'status': 'preconditions_match', 'observation_sha256': current['observation_sha256'],
            'assurance': 'Structural comparison; authenticated collector and change lease required.'}


def export_plan(plan, output):
    verify_plan(plan)
    destination = _path(output, must_exist=False)
    require(not destination.exists() and destination.parent.is_dir(), 'Metadata export requires a new directory')
    destination.mkdir(mode=0o700)
    write_json(destination / 'metadata-plan.json', plan)
    # Blocked previews retain proposed SQL inside JSON; they are not runnable files.
    if not plan['blockers']:
        for index, operation in enumerate(plan['operations']):
            path = destination / operation['phase']
            path.mkdir(exist_ok=True)
            (path / ('%05d-%s.sql' % (index + 1, operation['id']))).write_text(operation['sql'], encoding='utf-8')
    return str(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dictionary', type=Path, required=True)
    parser.add_argument('--configuration', type=Path, required=True)
    parser.add_argument('--observation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        contract = build_contract(load_json(args.dictionary), load_json(args.configuration))
        plan = plan_metadata(contract, load_json(args.observation))
        export_plan(plan, args.output)
        print(json.dumps({'status': plan['status'], 'counts': plan['counts'], 'blockers': plan['blockers']}))
        return 1 if plan['blockers'] else 0
    except (ValueError, OSError) as error:
        print('Metadata planning refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
