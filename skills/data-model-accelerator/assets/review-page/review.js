'use strict';
// Review page (references/review-page.md). Reads the checked delivery-data and the derived
// review-page-data; nothing here approves, executes or changes the delivery.
const D=JSON.parse(document.getElementById('delivery-data').textContent);
const P=JSON.parse(document.getElementById('review-page-data').textContent);
const $=s=>document.querySelector(s),byId=id=>document.getElementById(id);
function e(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
const tr=(s,n)=>{s=String(s);return s.length>n?s.slice(0,n-1)+'…':s};
const BADGE={served:'ok','partly served':'warn','not served':'bad',answered:'ok',covered:'ok','retire candidate':'info',pass:'ok',create:'ok',assumed:'warn','partially covered':'warn',extend:'warn',open:'bad',unresolved:'bad',fail:'bad',pending:'warn',reuse:''};
const b=s=>`<span class="b ${BADGE[s]||''}">${e(s)}</span>`;
const M=Object.create(null);P.models.forEach(m=>{m.disp=m.disposition||'unassessed';m.cols=(m.columns||[]).map(c=>[c.name,c.type||c.data_type||'',c.key||'',c.description||'']);m.dep=m.depends_on||[];m.used=[];m.src=m.sources||[];M[m.id]=m});
P.models.forEach(m=>m.dep.forEach(d=>{if(M[d])M[d].used.push(m.id)}));
const FILE=Object.create(null);P.files.forEach(f=>FILE[f.id]=f);
const EMB=Object.create(null);[...(D.files||[]),...(D.generated_deliverables||[])].forEach(f=>{if(f.base64)EMB[f.path]=f.base64});
const decoder=new TextDecoder();
function content(path){const b64=EMB[path];if(!b64)return null;const raw=atob(b64),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);return decoder.decode(bytes)}
const codeOf=m=>{const f=FILE[m.artifact_id]||FILE[(m.artifact_ids||[])[0]];return f?f.path:null};
const areaName=Object.create(null);P.areas.forEach(a=>areaName[a.id]=a.name);
const T=Object.create(null);P.topics.forEach(t=>T[t.topic]=t);
const primary=P.areas.length?(()=>{const c=Object.create(null);P.models.filter(m=>m.layer==='gold'&&m.area&&!(P.areas.find(a=>a.id===m.area)||{}).shared).forEach(m=>c[m.domain]=(c[m.domain]||0)+1);return Object.entries(c).sort((x,y)=>y[1]-x[1])[0]?.[0]})():null;
const shared=m=>m.layer!=='bronze'&&primary&&m.domain&&m.domain!==primary;
const cls=m=>({create:'new',extend:'ext',reuse:'reuse'}[m.disp]||'reuse')+(shared(m)?' shared':'');
const short=id=>id.replace(/^(stg|int|wh)_/,'');
function action(name,value){return `data-action="${name}" data-value="${e(value)}"`}
function link(n){return M[n]?`<a href="#" ${action('inspect-model',n)}>${e(n)}</a>`:e(n)}
function topicLink(t){return `<a href="#" ${action('inspect-topic',t.topic)}>${e(t.label)}</a>`}
function localHref(path){return typeof path==='string'&&path&&path===path.trim()&&!/^(?:[a-z][a-z0-9+.-]*:|[\\/])|[\x00-\x1f\x7f\\]/i.test(path)?path:null}
function go(v,label){return `<a href="#${v}">${e(label)}</a>`}
function fileLink(path,label){const f=P.files.find(x=>x.path===path);if(!f)return e(label||path);if(P.inline_files)return `<a href="#implementation-code" ${action('open-file',path)}>${e(label||path)}</a>`;const href=localHref(f.page||path);return href?`<a href="${e(href)}">${e(label||path)}</a>`:e(label||path)}
function filt(inp,id){const q=inp.value.toLowerCase();(byId(id)?.querySelectorAll('tbody tr')||[]).forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q)?'':'none')}

/* ---------- routing: eight tabs; Legacy coverage and Data dictionary live inside their parent sections ---------- */
const PARENT={architecture:'model',lineage:'model','table-dictionary':'model','implementation-code':'delivery','replacement-map':'delivery'};
const OWN_TAB={'table-dictionary':1,'replacement-map':1};
const built={};
function route(){let id=location.hash.slice(1)||'overview';if(!byId(id)||!(PARENT[id]||byId(id).hasAttribute('data-section')))id='overview';
 const top=PARENT[id]||id;
 document.querySelectorAll('[data-section]').forEach(s=>s.hidden=s.id!==top);
 Object.keys(PARENT).forEach(k=>{if(PARENT[k]===top)byId(k).hidden=OWN_TAB[id]?k!==id:!!OWN_TAB[k]});
 const tab=OWN_TAB[id]?id:top;
 document.querySelectorAll('#primary-navigation a').forEach(a=>a.setAttribute('aria-current',a.dataset.nav===tab?'page':'false'));
 document.querySelectorAll('.subnav a').forEach(a=>a.setAttribute('aria-current',a.dataset.nav===id?'page':'false'));
 const k=OWN_TAB[id]?id:top;if(R[k]&&!built[k]){R[k]();built[k]=1}
 if(top==='model'&&!OWN_TAB[id]&&!built.model){R.model();built.model=1}
 if(top==='delivery'&&!OWN_TAB[id]&&!built.delivery){R.delivery();built.delivery=1}
 if(PARENT[id]&&!OWN_TAB[id])byId(id).scrollIntoView();else window.scrollTo(0,0)}
addEventListener('hashchange',route);

/* ---------- overview ---------- */
function rOverview(){
 const L={bronze:{},silver:{},gold:{}};P.models.forEach(m=>{(L[m.layer]=L[m.layer]||{})[m.disp]=(L[m.layer][m.disp]||0)+1});
 const n=(l,d)=>(L[l]||{})[d]||0,meta=P.meta||{},reg=P.decisions.filter(d=>'assumed_option' in d||'options' in d);
 const dbt=P.files.filter(f=>/\/models\/.*\.sql$/.test(f.path)),sqlFor=d=>dbt.filter(f=>P.models.some(m=>m.disp===d&&codeOf(m)===f.path)).length;
 const yml=P.files.filter(f=>/\/models\/.*\.ya?ml$/.test(f.path)).length,views=P.files.filter(f=>f.path.endsWith('.view')).length;
 const rels=(()=>{const f=P.files.find(x=>x.path.endsWith('/relationships'));const t=f&&content(f.path);return t?(t.match(/^- join_from_view/mg)||[]).length:null})();
 const cross=P.topics.filter(t=>M[t.base]&&shared(M[t.base])).length;
 const leg=P.legacy||[],lc=s=>leg.filter(r=>r.status===s).length;
 const dash=P.assets||[],ds=s=>dash.filter(a=>(a.coverage_status||a.mapping_status)===s).length;
 const repos=meta.repositories||[];
 const accel=repos.find(r=>r.commit);
 const pending=P.validation.filter(v=>['pending','fail','skipped'].includes(v.status));
 const readOrder=meta.read_order||['Data model: pipelines, relationships and topic lineage per subject area; click any table or topic.','Decisions, starting with the open ones.','Legacy coverage: what each legacy model becomes.','Code & files: review the selected implementation and semantic files.','Validation and Open items.'];
 const notDone=meta.not_done||(pending.length?pending.map(v=>v.label||v.id):['Native build, reconciliation and semantic-layer validation are not established by this page.']);
 byId('overview').innerHTML=`
<h1>${e(P.title)} <span class="sub">domain review${P.checkpoint?' · checkpoint':''}</span></h1>
<p class="meta">${[meta.domain_position,P.target&&P.target.framework?`${P.target.framework} on ${P.target.warehouse||'the warehouse'}`:null,accel?`${accel.name} ${accel.commit.slice(0,7)}`:null].filter(Boolean).map(e).join(' · ')}</p>
<div class="banner">${e(P.checkpoint&&P.checkpoint.qualification||P.qualification)}</div>
<div class="cards">
 <div class="card"><div class="n">${P.models.length}</div><div class="l">models in scope</div><div class="d">${['gold','silver','bronze'].map(l=>`${l}: reuse ${n(l,'reuse')} · extend ${n(l,'extend')} · create ${n(l,'create')}`).join('<br>')}</div></div>
 <div class="card"><div class="n">${dbt.length+yml}</div><div class="l">dbt files to apply</div><div class="d">${sqlFor('create')} SQL for new models · ${sqlFor('extend')} SQL for changed models · ${yml} YAML</div></div>
 <div class="card"><div class="n">${P.topics.length}</div><div class="l">Omni topics</div><div class="d">${views} views${rels!=null?' · '+rels+' relationships':''}<br>${cross} cross-domain topics</div></div>
 ${leg.length?`<div class="card"><div class="n">${leg.length}</div><div class="l">legacy models accounted for</div><div class="d">covered ${lc('covered')} · partially ${lc('partially covered')} · retire candidate ${lc('retire candidate')}<br>out of domain ${lc('out of domain')} · unresolved ${lc('unresolved')}</div></div>`:''}
 <div class="card"><div class="n">${P.decisions.length}</div><div class="l">decisions & questions</div><div class="d">${reg.length?['answered','assumed','open'].map(s=>s+' '+reg.filter(d=>d.status===s).length).join(' · '):P.decisions.filter(d=>!['resolved','accepted','approved'].includes(d.status)).length+' still open'}</div></div>
 ${dash.length?`<div class="card"><div class="n">${dash.length}</div><div class="l">dashboards mapped</div><div class="d">served ${ds('served')} · partly served ${ds('partly_served')} · not served ${ds('not_served')}</div></div>`:''}
</div>
${repos.length?`<h2>Repositories</h2><div class="tw"><table><thead><tr><th>Role</th><th>Repository</th><th>Commit</th><th>Content fingerprint</th></tr></thead><tbody>${repos.map(r=>`<tr><td>${e(r.role)}</td><td>${e(r.name)}</td><td>${r.commit?`<code>${e(r.commit.slice(0,12))}</code>`:'<span class="note">not recorded</span>'}</td><td>${r.fingerprint?`<code>${e(r.fingerprint.slice(0,12))}</code>`+(r.complete===false?' <span class="note">partial scan</span>':''):'—'}</td></tr>`).join('')}</tbody></table></div>`:''}
<h2>Read in this order</h2><ol>${readOrder.map(x=>`<li>${e(x)}</li>`).join('')}</ol>
<h2>Not done yet</h2><ul>${notDone.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`;
}

/* ---------- data model ---------- */
function diagram(width,height,body){return `<div class="diagram"><div class="diagram-controls" aria-label="Diagram zoom"><button type="button" data-action="diagram-zoom" data-value="-0.25" aria-label="Zoom out">−</button><button type="button" data-action="diagram-reset">100%</button><button type="button" data-action="diagram-zoom" data-value="0.25" aria-label="Zoom in">+</button><output aria-live="polite">100%</output></div><div class="wide" tabindex="0" aria-label="Scrollable diagram"><svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" data-natural-width="${width}" data-zoom="1">${body}</svg></div></div>`}
function zoomDiagram(control,reset){const box=control.closest('.diagram'),svg=box?.querySelector('svg');if(!svg)return;const zoom=reset?1:Math.min(3,Math.max(1,Number(svg.dataset.zoom)+Number(control.dataset.value)));svg.dataset.zoom=String(zoom);svg.style.width=(Number(svg.dataset.naturalWidth)*zoom)+'px';box.querySelector('output').textContent=Math.round(zoom*100)+'%'}
function canonicalDiagram(value,index){return `<div class="diagram"><div class="diagram-controls"><button data-action="diagram-zoom" data-value="-0.25">Zoom out</button><button data-action="diagram-reset">Actual size</button><button data-action="diagram-zoom" data-value="0.25">Zoom in</button><output>100%</output></div><div class="wide" tabindex="0" data-canonical-diagram="${index}"></div></div>`}
function mountDiagrams(){document.querySelectorAll('[data-canonical-diagram]').forEach(box=>{const [kind,index]=box.dataset.canonicalDiagram.split(':');const row=kind==='pipeline'?(P.pipeline_diagrams||[])[Number(index)]:P.topics[Number(index)];if(!row?.base64)return;try{const svg=PortalSvg.sanitize(decoder.decode(Uint8Array.from(atob(row.base64),c=>c.charCodeAt(0))),'review-'+kind+'-'+index);svg.dataset.naturalWidth=svg.getAttribute('width');svg.dataset.zoom='1';box.append(svg);svg.querySelectorAll('[data-model-id]').forEach(n=>{n.dataset.action='inspect-model';n.dataset.value=n.getAttribute('data-model-id');n.setAttribute('role','button');n.setAttribute('tabindex','0')});if(kind==='topic')svg.querySelectorAll('[data-occurrence-id]').forEach(n=>{const id=n.getAttribute('data-occurrence-id');if(!(row.bindings||[]).some(b=>b.id===id))return;n.dataset.action='inspect-binding';n.dataset.value=JSON.stringify([row.topic,id]);n.setAttribute('role','button');n.setAttribute('tabindex','0')})}catch(error){box.textContent='Diagram unavailable. Review the table inventory and exported diagram.'}})}
function pipeline(a){return (P.pipeline_diagrams||[]).map((v,i)=>(a.diagram_ids||[]).includes(v.id)?`<h4>${e(v.label)}</h4>${canonicalDiagram(v,'pipeline:'+i)}`:'').join('')}
function erd(a){
 const g=new Set(a.gold),ids=a.erd.filter(i=>M[i]),isDim=i=>M[i].entity_type==='dimension'||/(?:^|\.)dim_|_dim$/.test(i);
 const rels=P.relationships.filter(r=>ids.includes(r.from)&&ids.includes(r.to)&&(g.has(r.from)||a.shared));
 const cols=a.shared?[ids.filter(i=>!isDim(i)).sort(),ids.filter(isDim).sort(),[]]:[ids.filter(i=>g.has(i)&&!isDim(i)).sort(),ids.filter(i=>g.has(i)&&isDim(i)).sort(),ids.filter(i=>!g.has(i)).sort()];
 const BW=500,CG=76,Q=Object.create(null);let H=0;
 const keys=i=>M[i].cols.filter(c=>c[2]==='PK'||c[2]==='FK');
 cols.forEach((col,ci)=>{let y=30;col.forEach(id=>{const k=keys(id).slice(0,7);const h=84+k.length*24;Q[id]={x:10+ci*(BW+CG),y,h,k,more:keys(id).length-k.length};y+=h+16});H=Math.max(H,y)});
 const W=20+3*BW+2*CG;
 let s=(a.shared?['FACTS & EXTENDED TABLES','DIMENSIONS','']:['THIS AREA — FACTS','THIS AREA — DIMENSIONS','RELATED TABLES']).map((t,i)=>t?`<text x="${10+i*(BW+CG)}" y="16" class="lh">${t}</text>`:'').join('');
 rels.forEach(r=>{const p=Q[r.from],q=Q[r.to];if(!p||!q)return;let d;const y1=p.y+26,y2=q.y+20;
  if(p.x<q.x){const x1=p.x+BW,x2=q.x,m=(x1+x2)/2;d=`M${x1} ${y1} C${m} ${y1} ${m} ${y2} ${x2} ${y2}`}
  else if(p.x>q.x){const x1=p.x,x2=q.x+BW,m=(x1+x2)/2;d=`M${x1} ${y1} C${m} ${y1} ${m} ${y2} ${x2} ${y2}`}
  else{const x=p.x+BW,bx=x+Math.min(CG-6,24+Math.abs(y2-y1)/12);d=`M${x} ${y1} C${bx} ${y1} ${bx} ${y2} ${x} ${y2}`}
  const t=`${r.from} → ${r.to} (${(r.card||'relationship').replace(/_/g,' ')})${r.key?' on '+r.key:''}`;
  s+=`<g><path d="${d}" class="relhit"><title>${e(t)}</title></path><path d="${d}" class="rel"/></g>`});
 ids.forEach(id=>{const p=Q[id];if(!p)return;const m=M[id];
  let t=`<text x="${p.x+10}" y="${p.y+26}" class="tn">${e(tr(short(id),40))}</text><text x="${p.x+10}" y="${p.y+50}" class="tg">${e(tr(m.grain||(shared(m)?'shared interface — '+String(m.domain).replace(/_/g,' '):m.entity_type||''),52))}</text>`;
  p.k.forEach((k,i)=>t+=`<text x="${p.x+10}" y="${p.y+76+i*24}" class="tg"><tspan class="${k[2]==='PK'?'kp':'kf'}">${k[2]}</tspan> ${e(tr(k[0],44))}</text>`);
  s+=`<g class="tbl ${cls(m)}" ${action('inspect-model',id)} tabindex="0" role="button"><rect x="${p.x}" y="${p.y}" width="${BW}" height="${p.h}" rx="6"/>${t}<title>${e(id)} · ${m.cols.length} columns${p.more>0?' · '+p.more+' more keys':''}</title></g>`});
 return diagram(W,H,s);
}
function topicLineage(a){return P.topics.map((t,i)=>t.area===a.id?`<h3>${topicLink(t)}</h3><p>Bindings: ${e(t.binding_status||'unassessed')}</p>${(t.diagnostics||[]).map(d=>`<p class="note">${e(d.code)}</p>`).join('')}${canonicalDiagram(t,'topic:'+i)}`:'').join('')}
const LEGEND='<div class="legend"><span class="k new"></span>create <span class="k ext"></span>extend (changes an existing model) <span class="k reuse"></span>reuse (unchanged) <span class="k shared"></span>dashed: shared interface (other domain) <span class="k raw"></span>raw source table <span class="k topic"></span>semantic topic</div>';
function rModel(){
 let h=`<p class="meta">One section per subject area: the pipeline from raw source tables through staging (bronze) and integration (silver) to the warehouse tables (gold), then the relationships between gold tables. Hover a line for its join; click any table for grain, keys, columns, lineage, security notes and code.</p>${LEGEND}`;
 P.areas.forEach(a=>{const tps=P.topics.filter(t=>t.area===a.id);
  h+=`<div class="area" id="area-${e(a.id)}"><h2>${e(a.name)} <span class="sub">${a.gold.length} gold${a.pipeline.length?' · '+a.pipeline.length+' models in the pipeline':''}</span></h2>
  ${tps.length?`<p class="note">Omni topics: ${tps.map(t=>topicLink(t)).join(', ')}</p>`:''}${a.shared?'<p class="note">Warehouse tables owned by other domains that this domain\'s topics join to or are built on. Their pipelines belong to their own domains.</p>':''}
  ${a.pipeline.length?`<h3>Pipeline — raw → staging (bronze) → integration (silver) → warehouse (gold)</h3>${pipeline(a)}`:''}
  <h3>Gold relationships</h3>${erd(a)}</div>`});
 byId('architecture').innerHTML=h;
 let t=`<h2>Topic lineage <span class="sub">${P.topics.length} topics</span></h2><p class="meta">Each semantic topic, its base view and the views it joins, per subject area. Hover a line for the join; click a topic for its joins, fields, dashboards and file.</p>${P.topic_note?`<p class="note">${e(P.topic_note)}</p>`:''}`;
 P.areas.forEach(a=>{const x=topicLineage(a);if(x)t+=`<div class="area"><h2>${e(a.name)}</h2>${x}</div>`});
 byId('lineage').innerHTML=t;mountDiagrams();
}

/* ---------- inspectors ---------- */
function insp(n){const m=M[n];if(!m)return;const p=byId('insp');
 const keys=m.cols.filter(c=>c[2]),path=codeOf(m),code=path&&P.inline_files?content(path):null;
 const relTo=c=>{const r=P.relationships.find(r=>r.from===n&&r.key.startsWith(c+' '));return r?' → '+link(r.to):''};
 const ts=P.topics.filter(t=>t.views.includes(n));
 const existing=m.existing_source||(m.reuse&&m.reuse.existing_id?'Existing model: '+m.reuse.existing_id:(m.disp==='create'?'New in this delivery':m.disp==='unassessed'?'Disposition not supplied':'Existing model, '+(m.disp==='extend'?'changed in this delivery':'unchanged')));
 const sec=m.security_notes||(m.security?[m.security]:[]);
 p.innerHTML=`<button class="x" type="button" data-action="close-inspector">Close</button><h2>${e(m.id)}</h2>
 <p>${b(m.disp)} · ${e(m.layer)} · ${e(m.domain||'')}${m.area&&areaName[m.area]?' · '+e(areaName[m.area]):''}</p>
 <p><b>Grain:</b> ${m.grain?e(m.grain):'<span class="note">not stated in the model documentation</span>'}</p>
 <p><b>Existing source:</b> ${e(existing)}</p>
 <p><b>Code file:</b> ${path?fileLink(path):'<span class="note">not in this package (unchanged)</span>'}${P.model_pages[n]?` · <a href="${e(localHref(P.model_pages[n])||'#')}">table page</a>`:''}</p>
 <p>${e(m.description||'')}</p>
 <h3>Keys</h3>${keys.length?keys.map(k=>`<div><code>${e(k[2])}</code> <code>${e(k[0])}</code>${relTo(k[0])}</div>`).join(''):'<p class="note">No keys declared.</p>'}
 <p><b>Semantic topics using this table:</b> ${ts.length?ts.map(t=>topicLink(t)+(t.base===n?' (base view)':'')).join(', '):'none'}</p>
 <h3>Lineage</h3><p><b>Depends on:</b> ${m.dep.map(link).join(', ')||'source tables only'}${m.src.length?'<br><span class="note">Source tables: '+m.src.map(e).join(', ')+'</span>':''}</p><p><b>Used by:</b> ${m.used.map(link).join(', ')||'—'}</p>
 <h3>Security notes</h3>${sec.length?`<ul>${sec.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`:'<p class="note">None recorded.</p>'}
 <h3>Columns (${m.cols.length})</h3><table><tr><th>Column</th><th>Type</th><th>Description</th></tr>${m.cols.map(c=>`<tr><td><code>${e(c[0])}</code>${c[2]?' '+e(c[2]):''}</td><td>${e(c[1])}</td><td>${e(c[3])}</td></tr>`).join('')}</table>
 ${code!=null?`<h3>Code — ${e(path)}</h3><pre>${e(code)}</pre>`:''}`;
 p.classList.add('on');p.scrollTop=0}
function inspBinding(value){let selected;try{selected=JSON.parse(value)}catch(error){return}if(!Array.isArray(selected)||selected.length!==2)return;const t=T[selected[0]],binding=t?.bindings?.find(b=>b.id===selected[1]);if(!binding)return;const ids=binding.model_ids.filter(id=>M[id]);if(ids.length===1)return insp(ids[0]);const p=byId('insp');p.innerHTML=`<button type="button" data-action="close-inspector">Close</button><h2>${e(binding.view_id)}</h2>${ids.length?'<p>Choose a bound warehouse table:</p>'+ids.map(link).join('<br>'):'<p>Unresolved warehouse binding. No table has been inferred from this view name.</p>'}`;p.classList.add('on')}
function inspTopic(n){const t=T[n];if(!t)return;const p=byId('insp'),code=P.inline_files?content(t.path):null;
 p.innerHTML=`<button class="x" type="button" data-action="close-inspector">Close</button><h2>${e(t.label)}</h2>
 <p><span class="b info">semantic topic</span> · ${e(t.group)} · ${e(areaName[t.area]||t.area)} · <code>${e(t.topic)}</code></p><p>${e(t.desc)}</p>
 <p><b>Base view:</b> ${link(t.base)}${M[t.base]&&M[t.base].grain?' <span class="note">— '+e(M[t.base].grain)+'</span>':''}</p>
 <h3>Joins (${t.joins.length})</h3>${t.joins.length?`<table><tr><th>From</th><th>To</th><th>Cardinality</th><th>On</th></tr>${t.joins.map(j=>`<tr><td>${link(j.from)}</td><td>${link(j.to)}</td><td>${e((j.card||'').replace(/_/g,' '))}</td><td><code>${e(String(j.on).replace(/\$\{|\}/g,''))}</code></td></tr>`).join('')}</table>`:'<p class="note">No joins; the topic reads its base view only.</p>'}
 <h3>Dashboards served (${t.dashboards.length})</h3>${t.dashboards.length?`<table><tr><th>ID</th><th>Dashboard</th><th>Status</th></tr>${t.dashboards.map(x=>`<tr><td>${e(x.id)}</td><td>${e(x.title)}</td><td>${b(String(x.status).replace('_',' '))}</td></tr>`).join('')}</table>`:'<p class="note">No in-scope dashboard maps to this topic.</p>'}
 <h3>Fields and AI context</h3><p>Inspect the supplied topic file below. The canonical diagram records joins and bindings; it does not assert field or AI context coverage.</p>
 <h3>Files</h3><p>${[t.path,...Object.values(t.view_files)].map(v=>fileLink(v)).join('<br>')}</p>
 ${code!=null?`<h3>Code — ${e(t.path)}</h3><pre>${e(code)}</pre>`:''}`;
 p.classList.add('on');p.scrollTop=0}
addEventListener('keydown',ev=>{if(ev.key==='Escape')byId('insp').classList.remove('on')});

/* ---------- code & files ---------- */
let cur=null;
function rDelivery(){const ph=P.placeholders,dbt=P.files.some(f=>/\/models\//.test(f.path)),omni=P.files.some(f=>f.path.endsWith('.topic')||f.path.endsWith('.view'));
 byId('implementation-code').innerHTML=`${dbt?'<p class="meta">dbt files drop in over the target project at the same paths under <code>models/</code>; files not listed are unchanged. Schema YAML files replace the file of the same name, so compare with the main branch first.</p>':''}
 ${P.new_sources.length?`<h2>Source tables used by new staging models <span class="sub">${P.new_sources.length}</span></h2><p>${P.new_sources.map(s=>`<code>${e(s)}</code>`).join(' ')}</p><p class="note">Check that each is declared in the source YAML for your environment.</p>`:''}
 ${omni?`<h2>Semantic-layer placeholders to replace</h2>${ph.length?`<ul>${ph.map(x=>`<li><b>${e(x.text)}</b> — ${x.files.length} files</li>`).join('')}</ul>`:'<p class="note">No TODO placeholders found in the semantic files.</p>'}`:''}
 <h2>Files <span class="sub">${P.files.length}</span></h2>
 <div class="files"><div><input class="q" placeholder="Filter files…" data-action="filter-files" id="fq"><ul id="flist"></ul></div><pre id="fview">${P.inline_files?'Select a file.':'Select a file to open its page.'}</pre></div>`;
 renderFiles()}
function renderFiles(){const q=(byId('fq').value||'').toLowerCase();
 byId('flist').innerHTML=P.files.filter(f=>f.path.toLowerCase().includes(q)).map(f=>`<li ${action('open-file',f.path)} data-p="${e(f.path)}" tabindex="0" role="button"${f.path===cur?' class="on"':''}><span class="b">${e(f.category)}</span> ${e(f.path)}</li>`).join('');}
function openFile(p){if(!built.delivery){R.delivery();built.delivery=1}cur=p;const f=P.files.find(x=>x.path===p);
 if(!f)return;
 if(!P.inline_files){const href=localHref(f.page||f.path);if(href)location.href=href;return}
 const t=content(p);byId('fview').textContent=t!=null?('// '+p+'\n\n'+t):'Binary or generated file: open it from the package folder.';
 document.querySelectorAll('#flist li').forEach(li=>li.classList.toggle('on',li.dataset.p===p));byId('insp').classList.remove('on')}

/* ---------- decisions ---------- */
function rChanges(){const reg=P.decisions.filter(d=>'assumed_option' in d||'options' in d),areas=[...new Set(P.decisions.map(d=>d.area||d.title||''))].sort();
 byId('changes').innerHTML=`<h1>Decisions</h1><p class="meta">${reg.length?'Answered: confirmed by a person. Assumed: chosen by the authors, still reviewable. Open: needs a person; the assumed option is what the code does meanwhile.':'Decisions recorded in the review.'}</p>
 <input class="q" placeholder="Filter…" data-action="filter-table" data-table="tdec">
 <div class="tw"><table id="tdec"><thead><tr><th>ID</th><th>Area</th><th>Question</th>${reg.length?'<th>Options</th><th>Assumed option</th>':''}<th>Status</th></tr></thead><tbody>${P.decisions.map(d=>`<tr><td style="white-space:nowrap">${e(d.id)}</td><td>${e(d.area||d.title||'')}</td><td>${e(d.question||d.title||d.summary||d.description||'')}${d.decision?`<div class="note">${e(d.decision)}</div>`:''}</td>${reg.length?`<td>${(d.options||[]).map(e).join('<br>')||'—'}</td><td>${e(d.assumed_option||'—')}</td>`:''}<td>${b(d.status||'unresolved')}</td></tr>`).join('')}</tbody></table></div>`}

/* ---------- legacy coverage ---------- */
function rLegacy(){const ST=['covered','partially covered','retire candidate','out of domain','unresolved'],leg=P.legacy;const tl=Object.create(null);P.topics.forEach(t=>tl[t.topic]=t.label);
 let h='<h2>Legacy coverage</h2>';
 if(leg){const rows=[...leg].sort((x,y)=>ST.indexOf(x.status)-ST.indexOf(y.status)||x.legacy.localeCompare(y.legacy));
  h+=`<p class="meta">${ST.map(s=>s+' '+leg.filter(r=>r.status===s).length).join(' · ')}</p>
  <p class="note"><b>covered</b>: already a warehouse table, reused or extended · <b>retire candidate</b>: fully replaced by a new table, retire after reconciliation · <b>partially covered</b>: replaced, some fields not carried or rules changed · <b>out of domain</b>: another domain's model; the cross-domain topic is named where one serves it · <b>unresolved</b>: no definition or no target yet.</p>
  <input class="q" placeholder="Filter legacy models…" data-action="filter-table" data-table="tleg"><div class="tw"><table id="tleg"><thead><tr><th>Legacy model</th><th>Status</th><th>Target</th><th>Topic</th><th>Note</th></tr></thead><tbody>${rows.map(r=>{
   let t=(r.topics||[]).length?r.topics.slice(0,3).map(x=>e(tl[x]||x)).join(', ')+(r.topics.length>3?` <span class="note">+${r.topics.length-3} more</span>`:''):'—';
   if(r.status==='out of domain')t=(r.cross_topics||[]).length?'cross-domain topic: <b>'+r.cross_topics.map(x=>e(tl[x]||x)).join(', ')+'</b>':`<span class="note">no topic in this delivery${r.domain?' ('+e(r.domain.replace(/_/g,' '))+')':''}</span>`;
   return `<tr><td><code>${e(r.legacy)}</code>${r.source?`<div class="note">${e(r.source)}</div>`:''}</td><td>${b(r.status)}</td><td>${(r.targets||[]).map(link).join('<br>')||'—'}</td><td>${t}</td><td>${e(r.note||'')}</td></tr>`}).join('')}</tbody></table></div>`}
 else h+='<p class="note">No legacy coverage register was supplied in this review.</p>';
 const assets=P.assets||[];
 if(assets.length)h+=`<h2>Dashboards and requirements → topics</h2><div class="tw"><table><thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Topics</th><th>Reason</th></tr></thead><tbody>${assets.map(a=>`<tr><td>${e(a.id)}</td><td>${e(a.name||'')}</td><td>${b(String(a.coverage_status||a.mapping_status||'').replace('_',' '))}</td><td>${(a.topics||[]).map(x=>e(tl[x]||x)).join(', ')||'—'}</td><td>${e(a.coverage_reason||'')}</td></tr>`).join('')}</tbody></table></div>`;
 byId('replacement-map').innerHTML=h}

/* ---------- dictionary ---------- */
let DICT=null;
function rDict(){DICT=[];P.models.forEach(m=>m.cols.forEach(c=>DICT.push([m.layer,m.id,m.disp,c[0],c[1],c[2],c[3],codeOf(m)])));
 byId('table-dictionary').innerHTML=`<h2>Data dictionary</h2><p class="meta">${P.models.length} models · ${DICT.length.toLocaleString('en-GB')} columns. Blank types are not documented in the existing model and are confirmed only by a build.</p>
 <input class="q" placeholder="Search models and columns…" id="xq" data-action="filter-dictionary"><select class="s" id="xl" data-action="filter-dictionary"><option value="">all layers</option><option>gold</option><option>silver</option><option>bronze</option></select> <span class="note" id="xn"></span>
 <div class="tw"><table id="tdict"><thead><tr><th>Layer</th><th>Model</th><th>Status</th><th>Column</th><th>Type</th><th>Description</th><th>Code file</th></tr></thead><tbody></tbody></table></div>`;drawDict()}
function drawDict(){const q=byId('xq').value.toLowerCase(),l=byId('xl').value;const rows=DICT.filter(r=>(!l||r[0]===l)&&(!q||(r[1]+' '+r[3]+' '+r[6]).toLowerCase().includes(q)));
 $('#tdict tbody').innerHTML=rows.slice(0,400).map(r=>`<tr><td>${e(r[0])}</td><td>${link(r[1])}</td><td>${e(r[2])}</td><td><code>${e(r[3])}</code>${r[5]?' '+e(r[5]):''}</td><td>${e(r[4])}</td><td>${e(r[6])}</td><td>${r[7]?fileLink(r[7]):'<span class="note">unchanged</span>'}</td></tr>`).join('');
 byId('xn').textContent=(rows.length>400?'showing 400 of ':'')+rows.length.toLocaleString('en-GB')+' columns'}

/* ---------- validation ---------- */
function rValidation(){const open=P.validation.filter(v=>!['pass','passed'].includes(v.status)),passed=P.validation.filter(v=>['pass','passed'].includes(v.status));
 byId('validation').innerHTML=`<h1>Validation</h1><p class="meta">Recorded checks and bounded file diagnostics. Missing, unsupported and pending evidence remain unverified; a zero finding count is not proof that the model works.</p>
 ${P.static.length?`<table><thead><tr><th>Check</th><th>Count</th><th>Status</th><th>Scope</th></tr></thead><tbody>${P.static.map(s=>`<tr><td>${e(s.label)}</td><td>${s.count}</td><td>${b(s.count?'fail':'pass')}</td><td>${e(s.scope||'')}${(s.items||[]).length?`<details><summary class="note">items</summary><pre>${e(JSON.stringify(s.items,null,1))}</pre></details>`:''}</td></tr>`).join('')}</tbody></table>`:'<p class="note">Static checks need PyYAML at packaging time.</p>'}
 ${Object.keys(P.evidence||{}).length?`<details><summary>Recorded workflow evidence</summary><pre>${e(JSON.stringify(P.evidence,null,2))}</pre></details>`:''}<h2>Remaining checks and unknowns</h2>${open.length?`<table><thead><tr><th>Check</th><th>Scope</th><th>Status</th><th>Detail</th></tr></thead><tbody>${open.map(v=>`<tr><td>${e(v.label||v.id)}</td><td>${e(v.scope||'')}</td><td>${b(v.status)}</td><td>${e(v.details||v.actual||'')}</td></tr>`).join('')}</tbody></table>`:'<p class="note">None recorded.</p>'}
 ${passed.length?`<h2>Reported passes</h2><table><thead><tr><th>Check</th><th>Scope</th><th>Status</th><th>Detail</th></tr></thead><tbody>${passed.map(v=>`<tr><td>${e(v.label||v.id)}</td><td>${e(v.scope||'')}</td><td>${b('pass')}</td><td>${e(v.actual||v.details||'')}</td></tr>`).join('')}</tbody></table>`:''}`}

/* ---------- open items ---------- */
function rOpen(){const items=[...P.decisions.filter(d=>['open','pending','unresolved'].includes(d.status)||!d.status).map(d=>({id:d.id,kind:'Question',text:d.question||d.title||'',who:d.reviewer_role||d.area||'',meanwhile:d.assumed_option||''})),
 ...P.validation.filter(v=>['pending','fail','skipped'].includes(v.status)).map(v=>({id:v.id,kind:'Check',text:v.label||'',who:'',meanwhile:v.details||''})),
 ...(P.legacy||[]).filter(r=>r.status==='unresolved').map(r=>({id:r.legacy,kind:'Legacy model',text:r.note||'',who:'',meanwhile:'No target'})),
 ...P.placeholders.map(x=>({id:x.text,kind:'Placeholder',text:x.files.length+' semantic files carry this placeholder',who:'',meanwhile:'Left as a comment'}))];
 byId('open-items').innerHTML=`<h1>Open items</h1><p class="meta">Everything still needing a person (${items.length}). "Meanwhile" is what the candidate does until it is answered. This page approves nothing.</p>
 <input class="q" placeholder="Filter…" data-action="filter-table" data-table="ttodo"><div class="tw"><table id="ttodo"><thead><tr><th>ID</th><th>Kind</th><th>What is unconfirmed</th><th>Who answers</th><th>Meanwhile</th></tr></thead><tbody>${items.map(o=>`<tr><td style="white-space:nowrap">${e(o.id)}</td><td>${e(o.kind)}</td><td>${e(o.text)}</td><td>${e(o.who)}</td><td>${e(o.meanwhile)}</td></tr>`).join('')}</tbody></table></div>`}

/* ---------- feedback and continuation ---------- */
const feedbackModels=new Set((D.kind==='partitioned_review'?D.models||[]:D.review?.models||[]).map(m=>m.id));
const feedbackTopics=new Set((D.kind==='partitioned_review'?D.topic_diagrams||[]:D.review?.topic_join_trees?.topics||[]).map(t=>t.id));
const feedbackSubjects=[{model_id:null,topic_id:null,label:'Whole review'},...[...feedbackModels].map(id=>({model_id:id,topic_id:null,label:'Table: '+id})),...[...feedbackTopics].map(id=>({model_id:null,topic_id:id,label:'Topic: '+id}))];
const feedbackBinding=!!(D.engagement?.engagement_id&&/^[a-f0-9]{64}$/.test(D.engagement?.context_sha256||''));
async function sha256Text(text){if(!globalThis.crypto?.subtle)throw new Error('This browser cannot bind feedback to the review. Return this package and your comments to the agent.');return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,'0')).join('')}
async function feedbackResponse(){
 if(!feedbackBinding)throw new Error('Refresh this review to establish a current context before exporting feedback.');
 const choice=byId('fb-table').value,subject=feedbackSubjects.find((_,i)=>String(i)===choice),text=byId('fb-text').value.trim(),type=byId('fb-kind').value;
 if(!subject||!['change_request','question'].includes(type))throw new Error('Select an included table or topic and a feedback type.');
 if(!text||text.length>10000)throw new Error('Enter between 1 and 10,000 characters of feedback.');
 return {schema_version:2,kind:'model_review_feedback',request_only:true,engagement_id:D.engagement.engagement_id,context_sha256:D.engagement.context_sha256,page_data_sha256:await sha256Text(byId('delivery-data').textContent),review_page_data_sha256:await sha256Text(byId('review-page-data').textContent),comments:[{model_id:subject.model_id,topic_id:subject.topic_id,type,text}]};
}
function showFeedbackJSON(text){const field=byId('fb-json');field.value=text;byId('fb-fallback').hidden=false;field.focus();field.select()}
async function exportFeedback(mode){try{
 const text=JSON.stringify(await feedbackResponse(),null,2);showFeedbackJSON(text);
 if(mode==='copy'){
  try{await navigator.clipboard.writeText(text);byId('fb-note').textContent='Copied. Return the JSON to the agent. Nothing has been approved or deployed.'}
  catch(error){byId('fb-note').textContent='Clipboard unavailable. Copy the selected JSON below with your keyboard, or download it.'}
 }else{
  try{const url=URL.createObjectURL(new Blob([text],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='model-review-feedback.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);byId('fb-note').textContent='Download requested. If it did not start, copy the JSON below. Nothing has been approved or deployed.'}
  catch(error){byId('fb-note').textContent='Download unavailable. Copy the selected JSON below with your keyboard.'}
 }
 }catch(error){byId('fb-fallback').hidden=true;byId('fb-json').value='';byId('fb-note').textContent=error.message}}
function rFeedback(){byId('review-feedback').innerHTML=`<h1>Prepare review feedback</h1><p class="meta">Write a correction or question, then return the JSON to the agent. Feedback is bound to this exact review snapshot; it is a request, never approval.</p>
 <p class="note">${feedbackBinding?'The agent must check freshness before applying these comments.':'This page has no current context binding. Ask the agent to refresh it before recording feedback.'}</p>
 <label for="fb-table">Table or topic</label><br><select class="s" id="fb-table">${feedbackSubjects.map((s,i)=>`<option value="${i}">${e(s.label)}</option>`).join('')}</select><br>
 <label for="fb-kind">Feedback type</label><select class="s" id="fb-kind"><option value="change_request">Change request</option><option value="question">Question</option></select><br>
 <label for="fb-text">Correction or question</label><textarea id="fb-text" maxlength="10000" placeholder="What should change, and why?"></textarea><br>
 <button type="button" data-action="feedback-download"${feedbackBinding?'':' disabled'}>Download feedback</button> <button type="button" data-action="feedback-copy"${feedbackBinding?'':' disabled'}>Copy feedback</button>
 <p class="note" id="fb-note" role="status"></p><div id="fb-fallback" hidden><label for="fb-json">Feedback JSON — select and copy if needed</label><textarea id="fb-json" readonly spellcheck="false"></textarea></div>`}
function rFrontend(){const f=P.frontend;byId('dashboard-migration').innerHTML=`<h1>Dashboard migration</h1>${f&&f.items?`<p class="meta">${e(f.qualification||'')}</p><table><thead><tr><th>Scope</th><th>Status</th><th>Dashboards</th><th>Topics</th><th>Next action</th></tr></thead><tbody>${f.items.map(r=>`<tr><td>${e(r.domain_id||r.id)}</td><td>${e(r.status)}</td><td>${e((r.dashboard_ids||[]).join(', '))}</td><td>${e((r.topic_names||[]).join(', '))}</td><td>${e(r.next_action||'')}</td></tr>`).join('')}</tbody></table>`:'<p class="note">No dashboard migration continuation was requested for this delivery.</p>'}`}

// Data attributes carry names only. They are never evaluated as JavaScript.
function dispatchAction(control){switch(control.dataset.action){
 case 'inspect-model':insp(control.dataset.value);break;
 case 'inspect-topic':inspTopic(control.dataset.value);break;
 case 'inspect-binding':inspBinding(control.dataset.value);break;
 case 'open-file':openFile(control.dataset.value);if(P.inline_files)location.hash='implementation-code';break;
 case 'close-inspector':byId('insp').classList.remove('on');break;
 case 'feedback-copy':return exportFeedback('copy');
 case 'feedback-download':return exportFeedback('download');
 case 'diagram-zoom':zoomDiagram(control,false);break;
 case 'diagram-reset':zoomDiagram(control,true);break;
}}
const clickActions=new Set(['inspect-model','inspect-topic','inspect-binding','open-file','close-inspector','feedback-copy','feedback-download','diagram-zoom','diagram-reset']);
document.addEventListener('click',event=>{const control=event.target.closest?.('[data-action]');if(!control||control.disabled||!clickActions.has(control.dataset.action))return;event.preventDefault();dispatchAction(control)});
document.addEventListener('keydown',event=>{const control=event.target.closest?.('[data-action][role="button"]');if(control&&(event.key==='Enter'||event.key===' ')){event.preventDefault();dispatchAction(control)}});
function filterEvent(event){const control=event.target;if(control.dataset.action==='filter-table')filt(control,control.dataset.table);else if(control.dataset.action==='filter-files')renderFiles();else if(control.dataset.action==='filter-dictionary')drawDict()}
document.addEventListener('input',filterEvent);document.addEventListener('change',filterEvent);

const R={overview:rOverview,model:rModel,delivery:rDelivery,changes:rChanges,'replacement-map':rLegacy,'table-dictionary':rDict,validation:rValidation,'open-items':rOpen,'review-feedback':rFeedback,'dashboard-migration':rFrontend};
byId('brand').textContent=P.title;byId('footer-id').textContent=' · '+(P.engagement_id||'')+' · no external requests';
route();
