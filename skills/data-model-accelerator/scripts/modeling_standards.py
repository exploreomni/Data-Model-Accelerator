"""Optional customer presentation standards; no rename, approval or native writes."""
import copy
import re
from ae_common import hash_json, require
from naming_governance import access as naming_policy

QUALIFICATION = ('Declared metadata preview only. Physical names remain governed by the selected naming policy. '
                 'No files, approvals, native controls or deployment state are changed.')


def _text(value):
    require(type(value) is str and 0 < len(value.strip()) <= 1000, 'Expected bounded standards text')
    return value


def _strings(value):
    require(type(value) is list and len(value) <= 1000 and all(_text(v) for v in value)
            and len(set(value)) == len(value), 'Expected distinct standards identifiers')
    return value


def normalize(document):
    require(type(document) is dict and set(document) == {'schema_version', 'version', 'request_reference', 'rules'},
            'Invalid modeling standards fields')
    require(type(document['schema_version']) is int and document['schema_version'] == 1, 'Unsupported standards version')
    _text(document['version']); _text(document['request_reference'])
    require(type(document['rules']) is list and len(document['rules']) <= 500, 'Standards rules must be bounded')
    seen = set()
    for rule in document['rules']:
        require(type(rule) is dict and set(rule) == {'id', 'entity_ids', 'domains', 'label_style',
            'required_tags', 'description_required', 'sample_queries_min'}, 'Invalid standards rule')
        require(_text(rule['id']) not in seen, 'Duplicate standards rule'); seen.add(rule['id'])
        _strings(rule['entity_ids']); _strings(rule['domains']); _strings(rule['required_tags'])
        require(bool(rule['entity_ids']) != bool(rule['domains']), 'Choose entity IDs or domains for each standards rule')
        require(rule['label_style'] in ('preserve', 'title_words', 'sentence_words'), 'Unsupported label style')
        require(type(rule['description_required']) is bool, 'Description requirement must be boolean')
        require(type(rule['sample_queries_min']) is int and 0 <= rule['sample_queries_min'] <= 20, 'Invalid sample-query minimum')
    return copy.deepcopy(document)


def _config(state):
    value = state.get('workflow', {}).get('modeling_standards')
    if value is None: return None
    require(type(value) is dict and set(value) == {'schema_version', 'version', 'request_reference', 'rules',
            'sha256', 'naming_policy_sha256', 'history'}, 'Invalid standards register')
    document = normalize({k: value[k] for k in ('schema_version', 'version', 'request_reference', 'rules')})
    require(hash_json(document) == value['sha256'], 'Standards register content changed')
    require(type(value['history']) is list and len(value['history']) < 100, 'Invalid standards history')
    return value


def configure(state, document):
    document = normalize(document)
    digest = hash_json(document)
    old = _config(state)
    pin = hash_json(naming_policy(state))
    if old and old['sha256'] == digest and old['naming_policy_sha256'] == pin: return
    previous = ([] if old is None else old['history'] + [{k: old[k] for k in
                 ('version', 'sha256', 'naming_policy_sha256')}])
    require(len(previous) < 100, 'Standards history limit reached')
    require(not any(r['version'] == document['version'] for r in previous),
            'Use a new standards version after changing rules or the naming policy')
    state['workflow']['modeling_standards'] = {**document, 'sha256': digest,
        'naming_policy_sha256': pin, 'history': previous}


def _selected(state, resource):
    config = _config(state)
    return [] if not config else [r for r in config['rules'] if resource['id'] in r['entity_ids']
                                 or resource.get('domain') in r['domains']]


def _scope_pin(state, resource, rules):
    config = state['workflow']['modeling_standards']
    # Scope changes invalidate affected previews; unrelated rules need no reread.
    return hash_json([rules, resource['id'], resource.get('name'), resource.get('domain'), config['naming_policy_sha256']])


def preview(state, request):
    require(type(request) is dict and set(request) == {'schema_version', 'resources'}
            and type(request['schema_version']) is int and request['schema_version'] == 1, 'Invalid standards preview')
    config = _config(state)
    require(config is not None, 'Configure standards before previewing metadata')
    require(type(request['resources']) is list and len(request['resources']) <= 2000, 'Preview a bounded domain batch')
    previous = {r['id']: r for r in state['workflow'].get('standards_preview', {}).get('resources', [])}
    design = {e['id']: e for e in (state['workflow'].get('design') or {}).get('entities', [])}
    rows, seen = [], set()
    for resource in request['resources']:
        require(type(resource) is dict and set(resource) == {'id', 'name', 'domain', 'label', 'tags', 'description', 'sample_query_count'},
                'Invalid standards resource; supply metadata only')
        identifier = _text(resource['id']); _text(resource['name']); _text(resource['domain'])
        require(identifier not in seen and (not design or identifier in design), 'Unknown or duplicate standards entity')
        seen.add(identifier)
        if design: require(resource['domain'] == design[identifier]['domain'] and resource['name'] == design[identifier]['name'],
                           'Preserve canonical entity name and domain in the preview')
        require(resource['label'] is None or type(resource['label']) is str and len(resource['label']) <= 1000, 'Invalid label')
        require(resource['description'] is None or type(resource['description']) is str and len(resource['description']) <= 8000, 'Invalid description')
        _strings(resource['tags'])
        require(type(resource['sample_query_count']) is int and resource['sample_query_count'] >= 0, 'Invalid query count')
        rules = _selected(state, resource); styles = {r['label_style'] for r in rules if r['label_style'] != 'preserve'}
        proposed = resource['label']; gaps = []
        if len(styles) > 1: gaps.append('standards.conflicting_label_rules')
        elif styles:
            words = resource['name'].replace('_', ' ')
            proposed = words.title() if 'title_words' in styles else words[:1].upper() + words[1:].lower()
            if resource['label'] != proposed: gaps.append('standards.label_differs')
        tags = sorted({t for r in rules for t in r['required_tags']} - set(resource['tags']))
        if tags: gaps.append('standards.tags_missing')
        if any(r['description_required'] for r in rules) and not (resource['description'] or '').strip(): gaps.append('standards.description_missing')
        minimum = max((r['sample_queries_min'] for r in rules), default=0)
        if resource['sample_query_count'] < minimum: gaps.append('standards.sample_queries_missing')
        scope_pin, metadata_pin = _scope_pin(state, resource, rules), hash_json(resource)
        old = previous.get(identifier, {})
        rows.append({'id': identifier, 'domain': resource['domain'], 'name': resource['name'],
            'current_label': resource['label'], 'proposed_label': proposed, 'missing_tags': tags,
            'sample_queries_min': minimum, 'findings': gaps, 'rule_ids': [r['id'] for r in rules],
            'scope_sha256': scope_pin, 'metadata_sha256': metadata_pin,
            'action': 'reuse' if old.get('scope_sha256') == scope_pin and old.get('metadata_sha256') == metadata_pin else 'review',
            'status': 'review_required' if gaps else 'conforming' if rules else 'out_of_scope'})
    result = {'schema_version': 1, 'kind': 'standards_preview', 'standards_version': config['version'],
        'standards_sha256': config['sha256'], 'naming_policy_sha256': config['naming_policy_sha256'],
        'resources': rows, 'changes_applied': False, 'native_verified': False, 'qualification': QUALIFICATION}
    state['workflow']['standards_preview'] = result
    return copy.deepcopy(result)


def summary(state, selected=None):
    config = _config(state)
    if not config: return None
    preview = state['workflow'].get('standards_preview') or {}
    rows = [r for r in preview.get('resources', []) if selected is None or r['id'] in selected]
    design = {e['id']: e for e in (state['workflow'].get('design') or {}).get('entities', [])}
    stale = config['naming_policy_sha256'] != hash_json(naming_policy(state))
    for row in rows:
        resource = design.get(row['id'], row)
        stale |= row['scope_sha256'] != _scope_pin(state, resource, _selected(state, resource))
    return {'version': config['version'], 'sha256': config['sha256'],
            'status': 'stale' if stale else 'review_required' if any(r['findings'] for r in rows) else 'previewed' if rows else 'not_previewed',
            'resources': copy.deepcopy(rows), 'qualification': QUALIFICATION}


def packet(state, selected):
    require(type(selected) is list and selected, 'Select entities for a standards packet')
    config = _config(state)
    if not config: return None
    entities = {e['id']: e for e in (state['workflow'].get('design') or {}).get('entities', [])}
    require(set(selected) <= set(entities), 'Standards packet requires existing entity IDs')
    rules = {r['id']: r for key in selected for r in _selected(state, entities[key])}
    scoped = []
    for rule in rules.values():
        scoped.append({**rule, 'domains': [], 'entity_ids': [key for key in selected if rule in _selected(state, entities[key])]})
    # Global revision metadata stays in the register/summary. A specialist binds
    # only its selected contract, so unrelated rule changes preserve its receipt.
    result = {'schema_version': 1, 'kind': 'modeling_standards_context',
        'entity_ids': sorted(set(selected)), 'rules': scoped, 'naming_policy_sha256': config['naming_policy_sha256'],
        'naming_current': config['naming_policy_sha256'] == hash_json(naming_policy(state)), 'qualification': QUALIFICATION}
    result['sha256'] = hash_json(result)
    return result


def validate_packet(request):
    body = request.get('modeling_standards'); pin = request.get('bindings', {}).get('modeling_standards')
    if body is None:
        require(pin is None, 'Standards pin requires its packet'); return None
    require(type(body) is dict and set(body) == {'schema_version', 'kind', 'entity_ids', 'rules',
            'naming_policy_sha256', 'naming_current', 'qualification', 'sha256'}, 'Invalid standards context')
    require(type(body['schema_version']) is int and body['schema_version'] == 1 and body['kind'] == 'modeling_standards_context', 'Invalid standards context version')
    _strings(body['entity_ids']); require(bool(body['entity_ids']), 'Empty standards context')
    require(type(body['naming_current']) is bool and body['qualification'] == QUALIFICATION, 'Invalid standards qualification')
    require(type(body['naming_policy_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', body['naming_policy_sha256']),
            'Invalid standards naming-policy pin')
    if request.get('brief'):
        require(set(body['entity_ids']) <= set(request['brief']['scope_ids']), 'Standards exceed the specialist task scope')
    normalize({'schema_version': 1, 'version': 'scoped', 'request_reference': 'packet', 'rules': body['rules']})
    require(all(not r['domains'] and set(r['entity_ids']) <= set(body['entity_ids']) for r in body['rules']), 'Standards packet expands scope')
    require(pin == body['sha256'] == hash_json({k: v for k, v in body.items() if k != 'sha256'}), 'Standards packet pin mismatch')
    return copy.deepcopy(body)


def scope_bindings(state):
    if not state.get('workflow', {}).get('modeling_standards'): return {}
    return {e['id']: _scope_pin(state, e, rules) for e in
            (state['workflow'].get('design') or {}).get('entities', [])
            if (rules := _selected(state, e))}
