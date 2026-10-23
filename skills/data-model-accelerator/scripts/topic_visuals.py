"""Offline topic review projections. Recorded joins are not native validation."""
import base64
import csv
import hashlib
import html
import io
import json
import re
import textwrap
from urllib.parse import quote

from ae_common import require

QUALIFICATION = 'Candidate topic structure and bindings. Native validation, fanout checks and business approval remain separate.'
STYLE = 'text{font-family:system-ui,sans-serif;fill:#173b46;font-size:18px}.title{font-size:25px;font-weight:700}.small{font-size:15px}.join{fill:none;stroke:#56818d;stroke-width:2}.card{fill:#fff;stroke:#087e83;stroke-width:2}.gap{fill:#fff5de;stroke:#b36b12}.caption{fill:#465d67}'


def panel():
    return '''<section id="omni-topic-trees" class="review-section" data-section hidden>
<h1>Omni Topics</h1><p>Choose a domain and topic to see its declared join paths and warehouse tables. A diagram is not a fanout test or native validation.</p>
<p id="topic-coverage" class="scope-note" aria-live="polite"></p>
<div class="controls filters"><div><label for="topic-domain">Domain</label><select id="topic-domain"><option value="">All domains</option></select></div><div><label for="topic-picker">Topic</label><select id="topic-picker"></select></div></div>
<p id="topic-empty" hidden>No topics match this selection.</p><div class="controls diagram-toolbar"><button id="topic-zoom-in" type="button">Zoom in</button><button id="topic-zoom-out" type="button">Zoom out</button><button id="topic-zoom-reset" type="button">Actual size</button><button id="topic-download" type="button">Download SVG</button></div>
<div id="topic-diagram" class="diagram" tabindex="0" aria-label="Topic join tree, scroll to explore"></div>
<div id="topic-findings" class="scope-note" role="status"></div><details class="panel"><summary>Views and warehouse tables</summary><div id="topic-bindings" class="scroll"></div></details></section>'''


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _cell(value):
    text = str(value or '')
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text


def _name(topic):
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', topic['id']).strip('-.')[:70] or 'topic'
    return slug + '-' + hashlib.sha256(topic['id'].encode()).hexdigest()[:12]


def svg(topic):
    """Layout occurrences, not view names: aliases keep their own join path."""
    nodes = topic.get('nodes', [])
    if not nodes:
        nodes = [{'id': 'unresolved', 'view_id': topic.get('base_view') or 'Unresolved base view',
                  'path': [], 'model_ids': [], 'binding_status': 'unresolved'}]
    require(len(nodes) <= 5000, 'Topic diagram exceeds the bounded view inventory; partition the semantic scope.')
    by_id = {n['id']: n for n in nodes}
    require(len(by_id) == len(nodes), 'Duplicate topic occurrence identity')
    children = {key: [] for key in by_id}
    roots = []
    for node in nodes:
        parent = node.get('parent_id')
        if parent in children: children[parent].append(node['id'])
        else: roots.append(node['id'])
    positions, visiting, cursor = {}, set(), [0]
    def place(key, depth):
        require(key not in visiting, 'Topic diagram contains a cycle')
        visiting.add(key)
        descendants = children[key]
        for child in descendants: place(child, depth + 1)
        if descendants: x = (positions[descendants[0]][0] + positions[descendants[-1]][0]) / 2
        else: x = 30 + cursor[0] * 390; cursor[0] += 1
        positions[key] = (x, 110 + depth * 255)
        visiting.remove(key)
    for key in roots: place(key, 0)
    require(len(positions) == len(nodes), 'Topic diagram has an unreachable occurrence')
    width = max(800, max(p[0] for p in positions.values()) + 370)
    height = max(p[1] for p in positions.values()) + 220
    e = lambda value: html.escape(str(value), quote=True)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" viewBox="0 0 {width:g} {height:g}" data-topic-id="{e(topic["id"])}" role="img" aria-label="{e(topic.get("name") or topic["id"])}">',
        '<style>' + STYLE + '</style>',
        f'<rect width="{width:g}" height="{height:g}" fill="#f3f8f8"/>',
        f'<text x="30" y="38" class="title">{e(topic.get("name") or topic["id"])}</text>',
        f'<text x="30" y="69" class="small caption">{e(topic.get("domain") or "Unassigned")} · {e(topic.get("structural_status", "unresolved"))} structure · {e(topic.get("binding_status", "unresolved"))} bindings</text>']
    for edge in topic.get('edges', []):
        if edge.get('from') not in positions or edge.get('to') not in positions: continue
        x1, y1 = positions[edge['from']]; x2, y2 = positions[edge['to']]
        mid = y2 - 45
        parts.append(f'<g data-edge-id="{e(edge.get("id") or edge["from"]+":"+edge["to"])}"><title>{e(edge.get("relationship_direction", "unresolved"))} relationship</title><path class="join" d="M{x1+160:g} {y1+165:g} V{mid:g} H{x2+160:g} V{y2:g}"/><path d="M{x2+154:g} {y2-9:g} L{x2+160:g} {y2:g} L{x2+166:g} {y2-9:g}" fill="none" stroke="#56818d" stroke-width="2"/><text x="{x2+8:g}" y="{y2-15:g}" class="small">{e(edge.get("relationship_type") or "Unresolved cardinality")} · {e(edge.get("join_type") or "join unresolved")}</text></g>')
    for node in nodes:
        x, y = positions[node['id']]
        status = node.get('binding_status', 'unresolved')
        klass = 'card' if status in ('bound', 'complete', 'resolved') else 'card gap'
        title = node.get('view_id') or node['id']
        bound = ', '.join(node.get('model_ids', [])) or 'No warehouse binding'
        parts.append(f'<g data-occurrence-id="{e(node["id"])}" data-view-id="{e(title)}" data-warehouse-model-ids="{e(_encoded(node.get("model_ids", [])))}"><title>{e(title)} → {e(bound)}</title><rect class="{klass}" x="{x:g}" y="{y:g}" width="320" height="165" rx="10"/>')
        for i, line in enumerate(textwrap.wrap(title, 29)[:3]):
            parts.append(f'<text x="{x+15:g}" y="{y+29+i*22:g}">{e(line)}</text>')
        for i, line in enumerate(textwrap.wrap(bound, 35)[:2]):
            parts.append(f'<text class="small" x="{x+15:g}" y="{y+104+i*20:g}">{e(line)}</text>')
        parts.append(f'<text class="small" x="{x+15:g}" y="{y+149:g}">{e(status)}</text></g>')
    parts.append(f'<text class="small caption" x="30" y="{height-22:g}">Declared join paths only. See the topic coverage findings before using this model.</text></svg>')
    return ''.join(parts).encode()


def projections(tree, layout=2):
    """One source produces page diagrams, index and spreadsheet mappings."""
    folder = '03_Design_Documents/Topics' if layout == 2 else '01_Model/Topics'
    mapping = '05_Mappings/TOPIC_TO_TABLE.csv' if layout == 2 else '01_Model/TOPIC_TO_TABLE.csv'
    pages, exports = [], []
    def export(identifier, path, category, body):
        exports.append({'id': identifier, 'path': path, 'category': category, 'description': QUALIFICATION,
                        'requires': [], 'origin': 'review_projection', 'sha256': hashlib.sha256(body).hexdigest(),
                        'size': len(body), 'base64': base64.b64encode(body).decode()})
    index = ['# Omni topic diagrams', '', QUALIFICATION, '']
    stream = io.StringIO(newline=''); writer = csv.writer(stream, lineterminator='\n', quoting=csv.QUOTE_ALL)
    writer.writerow(['topic_id', 'domain', 'view_id', 'join_path', 'warehouse_model_id', 'binding_status', 'structural_status'])
    for topic in tree.get('topics', []):
        path = folder + '/' + _name(topic) + '.svg'
        body = svg(topic)
        pages.append({'id': topic['id'], 'name': topic.get('name') or topic['id'], 'domain': topic.get('domain') or 'Unassigned',
                      'base64': base64.b64encode(body).decode(), 'export_path': path,
                      'binding_status': topic.get('binding_status'), 'structural_status': topic.get('structural_status'),
                      'diagnostics': topic.get('diagnostics', []), 'binding_diagnostics': topic.get('binding_diagnostics', []), 'nodes': topic.get('nodes', [])})
        export('generated:topic:' + _name(topic), path, 'diagrams', body)
        label = str(topic.get('name') or topic['id']).replace('[', '\\[').replace(']', '\\]').replace('\n', ' ')
        index.append('- [' + label + '](' + quote(path.rsplit('/', 1)[-1]) + ') — ' + str(topic.get('binding_status', 'unresolved')))
        for finding in topic.get('diagnostics', []) + topic.get('binding_diagnostics', []):
            index.append('  - ' + str(finding.get('code') if isinstance(finding, dict) else finding).replace('\n', ' '))
        for node in topic.get('nodes', []) or [{}]:
            for model in node.get('model_ids', []) or ['']:
                writer.writerow([_cell(v) for v in [topic['id'], topic.get('domain'), node.get('view_id'),
                    ' → '.join(node.get('path', [])), model, node.get('binding_status', 'unresolved'), topic.get('structural_status')]])
    export('generated:topic-index', folder + '/INDEX.md', 'diagrams', ('\n'.join(index) + '\n').encode())
    export('generated:topic-mapping', mapping, 'dictionary', stream.getvalue().encode())
    return pages, exports


def prepare(data):
    """Rebuild only from selected pinned evidence; never trust caller page flags."""
    review = data.get('review', {})
    for key in ('topic_diagrams', 'topic_exports', 'topic_coverage'): data.pop(key, None)
    review.pop('topic_join_trees', None)
    evidence = review.get('omni', {})
    if evidence.get('evidence_state') != 'selected': return
    raw = evidence.get('topic_trees')
    if raw is None:
        # Old immutable summaries remain usable without inventing their join paths.
        topics = [{'id': t['id'], 'name': t.get('label') or t['id'], 'domain': 'Unassigned',
                   'base_view': t.get('base_view'), 'nodes': [], 'edges': [],
                   'diagnostics': [{'code': 'topic.legacy_topology_unavailable'}],
                   'structural_status': 'incomplete', 'binding_status': 'unresolved'} for t in evidence.get('topics', [])]
        tree = {'schema_version': 1, 'kind': 'omni_topic_trees', 'topics': topics,
                'expected_topic_ids': [t['id'] for t in topics], 'legacy': True}
        coverage = {'status': 'incomplete' if topics else 'not_applicable', 'expected': len(topics), 'represented': len(topics),
                    'qualification': 'Refresh semantic evidence to produce join paths; existing candidate files remain available.'}
    else:
        from omni_topic_trees import bind_topic_trees, topic_tree_coverage
        tree = bind_topic_trees(raw, review.get('omni_warehouse_bindings') or [],
                                [{k: m.get(k) for k in ('id', 'layer', 'domain')} for m in review.get('models', [])],
                                review.get('omni_topic_domains'), expected_pins=evidence.get('topic_tree_pins'))
        coverage = topic_tree_coverage(tree)
    review['topic_join_trees'] = tree
    data['topic_coverage'] = coverage
    data['topic_diagrams'], data['topic_exports'] = projections(tree, data.get('package_layout_version', 1))


def verify(data):
    import copy
    check = copy.deepcopy(data)
    prepare(check)
    require(check.get('review', {}).get('topic_join_trees') == data.get('review', {}).get('topic_join_trees')
            and all(check.get(key) == data.get(key) for key in ('topic_diagrams', 'topic_exports', 'topic_coverage')),
            'Topic diagrams or coverage differ from selected semantic evidence and warehouse bindings')
