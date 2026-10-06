"""Deterministic lifecycle planning and imported-evidence comparison, never a writer.

Reparse exact authored/effective bytes; do not trust an imported dependency graph
or its status. No provider API, credential, raw query result or authenticated
evidence is created here. A passed comparison cannot authorize a native action.
"""
import argparse
import copy
import json
from pathlib import Path
import re

from omni_contract import _bounded, canonical_hash
from omni_inventory import decode_files, inspect_model

VERSION = 'omni-lifecycle-v1'
SHA = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z')
LANES = ('reference_scan', 'native_compilation', 'query_execution', 'access')
BINDINGS = {'baseline_inventory_sha256', 'candidate_inventory_sha256', 'baseline_files_sha256',
            'candidate_files_sha256', 'context_sha256', 'target_sha256', 'catalogue_sha256',
            'expected_remote_sha256', 'knowledge_sha256'}


class LifecycleError(ValueError):
    """Only stable, value-free codes cross the public boundary."""


def need(ok, code):
    if not ok:
        raise LifecycleError(code)


def sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def identity(value):
    return type(value) is str and ID.fullmatch(value) is not None


def bounded(value):
    _bounded(value)
    need(len(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()) <= 8 * 1024 * 1024,
         'lifecycle.input_limit')


def exact(value, keys, code):
    need(type(value) is dict and set(value) == set(keys), code)


def sequence(value, *, maximum=5000):
    return type(value) is list and len(value) <= maximum and all(type(x) is str for x in value) and len(set(value)) == len(value)


def _inventory(value):
    bounded(value)
    need(type(value) is dict and value.get('schema_version') == 1 and value.get('kind') == 'omni_inventory',
         'lifecycle.inventory_schema')
    need(value.get('inventory_sha256') == canonical_hash({k:v for k,v in value.items() if k != 'inventory_sha256'}),
         'lifecycle.inventory_integrity')
    rebuilt = inspect_model(decode_files(value['authored_files']), value['context'],
                            effective_files=decode_files(value['effective_files']))
    # Coverage may have used a separately supplied expected inventory. It is not
    # recoverable from raw files and never establishes independence here.
    ignored = {'inventory_sha256', 'coverage', 'findings', 'status'}
    need(set(value) == set(rebuilt) and all(value[k] == rebuilt[k] for k in rebuilt if k not in ignored),
         'lifecycle.inventory_reparse_mismatch')
    need([f for f in value['findings'] if not f['code'].startswith('coverage.')] == rebuilt['findings'],
         'lifecycle.inventory_findings_mismatch')
    return rebuilt


def _files(inventory):
    return {path:body.decode('utf-8') for path,body in decode_files(inventory['authored_files']).items()}


def contract_bindings(baseline, candidate, context, target, expected_remote, knowledge_sha256):
    """Convenience pins, not review or provenance authentication."""
    _inventory(baseline); _inventory(candidate)
    need(sha(knowledge_sha256), 'lifecycle.knowledge_pin')
    return {'baseline_inventory_sha256': baseline['inventory_sha256'],
            'candidate_inventory_sha256': candidate['inventory_sha256'],
            'baseline_files_sha256': canonical_hash(_files(baseline)),
            'candidate_files_sha256': canonical_hash(_files(candidate)),
            'context_sha256': canonical_hash(context), 'target_sha256': canonical_hash(target),
            'catalogue_sha256': context['catalogue_sha256'],
            'expected_remote_sha256': canonical_hash(expected_remote), 'knowledge_sha256': knowledge_sha256}


def _nodes(inventory):
    return {row['id']: row for row in inventory['objects'] + inventory['fields']}


def _impact(before, after):
    old, new = _nodes(before), _nodes(after)
    changes = {node: 'added' if node not in old else 'deleted' if node not in new else 'changed'
               for node in set(old) | set(new) if node not in old or node not in new
               or old[node]['definition_sha256'] != new[node]['definition_sha256']}
    reverse = {}
    def depends(source, target): reverse.setdefault(target, set()).add(source)
    for inventory in (before, after):
        for edge in inventory['dependencies']:
            if edge['status'] == 'resolved': depends(edge['from'], edge['to'])
        for field in inventory['fields']:
            # Conservatively preserve population/grouping/owner effects in both
            # directions rather than claiming isolated field-level SQL semantics.
            depends(field['id'], field['object_id']); depends(field['object_id'], field['id'])
        relations = [r['id'] for r in inventory['objects'] if r['kind'] == 'relationships']
        models = [r['id'] for r in inventory['objects'] if r['kind'] == 'model']
        for node in inventory['objects']:
            if node['parent_id']:
                depends(node['id'], node['parent_id']); depends(node['parent_id'], node['id'])
            if node['kind'] == 'topic':
                for relation in relations: depends(node['id'], relation)
            for model in models:
                if node['id'] != model: depends(node['id'], model)
    affected, pending = set(changes), list(changes)
    while pending:
        for dependent in reverse.get(pending.pop(), ()):
            if dependent not in affected:
                affected.add(dependent); pending.append(dependent)
    return changes, affected, old, new


def assess_lifecycle(contract, baseline_inventory, candidate_inventory, observations=None):
    """Compare pinned declarations. ``passed`` means local consistency only.

    ``preflight_status`` covers route, input graph/coverage, environment, and
    known impact failures. Missing runtime observations keep individual lanes
    pending; they cannot become access/compilation/execution evidence by proxy.
    """
    report = {'schema_version': 1, 'kind': 'omni_lifecycle_assessment', 'version': VERSION,
              'status': 'pending', 'preflight_status': 'pending', 'findings': [],
              'changed_nodes': [], 'affected_node_sha256': [], 'affected_content_sha256': [],
              'unrelated_baseline_issue_sha256': [], 'lanes': {lane: {'status': 'pending', 'case_count': 0} for lane in LANES},
              'native_verified': False, 'security_verified': False, 'deployment_authorized': False,
              'imported_evidence_authenticated': False,
              'limitations': ['Imported evidence and declared coverage are not authenticated.',
                              'No refresh, merge, promotion, Git edit, or physical-to-virtual migration is performed.',
                              'Graph closure is conservative; unsupported references keep qualification pending.']}
    preflight = []
    def issue(code, severity='pending', *, gate=True):
        item = {'code': code, 'severity': severity}
        if item not in report['findings']: report['findings'].append(item)
        if gate: preflight.append(severity)
    try:
        bounded([contract, observations])
        exact(contract, {'schema_version','kind','operation','bindings','route','environment','content_inventory','cases'}, 'lifecycle.contract_shape')
        need(type(contract['schema_version']) is int and contract['schema_version'] == 1 and contract['kind'] == 'omni_lifecycle_contract', 'lifecycle.contract_version')
        need(contract['operation'] in ('validate','update_and_validate','query'), 'lifecycle.operation')
        exact(contract['bindings'], BINDINGS, 'lifecycle.bindings')
        need(all(sha(v) for v in contract['bindings'].values()), 'lifecycle.bindings')
        before, after = _inventory(baseline_inventory), _inventory(candidate_inventory)
        pins = contract['bindings']
        need(pins['baseline_inventory_sha256'] == baseline_inventory['inventory_sha256'] and
             pins['candidate_inventory_sha256'] == candidate_inventory['inventory_sha256'] and
             pins['baseline_files_sha256'] == canonical_hash(_files(before)) and
             pins['candidate_files_sha256'] == canonical_hash(_files(after)), 'lifecycle.source_pin_mismatch')
        report['contract_sha256'] = canonical_hash(contract)
        report['observations_sha256'] = canonical_hash(observations)
        changes, affected, old, new = _impact(before, after)
        nodes = set(old) | set(new)
        report['changed_nodes'] = sorted([{'node_sha256': canonical_hash(node), 'change': change} for node,change in changes.items()], key=lambda v:v['node_sha256'])
        report['affected_node_sha256'] = sorted(canonical_hash(node) for node in affected)
        if before['status'] != 'inspected' or after['status'] != 'inspected':
            issue('lifecycle.dependency_graph_incomplete')
        route = contract['route']
        exact(route, {'mode','evidence_sha256','attached_content_ids'}, 'lifecycle.route_shape')
        need(route['mode'] in ('native','git_leader','git_follower','unknown') and
             (route['evidence_sha256'] is None or sha(route['evidence_sha256'])) and sequence(route['attached_content_ids']), 'lifecycle.route')
        if route['mode'] == 'unknown' or route['evidence_sha256'] is None: issue('lifecycle.route_unverified')
        if contract['operation'] == 'update_and_validate' and route['mode'] == 'git_follower':
            issue('lifecycle.follower_read_only', 'failed')

        environment = contract['environment']
        exact(environment, {'warehouse','environment','connection_id','environment_connection_id','catalogue_sha256','physical_resolution','dbt'}, 'lifecycle.environment_shape')
        need(environment['warehouse'] in ('snowflake','databricks','bigquery','redshift','clickhouse','motherduck') and
             environment['environment'] == 'development' and identity(environment['connection_id']) and
             identity(environment['environment_connection_id']) and environment['catalogue_sha256'] == pins['catalogue_sha256'], 'lifecycle.environment_binding')
        physical = environment['physical_resolution']
        need(type(physical) is list and len(physical) <= 1000, 'lifecycle.physical_resolution')
        physical_ids, fallbacks = set(), set()
        for record in physical:
            exact(record, {'node_id','namespace','environment','built','synthetic','evidence_sha256'}, 'lifecycle.physical_record')
            need(record['node_id'] in new and record['node_id'] not in physical_ids and
                 new[record['node_id']].get('kind') == 'view' and type(record['namespace']) is dict and
                 bool(record['namespace']) and all(identity(k) and type(v) is str and v for k,v in record['namespace'].items()) and
                 record['environment'] in ('development','production') and type(record['built']) is bool and
                 type(record['synthetic']) is bool and sha(record['evidence_sha256']), 'lifecycle.physical_record')
            physical_ids.add(record['node_id'])
            if not record['synthetic']: issue('lifecycle.synthetic_development_only', 'failed')
            if record['environment'] == 'production':
                fallbacks.add(record['node_id']); issue('lifecycle.production_resolution_requires_separate_qualification', 'failed')
            if not record['built']: fallbacks.add(record['node_id'])
        if not physical: issue('lifecycle.physical_resolution_missing')
        dbt = environment['dbt']
        if dbt is None:
            if fallbacks: issue('lifecycle.deferral_missing', 'failed')
        else:
            exact(dbt, {'environment_id','manifest_sha256','build','refresh','deferral'}, 'lifecycle.dbt_shape')
            need(identity(dbt['environment_id']) and sha(dbt['manifest_sha256']), 'lifecycle.dbt_identity')
            build, refresh, deferral = dbt['build'], dbt['refresh'], dbt['deferral']
            exact(build, {'status','environment_id','manifest_sha256','evidence_sha256'}, 'lifecycle.build_shape')
            exact(refresh, {'status','environment_id','manifest_sha256','build_evidence_sha256','physical_resolution_sha256','evidence_sha256'}, 'lifecycle.refresh_shape')
            for event in (build, refresh):
                need(event['status'] in ('completed','pending','failed') and identity(event['environment_id']) and
                     sha(event['manifest_sha256']) and sha(event['evidence_sha256']), 'lifecycle.dbt_event')
                if event['environment_id'] != dbt['environment_id'] or event['manifest_sha256'] != dbt['manifest_sha256']:
                    issue('lifecycle.dbt_environment_or_manifest_drift', 'failed')
                if event['status'] != 'completed': issue('lifecycle.dbt_build_or_refresh_incomplete', 'failed' if event['status'] == 'failed' else 'pending')
            need(sha(refresh['build_evidence_sha256']) and sha(refresh['physical_resolution_sha256']), 'lifecycle.refresh_pins')
            if refresh['build_evidence_sha256'] != build['evidence_sha256'] or refresh['physical_resolution_sha256'] != canonical_hash(physical):
                issue('lifecycle.refresh_chain_drift', 'failed')
            exact(deferral, {'enabled','production_fallback_acknowledged','fallback_nodes'}, 'lifecycle.deferral_shape')
            need(type(deferral['enabled']) is bool and type(deferral['production_fallback_acknowledged']) is bool and sequence(deferral['fallback_nodes']), 'lifecycle.deferral')
            if (set(deferral['fallback_nodes']) != fallbacks or (fallbacks and not deferral['enabled']) or
                    (any(r['environment'] == 'production' for r in physical) and not deferral['production_fallback_acknowledged'])):
                issue('lifecycle.deferral_resolution_unacknowledged', 'failed')

        content = contract['content_inventory']
        exact(content, {'complete','expected_ids','items','evidence_sha256'}, 'lifecycle.content_shape')
        need(type(content['complete']) is bool and sequence(content['expected_ids']) and
             all(identity(i) for i in content['expected_ids']) and type(content['items']) is list and
             len(content['items']) <= 5000 and (content['evidence_sha256'] is None or sha(content['evidence_sha256'])), 'lifecycle.content_inventory')
        content_ids, impacted = set(), set()
        for item in content['items']:
            exact(item, {'id','definition_sha256','dependencies','attached_to_branch'}, 'lifecycle.content_item')
            need(identity(item['id']) and item['id'] not in content_ids and sha(item['definition_sha256']) and
                 sequence(item['dependencies']) and bool(item['dependencies']) and type(item['attached_to_branch']) is bool,
                 'lifecycle.content_item')
            content_ids.add(item['id'])
            if not set(item['dependencies']) <= nodes: issue('lifecycle.content_dependency_unresolved')
            if set(item['dependencies']) & affected: impacted.add(item['id'])
        if not content['complete'] or content['evidence_sha256'] is None or set(content['expected_ids']) != content_ids:
            issue('lifecycle.content_coverage_incomplete')
        if set(route['attached_content_ids']) != {item['id'] for item in content['items'] if item['attached_to_branch']}:
            issue('lifecycle.attached_content_omitted', 'failed')
        report['affected_content_sha256'] = sorted(canonical_hash(i) for i in impacted)

        cases = contract['cases']; seen = set()
        need(type(cases) is list and len(cases) <= 5000, 'lifecycle.cases')
        for case in cases:
            exact(case, {'id','lane','node_ids','principal_id','path','query_sha256','attributes_sha256','timezone','expected'}, 'lifecycle.case_shape')
            need(identity(case['id']) and case['id'] not in seen and case['lane'] in LANES[1:] and
                 sequence(case['node_ids']) and bool(case['node_ids']) and set(case['node_ids']) <= set(new) and
                 identity(case['principal_id']) and case['path'] in ('omni_query','omni_drill','omni_metadata','omni_export') and
                 sha(case['query_sha256']) and sha(case['attributes_sha256']) and type(case['timezone']) is str,
                 'lifecycle.case')
            from zoneinfo import ZoneInfo
            ZoneInfo(case['timezone'])
            expected = case['expected']
            exact(expected, {'outcome','row_count','population_sha256'}, 'lifecycle.expected_shape')
            need(expected['outcome'] in ('pass','deny') and (expected['row_count'] is None or type(expected['row_count']) is int and expected['row_count'] >= 0)
                 and (expected['population_sha256'] is None or sha(expected['population_sha256'])), 'lifecycle.expected')
            if case['lane'] == 'native_compilation':
                need(expected['outcome'] == 'pass' and expected['row_count'] is None and expected['population_sha256'] is None, 'lifecycle.compilation_not_execution')
            elif expected['outcome'] == 'deny':
                need(case['lane'] == 'access' and expected['row_count'] is None and expected['population_sha256'] is None, 'lifecycle.denial_no_data')
            else:
                need(type(expected['row_count']) is int and sha(expected['population_sha256']), 'lifecycle.expected_population')
            seen.add(case['id']); report['lanes'][case['lane']]['case_count'] += 1

        captures = None
        if observations is not None:
            exact(observations, {'schema_version','kind','contract_sha256','baseline','candidate','cases'}, 'lifecycle.observations_shape')
            need(type(observations['schema_version']) is int and observations['schema_version'] == 1 and
                 observations['kind'] == 'omni_lifecycle_observations' and observations['contract_sha256'] == canonical_hash(contract) and
                 type(observations['cases']) is dict and set(observations['cases']) <= seen, 'lifecycle.observations_binding')
            captures = {}
            for label, inventory, scoped_nodes in (('baseline',baseline_inventory,set(old)), ('candidate',candidate_inventory,set(new))):
                capture = observations[label]
                if capture is None: continue
                exact(capture, {'inventory_sha256','content_inventory_sha256','evidence_sha256','complete','issues'}, 'lifecycle.capture_shape')
                need(capture['inventory_sha256'] == inventory['inventory_sha256'] and capture['content_inventory_sha256'] == canonical_hash(content) and
                     sha(capture['evidence_sha256']) and type(capture['complete']) is bool and type(capture['issues']) is list and len(capture['issues']) <= 5000,
                     'lifecycle.capture_binding')
                issues = {}
                for finding in capture['issues']:
                    exact(finding, {'fingerprint_sha256','node_ids','content_ids','severity'}, 'lifecycle.issue_shape')
                    need(sha(finding['fingerprint_sha256']) and finding['fingerprint_sha256'] not in issues and
                         sequence(finding['node_ids']) and sequence(finding['content_ids']) and
                         (finding['node_ids'] or finding['content_ids']) and set(finding['node_ids']) <= scoped_nodes and
                         set(finding['content_ids']) <= content_ids and finding['severity'] in ('error','warning'), 'lifecycle.issue')
                    issues[finding['fingerprint_sha256']] = finding
                captures[label] = issues
                if not capture['complete']: issue('lifecycle.content_scan_incomplete')
            previous = captures.get('baseline', {})
            current = captures.get('candidate', {})
            # A missing post-change scan cannot erase affected known errors.
            for key, finding in previous.items():
                affected_issue = bool(set(finding['node_ids']) & affected or set(finding['content_ids']) & impacted)
                if finding['severity'] == 'error' and affected_issue and ('candidate' not in captures or key in current):
                    issue('lifecycle.affected_baseline_failure', 'failed')
                elif not affected_issue and key in current and finding == current[key]:
                    report['unrelated_baseline_issue_sha256'].append(key)
            for key, finding in current.items():
                if finding['severity'] == 'error' and (key not in previous or finding != previous[key]):
                    issue('lifecycle.new_content_failure', 'failed')
            if set(captures) == {'baseline','candidate'} and all(observations[k]['complete'] for k in captures):
                report['lanes']['reference_scan']['status'] = 'failed' if any(i['code'] in ('lifecycle.affected_baseline_failure','lifecycle.new_content_failure') for i in report['findings']) else 'passed'
            for lane in LANES[1:]:
                selected = [case for case in cases if case['lane'] == lane]
                if not selected: continue
                statuses = []
                for case in selected:
                    observed = observations['cases'].get(case['id'])
                    if observed is None: statuses.append('pending'); continue
                    exact(observed, {'case_sha256','target_sha256','candidate_sha256','context_sha256','evidence_sha256','actual'}, 'lifecycle.case_observation_shape')
                    need(observed['case_sha256'] == canonical_hash(case) and observed['target_sha256'] == pins['target_sha256'] and
                         observed['candidate_sha256'] == pins['candidate_files_sha256'] and observed['context_sha256'] == pins['context_sha256'] and
                         sha(observed['evidence_sha256']), 'lifecycle.case_observation_binding')
                    actual = observed['actual']
                    exact(actual, {'outcome','row_count','population_sha256'}, 'lifecycle.case_actual_shape')
                    need(actual['outcome'] in ('pass','deny','error') and
                         (actual['row_count'] is None or type(actual['row_count']) is int and actual['row_count'] >= 0) and
                         (actual['population_sha256'] is None or sha(actual['population_sha256'])), 'lifecycle.case_actual')
                    statuses.append('passed' if observed['actual'] == case['expected'] else 'failed')
                if lane == 'access':
                    scopes = {}
                    for case in selected:
                        scope = canonical_hash({k:case[k] for k in ('principal_id','path','query_sha256','timezone','node_ids')})
                        scopes.setdefault(scope,set()).add(case['expected']['outcome'])
                    if any(outcomes != {'pass','deny'} for outcomes in scopes.values()):
                        statuses.append('pending'); issue('lifecycle.access_negative_coverage_missing', gate=False)
                status = 'failed' if 'failed' in statuses else 'pending' if 'pending' in statuses else 'passed'
                report['lanes'][lane]['status'] = status
                if status == 'failed': issue('lifecycle.' + lane + '_case_failed', 'failed')
        if captures is None or 'baseline' not in captures:
            issue('lifecycle.baseline_scan_missing')
        report['preflight_status'] = 'failed' if 'failed' in preflight else 'pending' if preflight else 'passed'
        report['status'] = ('failed' if report['preflight_status'] == 'failed' else 'passed'
                            if report['preflight_status'] == 'passed' and all(r['status'] == 'passed' for r in report['lanes'].values()) else 'pending')
    except LifecycleError as error:
        issue(str(error), 'failed'); report['status'] = report['preflight_status'] = 'failed'
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError, UnicodeError):
        issue('lifecycle.invalid_or_unsupported_input', 'failed'); report['status'] = report['preflight_status'] = 'failed'
    report['findings'] = sorted(report['findings'], key=lambda row:(row['code'],row['severity']))
    report['unrelated_baseline_issue_sha256'].sort()
    report['assessment_sha256'] = canonical_hash(report)
    return report


def prepare_request(contract, baseline_inventory, candidate_inventory, observations=None):
    report = assess_lifecycle(contract, baseline_inventory, candidate_inventory, observations)
    return {'schema_version': 1, 'kind': 'omni_lifecycle_request', 'contract': copy.deepcopy(contract),
            'baseline_inventory': copy.deepcopy(baseline_inventory), 'candidate_inventory': copy.deepcopy(candidate_inventory),
            'observations': copy.deepcopy(observations), 'assessment_sha256': report['assessment_sha256']}


def verify_request(payload, *, files, context, target, expected_remote, operation, query=None, query_mode=None, timezone=None):
    """Recompute local gates and exact native bindings. Never authenticates input."""
    exact(payload, {'schema_version','kind','contract','baseline_inventory','candidate_inventory','observations','assessment_sha256'}, 'lifecycle.request_shape')
    need(type(payload['schema_version']) is int and payload['schema_version'] == 1 and payload['kind'] == 'omni_lifecycle_request', 'lifecycle.request_version')
    contract = payload['contract']
    report = assess_lifecycle(contract, payload['baseline_inventory'], payload['candidate_inventory'], payload['observations'])
    need(payload['assessment_sha256'] == report['assessment_sha256'], 'lifecycle.assessment_changed')
    need(report['preflight_status'] == 'passed', 'lifecycle.preflight_not_passed')
    expected = contract_bindings(payload['baseline_inventory'], payload['candidate_inventory'], context, target, expected_remote, contract['bindings']['knowledge_sha256'])
    need(contract['bindings'] == expected and contract['operation'] == operation and canonical_hash(files) == expected['candidate_files_sha256'], 'lifecycle.native_binding_mismatch')
    env = contract['environment']
    need(env['warehouse'] == context['warehouse'] and all(env[k] == target[k] for k in ('environment','connection_id','environment_connection_id')), 'lifecycle.native_environment_mismatch')
    objects = _nodes(payload['candidate_inventory'])
    physical = {objects[r['node_id']]['name']:r for r in env['physical_resolution']}
    need(len(physical) == len(env['physical_resolution']) and set(physical) == set(context['bindings']) and
         all(physical[name]['namespace'] == binding['namespace'] for name,binding in context['bindings'].items()), 'lifecycle.physical_catalogue_mismatch')
    need(all(case['principal_id'] == target['principal_id'] for case in contract['cases']), 'lifecycle.selected_principal_mismatch')
    if operation == 'query':
        lane = 'native_compilation' if query_mode == 'plan' else 'query_execution'
        need(any(case['lane'] == lane and case['query_sha256'] == canonical_hash(query) and case['timezone'] == timezone
                 for case in contract['cases']), 'lifecycle.selected_query_case_missing')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        from omni_native import _json, _read, _private_file
        value = _json(_read(args.request))
        exact(value, {'contract','baseline_inventory','candidate_inventory','observations'}, 'lifecycle.cli_shape')
        report = assess_lifecycle(**value)
        _private_file(args.output, report)
        print(json.dumps({'status': report['status'], 'preflight_status': report['preflight_status'], 'native_verified': False}))
        return 0 if report['status'] == 'passed' else 1
    except (ValueError, TypeError, KeyError, OSError):
        print(json.dumps({'status': 'failed', 'code': 'lifecycle.invalid_or_unavailable_input', 'native_verified': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
