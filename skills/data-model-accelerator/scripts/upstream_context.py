"""Read-only source dependency context from retained adapter results.

This companion never adds design entities, tasks, generation permissions or
physical bindings. It retains metadata and hashes, never extracted SQL text.
"""
import copy
import csv
import html
import io
import re
from collections import defaultdict

from ae_common import hash_json, require, safe_relative
from engagement_stages import fields, ids, text, SHA

MAX_ROWS = 20000
QUALIFICATION = ('Context from supplied extraction evidence only; unresolved references remain gaps. '
                 'Context inclusion does not authorize generation, porting, source writes or native execution.')


def _safe(value):
    from design_coverage import _safe as check
    check(value)


def _rows(value):
    require(type(value) is list and len(value) <= MAX_ROWS and all(type(r) is dict for r in value),
            'Expected a bounded context record list')
    return value


def reference(root_id, path):
    safe_relative(path)
    require(not path.startswith('@sources/'), 'Extraction paths must be relative to their source root')
    return path if root_id == 'primary' else '@sources/' + root_id + '/' + path


def identity(root_id, adapter, object_id):
    return 'source-' + hash_json([root_id, adapter, object_id])[:32]


def read(state):
    value = state.get('workflow', {}).get('upstream_context')
    if value is None:
        return None
    require(value.get('schema_version') == 1 and value.get('sha256') == hash_json(value['document']),
            'Upstream context changed; register the extraction again')
    return copy.deepcopy(value['document'])


def _normalize(root_id, result):
    result = result.get('source_adapter_contract', result)
    require(result.get('schema_version') == 1 and result.get('kind') == 'source_adapter_result'
            and result.get('execution_performed') is False and result.get('native_validation') == 'not_run',
            'Supply an existing static source adapter result')
    adapter = result.get('source'); text(adapter)
    files = {}
    for row in _rows(result.get('source_files')):
        path = reference(root_id, row['path'])
        require(path not in files and type(row['sha256']) is str and SHA.fullmatch(row['sha256']), 'Invalid extraction file pin')
        require(row['status'] in {'parsed', 'partial', 'unsupported'}, 'Invalid extraction coverage')
        files[path] = {'sha256': row['sha256'], 'status': row['status']}

    def evidence(row):
        value = row['evidence']; path = reference(root_id, value['path']); text(value['locator'])
        require(path in files and value['sha256'] == files[path]['sha256'], 'Extraction evidence differs from its file inventory')
        return {'reference': path, 'sha256': value['sha256'], 'locator': value['locator']}

    objects = {o['id']: o for o in _rows(result.get('objects'))}
    require(len(objects) == len(result['objects']), 'Duplicate extraction object')
    aliases = {key: key for key in objects}
    # Only the adapter's exact authored-byte binding aliases SQL to a manifest
    # object. Names, filenames and package similarities never create this link.
    for key, obj in objects.items():
        binding = obj.get('details', {}).get('manifest_binding') or {}
        owner = binding.get('manifest_object_id')
        if (owner in objects and binding.get('binding') == 'package_original_path_exact_raw_code'
                and binding.get('sha256') == obj['evidence']['sha256']
                and binding.get('native_id') == objects[owner].get('native_id')):
            aliases[key] = owner
    nodes = {}
    for key, obj in objects.items():
        native = obj.get('native_id')
        require(native is None or type(native) is str, 'Invalid native identity')
        owner = objects[aliases[key]]; oid = identity(root_id, adapter, aliases[key])
        entry = nodes.setdefault(oid, {'id': oid, 'root_id': root_id, 'adapter': adapter,
            'extraction_object_id': aliases[key], 'native_id': owner.get('native_id'),
            'kind': owner['kind'], 'name': owner['name'], 'evidence': [],
            'disabled': owner.get('details', {}).get('disabled') is True})
        pin = evidence(obj)
        if pin not in entry['evidence']: entry['evidence'].append(pin)
    edges = []
    for row in _rows(result.get('dependencies')):
        require(row['source_id'] in objects, 'Dependency owner is missing')
        target = row.get('details', {}).get('target_object_id')
        resolved = target in objects and not objects[target].get('details', {}).get('disabled')
        edges.append({'source_id': identity(root_id, adapter, aliases[row['source_id']]),
            'target_id': identity(root_id, adapter, aliases[target]) if resolved else None,
            'reference': row['target'], 'evidence': [evidence(row)],
            'basis': row.get('details', {}).get('resolution', 'unresolved')})
    gaps = [{'code': row['code'], 'evidence': evidence(row)} for row in _rows(result.get('gaps'))]
    return {'root_id': root_id, 'adapter': adapter, 'result_sha256': hash_json(result),
            'files': files, 'nodes': list(nodes.values()), 'edges': edges, 'gaps': gaps}


def register(state, request, run_dir=None):
    """Normalize already-produced extraction results; no source scan or parser run."""
    fields(request, {'schema_version', 'extracts'}, {'bindings', 'links'})
    require(request['schema_version'] == 1 and type(state.get('workflow')) is dict, 'Unsupported context request')
    from source_roots import _rows as roots
    known = {r['id'] for r in roots(state)}
    previous = read(state) or {'extracts': {}, 'bindings': {}, 'links': []}
    value = copy.deepcopy(previous)
    seen = set()
    for row in _rows(request['extracts']):
        fields(row, {'id', 'root_id', 'result'}); text(row['id'])
        require(row['id'] not in seen and row['root_id'] in known, 'Duplicate extraction or unknown registered root')
        seen.add(row['id'])
        normalized = _normalize(row['root_id'], row['result'])
        old = value['extracts'].get(row['id'])
        require(not old or (old['root_id'], old['adapter']) == (normalized['root_id'], normalized['adapter']),
                'Extraction IDs cannot be reassigned to a different source')
        value['extracts'][row['id']] = normalized
    for row in _rows(request.get('bindings', [])):
        fields(row, {'entity_id', 'root_id', 'native_ids'}); text(row['entity_id'])
        require(row['root_id'] in known, 'Unknown binding root'); ids(row['native_ids'], nonempty=True)
        key = row['entity_id'] + ':' + row['root_id']
        value['bindings'][key] = copy.deepcopy(row)
    for row in _rows(request.get('links', [])):
        fields(row, {'source', 'target', 'evidence_refs'})
        for end in ('source', 'target'):
            fields(row[end], {'root_id', 'native_id'}); text(row[end]['native_id'])
            require(row[end]['root_id'] in known, 'Unknown cross-source root')
        require(row['source'] != row['target'], 'Self link is not a cross-source dependency')
        _rows(row['evidence_refs']); require(row['evidence_refs'], 'Cross-source link needs pinned evidence')
        for pin in row['evidence_refs']:
            fields(pin, {'reference', 'sha256'}); safe_relative(pin['reference'])
            require(type(pin['sha256']) is str and SHA.fullmatch(pin['sha256']), 'Invalid link evidence hash')
        if row not in value['links']: value['links'].append(copy.deepcopy(row))
    _safe(value)
    # Reject inconsistent partitions before mutating durable state.
    graph(value)
    state['workflow']['upstream_context'] = {'schema_version': 1, 'document': value, 'sha256': hash_json(value)}
    return derive(state)


def graph(document):
    nodes, files, edges, gaps = {}, {}, [], []
    for extract_id, item in document['extracts'].items():
        for path, pin in item['files'].items():
            require(path not in files or files[path]['sha256'] == pin['sha256'],
                    'Extraction partitions disagree on current file bytes; replace the stale partition')
            files[path] = pin
        for row in item['nodes']:
            old = nodes.get(row['id'])
            require(not old or old == row, 'Extraction partitions disagree on object evidence')
            nodes[row['id']] = row
        edges.extend(item['edges']); gaps.extend(item['gaps'])
    require(len(nodes) <= MAX_ROWS and len(files) <= MAX_ROWS and len(edges) <= MAX_ROWS * 4, 'Context inventory exceeds its bound')
    natives = defaultdict(list)
    for row in nodes.values():
        if row['native_id'] is not None and not row['disabled']:
            natives[(row['root_id'], row['native_id'])].append(row['id'])
    for link in document['links']:
        source = natives[(link['source']['root_id'], link['source']['native_id'])]
        target = natives[(link['target']['root_id'], link['target']['native_id'])]
        valid_pins = all(files.get(p['reference'], {}).get('sha256') == p['sha256'] for p in link['evidence_refs'])
        if len(source) == 1:
            edges.append({'source_id': source[0], 'target_id': target[0] if len(target) == 1 and valid_pins else None,
                'reference': link['target']['root_id'] + ':' + link['target']['native_id'],
                'evidence': link['evidence_refs'], 'basis': 'host_declared_cross_source_link'})
        else:
            gaps.append({'code': 'cross_source_owner_unresolved', 'evidence': link['evidence_refs'][0]})
    return nodes, files, edges, gaps, natives


def derive(state, selected=None, domain_id=None):
    """Private metadata projection; generation IDs are echoed, never expanded."""
    doc = read(state)
    models = {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}
    domain = None
    if domain_id is not None:
        from domain_workflow import _domain, _models
        domain = _domain(state, domain_id)
        if selected is None: selected = sorted(_models(state, domain))
    selected = sorted(models) if selected is None else sorted(set(selected))
    ids(selected, models)
    result = {'schema_version': 1, 'status': 'unassessed', 'generation_entity_ids': selected,
              'seed_object_ids': [], 'nodes': [], 'edges': [], 'files': [], 'gaps': [], 'qualification': QUALIFICATION}
    if doc is None: return result
    nodes, files, edges, observed_gaps, natives = graph(doc)
    seeds, missing, explicit = set(), [], set()
    for binding in doc['bindings'].values():
        if binding['entity_id'] not in selected: continue
        explicit.add(binding['entity_id'])
        for native in binding['native_ids']:
            matches = natives[(binding['root_id'], native)]
            if len(matches) == 1: seeds.update(matches)
            else: missing.append({'code': 'seed_identity_unresolved', 'entity_id': binding['entity_id'],
                                  'root_id': binding['root_id'], 'native_id': native})
    selected_paths = {p for key in selected if key not in explicit for p in models[key].get('source_paths', [])}
    if domain and not selected: selected_paths.update(domain['source_paths'])
    # A manifest is a graph inventory, not evidence that every manifest object
    # belongs to a selected target. Require exact IDs for that ambiguous case.
    for path in selected_paths:
        matches = [n for n in nodes.values() if not n['disabled'] and any(e['reference'] == path for e in n['evidence'])]
        authored = [n for n in matches if n['kind'] == 'dbt_authored_file' or
                    any(e['reference'] == path and e['locator'] == '$file' for e in n['evidence'])]
        usable = authored or matches
        if len(usable) == 1: seeds.add(usable[0]['id'])
        else: missing.append({'code': 'source_path_selection_unresolved', 'reference': path})
    outgoing = defaultdict(list)
    for edge in edges: outgoing[edge['source_id']].append(edge)
    reached, pending, retained_edges = set(), list(seeds), []
    while pending:
        key = pending.pop()
        if key in reached: continue
        reached.add(key)
        for edge in outgoing[key]:
            retained_edges.append(copy.deepcopy(edge))
            if edge['target_id'] in nodes: pending.append(edge['target_id'])
            else: missing.append({'code': 'dependency_unresolved', 'object_id': key, 'reference': edge['reference']})
    parents = {key: {e['target_id'] for e in outgoing[key] if e['target_id'] in reached} for key in reached}
    children = defaultdict(set)
    for key, dependencies in parents.items():
        for parent in dependencies: children[parent].add(key)
    ready = [key for key in reached if not parents[key]]; visited = set()
    while ready:
        key = ready.pop(); visited.add(key)
        for child in children[key]:
            parents[child].discard(key)
            if not parents[child]: ready.append(child)
    if len(visited) != len(reached): missing.append({'code': 'dependency_cycle', 'object_ids': sorted(reached - visited)})
    refs = {e['reference'] for key in reached for e in nodes[key]['evidence']}
    refs.update(e['reference'] for edge in retained_edges for e in edge['evidence'])
    # Configuration affects selected resources but is supporting context only.
    roots = {nodes[key]['root_id'] for key in reached}
    for row in nodes.values():
        if row['root_id'] in roots and row['kind'] in {'dbt_project', 'dbt_package_configuration'}:
            refs.update(e['reference'] for e in row['evidence'])
    locations = defaultdict(list)
    for key in reached:
        for pin in nodes[key]['evidence']: locations[pin['reference']].append(pin['locator'])
    for gap in observed_gaps:
        pin = gap['evidence']; path = pin['reference']; loc = pin.get('locator', '$')
        if path not in refs: continue
        selected_locations = locations[path]
        # A shared manifest must not pull other domains' object-level gaps into
        # this scope merely because they occupy the same physical file.
        if (not selected_locations or loc == '$' or '$file' in selected_locations
                or any(loc == p or loc.startswith(p + '.') or loc.startswith(p + '[') for p in selected_locations)):
            missing.append(copy.deepcopy(gap))
    if selected and not seeds: missing.append({'code': 'selected_source_context_missing'})
    result.update(status='partial' if missing else 'recorded', seed_object_ids=sorted(seeds),
        nodes=[copy.deepcopy(nodes[k]) for k in sorted(reached)], edges=retained_edges,
        files=[{'reference': p, **files[p]} for p in sorted(refs) if p in files], gaps=missing)
    result['context_sha256'] = hash_json(result)
    return result


def verify_files(state, pins):
    """Hash only explicitly selected files. Never enumerate or parse a repository."""
    from source_roots import resolve
    from source_adapters.filesystem import read_assigned
    from source_roots import split_reference
    import hashlib
    result, total = {}, 0
    for pin in pins:
        path = pin['reference']
        if total >= 32 * 1024 * 1024:
            result[path] = 'unavailable'
            continue
        try:
            resolve(state, path)
            root, relative = split_reference(state, path)
            raw = read_assigned(root, relative); total += len(raw)
            require(total <= 32 * 1024 * 1024, 'Selected evidence exceeds 32 MiB; partition the context')
            result[path] = hashlib.sha256(raw).hexdigest()
        except (ValueError, OSError):
            result[path] = 'unavailable'
    return result


def packet(state, selected=None, domain_id=None, max_bytes=32768):
    require(type(max_bytes) is int and 1024 <= max_bytes <= 65536, 'Context packet limit must be 1024..65536 bytes')
    value = derive(state, selected, domain_id)
    from guided_workflow import _bytes
    require(len(_bytes(value)) <= max_bytes, 'Context packet exceeds its bound; select a smaller coherent entity slice')
    actual = verify_files(state, value['files'])
    changed = [p['reference'] for p in value['files'] if actual[p['reference']] != p['sha256']]
    require(not changed, 'Source context bytes changed or are unavailable; refresh extraction evidence')
    return {**value, 'freshness': 'selected_file_hashes_current', 'source_text_included': False}


def summarize(state, selected=None, domain_id=None):
    """Disclosure-safe counts only; raw references stay in the private context."""
    value = derive(state, selected, domain_id)
    return {'status': value['status'], 'generation_entity_ids': value['generation_entity_ids'],
            'context_sha256': value.get('context_sha256'),
            'counts': {key: len(value[key]) for key in ('seed_object_ids', 'nodes', 'edges', 'files', 'gaps')},
            'gap_codes': sorted({g['code'] for g in value['gaps']}), 'qualification': QUALIFICATION}


def _public_token(value):
    # Extraction metadata is not a disclosure grant. Only identifier-shaped
    # labels leave this companion; paths, expressions and freeform text do not.
    return value if type(value) is str and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.:$-]{0,255}', value) else None


def public_projection(state, selected=None, domain_id=None):
    """Complete source-only graph for delivery, without paths or source contents.

    Edges point upstream -> consumer. Entity roots associate source evidence with
    target IDs without making any source object an approved target entity.
    """
    value = derive(state, selected, domain_id)
    nodes = []
    for row in value['nodes']:
        root = _public_token(row['root_id']) or 'source'
        native = _public_token(row['native_id'])
        name = _public_token(row['name']) or native or row['id']
        nodes.append({'id': row['id'], 'root_id': root,
                      'adapter': _public_token(row['adapter']) or 'unknown',
                      'native_id': native, 'kind': _public_token(row['kind']) or 'source_object',
                      'name': name, 'source_qualified_name': root + '::' + (native or name)})
    known = {n['id'] for n in nodes}
    edges = []
    seen = set()
    for row in value['edges']:
        edge = {'upstream_id': row['target_id'], 'consumer_id': row['source_id'],
                'status': 'resolved' if row['target_id'] in known else 'unresolved',
                'basis': _public_token(row['basis']) or 'unresolved'}
        signature = tuple(edge.values())
        if signature not in seen: edges.append(edge); seen.add(signature)
    gaps = []
    for row in value['gaps']:
        gap = {'code': _public_token(row['code']) or 'context_gap'}
        affected = set(row.get('object_ids', [])) | ({row['object_id']} if row.get('object_id') else set())
        if affected & known: gap['object_ids'] = sorted(affected & known)
        if row.get('entity_id') in value['generation_entity_ids']: gap['entity_id'] = row['entity_id']
        if gap not in gaps: gaps.append(gap)
    associations = []
    for entity_id in value['generation_entity_ids']:
        one = value if len(value['generation_entity_ids']) == 1 else derive(state, [entity_id])
        associations.append({'entity_id': entity_id, 'root_object_ids': one['seed_object_ids'],
                             'context_object_ids': sorted(n['id'] for n in one['nodes'])})
    return {'schema_version': 1, 'kind': 'source_lineage_context', 'status': value['status'],
            'generation_entity_ids': value['generation_entity_ids'], 'seed_object_ids': value['seed_object_ids'],
            'nodes': nodes, 'edges': edges, 'gaps': gaps, 'entity_roots': associations,
            'context_sha256': value.get('context_sha256'), 'qualification': QUALIFICATION}


def render_svg(projection):
    """Top-down, self-contained graph. All known source nodes remain present."""
    require(projection.get('kind') == 'source_lineage_context', 'Expected a public source context projection')
    nodes = {n['id']: n for n in _rows(projection['nodes'])}
    edges = [e for e in projection['edges'] if e['upstream_id'] in nodes and e['consumer_id'] in nodes]
    parents = {key: set() for key in nodes}; children = defaultdict(set)
    for edge in edges:
        parents[edge['consumer_id']].add(edge['upstream_id'])
        children[edge['upstream_id']].add(edge['consumer_id'])
    ready = sorted(key for key in nodes if not parents[key]); levels = {key: 0 for key in ready}; visited = set()
    while ready:
        key = ready.pop(); visited.add(key)
        for child in sorted(children[key]):
            levels[child] = max(levels.get(child, 0), levels[key] + 1)
            parents[child].discard(key)
            if not parents[child]: ready.append(child)
    cycle_level = max(levels.values(), default=0) + 1
    for key in nodes.keys() - visited: levels[key] = cycle_level
    layers = defaultdict(list)
    for key in nodes: layers[levels[key]].append(key)
    positions = {}; cursor = 112; width = 1450; card_width = 330
    for level in sorted(layers):
        layer = sorted(layers[level], key=lambda key: (nodes[key]['source_qualified_name'], key))
        for index, key in enumerate(layer): positions[key] = (24 + (index % 4) * 354, cursor + (index // 4) * 108)
        cursor += ((len(layer) + 3) // 4) * 108 + 36
    height = max(230, cursor + 70)
    esc = lambda text: html.escape(str(text), quote=True)
    output = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Source upstream context">',
              '<title>Source upstream context — supplied extraction evidence</title>',
              '<defs><marker id="source-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#64748b"/></marker></defs>',
              f'<rect width="{width}" height="{height}" fill="#f8fafc"/>',
              '<text x="24" y="32" font-family="sans-serif" font-size="22" fill="#0f172a">Source upstream context</text>',
              f'<text x="24" y="58" font-family="sans-serif" font-size="13" fill="#475569">{len(nodes)} known objects · {len(edges)} known dependencies · {len(projection["gaps"])} gap types</text>',
              '<text x="24" y="82" font-family="sans-serif" font-size="12" fill="#475569">Source evidence only. Target generation scope is unchanged.</text>']
    for edge in edges:
        x1, y1 = positions[edge['upstream_id']]; x2, y2 = positions[edge['consumer_id']]
        x1 += card_width / 2; x2 += card_width / 2; y1 += 82; middle = (y1 + y2) / 2
        output.append(f'<path data-upstream-id="{esc(edge["upstream_id"])}" data-consumer-id="{esc(edge["consumer_id"])}" d="M{x1},{y1} C{x1},{middle} {x2},{middle} {x2},{y2}" fill="none" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#source-arrow)"/>')
    for key, row in nodes.items():
        x, y = positions[key]; label = row['source_qualified_name']
        short = lambda val: val if len(val) <= 31 else val[:28] + '…'
        output.extend([f'<g data-source-node-id="{esc(key)}"><title>{esc(label)} ({esc(row["kind"])})</title>',
                       f'<rect x="{x}" y="{y}" width="{card_width}" height="82" rx="7" fill="#ffffff" stroke="#94a3b8"/>',
                       f'<text x="{x + 12}" y="{y + 23}" font-family="sans-serif" font-size="16" fill="#475569">{esc(short(row["root_id"]))}</text>',
                       f'<text x="{x + 12}" y="{y + 45}" font-family="sans-serif" font-size="18" fill="#0f172a">{esc(short(row["native_id"] or row["name"]))}</text>',
                       f'<text x="{x + 12}" y="{y + 65}" font-family="sans-serif" font-size="15" fill="#475569">{esc(short(row["kind"]))}</text></g>'])
    if not nodes:
        output.append('<text x="24" y="130" font-family="sans-serif" font-size="14" fill="#475569">No resolved source objects in the supplied selected evidence.</text>')
    if projection['gaps']:
        output.append(f'<text x="24" y="{height - 30}" font-family="sans-serif" font-size="12" fill="#92400e">Unresolved context remains. See the companion CSV for every gap code.</text>')
    output.append('</svg>')
    return '\n'.join(output)


def csv_export(state, selected=None, domain_id=None):
    """Complete scoped public nodes, edges and gaps; never truncate lineage."""
    value = public_projection(state, selected, domain_id)
    out = io.StringIO()
    columns = ['record_type', 'object_id', 'root_id', 'native_id', 'name', 'kind', 'upstream_id',
               'consumer_id', 'entity_ids', 'root_entity_ids', 'gap_code', 'status']
    writer = csv.DictWriter(out, fieldnames=columns); writer.writeheader()
    def write(row):
        clean = {key: ("'" + val if type(val) is str and val.lstrip().startswith(('=', '+', '-', '@')) else val)
                 for key, val in row.items()}
        writer.writerow(clean)
    for row in value['nodes']:
        write({'record_type': 'object', 'object_id': row['id'], 'root_id': row['root_id'], 'native_id': row['native_id'],
               'name': row['name'], 'kind': row['kind'], 'status': 'known_from_supplied_evidence',
               'entity_ids': '; '.join(a['entity_id'] for a in value['entity_roots'] if row['id'] in a['context_object_ids']),
               'root_entity_ids': '; '.join(a['entity_id'] for a in value['entity_roots'] if row['id'] in a['root_object_ids'])})
    for row in value['edges']:
        write({'record_type': 'dependency', 'upstream_id': row['upstream_id'], 'consumer_id': row['consumer_id'], 'status': row['status']})
    for row in value['gaps']:
        write({'record_type': 'gap', 'gap_code': row['code'], 'object_id': '; '.join(row.get('object_ids', [])),
               'entity_ids': row.get('entity_id'), 'status': 'unresolved'})
    return out.getvalue()


def scope_bindings(state):
    if read(state) is None: return {}
    models = (state.get('workflow', {}).get('design') or {}).get('entities', [])
    result, contexts, pins = {}, {}, {}
    for model in models:
        value = derive(state, [model['id']])
        if value['nodes'] or value['gaps']:
            contexts[model['id']] = value
            pins.update({p['reference']: p for p in value['files']})
    actual = verify_files(state, list(pins.values()))
    for key, value in contexts.items():
        result[key] = hash_json({'context': value, 'current_files': {p['reference']: actual[p['reference']] for p in value['files']}})
    return result
