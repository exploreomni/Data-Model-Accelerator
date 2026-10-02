"""Recompute mandatory engagement gates from pinned evidence; never execute SQL.

This joins independently captured evidence, not authenticated approvals. Older
refactor/review contracts remain readable but cannot alone establish this grade.
"""
import argparse
from pathlib import Path
import sys

from ae_common import hash_file, hash_json, load_json, require, safe_relative, snapshot, write_json
from freeze_benchmark import _bound_json, _fields, _text
from verify_dbt_evidence import instant
from verify_refactor_run import _association, verify_run
from verify_review_package import verify as verify_review
from verify_physical_schema import verify as verify_physical
from verify_value_coverage import verify as verify_values
from verify_engagement_authority import verify as verify_authority

ASSOCIATIONS = ('refactor_record', 'review_package', 'model_inventory',
                'physical_observation', 'value_contract', 'scope_contract',
                'authority', 'catalogue_provenance')


def qualified_relation(node):
    """Canonical, exact SQL-quoted name; no identifier folding or alias guessing."""
    parts = (node.get('database'), node.get('schema'),
             node.get('identifier') if node.get('resource_type') == 'source' else node.get('alias'))
    return '.'.join('"' + _text(part, 'native relation identifier').replace('"', '""') + '"' for part in parts)


def physical_denominator(manifest):
    relations = set()
    require(all(node.get('resource_type') == 'source' for node in manifest.get('sources', {}).values()),
            'Native sources must carry explicit source resource identities')
    for node in list(manifest['nodes'].values()) + list(manifest.get('sources', {}).values()):
        if node.get('config', {}).get('enabled', True) is False:
            continue
        if node.get('resource_type') in ('model', 'seed', 'snapshot', 'source') and node.get('config', {}).get('materialized') != 'ephemeral':
            relations.add(qualified_relation(node))
    require(relations, 'Native physical relation denominator is empty')
    return relations


def verify_native_sources(bindings, manifest, catalogue, resolved_bindings, observation, stage):
    """Bind actual native source namespaces/columns to the reviewed raw catalogue."""
    require(type(bindings) is list, 'Native source bindings must be a list')
    sources = {uid: node for uid, node in manifest.get('sources', {}).items()
               if node.get('config', {}).get('enabled', True) is not False}
    objects = {obj['object_id']: obj for obj in catalogue['objects']}
    resolved = {entry['object_id'] for entry in resolved_bindings['references'] if entry.get('status') == 'resolved'}
    observed = {entry['physical_name']: set(entry['columns']) for entry in observation['relations']}
    seen = set()
    for binding in bindings:
        _fields(binding, ('source_id', 'catalogue_object_id', 'local_remap'))
        uid = _text(binding['source_id'], 'native source ID')
        oid = _text(binding['catalogue_object_id'], 'catalogue object ID')
        require(uid in sources and uid not in seen, 'Missing, duplicate or unknown native source binding')
        seen.add(uid)
        require(oid in objects and oid in resolved, 'Native source must bind a resolved catalogue object')
        node, obj = sources[uid], objects[oid]
        actual = [node['database'], node['schema'], node['identifier']]
        expected = [obj['identity'][key] for key in ('catalog', 'schema', 'name')]
        remap = binding['local_remap']
        if actual == expected:
            require(remap is None, 'Matching native source does not require a local remap')
        else:
            require(stage == 'local', 'Target native source identity differs from catalogue')
            _fields(remap, ('relation', 'reason'))
            require(remap['relation'] == actual, 'Local source identity requires an exact explicit remap')
            _text(remap['reason'], 'local remap reason')
        if stage == 'target':
            require(remap is None, 'Target source cannot use a local remap')
        require(observed.get(qualified_relation(node)) == {col['path'][0] for col in obj['columns']},
                'Observed native source columns differ from catalogue: ' + uid)
    require(seen == set(sources), 'Native source binding denominator incomplete')


def _verify(request_path):
    from verify_engagement_scope import verify as verify_scope
    from verify_catalogue_provenance import verify as verify_provenance
    request_path = Path(request_path).absolute()
    request, digest = _bound_json(request_path)
    _fields(request, ('schema_version', 'kind', 'native_source_bindings') + ASSOCIATIONS)
    require(type(request['schema_version']) is int and request['schema_version'] == 1
            and request['kind'] == 'engagement_validation_request', 'Unsupported engagement request')
    paths, docs = {}, {}
    for name in ASSOCIATIONS:
        paths[name], docs[name] = _association(request[name], request_path.parent)
    require(len(set(paths.values())) == len(paths), 'Engagement associations must be distinct')
    record = docs['refactor_record']
    project = Path(record['candidate_project'])
    candidate = snapshot(project)
    base = paths['refactor_record'].parent
    plan_path, plan = _association(record['plan'], base)
    native_path, native = _association(record['native'], base)
    baseline_path, baseline = _association(record['baseline'], base)
    actual_path, _ = _association(record['actual'], base)
    stage = native['validation_scope']
    require(stage in ('local', 'target'), 'Unknown native validation scope')
    source = Path(plan['project_root'])
    source_snapshot = snapshot(source)
    require(source_snapshot == plan['source_snapshot'], 'Engagement source drift')

    package = docs['review_package']
    artifacts = {item['id']: item for item in package['artifacts']}
    inventory_id = package['model_documentation']['inventory_artifact_id']
    def artifact_path(aid):
        return paths['review_package'].parent / safe_relative(artifacts[aid]['path'])
    require(artifact_path(inventory_id) == paths['model_inventory'], 'Review and physical gates must use the same model inventory')
    source_artifacts = [item for item in package['artifacts'] if item['role'] == 'source_inventory']
    require(len(source_artifacts) == 1, 'One source inventory is required')
    source_inventory = load_json(artifact_path(source_artifacts[0]['id']))
    require(type(source_inventory.get('schema_version')) is int and source_inventory['schema_version'] == 1
            and source_inventory.get('kind') == 'engagement_source_inventory'
            and source_inventory.get('project_root') == str(source)
            and source_inventory.get('snapshot') == source_snapshot, 'Review inventory does not bind the original source project')
    code_inventories = []
    for artifact in package['artifacts']:
        if artifact['role'] == 'code':
            try:
                content = load_json(artifact_path(artifact['id']))
            except ValueError:
                continue  # Ordinary SQL/code artifacts may accompany the required inventory.
            if type(content) is dict and content.get('kind') == 'engagement_candidate_inventory':
                code_inventories.append(content)
    require(len(code_inventories) == 1 and type(code_inventories[0].get('schema_version')) is int
            and code_inventories[0]['schema_version'] == 1 and code_inventories[0].get('project_root') == str(project)
            and code_inventories[0].get('snapshot') == candidate, 'Review code inventory must bind the exact candidate project')
    catalogues = package['warehouse_catalogues']
    require(len(catalogues) == 1, 'Enhanced engagement currently requires one normalized catalogue')
    catalogue_path = artifact_path(catalogues[0]['catalogue_artifact_id'])
    require(hash_file(catalogue_path) == plan['catalogue_sha256'] == baseline['contract']['catalogue_sha256'],
            'Engagement catalogue differs across plan, baseline and review')
    catalogue = load_json(catalogue_path)
    resolved_bindings = load_json(artifact_path(catalogues[0]['bindings_artifact_id']))

    observed = docs['physical_observation']
    require(observed.get('native_receipt_sha256') == hash_file(native_path), 'Physical metadata must bind this native receipt')
    manifest = load_json(native_path.parent / safe_relative(native['manifest']['path']), max_bytes=100 * 1024 * 1024)
    require(observed.get('invocation_id') == manifest['metadata']['invocation_id'], 'Physical metadata invocation mismatch')
    require(observed['adapter_type'] == native['expected_adapter_type'] and observed['validation_scope'] == stage,
            'Physical metadata adapter/scope mismatch')
    require(instant(observed['captured_at'], 'metadata capture') >= instant(native['execution']['finished_at'], 'native finish'),
            'Physical metadata predates the completed build')
    require({row['physical_name'] for row in observed['relations']} == physical_denominator(manifest),
            'Observed relation denominator differs from native materialized models, seeds, snapshots and sources')
    verify_native_sources(request['native_source_bindings'], manifest, catalogue, resolved_bindings, observed, stage)

    run = verify_run(paths['refactor_record'])
    review_errors = verify_review(paths['review_package'], stage)
    physical = verify_physical(paths['model_inventory'], paths['physical_observation'], project)
    values = verify_values(paths['value_contract'], baseline_path, actual_path, paths['model_inventory'], project)
    scope = verify_scope(paths['scope_contract'], source)
    provenance = verify_provenance(paths['catalogue_provenance'], catalogue_path)
    authority = verify_authority(paths['authority'], {
        'source_revision': source_snapshot['sha256'], 'candidate_sha256': candidate['sha256'],
        'catalogue_sha256': hash_file(catalogue_path), 'baseline_sha256': baseline['baseline_sha256'],
        'scope_contract_sha256': hash_file(paths['scope_contract']), 'value_contract_sha256': hash_file(paths['value_contract']),
        'native_source_bindings_sha256': hash_json(request['native_source_bindings']),
        'rule_ids': sorted({rule for model in plan['models'] for rule in model['rule_ids']}),
        'decision_ids': sorted({case['decision']['id'] for case in baseline['contract']['cases'] if case['category'] == 'correctness'}),
        'origin': provenance['origin'], 'stage': stage, 'execution_mode': record['execution_mode']})
    errors = list(run['errors']) + review_errors + physical['errors'] + scope['errors'] + provenance['errors']
    if not values['passed']:
        errors.append('Independent source-value/benchmark validation failed')
    require(scope['source_revision'] == plan['source_snapshot']['sha256'], 'Scope source revision mismatch')
    require(snapshot(project) == candidate and snapshot(source) == source_snapshot, 'Engagement project changed during verification')
    for name, path in paths.items():
        require(hash_file(path) == request[name]['sha256'], 'Engagement association changed: ' + name)
    require(hash_file(request_path) == digest, 'Engagement request changed')
    return {'schema_version': 1, 'kind': 'engagement_verification', 'evidence_complete': not errors,
            'state': 'enhanced_' + stage + '_validated' if not errors else 'incomplete',
            'request_sha256': digest, 'candidate_sha256': candidate['sha256'],
            'source_revision': source_snapshot['sha256'], 'execution_mode': record['execution_mode'],
            'gates': {'refactor': run, 'review': {'passed': not review_errors, 'errors': review_errors},
                      'physical': physical, 'source_values': values, 'scope': scope,
                      'catalogue_provenance': provenance, 'authority': authority}, 'errors': errors,
            'limitations': ['Read-only evidence association, not execution, deployment or business approval.',
                            'Graph completeness, metadata authenticity and expected-value independence require trusted host review.',
                            'Physical names/columns are checked; types, nullability and semantic behavior need their own cases.']}


def verify(request_path):
    try:
        return _verify(request_path)
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        return {'schema_version': 1, 'kind': 'engagement_verification', 'evidence_complete': False,
                'state': 'incomplete', 'errors': [str(error)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = load_json(args.request)
        record_path, record = _association(request['refactor_record'], args.request.absolute().parent)
        _, plan = _association(record['plan'], record_path.parent)
        for root in (Path(record['candidate_project']), Path(plan['project_root'])):
            require(root.resolve() not in args.output.absolute().parents, 'Output must stay outside source and candidate projects')
        result = verify(args.request)
        write_json(args.output, result)
        print(result['state'] + ': ' + '; '.join(result['errors']))
        return 0 if result['evidence_complete'] else 1
    except (ValueError, OSError, TypeError, KeyError) as error:
        print('Engagement verification refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
