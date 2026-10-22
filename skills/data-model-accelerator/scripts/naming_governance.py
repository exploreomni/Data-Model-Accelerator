"""Optional lexical naming governance; no source edits or native identity authority.

The companion lives at workflow.naming_governance. Host-supplied decisions are
attribution, not authenticated approval. Native namespace isolation is separate.
"""
import copy
import re
from string import Formatter

from ae_common import hash_json, require

PROFILES = {'abbreviated', 'expanded', 'medallion', 'custom', 'preserve'}
PLATFORMS = {'snowflake', 'bigquery', 'postgres', 'redshift', 'databricks',
             'clickhouse', 'motherduck', 'fabric', 'unknown'}
ROLES = {'source', 'staging', 'intermediate', 'fact', 'dimension', 'mart', 'other'}
LAYERS = {'raw', 'bronze', 'silver', 'gold'}
TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,199}\Z')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z')
MAX_RESOURCES = 20000
QUALIFICATION = ('Host-attributed naming decisions only; no authenticated approval, '
                 'native catalogue uniqueness, schema isolation or deployment authority.')


def _fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional),
            'Invalid naming document fields')


def _text(value, limit=1000):
    require(type(value) is str and value.strip() == value and value and len(value) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Expected bounded naming text')
    return value


def _id(value):
    require(type(value) is str and ID.fullmatch(value), 'Invalid naming identity')
    return value


def _token(value):
    require(type(value) is str and TOKEN.fullmatch(value), 'Naming fields require explicit identifier tokens')
    return value


def _name(value, quote='unquoted'):
    _text(value, 255)
    pattern = r'[A-Za-z_][A-Za-z0-9_]{0,254}' if quote == 'unquoted' else r'[A-Za-z_][A-Za-z0-9_ .-]{0,254}'
    require(re.fullmatch(pattern, value), 'Unsupported literal identifier; do not supply SQL or quote delimiters')
    return value


def _template(value):
    _text(value, 250)
    require(re.fullmatch(r'[A-Za-z0-9_{}]+', value), 'Templates accept identifier literals and bounded fields only')
    try:
        parts = list(Formatter().parse(value))
    except ValueError as error:
        raise ValueError('Invalid naming template') from error
    found = []
    for literal, field, spec, conversion in parts:
        require('{' not in literal and '}' not in literal, 'Escaped template braces are unsupported')
        if field is not None:
            require(field in {'layer', 'role', 'business_stem', 'domain'} and not spec and conversion is None,
                    'Unsupported naming template field or formatting')
            found.append(field)
    require('business_stem' in found, 'Naming template must retain the explicit business stem')
    return value


def _folder_template(value):
    _text(value, 250)
    parts = value.split('/')
    require(1 <= len(parts) <= 8 and all(re.fullmatch(r'[A-Za-z0-9_{}-]+', p) for p in parts),
            'Folder patterns require bounded relative literal directories')
    try:
        for literal, field, spec, conversion in Formatter().parse(value):
            require('{' not in literal and '}' not in literal and (field is None or
                    field in {'layer', 'role', 'business_stem', 'domain'} and not spec and conversion is None),
                    'Unsupported folder template field or formatting')
    except ValueError as error:
        raise ValueError('Invalid folder template') from error
    return value


def _column_rule(value):
    _fields(value, set(), {'case', 'primary_key', 'foreign_key'})
    require(bool(value), 'Column conventions cannot be empty')
    if 'case' in value:
        require(value['case'] in {'lower_snake', 'upper_snake'}, 'Unsupported column case convention')
    for kind in ('primary_key', 'foreign_key'):
        if kind not in value: continue
        rule = value[kind]; _fields(rule, set(), {'prefix', 'suffix'})
        require(any(rule.values()), 'Key conventions require a literal prefix or suffix')
        require(all(type(v) is str and len(v) <= 40 and re.fullmatch(r'[A-Za-z0-9_]*', v)
                    for v in rule.values()), 'Key conventions accept bounded identifier fragments only')
    return copy.deepcopy(value)


def validate_policy(policy):
    _fields(policy, {'schema_version', 'profile'}, {'platform', 'case', 'quote', 'templates',
        'fact_pattern', 'medallion_placement', 'include_raw', 'native_case_sensitive',
        'folder_patterns', 'column_rules'})
    require(type(policy['schema_version']) is int and policy['schema_version'] == 1
            and policy['profile'] in PROFILES, 'Unsupported naming policy version/profile')
    result = dict(copy.deepcopy(policy))
    result.setdefault('platform', 'unknown'); result.setdefault('case', 'lower'); result.setdefault('quote', 'unquoted')
    require(result['platform'] in PLATFORMS and result['case'] in {'lower', 'upper', 'preserve'}
            and result['quote'] in {'unquoted', 'quoted'}, 'Unsupported naming normalization')
    if 'native_case_sensitive' in result:
        require(type(result['native_case_sensitive']) is bool
                and result['platform'] in {'bigquery', 'fabric', 'redshift'}, 'Native case setting is only accepted for context-dependent platforms')
    profile = result['profile']
    require('templates' not in result or profile == 'custom', 'Custom templates require the custom profile')
    require('fact_pattern' not in result or profile == 'expanded', 'fact_pattern requires the expanded profile')
    require(not {'medallion_placement', 'include_raw'} & set(result) or profile == 'medallion',
            'Layer placement options require medallion profile')
    if profile == 'custom':
        templates = result.get('templates')
        require(type(templates) is dict and templates and set(templates) <= ROLES - {'source'}, 'Explicit role templates required')
        result['templates'] = {key: _template(value) for key, value in sorted(templates.items())}
    elif profile == 'expanded':
        result['fact_pattern'] = _template(result.get('fact_pattern'))
    elif profile == 'medallion':
        result.setdefault('medallion_placement', 'prefix'); result.setdefault('include_raw', False)
        require(result['medallion_placement'] in {'prefix', 'schema'} and type(result['include_raw']) is bool,
                'Invalid medallion placement')
    for field, validator in (('folder_patterns', _folder_template), ('column_rules', _column_rule)):
        if field in result:
            require(type(result[field]) is dict and result[field] and set(result[field]) <= ROLES - {'source'},
                    'Optional conventions require explicit non-source roles')
            result[field] = {role: validator(value) for role, value in sorted(result[field].items())}
    return result


def _store(state):
    value = state.get('workflow', {}).get('naming_governance')
    if value is not None:
        require(type(value) is dict and value.get('schema_version') == 1, 'Unsupported naming companion')
    return value


def access(state):
    """Return the selected policy, never silently adopt a proposed profile."""
    saved = _store(state)
    return copy.deepcopy(saved['selected']['policy']) if saved and saved.get('selected') else None


def _entities(state):
    return {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}


def _source(entity):
    return entity.get('object_kind') == 'source'


def _design_pin(entity):
    return hash_json({key: entity.get(key) for key in ('id', 'name', 'domain', 'layer', 'object_kind')})


def _namespace(value, quote):
    require(type(value) is list and 1 <= len(value) <= 3, 'Namespaces require ordered database/schema components')
    for part in value: _name(part, quote)


def _physical_policy(policy, row):
    relation = row['source_relation']
    if row['existing'] and relation and (row['physical_alias'] == relation['name']
            or row['physical_alias'] is None and row['target_name'] == row['original_name']):
        return dict(policy, quote=relation['quote'])
    return policy


def _empty():
    return {'schema_version': 1, 'selected': None, 'proposed': None, 'history': [], 'resources': [], 'exceptions': []}


def records(state, selected=None):
    rows = (_store(state) or {}).get('resources', [])
    chosen = set(selected) if selected is not None else None
    return [copy.deepcopy(row['resource']) for row in rows if chosen is None or row['resource']['entity_id'] in chosen]


def _expected(policy, row):
    if row['existing'] or row['role'] == 'source' or policy['profile'] == 'preserve':
        return row['original_name'], None
    profile, role = policy['profile'], row['role']
    if profile == 'abbreviated':
        prefix = {'staging': 'stg', 'intermediate': 'int', 'fact': 'fct', 'dimension': 'dim', 'mart': 'mart'}.get(role)
        template = prefix + '_{business_stem}' if prefix else None
    elif profile == 'expanded':
        prefix = {'staging': 'staging', 'intermediate': 'intermediate', 'dimension': 'dim', 'mart': 'mart'}.get(role)
        template = policy['fact_pattern'] if role == 'fact' else prefix + '_{business_stem}' if prefix else None
    elif profile == 'custom':
        template = policy['templates'].get(role)
    else:
        if row['layer'] == 'raw' and not policy['include_raw']:
            return None, None
        template = '{layer}_{business_stem}' if policy['medallion_placement'] == 'prefix' else '{business_stem}'
    if template is None:
        return None, None
    name = template.format(**{key: row[key] for key in ('layer', 'role', 'domain', 'business_stem')})
    if policy['case'] != 'preserve': name = getattr(name, policy['case'])()
    _name(name, policy['quote'])
    return name, row['layer'] if profile == 'medallion' and policy['medallion_placement'] == 'schema' else None


def _normalize(policy, value):
    platform, quote = policy['platform'], policy['quote']
    if platform == 'snowflake': return value.upper() if quote == 'unquoted' else value
    if platform == 'postgres': return value.lower() if quote == 'unquoted' else value
    if platform in {'databricks', 'motherduck'}: return value.casefold()
    if platform == 'clickhouse': return value
    if platform in {'bigquery', 'fabric', 'redshift'}:
        if 'native_case_sensitive' not in policy: return None
        return value if policy['native_case_sensitive'] else value.casefold()
    return None


def _exception(saved, row, field):
    return any(e['resource_id'] == row['id'] and field in e['fields']
               and e['values'].get(field) == row[field] for e in saved['exceptions'])


def _conventions(policy, row, entity, relationships):
    """Inspect declared metadata only; never derive keys or rewrite identifiers."""
    if not policy or not entity or row['existing'] or row['role'] == 'source' or _source(entity) or entity.get('disposition') == 'reuse':
        return {}, []
    folder = policy.get('folder_patterns', {}).get(row['role'])
    rules = policy.get('column_rules', {}).get(row['role'])
    material, gaps = {}, []
    if folder is not None:
        expected = folder.format(**{k: row[k] for k in ('layer', 'role', 'domain', 'business_stem')})
        require(len(expected) <= 1000, 'Expanded folder convention exceeds its bound')
        material['expected_folder'] = expected
    if rules is None: return material, gaps
    columns = [c['name'] for c in entity['columns']]
    material['column_rules'] = rules
    if 'case' in rules:
        pattern = r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*' if rules['case'] == 'lower_snake' else r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*'
        material['columns'] = sorted(columns)
        gaps.extend('column_case_nonconforming:' + name for name in columns if not re.fullmatch(pattern, name))
    for kind in ('primary_key', 'foreign_key'):
        if kind not in rules: continue
        keys = list(entity['keys']) if kind == 'primary_key' else []
        if kind == 'foreign_key':
            bindings = []
            for edge in relationships:
                if edge.get('kind') != 'relationship' or entity['id'] not in (edge['from'], edge['to']): continue
                cardinality = edge.get('cardinality')
                side = 'from' if cardinality == 'many_to_one' else 'to' if cardinality == 'one_to_many' else None
                if side is not None and edge[side] != entity['id']: continue
                bound = edge.get(side + '_columns') if side else None
                bindings.append({k: edge.get(k) for k in ('from', 'to', 'cardinality', 'from_columns', 'to_columns')})
                if not bound:
                    gaps.append('foreign_key_binding_unassessed')
                else:
                    keys.extend(bound)
            material['foreign_key_bindings'] = sorted(bindings, key=hash_json)
        material[kind + '_columns'] = sorted(set(keys))
        if kind == 'primary_key' and not keys: gaps.append('primary_key_binding_unassessed')
        rule = rules[kind]
        for name in sorted(set(keys)):
            if name not in columns: gaps.append(kind + '_column_absent:' + name)
            elif not name.startswith(rule.get('prefix', '')) or not name.endswith(rule.get('suffix', '')):
                gaps.append(kind + '_nonconforming:' + name)
    return material, sorted(set(gaps))


def _relationships(state):
    return (state.get('workflow', {}).get('design') or {}).get('relationships', [])


def folder_requirement(state, resource):
    """Exact relative directory for associated warehouse code, when selected."""
    conventions, _ = _conventions(access(state), resource, _entities(state).get(resource['entity_id']), ())
    return conventions.get('expected_folder')


def _row_status(saved, stored, entities, relationships=()):
    row = stored['resource']; policy = (saved.get('selected') or {}).get('policy')
    entity = entities.get(row['entity_id']); gaps = []
    expected, namespace = _expected(policy, row) if policy else (None, None)
    if not policy: gaps.append('policy_not_selected')
    if entity is None: gaps.append('entity_absent')
    elif stored['design_sha256'] != _design_pin(entity): gaps.append('design_changed')
    if entity is not None and entity.get('name') != row['target_name']: gaps.append('design_name_differs')
    if policy and expected is None: gaps.append('role_pattern_unspecified')
    elif expected is not None and row['target_name'] != expected and not _exception(saved, row, 'target_name'):
        gaps.append('name_nonconforming')
    if namespace is not None and row['namespace'][-1] != namespace and not _exception(saved, row, 'namespace'):
        gaps.append('logical_namespace_nonconforming')
    conventions, convention_gaps = _conventions(policy, row, entity, relationships)
    gaps.extend(convention_gaps)
    return {'id': row['id'], 'entity_id': row['entity_id'], 'target_name': row['target_name'],
            'physical_alias': row['physical_alias'], 'expected_name': expected, 'expected_logical_namespace': namespace,
            'layer': row['layer'], 'role': row['role'], 'domain': row['domain'],
            'status': 'gaps' if gaps else 'conforming', 'gaps': gaps,
            **({'conventions': conventions} if conventions else {}),
            'native_identity': 'unsupported' if not policy or _normalize(_physical_policy(policy, row), row['target_name']) is None else 'supplied_registry_only'}


def scope_bindings(state):
    saved = _store(state)
    if not saved: return {}
    entities = _entities(state); policy = access(state); by_entity = {r['resource']['entity_id']: r for r in saved['resources']}
    result = {}
    for key, entity in entities.items():
        row = by_entity.get(key)
        material = {'resource': row, 'current_design_sha256': _design_pin(entity)}
        if row:
            material['conformance'] = _row_status(saved, row, entities, _relationships(state))
            material['normalization'] = {k: policy.get(k) for k in ('platform', 'quote', 'native_case_sensitive')} if policy else None
            material['exceptions'] = [e for e in saved['exceptions'] if e['resource_id'] == row['resource']['id']]
        else:
            material['unregistered_policy'] = policy
        result[key] = hash_json(material)
    return result


def _publish(state, saved, before):
    require(len(saved['history']) <= 1000 and len(saved['exceptions']) <= MAX_RESOURCES, 'Naming history bound exceeded')
    require(type(state.get('workflow')) is dict, 'Adopt the staged workflow before configuring naming')
    # Validate derived names before committing, including bounded template expansion.
    candidate = dict(state, workflow=dict(state['workflow'], naming_governance=saved))
    after = scope_bindings(candidate)
    result = summarize(candidate)
    result['invalidated_entity_ids'] = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    state['workflow']['naming_governance'] = saved
    return result


def configure(state, request):
    _fields(request, {'schema_version', 'policy'}, {'decision_reference', 'change_reference'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported naming configuration')
    policy = validate_policy(request['policy']); saved = copy.deepcopy(_store(state) or _empty())
    before = scope_bindings(state); selected = saved['selected']
    decision = request.get('decision_reference')
    if decision is None:
        saved['proposed'] = {'policy': policy, 'policy_sha256': hash_json(policy)}
    else:
        _text(decision)
        if selected and selected['policy'] == policy:
            return dict(summarize(state), invalidated_entity_ids=[])
        change = request.get('change_reference')
        if selected: _text(change)
        elif change is not None: _text(change)
        entry = {'policy': policy, 'policy_sha256': hash_json(policy), 'decision_reference': decision,
                 'change_reference': change, 'authority': 'host_attributed_not_authenticated'}
        saved['selected'] = entry; saved['proposed'] = None
        saved['history'].append({'kind': 'policy_selection', **copy.deepcopy(entry)})
    return _publish(state, saved, before)


def _resource(row, entities, policy):
    required = {'id', 'entity_id', 'source_id', 'original_name', 'target_name', 'physical_alias', 'source_relation',
                'existing', 'layer', 'role', 'business_stem', 'domain', 'namespace', 'evidence_refs'}
    _fields(row, required)
    for key in ('id', 'entity_id', 'source_id'): _id(row[key])
    require('.' in row['source_id'] or ':' in row['source_id'], 'Source identity must be explicitly source-qualified')
    require(row['entity_id'] in entities, 'Naming resource references an absent canonical entity')
    entity = entities[row['entity_id']]
    require(type(row['existing']) is bool and row['layer'] in LAYERS and row['role'] in ROLES, 'Invalid resource kind/layer/role')
    require(row['layer'] == entity['layer'] and row['domain'] == entity.get('domain'), 'Resource layer/domain differs from canonical entity')
    require(not _source(entity) or row['role'] == 'source', 'Canonical source objects require protected source role')
    for key in ('business_stem', 'domain'): _token(row[key])
    _text(row['original_name'], 255)
    if row['source_relation'] is not None:
        relation = row['source_relation']; _fields(relation, {'namespace', 'name', 'quote'})
        require(relation['quote'] in {'unquoted', 'quoted'}, 'Unknown source relation quoting')
        _namespace(relation['namespace'], relation['quote']); _name(relation['name'], relation['quote'])
    physical_policy = _physical_policy(policy, row)
    _name(row['target_name'], relation['quote'] if row['existing'] and row['target_name'] == row['original_name']
          and (relation := row['source_relation']) else policy['quote'])
    _namespace(row['namespace'], physical_policy['quote'])
    if row['physical_alias'] is not None: _name(row['physical_alias'], physical_policy['quote'])
    refs = row['evidence_refs']
    require(type(refs) is list and len(refs) <= 100 and len(set(refs)) == len(refs), 'Invalid naming evidence references')
    for ref in refs: _text(ref)
    if row['role'] == 'source':
        require(row['target_name'] == row['original_name'], 'Source names are protected; rename a separate target model')
        require(row['physical_alias'] is None or row['source_relation'] is not None
                and row['physical_alias'] == row['source_relation']['name'], 'Source physical relation is protected')
    return copy.deepcopy(row)


def register(state, request):
    _fields(request, {'schema_version', 'resources'}, {'overrides'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported naming registration')
    saved = copy.deepcopy(_store(state)); require(saved is not None, 'Configure a proposed or selected naming policy first')
    policy = access(state) or saved['proposed']['policy']; entities = _entities(state)
    incoming = request['resources']
    require(type(incoming) is list and 0 < len(incoming) <= MAX_RESOURCES, 'Expected bounded nonempty resource inventory')
    rows = [_resource(row, entities, policy) for row in incoming]
    require(len({r['id'] for r in rows}) == len(rows) and len({r['entity_id'] for r in rows}) == len(rows), 'Duplicate resource/entity identity')
    prior = {r['resource']['id']: r for r in saved['resources']}; overrides = {}
    for value in request.get('overrides', []):
        _fields(value, {'resource_id', 'fields', 'decision_reference', 'reason'})
        rid = _id(value['resource_id']); require(rid in {r['id'] for r in rows} and rid not in overrides, 'Override must match one supplied resource')
        require(type(value['fields']) is list and value['fields'] and len(set(value['fields'])) == len(value['fields'])
                and set(value['fields']) <= {'target_name', 'physical_alias', 'namespace'}, 'Unsupported scoped override fields')
        _text(value['decision_reference']); _text(value['reason']); overrides[rid] = copy.deepcopy(value)
    immutable = ('id', 'entity_id', 'source_id', 'original_name', 'source_relation', 'existing')
    for row in rows:
        old = prior.get(row['id']); override = overrides.get(row['id'], {})
        if old:
            require(all(old['resource'][key] == row[key] for key in immutable), 'Stable source identity/original relation cannot drift')
            changed = {key for key in ('target_name', 'physical_alias', 'namespace') if old['resource'][key] != row[key]}
            require(changed <= set(override.get('fields', [])), 'Name or alias changes require an explicit scoped override')
        if row['existing'] and row['target_name'] != row['original_name']:
            require('target_name' in override.get('fields', []) or _exception(saved, row, 'target_name'), 'Existing names require an explicit scoped override')
        if row['existing'] and row['physical_alias'] is not None:
            original_alias = (row['source_relation'] or {}).get('name')
            require(row['physical_alias'] == original_alias or 'physical_alias' in override.get('fields', [])
                    or _exception(saved, row, 'physical_alias'), 'Existing physical alias requires an exact original relation or scoped override')
        if override:
            require(row['role'] != 'source', 'Source identities cannot receive target rename exceptions')
            entry = dict(override, values={key: row[key] for key in override['fields']}, authority='host_attributed_not_authenticated')
            if entry not in saved['exceptions']: saved['exceptions'].append(entry)
        prior[row['id']] = {'resource': row, 'design_sha256': _design_pin(entities[row['entity_id']])}
    combined = list(prior.values()); require(len(combined) <= MAX_RESOURCES, 'Resource inventory bound exceeded')
    require(len({r['resource']['entity_id'] for r in combined}) == len(combined), 'Canonical entity already has a different stable resource ID')
    logical, physical = {}, {}
    for record in combined:
        row = record['resource']; logical_key = row['target_name']
        # Physical sources in different namespaces may share a basename; only
        # generated/ref-able models occupy the dbt logical-name namespace.
        if row['role'] != 'source':
            require(logical_key not in logical, 'Duplicate generated model name'); logical[logical_key] = row['id']
        physical_policy = _physical_policy(policy, row)
        name = _normalize(physical_policy, row['physical_alias'] or row['target_name'])
        namespace = tuple(_normalize(physical_policy, part) for part in row['namespace'])
        key = (namespace, name) if name is not None else (tuple(row['namespace']), row['physical_alias'] or row['target_name'])
        require(key not in physical, 'Physical identity collision in supplied registry'); physical[key] = row['id']
    before = scope_bindings(state)
    saved['resources'] = sorted(combined, key=lambda r: r['resource']['id'])
    if saved != _store(state):
        saved['history'].append({'kind': 'identity_registration', 'resources_sha256': hash_json(saved['resources']),
                                 'resource_ids': sorted(r['id'] for r in rows)})
    return _publish(state, saved, before)


def stage_requirements(state, entity_ids):
    saved = _store(state)
    if not saved: return []
    selected = set(entity_ids); entities = _entities(state)
    gaps = []; registered = set()
    if not saved.get('selected'): gaps.append('naming: select a naming policy with a host-recorded user decision')
    for row in saved['resources']:
        rid = row['resource']['entity_id']
        if rid in selected:
            registered.add(rid)
            gaps.extend('naming:' + rid + ':' + gap for gap in _row_status(saved, row, entities, _relationships(state))['gaps'])
    gaps.extend('naming:' + key + ':identity_not_registered' for key in sorted(selected - registered))
    return sorted(set(gaps))


def summarize(state, selected=None):
    saved = _store(state)
    if not saved:
        return {'schema_version': 1, 'status': 'unassessed', 'resources': [], 'qualification': QUALIFICATION}
    entities = _entities(state); chosen = set(entities) if selected is None else set(selected)
    rows = [_row_status(saved, row, entities, _relationships(state)) for row in saved['resources'] if row['resource']['entity_id'] in chosen]
    gaps = stage_requirements(state, chosen)
    return {'schema_version': 1, 'status': 'proposed' if not saved['selected'] else 'gaps' if gaps else 'conforming',
            'policy': access(state), 'proposed_policy': copy.deepcopy(saved['proposed']), 'resources': rows,
            'resource_count': len(rows), 'missing_entity_ids': sorted(chosen - {r['entity_id'] for r in rows}),
            'gaps': gaps, 'history_count': len(saved['history']),
            'exception_count': sum(e['resource_id'] in {r['id'] for r in rows} for e in saved['exceptions']),
            'physical_collision_scope': 'supplied_registry_only_not_catalogue',
            'native_identity_status': 'unsupported' if any(r['native_identity'] == 'unsupported' for r in rows) else 'not_native_validated',
            'deployment_authorized': False, 'qualification': QUALIFICATION}
