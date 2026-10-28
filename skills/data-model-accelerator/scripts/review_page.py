"""The review page every package opens on (references/review-page.md).

One template serves both packaging modes. Small packages embed every file in delivery-data, so
code opens inline; large (partitioned) packages link to their per-file code pages. The page model
is derived from the checked review projection and the packaged files only: it reads no source
repository, executes nothing and records no approval.
"""
import base64
import collections
import html
import json
import re
from pathlib import Path, PurePosixPath

try:
    import yaml
except ImportError:  # pragma: no cover - optional in lightweight runs
    yaml = None

ASSETS = Path(__file__).resolve().parent.parent / 'assets/review-page'
TABS = (('overview', 'Overview'), ('model', 'Data model'), ('delivery', 'Code & files'), ('changes', 'Decisions'),
        ('replacement-map', 'Legacy coverage'), ('table-dictionary', 'Data dictionary'), ('validation', 'Validation'),
        ('open-items', 'Open items'))
TOP_SECTIONS = ('overview', 'model', 'delivery', 'changes', 'validation', 'open-items', 'review-feedback', 'dashboard-migration')
NESTED = {'architecture': 'model', 'lineage': 'model', 'table-dictionary': 'model',
          'implementation-code': 'delivery', 'replacement-map': 'delivery'}
QUALIFICATION = ('Candidate review. Recorded validation evidence is shown below; '
                 'this page does not establish native execution, business approval or deployment authority.')
REF = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")
SOURCE = re.compile(r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")
FIELD = re.compile(r"\$\{([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}")


def _encode(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def _yaml(text):
    if yaml is None:
        return None
    try:
        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - a parse failure is reported by the static checks
        return None


def _areas(review, models, relationships, pipelines):
    """Group canonical views without losing disconnected or upstream-only inventory."""
    declared = review.get('subject_areas') or []
    areas = {a['id']: dict(a, gold=[], erd=[], pipeline=[], diagram_ids=[]) for a in declared}
    for m in models.values():
        key = m.get('area') or m.get('domain') or 'Unassigned'
        area = areas.setdefault(key, {'id': key, 'name': key, 'shared': False,
                                     'gold': [], 'erd': [], 'pipeline': [], 'diagram_ids': []})
        if m.get('layer') == 'gold': area['gold'].append(m['id'])
    for view in pipelines:
        owner = models.get(view.get('target_model_id')) or next((models[x] for x in view['model_ids'] if x in models), {})
        key = owner.get('area') or owner.get('domain') or 'Unassigned'
        area = areas.setdefault(key, {'id': key, 'name': key, 'shared': False,
                                     'gold': [], 'erd': [], 'pipeline': [], 'diagram_ids': []})
        area['diagram_ids'].append(view['id'])
        area['pipeline'] = sorted(set(area['pipeline']) | set(view['model_ids']))
    for area in areas.values():
        own = set(area['gold'])
        area['erd'] = sorted(own | {x for r in relationships if r['from'] in own or r['to'] in own
                                   for x in (r['from'], r['to']) if x in models})
    return list(areas.values())


def _topics(review, texts, assets, models, home):
    """Project the canonical producer only. Never infer physical bindings from names."""
    from topic_visuals import svg
    topology = review.get('topic_join_trees') or {}
    rows = list(topology.get('topics', []))
    # A missing producer is a visible gap, including inherited topics with no local base_view.
    from omni_query_views import _identity
    known = {r['id'] for r in rows}
    for path in sorted(texts):
        kind, name = _identity(path)
        if kind == 'topic' and name not in known:
            rows.append({'id': name, 'source_path': path, 'nodes': [], 'edges': [],
                         'diagnostics': [{'code': 'topic.canonical_tree_missing'}]})
            known.add(name)
    out = []
    for topic in rows:
        nodes = topic.get('nodes', []); by_id = {n['id']: n for n in nodes}
        root = next((n for n in nodes if n.get('parent_id') is None), {})
        bound = root.get('model_ids', [])
        base = bound[0] if len(bound) == 1 else topic.get('base_view') or 'Unresolved base view'
        name = topic['id']; domain = topic.get('domain') or 'Unassigned'
        area = home.get(base) or domain
        edges = [{'from': (by_id.get(r['from']) or {}).get('view_id', r['from']),
                  'to': (by_id.get(r['to']) or {}).get('view_id', r['to']),
                  'depth': max(1, len(r.get('path', [])) - 1), 'card': r.get('relationship_type') or '',
                  'on': 'Predicate not projected; inspect the relationship file', 'direction': r.get('relationship_direction'), 'id': r['id']}
                 for r in topic.get('edges', [])]
        diagnostics = topic.get('diagnostics', []) + topic.get('binding_diagnostics', [])
        out.append({'topic': name, 'label': topic.get('name') or name, 'base': base, 'area': area,
                    'domain': domain, 'joins': edges, 'views': sorted({m for n in nodes for m in n.get('model_ids', [])}),
                    'view_ids': [n.get('view_id') for n in nodes],
                    'bindings': [{'id': n['id'], 'view_id': n.get('view_id'), 'model_ids': n.get('model_ids', [])} for n in nodes], 'fields': [], 'group': '', 'desc': '', 'ai': '',
                    'path': topic.get('source_path', ''), 'view_files': {}, 'diagnostics': diagnostics,
                    'binding_status': topic.get('binding_status', 'gap'),
                    'base64': base64.b64encode(svg(topic)).decode(),
                    'dashboards': [{'id': a.get('id'), 'title': a.get('name') or a.get('id'),
                                    'status': a.get('coverage_status') or a.get('mapping_status') or 'unassessed'}
                                   for a in assets if name in (a.get('topics') or [])]})
    return out, ('Unresolved topic structure or bindings remain visible; run the canonical semantic producer.'
                 if any(t['diagnostics'] or t['binding_status'] != 'complete' for t in out) else '')


def static_checks(texts, model_ids):
    """File-only counts: YAML errors, models without YAML, unresolved refs/sources, broken Omni references."""
    if yaml is None:
        return []
    yml = {p: t for p, t in texts.items() if p.endswith(('.yml', '.yaml')) and '/models/' in p}
    omni = {p: t for p, t in texts.items() if p.endswith(('.view', '.topic')) or PurePosixPath(p).name in ('model', 'relationships')}
    errors, docs = [], []
    for path, text in sorted({**yml, **omni}.items()):
        try:
            doc = yaml.safe_load(text)
        except Exception as error:  # noqa: BLE001
            errors.append({'file': path, 'error': str(error).splitlines()[0][:200]})
            continue
        if path in yml and isinstance(doc, dict):
            docs.append(doc)
    sql = {PurePosixPath(p).stem: t for p, t in texts.items() if p.endswith('.sql') and '/models/' in p}
    documented = {m.get('name') for d in docs for m in (d.get('models') or []) if isinstance(m, dict)}
    sources = {(s.get('name'), t.get('name')) for d in docs for s in (d.get('sources') or []) if isinstance(s, dict)
               for t in (s.get('tables') or []) if isinstance(t, dict)}
    known = set(model_ids) | set(sql)
    unresolved = []
    for name, text in sorted(sql.items()):
        unresolved += [{'model': name, 'ref': r} for r in REF.findall(text) if r not in known]
        unresolved += [{'model': name, 'ref': 'source ' + a + '.' + b} for a, b in SOURCE.findall(text) if sources and (a, b) not in sources]
    views = {}
    for path, text in omni.items():
        if path.endswith('.view'):
            doc = _yaml(text) or {}
            views[PurePosixPath(path).stem] = set(doc.get('dimensions') or {}) | set(doc.get('measures') or {}) if isinstance(doc, dict) else set()
    field_issues, relation_issues, pairs = [], [], set()

    def refs(expression, where, bucket):
        for view, field in FIELD.findall(expression):
            if view not in views:
                bucket.append({'where': where, 'ref': view + '.' + field, 'issue': 'view not in model'})
            elif field not in views[view]:
                bucket.append({'where': where, 'ref': view + '.' + field, 'issue': 'field not defined'})
    for path, text in omni.items():
        if path.endswith('.view'):
            doc = _yaml(text) or {}
            for section in ('dimensions', 'measures'):
                for field, spec in ((doc.get(section) or {}) if isinstance(doc, dict) else {}).items():
                    refs(json.dumps(spec), PurePosixPath(path).stem + '.' + field, field_issues)
    rows = next((_yaml(t) for p, t in omni.items() if PurePosixPath(p).name == 'relationships'), None) or []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        where = str(row.get('join_from_view')) + ' → ' + str(row.get('join_to_view'))
        for side in ('join_from_view', 'join_to_view'):
            if row.get(side) not in views:
                relation_issues.append({'where': where, 'ref': str(row.get(side)), 'issue': 'view not in model'})
        refs(str(row.get('on_sql', '')), where, relation_issues)
        pairs.add((row.get('join_from_view'), row.get('join_to_view')))
    topics = 0
    for path, text in omni.items():
        if not path.endswith('.topic'):
            continue
        topics += 1
        doc = _yaml(text) or {}
        where = 'topic ' + PurePosixPath(path).stem
        if doc.get('base_view') not in views:
            field_issues.append({'where': where, 'ref': str(doc.get('base_view')), 'issue': 'base view not in model'})
        for item in doc.get('fields') or []:
            view, _, field = str(item).lstrip('-').partition('.')
            if view not in views:
                field_issues.append({'where': where, 'ref': str(item), 'issue': 'view not in model'})
            elif field != '*' and field not in views[view]:
                field_issues.append({'where': where, 'ref': str(item), 'issue': 'field not defined'})

        def walk(parent, children):
            for child, nested in (children or {}).items():
                if (parent, child) not in pairs and (child, parent) not in pairs:
                    relation_issues.append({'where': where, 'ref': str(parent) + ' → ' + child, 'issue': 'join has no relationship'})
                walk(child, nested if isinstance(nested, dict) else {})
        walk(doc.get('base_view'), doc.get('joins') if isinstance(doc.get('joins'), dict) else {})
    checks = [{'id': 'yaml-errors', 'label': 'YAML errors', 'count': len(errors), 'scope': f'{len(yml) + len(omni)} YAML and Omni files parsed', 'items': errors}]
    if sql:
        checks += [{'id': 'models-without-yaml', 'label': 'Models without YAML', 'count': len([m for m in sql if m not in documented]),
                    'scope': f'{len(sql)} packaged SQL models', 'items': sorted(m for m in sql if m not in documented)},
                   {'id': 'unresolved-refs', 'label': 'Unresolved refs and sources', 'count': len(unresolved),
                    'scope': f'{len(sql)} packaged SQL models, against the packaged files and the review inventory', 'items': unresolved}]
    if omni:
        checks += [{'id': 'omni-field-refs', 'label': 'Broken Omni field references', 'count': len(field_issues),
                    'scope': f'{len(views)} views and {topics} topics', 'items': field_issues},
                   {'id': 'omni-relationships', 'label': 'Broken Omni relationships', 'count': len(relation_issues),
                    'scope': f'{len(rows) if isinstance(rows, list) else 0} relationships, plus every topic join', 'items': relation_issues}]
    return checks


def page_model(data, texts, code_pages=None, model_pages=None):
    """texts maps packaged paths to decoded text; code_pages/model_pages map ids to detail pages (large packages)."""
    review = data.get('review', {})
    keep = ('id', 'name', 'layer', 'domain', 'disposition', 'grain', 'description', 'columns', 'depends_on', 'area',
            'security_notes', 'security', 'existing_source', 'sources', 'artifact_id', 'artifact_ids', 'entity_type', 'reuse', 'object_kind', 'keys')
    models = {m['id']: {k: m[k] for k in keep if k in m} for m in review.get('models', [])}
    relationships = [{'from': r['from'], 'to': r['to'], 'card': r.get('cardinality') or '', 'role': r.get('role') or '',
                      'key': ', '.join(r.get('from_columns', [])) + (' = ' + ', '.join(r.get('to_columns', [])) if r.get('to_columns') else '')}
                     for r in review.get('relationships', []) if r.get('kind') == 'relationship' and r['from'] in models and r['to'] in models]
    from pipeline_diagrams import pipeline_views, pipeline_layout
    graph = pipeline_layout(list(models.values()), review.get('relationships', []))
    for model in models.values():
        model['depends_on'] = sorted({e['from'] for e in graph['edges'] if e['to'] == model['id'] and e['kind'] == 'lineage'})
    pipelines = pipeline_views(review.get('models', []), review.get('relationships', []))
    areas = _areas(review, models, relationships, pipelines)
    home = {g: a['id'] for a in areas for g in a['gold']}
    for identifier, model in models.items():
        model.setdefault('area', home.get(identifier))
    inventory = data.get('files', []) + data.get('generated_deliverables', [])
    files = [{'id': f['id'], 'path': f['path'], 'category': f.get('category', ''), 'size': f.get('size', 0),
              'page': (code_pages or {}).get(f['id'])} for f in inventory]
    topics, topic_note = _topics(review, texts, review.get('assets', []), models, home)
    area_ids = {a['id'] for a in areas}
    for topic in topics:
        if topic['area'] not in area_ids:
            areas.append({'id': topic['area'], 'name': topic['area'], 'gold': [], 'erd': [], 'pipeline': [], 'diagram_ids': []})
            area_ids.add(topic['area'])
    placeholders = collections.defaultdict(list)
    for path, text in texts.items():
        if path.endswith('.topic') or path.endswith('.view'):
            for line in text.splitlines():
                if 'TODO' in line:
                    placeholders[line.strip().lstrip('# ').split(':')[0][:80]].append(path)
    return {'schema_version': 1, 'qualification': QUALIFICATION, 'title': review.get('title') or 'Data model review',
            'meta': review.get('review_meta', {}), 'models': list(models.values()), 'relationships': relationships,
            'decisions': review.get('decisions', []),
            'validation': review.get('validation', []) + review.get('quality_checks', []),
            'evidence': {**{key: data[key] for key in ('domain_journey', 'deployment', 'delivery_assurance') if key in data},
                         **{key: review[key] for key in ('metadata', 'quality_checks') if key in review},
                         **({'dbt_runtime': data['engagement']['dbt_runtime']} if data.get('engagement', {}).get('dbt_runtime') else {})},
            'assets': review.get('assets', []), 'pipeline_diagrams': pipelines,
            'legacy': review.get('legacy_coverage'), 'areas': areas, 'topics': topics, 'topic_note': topic_note,
            'static': review['static_checks'] if 'static_checks' in review else static_checks(texts, models),
            'placeholders': [{'text': k, 'files': sorted(set(v))} for k, v in sorted(placeholders.items())],
            'new_sources': sorted({s for m in models.values() if m.get('layer') == 'bronze' and m.get('disposition') == 'create' for s in m.get('sources', [])}),
            'files': files, 'model_pages': model_pages or {}, 'inline_files': code_pages is None,
            'checkpoint': data.get('checkpoint'), 'engagement_id': data.get('engagement', {}).get('engagement_id'),
            'target': data.get('engagement', {}).get('target') or review.get('target', {}),
            'frontend': data.get('workflow', {}).get('frontend_continuation')}


def text_files(data):
    texts = {}
    for record in data.get('files', []) + data.get('generated_deliverables', []):
        if PurePosixPath(record['path']).suffix.lower() in {'.pdf', '.docx', '.xlsx', '.svg'}:
            continue
        try:
            texts[record['path']] = base64.b64decode(record.get('base64', ''), validate=True).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            continue
    return texts


def render(delivery_data, page=None, *, extra_html='', extra_js=''):
    """Render START_HERE.html. delivery_data is embedded unchanged as the checked delivery-data block."""
    page = page or page_model(delivery_data, text_files(delivery_data))
    if not extra_html and not extra_js:
        extra_html, extra_js = topic_extras(delivery_data)
    template = (ASSETS / 'review.html').read_text(encoding='utf-8')
    return (template.replace('__TITLE__', html.escape(page['title']))
            .replace('/*__REVIEW_CSS__*/', (ASSETS / 'review.css').read_text(encoding='utf-8'))
            .replace('<!--__EXTRA_HTML__-->', extra_html)
            .replace('/*__DELIVERY_DATA__*/', _encode(delivery_data))
            .replace('/*__PAGE_DATA__*/', _encode(page))
            .replace('/*__REVIEW_JS__*/', (ASSETS.parent / 'guided-delivery/portal-svg.js').read_text(encoding='utf-8') + '\n' + (ASSETS / 'review.js').read_text(encoding='utf-8'))
            .replace('/*__EXTRA_JS__*/', extra_js))


def topic_extras(data):
    """The verified topic-tree panel, when the selection includes topic coverage."""
    if not data.get('topic_coverage'):
        return '', ''
    from topic_visuals import panel
    assets = Path(__file__).resolve().parent.parent / 'assets/guided-delivery'
    nav = '<nav class="footnav" aria-label="Topic trees"><a href="#omni-topic-trees" data-nav="omni-topic-trees">Omni topic trees</a></nav>'
    return panel(data) + nav, (assets / 'portal-svg.js').read_text(encoding='utf-8') + '\n' + (assets / 'topic-panel.js').read_text(encoding='utf-8')


def check_structure(parsed, *, topic_trees=False):
    """Eight primary tabs in order, every route present, every link pointing at a route."""
    from ae_common import require
    primary = [n for n in parsed.navigation if any(tag == 'nav' and ident == 'primary-navigation' for tag, ident in n['parents'])]
    require([(n['attrs'].get('data-nav'), n['attrs'].get('href')) for n in primary] == [(k, '#' + k) for k, _ in TABS],
            'Review page primary tabs must be: ' + ', '.join(label for _, label in TABS))
    for identifier in TOP_SECTIONS + (('omni-topic-trees',) if topic_trees else ()):
        node = parsed.nodes.get(identifier, {})
        require(node.get('tag') == 'section' and 'data-section' in node.get('attrs', {})
                and 'review-section' in node['attrs'].get('class', '').split(), 'Review page route is missing: ' + identifier)
    for identifier, parent in NESTED.items():
        node = parsed.nodes.get(identifier, {})
        require(node.get('tag') == 'section' and node.get('parents', ())[-1:] == (('section', parent),),
                'Review page view is missing or misplaced: ' + identifier)
    for nav in parsed.navigation:
        target = nav['attrs'].get('data-nav')
        require(nav['attrs'].get('href') == '#' + str(target) and parsed.nodes.get(target, {}).get('tag') == 'section',
                'Review page link must target a route: ' + str(target))
