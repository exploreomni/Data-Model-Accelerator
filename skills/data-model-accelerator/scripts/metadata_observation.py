"""Bounded normalized metadata observations; structural validity is not authority.

Collectors must enumerate every physical column, not the dictionary column list.
An external verification signer authenticates live provenance in the release gate.
"""
from datetime import datetime, timezone
from ae_common import hash_json, require
from metadata_contract import SHA, identifier, relation, relation_key, text, verify_contract


def scope(contract):
    return [{'id': r['id'], 'relation': r['relation'], 'disposition': r['disposition']}
            for r in contract['resources']]


def seal(value):
    result = {k: v for k, v in value.items() if k != 'observation_sha256'}
    result['observation_sha256'] = hash_json(result)
    return result


def timestamp(value):
    require(type(value) is str, 'Observation time must be explicit')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid observation time') from None
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, 'Observation time requires a timezone')
    return parsed


def _comment(value):
    require(value is None or type(value) is str and len(value) <= 16000 and '\x00' not in value,
            'Observed comment must be bounded text or null')


def _tags(values):
    require(type(values) is list and len(values) <= 1000, 'Invalid observed tag list')
    seen = set()
    for tag in values:
        require(type(tag) is dict and set(tag) == {'name', 'value', 'application'}, 'Invalid observed tag')
        require(type(tag['name']) is list and 1 <= len(tag['name']) <= 3, 'Invalid observed tag name')
        for part in tag['name']:
            identifier(part)
        require(tag['application'] in ('direct', 'inherited', 'propagated', 'unknown'), 'Unknown tag application method')
        text(tag['value'], 'observed tag value')
        key = (tuple(tag['name']), tag['application'])
        require(key not in seen, 'Duplicate observed tag association')
        seen.add(key)


def validate_observation(contract, observation, *, now=None, max_age_seconds=None):
    verify_contract(contract)
    required = {'schema_version', 'kind', 'contract_sha256', 'candidate_sha256', 'target',
                'scope_sha256', 'release_id', 'observed_at', 'collection', 'resources',
                'governance', 'observation_sha256'}
    require(type(observation) is dict and set(observation) == required, 'Invalid metadata observation fields')
    require(type(observation['schema_version']) is int and observation['schema_version'] == 1
            and observation['kind'] == 'warehouse_metadata_observation', 'Unsupported metadata observation')
    require(seal(observation) == observation, 'Metadata observation digest mismatch')
    config = contract['configuration']
    require(observation['contract_sha256'] == contract['contract_sha256'], 'Observation contract differs')
    require(observation['candidate_sha256'] == config['candidate_sha256'], 'Observation candidate differs')
    require(observation['target'] == config['target'], 'Observation target identity differs')
    require(observation['scope_sha256'] == hash_json(scope(contract)), 'Observation scope differs')
    text(observation['release_id'], 'release ID')
    collected = timestamp(observation['observed_at'])
    if now is not None or max_age_seconds is not None:
        current = now or datetime.now(timezone.utc)
        require(current.tzinfo is not None, 'Comparison clock requires a timezone')
        age = (current - collected).total_seconds()
        require(age >= -60, 'Observation is in the future')
        if max_age_seconds is not None:
            require(type(max_age_seconds) is int and 0 < max_age_seconds <= 86400, 'Invalid freshness bound')
            require(age <= max_age_seconds, 'Observation is stale; recollect before a write')
    collection = observation['collection']
    require(type(collection) is dict and set(collection) == {'origin', 'complete', 'identity_verified',
            'visibility_verified', 'query_ids', 'evidence_sha256'}, 'Invalid collection provenance')
    require(collection['origin'] in ('operator_export', 'trusted_collector', 'simulation'), 'Unknown collection origin')
    for name in ('complete', 'identity_verified', 'visibility_verified'):
        require(type(collection[name]) is bool, 'Collection flags must be booleans')
    require(type(collection['query_ids']) is list and collection['query_ids']
            and all(type(v) is str and v for v in collection['query_ids']), 'Native query references required')
    require(type(collection['evidence_sha256']) is str and SHA.fullmatch(collection['evidence_sha256']), 'Raw evidence digest required')
    rows = observation['resources']
    require(type(rows) is list and len(rows) <= 5000, 'Invalid observed resources')
    ids, physical = set(), set()
    for row in rows:
        require(type(row) is dict and set(row) == {'id', 'relation', 'object_version', 'comment', 'tags', 'columns'}, 'Invalid observed resource')
        text(row['id'], 'observed resource ID')
        rel = relation(row['relation'], config['warehouse'])
        require(row['id'] not in ids and relation_key(rel) not in physical, 'Duplicate observed resource')
        ids.add(row['id']); physical.add(relation_key(rel))
        text(row['object_version'], 'object incarnation/version')
        _comment(row['comment']); _tags(row['tags'])
        columns = row['columns']
        require(type(columns) is list and len(columns) <= 10000, 'Invalid observed columns')
        names = set()
        for column in columns:
            require(type(column) is dict and set(column) == {'name', 'data_type', 'comment', 'tags'}, 'Invalid observed column')
            identifier(column['name']); text(column['data_type'], 'observed column type')
            require(column['name'] not in names, 'Duplicate observed column')
            names.add(column['name']); _comment(column['comment']); _tags(column['tags'])
    require(type(observation['governance']) is list, 'Explicit governance inventory required')
    names = set()
    for tag in observation['governance']:
        require(type(tag) is dict and set(tag) == {'name', 'allowed_values', 'policy_effects', 'evidence_reference'}, 'Invalid governance definition')
        require(type(tag['name']) is list and tag['name'], 'Governance tag identity required')
        for part in tag['name']:
            identifier(part)
        require(tuple(tag['name']) not in names, 'Duplicate governance definition')
        names.add(tuple(tag['name']))
        require(tag['allowed_values'] is None or type(tag['allowed_values']) is list
                and all(type(v) is str for v in tag['allowed_values']), 'Invalid tag allowed values')
        require(tag['policy_effects'] in ('none_verified', 'policy_bound', 'unknown'), 'Invalid governance policy state')
        text(tag['evidence_reference'], 'governance evidence')
    return observation


def shape_discrepancies(contract, observation):
    """Compare the full declared model/source union to independently observed shape."""
    validate_observation(contract, observation)
    issues = []
    for key in ('complete', 'identity_verified', 'visibility_verified'):
        if observation['collection'][key] is not True:
            issues.append('collection: ' + key + ' is unverified')
    expected = {r['id']: r for r in contract['resources'] if r['disposition'] == 'required'}
    observed = {r['id']: r for r in observation['resources']}
    known = {r['id'] for r in contract['resources']}
    for key in set(observed) - known:
        issues.append(key + ': unexpected resource outside approved collection scope')
    for key, resource in expected.items():
        actual = observed.get(key)
        if actual is None:
            issues.append(key + ': physical resource missing or inaccessible')
            continue
        if actual['relation'] != resource['relation']:
            issues.append(key + ': physical identity/object type differs')
        columns = {c['name']: c for c in resource['columns']}
        actual_columns = {c['name']: c for c in actual['columns']}
        for name in set(columns) - set(actual_columns):
            issues.append(key + '.' + name + ': physical column missing')
        for name in set(actual_columns) - set(columns):
            issues.append(key + '.' + name + ': physical column is undocumented')
        for name in set(columns) & set(actual_columns):
            if columns[name]['data_type'] != actual_columns[name]['data_type']:
                issues.append(key + '.' + name + ': physical type differs; resolve exact adapter type mapping')
    return sorted(issues)


def physical_union(contract, observation):
    """Reuse the established physical reconciler without putting RAW in layer docs."""
    from verify_physical_schema import reconcile
    verify_contract(contract)
    validate_observation(contract, observation)
    def qualified(rel):
        return '.'.join('"' + p.replace('"', '""') + '"' for p in rel['namespace'] + [rel['name']])
    records = [r for r in contract['resources'] if r['disposition'] == 'required']
    require(records, 'There are no required physical resources; coverage cannot pass')
    ids = {r['id'] for r in records}
    inventory = {'schema_version': 1, 'kind': 'data_model_inventory', 'models': [
        {'model_id': r['id'], 'physical_name': qualified(r['relation']), 'columns': [c['name'] for c in r['columns']]}
        for r in records]}
    actual = {'schema_version': 1, 'kind': 'physical_schema_observation',
        'candidate_sha256': observation['candidate_sha256'], 'origin': 'provided_export',
        'validation_scope': 'local' if observation['collection']['origin'] == 'simulation' else 'target',
        'adapter_type': contract['configuration']['warehouse'], 'captured_at': observation['observed_at'],
        'identifier_policy': 'exact', 'scope': [qualified(r['relation']) for r in records],
        'relations': [{'physical_name': qualified(r['relation']), 'columns': [c['name'] for c in r['columns']]}
                      for r in observation['resources'] if r['id'] in ids]}
    return reconcile(inventory, actual, observation['candidate_sha256'])


def bind_dbt_manifest(contract, manifest):
    """Full enabled physical execution scope, including native sources and seeds."""
    from verify_engagement import physical_denominator
    verify_contract(contract)
    require(contract['configuration']['framework'] in ('dbt', 'dbt_core', 'dbt_platform'), 'dbt binding requires dbt framework')
    expected = set()
    for resource in contract['resources']:
        if resource['disposition'] == 'ephemeral':
            continue
        rel = resource['relation']
        expected.add('.'.join('"' + p.replace('"', '""') + '"' for p in rel['namespace'] + [rel['name']]))
    actual = physical_denominator(manifest)
    require(actual == expected, 'Metadata scope differs from full enabled dbt build: missing=' + repr(sorted(actual - expected))
            + '; extra=' + repr(sorted(expected - actual)))
    return {'status': 'scope_matches', 'relations': len(actual), 'manifest_sha256': hash_json(manifest),
            'contract_sha256': contract['contract_sha256'], 'warehouse_metadata_verified': False}
