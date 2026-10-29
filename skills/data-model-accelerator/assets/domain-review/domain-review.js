'use strict';
// Domain review page (references/domain-review-page.md). Reads only the embedded page data;
// nothing here executes, approves or changes the delivery.
const D=JSON.parse(document.getElementById('domain-review-data').textContent);
const $=s=>document.querySelector(s),byId=id=>document.getElementById(id);
function e(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
const tr=(s,n)=>{s=String(s);return s.length>n?s.slice(0,n-1)+'…':s};
const M=Object.create(null);D.models.forEach(m=>M[m.id]=m);
const FILES=Object.create(null);D.files.forEach(f=>FILES[f.path]=f);
const DEC=Object.create(null);D.decisions.forEach(d=>DEC[d.id]=d);
const T=Object.create(null);D.topics.forEach(t=>T[t.topic]=t);
const V=[['overview','Overview'],['model','Data model'],['code','Code & files'],['decisions','Decisions'],['legacy','Legacy coverage'],['dict','Data dictionary'],['valid','Validation'],['todos','Open items']];
const areaName=Object.create(null);D.areas.forEach(a=>areaName[a.id]=a.name);
const BADGE={served:'ok','partly served':'warn','not served':'bad',answered:'ok',covered:'ok','retire candidate':'info',pass:'ok',new:'ok',create:'ok',assumed:'warn','partially covered':'warn',changed:'warn',extend:'warn',open:'bad',unresolved:'bad',fail:'bad',pending:'warn',skipped:'mut','not applicable':'mut','out of domain':'mut',reuse:'mut'};
const b=s=>`<span class="b ${BADGE[s]||'mut'}">${e(s)}</span>`;
const human=s=>String(s||'').replace(/_/g,' ');
const act=(name,value)=>`data-act="${name}" data-v="${e(value)}"`;
const link=n=>M[n]?`<a href="#" ${act('model',n)}>${e(n)}</a>`:e(n);
const topicLink=(n,label)=>T[n]?`<a href="#" ${act('topic',n)}>${e(label||T[n].label)}</a>`:e(label||n);
const go=(v,label)=>`<a href="#${v}" ${act('show',v)}>${e(label)}</a>`;
const fileLink=(p,label)=>FILES[p]?`<a href="#code" ${act('file',p)}>${e(label||p)}</a>`:`<span class="note">${e(label||p)}</span>`;
const isShared=m=>m.layer!=='bronze'&&m.domain!==D.meta.domain;
const kind=m=>isShared(m)?'shared':m.disp;
const subl=m=>isShared(m)?`${m.disp} · interface (${human(m.domain)})`:`${m.disp} · ${m.type}`;

byId('nav').innerHTML=V.map(([k,l])=>`<button type="button" data-v="${k}" ${act('show',k)}>${e(l)}</button>`).join('');
byId('main').innerHTML=V.map(([k])=>`<section class="view" id="v-${k}"></section>`).join('');
const built={};
function show(v){if(!R[v])v='overview';if(!built[v]){R[v]();built[v]=1}
 document.querySelectorAll('.view').forEach(x=>x.classList.toggle('on',x.id==='v-'+v));
 document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('on',x.dataset.v===v));
 if(location.hash!=='#'+v)history.replaceState(null,'','#'+v);window.scrollTo(0,0)}
function filt(inp,id){const q=inp.value.toLowerCase();document.querySelectorAll('#'+id+' tbody tr').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q)?'':'none')}
const closeInsp=()=>byId('insp').classList.remove('on');

/* ---------- overview ---------- */
function rOverview(){
 const c=D.cards,mt=D.meta,L=c.layers,Lg=c.legacy,Dc=c.decisions,Ds=c.dashboards;
 const tot=['bronze','silver','gold'].reduce((s,l)=>s+L[l].reuse+L[l].extend+L[l].create,0);
 const cards=[
  [tot,'models in scope',['gold','silver','bronze'].map(l=>`${l}: reuse ${L[l].reuse} · extend ${L[l].extend} · create ${L[l].create}`).join('<br>')],
  [c.code.new+c.code.changed,'code files to apply',`${c.code.new} new (${c.code.new_sql} models) · ${c.code.changed} change existing files (${c.code.changed_sql} models)`],
  [c.semantic.topics,'semantic topics',`${c.semantic.views} views · ${c.semantic.relationships} relationships<br>${c.semantic.cross_domain_topics} cross-domain topics`]];
 if(c.legacy_total)cards.push([c.legacy_total,'legacy models accounted for',`covered ${Lg.covered} · partially ${Lg['partially covered']} · retire candidate ${Lg['retire candidate']}<br>out of domain ${Lg['out of domain']} · unresolved ${Lg.unresolved}`]);
 cards.push([Dc.answered+Dc.assumed+Dc.open,'decisions',`answered ${Dc.answered} · assumed ${Dc.assumed} · open ${Dc.open}`]);
 if(D.dashboards.length)cards.push([D.dashboards.length,'dashboards mapped',`served ${Ds.served} · partly served ${Ds.partly_served} · not served ${Ds.not_served}`]);
 const tool=mt.repositories.find(r=>r.role==='Tooling'&&r.commit);
 const facts=[mt.scope_label,D.dashboards.length?`${D.dashboards.length} dashboards in scope`:null,...mt.facts].filter(Boolean).map(e);
 if(tool)facts.push(`${e(tool.name)} rev <code>${e(tool.commit.slice(0,7))}</code>`);
 byId('v-overview').innerHTML=`
<h1>${e(mt.title)} <span class="sub">${e(mt.subtitle)}</span></h1>
<p class="meta">${facts.join(' · ')}</p>
<div class="banner">${e(mt.banner)}</div>
<div class="cards">${cards.map(([n,l,d])=>`<div class="card"><div class="n">${n}</div><div class="l">${e(l)}</div><div class="d">${d}</div></div>`).join('')}</div>
${mt.repositories.length?`<h2>Repositories</h2><div class="tw"><table><thead><tr><th>Role</th><th>Repository</th><th>Commit</th><th>Content fingerprint</th></tr></thead><tbody>${mt.repositories.map(r=>`<tr><td>${e(r.role)}</td><td>${e(r.name)}</td><td>${r.commit?`<code>${e(r.commit.slice(0,12))}</code>`:'<span class="note">not recorded</span>'}</td><td>${r.fingerprint?`<code>${e(r.fingerprint.slice(0,12))}</code>`+(r.complete===false?' <span class="note">partial scan</span>':''):'—'}</td></tr>`).join('')}</tbody></table></div>`:''}
<h2>Read in this order</h2>
<ol>${D.reading_order.map(r=>`<li>${r.view?go(r.view,r.label):e(r.label)}${r.text?': '+e(r.text):''}</li>`).join('')}</ol>
${D.dashboards.length?`<h2>Dashboards</h2>
<div class="tw"><table><thead><tr><th>ID</th><th>Dashboard</th><th>Status</th><th>Query tiles</th><th>Topics</th><th>Reason</th></tr></thead><tbody>${D.dashboards.map(x=>`<tr><td style="white-space:nowrap">${e(x.asset_type==='look'?'Look '+x.asset_id:x.asset_id)}</td><td>${e(x.title)}</td><td>${b(human(x.status))}</td><td style="white-space:nowrap">${x.n_query_tiles==null?'<span class="note">not counted</span>':`${x.n_served} served<br>${x.n_partly_served} partly<br>${x.n_not_served} not`}</td><td>${x.topics.map(t=>topicLink(t,t)).join(', ')||'—'}</td><td class="note">${e(x.reason)}${x.scope_reason?`<br>${e(x.scope_reason)}`:''}</td></tr>`).join('')}</tbody></table></div>`:''}
<h2>Not done yet</h2>
<ul>${D.not_done.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`;
}

/* ---------- data model ---------- */
const COL={create:'#2f9e5b',extend:'#e0952b',reuse:'#8a94a6',shared:'#4a5bdc',topic:'#e8306e'};
function box(x,y,w,h,id,l1,l2,k,a,tip){const c=COL[k]||COL.reuse;
 return `<g class="nd k-${k}" ${act(a,id)} role="button" tabindex="0"><rect class="bg" x="${x}" y="${y}" width="${w}" height="${h}" rx="5" style="stroke:${c}"/><rect x="${x}" y="${y}" width="5" height="${h}" rx="2" style="fill:${c}"/><text class="t1" x="${x+14}" y="${y+16}">${e(l1)}</text>${l2?`<text class="t2" x="${x+14}" y="${y+29}">${e(l2)}</text>`:''}<title>${e(tip||id)}</title></g>`}
function curve(x1,y1,x2,y2,cls,tip){const m=(x1+x2)/2,d=`M${x1} ${y1} C${m} ${y1} ${m} ${y2} ${x2} ${y2}`;
 return tip?`<g><path d="${d}" class="relhit"><title>${e(tip)}</title></path><path d="${d}" class="${cls}"/></g>`:`<path d="${d}" class="${cls}"/>`}
const canvas=(W,H,s)=>`<div class="wide canvas"><svg viewBox="0 0 ${W} ${H}" style="min-width:${Math.min(W,1100)}px">${s}</svg></div>`;
function pipeline(a){
 const NW=330,NH=36,GAP=10,CG=110,cols={bronze:[],silver:[],gold:[]};
 a.pipeline.forEach(i=>cols[M[i].layer].push(i));
 const order=['bronze','silver','gold'],P={};let rows=0;
 order.forEach((k,ci)=>{cols[k].sort((x,y)=>(isShared(M[x])-isShared(M[y]))||x.localeCompare(y));cols[k].forEach((id,ri)=>P[id]={x:16+ci*(NW+CG),y:34+ri*(NH+GAP)});rows=Math.max(rows,cols[k].length)});
 const W=32+3*NW+2*CG+CG-10,H=34+rows*(NH+GAP)+6;
 let s=order.map((k,ci)=>`<text x="${16+ci*(NW+CG)}" y="18" class="lh">${k.toUpperCase()} — ${cols[k].length} models</text>`).join('');
 let nSame=0;
 a.pipeline.forEach(i=>M[i].dep.forEach(d=>{if(!P[d]||!P[i])return;const p=P[d],q=P[i],tip=`${d} → ${i}`;
  if(p.x!==q.x){s+=curve(p.x+NW,p.y+NH/2,q.x-4,q.y+NH/2,'edge arr',tip);return}
  nSame++;const x=p.x+NW,y1=p.y+NH/2,y2=q.y+NH/2,bx=x+Math.min(CG-14,22+Math.abs(y2-y1)/6);
  const dd=`M${x} ${y1} C${bx} ${y1} ${bx} ${y2} ${x+4} ${y2}`;
  s+=`<g><path d="${dd}" class="relhit"><title>${e(tip+' (same layer)')}</title></path><path d="${dd}" class="edge same arr"/></g>`}));
 s=`<defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L8 4L0 8z" fill="#8f8799"/></marker></defs>`+s;
 a.pipeline.forEach(id=>{const p=P[id],m=M[id];s+=box(p.x,p.y,NW,NH,id,tr(id,46),subl(m)+(m.src.length?' · '+m.src.length+' source table'+(m.src.length>1?'s':''):''),kind(m),'model',`${id} · ${subl(m)}${m.src.length?'\nSources: '+m.src.join(', '):''}`)});
 return `<p class="note">Arrows point from a model to the model built on it.${nSame?` Curved lines on the right of a column (${nSame}) join two models in the same layer.`:''}</p>${canvas(W,H,s)}`;
}
function erd(a){
 const g=new Set(a.gold),ids=a.erd.filter(i=>M[i]),isDim=i=>M[i].type==='dimension';
 const rels=D.rels.filter(r=>ids.includes(r.from)&&ids.includes(r.to)&&(g.has(r.from)||a.shared));
 const cols=a.shared?[ids.filter(i=>!isDim(i)).sort(),ids.filter(isDim).sort(),[]]:[ids.filter(i=>g.has(i)&&!isDim(i)).sort(),ids.filter(i=>g.has(i)&&isDim(i)).sort(),ids.filter(i=>!g.has(i)).sort()];
 const BW=330,CG=90,P={};let H=0;
 const keys=i=>M[i].cols.filter(c=>c[2]==='PK'||c[2]==='FK');
 cols.forEach((col,ci)=>{let y=34;col.forEach(id=>{const k=keys(id).slice(0,8);const h=46+k.length*15;P[id]={x:16+ci*(BW+CG),y,h,k,more:keys(id).length-k.length};y+=h+16});H=Math.max(H,y)});
 const W=32+3*BW+2*CG;
 let s=(a.shared?['FACTS & EXTENDED TABLES','DIMENSIONS','']:['THIS AREA — FACTS & EXTENDED TABLES','THIS AREA — DIMENSIONS','RELATED TABLES']).map((t,i)=>t?`<text x="${16+i*(BW+CG)}" y="18" class="lh">${t}</text>`:'').join('');
 rels.forEach(r=>{const p=P[r.from],q=P[r.to];if(!p||!q)return;const y1=p.y+18,y2=q.y+18,t=`${r.from} → ${r.to}${r.card?` (${human(r.card)})`:''}${r.key?' on '+r.key:''}${r.basis?' · from '+r.basis:''}`;
  if(p.x<q.x)s+=curve(p.x+BW,y1,q.x,y2,'rel',t);else if(p.x>q.x)s+=curve(p.x,y1,q.x+BW,y2,'rel',t);
  else{const x=p.x+BW,bx=x+Math.min(CG-8,26+Math.abs(y2-y1)/12),d=`M${x} ${y1} C${bx} ${y1} ${bx} ${y2} ${x} ${y2}`;s+=`<g><path d="${d}" class="relhit"><title>${e(t)}</title></path><path d="${d}" class="rel"/></g>`}});
 ids.forEach(id=>{const p=P[id];if(!p)return;const m=M[id],c=COL[kind(m)]||COL.reuse;
  let t=`<rect class="bg" x="${p.x}" y="${p.y}" width="${BW}" height="${p.h}" rx="5" style="stroke:${c}"/><rect x="${p.x}" y="${p.y}" width="5" height="${p.h}" rx="2" style="fill:${c}"/><text x="${p.x+14}" y="${p.y+17}" class="t1">${e(tr(id,46))}</text><text x="${p.x+14}" y="${p.y+31}" class="t2">${e(tr(m.grain||subl(m),58))}</text>`;
  p.k.forEach((k,i)=>t+=`<text x="${p.x+14}" y="${p.y+48+i*15}" class="t2"><tspan class="${k[2]==='PK'?'kp':'kf'}">${k[2]}</tspan> ${e(tr(k[0],46))}</text>`);
  if(p.more>0)t+=`<text x="${p.x+BW-10}" y="${p.y+p.h-6}" class="t2" text-anchor="end">+${p.more} keys</text>`;
  s+=`<g class="nd k-${kind(m)}" ${act('model',id)} role="button" tabindex="0">${t}<title>${e(id)} · ${subl(m)} · ${m.cols.length} columns</title></g>`});
 return ids.length?canvas(W,H,s):'<p class="note">No gold tables in this area.</p>';
}
function topicLineage(a){
 const tps=D.topics.filter(t=>t.area===a.id).sort((x,y)=>x.label.localeCompare(y.label));
 const NW=300,NH=36,GAP=10,CG=80,maxDepth=Math.max(1,...tps.flatMap(t=>t.joins.map(j=>j.depth)));
 const nc=2+maxDepth,W=32+nc*NW+(nc-1)*CG,X=i=>16+i*(NW+CG);
 let s=['SEMANTIC TOPIC','BASE VIEW',...Array.from({length:maxDepth},(_,i)=>'JOINED — LEVEL '+(i+1))].map((h,i)=>`<text x="${X(i)}" y="18" class="lh">${h}</text>`).join('');
 let y=32;
 tps.forEach(t=>{const rows=[1,...Array(maxDepth).fill(0)],pos={};pos[t.base]={x:X(1),y};
  t.joins.forEach(j=>{pos[j.to]={x:X(1+j.depth),y:y+rows[j.depth]*(NH+GAP)};rows[j.depth]++});
  const h=Math.max(1,...rows)*(NH+GAP)-GAP;
  s+=`<rect x="6" y="${y-6}" width="${W-12}" height="${h+12}" rx="8" class="tband"/>`;
  s+=curve(X(0)+NW,y+NH/2,X(1),y+NH/2,'rel',`${t.label} → ${t.base} (base view)`);
  t.joins.forEach(j=>{const p=pos[j.from],q=pos[j.to];if(p&&q)s+=curve(p.x+NW,p.y+NH/2,q.x,q.y+NH/2,'rel',`${j.from} → ${j.to}${j.card?` (${human(j.card)})`:''}${j.on?' on '+j.on:''}`)});
  s+=box(X(0),y,NW,NH,t.topic,t.label,`${t.views.length} views · ${t.dashboards.length} dashboard${t.dashboards.length===1?'':'s'}`,'topic','topic','Topic '+t.label);
  Object.entries(pos).forEach(([id,p])=>{const m=M[id];s+=box(p.x,p.y,NW,NH,id,tr(id,42),m?subl(m):'not a model in this review',m?kind(m):'reuse','model',id)});
  y+=h+24});
 return canvas(W,y,s);
}
let MA=null,MS='pipeline';
function rModel(){
 if(!D.areas.length){byId('v-model').innerHTML='<h1>Data model</h1><p class="note">No subject areas in this review.</p>';return}
 byId('v-model').innerHTML=`<h1>Data model</h1><p class="meta">Pick a subject area, then a view. Click any table for grain, keys, columns, lineage and its code; click a topic for its joins, fields and dashboards. Hover a line for the join.</p>
 <div class="lg"><span><i style="background:${COL.reuse}"></i>reuse</span><span><i style="background:${COL.extend}"></i>extend</span><span><i style="background:${COL.create}"></i>create</span><span><i style="background:${COL.shared}"></i>shared interface (other domain)</span><span><i style="background:${COL.topic}"></i>semantic topic</span><span class="note">— dashed border = owned by another domain</span></div>
 <div class="pills" id="apills">${D.areas.map(a=>`<button type="button" data-a="${e(a.id)}" ${act('area',a.id)}>${e(a.name)} <span>${a.gold.length} gold</span></button>`).join('')}</div>
 <div class="pills sub" id="spills"></div><div id="abody"></div>`;
 drawArea(MA||D.areas[0].id)}
function drawArea(id,sub){const a=D.areas.find(x=>x.id===id);if(!a)return;MA=id;if(sub)MS=sub;
 const tps=D.topics.filter(t=>t.area===a.id);
 const subs=[a.pipeline.length&&['pipeline','Pipeline'],['rel','Gold relationships'],tps.length&&['topics','Semantic topics']].filter(Boolean);
 if(!subs.some(s=>s[0]===MS))MS=subs[0][0];
 document.querySelectorAll('#apills button').forEach(x=>x.classList.toggle('on',x.dataset.a===id));
 byId('spills').innerHTML=subs.map(([k,l])=>`<button type="button" class="${k===MS?'on':''}" ${act('sub',k)}>${l}</button>`).join('');
 const head={pipeline:'Pipeline — staging (bronze) → integration (silver) → warehouse (gold)',rel:'Gold relationships — facts and extended tables → dimensions',topics:'Semantic topics — topic → base view → joined views'}[MS];
 const note=a.shared?`<p class="note">Warehouse tables owned by other domains that the ${e(D.meta.domain_label)} tables and topics join to. Their pipelines belong to their own domains.</p>`:(tps.length?`<p class="note">Semantic topics in this area: ${tps.map(t=>topicLink(t.topic)).join(', ')}</p>`:'');
 byId('abody').innerHTML=`<h3 class="ah">${head}</h3>${note}${MS==='pipeline'?pipeline(a):MS==='rel'?erd(a):topicLineage(a)}`}

/* ---------- inspectors ---------- */
function openFileLinks(paths){return paths.map(p=>fileLink(p)).join('<br>')}
function inspTopic(n){const t=T[n];if(!t)return;const p=byId('insp'),f=FILES[t.path];
 p.innerHTML=`<button type="button" class="x" ${act('close','')}>Close</button><h2>${e(t.label)}</h2>
 <p><span class="b info">semantic topic</span>${t.group?' · '+e(t.group):''} · ${e(areaName[t.area]||t.area)} · <code>${e(t.topic)}</code></p>
 <p>${e(t.desc)}</p>
 <p><b>Base view:</b> ${link(t.base)}${M[t.base]&&M[t.base].grain?' <span class="note">— '+e(M[t.base].grain)+'</span>':''}</p>
 <h3>Joins (${t.joins.length})</h3>${t.joins.length?`<table><tr><th>From</th><th>To</th><th>Cardinality</th><th>On</th></tr>${t.joins.map(j=>`<tr><td>${link(j.from)}</td><td>${link(j.to)}</td><td>${e(human(j.card))}</td><td><code>${e(j.on)}</code></td></tr>`).join('')}</table>`:'<p class="note">No joins; the topic reads its base view only.</p>'}
 <h3>Dashboards served (${t.dashboards.length})</h3>${t.dashboards.length?`<table><tr><th>ID</th><th>Dashboard</th><th>Status</th></tr>${t.dashboards.map(x=>`<tr><td>${e(x.id)}</td><td>${e(x.title)}</td><td>${b(human(x.status))}</td></tr>`).join('')}</table>`:'<p class="note">No in-scope dashboard maps to this topic.</p>'}
 <h3>AI context</h3><p>${t.ai?e(t.ai):'<span class="note">none</span>'}</p>
 <h3>Fields (${t.fields.length} entries)</h3><p>${t.fields.map(x=>`<code>${e(x)}</code>`).join(' ')||'<span class="note">all fields of the joined views</span>'}</p>
 <h3>Files</h3><p>${openFileLinks([t.path,...Object.values(t.view_files)].filter(Boolean))}</p>
 ${f?`<h3>Code — ${e(t.path)}</h3><pre>${e(f.content)}</pre>`:''}`;
 p.classList.add('on');p.scrollTop=0}
function insp(n){const m=M[n];if(!m)return;const p=byId('insp');
 const keys=m.cols.filter(c=>c[2]),f=m.code&&FILES[m.code];
 const relTo=c=>{const r=D.rels.find(r=>r.from===n&&(r.key||'').startsWith(c+' '));return r?' → '+link(r.to):''};
 const ts=D.topics.filter(t=>t.views.includes(n));
 p.innerHTML=`<button type="button" class="x" ${act('close','')}>Close</button><h2>${e(m.id)}</h2>
 <p>${b(m.disp)} · ${e(m.layer)} · ${e(m.domain)}${m.area&&areaName[m.area]?' · '+e(areaName[m.area]):''}</p>
 <p><b>Grain:</b> ${m.grain?e(m.grain):'<span class="note">not stated in the model documentation</span>'}</p>
 <p><b>Existing source:</b> ${e(m.existing)}</p>
 <p><b>Code file:</b> ${m.code?fileLink(m.code):`<code>${e(m.source_path||'—')}</code> <span class="note">unchanged, not in this package</span>`}</p>
 <p>${e(m.desc)}</p>
 <h3>Keys</h3>${keys.length?keys.map(k=>`<div><code>${e(k[2])}</code> <code>${e(k[0])}</code>${relTo(k[0])}</div>`).join(''):'<p class="note">No keys declared.</p>'}
 <p><b>Semantic topics using this table:</b> ${ts.length?ts.map(t=>topicLink(t.topic)+(t.base===n?' (base view)':'')).join(', '):'none'}</p>
 <h3>Lineage</h3><p><b>Depends on:</b> ${m.dep.map(link).join(', ')||'source tables only'}${m.src.length?'<br><span class="note">Source tables: '+m.src.map(e).join(', ')+'</span>':''}</p><p><b>Used by:</b> ${m.used.map(link).join(', ')||'—'}</p>
 <h3>Security notes</h3>${m.sec.length?`<ul>${m.sec.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`:'<p class="note">None recorded.</p>'}
 <h3>Columns (${m.cols.length})</h3><table><tr><th>Column</th><th>Type</th><th>Description</th></tr>${m.cols.map(c=>`<tr><td><code>${e(c[0])}</code>${c[2]?' '+e(c[2]):''}</td><td>${e(c[1])}</td><td>${e(c[3])}</td></tr>`).join('')}</table>
 ${f?`<h3>Code — ${e(m.code)}</h3><pre>${e(f.content)}</pre>`:''}`;
 p.classList.add('on');p.scrollTop=0}

/* ---------- code & files ---------- */
const NOUN={topic:'topic file',view:'view file',relationships:'relationships file',model:'model file',dbt:'code file',other:'file'};
function rCode(){const ap=D.apply,mt=D.meta,ph=Object.create(null);
 ap.placeholders.forEach(p=>{(ph[p.label]=ph[p.label]||[]).push(p)});
 const groups=Object.entries(ph).map(([k,v])=>{const files=[...new Set(v.map(x=>x.file))],kinds=[...new Set(v.map(x=>x.kind))],noun=kinds.length===1?NOUN[kinds[0]]||'file':'file';
  return `<li><b>${e(k)}</b> — ${files.length} ${noun}${files.length===1?'':'s'}. <span class="note">${e(v[0].text)}</span></li>`});
 if(mt.access_note)groups.push(`<li>${e(mt.access_note)}</li>`);
 const ct=mt.code_target,st=mt.semantic_target;
 byId('v-code').innerHTML=`<h1>Code &amp; files</h1>
 <p class="meta">${ct.package_path?`Files under <code>${e(ct.package_path)}</code> drop in over <code>${e(ct.project_path||'the project root')}</code> at the same paths; files not listed are unchanged, and schema YAML files replace the file of the same name (compare with the main branch first).`:''}${st.connection?` Semantic views point at <code>${e(st.connection)}</code>${st.note?` (${e(st.note)})`:''}.`:''}</p>
 <h2>Source tables to add <span class="sub">${ap.new_sources.length}</span></h2>${ap.new_sources.length?`<p>${ap.new_sources.map(s=>`<code>${e(s)}</code>`).join(' ')}</p><p class="note">Declared in the new source files; check dataset names for your environment.</p>`:'<p class="note">None: every source is already declared.</p>'}
 <h2>Placeholders to replace</h2>${groups.length?`<ul>${groups.join('')}</ul>`:'<p class="note">None found in the semantic files.</p>'}
 <h2>Files <span class="sub">${D.files.length}</span></h2>
 <div class="files"><div><input class="q" placeholder="Filter files…" id="fq"><select class="s" id="fk"><option value="">all</option><option value="new">new</option><option value="changed">changed</option></select><ul id="flist"></ul></div><pre id="fview">Select a file.</pre></div>`;
 byId('fq').oninput=renderFiles;byId('fk').onchange=renderFiles;renderFiles()}
let cur=null;
function renderFiles(){const q=(byId('fq').value||'').toLowerCase(),k=byId('fk').value;
 byId('flist').innerHTML=D.files.filter(f=>(!k||f.status===k)&&f.path.toLowerCase().includes(q)).map(f=>`<li ${act('file',f.path)}${f.path===cur?' class="on"':''}>${b(f.status)} ${e(f.path)}</li>`).join('')}
function openFile(p){if(!built.code){rCode();built.code=1}cur=p;const f=FILES[p];byId('fview').textContent=f?('// '+f.path+' · '+f.status+'\n\n'+f.content):'';
 document.querySelectorAll('#flist li').forEach(li=>li.classList.toggle('on',li.dataset.v===p))}

/* ---------- decisions ---------- */
function rDecisions(){const areas=[...new Set(D.decisions.map(d=>d.area))].sort();
 byId('v-decisions').innerHTML=`<h1>Decisions</h1><p class="meta">${e(D.notes.decisions)}</p>
 <input class="q" placeholder="Filter…" id="dq"><select class="s" id="ds"><option value="">all statuses</option><option>answered</option><option>assumed</option><option>open</option></select><select class="s" id="da"><option value="">all areas</option>${areas.map(a=>`<option>${e(a)}</option>`).join('')}</select> <span class="note" id="dn"></span>
 <div class="tw"><table id="tdec"><thead><tr><th>ID</th><th>Area</th><th>Question</th><th>Options</th><th>Assumed option</th><th>Status</th></tr></thead><tbody></tbody></table></div>`;
 ['dq','ds','da'].forEach(i=>byId(i)[i==='dq'?'oninput':'onchange']=drawDec);drawDec()}
function drawDec(){const q=byId('dq').value.toLowerCase(),s=byId('ds').value,a=byId('da').value;
 const rows=D.decisions.filter(d=>(!s||d.status===s)&&(!a||d.area===a)&&(d.id+' '+d.q+' '+d.assumed+' '+d.detail).toLowerCase().includes(q));
 $('#tdec tbody').innerHTML=rows.map(d=>`<tr><td style="white-space:nowrap">${e(d.id)}</td><td>${e(d.area)}</td><td>${e(d.q)}${d.detail?`<div class="note">${e(d.detail)}</div>`:''}${d.models.length?`<div class="note">Models: ${d.models.map(link).join(', ')}</div>`:''}</td><td>${d.opts.length?d.opts.map(e).join('<br>'):'—'}</td><td>${e(d.assumed)||'—'}</td><td>${b(d.status)}</td></tr>`).join('');
 byId('dn').textContent=rows.length+' of '+D.decisions.length}
function goDec(id){show('decisions');byId('dq').value=id;drawDec()}

/* ---------- legacy ---------- */
const LST=['covered','partially covered','retire candidate','out of domain','unresolved'];
function rLegacy(){const tl=Object.create(null);D.topics.forEach(t=>tl[t.topic]=t.label);
 const rows=[...D.legacy].sort((x,y)=>LST.indexOf(x.status)-LST.indexOf(y.status)||x.legacy.localeCompare(y.legacy));
 byId('v-legacy').innerHTML=`<h1>Legacy coverage</h1>
 ${rows.length?`<p class="meta">${LST.map(s=>s+' '+D.legacy.filter(r=>r.status===s).length).join(' · ')}</p>
 <p class="note"><b>covered</b>: already a warehouse table, reused or extended · <b>retire candidate</b>: fully replaced by a new table, retire after reconciliation · <b>partially covered</b>: replaced, some fields not carried or rules changed · <b>out of domain</b>: another domain's model; the cross-domain topic is named where one serves it · <b>unresolved</b>: no definition or no target yet.</p>
 <input class="q" placeholder="Filter legacy models…" id="lq">
 <div class="tw"><table id="tleg"><thead><tr><th>Legacy model</th><th>Status</th><th>Target</th><th>Semantic topic</th><th>Note</th></tr></thead><tbody>${rows.map(r=>{
  let t=r.topics.length?r.topics.slice(0,3).map(x=>e(tl[x]||x)).join(', ')+(r.topics.length>3?` <span class="note">+${r.topics.length-3} more</span>`:''):'—';
  if(r.status==='out of domain')t=r.cross_topics.length?'cross-domain topic: <b>'+r.cross_topics.map(x=>e(tl[x]||x)).join(', ')+'</b>':`<span class="note">no topic in this delivery${r.domain?' ('+e(human(r.domain))+')':''}</span>`;
  return `<tr><td><code>${e(r.legacy)}</code><div class="note">${e(r.source)}</div></td><td>${b(r.status)}</td><td>${r.targets.map(link).join('<br>')||'—'}</td><td>${t}</td><td>${e(r.note)}</td></tr>`}).join('')}</tbody></table></div>`:'<p class="note">No legacy models were supplied for this review.</p>'}`;
 if(byId('lq'))byId('lq').oninput=ev=>filt(ev.target,'tleg')}

/* ---------- dictionary ---------- */
let DICT=null;
function rDict(){DICT=[];D.models.forEach(m=>m.cols.forEach(c=>DICT.push([m.layer,m.id,m.disp,c[0],c[1],c[2],c[3],m.code||m.source_path||''])));
 byId('v-dict').innerHTML=`<h1>Data dictionary</h1><p class="meta">${D.models.length} models · ${DICT.length.toLocaleString('en-GB')} columns. Types come from the design specification where stated; blank types are not documented and are confirmed only by a build.</p>
 <input class="q" placeholder="Search models and columns…" id="xq"><select class="s" id="xl"><option value="">all layers</option><option>gold</option><option>silver</option><option>bronze</option></select> <span class="note" id="xn"></span>
 <div class="tw"><table id="tdict"><thead><tr><th>Layer</th><th>Model</th><th>Status</th><th>Column</th><th>Type</th><th>Description</th><th>Code file</th></tr></thead><tbody></tbody></table></div>`;
 byId('xq').oninput=drawDict;byId('xl').onchange=drawDict;drawDict()}
function drawDict(){const q=byId('xq').value.toLowerCase(),l=byId('xl').value;const rows=DICT.filter(r=>(!l||r[0]===l)&&(!q||(r[1]+' '+r[3]+' '+r[6]).toLowerCase().includes(q)));
 $('#tdict tbody').innerHTML=rows.slice(0,400).map(r=>`<tr><td>${e(r[0])}</td><td>${link(r[1])}</td><td>${e(r[2])}</td><td><code>${e(r[3])}</code>${r[5]?' '+e(r[5]):''}</td><td>${e(r[4])}</td><td>${e(r[6])}</td><td>${fileLink(r[7])}</td></tr>`).join('');
 byId('xn').textContent=(rows.length>400?'showing 400 of ':'')+rows.length.toLocaleString('en-GB')+' columns'}

/* ---------- validation ---------- */
function rValid(){byId('v-valid').innerHTML=`<h1>Validation</h1><p class="meta">${e(D.notes.validation)}</p>
 <table><thead><tr><th>Check</th><th>Count</th><th>Status</th><th>Scope</th></tr></thead><tbody>${D.static.map(s=>`<tr><td>${e(s.label)}${s.items.length?`<div class="note">${s.items.slice(0,20).map(e).join('<br>')}${s.items.length>20?'<br>…':''}</div>`:''}</td><td>${s.count}</td><td>${b(s.count?'fail':'pass')}</td><td>${e(s.of)}</td></tr>`).join('')}</tbody></table>
 <h2>Remaining breaks and unknowns</h2>${D.remaining.length?`<ul>${D.remaining.map(r=>`<li>${e(r)}</li>`).join('')}</ul>`:'<p class="note">None recorded.</p>'}
 ${D.checks.length?`<h2>Other recorded checks</h2><div class="tw"><table><thead><tr><th>Check</th><th>Scope</th><th>Status</th><th>Detail</th></tr></thead><tbody>${D.checks.map(v=>`<tr><td>${e(v.label)}</td><td>${e(v.scope)}</td><td>${b(human(v.status))}</td><td>${e(v.actual)}${v.details?`<div class="note">${e(v.details)}</div>`:''}</td></tr>`).join('')}</tbody></table></div>`:''}`}

/* ---------- open items ---------- */
function rTodos(){byId('v-todos').innerHTML=`<h1>Open items</h1><p class="meta">Everything the authors could not confirm (${D.open.length}). "Meanwhile" is what the candidate does until it is answered.</p>
 <input class="q" placeholder="Filter…" id="oq">
 <div class="tw"><table id="ttodo"><thead><tr><th>ID</th><th>Kind</th><th>Question</th><th>Who answers</th><th>Meanwhile</th></tr></thead><tbody>${D.open.map(o=>`<tr><td style="white-space:nowrap">${DEC[o.id]?`<a href="#decisions" ${act('decision',o.id)}>${e(o.id)}</a>`:e(o.id)}</td><td>${e(o.kind)}</td><td>${e(o.text)}</td><td>${e(o.owner)}</td><td>${e(o.meanwhile)}</td></tr>`).join('')}</tbody></table></div>`;
 byId('oq').oninput=ev=>filt(ev.target,'ttodo')}

/* ---------- events ---------- */
const R={overview:rOverview,model:rModel,code:rCode,decisions:rDecisions,legacy:rLegacy,dict:rDict,valid:rValid,todos:rTodos};
const ACTIONS={show:v=>{closeInsp();show(v)},model:insp,topic:inspTopic,area:v=>drawArea(v),sub:v=>drawArea(MA,v),
 file:v=>{closeInsp();show('code');openFile(v)},decision:goDec,close:closeInsp};
document.addEventListener('click',ev=>{const t=ev.target.closest('[data-act]');if(!t)return;ev.preventDefault();ACTIONS[t.dataset.act]?.(t.dataset.v)});
document.addEventListener('keydown',ev=>{if(ev.key==='Escape')closeInsp();
 if((ev.key==='Enter'||ev.key===' ')&&ev.target.dataset&&ev.target.dataset.act){ev.preventDefault();ev.target.click()}});
show(location.hash.slice(1)||'overview');
