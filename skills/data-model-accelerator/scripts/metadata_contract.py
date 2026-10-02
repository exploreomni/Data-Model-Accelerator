"""Canonical metadata projection and exact physical scope. No warehouse execution."""
import copy
import re
from ae_common import hash_json, require
from metadata_platforms import capabilities
from metadata_options import validate_options
from metadata_descriptions import relation_description, column_description, meaningful_description

SHA = re.compile(r'[0-9a-f]{64}\Z')


def text(value, label, *, optional=False):
    if value is None and optional:
        return value
    require(type(value) is str and bool(value.strip()) and len(value) <= 16000 and '\x00' not in value,
            'Invalid ' + label)
    require(not any(token in value for token in ('{{', '{%', '{#')), 'Executable template in ' + label)
    return value


def identifier(value):
    text(value, 'identifier')
    require(value == value.strip() and len(value) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in value),
            'Invalid identifier')
    return value


def relation(value, warehouse):
    require(type(value) is dict and set(value) == {'namespace', 'name', 'kind'}, 'Invalid relation fields')
    cap = capabilities(warehouse)
    require(type(value['namespace']) is list and len(value['namespace']) == cap['namespace_components'],
            'Exact platform namespace components required')
    for part in value['namespace'] + [value['name']]:
        identifier(part)
    require(value['kind'] in ('table', 'view', 'ephemeral', 'external', 'late_binding_view'), 'Unsupported object kind')
    return copy.deepcopy(value)


def relation_key(value):
    return tuple(value['namespace'] + [value['name']])


def _tags(values, warehouse):
    require(type(values) is list, 'Tag assignments must be a list')
    found, names = set(), set()
    for item in values:
        require(type(item) is dict and set(item) == {'id', 'name', 'value', 'policy_effects', 'evidence_reference'},
                'Invalid tag assignment fields')
        identifier(item['id'])
        require(item['id'] not in found, 'Duplicate logical tag ID')
        found.add(item['id'])
        require(type(item['name']) is list and len(item['name']) == (3 if warehouse == 'snowflake' else 1),
                'Tag must use exact native namespace')
        for part in item['name']:
            identifier(part)
        require(tuple(item['name']) not in names, 'Duplicate native tag assignment')
        names.add(tuple(item['name']))
        text(item['value'], 'tag value')
        require(len(item['value']) <= 256, 'Tag value exceeds 256 characters; use a dictionary reference')
        require(item['policy_effects'] in ('none_verified', 'unknown', 'policy_bound'), 'Invalid tag policy state')
        text(item['evidence_reference'], 'tag policy evidence', optional=True)
        if item['policy_effects'] == 'none_verified':
            require(item['evidence_reference'], 'Informational-only tags require policy evidence')
    return copy.deepcopy(values)


def build_contract(dictionary, configuration):
    """Project v2 definitions through an explicit map; unresolved meaning stays blocked.

    Hashes bind supplied evidence, not authenticated authorship or live identity.
    No relation/column name, source lineage or business approval is inferred.
    """
    from data_dictionary_v2 import validate_dictionary
    require(not validate_dictionary(dictionary), 'A valid v2 dictionary is required: ' + '; '.join(validate_dictionary(dictionary)))
    required = {'schema_version', 'kind', 'framework', 'warehouse', 'environment', 'target',
                'candidate_sha256', 'catalogue_sha256', 'metadata_policy', 'resources'}
    require(type(configuration) is dict and set(configuration) == required, 'Invalid metadata configuration fields')
    require(type(configuration['schema_version']) is int and configuration['schema_version'] == 1
            and configuration['kind'] == 'metadata_configuration', 'Unsupported metadata configuration')
    warehouse, framework = configuration['warehouse'], configuration['framework']
    cap = capabilities(warehouse, framework)
    require(cap['supported_pairing'], 'Unsupported framework/warehouse metadata pairing')
    policy = validate_options(configuration['metadata_policy'])
    environment = identifier(configuration['environment'])
    require(environment in policy['environments'], 'Metadata environment was not selected')
    target = configuration['target']
    require(type(target) is dict and set(target) == {'id', 'identity'} and type(target['identity']) is dict
            and bool(target['identity']), 'Exact target identity required')
    identifier(target['id'])
    for k, v in target['identity'].items():
        identifier(k); text(v, 'target identity')
    from guided_workflow import _secrets
    _secrets(target)
    for key in ('candidate_sha256', 'catalogue_sha256'):
        require(type(configuration[key]) is str and SHA.fullmatch(configuration[key]), 'Invalid ' + key)
    entries = {m['model_id']: m for m in dictionary['models']}
    sources = {s['source_id']: s for s in dictionary.get('sources', [])}
    entries.update(sources)
    resources, seen, physical = [], set(), set()
    blockers = []
    require(type(configuration['resources']) is list and configuration['resources'], 'Nonempty metadata scope required')
    for binding in configuration['resources']:
        keys = {'resource_id', 'resource_type', 'layer', 'relation', 'disposition', 'reason', 'columns',
                'source_write_decision', 'tags', 'column_tags'}
        require(type(binding) is dict and set(binding) == keys, 'Invalid metadata binding fields')
        mid = text(binding['resource_id'], 'resource ID')
        require(mid in entries and mid not in seen, 'Unknown or duplicate model ID')
        seen.add(mid)
        model = entries[mid]
        require(binding['resource_type'] == ('source' if mid in sources else 'model'), 'Resource type differs from dictionary inventory')
        require(binding['layer'] in ('raw', 'bronze', 'silver', 'gold'), 'Invalid layer')
        rel = relation(binding['relation'], warehouse)
        require(relation_key(rel) not in physical, 'Physical collision: consolidate source/model aliases explicitly')
        physical.add(relation_key(rel))
        disposition = binding['disposition']
        require(disposition in ('required', 'documented_only', 'excluded', 'ephemeral'), 'Invalid metadata disposition')
        if disposition != 'required':
            text(binding['reason'], 'exclusion/disposition reason')
        text(binding['source_write_decision'], 'source owner decision', optional=True)
        if disposition == 'ephemeral':
            require(rel['kind'] == 'ephemeral', 'Ephemeral disposition needs an ephemeral resource')
        elif disposition == 'required':
            require(rel['kind'] != 'ephemeral', 'Ephemeral models cannot require native comments')
        columns = binding['columns']
        require(type(columns) is dict and set(columns) == {c['name'] for c in model['columns']}, 'Exact column mapping required')
        for name in columns.values():
            identifier(name)
        require(len(set(columns.values())) == len(columns), 'Physical column alias collision')
        tags = _tags(binding['tags'], warehouse)
        column_tags = binding['column_tags']
        require(type(column_tags) is dict and set(column_tags) <= set(columns), 'Unknown tagged column')
        ctags = {name: _tags(values, warehouse) for name, values in column_tags.items()}
        if tags or any(ctags.values()):
            require(policy['mode'] == 'comments_and_tags', 'Tags were not selected')
        if disposition == 'required':
            if policy['mode'] == 'documentation_only':
                blockers.append(mid + ': documentation-only scope cannot require native writes')
            if model['review_status'] != 'approved' or not meaningful_description(model):
                blockers.append(mid + ': model definition requires review')
            if rel['kind'] not in cap['relation_comments']:
                blockers.append(mid + ': native relation comments are outside the qualified object contract')
            if binding['resource_type'] == 'source':
                if not policy['raw_comments'] or mid not in policy['source_ids'] or not binding['source_write_decision']:
                    blockers.append(mid + ': RAW comment scope/owner decision is missing')
        result_columns = []
        for column in model['columns']:
            item = {'id': column['column_id'], 'name': columns[column['name']],
                    'description': column_description(column), 'data_type': column['data_type'],
                    'sensitivity': column['sensitivity'], 'review_status': column['review_status'],
                    'key_roles': column['key_roles'], 'source_refs': column['source_refs'],
                    'tags': ctags.get(column['name'], [])}
            if disposition == 'required':
                if column['review_status'] != 'approved' or not meaningful_description(column):
                    blockers.append(mid + '.' + column['name'] + ': column definition requires review')
                if policy['mode'] == 'comments_and_tags' and (column['sensitivity'] == 'UNKNOWN' or column['sensitivity_review_status'] != 'approved'):
                    blockers.append(mid + '.' + column['name'] + ': sensitivity requires review')
                if binding['resource_type'] == 'source' and not any(
                        ref['object_id'] == mid and ref['column_path'] == [item['name']]
                        and ref['catalogue_sha256'] == configuration['catalogue_sha256']
                        for ref in column['source_refs']):
                    blockers.append(mid + '.' + column['name'] + ': exact source catalogue lineage is missing')
                if rel['kind'] not in cap['column_comments']:
                    blockers.append(mid + '.' + column['name'] + ': column comments unsupported for this object')
            result_columns.append(item)
            for tag in item['tags']:
                if tag['id'] == 'sensitivity':
                    require(tag['value'] == item['sensitivity'], 'Sensitivity tag must match canonical classification')
                if tag['id'] == 'key_roles':
                    require(tag['value'] == ','.join(sorted(item['key_roles'])), 'Key-role tag must preserve every canonical role')
        for tag in tags:
            if tag['id'] == 'sensitivity':
                rank = {'PUBLIC': 0, 'INTERNAL': 1, 'CONFIDENTIAL': 2, 'RESTRICTED': 3}
                require(tag['value'] in rank, 'Object sensitivity must use the canonical taxonomy')
                known = [rank[c['sensitivity']] for c in result_columns if c['sensitivity'] in rank]
                require(not known or rank[tag['value']] >= max(known), 'Object sensitivity cannot downgrade a classified column')
        for tag in tags + [t for ts in ctags.values() for t in ts]:
            if warehouse == 'snowflake':
                require(tag['name'][:-1] == policy['tag_namespace'], 'Tag namespace differs from the reviewed selection')
            if disposition == 'required' and tag['policy_effects'] != 'none_verified':
                blockers.append(mid + ': tag policy effects require separate security qualification')
            if warehouse == 'snowflake' and [x.upper() for x in tag['name'][:2]] == ['SNOWFLAKE', 'TAGS']:
                blockers.append(mid + ': Preview built-in tags require a separately qualified route')
        if (tags or any(ctags.values())) and cap['tags'] not in ('custom_governed', 'unity_catalog'):
            blockers.append(mid + ': native governed tag emission is not implemented on this route')
        resources.append({'id': mid, 'resource_type': binding['resource_type'], 'layer': binding['layer'],
                          'relation': rel, 'disposition': disposition, 'reason': binding['reason'],
                          'description': relation_description(model), 'grain': model['grain'], 'tags': tags,
                          'columns': result_columns, 'source_write_decision': binding['source_write_decision']})
    require(seen == set(entries), 'Every dictionary model must have an explicit disposition')
    result = {'schema_version': 1, 'kind': 'warehouse_metadata_contract',
              'configuration': copy.deepcopy(configuration), 'dictionary': copy.deepcopy(dictionary),
              'dictionary_sha256': hash_json(dictionary),
              'resources': resources, 'blockers': sorted(set(blockers)), 'capabilities': cap,
              'authority': 'Proposed metadata only; review flags and source decisions do not authorize writes.'}
    result['contract_sha256'] = hash_json(result)
    return result


def verify_contract(contract):
    require(type(contract) is dict and contract.get('kind') == 'warehouse_metadata_contract'
            and contract.get('schema_version') == 1, 'Invalid metadata contract')
    require(contract.get('contract_sha256') == hash_json({k: v for k, v in contract.items() if k != 'contract_sha256'}),
            'Metadata contract content changed')
    require(build_contract(contract.get('dictionary'), contract.get('configuration')) == contract,
            'Metadata contract differs from canonical projection')
    return contract


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    from ae_common import load_json, write_json, _path
    parser = argparse.ArgumentParser(description='Bind dictionary-v2 metadata to explicit physical destinations. No execution.')
    for field in ('dictionary', 'configuration', 'output'):
        parser.add_argument('--' + field, required=True, type=Path)
    args = parser.parse_args(argv)
    output = _path(args.output, must_exist=False)
    require(not output.exists(), 'Contract output must be a new file')
    result = build_contract(load_json(args.dictionary), load_json(args.configuration))
    write_json(output, result)
    print(json.dumps({'contract_sha256': result['contract_sha256'], 'blockers': result['blockers']}))
    return 1 if result['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
