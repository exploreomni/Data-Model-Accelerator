"""Typed metadata phases for the existing signed, journaled deployment runner.

This bridge never calls a warehouse. Native transport remains in the established
coordinator. A separately prepared metadata handoff links an immutable completed
build; the original build handoff stays frozen. Imported flags cannot authorize.
"""
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from ae_common import hash_json, load_json, require
from metadata_contract import relation_key
from metadata_observation import timestamp
from plan_warehouse_metadata import verify_plan, check_preconditions

CHECKS = {'metadata_readback', 'metadata_physical_coverage', 'metadata_governance'}


def target_binding(destination_id, target):
    from deployment_workflow import digest
    return {'id': destination_id, 'identity': {'deployment_target_sha256': digest(target)}}


def candidate_binding(parent_plan):
    """Pin the exact executable artifact set and immutable commit of the build."""
    artifacts = [a for a in parent_plan['selected_artifacts'] if a['role'] not in ('documentation', 'semantic')]
    require(artifacts, 'Parent build has no executable artifact inventory')
    # Bind all companion project/macros/config files as well as entrypoint SQL.
    return hash_json({'commit_sha': parent_plan['commit_sha'], 'selected': artifacts,
                      'complete_handoff': parent_plan['artifact_manifest']})


def configuration_template(configuration):
    """Review before build; the exact candidate hash is filled after freezing it."""
    value = copy.deepcopy(configuration)
    value.pop('candidate_sha256', None)
    value['kind'] = 'metadata_configuration_template'
    return value


def reviewed_policy(config, state):
    require(config['metadata_policy'] == state['answers'].get('metadata_policy'),
            'Metadata policy differs from the recorded discovery selection')


def reviewed_contract(plan, contract):
    import deployment_workflow as runner
    from ae_common import _pairs, _float, _nonfinite, MAX_JSON_BYTES
    reviewed_dictionary, reviewed_configuration = False, False
    for artifact in plan['artifact_manifest']:
        if Path(artifact['path']).suffix.lower() != '.json':
            continue
        data = runner._stable_bytes(Path(plan['artifact_root']) / runner.relative_path(artifact['path']))
        require(hashlib.sha256(data).hexdigest() == artifact['sha256'],
                'Frozen metadata artifact changed after build review')
        require(len(data) <= MAX_JSON_BYTES, 'Metadata JSON artifact exceeds size limit')
        try:
            value = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs, parse_float=_float, parse_constant=_nonfinite)
        except (ValueError, UnicodeError):
            continue
        if type(value) is dict and value.get('kind') == 'data_dictionary' and value.get('schema_version') == 2:
            reviewed_dictionary = reviewed_dictionary or hash_json(value) == contract['dictionary_sha256']
        if type(value) is dict and value.get('kind') == 'metadata_configuration_template':
            reviewed_configuration = reviewed_configuration or value == configuration_template(contract['configuration'])
    require(reviewed_dictionary, 'Metadata dictionary must match the reviewed v2 dictionary in the frozen build handoff')
    require(reviewed_configuration, 'Metadata configuration must match the reviewed template in the frozen build handoff')


def allowed_namespace(target, namespace):
    warehouse = target['warehouse']
    def parts(value):
        if warehouse == 'bigquery':
            return [target['project'], value.get('dataset')]
        if warehouse == 'clickhouse':
            return [value.get('database')]
        if warehouse == 'databricks':
            return [value.get('catalog'), value.get('schema')]
        return [value.get('database'), value.get('schema')]
    choices = target.get('metadata_namespaces', [target['namespace']])
    return any(parts(value) == namespace for value in choices)


def same_physical_destination(parent, target):
    """Trusted policy maps an orchestrator connection to its native account.

    dbt/Coalesce service URLs identify the control plane, not the warehouse.
    A shared, externally provisioned physical identity is therefore mandatory.
    Compare native endpoint fields as well whenever both adapters expose them.
    """
    from deployment_adapters import SQL_ADAPTERS
    require(parent.get('physical_destination') and
            parent['physical_destination'] == target.get('physical_destination'),
            'Build and metadata require the same policy-bound physical_destination')
    require(parent['warehouse'] == target['warehouse'] and parent['environment'] == target['environment'],
            'Metadata and build destinations differ')
    if parent['adapter'] in SQL_ADAPTERS:
        for key in ('base_url', 'project', 'location', 'region', 'cluster_identifier', 'workgroup_name'):
            require(parent.get(key) == target.get(key), 'Native destination identity differs: ' + key)


def bind_phase(descriptor, *, artifact_root, artifacts, target, destination_id, policy,
               commit_sha, source_bindings, reviewed_framework):
    from deployment_adapters import SQL_ADAPTERS
    import deployment_workflow as runner
    require(type(descriptor) is dict and set(descriptor) == {'plan_artifact', 'parent_operation_id', 'phase'}, 'Invalid metadata phase descriptor')
    require(descriptor['phase'] in ('target_metadata', 'source_metadata'), 'Unsupported metadata phase')
    require(target['adapter'] in SQL_ADAPTERS and target['framework'] == 'native_sql', 'Metadata requires its typed native SQL destination')
    path = runner.relative_path(descriptor['plan_artifact'])
    require(any(a['path'] == path and a['role'] == 'documentation' for a in artifacts), 'Select the metadata plan as a pinned documentation artifact')
    metadata = verify_plan(load_json(Path(artifact_root) / path))
    require(not metadata['blockers'], 'Blocked metadata plan cannot become a deployment')
    contract = metadata['contract']; config = contract['configuration']
    require(config['target'] == target_binding(destination_id, target), 'Metadata destination differs from the trusted runner target')
    require(config['warehouse'] == target['warehouse'] and config['environment'] == target['environment']
            and config['framework'] == reviewed_framework, 'Metadata framework/warehouse/environment differs')
    units = [o for o in metadata['operations'] if o['phase'] == descriptor['phase']]
    require(units, 'No pending writes in this phase; collect and verify metadata instead')
    for unit in units:
        require(allowed_namespace(target, unit['relation']['namespace']), 'Metadata object is outside policy-authorized namespaces')
        if unit['tag'] and target['warehouse'] == 'snowflake':
            require(allowed_namespace(target, unit['tag']['name'][:2]), 'Metadata tag is outside policy-authorized namespaces')
    require(all(a['role'] in ('model_sql', 'documentation') for a in artifacts), 'Metadata phases permit only generated SQL and documentation')
    sql = [a for a in artifacts if a['role'] == 'model_sql']
    require(len(sql) == len(units) and all(a.get('content') == o['sql'] and a['sha256'] == o['sha256']
            for a, o in zip(sql, units)), 'Metadata SQL differs from the exact typed operation sequence')
    parent = runner._load_record(runner._root(policy), descriptor['parent_operation_id'], policy)
    parent_plan = runner.load_plan(parent['plan_path'])
    runner._record_plan(parent, parent_plan, policy)
    require('metadata_phase' not in parent_plan and parent_plan['action'] != 'publish_pr', 'A metadata phase requires a framework build parent')
    require(parent['state'] in ('verification_pending', 'deployed_verified', 'simulation_verified'), 'Parent native build is incomplete or needs recovery')
    native_ids = {o['id'] for o in parent_plan['native']['operations']}
    require(native_ids and {o['id'] for o in parent['operations']} == native_ids
            and all(o.get('receipt', {}).get('state') == 'succeeded' for o in parent['operations']), 'Every parent build operation must have a successful native receipt')
    require(parent_plan['commit_sha'] == commit_sha and config['candidate_sha256'] == candidate_binding(parent_plan), 'Metadata candidate differs from the completed build')
    reviewed_contract(parent_plan, contract)
    require(parent_plan['bindings']['source_bindings'] == source_bindings, 'Metadata source/catalogue/runtime/intake context differs from the build')
    parent_state = runner.workflow.load_engagement(parent_plan['engagement_run'])
    reviewed_policy(config, parent_state)
    require(config['catalogue_sha256'] == (parent_state['inputs'].get('catalogue') or {}).get('sha256'),
            'Metadata catalogue differs from the reviewed raw inventory')
    same_physical_destination(parent_plan['target'], target)
    require(parent_plan['review_target']['framework'] == reviewed_framework, 'Metadata framework differs from parent build')
    require(metadata['before']['release_id'] == parent_plan['id'], 'Metadata observation is not bound to this build release')
    completed_at = [item['at'] for item in parent['history'] if item['event'] == 'verification_pending']
    require(completed_at and timestamp(metadata['before']['observed_at']) >= timestamp(completed_at[-1]),
            'Metadata baseline must be independently collected after the parent build completed')
    return {'descriptor': copy.deepcopy(descriptor), 'metadata_plan_sha256': metadata['plan_sha256'],
            'contract_sha256': contract['contract_sha256'], 'before_sha256': metadata['before_sha256'],
            'parent_plan_sha256': parent_plan['plan_sha256'], 'candidate_sha256': config['candidate_sha256'],
            'operation_ids': [o['id'] for o in units]}


def revalidate(plan, policy):
    metadata = plan.get('metadata_phase')
    require(type(metadata) is dict and 'descriptor' in metadata, 'Metadata phase binding required')
    artifacts = []
    for item in plan['selected_artifacts']:
        value = copy.deepcopy(item)
        if item['role'] == 'model_sql':
            value['content'] = (Path(plan['artifact_root']) / item['path']).read_text(encoding='utf-8')
        artifacts.append(value)
    actual = bind_phase(metadata['descriptor'], artifact_root=plan['artifact_root'], artifacts=artifacts,
        target=plan['target'], destination_id=plan['destination_id'], policy=policy,
        commit_sha=plan['commit_sha'], source_bindings=plan['bindings']['source_bindings'],
        reviewed_framework=plan['review_target']['framework'])
    require(actual == metadata, 'Metadata phase binding changed')
    require(CHECKS <= set(plan['required_checks']), 'Metadata acceptance obligations cannot be removed')
    return verify_plan(load_json(Path(plan['artifact_root']) / metadata['descriptor']['plan_artifact']))


def verify_preflight(plan, policy, deployment_claims):
    """Only called after the coordinator verifies the approval issuer/signature."""
    metadata = revalidate(plan, policy)
    evidence = deployment_claims.get('metadata_preflight')
    require(type(evidence) is dict, 'Metadata requires independently captured preflight in the signed deployment approval')
    binding = plan['metadata_phase']
    for name in ('metadata_plan_sha256', 'contract_sha256', 'before_sha256', 'parent_plan_sha256', 'candidate_sha256'):
        require(evidence.get(name) == binding[name], 'Metadata preflight binding differs: ' + name)
    for flag in ('physical_build_verified', 'full_build_scope_verified', 'permissions_verified', 'policy_effects_verified', 'exclusive_change_window'):
        require(evidence.get(flag) is True, 'Metadata preflight requires ' + flag)
    require(evidence.get('lease_reference'), 'Metadata change-window reference required')
    current = datetime.now(timezone.utc)
    until = timestamp(evidence.get('lease_expires_at'))
    require(0 < (until - current).total_seconds() <= policy['max_attestation_age_seconds'], 'Metadata change window is expired or exceeds runner policy')
    require(evidence.get('parent_operation_id') == binding['descriptor']['parent_operation_id'], 'Metadata preflight parent differs')
    if policy['mode'] == 'live':
        require(metadata['before']['collection']['origin'] != 'simulation', 'Simulation metadata cannot authorize live writes')
        raise ValueError('Automatic live metadata dispatch is not implemented without an authenticated native drift collector; use the reviewed SQL/operator handoff')
    check_preconditions(metadata, metadata['before'], now=current,
                        max_age_seconds=min(policy['max_attestation_age_seconds'], 86400))
    return metadata


def pending_parent_allowed(previous, plan):
    """Only the matching metadata child can follow a completed unaccepted build."""
    return (previous.get('state') == 'verification_pending'
            and plan.get('metadata_phase', {}).get('descriptor', {}).get('parent_operation_id') == previous.get('operation_id')
            and plan.get('metadata_phase', {}).get('parent_plan_sha256') == previous.get('plan_sha256'))


def verify_acceptance(plan, record, policy, claims):
    """Recompute metadata checks from the independent signer's bound observation."""
    from verify_warehouse_metadata import verify_metadata
    from metadata_contract import verify_contract
    from metadata_observation import validate_observation
    from deployment_adapters import validate_target
    import deployment_workflow as runner
    if plan.get('metadata_phase'):
        metadata = revalidate(plan, policy)
        contract = metadata['contract']
        phase = plan['metadata_phase']['descriptor']['phase']
        release_id = metadata['before']['release_id']
    else:
        contract = verify_contract(claims.get('metadata_contract'))
        require(contract['configuration']['candidate_sha256'] == candidate_binding(plan), 'Accepted metadata differs from the built artifact set')
        config = contract['configuration']; target_id = config['target']['id']
        require(target_id in policy['destinations'], 'Metadata readback destination is not provisioned')
        target = validate_target(policy['destinations'][target_id])
        require(config['target'] == target_binding(target_id,target)
                and target['warehouse'] == plan['target']['warehouse'] and target['environment'] == plan['target']['environment'],
                'Metadata readback destination differs from build')
        same_physical_destination(plan['target'], target)
        state = runner.workflow.load_engagement(plan['engagement_run'])
        reviewed_policy(config, state)
        require(config['catalogue_sha256'] == (state['inputs'].get('catalogue') or {}).get('sha256'),
                'Accepted metadata catalogue differs from the reviewed raw inventory')
        require(config['warehouse']==target['warehouse'] and config['environment']==target['environment'], 'Metadata configuration differs from its destination')
        require(config['framework'] == plan['review_target']['framework'], 'Metadata readback framework differs')
        reviewed_contract(plan, contract)
        for resource in contract['resources']:
            if resource['disposition']=='required':
                require(allowed_namespace(target,resource['relation']['namespace']), 'Readback outside authorized namespace')
        require(claims.get('metadata_full_build_scope_verified') is True, 'Independent full-build metadata scope verification required')
        phase, release_id = None, plan['id']
    observed = claims.get('metadata_observation')
    validate_observation(contract, observed, now=datetime.now(timezone.utc),
                         max_age_seconds=min(policy['max_attestation_age_seconds'],86400))
    if plan.get('metadata_phase'):
        versions = {r['id']:r['object_version'] for r in metadata['before']['resources']}
        require(all(versions.get(r['id']) == r['object_version'] for r in observed['resources']),
                'Metadata object incarnation changed after planning; collect and review a new plan')
    require(timestamp(observed['observed_at']) >= timestamp(record['updated_at']), 'Metadata readback predates completed execution')
    if policy['mode']=='live':
        require(observed['collection']['origin']!='simulation', 'Simulation readback cannot establish live metadata acceptance')
    report = verify_metadata(contract,observed,phase=phase,release_id=release_id)
    require(report['passed'], 'Metadata readback failed: '+'; '.join(report['issues']))
    checks = {c['id']:c for c in claims['checks']}
    for name in CHECKS & set(plan['required_checks']):
        require(checks[name]['evidence_sha256'] == report['verification_sha256'], 'Metadata check must bind the recomputed readback report: '+name)
    return report
