"""Bounded offline pages for large deliveries; original files stay byte-for-byte intact."""
import base64
import hashlib
import html
import json
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit, unquote

from ae_common import require

ROOT = '03_Design_Documents/Review'
QUALIFICATION = 'Candidate review. Native warehouse checks, Omni validation and business approval remain separate.'
CSS = '''
*{box-sizing:border-box}body{margin:0;font:18px/1.5 system-ui,sans-serif;color:#19354a;background:#f4f7fa}
nav{position:fixed;inset:0 auto 0 0;width:220px;padding:30px 20px;background:#143c47;color:white}
nav a{display:block;color:white;padding:12px 0;text-decoration:none}nav strong{display:block;margin-bottom:28px}
.review-section{margin-left:220px;max-width:1600px;padding:32px 40px}.detail .review-section{margin:0;max-width:none;padding:24px}
h1{font-size:32px;margin:0 0 12px}h2{font-size:25px}h3{font-size:21px}a{color:#006e79}button,select,input{font:inherit;padding:9px;border:1px solid #a5bac6;border-radius:6px;background:white;color:#19354a}button{cursor:pointer}button:focus-visible,a:focus-visible{outline:3px solid #c8643a}label{display:block;margin-bottom:5px}select{max-width:100%}.controls{display:flex;gap:18px;flex-wrap:wrap;margin:20px 0}.panel{padding:22px;background:white;border:1px solid #d4e0e7;border-radius:10px;margin:18px 0}.muted{color:#516879}.badge{display:inline-block;border-radius:4px;padding:3px 9px;background:#dff2ec}.diagram{overflow:auto;max-height:78vh;background:white;border:1px solid #d4e0e7}.diagram svg{max-width:none;display:block}.diagram [data-model-id]{cursor:pointer}iframe{width:100%;height:75vh;border:1px solid #d4e0e7;background:white;border-radius:8px}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #dce4e9;overflow-wrap:anywhere}th{background:#e7f1f5}pre{white-space:pre;overflow:auto;background:#102f3d;color:#edf7f9;padding:22px;border-radius:8px;font-size:16px}code{font-family:ui-monospace,monospace}.scroll{overflow:auto}dialog{width:min(950px,94vw);height:88vh;border:0;border-radius:12px;padding:16px}dialog iframe{height:calc(100% - 55px)}dialog::backdrop{background:#17384999}[hidden]{display:none!important}
@media(max-width:1000px){nav{position:static;width:auto;display:flex;gap:18px;flex-wrap:wrap;padding:15px}nav strong{margin:0}nav a{padding:0}.review-section{margin-left:0;padding:25px;max-width:none}}
@media(max-width:700px){.review-section,.detail .review-section{padding:16px}h1{font-size:27px}.controls{display:block}.controls>div{margin-bottom:12px}table{min-width:520px}iframe{height:72vh}}
'''

DETAIL_JS = ''''use strict';
const d=JSON.parse(document.getElementById('delivery-data').textContent);
document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',async()=>{
 const text=document.getElementById(b.dataset.copy).textContent;
 try{await navigator.clipboard.writeText(text);b.textContent='Copied';}catch(e){const r=document.createRange();r.selectNodeContents(document.getElementById(b.dataset.copy));const s=window.getSelection();s.removeAllRanges();s.addRange(r);b.textContent='Selected — copy with your keyboard';}
}));
const svg=document.querySelector('.diagram svg');let zoom=1;
document.querySelectorAll('[data-zoom]').forEach(b=>b.addEventListener('click',()=>{if(!svg)return;zoom=b.dataset.zoom==='reset'?1:Math.max(.4,Math.min(3,zoom+Number(b.dataset.zoom)));svg.style.width=Number(svg.getAttribute('width'))*zoom+'px';svg.style.height=Number(svg.getAttribute('height'))*zoom+'px';}));
if(svg)svg.querySelectorAll('[data-model-id]').forEach(n=>{n.setAttribute('tabindex','0');n.setAttribute('role','link');const open=()=>{const id=n.getAttribute('data-model-id');if(d.model_pages[id])location.href=d.model_pages[id];};n.addEventListener('click',open);n.addEventListener('keydown',e=>{if(e.key==='Enter')open();});});
'''

INDEX_JS = ''''use strict';
const d=JSON.parse(document.getElementById('delivery-data').textContent), byId=id=>document.getElementById(id);
function route(){const id=location.hash.slice(1)||'model';document.querySelectorAll('[data-section]').forEach(s=>s.hidden=s.id!==id);if(!['model','code','migration','validation',...(d.topic_coverage?['omni-topic-trees']:[])].includes(id)){location.hash='model';return;}document.querySelectorAll('nav a').forEach(a=>a.setAttribute('aria-current',a.hash==='#'+id?'page':'false'));}
window.addEventListener('hashchange',route);route();
const domain=byId('domain'),output=byId('output'),frame=byId('pipeline');
for(const name of d.domains){const o=document.createElement('option');o.value=name;o.textContent=name;domain.appendChild(o);}
function outputs(){output.replaceChildren();for(const p of d.pipelines.filter(p=>!domain.value||p.domain===domain.value)){const o=document.createElement('option');o.value=p.path;o.textContent=p.title;output.appendChild(o);}show();filterFiles();document.querySelectorAll('[data-table-domain]').forEach(r=>r.hidden=!!(domain.value&&r.dataset.tableDomain!==domain.value));}
function show(){frame.hidden=!output.value;if(output.value)frame.src=output.value;byId('empty').hidden=!!output.value;}
domain.addEventListener('change',outputs);output.addEventListener('change',show);outputs();
function filterFiles(){const q=byId('search').value.toLowerCase();document.querySelectorAll('[data-file]').forEach(r=>{r.hidden=(!r.textContent.toLowerCase().includes(q))||!!(domain.value&&r.dataset.domain&&r.dataset.domain!==domain.value);});}
byId('search').addEventListener('input',filterFiles);
const dialog=byId('inspector');document.querySelectorAll('[data-inspect]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();byId('table-frame').src=a.getAttribute('href');dialog.showModal();}));
byId('close-inspector').addEventListener('click',()=>dialog.close());
'''


def _encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def _page(title, content, data, *, index=False):
    script = INDEX_JS if index else DETAIL_JS
    if index and data.get('topic_coverage'):
        assets = Path(__file__).resolve().parent.parent / 'assets/guided-delivery'
        script += '\n' + (assets / 'portal-svg.js').read_text() + '\n' + (assets / 'topic-panel.js').read_text()
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    policy = "default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-" + digest + "'; frame-src 'self' file:; img-src data:; base-uri 'none'; form-action 'none'"
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="' + html.escape(policy, quote=True) + '">'
            '<title>' + html.escape(title) + '</title><style>' + CSS + '</style></head><body class="' + ('index' if index else 'detail') + '">'
            + content + '<script id="delivery-data" type="application/json">' + _encoded(data) + '</script><script>' + script + '</script></body></html>').encode()


def _link(origin, destination, label, **attrs):
    parts = urlsplit(destination)
    path = quote(posixpath.relpath(parts.path, posixpath.dirname(origin) or '.'), safe='/')
    if parts.fragment:
        path += '#' + quote(parts.fragment)
    extra = ''.join(' ' + k.replace('_', '-') + '="' + html.escape(str(v), quote=True) + '"' for k, v in attrs.items())
    return '<a href="' + path + '"' + extra + '>' + html.escape(str(label)) + '</a>'


def _table(headers, rows, domains=None):
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th>' + html.escape(h) + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr' + (' data-table-domain="' + html.escape(domains[i], quote=True) + '"' if domains else '') + '>' + ''.join('<td>' + str(c) + '</td>' for c in row) + '</tr>' for i, row in enumerate(rows)) + '</tbody></table></div>'


def should_partition(data):
    if data.get('package_layout_version') != 2 or data.get('audience') == 'audit':
        return False
    from sensitive_data import MAX_MEMBERS
    return (len(data.get('review', {}).get('models', [])) > 100 or len(data.get('files', [])) > 200
            or len(data.get('files', [])) + len(data.get('generated_deliverables', [])) + 3 > MAX_MEMBERS
            or len(_encoded(data).encode()) > 4 * 1024 * 1024)


def build(data, original_files):
    """Project one checked canonical review into bounded pages, with no filesystem reads."""
    from delivery_portal import _sha, _validate_svg
    files, page_roles = {}, {}
    models = data.get('review', {}).get('models', [])
    model_pages = {m['id']: ROOT + '/tables/' + _sha(m['id'].encode())[:24] + '.html' for m in models}
    artifacts = {r['id']: r for r in data.get('files', [])}
    code_pages = {}
    for record in data.get('files', []):
        if record['category'] != 'implementation':
            continue
        raw = original_files[record['path']]
        if PurePosixPath(record['path']).suffix.lower() in {'.pdf', '.docx', '.xlsx'}:
            continue
        try:
            source = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        path = ROOT + '/code/' + _sha(record['id'].encode())[:24] + '.html'
        code_pages[record['id']] = path
        content = '<section class="review-section"><p>' + _link(path, 'START_HERE.html#code', 'Back to delivery', target='_top') + '</p><h1>' + html.escape(record['path']) + '</h1><p>' + _link(path, record['path'], 'Open original file', download='') + '</p><button data-copy="source">Copy code</button><pre id="source">' + html.escape(source) + '</pre></section>'
        files[path] = _page(record['path'], content, {'kind': 'code_page', 'artifact_id': record['id'], 'source_sha256': record['sha256']})
        page_roles[path] = {'role': 'review_page', 'category': 'implementation'}
    for model in models:
        path = model_pages[model['id']]
        bound_ids = list(dict.fromkeys([model.get('artifact_id'), *model.get('artifact_ids', [])]))
        bound = [artifacts[key] for key in bound_ids if key in artifacts]
        code = ' · '.join(_link(path, code_pages.get(a['id'], a['path']), a['path']) for a in bound) if bound else 'No selected code binding supplied.'
        rows = [[html.escape(str(c.get(k, ''))) for k in ('name', 'type', 'key', 'description')] for c in model.get('columns', [])]
        dependencies = [_link(path, model_pages[p], p) if p in model_pages else html.escape(p) for p in model.get('depends_on', [])]
        content = '<section class="review-section"><p>' + _link(path, 'START_HERE.html#model', 'Back to delivery', target='_top') + '</p><h1 id="name">' + html.escape(model.get('name', model['id'])) + '</h1><button data-copy="name">Copy full name</button><p><span class="badge">' + html.escape(model.get('disposition', 'undetermined')) + '</span> · ' + html.escape(model.get('domain') or 'Unassigned') + ' · ' + html.escape(model['layer']) + '</p><p><b>Grain:</b> ' + html.escape(model.get('grain') or 'Unspecified') + '</p><p><b>Keys:</b> ' + html.escape(', '.join(model.get('keys', [])) or 'Unspecified') + '</p><p>' + code + '</p><h2>Columns</h2>' + (_table(['Name', 'Type', 'Key', 'Meaning'], rows) if rows else '<p>Column evidence not supplied.</p>') + '<h2>Upstream tables</h2><p>' + (' · '.join(dependencies) or 'No declared dependencies.') + '</p></section>'
        related = [r for r in data.get('review', {}).get('relationships', []) if model['id'] in (r['from'], r['to'])]
        context = '<h2>Relationships</h2>' + _table(['From', 'To', 'Kind', 'Declared detail'], [[html.escape(r['from']), html.escape(r['to']), html.escape(r['kind']), html.escape(json.dumps({k: v for k, v in r.items() if k not in {'from', 'to', 'kind'}}, ensure_ascii=False))] for r in related])
        context += '<p><b>Security:</b> ' + html.escape(str(model.get('security') or 'Unspecified')) + '</p><p><b>History:</b> ' + html.escape(str(model.get('history') or 'Unspecified')) + '</p>'
        content = content.replace('</section>', context + '</section>')
        files[path] = _page(model.get('name', model['id']), content, {'kind': 'table_page', 'model': model})
        page_roles[path] = {'role': 'review_page', 'category': 'documentation'}
    pipelines = []
    for n, diagram in enumerate(data.get('diagrams', []), 1):
        body = base64.b64decode(diagram['base64'], validate=True)
        _validate_svg(body)
        path = ROOT + '/pipelines/' + str(n).zfill(4) + '.html'
        links = {key: quote(posixpath.relpath(model_pages[key], posixpath.dirname(path)), safe='/') for key in diagram['model_ids'] if key in model_pages}
        title = diagram.get('title') or diagram.get('target_model_id') or 'Model pipeline'
        content = '<section class="review-section"><h1>' + html.escape(title) + '</h1><p>Read top to bottom. Select a table for columns, keys and code. Shapes represent declared dependencies; joins require separate validation.</p><div class="controls"><button data-zoom="0.2">Zoom in</button><button data-zoom="-0.2">Zoom out</button><button data-zoom="reset">Reset</button></div><div class="diagram">' + body.decode() + '</div></section>'
        files[path] = _page(title, content, {'kind': 'pipeline_page', 'model_pages': links, 'model_ids': diagram['model_ids']})
        page_roles[path] = {'role': 'review_page', 'category': 'diagrams'}
        target = next((m for m in models if m['id'] == diagram.get('target_model_id')), {})
        pipelines.append({'path': path, 'title': title, 'domain': target.get('domain') or diagram.get('domain') or 'Unassigned',
                          'target_model_id': diagram.get('target_model_id'), 'model_ids': diagram['model_ids']})
    topic_pages = []
    for diagram in data.get('topic_diagrams', []):
        from topic_visuals import STYLE
        raw = base64.b64decode(diagram['base64'], validate=True)
        _validate_svg(raw, trusted_styles=(STYLE,))
        path = ROOT + '/topics/' + _sha(diagram['id'].encode())[:24] + '.html'
        download = (_link(path, diagram['export_path'], 'Download SVG', download='') if diagram['export_path'] in original_files else '')
        content = '<section class="review-section"><p>' + download + '</p><div class="controls"><button data-zoom="0.2">Zoom in</button><button data-zoom="-0.2">Zoom out</button><button data-zoom="reset">Actual size</button></div><div class="diagram">' + raw.decode() + '</div></section>'
        files[path] = _page(diagram['name'], content, {'kind': 'topic_page', 'topic_id': diagram['id'], 'model_pages': {}})
        page_roles[path] = {'role': 'review_page', 'category': 'diagrams'}
        topic_pages.append({**{k:v for k,v in diagram.items() if k!='base64'}, 'page_path': path, 'download_available': diagram['export_path'] in original_files})
    inventory = [{k: v for k, v in r.items() if k != 'base64'} for r in data.get('files', []) + data.get('generated_deliverables', [])]
    compact = {'schema_version': 1, 'kind': 'partitioned_review', 'engagement': data['engagement'],
               'domains': sorted({p['domain'] for p in pipelines if p['target_model_id']}
                                 or {m.get('domain') or 'Unassigned' for m in models}), 'pipelines': pipelines,
               'models': [{'id': m['id'], 'name': m.get('name', m['id']), 'domain': m.get('domain') or 'Unassigned', 'path': model_pages[m['id']]} for m in models],
               'files': inventory, 'selected_categories': data['selected_categories'],
               'model_count': len(models), 'file_count': len(inventory), 'qualification': QUALIFICATION,
               'checkpoint': data.get('checkpoint'), 'completion': data.get('completion')}
    from portal_checks import erd_inventory
    compact['diagram_model_ids'] = sorted(n['id'] for n in erd_inventory(data.get('review', {}))[0])
    # Large readiness/task inventories stay in their selected evidence files.
    compact['engagement'] = {k: v for k, v in data['engagement'].items() if k in ('engagement_id', 'source_fingerprint', 'context_sha256', 'target', 'status')}
    if 'topic_coverage' in data:
        compact['topic_coverage'] = data['topic_coverage']
        compact['topic_diagrams'] = topic_pages
        compact['topic_review'] = {key:data['review'].get(key) for key in ('omni', 'omni_warehouse_bindings', 'omni_topic_domains')}
        compact['topic_review']['models'] = [{k:m.get(k) for k in ('id','layer','domain')} for m in models]
    nav = '<nav aria-label="Review"><strong>Data model review</strong>' + ''.join('<a data-nav="' + key + '" href="#' + key + '">' + label + '</a>' for key, label in [('model', '01 Data model'), ('code', '02 Code & files'), ('migration', '03 Migration plan'), ('validation', '04 Validation')] + ([('omni-topic-trees', 'Omni Topics')] if 'topic_coverage' in data else [])) + '</nav>'
    model_rows = [[_link('START_HERE.html', model_pages[m['id']], m.get('name', m['id']), data_inspect=''), html.escape(m.get('domain') or 'Unassigned'), html.escape(m.get('disposition') or 'undetermined')] for m in models]
    body = nav + '<section id="model" class="review-section" data-section><h1>Review your data model</h1><p>' + str(len(models)) + ' tables and interfaces · ' + str(len(compact['domains'])) + ' domains. Choose a domain and an output to follow its pipeline.</p><p class="muted">' + QUALIFICATION + '</p><div class="controls"><div><label for="domain">Domain</label><select id="domain"><option value="">All domains</option></select></div><div><label for="output">Gold output / pipeline</label><select id="output"></select></div></div><p id="empty" hidden>No diagram was selected for this scope. Use the table inventory below.</p><iframe id="pipeline" title="Selected output pipeline"></iframe><details class="panel"><summary>All tables — columns, keys and code</summary>' + _table(['Table', 'Domain', 'Change'], model_rows, [m.get('domain') or 'Unassigned' for m in models]) + '</details></section>'
    code_rows = []
    domains_by_artifact = {m.get('artifact_id'): m.get('domain', '') for m in models}
    for item in inventory:
        link = _link('START_HERE.html', code_pages.get(item['id'], item['path']), item['path'])
        code_rows.append('<tr data-file data-domain="' + html.escape(domains_by_artifact.get(item['id']) or '', quote=True) + '"><td>' + link + '</td><td>' + html.escape(item['category']) + '</td></tr>')
    body += '<section id="code" class="review-section" data-section hidden><h1>Code & files</h1><p>Original deliverables live in the five named folders. Use the domain selector on Data model to narrow associated code.</p><label for="search">Find a file</label><input id="search" type="search" placeholder="Search name or format"><div class="scroll"><table><thead><tr><th>File</th><th>Type</th></tr></thead><tbody>' + ''.join(code_rows) + '</tbody></table></div></section>'
    docs = [r for r in inventory if PurePosixPath(r['path']).suffix.lower() in {'.xlsx', '.docx', '.pdf'} or r['path'].startswith('05_Mappings/')]
    body += '<section id="migration" class="review-section" data-section hidden><h1>Migration plan & mappings</h1><p>Review old-to-new mappings and ticket requirements here. Templates do not create live tickets.</p>' + (_table(['Deliverable', 'Description'], [[_link('START_HERE.html', r['path'], r['path']), html.escape(r.get('description', ''))] for r in docs]) if docs else '<p>No migration document was selected. Ask for migration planning or include the existing files.</p>') + '</section>'
    validation = data.get('review', {}).get('validation', [])
    body += '<section id="validation" class="review-section" data-section hidden><h1>Validation & decisions</h1><p>' + QUALIFICATION + '</p>' + _table(['Check', 'Status', 'Scope'], [[html.escape(str(r.get(k, 'unknown'))) for k in ('id', 'status', 'scope')] for r in validation]) + '<p>Requested artifact delivery: ' + html.escape((data.get('completion') or {}).get('artifact_delivery', 'candidate')) + '</p>'
    quality = data.get('review', {}).get('quality_checks', [])
    compact['quality_checks'] = quality
    body += _table(['Evidence lane', 'Status', 'Finding / next action'], [[html.escape(str(r.get('id', ''))), html.escape(str(r.get('status', 'unknown'))), html.escape(' '.join(str(r.get(k) or '') for k in ('summary', 'next_action')))] for r in quality])
    omni = data.get('review', {}).get('omni', {})
    if omni:
        compact['omni'] = {k: v for k, v in omni.items() if k not in {'views', 'topics', 'relationships'}}
        body += '<p>Omni candidates: ' + str(len(omni.get('views', []))) + ' views, ' + str(len(omni.get('topics', []))) + ' topics. Authored YAML, explicit physical bindings, proposed relationships, native validation and dashboard creation are separate outcomes. Review the selected Omni evidence and code files.</p>'
    for key, title in (('delivery_assurance', 'Acceptance evidence'), ('migration_intent', 'Architecture intent')):
        if data.get(key):
            compact[key] = data[key]
            body += '<details class="panel"><summary>' + title + '</summary><pre>' + html.escape(json.dumps(data[key], indent=2)) + '</pre></details>'
    decisions = data.get('review', {}).get('decisions', [])
    body += _table(['Decision', 'Status', 'Detail'], [[html.escape(str(r.get('id', ''))), html.escape(str(r.get('status', 'unresolved'))), html.escape(str(r.get('question') or r.get('rationale') or r.get('description') or 'Review the maintained design document.'))] for r in decisions]) + '</section><dialog id="inspector"><button id="close-inspector">Close table</button><iframe id="table-frame" title="Selected table"></iframe></dialog>'
    if 'topic_coverage' in data:
        from topic_visuals import panel
        body += panel(data)
    # The entry page is the shared review page; detail pages keep their bounded per-table layout.
    import review_page
    texts = {}
    for record in data.get('files', []) + data.get('generated_deliverables', []):
        raw = original_files.get(record['path'])
        if raw is None or PurePosixPath(record['path']).suffix.lower() in {'.pdf', '.docx', '.xlsx', '.svg'}:
            continue
        try:
            texts[record['path']] = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
    page = review_page.page_model(data, texts, code_pages=code_pages, model_pages=model_pages)
    extra_html, extra_js = review_page.topic_extras(data)
    files['START_HERE.html'] = review_page.render(compact, page, extra_html=extra_html, extra_js=extra_js).encode('utf-8')
    page_roles['START_HERE.html'] = {'role': 'entrypoint'}
    return files, page_roles, compact


def check_page(page):
    from portal_checks import parse_page
    parsed, data = parse_page(page)
    kind = data.get('kind')
    require(kind in {'partitioned_review', 'pipeline_page', 'table_page', 'code_page', 'topic_page'}, 'Unknown partitioned page')
    sections = [node for node in parsed.nodes.values() if 'data-section' in node.get('attrs', {})]
    if kind == 'partitioned_review':
        import review_page
        review_page.check_structure(parsed, topic_trees=bool(data.get('topic_coverage')))
        require(data['model_count'] == len(data['models']) and data['file_count'] == len(data['files']), 'Partitioned page counts differ')
    return {'status': 'page_contract_verified', 'presentation': 'partitioned_v1', 'kind': kind}


def verify(archive, manifest):
    """Validate indexed files, table evidence and diagram coverage against exact ZIP bytes."""
    from delivery_portal import _relative, _sha
    from portal_checks import parse_page, svg_model_coverage
    require(manifest.get('schema_version') == 1 and manifest.get('kind') == 'portable_delivery_integrity', 'Unknown delivery manifest')
    rows = manifest['files']
    require(len({r['path'].casefold() for r in rows}) == len(rows), 'Duplicate manifest path')
    require(set(archive.namelist()) == {'DELIVERY_MANIFEST.json'} | {r['path'] for r in rows}, 'Package inventory differs from manifest')
    by_path = {r['path']: r for r in rows}
    class Links(HTMLParser):
        def __init__(self):
            super().__init__(); self.links = []
        def handle_starttag(self, tag, attributes):
            if tag in {'a', 'iframe'}:
                value = dict(attributes).get('href' if tag == 'a' else 'src')
                if value: self.links.append(value)
    for row in rows:
        _relative(row['path'])
        body = archive.read(row['path'])
        require(len(body) == row['bytes'] and _sha(body) == row['sha256'], 'Package bytes differ: ' + row['path'])
        if row['role'] in {'entrypoint', 'review_page'}:
            check_page(body)
            links = Links(); links.feed(body.decode())
            for link in links.links:
                parts = urlsplit(link)
                require(not parts.scheme and not parts.netloc and not parts.query, 'Review pages require local offline links')
                if parts.path:
                    destination = posixpath.normpath(posixpath.join(posixpath.dirname(row['path']), unquote(parts.path)))
                    require(destination in by_path, 'Review link has no packaged destination: ' + destination)
    _, data = parse_page(archive.read('START_HERE.html'))
    from omni_handoff import artifact_id, REVIEW_PATH
    semantic_inventory = next((item for item in data['files'] if item['id'] == artifact_id(REVIEW_PATH)), None)
    if semantic_inventory:
        native_summary = json.loads(archive.read(semantic_inventory['path']))
        if 'topic_trees' in native_summary:
            require('topic_coverage' in data and 'topic_review' in data and 'topic_diagrams' in data,
                    'Selected semantic inventory requires its topic review and coverage')
    require(data['engagement'].get('context_sha256') == manifest.get('context_sha256'), 'Package context differs')
    require(manifest.get('package_layout_version') == 2 and data['selected_categories'] == manifest.get('deliverables'), 'Package scope differs')
    if manifest.get('delivery_kind') == 'checkpoint' or manifest.get('checkpoint') or data.get('checkpoint'):
        require(manifest.get('delivery_kind') == 'checkpoint' and manifest.get('checkpoint') == data.get('checkpoint')
                and data['checkpoint'].get('status') == 'incomplete', 'Checkpoint label differs from the Start Here page')
    require(data.get('completion') == manifest.get('completion'), 'Completion labels differ')
    require(all(data['engagement'].get('target', {}).get(k) == manifest['target'].get(k)
                for k in ('framework', 'warehouse')), 'Package target differs')
    source_context = next((row for row in data['files'] if row['id'] == 'generated:source-lineage-json'), None)
    if source_context:
        from source_visuals import exports as source_exports
        csv_record = next((row for row in data['files'] if row['id'] == 'generated:source-lineage-csv'), None)
        source_data = {'review': {'models': data['models']}, 'package_layout_version': 2,
            'source_lineage': {'projection': json.loads(archive.read(source_context['path'])),
                              'csv': archive.read(csv_record['path']).decode() if csv_record else ''}}
        for expected in source_exports(source_data):
            if expected['category'] in data['selected_categories']:
                require(expected['path'] in by_path and archive.read(expected['path']) == base64.b64decode(expected['base64']),
                        'Source context export differs from its scoped source inventory')
    ids = {m['id'] for m in data['models']}
    require(len(ids) == len(data['models']), 'Repeated table identity')
    for item in data['files']:
        row = by_path.get(item['path'], {})
        require(row.get('sha256') == item['sha256'] and row.get('bytes') == item['size'], 'Indexed artifact bytes differ')
    for model in data['models']:
        require(model['path'] in by_path, 'Missing table page')
        _, detail = parse_page(archive.read(model['path']))
        require(detail.get('model', {}).get('id') == model['id'], 'Table page identity differs')
    canonical = next((r for r in data['files'] if r['id'] == 'generated:erd-source'), None)
    if canonical:
        source = json.loads(archive.read(canonical['path']))
        require({m['id'] for m in source['models']} == ids, 'Editable source and review inventory differ')
        from portal_checks import erd_inventory
        require(set(data['diagram_model_ids']) == {m['id'] for m in erd_inventory(source)[0]}, 'Diagram reference inventory differs')
        by_id = {m['id']: m for m in source['models']}
        for model in data['models']:
            _, detail = parse_page(archive.read(model['path']))
            require(detail['model'] == by_id[model['id']], 'Table columns or definitions differ from the canonical source')
    if data.get('quality_checks'):
        from delivery_portal import _select_quality_evidence
        import copy
        checked = {'engagement': data['engagement'], 'review': {'quality_checks': copy.deepcopy(data['quality_checks'])}}
        evidence = [{'id': item['id'], 'sha256': item['sha256'], 'content': archive.read(item['path'])} for item in data['files']]
        _select_quality_evidence(checked, evidence)
        require(checked['review']['quality_checks'] == data['quality_checks'], 'Quality evidence differs from the displayed summary')
    require(manifest.get('topic_coverage') == data.get('topic_coverage'), 'Topic manifest coverage differs')
    if 'topic_coverage' in data:
        import copy
        from delivery_portal import _select_omni_evidence
        from topic_visuals import prepare as prepare_topics
        checked = {'engagement': data['engagement'], 'review': copy.deepcopy(data['topic_review']), 'package_layout_version': 2}
        # The diagram inventory is checked against separately selected semantic bytes.
        evidence = [{'id': item['id'], 'sha256': item['sha256'], 'content': archive.read(item['path'])} for item in data['files']]
        _select_omni_evidence(checked, evidence)
        require(checked['review']['omni'] == data['topic_review']['omni'], 'Topic semantic evidence differs')
        if canonical:
            require(checked['review']['models'] == [{k:m.get(k) for k in ('id','layer','domain')} for m in source['models']],
                    'Topic binding models differ from the canonical model inventory')
        prepare_topics(checked)
        require(checked['topic_coverage'] == data['topic_coverage'], 'Topic coverage differs from selected evidence')
        expected = {row['id']:row for row in checked['topic_diagrams']}
        require(len(data['topic_diagrams']) == len(expected) and {row['id'] for row in data['topic_diagrams']} == set(expected),
                'Topic diagram inventory differs')
        for row in data['topic_diagrams']:
            wanted = expected[row['id']]
            require({k:v for k,v in row.items() if k not in ('page_path','download_available')} == {k:v for k,v in wanted.items() if k!='base64'},
                    'Topic page metadata differs')
            body = archive.read(row['page_path'])
            match = re.search(rb'(<svg\b.*?</svg>)', body, re.S)
            require(match is not None and match[1] == base64.b64decode(wanted['base64']), 'Topic diagram differs from declared paths')
        for record in checked['topic_exports']:
            if record['category'] in data['selected_categories']:
                require(record['path'] in by_path and archive.read(record['path']) == base64.b64decode(record['base64']),
                        'Topic export missing or differs from the diagram inventory')
    covered = set()
    for item in data['pipelines']:
        body = archive.read(item['path'])
        match = re.search(rb'(<svg\b.*?</svg>)', body, re.S)
        require(match is not None, 'Pipeline SVG missing')
        svg_model_coverage(match[1], item['model_ids'])
        covered.update(item['model_ids'])
    if 'diagrams' in data['selected_categories'] and ids:
        require(covered == set(data['diagram_model_ids']), 'Pipeline coverage differs from the table inventory')
    return {'status': 'integrity_verified', 'files': len(rows), 'context_sha256': manifest.get('context_sha256'),
            'diagram_coverage': {'status': 'complete' if covered == set(data['diagram_model_ids']) else 'not_selected', 'models': len(ids)},
            'authority': 'Integrity only; not native execution or business acceptance.'}


def package(state, review, selected, data, files, output, checkpoint=False):
    """Use member-level inspection for the maintained bounded delivery container.

    Generic incoming archives retain the smaller recursive scanner limits. Every
    member here is generated/selected, scanned, hashed and read back before publish.
    """
    import io
    import stat
    import zipfile
    import delivery_portal as portal
    pages, roles, compact = build(data, files)
    require(not (set(files) & set(pages)), 'Review pages collide with selected deliverables')
    original_inventory = [r for r in portal.package_file_inventory(data, {**files, 'START_HERE.html': b''})
                          if r['path'] != 'START_HERE.html']
    for row in original_inventory:
        row['embedded'] = False
    files.update(pages)
    require(len(files) <= portal.MAX_ARTIFACTS, 'Delivery file count exceeds limit; select fewer domains')
    require(sum(map(len, files.values())) <= portal.MAX_PACKAGE_BYTES * 3, 'Delivery exceeds bounded package size')
    disclosure = portal._check_share_policy(state, review, selected, compact, data['audience'])
    scans = {name: portal._check_disclosure_bytes(body, name) for name, body in files.items()}
    rows = original_inventory + [dict(path=path, sha256=portal._sha(files[path]), bytes=len(files[path]), embedded=False, **role) for path, role in roles.items()]
    manifest = {'schema_version': 1, 'kind': 'portable_delivery_integrity', 'engagement_id': state['engagement_id'],
        'package_layout_version': 2, 'presentation_contract': 'partitioned_v1', 'export_origin': 'agent_packager',
        'disclosure_scans': scans, 'disclosure_policy_status': disclosure,
        'inspection_mode': 'every_exact_member_plus_container_integrity',
        'migration_scope': state.get('answers', {}).get('migration_scope'),
        'acceptance_ready': False, 'deployment_authorized': False,
        'source_fingerprint': portal.source_fingerprint(state), 'context_sha256': portal.context_fingerprint(state),
        'target': review['target'], 'audience': data['audience'], 'deliverables': data['selected_categories'],
        'completion': data['completion'], 'authority': QUALIFICATION, 'files': sorted(rows, key=lambda r: r['path'])}
    if 'topic_coverage' in data:
        manifest['topic_coverage'] = data['topic_coverage']
    if checkpoint:
        manifest.update(delivery_kind='checkpoint', checkpoint=data['checkpoint'])
    files['DELIVERY_MANIFEST.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    portal._check_disclosure_bytes(files['DELIVERY_MANIFEST.json'], 'DELIVERY_MANIFEST.json')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, body)
    payload = stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        verify(archive, manifest)
    portal._atomic_write(output, payload)
    return manifest
