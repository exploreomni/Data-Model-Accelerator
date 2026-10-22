"""Readable, deterministic upstream pipelines; no execution or approval claims.

``pipeline_views`` returns portable diagram records, one per concrete gold output,
then supplemental views covering everything else. Only recorded lineage and
``depends_on`` form warehouse pipelines. Joins are retained separately.

Optional semantic input is explicitly bound, never matched by names::

    {"views": [{"id": "orders", "name": "Orders", "warehouse_model_ids": ["gold.orders"]}],
     "topics": [{"id": "sales", "name": "Sales", "view_ids": ["orders"]}]}

Callers must supply their permitted inventory. An outside semantic binding fails
validation. A named missing warehouse endpoint becomes a reference-only block,
with ``data-reference-id`` rather than a certified canonical model identity.
"""
from collections import defaultdict, deque
import base64
import copy
import hashlib
import html
import json
import re
import textwrap

CARD_WIDTH = 300
CARD_GAP = 48
ROW_GAP = 66
TRACK_GAP = 12
QUALIFICATION = ('Recorded dependency structure only. Joins remain in the detailed ERD; '
                 'native validity, execution order and acceptance are not established.')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _identifier(value):
    _require(isinstance(value, str) and value and value == value.strip()
             and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid pipeline identity')
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()[:20]


def _wrap(value, width=24):
    # Every character in a full model name remains available in the title and
    # data-full-name. Visible text wraps rather than ellipsizing the name.
    value = re.sub(r'\s+', ' ', str(value))
    return textwrap.wrap(value, width, break_long_words=True, break_on_hyphens=False) or ['']


def _card_lines(node):
    lines = [(part, 'name') for part in _wrap(node.get('name') or node['id'])]
    if node.get('semantic_kind'):
        note = 'Semantic view · supplied binding' if node['semantic_kind'] == 'view' else 'Topic · supplied membership'
    elif node.get('reference_only'):
        note = 'Reference only · definition missing'
    elif node.get('object_kind') == 'interface':
        note = 'External interface · implementation unresolved'
    elif node.get('object_kind') == 'source' or node['layer'] == 'bronze':
        note = 'Raw / source object'
    else:
        note = 'Gold model' if node['layer'] == 'gold' else 'Transformation model'
    lines.extend((part, 'note') for part in _wrap(note, 30))
    if node.get('semantic_kind') or node.get('reference_only'):
        return lines
    disposition = {'create': 'New proposal', 'reuse': 'Reused · declared', 'extend': 'Extend existing',
                   'replace': 'Replacement proposal'}.get(node.get('disposition'), 'Disposition not supplied')
    lines.append((disposition, 'badge'))
    columns = node.get('columns', [])
    declared = node.get('keys', [])
    keys = [(str(column.get('key') or 'Declared key'), column['name'], False)
            for column in columns if column.get('key') or column['name'] in declared]
    keys.extend(('Declared key', key, True) for key in declared if not any(c['name'] == key for c in columns))
    if not keys:
        lines.append(('Keys not supplied', 'key'))
    else:
        for role, name, unknown in keys[:3]:
            label = role + ': ' + name + (' · type unverified' if unknown else '')
            lines.extend((part, 'key') for part in _wrap(label, 30))
        if len(keys) > 3:
            lines.append((str(len(keys) - 3) + ' more keys in dictionary', 'note'))
    return lines


def _normalize(models, relationships, semantic=None):
    from portal_checks import model_inventory
    model_inventory(models, references=True)
    _require(isinstance(relationships, list) and len(relationships) <= 20000, 'Pipeline relationships must be a bounded list')
    nodes = {model['id']: dict(copy.deepcopy(model), identity_kind='model') for model in models}
    supplied_ids = set(nodes)
    occurrences = []
    for edge in relationships:
        _require(isinstance(edge, dict) and edge.get('kind') in {'lineage', 'relationship'}, 'Unknown pipeline relationship kind')
        _identifier(edge.get('from')); _identifier(edge.get('to'))
        occurrence = copy.deepcopy(edge)
        occurrence.setdefault('evidence_origin', 'relationship_record')
        occurrences.append(occurrence)
    for model in models:
        parents = model.get('depends_on', [])
        _require(isinstance(parents, list) and len(occurrences) + len(parents) <= 40000, 'Recorded model dependencies exceed the bounded pipeline inventory')
        _require(isinstance(model.get('keys', []), list) and all(isinstance(key, str) and key for key in model.get('keys', [])), 'Model keys must be text names')
        for parent in parents:
            _identifier(parent)
            occurrences.append({'from': parent, 'to': model['id'], 'kind': 'lineage',
                                'label': 'Recorded model dependency', 'evidence_origin': 'depends_on'})
    # An endpoint identity is explicit evidence of a reference, never a definition.
    # Missing join-only endpoints remain in the join inventory, not lineage closure.
    for edge in occurrences:
        for identifier in (edge['from'], edge['to']):
            if identifier not in nodes:
                nodes[identifier] = {'id': identifier, 'name': identifier, 'layer': 'reference',
                    'identity_kind': 'reference', 'reference_only': True, 'object_kind': 'reference'}
    semantic_ids = set()
    if semantic is not None:
        _require(isinstance(semantic, dict) and set(semantic) <= {'views', 'topics'}, 'Unsupported semantic pipeline fields')
        views, topics = semantic.get('views', []), semantic.get('topics', [])
        _require(isinstance(views, list) and isinstance(topics, list) and len(views) + len(topics) <= 20000, 'Semantic pipeline collections must be bounded lists')
        known_views = set()
        for kind, rows, binding in (('view', views, 'warehouse_model_ids'), ('topic', topics, 'view_ids')):
            seen = set()
            for row in rows:
                _require(isinstance(row, dict) and set(row) == {'id', 'name', binding}, 'Semantic pipelines need explicit names and bindings')
                identifier = _identifier(row['id'])
                _require(identifier not in seen, 'Duplicate semantic pipeline identity'); seen.add(identifier)
                _require(isinstance(row['name'], str) and row['name'].strip(), 'Semantic pipeline name is required')
                links = row[binding]
                _require(isinstance(links, list) and links and all(isinstance(link, str) for link in links)
                         and len(set(links)) == len(links), 'Semantic bindings must be a nonempty list of unique identities')
                _require(set(links) <= (supplied_ids if kind == 'view' else known_views), 'Semantic binding is outside the permitted inventory')
                internal = '@semantic/' + kind + '/' + identifier
                _require(internal not in nodes, 'Semantic identity collides with a warehouse model')
                nodes[internal] = {'id': internal, 'name': row['name'], 'layer': 'semantic',
                    'identity_kind': 'semantic', 'semantic_kind': kind, 'semantic_id': identifier,
                    binding: sorted(links)}
                semantic_ids.add(internal)
                _require(len(occurrences) + len(links) <= 60000, 'Semantic bindings exceed the bounded pipeline inventory')
                for link in links:
                    occurrences.append({'from': link if kind == 'view' else '@semantic/view/' + link,
                        'to': internal, 'kind': 'semantic_binding' if kind == 'view' else 'topic_membership',
                        'evidence_origin': 'explicit_semantic_binding'})
            if kind == 'view': known_views = seen
    grouped = defaultdict(list)
    for occurrence in occurrences:
        grouped[(occurrence['kind'], occurrence['from'], occurrence['to'])].append(occurrence)
    edges = []
    for (kind, source, target), records in sorted(grouped.items()):
        # Render a shared path, preserving every supplied occurrence and its source.
        records.sort(key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False))
        counters = defaultdict(int)
        for record in records:
            signature = _digest(record); counters[signature] += 1
            record['pipeline_occurrence_id'] = record.get('occurrence_id') or 'occurrence-' + signature + '-' + str(counters[signature])
        edges.append({'id': 'edge-' + _digest([kind, source, target]), 'from': source, 'to': target,
                      'kind': kind, 'occurrences': records, 'occurrence_count': len(records)})
    return {'nodes': nodes, 'edges': edges, 'supplied_ids': supplied_ids, 'semantic_ids': semantic_ids}


def _ancestors(identifiers, edges):
    upstream = defaultdict(set)
    for edge in edges:
        if edge['kind'] == 'lineage': upstream[edge['to']].add(edge['from'])
    found, todo = set(identifiers), list(identifiers)
    while todo:
        for parent in sorted(upstream[todo.pop()]):
            if parent not in found:
                found.add(parent); todo.append(parent)
    return found


def _components(identifiers, edges):
    """Iterative Kosaraju, so long pipelines do not depend on recursion depth."""
    adjacency = {identifier: set() for identifier in identifiers}
    reverse = {identifier: set() for identifier in identifiers}
    for edge in edges:
        adjacency[edge['from']].add(edge['to']); reverse[edge['to']].add(edge['from'])
    seen, finished = set(), []
    for start in sorted(identifiers):
        if start in seen: continue
        seen.add(start); stack = [(start, iter(sorted(adjacency[start])))]
        while stack:
            current, children = stack[-1]
            child = next(children, None)
            if child is None:
                finished.append(current); stack.pop()
            elif child not in seen:
                seen.add(child); stack.append((child, iter(sorted(adjacency[child]))))
    component_of, components = {}, []
    for start in reversed(finished):
        if start in component_of: continue
        index = len(components); component_of[start] = index; todo = [start]; component = []
        while todo:
            current = todo.pop(); component.append(current)
            for parent in sorted(reverse[current]):
                if parent not in component_of:
                    component_of[parent] = index; todo.append(parent)
        components.append(sorted(component))
    return components, component_of


def _rank(nodes, edges):
    components, component_of = _components(nodes, edges)
    parents, children = defaultdict(set), defaultdict(set)
    self_loops = {e['from'] for e in edges if e['from'] == e['to']}
    for edge in edges:
        a, b = component_of[edge['from']], component_of[edge['to']]
        if a != b: parents[b].add(a); children[a].add(b)
    base = lambda n: 4 if n.get('semantic_kind') == 'view' else 5 if n.get('semantic_kind') == 'topic' else {'bronze': 0, 'reference': 0, 'silver': 1, 'gold': 3}[n['layer']]
    ranks = {i: max(base(nodes[identifier]) for identifier in group) for i, group in enumerate(components)}
    waiting = {i: len(parents[i]) for i in range(len(components))}
    todo = deque(sorted(i for i, count in waiting.items() if not count))
    while todo:
        index = todo.popleft()
        for child in sorted(children[index]):
            ranks[child] = max(ranks[child], ranks[index] + 1); waiting[child] -= 1
            if waiting[child] == 0: todo.append(child)
    compact = {rank: i for i, rank in enumerate(sorted(set(ranks.values())))}
    node_rank = {identifier: compact[ranks[component_of[identifier]]] for identifier in nodes}
    cycles = [group for group in components if len(group) > 1 or any(identifier in self_loops for identifier in group)]
    return node_rank, sorted(cycles), component_of


def _layout(graph, selected, target_model_id=None, label=None):
    nodes = {identifier: graph['nodes'][identifier] for identifier in sorted(selected)}
    edges = [edge for edge in graph['edges'] if edge['kind'] != 'relationship' and edge['from'] in nodes and edge['to'] in nodes]
    joins = [edge for edge in graph['edges'] if edge['kind'] == 'relationship' and (edge['from'] in nodes or edge['to'] in nodes)]
    external = [edge for edge in graph['edges'] if edge['kind'] != 'relationship' and ((edge['from'] in nodes) != (edge['to'] in nodes))]
    if not nodes:
        return {'nodes': [], 'edges': [], 'join_relationships': [], 'external_connections': [], 'rows': [], 'cycles': [],
                'width': 1100, 'height': 170, 'target_model_id': target_model_id, 'label': label or 'No pipeline models supplied'}
    node_rank, cycles, component_of = _rank(nodes, edges)
    ranks = sorted(set(node_rank.values()))
    grouped = {rank: sorted(identifier for identifier in nodes if node_rank[identifier] == rank) for rank in ranks}
    # Deterministic barycentric order reduces crossings without changing levels.
    parents = defaultdict(list)
    for edge in edges:
        if node_rank[edge['from']] < node_rank[edge['to']]: parents[edge['to']].append(edge['from'])
    order = {}
    for rank in ranks:
        grouped[rank].sort(key=lambda identifier: (sum(order[p] for p in parents[identifier]) / len(parents[identifier]) if parents[identifier] else float('inf'), identifier))
        for index, identifier in enumerate(grouped[rank]): order[identifier] = index
    lines = {identifier: _card_lines(node) for identifier, node in nodes.items()}
    heights = {identifier: 32 + sum(25 if kind == 'name' else 20 for _, kind in rows) for identifier, rows in lines.items()}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    tracks = defaultdict(list); outer = []
    for edge in edges:
        a, b = node_rank[edge['from']], node_rank[edge['to']]
        outgoing[edge['from']].append(edge['id']); incoming[edge['to']].append(edge['id'])
        tracks[a + 1].append((edge['id'], 'departure'))
        if b != a + 1:
            tracks[b].append((edge['id'], 'arrival')); outer.append(edge['id'])
    # Every horizontal segment has a dedicated lane. Long/cyclic connections use
    # reserved outer channels, never vertical routes through intervening cards.
    left = outer[::2]; right = outer[1::2]
    gutter_left = 160 + len(left) * TRACK_GAP
    maximum = max(len(group) for group in grouped.values())
    grid_width = maximum * CARD_WIDTH + (maximum - 1) * CARD_GAP
    row_y, track_y = {}, {}
    cursor = 110
    for gap in range(len(ranks) + 1):
        entries = sorted(tracks[gap])
        for index, entry in enumerate(entries): track_y[(gap, *entry)] = cursor + 24 + index * TRACK_GAP
        cursor += ROW_GAP + max(0, len(entries) - 1) * TRACK_GAP
        if gap < len(ranks):
            row_y[gap] = cursor
            cursor += max(heights[identifier] for identifier in grouped[gap])
    positions = {}
    for rank, group in grouped.items():
        width = len(group) * CARD_WIDTH + (len(group) - 1) * CARD_GAP
        for index, identifier in enumerate(group):
            positions[identifier] = {'x': gutter_left + (grid_width - width) / 2 + index * (CARD_WIDTH + CARD_GAP),
                                     'y': row_y[rank], 'width': CARD_WIDTH, 'height': heights[identifier]}
    ports, used_ports = {}, defaultdict(dict)
    for edge in edges:
        for direction, identifier in (('from', edge['from']), ('to', edge['to'])):
            box = positions[identifier]; items = outgoing[identifier] if direction == 'from' else incoming[identifier]
            gap = node_rank[identifier] + (1 if direction == 'from' else 0)
            lower, upper = round((box['x'] + 24) * 1000), round((box['x'] + CARD_WIDTH - 24) * 1000)
            desired = round((box['x'] + 24 + (items.index(edge['id']) + .5) * (CARD_WIDTH - 48) / len(items)) * 1000)
            slot, distance = desired, 0
            while slot in used_ports[gap] and used_ports[gap][slot] != edge['id']:
                distance += 3000
                if desired + distance <= upper: slot = desired + distance
                elif desired - distance >= lower: slot = desired - distance
                else:
                    # Dense fan-in still keeps distinct ports within the block.
                    slot = next(value for value in range(lower, upper + 1) if value not in used_ports[gap])
            used_ports[gap][slot] = edge['id']; ports[(identifier, edge['id'], direction)] = slot / 1000
    routed = []
    for edge in edges:
        a, b = node_rank[edge['from']], node_rank[edge['to']]
        source, target = positions[edge['from']], positions[edge['to']]
        x1, x2 = ports[(edge['from'], edge['id'], 'from')], ports[(edge['to'], edge['id'], 'to')]
        y1, y2 = source['y'] + source['height'], target['y']
        departure = track_y[(a + 1, edge['id'], 'departure')]
        if b == a + 1:
            points = [(x1, y1), (x1, departure), (x2, departure), (x2, y2)]
        else:
            channel = 144 + left.index(edge['id']) * TRACK_GAP if edge['id'] in left else gutter_left + grid_width + 20 + right.index(edge['id']) * TRACK_GAP
            arrival = track_y[(b, edge['id'], 'arrival')]
            points = [(x1, y1), (x1, departure), (channel, departure), (channel, arrival), (x2, arrival), (x2, y2)]
        routed.append(dict(edge, points=points, cycle=component_of[edge['from']] == component_of[edge['to']]))
    cycle_ids = {identifier for group in cycles for identifier in group}
    rendered_nodes = [dict(node, **positions[identifier], rank=node_rank[identifier], lines=lines[identifier],
                           cycle=identifier in cycle_ids, target=identifier == target_model_id) for identifier, node in nodes.items()]
    rows = []
    for rank in ranks:
        group = [nodes[identifier] for identifier in grouped[rank]]
        if any(identifier in cycle_ids for identifier in grouped[rank]): heading = 'Cycle / review required'
        elif all(node.get('semantic_kind') == 'topic' for node in group): heading = 'Semantic topics'
        elif all(node.get('semantic_kind') == 'view' for node in group): heading = 'Semantic views'
        elif all(node['layer'] in {'bronze', 'reference'} for node in group): heading = 'Raw / sources'
        elif all(node['layer'] == 'silver' for node in group):
            # Dependency depth does not establish a transformation's purpose.
            # Use familiar declared naming conventions only when the whole row
            # agrees; opaque or mixed names retain the supplied silver layer.
            names = [str(node.get('name') or node['id']).lower() for node in group]
            if all(re.search(r'(^|[./])stg[_.]', name) for name in names): heading = 'Staging / preparation'
            elif all(re.search(r'(^|[./])int[_.]', name) for name in names): heading = 'Intermediate'
            else: heading = 'Silver / transformations'
        elif all(node['layer'] == 'gold' for node in group): heading = 'Gold output' if target_model_id in grouped[rank] else 'Upstream gold'
        else: heading = 'Recorded dependency stage'
        rows.append({'rank': rank, 'label': heading, 'x': 20, 'y': row_y[rank], 'node_ids': grouped[rank]})
    return {'nodes': rendered_nodes, 'edges': routed, 'join_relationships': joins, 'external_connections': external,
            'rows': rows, 'cycles': cycles, 'width': max(1100, gutter_left + grid_width + 44 + len(right) * TRACK_GAP),
            'height': cursor + 48, 'target_model_id': target_model_id, 'label': label or 'Recorded upstream pipeline'}


def _selected(graph, target_model_id):
    if target_model_id is None: return set(graph['nodes'])
    _require(target_model_id in graph['supplied_ids'], 'Pipeline target is outside the supplied inventory')
    selected = _ancestors([target_model_id], graph['edges'])
    views = {identifier for identifier in graph['semantic_ids']
             if target_model_id in graph['nodes'][identifier].get('warehouse_model_ids', [])}
    selected.update(views)
    selected.update(identifier for identifier in graph['semantic_ids'] if any('@semantic/view/' + view in views
                    for view in graph['nodes'][identifier].get('view_ids', [])))
    return selected


def pipeline_layout(models, relationships, *, target_model_id=None, semantic=None, label=None):
    """Pure geometry plus full occurrence metadata; joins are never routed as lineage."""
    graph = _normalize(models, relationships, semantic)
    return _layout(graph, _selected(graph, target_model_id), target_model_id, label)


def _svg(layout):
    e = lambda value: html.escape(str(value), quote=True)
    width, height = layout['width'], layout['height']
    title = layout['label']
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" viewBox="0 0 {width:g} {height:g}" role="img">',
             f'<title>{e(title)}</title><desc>{e(QUALIFICATION)} Full names are retained in block titles. Crossing paths do not imply joins.</desc>',
             f'<rect width="{width:g}" height="{height:g}" fill="#f4f7fb"/>',
             '<defs><marker id="pipeline-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#246d72"/></marker></defs>']
    for index, line in enumerate(_wrap(title, max(50, int((width - 40) / 12)))[:2]):
        parts.append(f'<text x="20" y="{30 + index * 25}" font-family="sans-serif" font-size="21" font-weight="700" fill="#172d43">{e(line)}</text>')
    note = f'{len(layout["nodes"])} objects · {len(layout["edges"])} dependency paths · {len(layout["join_relationships"])} joins retained separately'
    if layout['external_connections']: note += f' · {len(layout["external_connections"])} connections outside this view'
    if layout['cycles']: note += ' · CYCLE: execution order unresolved'
    parts.append(f'<text x="20" y="88" font-family="sans-serif" font-size="14" fill="#53697f">{e(note)}</text>')
    for row in layout['rows']:
        for index, line in enumerate(_wrap(row['label'], 14)):
            parts.append(f'<text x="20" y="{row["y"] + 22 + index * 21:g}" font-family="sans-serif" font-size="16" font-weight="700" fill="#53697f">{e(line)}</text>')
    for edge in layout['edges']:
        color = '#a04729' if edge['cycle'] else '#77579a' if edge['kind'] != 'lineage' else '#246d72'
        dash = ' stroke-dasharray="6 4"' if edge['cycle'] or edge['kind'] != 'lineage' else ''
        path = 'M ' + ' L '.join(f'{x:.12g} {y:.12g}' for x, y in edge['points'])
        description = edge['from'] + ' → ' + edge['to'] + ' · ' + edge['kind'] + ' · ' + str(edge['occurrence_count']) + ' supplied declaration(s)'
        if edge['cycle']: description += ' · Cycle: dependency order unresolved'
        occurrence_ids = json.dumps([row['pipeline_occurrence_id'] for row in edge['occurrences']], ensure_ascii=False)
        parts.append(f'<path data-edge-id="{e(edge["id"])}" data-edge-kind="{e(edge["kind"])}" data-from="{e(edge["from"])}" data-to="{e(edge["to"])}" data-occurrence-ids="{e(occurrence_ids)}" d="{path}" fill="none" stroke="{color}" stroke-width="2"{dash} marker-end="url(#pipeline-arrow)"><title>{e(description)}</title></path>')
    for node in layout['nodes']:
        x, y, w, h = node['x'], node['y'], node['width'], node['height']
        name = node.get('name') or node['id']
        identity = ('data-semantic-id="' + e(node['semantic_id']) + '" data-semantic-kind="' + e(node['semantic_kind']) + '"') if node['identity_kind'] == 'semantic' else ('data-reference-id' if node['identity_kind'] == 'reference' else 'data-model-id') + '="' + e(node['id']) + '"'
        color = '#a04729' if node['cycle'] else '#77579a' if node.get('semantic_kind') else '#b27b26' if node.get('reference_only') or node.get('object_kind') == 'interface' else '#16776c' if node['target'] else '#8197aa'
        parts.append(f'<g {identity} data-node-id="{e(node["id"])}" data-full-name="{e(name)}"><title>{e(name)}</title><rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="9" fill="#ffffff" stroke="{color}" stroke-width="{3 if node["target"] else 2}"/>')
        cursor = y + 27
        for line, kind in node['lines']:
            size = 18 if kind == 'name' else 13 if kind == 'badge' else 14
            weight = '700' if kind in {'name', 'badge'} else '400'
            text_identity = (' ' + identity) if kind == 'name' else ''
            parts.append(f'<text{text_identity} x="{x + 16:g}" y="{cursor:g}" font-family="monospace" font-size="{size}" font-weight="{weight}" fill="{color if kind == "badge" else "#172d43"}">{e(line)}</text>')
            cursor += 25 if kind == 'name' else 20
        parts.append('</g>')
    if not layout['nodes']:
        parts.append('<text x="20" y="130" font-family="sans-serif" font-size="18" fill="#53697f">No pipeline models supplied.</text>')
    parts.append('</svg>')
    return ''.join(parts)


def pipeline_svg(models, relationships, *, target_model_id=None, semantic=None, label=None):
    """Render fixed natural-size SVG; callers should scroll instead of shrinking it."""
    return _svg(pipeline_layout(models, relationships, target_model_id=target_model_id, semantic=semantic, label=label))


def pipeline_views(models, relationships, *, semantic=None):
    """Gold pipelines first, then upstream-closed supplements; no inventory loss.

    ``model_ids`` contains only supplied warehouse identities. Synthesized missing
    references and semantic identities have separate lists and SVG attributes.
    ``edges`` retains all included declarations, even when a shared rendered path
    deduplicates them. ``join_relationships`` is for a separate ERD, never a route.
    """
    graph = _normalize(models, relationships, semantic)
    primary = sorted(identifier for identifier in graph['supplied_ids'] if graph['nodes'][identifier]['layer'] == 'gold'
        and not graph['nodes'][identifier].get('reference_only') and graph['nodes'][identifier].get('object_kind', 'model') not in {'interface', 'source', 'reference'})
    specifications = [('gold_pipeline', identifier, _selected(graph, identifier)) for identifier in primary]
    covered = set().union(*(scope for _, _, scope in specifications)) if specifications else set()
    remaining = set(graph['nodes']) - covered
    # Each remaining dependency sink gets its own upstream view. This keeps
    # disconnected domains and isolated nodes out of an all-model hairball.
    dependency_edges = [edge for edge in graph['edges'] if edge['kind'] != 'relationship']
    if remaining:
        components, membership = _components(remaining, [edge for edge in dependency_edges if edge['from'] in remaining and edge['to'] in remaining])
        non_sinks = {membership[edge['from']] for edge in dependency_edges if edge['from'] in remaining and edge['to'] in remaining and membership[edge['from']] != membership[edge['to']]}
        upstream = defaultdict(set)
        for edge in dependency_edges: upstream[edge['to']].add(edge['from'])
        for index, component in sorted(enumerate(components), key=lambda item: item[1]):
            if index in non_sinks: continue
            scope = set(component); todo = list(component)
            while todo:
                for parent in sorted(upstream[todo.pop()]):
                    if parent not in scope: scope.add(parent); todo.append(parent)
            identifier = component[0]
            specifications.append(('supplemental_pipeline', identifier, scope)); covered.update(scope)
    result = []
    for kind, identifier, scope in specifications:
        name = graph['nodes'][identifier].get('name') or identifier
        label = ('Pipeline to ' if kind == 'gold_pipeline' else 'Supplemental dependency view · ') + name
        layout = _layout(graph, scope, identifier if kind == 'gold_pipeline' else None, label)
        model_ids = sorted(scope & graph['supplied_ids'])
        result.append({'id': 'pipeline-' + _digest([kind, identifier]), 'kind': kind, 'label': label,
            'target_model_id': identifier if kind == 'gold_pipeline' else None, 'model_ids': model_ids,
            'reference_ids': sorted(scope - graph['supplied_ids'] - graph['semantic_ids']),
            'semantic_ids': sorted(scope & graph['semantic_ids']), 'internal_connections': len(layout['edges']),
            'cross_view_connections': len(layout['external_connections']), 'external_connections': layout['external_connections'], 'join_relationships': layout['join_relationships'],
            'edges': [{key: value for key, value in edge.items() if key not in {'points'}} for edge in layout['edges']],
            'cycles': layout['cycles'], 'qualification': QUALIFICATION, 'width': layout['width'], 'height': layout['height'],
            'base64': base64.b64encode(_svg(layout).encode()).decode()})
    return result
