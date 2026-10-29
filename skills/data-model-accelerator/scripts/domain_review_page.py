#!/usr/bin/env python3
"""Domain review page: the standard Start Here page and folder layout for one domain.

A domain review is a single-domain design handoff: the medallion model (bronze, silver, gold),
the semantic layer built on it, the legacy models and dashboards it replaces, decisions,
validation and open items. This module owns one explicit page-data contract
(references/domain-review-page.md) and three operations:

* ``project`` derives page data from a checked review (delivery_portal review contract) and the
  packaged code files. It never reads a source repository and never infers a table from a name:
  semantic views bind to models only through their declared ``table_name``.
* ``render`` validates page data and writes the self-contained ``START_HERE.html``.
* ``write_package`` writes the review folder (01_review, 02_dbt, 03_omni, 04_docs, START_HERE.html,
  MANIFEST.csv) into a new version folder.

Nothing here executes code, approves a design or grants a share; counts are computed from the
data so headline figures cannot drift from the tables they summarise.
"""
import argparse
import collections
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile

from ae_common import load_json, require, safe_relative

try:
    import yaml
except ImportError:  # pragma: no cover - optional in lightweight runs
    yaml = None

ASSETS = Path(__file__).resolve().parent.parent / 'assets/domain-review'
SCHEMA_VERSION = 1
KIND = 'domain_review_page'
LAYERS = ('bronze', 'silver', 'gold')
DISPOSITIONS = ('create', 'extend', 'reuse')
DASHBOARD_STATUSES = ('served', 'partly_served', 'not_served')
LEGACY_STATUSES = ('covered', 'partially covered', 'retire candidate', 'out of domain', 'unresolved')
DECISION_STATUSES = ('answered', 'assumed', 'open')
FILE_STATUSES = ('new', 'changed')
CHECK_STATUSES = ('pass', 'fail', 'pending', 'skipped', 'not_applicable')
VIEWS = ('overview', 'model', 'code', 'decisions', 'legacy', 'dict', 'valid', 'todos')
LAYOUT = {'review': '01_review', 'code': '02_dbt', 'semantic': '03_omni', 'docs': '04_docs'}
MAX_ITEMS = 20000
MAX_PAGE_BYTES = 20 * 1024 * 1024
TEMPLATE_TOKENS = ('__TITLE__', '__BRAND__', '/*__DOMAIN_REVIEW_CSS__*/', '/*__DOMAIN_REVIEW_DATA__*/',
                   '/*__DOMAIN_REVIEW_JS__*/')

DEFAULT_BANNER = ('Candidate delivery for design review. Not compiled, not run in the warehouse, not imported '
                  'into the semantic layer, not validated with data, and not approved.')
DECISION_NOTE = ('Answered = set by the people who requested the work; assumed = chosen by the authors and still '
                 'reviewable; open = needs a person, and nothing that depends on it is modelled until it is '
                 'answered. For open decisions the assumed option is what the code does until someone answers.')
VALIDATION_NOTE = ('Static checks only. Nothing was compiled or executed: no build, no warehouse query, no '
                   'semantic-layer import. A zero means the check found nothing in the files, not that the model works.')
DISPOSITION_ALIASES = {'create': 'create', 'new': 'create', 'created': 'create',
                       'extend': 'extend', 'changed': 'extend', 'extended': 'extend', 'modified': 'extend',
                       'reuse': 'reuse', 'reused': 'reuse', 'existing': 'reuse', 'unchanged': 'reuse'}
DECISION_ALIASES = {'answered': 'answered', 'resolved': 'answered', 'accepted': 'answered', 'approved': 'answered',
                    'assumed': 'assumed', 'recorded': 'assumed', 'proposed': 'assumed',
                    'open': 'open', 'pending': 'open', 'unresolved': 'open'}
LEGACY_FROM_DISPOSITION = {'reuse_existing': 'covered', 'extend_existing': 'covered', 'replace': 'retire candidate',
                           'retire_candidate': 'retire candidate', 'move_upstream': 'retire candidate',
                           'split': 'retire candidate', 'consolidate_candidate': 'retire candidate',
                           'retain_semantic': 'retire candidate', 'partial': 'partially covered',
                           'out_of_domain': 'out of domain', 'unresolved': 'unresolved'}
SUFFIX_TYPES = (('_dim', 'dimension'), ('_fct', 'fact'), ('_fact', 'fact'), ('_xa', 'extended analysis'),
                ('_bridge', 'bridge'), ('_daily', 'snapshot'), ('_monthly', 'snapshot'))
REF = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")
SOURCE = re.compile(r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")
FIELD = re.compile(r"\$\{([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}")


def human(value):
    return str(value or '').replace('_', ' ')


def _text(value, name, *, empty=True):
    require(isinstance(value, str) and (empty or value.strip()), name + ' must be text')
    return value


def _list(value, name):
    require(isinstance(value, list) and len(value) <= MAX_ITEMS, name + ' must be a bounded list')
    return value


def _unique(rows, key, name):
    values = [row[key] for row in rows]
    require(len(values) == len(set(values)), name + ' IDs must be unique')
    return set(values)


def model_type(model_id, layer):
    for suffix, label in SUFFIX_TYPES:
        if model_id.endswith(suffix):
            return label
    return {'bronze': 'staging', 'silver': 'integration'}.get(layer, 'table')


def file_kind(path):
    name = PurePosixPath(path).name
    if name.endswith('.topic'):
        return 'topic'
    if name.endswith('.view'):
        return 'view'
    if name.split('.')[0] == 'relationships':
        return 'relationships'
    if name in ('model', 'model.yaml'):
        return 'model'
    return 'dbt' if path.startswith(LAYOUT['code'] + '/') else 'other'


def placeholder_label(text):
    head = text.strip().lstrip('#-/* ').split(':')[0].strip()
    return head[:80] or 'TODO'


def _upstream(models, start):
    seen, stack = set(), list(models[start]['dep'])
    while stack:
        current = stack.pop()
        if current in seen or current not in models or models[current]['layer'] == 'gold':
            continue
        seen.add(current)
        stack.extend(models[current]['dep'])
    return seen


def _model(row):
    require(isinstance(row, dict), 'Model must be an object')
    model_id = _text(row.get('id'), 'Model id', empty=False)
    require(row.get('layer') in LAYERS, 'Model layer must be bronze, silver or gold: ' + model_id)
    require(row.get('disp') in DISPOSITIONS, 'Model disposition must be create, extend or reuse: ' + model_id)
    _text(row.get('domain'), 'Model domain', empty=False)
    out = dict(row)
    out.setdefault('type', model_type(model_id, row['layer']))
    for key in ('desc', 'grain', 'source_path'):
        out[key] = _text(out.get(key) or '', 'Model ' + key)
    out['existing'] = out.get('existing') or {
        'create': 'New in this delivery', 'extend': 'Existing model, changed in this delivery',
        'reuse': 'Existing model, reused unchanged'}[row['disp']]
    for key in ('dep', 'src', 'sec'):
        out[key] = [_text(x, 'Model ' + key) for x in _list(out.get(key) or [], 'Model ' + key)]
    cols = []
    for col in _list(out.get('cols') or [], 'Model columns'):
        require(isinstance(col, list) and len(col) == 4 and all(isinstance(x, str) for x in col)
                and col[0] and col[2] in ('', 'PK', 'FK'), 'Columns are [name, type, PK|FK|"", description]: ' + model_id)
        cols.append(col)
    out['cols'] = cols
    out.setdefault('code', None)
    out.setdefault('area', None)
    return out


def _cards(data):
    layers = {layer: {d: 0 for d in DISPOSITIONS} for layer in LAYERS}
    for model in data['models']:
        layers[model['layer']][model['disp']] += 1
    files = data['files']
    sql = lambda status: sum(f['status'] == status and f['path'].endswith('.sql') for f in files)
    code = [f for f in files if file_kind(f['path']) == 'dbt']
    shared = {m['id'] for m in data['models'] if m['layer'] != 'bronze' and m['domain'] != data['meta']['domain']}
    legacy = collections.Counter(row['status'] for row in data['legacy'])
    decisions = collections.Counter(row['status'] for row in data['decisions'])
    dashboards = collections.Counter(row['status'] for row in data['dashboards'])
    return {'layers': layers,
            'code': {'new': sum(f['status'] == 'new' for f in code), 'changed': sum(f['status'] == 'changed' for f in code),
                     'new_sql': sql('new'), 'changed_sql': sql('changed')},
            'semantic': {'topics': len(data['topics']), 'views': sum(file_kind(f['path']) == 'view' for f in files),
                         'relationships': data['semantic_relationships'],
                         'cross_domain_topics': sum(t['base'] in shared for t in data['topics'])},
            'legacy': {s: legacy[s] for s in LEGACY_STATUSES}, 'legacy_total': len(data['legacy']),
            'decisions': {s: decisions[s] for s in DECISION_STATUSES},
            'dashboards': {s: dashboards[s] for s in DASHBOARD_STATUSES}}


def _reading_order(data):
    areas = [a['name'] for a in data['areas'] if not a.get('shared')][:2]
    opened = sum(d['status'] == 'open' for d in data['decisions'])
    order = [{'view': None, 'label': 'The banner above and "Not done yet" below', 'text': 'what this is and is not'},
             {'view': 'decisions', 'label': 'Decisions',
              'text': f'start with the {opened} open decision{"s" if opened != 1 else ""}, then the assumed ones'}]
    if areas:
        order.append({'view': 'model', 'label': 'Data model', 'text': 'pipeline and relationships per subject area, starting with '
                      + ' and '.join(areas) + '; click any table for grain, keys, columns, lineage and code'})
    if data['legacy']:
        order.append({'view': 'legacy', 'label': 'Legacy coverage', 'text': 'every legacy model behind the dashboards and what replaces it'})
    order.append({'view': 'code', 'label': 'Code & files', 'text': 'files to apply, source tables to add and placeholders to replace'})
    order.append({'view': 'valid', 'label': 'Validation and open items', 'text': 'static checks, remaining unknowns and who answers what'})
    return order


def normalise(data):
    """Validate page data, fill neutral defaults and derive every count. Returns a new object."""
    require(isinstance(data, dict) and data.get('schema_version') == SCHEMA_VERSION and data.get('kind') == KIND,
            'Domain review page data must declare kind domain_review_page and schema_version 1')
    data = json.loads(json.dumps(data, allow_nan=False))
    meta = data.get('meta')
    require(isinstance(meta, dict), 'meta must be an object')
    _text(meta.get('title'), 'meta.title', empty=False)
    domain = _text(meta.get('domain'), 'meta.domain', empty=False)
    meta.setdefault('domain_label', human(domain))
    meta.setdefault('brand', meta['title'])
    meta.setdefault('subtitle', 'domain review')
    meta.setdefault('scope_label', meta['domain_label'][:1].upper() + meta['domain_label'][1:] + ' domain')
    meta.setdefault('banner', DEFAULT_BANNER)
    meta['facts'] = [_text(x, 'meta.facts') for x in _list(meta.get('facts') or [], 'meta.facts')]
    repos = _list(meta.get('repositories') or [], 'meta.repositories')
    for repo in repos:
        require(isinstance(repo, dict) and isinstance(repo.get('role'), str) and isinstance(repo.get('name'), str),
                'Repositories need a role and a name')
        for key in ('commit', 'fingerprint'):
            require(repo.get(key) is None or (isinstance(repo[key], str) and re.fullmatch(r'[0-9a-f]{7,64}', repo[key])),
                    'Repository ' + key + ' must be hexadecimal or null')
        repo.setdefault('commit', None); repo.setdefault('fingerprint', None); repo.setdefault('complete', True)
    meta['repositories'] = repos
    meta['code_target'] = dict(meta.get('code_target') or {})
    meta['semantic_target'] = dict(meta.get('semantic_target') or {})
    meta.setdefault('access_note', '')

    models = [_model(row) for row in _list(data.get('models'), 'models')]
    by_id = {m['id']: m for m in models}
    require(len(by_id) == len(models), 'Model IDs must be unique')
    for model in models:
        require(all(d in by_id for d in model['dep']), 'Model depends on an absent model: ' + model['id'])
        model['used'] = []
    for model in models:
        for dep in model['dep']:
            by_id[dep]['used'].append(model['id'])

    rels = _list(data.get('rels') or [], 'rels')
    for rel in rels:
        require(isinstance(rel, dict) and rel.get('from') in by_id and rel.get('to') in by_id,
                'Relationship endpoints must be models in this review')
        rel.setdefault('card', ''); rel.setdefault('key', '')

    areas = _list(data.get('areas') or [], 'areas')
    _unique([dict(a, id=a.get('id')) for a in areas], 'id', 'Area')
    for area in areas:
        _text(area.get('id'), 'Area id', empty=False); _text(area.get('name'), 'Area name', empty=False)
        area['shared'] = bool(area.get('shared'))
        gold = _list(area.get('gold') or [], 'Area gold')
        require(all(g in by_id and by_id[g]['layer'] == 'gold' for g in gold), 'Area gold tables must be gold models: ' + area['id'])
        if area['shared']:
            area['pipeline'] = []
        elif 'pipeline' not in area:
            area['pipeline'] = sorted(set(gold).union(*[_upstream(by_id, g) for g in gold]))
        require(all(p in by_id for p in area['pipeline']), 'Area pipeline references an absent model: ' + area['id'])
        require(area['shared'] or set(gold) <= set(area['pipeline']), 'Area pipeline must include its gold tables: ' + area['id'])
        if 'erd' not in area:
            own = set(gold)
            area['erd'] = sorted(own | {x for r in rels if r['from'] in own or r['to'] in own for x in (r['from'], r['to'])})
        require(all(x in by_id for x in area['erd']), 'Area relationship view references an absent model: ' + area['id'])
        for member in area['pipeline']:
            if by_id[member]['area'] is None:
                by_id[member]['area'] = area['id']
    area_ids = {a['id'] for a in areas}
    for model in models:
        require(model['area'] is None or model['area'] in area_ids, 'Model area is not declared: ' + model['id'])

    files = _list(data.get('files') or [], 'files')
    for row in files:
        safe_relative(row.get('path'))
        require(row.get('status') in FILE_STATUSES and isinstance(row.get('content'), str), 'Files need new|changed status and text content')
        row['kind'] = file_kind(row['path'])
    paths = _unique(files, 'path', 'File')
    for model in models:
        require(model['code'] is None or model['code'] in paths, 'Model code file is not packaged: ' + model['id'])

    dashboards = _list(data.get('dashboards') or [], 'dashboards')
    topics = _list(data.get('topics') or [], 'topics')
    topic_ids = _unique(topics, 'topic', 'Topic')
    for row in dashboards:
        require(row.get('status') in DASHBOARD_STATUSES, 'Dashboard status must be served, partly_served or not_served')
        _text(row.get('asset_id'), 'Dashboard asset_id', empty=False); _text(row.get('title'), 'Dashboard title')
        row.setdefault('asset_type', 'dashboard'); row.setdefault('reason', ''); row.setdefault('scope_reason', '')
        row['topics'] = _list(row.get('topics') or [], 'Dashboard topics')
        require(set(row['topics']) <= topic_ids, 'Dashboard maps to an unknown topic: ' + row['asset_id'])
        for key in ('n_query_tiles', 'n_served', 'n_partly_served', 'n_not_served'):
            row.setdefault(key, None)
    for topic in topics:
        _text(topic.get('label'), 'Topic label', empty=False); _text(topic.get('base'), 'Topic base view', empty=False)
        require(topic.get('area') in area_ids, 'Topic area is not declared: ' + topic['topic'])
        for key in ('path', 'group', 'desc', 'ai'):
            topic[key] = topic.get(key) or ''
        topic['joins'] = _list(topic.get('joins') or [], 'Topic joins')
        for join in topic['joins']:
            require(isinstance(join.get('depth'), int) and join['depth'] >= 1, 'Topic join depth must be a positive integer')
            join.setdefault('card', ''); join.setdefault('on', '')
        topic['views'] = _list(topic.get('views') or [], 'Topic views')
        topic['fields'] = _list(topic.get('fields') or [], 'Topic fields')
        topic['view_files'] = dict(topic.get('view_files') or {})
        if 'dashboards' not in topic:
            topic['dashboards'] = [{'id': d['asset_id'], 'title': d['title'], 'status': d['status']}
                                   for d in dashboards if topic['topic'] in d['topics']]

    decisions = _list(data.get('decisions') or [], 'decisions')
    _unique(decisions, 'id', 'Decision')
    for row in decisions:
        require(row.get('status') in DECISION_STATUSES, 'Decision status must be answered, assumed or open: ' + str(row.get('id')))
        row.setdefault('area', 'General'); row.setdefault('q', ''); row.setdefault('assumed', ''); row.setdefault('detail', '')
        row['opts'] = _list(row.get('opts') or [], 'Decision options')
        row['models'] = [m for m in _list(row.get('models') or [], 'Decision models')]
        require(set(row['models']) <= set(by_id), 'Decision references an absent model: ' + row['id'])
    legacy = _list(data.get('legacy') or [], 'legacy')
    for row in legacy:
        require(row.get('status') in LEGACY_STATUSES, 'Unknown legacy status: ' + str(row.get('status')))
        _text(row.get('legacy'), 'Legacy model', empty=False)
        row['targets'] = _list(row.get('targets') or [], 'Legacy targets')
        require(set(row['targets']) <= set(by_id), 'Legacy target is not a model in this review: ' + row['legacy'])
        require(row['status'] in ('out of domain', 'unresolved') or row['targets'], 'Covered legacy models need a target: ' + row['legacy'])
        for key in ('topics', 'cross_topics'):
            row[key] = _list(row.get(key) or [], 'Legacy ' + key)
        for key in ('source', 'note', 'domain'):
            row[key] = row.get(key) or ''

    static = _list(data.get('static') or [], 'static')
    for row in static:
        _text(row.get('label'), 'Static check label', empty=False)
        require(isinstance(row.get('count'), int) and row['count'] >= 0, 'Static check count must be a non-negative integer')
        row.setdefault('of', ''); row['items'] = [str(x) for x in _list(row.get('items') or [], 'Static check items')]
    checks = _list(data.get('checks') or [], 'checks')
    for row in checks:
        require(row.get('status') in CHECK_STATUSES, 'Unknown check status: ' + str(row.get('status')))
        _text(row.get('label'), 'Check label', empty=False)
        for key in ('id', 'scope', 'expected', 'actual', 'details'):
            row[key] = str(row.get(key) or '')
    remaining = [_text(x, 'remaining') for x in _list(data.get('remaining') or [], 'remaining')]
    opened = _list(data.get('open') or [], 'open')
    for row in opened:
        for key in ('kind', 'id', 'text'):
            _text(row.get(key), 'Open item ' + key, empty=False)
        row['owner'] = row.get('owner') or 'Not assigned'
        row['meanwhile'] = row.get('meanwhile') or ''
    apply = dict(data.get('apply') or {})
    apply['new_sources'] = sorted({_text(x, 'Source table') for x in _list(apply.get('new_sources') or [], 'new_sources')})
    placeholders = _list(apply.get('placeholders') or [], 'placeholders')
    for row in placeholders:
        require(row.get('file') in paths and isinstance(row.get('line'), int), 'Placeholder must point at a packaged file and line')
        row['text'] = _text(row.get('text'), 'Placeholder text')
        row.setdefault('label', placeholder_label(row['text']))
        row['kind'] = file_kind(row['file'])
    apply['placeholders'] = placeholders
    relationships = data.get('semantic_relationships')
    require(relationships is None or (isinstance(relationships, int) and relationships >= 0), 'semantic_relationships must be a count')

    page = {'schema_version': SCHEMA_VERSION, 'kind': KIND, 'meta': meta, 'models': models, 'rels': rels,
            'areas': areas, 'topics': topics, 'files': files, 'decisions': decisions, 'legacy': legacy,
            'dashboards': dashboards, 'static': static, 'checks': checks, 'remaining': remaining, 'open': opened,
            'apply': apply, 'semantic_relationships': relationships if relationships is not None else len(rels),
            'notes': {'decisions': (data.get('notes') or {}).get('decisions') or DECISION_NOTE,
                      'validation': (data.get('notes') or {}).get('validation') or VALIDATION_NOTE}}
    page['reading_order'] = _list(data.get('reading_order') or _reading_order(page), 'reading_order')
    for row in page['reading_order']:
        require(isinstance(row, dict) and isinstance(row.get('label'), str) and row.get('view') in VIEWS + (None,),
                'Reading order entries need a label and an optional view: ' + ', '.join(VIEWS))
        row.setdefault('text', '')
    page['not_done'] = [_text(x, 'not_done') for x in _list(
        data.get('not_done') or (remaining + ['Design review and sign-off.']), 'not_done')]
    page['cards'] = _cards(page)
    return page


def _encode(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
            .replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))


def render(data):
    """Return START_HERE.html for page data. The page is validated before it is returned."""
    page = normalise(data)
    template = (ASSETS / 'domain-review.html').read_text(encoding='utf-8')
    for token in TEMPLATE_TOKENS:
        require(template.count(token) == 1, 'Domain review template is missing ' + token)
    rendered = (template.replace('__TITLE__', html.escape(page['meta']['title']))
                .replace('__BRAND__', html.escape(page['meta']['brand']))
                .replace('/*__DOMAIN_REVIEW_CSS__*/', (ASSETS / 'domain-review.css').read_text(encoding='utf-8'))
                .replace('/*__DOMAIN_REVIEW_DATA__*/', _encode(page))
                .replace('/*__DOMAIN_REVIEW_JS__*/', (ASSETS / 'domain-review.js').read_text(encoding='utf-8')))
    check_page(rendered)
    return rendered


def page_data(html_text):
    match = re.search(r'<script type="application/json" id="domain-review-data">(.*?)</script>', html_text, re.S)
    require(match is not None, 'Page has no domain review data block')
    return json.loads(match.group(1))


def check_page(html_text):
    """Structural check of a rendered page: one data block that passes the contract, no open tokens."""
    require(isinstance(html_text, str) and len(html_text.encode('utf-8')) <= MAX_PAGE_BYTES, 'Page exceeds its byte limit')
    require("http-equiv=\"Content-Security-Policy\"" in html_text and "connect-src 'none'" in html_text,
            'Page must keep its offline Content-Security-Policy')
    require(not any(token in html_text for token in TEMPLATE_TOKENS), 'Page has unreplaced template tokens')
    require(html_text.count('id="domain-review-data"') == 1, 'Page must embed exactly one data block')
    require(not re.search(r'<script[^>]+src=|<link[^>]+href=', html_text, re.I), 'Page must not load external resources')
    page = normalise(page_data(html_text))
    require(page['cards'] == page_data(html_text)['cards'], 'Embedded counts differ from the data they summarise')
    return {'status': 'pass', 'models': len(page['models']), 'topics': len(page['topics']),
            'dashboards': len(page['dashboards']), 'files': len(page['files'])}


def _mermaid_name(value):
    return re.sub(r'[^A-Za-z0-9_]', '_', value)


def area_mermaid(page, area):
    """erDiagram source for one subject area: its gold tables, related tables and key columns."""
    cards = {'many_to_one': '}o--||', 'one_to_one': '||--||', 'one_to_many': '||--o{', 'many_to_many': '}o--o{'}
    models = {m['id']: m for m in page['models']}
    ids, gold = set(area['gold']) | set(area['erd']), set(area['gold'])
    lines = ['%% ' + area['name'] + ': gold tables and their relationships', 'erDiagram']
    for rel in page['rels']:
        if rel['from'] in ids and rel['to'] in ids and (rel['from'] in gold or rel['to'] in gold or area['shared']):
            label = (rel['key'] or human(rel['card']) or 'relates to').replace('"', "'")
            lines.append(f'    {_mermaid_name(rel["from"])} {cards.get(rel["card"], "}o--||")} {_mermaid_name(rel["to"])} : "{label}"')
    for model_id in sorted(ids):
        lines.append(f'    {_mermaid_name(model_id)} {{')
        for name, kind, key, _ in models[model_id]['cols']:
            if key:
                lines.append(f'        {_mermaid_name(kind or "STRING")} {_mermaid_name(name)} {key}')
        lines.append('    }')
    return '\n'.join(lines) + '\n'


def start_here_markdown(page):
    c, meta = page['cards'], page['meta']
    layer = lambda name: f"{name} {c['layers'][name]['create']} new, {c['layers'][name]['extend']} changed, {c['layers'][name]['reuse']} reused"
    ds, lg, dc = c['dashboards'], c['legacy'], c['decisions']
    lines = ['# ' + meta['title'], '',
             'Open `../START_HERE.html` for the full review (data model, code, decisions, legacy coverage, dictionary, '
             'validation, open items). This file is the short written version.', '', 'Status: ' + meta['banner'], '', '## In numbers', '']
    if page['dashboards']:
        lines.append(f"- {len(page['dashboards'])} dashboards in scope: {ds['served']} served, {ds['partly_served']} partly served, {ds['not_served']} not served.")
    lines += [f"- {len(page['models'])} models in scope: {layer('gold')}; {layer('silver')}; {layer('bronze')}.",
              f"- Code files to apply: {c['code']['new']} new, {c['code']['changed']} changed. Semantic layer: {c['semantic']['topics']} topics, "
              f"{c['semantic']['views']} views, {c['semantic']['relationships']} relationships."]
    if page['legacy']:
        lines.append(f"- Legacy models accounted for: {c['legacy_total']} (" + ', '.join(f'{k} {v}' for k, v in lg.items()) + ').')
    lines += [f"- Decisions: {sum(dc.values())} (answered {dc['answered']}, assumed {dc['assumed']}, open {dc['open']}). Open items: {len(page['open'])}.",
              '', '## Subject areas', '']
    lines += [f"- **{a['name']}** ({len(a['gold'])} gold tables): diagram `erd/{a['id']}.mmd`." for a in page['areas']]
    lines += ['', '## Read in this order', '']
    lines += [f"{i}. {r['label']}{': ' + r['text'] if r['text'] else ''}." for i, r in enumerate(page['reading_order'], 1)]
    lines += ['', '## Not done yet', ''] + ['- ' + x for x in page['not_done']]
    lines += ['', '## Where things are', '',
              f"- `{LAYOUT['code']}/`: warehouse code. `{LAYOUT['semantic']}/`: semantic-layer files.",
              f"- `{LAYOUT['docs']}/`: design documents, registers, model files and validation evidence.",
              '- `MANIFEST.csv`: every file with its size and SHA-256.']
    return '\n'.join(lines) + '\n'


def _docs_from_directory(root):
    """Regular files under a documents folder, keyed by relative path. Links are not followed."""
    root = Path(root).resolve()
    require(root.is_dir(), 'Documents folder must be a directory')
    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if name.startswith('.') or path.is_symlink() or not path.is_file():
                continue
            out[path.relative_to(root).as_posix()] = path.read_bytes()
    require(len(out) <= MAX_ITEMS, 'Too many documents; partition the review')
    return out


def write_package(data, output, *, docs=None, scan=True):
    """Write a new review version folder. Refuses to overwrite; writes atomically via a sibling temp folder."""
    page = normalise(data)
    output = Path(output)
    require(output.parent.is_dir(), 'Output parent must exist')
    require(not output.exists(), 'Output exists; choose a new version folder')
    contents = {}
    for row in page['files']:
        require(row['path'].startswith((LAYOUT['code'] + '/', LAYOUT['semantic'] + '/')),
                f"Packaged code must live under {LAYOUT['code']}/ or {LAYOUT['semantic']}/: " + row['path'])
        contents[row['path']] = row['content'].encode('utf-8')
    for relative, value in sorted((docs or {}).items()):
        safe_relative(relative)
        target = LAYOUT['docs'] + '/' + relative
        require(target not in contents, 'Duplicate packaged path: ' + target)
        contents[target] = value if isinstance(value, bytes) else str(value).encode('utf-8')
    contents[LAYOUT['review'] + '/START_HERE.md'] = start_here_markdown(page).encode('utf-8')
    for area in page['areas']:
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}', area['id']) is not None, 'Area id is not a safe file name: ' + area['id'])
        contents[f"{LAYOUT['review']}/erd/{area['id']}.mmd"] = area_mermaid(page, area).encode('utf-8')
    contents['START_HERE.html'] = render(page).encode('utf-8')
    if scan:
        from sensitive_data import scan_bytes
        for name, content in sorted(contents.items()):
            report = scan_bytes(content, name)
            if report['status'] == 'unsupported':
                # Text formats the scanner has no parser for (for example DBML) are scanned as plain text.
                try:
                    content.decode('utf-8')
                except UnicodeDecodeError:
                    pass
                else:
                    report = scan_bytes(content, name + '.txt')
            require(report['status'] == 'clear', 'Disclosure scan blocked ' + name + ': ' + report['status']
                    + '. Inspect the value-free findings; do not rewrite source logic to hide a finding.')
    rows = sorted((name, len(content), hashlib.sha256(content).hexdigest()) for name, content in contents.items())
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(['path', 'bytes', 'sha256'])
    writer.writerows(rows)
    contents['MANIFEST.csv'] = buffer.getvalue().encode('utf-8')
    temp = Path(tempfile.mkdtemp(prefix='.' + output.name + '.', dir=output.parent))
    try:
        for name, content in contents.items():
            target = temp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        os.rename(temp, output)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return {'output': str(output), 'entrypoint': str(output / 'START_HERE.html'), 'files': len(contents),
            'manifest': str(output / 'MANIFEST.csv')}


def verify_package(folder):
    """Every manifest row matches its file and every file is listed."""
    folder = Path(folder)
    rows = list(csv.DictReader((folder / 'MANIFEST.csv').read_text(encoding='utf-8').splitlines()))
    listed = {row['path'] for row in rows}
    present = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()} - {'MANIFEST.csv'}
    require(listed == present, 'Manifest and folder differ')
    for row in rows:
        content = (folder / row['path']).read_bytes()
        require(len(content) == int(row['bytes']) and hashlib.sha256(content).hexdigest() == row['sha256'],
                'File changed after packaging: ' + row['path'])
    check_page((folder / 'START_HERE.html').read_text(encoding='utf-8'))
    return {'status': 'pass', 'files': len(rows)}


# ---------------------------------------------------------------- projection from a checked review

def _yaml(text):
    if yaml is None:
        return None
    try:
        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - parse failures are reported by static_checks
        return None


def _flatten_joins(joins, parent, depth=1):
    out = []
    if isinstance(joins, dict):
        for name, children in joins.items():
            out.append((parent, str(name), depth))
            out.extend(_flatten_joins(children, str(name), depth + 1))
    elif isinstance(joins, list):
        for item in joins:
            out.extend(_flatten_joins(item if isinstance(item, dict) else {item: None}, parent, depth))
    return out


def semantic_from_files(files, models):
    """Topics, view bindings and relationships from packaged semantic files.

    A view binds to a model only when its declared ``table_name`` equals the model id; an unbound
    view keeps its view name, so missing bindings stay visible instead of being guessed.
    """
    views, view_files, relationships, topics = {}, {}, [], []
    for row in files:
        kind, name = file_kind(row['path']), PurePosixPath(row['path']).name.split('.')[0]
        doc = _yaml(row['content']) if kind in ('view', 'topic', 'relationships') else None
        if kind == 'view':
            view_files[name] = row['path']
            table = doc.get('table_name') if isinstance(doc, dict) else None
            views[name] = table if table in models else name
        elif kind == 'relationships' and isinstance(doc, list):
            relationships.extend(r for r in doc if isinstance(r, dict))
    rel_index = {}
    for rel in relationships:
        pair = (rel.get('join_from_view'), rel.get('join_to_view'))
        rel_index[pair] = rel
        rel_index.setdefault(pair[::-1], dict(rel, reversed=True))
    for row in files:
        if file_kind(row['path']) != 'topic':
            continue
        name = PurePosixPath(row['path']).name.split('.')[0]
        doc = _yaml(row['content'])
        doc = doc if isinstance(doc, dict) else {}
        base_view = doc.get('base_view') or name
        joins = []
        for parent, child, depth in _flatten_joins(doc.get('joins') or {}, base_view):
            rel = rel_index.get((parent, child), {})
            joins.append({'from': views.get(parent, parent), 'to': views.get(child, child), 'depth': depth,
                          'card': str(rel.get('relationship_type') or ''),
                          'on': re.sub(r'\$\{|\}', '', str(rel.get('on_sql') or ''))})
        bound = [views.get(base_view, base_view)] + [j['to'] for j in joins]
        topics.append({'topic': name, 'label': str(doc.get('label') or human(name).title()), 'base': views.get(base_view, base_view),
                       'path': row['path'], 'group': str(doc.get('group_label') or ''), 'desc': str(doc.get('description') or ''),
                       'ai': str(doc.get('ai_context') or ''), 'joins': joins,
                       'views': sorted(set(bound)), 'fields': [str(f) for f in doc.get('fields') or []],
                       'view_files': {v: view_files[v] for v in [base_view] + [c for _, c, _ in _flatten_joins(doc.get('joins') or {}, base_view)] if v in view_files}})
    return topics, views, relationships


def static_checks(files, model_ids, known_models=(), views=None, relationships=()):
    """Supplemental file checks. They prove syntax and reference closure only, never execution."""
    if yaml is None:
        return [{'label': 'YAML syntax not checked', 'count': 1, 'of': 'Optional YAML parser unavailable', 'items': []}]
    parsed, documented = [], set()
    yaml_files = [f for f in files if f['path'].endswith(('.yml', '.yaml', '.view', '.topic')) or file_kind(f['path']) == 'relationships']
    errors = []
    for row in yaml_files:
        try:
            doc = yaml.safe_load(row['content'])
        except Exception:  # noqa: BLE001
            errors.append(row['path']); continue
        parsed.append((row, doc))
        if isinstance(doc, dict) and isinstance(doc.get('models'), list):
            documented |= {m.get('name') for m in doc['models'] if isinstance(m, dict)}
    sql = [f for f in files if f['path'].endswith('.sql') and '/models/' in f['path']]
    stems = {PurePosixPath(f['path']).stem for f in sql}
    known = set(model_ids) | set(known_models) | stems
    undocumented = sorted(f['path'] for f in sql if PurePosixPath(f['path']).stem not in documented | set(known_models))
    unresolved = sorted({r for f in sql for r in REF.findall(f['content']) if r not in known})
    views = views or {}
    broken_fields = sorted({f"{row['path']}: {view}" for row, _ in parsed if file_kind(row['path']) in ('view', 'topic')
                            for view, _ in FIELD.findall(row['content']) if view not in views})
    broken_rels = sorted({f"{r.get('join_from_view')} → {r.get('join_to_view')}" for r in relationships
                          if r.get('join_from_view') not in views or r.get('join_to_view') not in views})
    n_sem = sum(file_kind(f['path']) in ('view', 'topic') for f in files)
    return [{'label': 'YAML errors', 'count': len(errors), 'of': f'{len(yaml_files)} YAML and semantic files parsed', 'items': errors},
            {'label': 'Models without YAML', 'count': len(undocumented), 'of': f'{len(sql)} packaged SQL models', 'items': undocumented},
            {'label': 'Unresolved refs', 'count': len(unresolved), 'of': f'{len(sql)} SQL models, checked against this review'
             + (' and the supplied base project' if known_models else ''), 'items': unresolved},
            {'label': 'Broken semantic field references', 'count': len(broken_fields), 'of': f'{n_sem} views and topics', 'items': broken_fields},
            {'label': 'Broken semantic relationships', 'count': len(broken_rels), 'of': f'{len(relationships)} relationships', 'items': broken_rels}]


def _disposition(model):
    for key in ('disposition', 'status'):
        value = DISPOSITION_ALIASES.get(str(model.get(key) or '').lower())
        if value:
            return value
    raise ValueError('Model needs a disposition (create, extend or reuse): ' + str(model.get('id')))


def _key(column):
    key = str(column.get('key') or '').lower()
    return 'PK' if key in ('primary', 'pk', 'primary_key') else 'FK' if key in ('foreign', 'fk', 'foreign_key') else ''


def _relationship(edge):
    card = edge.get('cardinality') or ''
    key = ''
    if edge.get('from_columns') and edge.get('to_columns'):
        key = ', '.join(edge['from_columns']) + ' = ' + ', '.join(edge['to_columns'])
    else:
        match = re.fullmatch(r'\s*(.+?=.+?)\s*(?:\((\w+)\))?\s*', str(edge.get('label') or ''))
        if match:
            key, card = match.group(1).strip(), card or (match.group(2) or '')
    return {'from': edge['from'], 'to': edge['to'], 'card': card, 'key': key}


def _owning_domain(review, domain):
    if domain:
        return domain
    counts = collections.Counter(m.get('domain') for m in review.get('models', []) if m.get('layer') == 'gold')
    require(counts, 'Name the domain: the review has no gold models')
    return counts.most_common(1)[0][0]


def _areas(review, models, domain, overlay):
    declared = overlay.get('areas') or review.get('subject_areas')
    if declared:
        areas = []
        for row in declared:
            gold = row.get('gold') or [m['id'] for m in models.values() if m['layer'] == 'gold' and m.get('area') == row['id']]
            areas.append({k: v for k, v in dict(row, gold=sorted(gold)).items() if k in ('id', 'name', 'gold', 'shared', 'pipeline', 'erd')})
        placed = {g for a in areas for g in a['gold']}
        missing = sorted(m['id'] for m in models.values() if m['layer'] == 'gold' and m['id'] not in placed)
        if missing:
            areas.append({'id': 'unassigned', 'name': 'Not assigned to a subject area', 'gold': missing})
        return areas
    own = sorted(m['id'] for m in models.values() if m['layer'] == 'gold' and m['domain'] == domain)
    other = sorted(m['id'] for m in models.values() if m['layer'] == 'gold' and m['domain'] != domain)
    areas = [{'id': re.sub(r'[^A-Za-z0-9_.-]', '_', domain), 'name': human(domain).capitalize(), 'gold': own}]
    if other:
        areas.append({'id': 'shared', 'name': 'Shared interfaces (other domains)', 'gold': other, 'shared': True})
    return areas


def _dashboards(review, overlay):
    out, details = [], overlay.get('dashboards') or {}
    for asset in review.get('assets', []):
        status = asset.get('coverage_status') or asset.get('mapping_status')
        if status == 'out_of_scope':
            continue
        require(status in DASHBOARD_STATUSES, 'Dashboard has no coverage status (served, partly_served, not_served or out_of_scope): ' + asset['id'])
        extra = details.get(asset['id'], {})
        kind = str(asset.get('kind') or '')
        number = re.search(r'(\d+)$', asset['id'])
        row = {'asset_type': 'look' if 'look' in kind and 'dashboard' not in kind else 'dashboard',
               'asset_id': str(asset.get('asset_id') or (number.group(1) if number else asset['id'])),
               'title': re.sub(r'^\w+ \d+:\s*', '', asset.get('name') or asset['id']), 'status': status,
               'topics': asset.get('topics') or [], 'reason': asset.get('coverage_reason') or ''}
        row.update({k: v for k, v in extra.items() if k in ('asset_type', 'asset_id', 'title', 'topics', 'reason', 'scope_reason',
                                                             'n_query_tiles', 'n_served', 'n_partly_served', 'n_not_served')})
        out.append(row)
    return out


def _legacy(review, models):
    rows = review.get('legacy_coverage')
    if rows is not None:
        return [dict(row) for row in rows]
    out = []
    for change in review.get('changes', []):
        status = LEGACY_FROM_DISPOSITION.get(change.get('disposition'))
        require(status is not None, 'Change has no legacy coverage mapping: ' + str(change.get('id')))
        targets = change.get('model_ids') or [t.strip() for t in str(change.get('target') or '').split(',') if t.strip() in models]
        targets = [t for t in targets if t in models]
        if status in ('covered', 'retire candidate', 'partially covered') and not targets:
            status = 'unresolved'
        out.append({'legacy': re.sub(r'^\w+:\s*', '', str(change.get('source') or change['id'])), 'source': str(change.get('source') or ''),
                    'status': status, 'targets': targets, 'note': str(change.get('rationale') or '')})
    return out


def project(review, files, *, domain=None, overlay=None, known_models=()):
    """Page data from a checked review and its packaged code files.

    ``files`` is a list of ``{path, status, content}`` with paths already in the review layout
    (``02_dbt/...``, ``03_omni/...``). ``overlay`` carries authored presentation fields that the
    review does not hold (meta, areas, dashboards details, reading order, remaining, open items).
    """
    overlay = dict(overlay or {})
    require(isinstance(review, dict), 'Review must be an object')
    domain = _owning_domain(review, domain or (overlay.get('meta') or {}).get('domain'))
    review_meta = review.get('review_meta') or {}
    by_path = {f['path']: f for f in files}
    sql_by_stem = {PurePosixPath(p).stem: p for p in by_path if p.endswith('.sql')}
    models = {}
    for row in review.get('models', []):
        model_id = row['id']
        code = sql_by_stem.get(model_id) or sql_by_stem.get(row.get('name') or '')
        sources = row.get('sources')
        if sources is None and code:
            sources = sorted({f'{a}.{b}' for a, b in SOURCE.findall(by_path[code]['content'])})
        models[model_id] = {
            'id': model_id, 'layer': row['layer'], 'domain': row.get('domain') or domain, 'disp': _disposition(row),
            'type': row.get('entity_type') or model_type(model_id, row['layer']),
            'desc': row.get('description') or '', 'grain': row.get('grain') or '',
            'cols': [[c['name'], c.get('type') or c.get('data_type') or '', _key(c), c.get('description') or '']
                     for c in row.get('columns', [])],
            'dep': sorted(set(row.get('depends_on') or []) | {e['from'] for e in review.get('relationships', [])
                                                              if e.get('kind') == 'lineage' and e.get('to') == model_id and e.get('from') in
                                                              {m['id'] for m in review.get('models', [])}}),
            'src': sources or [], 'sec': row.get('security_notes') or ([row['security']] if row.get('security') else []),
            'code': code, 'source_path': row.get('source_path') or '', 'area': row.get('area')}
        if row.get('existing_source'):
            models[model_id]['existing'] = row['existing_source']
    rels = [_relationship(e) for e in review.get('relationships', []) if e.get('kind') == 'relationship'
            and e.get('from') in models and e.get('to') in models]
    areas = _areas(review, models, domain, overlay)
    topics, views, sem_rels = semantic_from_files(files, models)
    home = {}
    for area in areas:
        for gold in area['gold']:
            home.setdefault(gold, area['id'])
    for model in models.values():
        model['area'] = model['area'] if model['area'] in {a['id'] for a in areas} else None
    topic_areas = overlay.get('topic_areas') or {}
    for topic in topics:
        topic['area'] = topic_areas.get(topic['topic']) or home.get(topic['base'])
        if topic['area'] is None:
            if not any(a['id'] == 'unassigned' for a in areas):
                areas.append({'id': 'unassigned', 'name': 'Not assigned to a subject area', 'gold': []})
            topic['area'] = 'unassigned'
    dashboards = _dashboards(review, overlay)
    decisions, opened = [], []
    for row in review.get('decisions', []):
        status = DECISION_ALIASES.get(str(row.get('status') or '').lower())
        require(status is not None, 'Unknown decision status: ' + str(row.get('id')))
        decision = {'id': row['id'], 'area': row.get('area') or ('Open question' if status == 'open' else 'General'),
                    'q': row.get('question') or '', 'opts': row.get('options') or [],
                    'assumed': row.get('assumed_option') or row.get('answer') or '', 'status': status,
                    'detail': row.get('detail') or '', 'models': [m for m in row.get('model_ids') or [] if m in models]}
        decisions.append(decision)
        if status == 'open':
            opened.append({'kind': 'Question', 'id': row['id'], 'owner': row.get('owner') or 'Not assigned',
                           'text': decision['q'] or decision['area'],
                           'meanwhile': row.get('meanwhile') or ('Assumed: ' + decision['assumed'] if decision['assumed']
                                                                 else 'Nothing that depends on this is modelled until it is answered.')})
    checks = [{k: row.get(k, '') for k in ('id', 'label', 'scope', 'status', 'expected', 'actual', 'details')}
              for row in review.get('validation', [])]
    for row in checks:
        if row['status'] in ('fail', 'pending'):
            opened.append({'kind': 'Unverified', 'id': row['id'] or row['label'], 'owner': 'Not assigned',
                           'text': row['label'] + (': ' + row['actual'] if row['actual'] else ''), 'meanwhile': row['details']})
    legacy = _legacy(review, models)
    opened += [{'kind': 'Unresolved legacy model', 'id': r['legacy'], 'owner': 'Not assigned', 'text': r['note'] or 'No target yet.',
                'meanwhile': 'Not replaced in this delivery.'} for r in legacy if r['status'] == 'unresolved']
    opened += overlay.get('open') or []
    placeholders = [{'file': f['path'], 'line': i, 'text': line.strip()[:200]}
                    for f in files if file_kind(f['path']) in ('view', 'topic', 'relationships', 'model')
                    for i, line in enumerate(f['content'].splitlines(), 1) if 'TODO' in line]
    new_sources = sorted({s for m in models.values() if m['layer'] == 'bronze' and m['disp'] == 'create' for s in m['src']})
    target = review.get('target') or {}
    meta = {'title': review.get('title') or human(domain).capitalize() + ' data model review', 'domain': domain,
            'scope_label': review_meta.get('domain_position') or None, 'repositories': review_meta.get('repositories') or [],
            'facts': [f"{target['framework']} on {target['warehouse']}"] if target.get('framework') and target.get('warehouse') else []}
    meta = {k: v for k, v in meta.items() if v is not None}
    meta.update(overlay.get('meta') or {})
    meta['domain'] = domain
    data = {'schema_version': SCHEMA_VERSION, 'kind': KIND, 'meta': meta, 'models': list(models.values()), 'rels': rels,
            'areas': areas, 'topics': topics, 'files': [{k: f[k] for k in ('path', 'status', 'content')} for f in files],
            'decisions': decisions, 'legacy': legacy, 'dashboards': dashboards,
            'static': review.get('static_checks') or static_checks(files, models, known_models, views, sem_rels),
            'checks': checks, 'remaining': overlay.get('remaining') or review_meta.get('remaining') or [],
            'open': opened, 'apply': {'new_sources': new_sources, 'placeholders': placeholders},
            'semantic_relationships': len(sem_rels) if sem_rels else len(rels)}
    for key in ('reading_order', 'not_done', 'notes'):
        value = overlay.get(key) or (review_meta.get({'reading_order': 'read_order'}.get(key, key)))
        if value:
            data[key] = [{'view': None, 'label': x, 'text': ''} if isinstance(x, str) else x for x in value] if key == 'reading_order' else value
    return normalise(data)


def files_from_artifacts(review, root, path_map, *, changed=()):
    """Packaged files from the review's registered implementation artifacts.

    ``path_map`` maps artifact path prefixes to review layout prefixes, for example
    ``{"dbt/": "02_dbt/", "omni/": "03_omni/model/"}``. Each file's bytes must still match the
    registered SHA-256; ``changed`` lists artifact paths that replace an existing file.
    """
    root = Path(root).resolve()
    require(root.is_dir(), 'Artifact root must be a directory')
    require(path_map and all(isinstance(k, str) and isinstance(v, str) and v.startswith((LAYOUT['code'] + '/', LAYOUT['semantic'] + '/'))
                             for k, v in path_map.items()), f"Every path map target must start with {LAYOUT['code']}/ or {LAYOUT['semantic']}/")
    changed, out = set(changed), []
    for record in review.get('artifacts', []):
        if record.get('category') != 'implementation':
            continue
        relative = safe_relative(record['path'])
        prefix = next((k for k in sorted(path_map, key=len, reverse=True) if relative.startswith(k)), None)
        if prefix is None:
            continue
        source = (root / relative).resolve()
        require(source.is_relative_to(root) and source.is_file() and not (root / relative).is_symlink(), 'Artifact must be a regular file: ' + relative)
        content = source.read_bytes()
        require(hashlib.sha256(content).hexdigest() == record.get('sha256'), 'Artifact changed since the review: ' + relative)
        status = record.get('change_status') or ('changed' if relative in changed else 'new')
        require(status in FILE_STATUSES, 'Artifact change_status must be new or changed: ' + relative)
        out.append({'path': path_map[prefix] + relative[len(prefix):], 'status': status, 'content': content.decode('utf-8')})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('project', help='Derive page data from a checked review and its artifacts')
    p.add_argument('--review', required=True); p.add_argument('--artifacts', required=True)
    p.add_argument('--path-map', required=True, help='JSON object: artifact prefix -> review layout prefix')
    p.add_argument('--changed', help='Text file listing artifact paths that replace existing files')
    p.add_argument('--overlay', help='JSON with authored presentation fields (meta, areas, dashboards, ...)')
    p.add_argument('--known-models', help='Text file of model names that exist in the base project')
    p.add_argument('--domain'); p.add_argument('--output', required=True)
    p = sub.add_parser('render', help='Write START_HERE.html from page data')
    p.add_argument('--data', required=True); p.add_argument('--output', required=True)
    p = sub.add_parser('package', help='Write a new review version folder')
    p.add_argument('--data', required=True); p.add_argument('--output', required=True)
    p.add_argument('--docs', help='Folder copied into 04_docs/')
    p = sub.add_parser('verify', help='Check a review folder against its manifest and the page contract')
    p.add_argument('folder')
    p = sub.add_parser('check-page'); p.add_argument('page')
    args = parser.parse_args(argv)
    lines = lambda path: [x.strip() for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()] if path else []
    if args.command == 'project':
        review = load_json(args.review)
        files = files_from_artifacts(review, args.artifacts, json.loads(args.path_map), changed=lines(args.changed))
        page = project(review, files, domain=args.domain, overlay=load_json(args.overlay) if args.overlay else None,
                       known_models=lines(args.known_models))
        out = Path(args.output)
        require(not out.exists(), 'Output exists; choose a new file')
        out.write_text(json.dumps(page, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        result = {'output': str(out), 'models': len(page['models']), 'topics': len(page['topics']), 'dashboards': len(page['dashboards'])}
    elif args.command == 'render':
        out = Path(args.output)
        require(not out.exists(), 'Output exists; choose a new version')
        out.write_text(render(load_json(args.data, max_bytes=MAX_PAGE_BYTES)), encoding='utf-8')
        result = {'output': str(out)}
    elif args.command == 'package':
        result = write_package(load_json(args.data, max_bytes=MAX_PAGE_BYTES), args.output,
                               docs=_docs_from_directory(args.docs) if args.docs else None)
    elif args.command == 'verify':
        result = verify_package(args.folder)
    else:
        result = check_page(Path(args.page).read_text(encoding='utf-8'))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
