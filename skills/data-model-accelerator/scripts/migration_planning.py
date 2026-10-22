"""Optional migration planning evidence and human edits; no execution authority.

Mappings remain owned by legacy_alignment. Planning records are proposals, not
design approval, verified lineage/parity, ticket writes or completed delivery.
"""
import copy
import datetime
import hashlib

from ae_common import hash_json, require, safe_relative
from engagement_stages import fields, identifier, ids, text, SHA
from review_assurance import load_document

VERSION = '1'
QUALIFICATION = ('Reviewable migration planning proposals only. Supplied/observed lineage is not '
                 'independently verified parity, approval, delivery, ticket publication or deployment. '
                 'Unknown owners, dates and complexity remain unknown.')
FORMATS = {'local', 'google', 'both'}
PLATFORMS = {'jira', 'linear', 'azure_devops', 'monday', 'asana', 'github', 'generic'}
STATUSES = {'proposed', 'observed', 'unresolved', 'unsupported'}
DISPOSITIONS = {'preserve', 'reconnect', 'rebuild', 'retire_candidate', 'out_of_scope', 'unresolved'}
EDIT_FIELDS = {'notes', 'owner', 'priority', 'due_date'}
UNKNOWN_EFFORT = {'complexity': None, 'confidence': 'unknown', 'basis': 'Not supplied.'}
MAX_ROWS = 2000


def _version(value):
    require(type(value.get('schema_version')) is int and value['schema_version'] == 1,
            'Unsupported migration planning schema')


def _safe(value):
    import guided_workflow as guided
    guided._secrets(value)
    require(len(guided._bytes(value)) <= guided.MAX_JSON_BYTES, 'Migration plan exceeds bounded size')


def _rows(rows, name):
    require(type(rows) is list and len(rows) <= MAX_ROWS and all(type(r) is dict for r in rows),
            'Invalid bounded ' + name)
    ids([r.get('id') for r in rows])
    return rows


def _state(state):
    value = state.get('workflow', {}).get('migration_planning')
    if value is not None:
        fields(value, {'schema_version', 'domains', 'plans'}); _version(value)
        require(type(value['domains']) is dict and type(value['plans']) is dict, 'Invalid migration planning state')
    return value


def _active(state, domain_id):
    from domain_workflow import ledger
    value = ledger(state)
    if value:
        require(value['active_domain_id'] == domain_id, 'Select this domain before changing its migration plan')


def _models(state):
    return {m['id']: m for m in (state.get('workflow', {}).get('design') or {}).get('entities', [])}


def _scope(state, domain_id):
    from legacy_alignment import _domain_models
    from engagement_stages import closure
    models = _models(state)
    selected = _domain_models(state, domain_id) & set(models)
    return set(closure({k: m['depends_on'] for k, m in models.items()}, sorted(selected))) if selected else set()


def _config(state, domain_id):
    value = _state(state)
    require(value is not None and domain_id in value['domains'], 'Configure migration planning for the domain first')
    return value['domains'][domain_id]


def configure(state, request):
    fields(request, {'schema_version', 'domain_id', 'mode', 'output_format', 'ticket_platform', 'request_reference'})
    _version(request); identifier(request['domain_id']); text(request['request_reference'])
    require(request['mode'] in {'new_model', 'refactor', 'mixed'} and request['output_format'] in FORMATS
            and request['ticket_platform'] in PLATFORMS, 'Invalid migration planning selection')
    require(type(state.get('workflow')) is dict, 'Adopt stages before configuring migration planning')
    _active(state, request['domain_id']); _safe(request)
    value = copy.deepcopy(_state(state) or {'schema_version': 1, 'domains': {}, 'plans': {}})
    value['domains'][request['domain_id']] = copy.deepcopy(request)
    state['workflow']['migration_planning'] = value
    return public_summary(state)


def _inventory(state, domain_id, allowed_models=None):
    from legacy_alignment import public_summary as alignment_summary
    summary = alignment_summary(state, allowed_models)
    return next((d for d in (summary or {}).get('domains', []) if d['domain_id'] == domain_id),
                {'baseline_status': 'not_supplied', 'freshness': 'current', 'tables': [], 'mappings': [],
                 'unmatched': [], 'coverage': {}, 'omitted_details': False})


def _known_consumers(state, domain_id):
    from domain_workflow import ledger
    from migration_review import load
    scope = _scope(state, domain_id); models = _models(state)
    domain = next((d for d in (ledger(state) or {}).get('domains', []) if d['id'] == domain_id), {})
    labels = {domain_id.casefold(), domain.get('name', domain_id).casefold()}
    found = {key: {'id': key, 'label': key, 'model_ids': []} for key in domain.get('asset_ids', [])}
    for key in scope:
        for asset in models[key].get('asset_ids', []):
            found.setdefault(asset, {'id': asset, 'label': asset, 'model_ids': []})['model_ids'].append(key)
    # Retain all declared consumers of a shared asset, not only the current
    # domain's link, so a restricted projection cannot disclose its name.
    for key, model in models.items():
        for asset in model.get('asset_ids', []):
            if asset in found: found[asset]['model_ids'].append(key)
    design_assets = {a['id']: a for a in (state['workflow'].get('design') or {}).get('assets', [])}
    for key, value in found.items():
        value['label'] = design_assets.get(key, {}).get('name', key)
    portfolio = load(state, 'portfolio')
    for asset in (portfolio or {}).get('request', {}).get('assets', []):
        if asset.get('domain', '').casefold() in labels or set(asset.get('model_ids', [])) & scope:
            found[asset['id']] = {'id': asset['id'], 'label': asset['name'], 'model_ids': asset['model_ids']}
    parity = load(state, 'parity')
    for row in (parity or {}).get('report', {}).get('crosswalk', []):
        if set(row['model_ids']) & scope or row['dashboard_id'] in found:
            for key, label in ((row['dashboard_id'], row['dashboard_label']), (row['subject_id'], row['source_label'])):
                entry = found.setdefault(key, {'id': key, 'label': label, 'model_ids': []})
                entry['model_ids'] = sorted(set(entry['model_ids']) | set(row['model_ids']))
    for row in found.values(): row['model_ids'] = sorted(set(row['model_ids']))
    return found


def _migration_context(state, domain_id):
    """Reuse scoped definitions and consumer IDs without importing parity authority."""
    from business_rules import summary as rule_summary
    from migration_review import load
    scope = _scope(state, domain_id)
    rules = rule_summary(state, scope if scope else None)['rows']
    if not scope:
        rules = [r for r in rules if set(r['scope']['domains']) == {domain_id} and not r['scope']['model_ids']]
    definitions = [{k: copy.deepcopy(r[k]) for k in ('id', 'name', 'statement', 'definition', 'status', 'model_ids')}
                   for r in rules]
    value = load(state, 'parity'); crosswalk = []
    for row in (value or {}).get('report', {}).get('crosswalk', []):
        if row['model_ids'] and set(row['model_ids']) <= scope:
            crosswalk.append({k: copy.deepcopy(row[k]) for k in ('subject_kind', 'subject_id', 'dashboard_id',
                'dashboard_label', 'source_label', 'model_ids', 'topic_ids')})
    result = {'definitions': definitions, 'consumer_crosswalk': crosswalk, 'validation_status': 'not_revalidated',
              'qualification': 'Planning reuses supplied definitions and crosswalk identities only. Consult the separate current validation scorecard; no pass/fail result is inherited.'}
    from migration_context import task_contracts, contract_bindings
    contracts = task_contracts(state, [domain_id, *sorted(scope)])
    if contracts:
        # The same material feeds work claims and retained-plan freshness. Do
        # not include authored assessments or change hashes for older plans.
        context = {'bindings': contract_bindings(contracts)}
        own = next((c for c in contracts if c['domain_id'] == domain_id), None)
        if own:
            value = own['intent']
            context['intent'] = {k: copy.deepcopy(value[k]) for k in
                ('domain_id', 'structural_objective', 'behavior', 'objectives', 'behavior_constraints')}
            context['intent']['source_roles'] = [{k: r[k] for k in ('id', 'root_id', 'role')}
                                                  for r in value['source_roles']]
        # Shared-domain contracts affect freshness, but their private prose and
        # repository scopes are not part of this domain's public projection.
        result['migration_intents'] = context
    return result


def _evidence(rows):
    require(type(rows) is list and len(rows) <= 64, 'Invalid evidence descriptors')
    for row in rows:
        fields(row, {'label', 'reference'}, {'source_path', 'sha256'})
        text(row['label']); text(row['reference'])
        require(('source_path' in row) == ('sha256' in row), 'Local evidence needs source path and hash')
        if 'source_path' in row:
            safe_relative(row['source_path'])
            require(type(row['sha256']) is str and SHA.fullmatch(row['sha256']), 'Invalid evidence hash')


def _editable(row):
    for key in EDIT_FIELDS & set(row):
        if row[key] is None: continue  # An explicit human clear survives regeneration.
        text(row[key])
        if key == 'due_date':
            require(len(row[key]) == 10 and datetime.date.fromisoformat(row[key]).isoformat() == row[key],
                    'Due date must be a supplied ISO date')


def _acyclic(graph, label):
    # Iterative Kahn traversal avoids recursion depth failure on bounded long plans.
    remaining = {key: set(parents) for key, parents in graph.items()}
    require(all(p in remaining for parents in remaining.values() for p in parents), 'Dangling ' + label)
    ready = [key for key, parents in remaining.items() if not parents]; count = 0
    children = {key: [] for key in remaining}
    for key, parents in remaining.items():
        for parent in parents: children[parent].append(key)
    while ready:
        key = ready.pop(); count += 1
        for child in children[key]:
            remaining[child].remove(key)
            if not remaining[child]: ready.append(child)
    require(count == len(remaining), 'Cyclic ' + label)


def _validate(request, state=None):
    fields(request, {'schema_version', 'domain_id', 'consumers', 'work_items'},
           {'decisions', 'questions', 'waves', 'narrative', 'source_lineage', 'expected_plan_sha256'})
    _version(request); identifier(request['domain_id'])
    if 'expected_plan_sha256' in request:
        pin = request['expected_plan_sha256']
        require(pin is None or type(pin) is str and SHA.fullmatch(pin), 'Invalid expected plan hash')
    normalized = copy.deepcopy(request)
    for key in ('decisions', 'questions', 'waves'): normalized.setdefault(key, [])
    normalized.setdefault('narrative', '')
    require(type(normalized['narrative']) is str and len(normalized['narrative']) <= 16000, 'Invalid plan narrative')
    normalized.setdefault('source_lineage', {'nodes': [], 'edges': []})
    scope = _scope(state, request['domain_id']) if state is not None else None
    models = set(_models(state)) if state is not None else None
    inventory = _inventory(state, request['domain_id']) if state is not None else None
    tables = {r['id'] for r in inventory['tables']} if inventory else None
    mappings = {r['id'] for r in inventory['mappings']} if inventory else None
    consumers = _rows(normalized['consumers'], 'consumers'); consumer_ids = {r['id'] for r in consumers}
    for row in consumers:
        fields(row, {'id', 'kind', 'label', 'model_ids', 'topic_ids', 'status'},
               {'parent_id', 'legacy_table_ids', 'disposition', 'evidence_refs'})
        require(row['kind'] in {'dashboard', 'chart'} and row['status'] in STATUSES, 'Invalid consumer kind or status')
        text(row['label']); ids(row['model_ids'], models); ids(row['topic_ids'])
        row.setdefault('legacy_table_ids', []); ids(row['legacy_table_ids'], tables)
        row.setdefault('disposition', 'unresolved'); require(row['disposition'] in DISPOSITIONS, 'Invalid consumer disposition')
        row.setdefault('evidence_refs', []); _evidence(row['evidence_refs'])
        require(row['status'] != 'observed' or row['evidence_refs'], 'Observed consumer needs supplied evidence')
        if 'parent_id' in row:
            parent = next((c for c in consumers if c['id'] == row['parent_id']), None)
            require(row['kind'] == 'chart' and parent is not None and parent['kind'] == 'dashboard', 'Invalid consumer parent')
    _acyclic({r['id']: [r['parent_id']] if 'parent_id' in r else [] for r in consumers}, 'consumer hierarchy')
    items = _rows(normalized['work_items'], 'work items'); item_ids = {r['id'] for r in items}
    for row in items:
        fields(row, {'id', 'title', 'outcome', 'scope', 'model_ids', 'mapping_ids', 'consumer_ids',
                     'acceptance_criteria', 'dependencies'}, EDIT_FIELDS | {'effort', 'operation', 'external_id'})
        for key in ('title', 'outcome', 'scope'): text(row[key])
        ids(row['model_ids'], scope); ids(row['mapping_ids'], mappings); ids(row['consumer_ids'], consumer_ids)
        ids(row['dependencies'], item_ids)
        criteria = _rows(row['acceptance_criteria'], 'acceptance criteria')
        require(bool(criteria), 'Work item needs independent acceptance criteria')
        for criterion in criteria:
            fields(criterion, {'id', 'expected', 'evidence_ref'}, {'evidence_label'})
            text(criterion['expected'])
            if criterion['evidence_ref'] is not None: text(criterion['evidence_ref'])
            if 'evidence_label' in criterion: text(criterion['evidence_label'])
        row.setdefault('effort', copy.deepcopy(UNKNOWN_EFFORT)); effort = row['effort']
        fields(effort, {'complexity', 'confidence', 'basis'})
        require(effort['complexity'] in {None, 'Easy', 'Somewhat easy', 'Difficult', 'Very difficult'}
                and effort['confidence'] in {'unknown', 'low', 'medium', 'high'}, 'Invalid complexity estimate')
        require(effort['complexity'] is not None or effort['confidence'] == 'unknown', 'Unknown complexity needs unknown confidence')
        text(effort['basis']); _editable(row)
        row.setdefault('operation', 'create'); require(row['operation'] in {'create', 'update', 'review'}, 'Invalid ticket proposal operation')
        if 'external_id' in row: text(row['external_id'])
        require(row['operation'] != 'update' or row.get('external_id'), 'Update proposal requires supplied external ID')
    _acyclic({r['id']: r['dependencies'] for r in items}, 'work item dependencies')
    for name in ('decisions', 'questions'):
        for row in _rows(normalized[name], name):
            fields(row, {'id', 'text', 'model_ids', 'consumer_ids'})
            text(row['text']); ids(row['model_ids'], scope); ids(row['consumer_ids'], consumer_ids)
    waves = _rows(normalized['waves'], 'waves'); wave_ids = {r['id'] for r in waves}; assigned = set()
    for row in waves:
        fields(row, {'id', 'title', 'item_ids', 'depends_on'}); text(row['title'])
        ids(row['item_ids'], item_ids); ids(row['depends_on'], wave_ids)
        require(not assigned & set(row['item_ids']), 'Work item belongs to multiple waves'); assigned.update(row['item_ids'])
    _acyclic({r['id']: r['depends_on'] for r in waves}, 'wave dependencies')
    lineage = normalized['source_lineage']; fields(lineage, {'nodes', 'edges'})
    nodes = _rows(lineage['nodes'], 'source lineage nodes'); node_ids = {r['id'] for r in nodes}
    for row in nodes:
        fields(row, {'id', 'kind', 'label'}, {'legacy_table_id', 'native_id'})
        text(row['label']); require(row['kind'] in {'source', 'transformation', 'legacy_table'}, 'Invalid source lineage node')
        if 'native_id' in row: text(row['native_id'])
        require(('legacy_table_id' in row) == (row['kind'] == 'legacy_table'), 'Legacy lineage node needs exact table binding')
        if 'legacy_table_id' in row: ids([row['legacy_table_id']], tables)
    graph = {key: [] for key in node_ids}; edge_pairs = set()
    for row in _rows(lineage['edges'], 'source lineage edges'):
        fields(row, {'id', 'source_id', 'target_id', 'status', 'evidence_refs'}, {'native_id'})
        if 'native_id' in row: text(row['native_id'])
        ids([row['source_id'], row['target_id']], node_ids)
        pair = (row['source_id'], row['target_id']); require(pair not in edge_pairs, 'Duplicate source lineage edge'); edge_pairs.add(pair)
        require(row['status'] in STATUSES, 'Invalid source lineage status'); _evidence(row['evidence_refs'])
        require(row['status'] != 'observed' or row['evidence_refs'], 'Observed lineage needs supplied evidence')
        graph[row['target_id']].append(row['source_id'])
    _acyclic(graph, 'source lineage')
    _safe(normalized)
    return normalized


def _load(state, domain_id):
    reference = _config(state, domain_id) and _state(state)['plans'].get(domain_id)
    if reference is None: return None
    doc = load_document(reference)
    fields(doc, {'schema_version', 'kind', 'request', 'request_sha256', 'binding', 'human_edits', 'edit_history', 'version'})
    _version(doc); require(doc['kind'] == 'migration_plan' and doc['version'] == VERSION, 'Invalid retained migration plan')
    require(doc['request_sha256'] == hash_json(doc['request']), 'Retained planning request changed')
    require(_validate(doc['request']) == doc['request'], 'Retained planning request malformed')
    require(doc['request']['domain_id'] == domain_id, 'Retained planning domain changed')
    require(type(doc['human_edits']) is dict and type(doc['edit_history']) is list, 'Invalid retained human edits')
    for key, row in doc['human_edits'].items():
        identifier(key); fields(row, set(), EDIT_FIELDS); _editable(row)
    _safe(doc)
    return doc


def _evidence_pins(state, request, *, strict=False):
    from engagement_stages import _source_hash
    descriptors = [e for c in request['consumers'] for e in c['evidence_refs']]
    descriptors += [e for edge in request['source_lineage']['edges'] for e in edge['evidence_refs']]
    pins = {}
    for row in descriptors:
        if 'source_path' not in row: continue
        path = row['source_path']
        if path not in pins:
            try: pins[path] = _source_hash(state, path)
            except (ValueError, OSError): pins[path] = 'unavailable'
        if strict: require(pins[path] == row['sha256'], 'Source lineage/consumer evidence changed or unavailable')
    return pins


def _binding(state, domain_id, request):
    from legacy_alignment import _target_pin
    scope = _scope(state, domain_id); cache = {}
    # Shared consumer contracts are included only where explicitly referenced.
    selected = scope | {m for c in request['consumers'] for m in c['model_ids']}
    config = {k: v for k, v in _config(state, domain_id).items() if k != 'request_reference'}
    return hash_json({'version': VERSION, 'config': config, 'inventory': _inventory(state, domain_id),
                      'targets': {key: _target_pin(state, {'model_id': key, 'kind': 'table'}, cache) for key in sorted(selected)},
                      'known_consumers': _known_consumers(state, domain_id), 'migration_context': _migration_context(state, domain_id),
                      'evidence': _evidence_pins(state, request)})


def _store(state, domain_id, document, run_dir):
    import guided_workflow as guided
    _safe(document); root = guided._path(run_dir)
    guided._outside(root, guided._path(state['inputs']['source']['path']))
    folder = root / 'migration-planning'; require(not folder.is_symlink(), 'Planning directory cannot be a symlink')
    folder.mkdir(exist_ok=True); raw = guided._bytes(document); digest = hashlib.sha256(raw).hexdigest()
    path = folder / (digest + '.json'); reference = {'path': str(path), 'sha256': digest, 'bytes': len(raw)}
    if path.exists(): require(load_document(reference) == document, 'Planning evidence changed')
    else: guided._atomic_write(path, raw, replace=False)
    value = copy.deepcopy(_state(state)); value['plans'][domain_id] = reference
    state['workflow']['migration_planning'] = value


def register_plan(state, request, run_dir):
    domain_id = request.get('domain_id'); _config(state, domain_id); _active(state, domain_id)
    normalized = _validate(request, state)
    current = _state(state)['plans'].get(domain_id)
    require(normalized.get('expected_plan_sha256') == (current['sha256'] if current else None),
            'Plan changed; use the current expected_plan_sha256 before regenerating')
    normalized.pop('expected_plan_sha256', None)  # Concurrency token is not plan content.
    old = _load(state, domain_id)
    _evidence_pins(state, normalized, strict=True)
    document = {'schema_version': 1, 'kind': 'migration_plan', 'version': VERSION, 'request': normalized,
                'request_sha256': hash_json(normalized), 'binding': _binding(state, domain_id, normalized),
                'human_edits': copy.deepcopy(old['human_edits']) if old else {},
                'edit_history': copy.deepcopy(old['edit_history']) if old else []}
    _store(state, domain_id, document, run_dir)
    return public_summary(state)


def edit_items(state, request, run_dir):
    fields(request, {'schema_version', 'domain_id', 'plan_sha256', 'request_reference', 'edits'})
    _version(request); domain_id = request['domain_id']; _config(state, domain_id); _active(state, domain_id)
    text(request['request_reference']); require(type(request['plan_sha256']) is str and SHA.fullmatch(request['plan_sha256']), 'Invalid plan hash')
    reference = _state(state)['plans'].get(domain_id)
    require(reference and reference['sha256'] == request['plan_sha256'], 'Plan changed; reload before applying human edits')
    doc = _load(state, domain_id); known = {r['id'] for r in doc['request']['work_items']}
    for row in _rows(request['edits'], 'human edits'):
        fields(row, {'id'}, EDIT_FIELDS); ids([row['id']], known)
        require(set(row) & EDIT_FIELDS, 'Human edit is empty'); _editable(row)
        doc['human_edits'].setdefault(row['id'], {}).update({k: v for k, v in row.items() if k != 'id'})
    _safe(request)
    doc['edit_history'].append({'request_reference': request['request_reference'], 'plan_sha256': request['plan_sha256'],
                                'edits': copy.deepcopy(request['edits']), 'assurance': 'host_reported_human_edit'})
    _store(state, domain_id, doc, run_dir)
    return public_summary(state)


def _public_models(state, scope):
    allowed = {'name', 'type', 'description', 'nullable', 'primary_key', 'key'}
    result = []
    for key in sorted(scope):
        model = _models(state)[key]
        row = {k: copy.deepcopy(model[k]) for k in ('id', 'name', 'domain', 'layer', 'grain', 'keys', 'depends_on', 'disposition') if k in model}
        row['columns'] = [{k: copy.deepcopy(v) for k, v in c.items() if k in allowed} for c in model.get('columns', [])]
        result.append(row)
    return result


def _redact_private(value, state, document=None):
    """Do not let a private reference copied into a display field escape projection."""
    forbidden = {state['inputs']['source']['path']}
    if value.get('migration_context', {}).get('migration_intents'):
        from source_roots import approved_roots
        forbidden.update(str(path) for path in approved_roots(state))
        for record in state.get('workflow', {}).get('migration_intents', {}).values():
            contract = record.get('intent', {})
            if contract.get('request_reference'): forbidden.add(contract['request_reference'])
            forbidden.update(r['path_prefix'] for r in contract.get('source_roles', []) if r.get('path_prefix'))
    if document:
        request = document['request']
        for row in request['consumers']:
            for ref in row['evidence_refs']:
                forbidden.add(ref['reference'])
                if 'source_path' in ref: forbidden.add(ref['source_path'])
        for row in request['source_lineage']['edges']:
            for ref in row['evidence_refs']:
                forbidden.add(ref['reference'])
                if 'source_path' in ref: forbidden.add(ref['source_path'])
        for item in request['work_items']:
            forbidden.update(c['evidence_ref'] for c in item['acceptance_criteria'] if c['evidence_ref'])
    prose = {'name', 'label', 'title', 'outcome', 'scope', 'expected', 'evidence_label', 'evidence_labels',
             'notes', 'owner', 'priority', 'basis', 'text', 'narrative', 'description', 'grain', 'native_id', 'warnings',
             'statement', 'source_label', 'dashboard_label', 'behavior_constraints'}
    def visit(node, field=None):
        if isinstance(node, dict): return {key: visit(item, key) for key, item in node.items()}
        if isinstance(node, list): return [visit(item, field) for item in node]
        if isinstance(node, str) and field in prose:
            for private in sorted(forbidden, key=len, reverse=True):
                if private: node = node.replace(private, '[private reference]')
        return node
    return visit(value)


def _public_lineage(request, permitted_tables, *, restricted=False):
    lineage = request['source_lineage']; nodes = lineage['nodes']; omitted = False
    if restricted and any(n.get('legacy_table_id') not in permitted_tables for n in nodes if n['kind'] == 'legacy_table'):
        # Upstream nodes may be shared. Without consumer-specific ownership, omit
        # the graph instead of guessing which upstream labels can be disclosed.
        nodes = []; omitted = True
    node_ids = {n['id'] for n in nodes}
    edges = [{k: copy.deepcopy(v) for k, v in e.items() if k != 'evidence_refs'} |
             {'evidence_labels': [x['label'] for x in e['evidence_refs']]}
             for e in lineage['edges'] if e['source_id'] in node_ids and e['target_id'] in node_ids]
    return {'status': 'supplied' if nodes else 'unknown', 'nodes': copy.deepcopy(nodes), 'edges': edges, 'omitted_details': omitted}


def _edges(inventory, consumers):
    edges = []
    for mapping in inventory['mappings']:
        status = 'unsupported' if mapping['status'] == 'unsupported' else 'unresolved' if mapping['status'] != 'mapped' else 'proposed'
        # Represent the mapping as a group node: a Cartesian product would invent
        # pairwise lineage for a declared many-to-many relationship.
        hub = {'kind': 'mapping', 'id': mapping['id']}
        for index, source in enumerate(mapping['legacy_sources']):
            edges.append({'id': mapping['id'] + ':source:' + str(index), 'source': {'kind': 'legacy_' + source['kind'],
                'id': source['table_id'], **({'field_id': source['field_id']} if 'field_id' in source else {})},
                'target': hub, 'mapping_id': mapping['id'], 'status': status, 'evidence_labels': mapping['evidence_labels']})
        for index, target in enumerate(mapping['targets']):
            edges.append({'id': mapping['id'] + ':target:' + str(index), 'source': hub,
                'target': {'kind': 'model', 'id': target['model_id'], **({'field': target['field']} if 'field' in target else {})},
                'mapping_id': mapping['id'], 'status': status, 'evidence_labels': mapping['evidence_labels']})
    for consumer in consumers:
        for kind, key in (('legacy_table', 'legacy_table_ids'), ('model', 'model_ids'), ('topic', 'topic_ids')):
            for target in consumer[key]:
                edges.append({'id': consumer['id'] + ':' + kind + ':' + target,
                    'source': {'kind': kind, 'id': target}, 'target': {'kind': 'consumer', 'id': consumer['id']},
                    'status': consumer['status'], 'evidence_labels': consumer['evidence_labels']})
    return edges


def _summary(state, domain_id, allowed_models):
    config = _config(state, domain_id); scope = _scope(state, domain_id)
    allowed = set(allowed_models) if allowed_models is not None else None
    if allowed is not None and (not scope or not scope <= allowed): return None
    inventory = _inventory(state, domain_id, allowed_models)
    upstream_freshness = inventory['freshness']
    inventory = {k: copy.deepcopy(inventory[k]) for k in ('baseline_status', 'tables', 'mappings', 'unmatched', 'coverage', 'omitted_details')}
    result = {'domain_id': domain_id, 'plan_sha256': None, 'freshness': 'unassessed',
              'config': {k: v for k, v in config.items() if k not in ('schema_version', 'request_reference')},
              'model_ids': sorted(scope), 'models': _public_models(state, scope), 'inventory': inventory,
              'relationships': [{k: copy.deepcopy(v) for k, v in r.items() if k in {'from', 'to', 'kind', 'cardinality', 'from_columns', 'to_columns'}}
                                for r in (state['workflow'].get('design') or {}).get('relationships', []) if r['from'] in scope and r['to'] in scope],
              'graph_edges': [], 'consumers': [], 'work_items': [], 'decisions': [], 'questions': [], 'waves': [],
              'narrative': '', 'archived_edits': [], 'warnings': [], 'missing_consumers': [],
              'migration_context': {'definitions': [], 'consumer_crosswalk': [], 'validation_status': 'not_revalidated'},
              'consumer_coverage': {'total': None, 'supplied': 0, 'missing': None, 'completeness': 'unavailable'},
              'source_lineage': {'status': 'unknown', 'nodes': [], 'edges': [], 'omitted_details': False}}
    doc = None
    try:
        known = _known_consumers(state, domain_id)
        known = {k: r for k, r in known.items() if allowed is None or set(r['model_ids']) <= allowed}
        result['migration_context'] = _migration_context(state, domain_id)
        doc = _load(state, domain_id)
        if doc:
            result['plan_sha256'] = _state(state)['plans'][domain_id]['sha256']
            result['freshness'] = 'current' if doc['binding'] == _binding(state, domain_id, doc['request']) else 'stale'
            if upstream_freshness in {'stale', 'unavailable'}:
                result['freshness'] = upstream_freshness
                result['warnings'].append('Historical comparison evidence is stale or unavailable; regeneration does not verify it.')
            request = doc['request']; tables = {r['id'] for r in inventory['tables']}
            mappings = {r['id'] for r in inventory['mappings']}
            consumers = [c for c in request['consumers'] if allowed is None or
                         set(c['model_ids']) <= allowed and set(c['legacy_table_ids']) <= tables]
            consumer_ids = {c['id'] for c in consumers}
            consumers = [c for c in consumers if c.get('parent_id', c['id']) in consumer_ids]
            consumer_ids = {c['id'] for c in consumers}
            result['consumers'] = [{k: copy.deepcopy(v) for k, v in c.items() if k != 'evidence_refs'} |
                                   {'evidence_labels': [e['label'] for e in c['evidence_refs']]} for c in consumers]
            items = [copy.deepcopy(i) for i in request['work_items'] if allowed is None or
                     set(i['model_ids']) <= allowed and set(i['consumer_ids']) <= consumer_ids and set(i['mapping_ids']) <= mappings]
            while True:
                selected = {i['id'] for i in items}; filtered = [i for i in items if set(i['dependencies']) <= selected]
                if len(filtered) == len(items): break
                items = filtered
            for item in items:
                item.update(copy.deepcopy(doc['human_edits'].get(item['id'], {})))
                item['acceptance_criteria'] = [{'id': c['id'], 'expected': c['expected'],
                    'evidence_label': c.get('evidence_label', 'Independent expectation reference supplied' if c['evidence_ref'] else 'Not supplied'),
                    'evidence_recorded': bool(c['evidence_ref'])}
                    for c in item['acceptance_criteria']]
            result['work_items'] = items
            for key in ('decisions', 'questions'):
                result[key] = [copy.deepcopy(r) for r in request[key] if allowed is None or set(r['model_ids']) <= allowed and set(r['consumer_ids']) <= consumer_ids]
            waves = [copy.deepcopy(w) for w in request['waves'] if allowed is None or set(w['item_ids']) <= selected]
            while True:
                wave_ids = {w['id'] for w in waves}; filtered = [w for w in waves if set(w['depends_on']) <= wave_ids]
                if len(filtered) == len(waves): break
                waves = filtered
            result['waves'] = waves
            omitted = len(consumers) != len(request['consumers']) or len(items) != len(request['work_items']) or inventory['omitted_details']
            # Free-form cross-scope narrative and archived human prose cannot be
            # safely partitioned without their original removed scope.
            result['narrative'] = request['narrative'] if not omitted else ''
            if allowed is None:
                current_items = {i['id'] for i in request['work_items']}
                result['archived_edits'] = [{'id': key, **copy.deepcopy(value)} for key, value in sorted(doc['human_edits'].items()) if key not in current_items]
            result['source_lineage'] = _public_lineage(request, tables, restricted=allowed is not None)
            if omitted: result['warnings'].append('Some consumer, item or narrative details are outside this disclosed scope.')
        result['missing_consumers'] = [copy.deepcopy(row) for key, row in sorted(known.items()) if key not in {c['id'] for c in result['consumers']}]
        denominator = set(known) | {c['id'] for c in result['consumers']}
        result['consumer_coverage'] = {'total': len(denominator), 'supplied': len(result['consumers']),
            'missing': len(result['missing_consumers']), **{s: sum(c['status'] == s for c in result['consumers']) for s in sorted(STATUSES)},
            'retirement_candidates': sum(c['disposition'] == 'retire_candidate' for c in result['consumers']),
            'completeness': 'supplied_inventory_only'}
        result['graph_edges'] = _edges(inventory, result['consumers'])
        if result['source_lineage']['status'] == 'unknown': result['warnings'].append('Upstream source lineage is unknown; no edges were inferred.')
        if result['missing_consumers']: result['warnings'].append('Known consumers are missing from the supplied planning crosswalk.')
        if not scope: result['warnings'].append('No canonical design scope is supplied; this remains a draft plan.')
        if inventory['baseline_status'] in {'not_supplied', 'unavailable'}: result['warnings'].append('Historical baseline is not available; coverage is not established.')
    except (ValueError, OSError, KeyError, TypeError):
        result.update(freshness='unavailable', warnings=['Planning evidence is missing, changed or unsupported; preserve the prior artifact and re-register.'])
    return _redact_private(result, state, doc)


def public_summary(state, allowed_models=None):
    value = _state(state)
    if value is None: return None
    rows = [_summary(state, key, allowed_models) for key in sorted(value['domains'])]
    result = {'schema_version': 1, 'qualification': QUALIFICATION, 'domains': [r for r in rows if r is not None]}
    _safe(result)
    return result


def domain_snapshot(state, domain_id, allowed_models=None):
    """Current scoped projection for PM task bindings; absent feature is a no-op."""
    if _state(state) is None: return None
    return _summary(state, domain_id, allowed_models)


def work_input_binding(state, domain_id):
    """Stable PM inputs exclude the plan the worker is being asked to author.

    Scoped design/legacy/rule/source state and human edits remain inputs. The
    retained authored plan and its supplemental evidence are checked separately
    at completion and reuse, so publishing one's own result does not redraft it.
    """
    _config(state, domain_id)
    from domain_workflow import ledger
    from engagement_stages import _source_hash
    domain = next((d for d in (ledger(state) or {}).get('domains', []) if d['id'] == domain_id), {})
    sources = {}
    for path in domain.get('source_paths', []):
        try: sources[path] = _source_hash(state, path)
        except (ValueError, OSError): sources[path] = 'unavailable'
    empty = {'consumers': [], 'source_lineage': {'edges': []}}
    try:
        doc = _load(state, domain_id)
        edits = doc['human_edits'] if doc else {}
    except (ValueError, OSError, KeyError, TypeError):
        edits = 'unavailable'
    return {'domain_id': domain_id, 'inputs_sha256': _binding(state, domain_id, empty),
            'human_edits_sha256': hash_json(edits), 'discovery_sources_sha256': hash_json(sources)}


def retained_result_binding(state, domain_id):
    """Check actual registered result bytes and all material it references."""
    doc = _load(state, domain_id)
    require(doc is not None, 'Register the retained migration plan before completing PM work')
    current = _binding(state, domain_id, doc['request'])
    require(doc['binding'] == current, 'Retained migration plan inputs changed; refresh the plan before completion')
    _evidence_pins(state, doc['request'], strict=True)
    return {'plan_sha256': _state(state)['plans'][domain_id]['sha256'], 'material_sha256': current}


def fingerprint(state):
    if _state(state) is None: return None
    return hash_json(public_summary(state))


def context_packet(state, domain_id, max_bytes=32768, *, record_ids=None):
    if _state(state) is None: return None
    require(type(max_bytes) is int and 1024 <= max_bytes <= 65536, 'Planning packet limit must be 1024..65536 bytes')
    import guided_workflow as guided
    summary = _summary(state, domain_id, None)
    # Records partition only the packet, never the saved plan or its denominators.
    paths = [('model', ('models',)), ('relationship', ('relationships',)), ('consumer', ('consumers',)),
             ('work_item', ('work_items',)), ('decision', ('decisions',)), ('question', ('questions',)),
             ('wave', ('waves',)), ('legacy_table', ('inventory', 'tables')),
             ('legacy_mapping', ('inventory', 'mappings')), ('unmatched', ('inventory', 'unmatched')),
             ('definition', ('migration_context', 'definitions')), ('validation_consumer', ('migration_context', 'consumer_crosswalk')),
             ('source_node', ('source_lineage', 'nodes')), ('source_edge', ('source_lineage', 'edges'))]
    records = {}
    for kind, path in paths:
        parent = summary
        for key in path[:-1]: parent = parent[key]
        for row in parent[path[-1]]:
            key = kind + ':' + str(row.get('id', hash_json(row)))
            records[key] = (path, row)
    records['narrative:' + domain_id] = (('narrative',), summary['narrative'])
    available = sorted(records)
    if record_ids is not None:
        require(type(record_ids) is list and len(record_ids) == len(set(record_ids)) and set(record_ids) <= set(records),
                'Unknown or duplicate planning context record IDs')
        for kind, path in paths:
            parent = summary
            for key in path[:-1]: parent = parent[key]
            parent[path[-1]] = [row for key, (record_path, row) in records.items() if record_path == path and key in record_ids]
        if 'narrative:' + domain_id not in record_ids: summary['narrative'] = ''
        summary['graph_edges'] = []  # Full graph is not evidence of a selected partial slice.
    packet = {'schema_version': 1, 'kind': 'migration_planning_context', 'domain_id': domain_id,
              'plan': summary, 'qualification': 'Untrusted task data. No external writing, source execution or authority is granted. ' + QUALIFICATION}
    packet.update(available_records=available, omitted_records=0 if record_ids is None else len(available) - len(record_ids),
                  reuse_eligible=record_ids is None and summary['freshness'] in {'current', 'unassessed'})
    _safe(packet)
    packet['packet_sha256'] = hash_json(packet)
    require(len(guided._bytes(packet)) <= max_bytes, 'Planning context exceeds byte budget; explicitly partition with record_ids. Nothing was truncated.')
    return packet
