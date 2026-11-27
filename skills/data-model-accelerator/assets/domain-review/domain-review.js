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
 if(location.hash!=='#'+v)history.replaceState(null,'','#'+v);window.scrollTo(0,0);if(v==='model')checkJump()}
function filt(inp,id){const q=inp.value.toLowerCase();document.querySelectorAll('#'+id+' tbody tr').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q)?'':'none')}
const closeInsp=()=>byId('insp').classList.remove('on');

/* ---------- overview ---------- */
function rOverview(){
 const c=D.cards,mt=D.meta,L=c.layers,Lg=c.legacy,Dc=c.decisions,Ds=c.dashboards;
 const tot=['bronze','silver','gold'].reduce((s,l)=>s+L[l].reuse+L[l].extend+L[l].create+L[l].unassessed,0);
 const cards=[
  [tot,'models in scope',['gold','silver','bronze'].map(l=>`${l}: reuse ${L[l].reuse} · extend ${L[l].extend} · create ${L[l].create} · ${L[l].unassessed} unassessed`).join('<br>')],
  [c.code.new+c.code.changed+c.code.unassessed,'selected warehouse code files',`${c.code.new} new (${c.code.new_sql} models) · ${c.code.changed} change existing files (${c.code.changed_sql} models) · ${c.code.unassessed} change status unassessed`],
  [c.semantic.topics,'semantic topics',`${c.semantic.views} view files included · ${c.semantic.relationships} resolved join definitions<br>${c.semantic.cross_domain_topics} cross-domain topics`]];
 if(c.legacy_total)cards.push([c.legacy_total,'legacy models accounted for',`covered ${Lg.covered} · partially ${Lg['partially covered']} · retire candidate ${Lg['retire candidate']}<br>out of domain ${Lg['out of domain']} · unresolved ${Lg.unresolved}`]);
 cards.push([Dc.answered+Dc.assumed+Dc.open+Dc.unassessed,'decisions',`answered ${Dc.answered} · assumed ${Dc.assumed} · open ${Dc.open} · ${Dc.unassessed} unassessed`]);
 if(D.dashboards.length)cards.push([D.dashboards.length,'dashboards in scope',`served ${Ds.served} · partly served ${Ds.partly_served} · not served ${Ds.not_served} · ${Ds.unassessed} unassessed`]);
 const tool=mt.repositories.find(r=>r.role==='Tooling'&&r.commit);
 const facts=[mt.scope_label,D.dashboards.length?`${D.dashboards.length} dashboards in scope`:null,...mt.facts].filter(Boolean).map(e);
 if(tool)facts.push(`${e(tool.name)} rev <code>${e(tool.commit.slice(0,7))}</code>`);
 byId('v-overview').innerHTML=`
<h1>${e(mt.title)} <span class="sub">${e(mt.subtitle)}</span></h1>
<p class="meta">${facts.join(' · ')}</p>
<div class="banner">${e(mt.banner)}</div>
<div class="cards">${cards.map(([n,l,d])=>`<div class="card"><div class="n">${n}</div><div class="l">${e(l)}</div><div class="d">${d}</div></div>`).join('')}</div>
<h2>Read in this order</h2>
<ol>${D.reading_order.map(r=>`<li>${r.view?go(r.view,r.label):e(r.label)}${r.text?': '+e(r.text):''}</li>`).join('')}</ol>
${D.dashboards.length?`<h2>Dashboards</h2>
<div class="tw"><table><thead><tr><th>ID</th><th>Dashboard</th><th>Status</th><th>Query tiles</th><th>Topics</th><th>Reason</th></tr></thead><tbody>${D.dashboards.map(x=>`<tr><td style="white-space:nowrap">${e(x.asset_type==='look'?'Look '+x.asset_id:x.asset_id)}</td><td>${e(x.title)}</td><td>${b(human(x.status))}</td><td style="white-space:nowrap">${x.n_query_tiles==null?'<span class="note">not counted</span>':`${e(x.n_served==null?'unknown':x.n_served)} served<br>${e(x.n_partly_served==null?'unknown':x.n_partly_served)} partly<br>${e(x.n_not_served==null?'unknown':x.n_not_served)} not`}</td><td>${x.topics.map(t=>topicLink(t,t)).join(', ')||'—'}</td><td class="note">${e(x.reason)}${x.scope_reason?`<br>${e(x.scope_reason)}`:''}</td></tr>`).join('')}</tbody></table></div>`:''}
<h2>Not done yet</h2>
<ul>${D.not_done.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`;
}

/* ---------- data model ---------- */
const COL={create:'#2f9e5b',extend:'#e0952b',reuse:'#8a94a6',shared:'#4a5bdc',topic:'#e8306e'};
function box(x,y,w,h,id,l1,l2,k,a,tip,hl){const c=COL[k]||COL.reuse;
 return `<g class="nd k-${k}${hl?' focus':''}" ${act(a,id)} role="button" tabindex="0"><rect class="bg" x="${x}" y="${y}" width="${w}" height="${h}" rx="5" style="stroke:${c}"/><rect x="${x}" y="${y}" width="5" height="${h}" rx="2" style="fill:${c}"/><text class="t1" x="${x+14}" y="${y+16}">${e(l1)}</text>${l2?`<text class="t2" x="${x+14}" y="${y+29}">${e(l2)}</text>`:''}<title>${e(tip||id)}</title></g>`}
function curve(x1,y1,x2,y2,cls,tip){const m=(x1+x2)/2,d=`M${x1} ${y1} C${m} ${y1} ${m} ${y2} ${x2} ${y2}`;
 return tip?`<g><path d="${d}" class="relhit"><title>${e(tip)}</title></path><path d="${d}" class="${cls}"/></g>`:`<path d="${d}" class="${cls}"/>`}
const canvas=(W,H,s)=>`<div class="wide canvas"><svg viewBox="0 0 ${W} ${H}" style="min-width:${Math.min(W,1100)}px">${s}</svg></div>`;
/* ---------- pipeline: layered layout, lineage filter, zoom and pan ---------- */
const PL={NW:360,NH:36,GAP:10,CG:96,LG:70,PAD:16,TOP:58};
const LAYERS=['bronze','silver','gold'],LNAME={bronze:'Bronze',silver:'Silver',gold:'Gold'},LROLE={bronze:'staging',silver:'integration',gold:'warehouse'};
const USED=Object.create(null);D.models.forEach(m=>USED[m.id]=[]);
D.models.forEach(m=>m.dep.forEach(d=>{if(USED[d]&&!USED[d].includes(m.id))USED[d].push(m.id)}));
function walk(id,next){const s=new Set([id]),st=[id];while(st.length){const n=st.pop();(next(n)||[]).forEach(d=>{if(M[d]&&!s.has(d)){s.add(d);st.push(d)}})}return s}
function upstream(id){return walk(id,n=>(M[n]||{}).dep)}
function downstream(id){return walk(id,n=>USED[n])}
function lineageOf(id){return new Set([...upstream(id),...downstream(id)])}
function pav(z){const v=[],w=[];z.forEach(x=>{v.push(x);w.push(1);while(v.length>1&&v[v.length-2]>v[v.length-1]){const b2=v.pop(),bw=w.pop(),a2=v.pop(),aw=w.pop();v.push((a2*aw+b2*bw)/(aw+bw));w.push(aw+bw)}});
 const out=[];v.forEach((x,i)=>{for(let k=0;k<w[i];k++)out.push(x)});return out}
function layoutPipe(ids){const {NW,NH,GAP,CG,LG,PAD,TOP}=PL,R=NH+GAP,S=new Set(ids.filter(i=>M[i]));
 const deps=id=>M[id].dep.filter(d=>S.has(d)&&d!==id),step=Object.create(null);
 const st=id=>{if(step[id]!=null)return step[id];step[id]=1;let k=1;deps(id).forEach(d=>{if(M[d].layer===M[id].layer)k=Math.max(k,st(d)+1)});return step[id]=k};
 const cols=[];LAYERS.forEach(l=>{const its=[...S].filter(i=>M[i].layer===l);if(!its.length)return;const n=Math.max(...its.map(st));
  for(let k=1;k<=n;k++)cols.push({layer:l,step:k,ids:its.filter(i=>step[i]===k).sort((x,y)=>(isShared(M[x])-isShared(M[y]))||x.localeCompare(y))})});
 const edges=[];S.forEach(t=>deps(t).forEach(s=>edges.push([s,t])));
 const nb=Object.create(null),preds=Object.create(null),succs=Object.create(null);S.forEach(i=>{nb[i]=[];preds[i]=[];succs[i]=[]});
 edges.forEach(([s,t])=>{nb[s].push(t);nb[t].push(s);preds[t].push(s);succs[s].push(t)});
 const ci=Object.create(null);cols.forEach((c,k)=>c.ids.forEach(i=>ci[i]=k));
 const Y=Object.create(null);cols.forEach(c=>c.ids.forEach((i,r)=>Y[i]=TOP+r*R));
 const crossings=()=>{let n=0;for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++){const [a1,b1]=edges[i],[a2,b2]=edges[j];
  if(ci[a1]===ci[a2]&&ci[b1]===ci[b2]&&a1!==a2&&b1!==b2&&(Y[a1]-Y[a2])*(Y[b1]-Y[b2])<0)n++}return n};
 const snap=()=>({o:cols.map(c=>c.ids.slice()),y:Object.assign(Object.create(null),Y)});
 let best=snap(),bestX=crossings();
 const big=cols.reduce((m,c)=>c.ids.length>m.ids.length?c:m,cols[0]||{ids:[]});
 for(let it=0;it<12&&cols.length>1;it++){const seq=it%2?cols.slice().reverse():cols;
  seq.forEach(c=>{if(it===0&&c===big)return;
   const des=Object.create(null);c.ids.forEach(i=>{const n=nb[i];des[i]=n.length?n.reduce((s2,x)=>s2+Y[x],0)/n.length:Y[i]});
   c.ids.sort((x,y)=>des[x]-des[y]||Y[x]-Y[y]);
   const fit=pav(c.ids.map((i,r)=>des[i]-r*R));c.ids.forEach((i,r)=>Y[i]=fit[r]+r*R)});
  const lo=Math.min(...Object.values(Y));Object.keys(Y).forEach(i=>Y[i]=Y[i]-lo+TOP);
  const x=crossings();if(x<bestX||(x===bestX&&it>0)){best=snap();bestX=x}}
 cols.forEach((c,k)=>c.ids=best.o[k]);Object.assign(Y,best.y);Object.keys(Y).forEach(i=>Y[i]=Math.round(Y[i]));
 const X=Object.create(null),bands=[];let x=PAD;
 LAYERS.forEach(l=>{const lc=cols.filter(c=>c.layer===l);if(!lc.length)return;
  lc.forEach((c,k)=>{c.x=x+PAD+k*(NW+CG);c.ids.forEach(i=>X[i]=c.x)});
  const w=2*PAD+lc.length*NW+(lc.length-1)*CG;bands.push({layer:l,x,w,n:lc.reduce((s2,c)=>s2+c.ids.length,0),cols:lc});x+=w+LG});
 const W=Math.max(x-LG+PAD,NW+4*PAD),H=Math.max(TOP+R,...Object.values(Y).map(y=>y+NH+PAD+6));
 return {ids:[...S],cols,bands,edges,X,Y,W,H,preds,succs,crossings:bestX}}
function pnode(id,x,y,sel){const {NW,NH}=PL,m=M[id],k=kind(m),c=COL[k]||COL.reuse,sub=subl(m)+(m.src.length?' · '+m.src.length+' source table'+(m.src.length>1?'s':''):''),ix=x+NW-17,iy=y+NH/2;
 return `<g class="nd k-${k} pn${sel?' focus':''}" data-id="${e(id)}" ${act('lineage',id)} role="button" tabindex="0" aria-label="${e('Filter to the lineage of '+id)}"><rect class="bg" x="${x}" y="${y}" width="${NW}" height="${NH}" rx="5" style="stroke:${c}"/><rect x="${x}" y="${y}" width="5" height="${NH}" rx="2" style="fill:${c}"/><text class="t1" x="${x+14}" y="${y+16}">${e(tr(id,44))}</text><text class="t2" x="${x+14}" y="${y+29}">${e(tr(sub,54))}</text><title>${e(`${id} · ${subl(m)}${m.src.length?'\nSources: '+m.src.join(', '):''}`)}</title><g class="pinfo" ${act('model',id)} role="button" tabindex="0" aria-label="${e('Details of '+id)}"><circle cx="${ix}" cy="${iy}" r="8"/><text x="${ix}" y="${iy+4}" text-anchor="middle">i</text><title>Details</title></g></g>`}
let PIPE=null,PZ=1,LIN=null,HIST=[],PEND=null,DRAG=null;const Z={full:1,foc:1,lin:1};
const zkey=()=>LIN?'lin':FOC?'foc':'full';
function pipeline(a){const {NW,NH}=PL,ids=LIN?[...lineageOf(LIN)]:a.pipeline,L=layoutPipe(ids);PIPE=L;
 let s=`<defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L8 4L0 8z" fill="#8f8799"/></marker><marker id="ahp" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L8 4L0 8z" fill="#e8306e"/></marker></defs>`;
 L.bands.forEach(b=>{s+=`<rect class="band b-${b.layer}" id="band-${b.layer}" x="${b.x}" y="4" width="${b.w}" height="${L.H-8}" rx="10"/><text class="bh" x="${b.x+PL.PAD}" y="24">${LNAME[b.layer].toUpperCase()} (${LROLE[b.layer]}) · ${b.n} table${b.n===1?'':'s'}</text>`;
  b.cols.forEach(c=>s+=`<text class="lh" x="${c.x}" y="46">${c.layer.toUpperCase()} · step ${c.step} · ${c.ids.length} model${c.ids.length===1?'':'s'}</text>`)});
 L.edges.forEach(([f,t])=>{const x1=L.X[f]+NW,y1=L.Y[f]+NH/2,x2=L.X[t]-2,y2=L.Y[t]+NH/2,bend=x2>x1?(x2-x1)/2:90;
  const d=x2>x1?`M${x1} ${y1} C${x1+bend} ${y1} ${x2-bend} ${y2} ${x2} ${y2}`:`M${x1} ${y1} C${x1+bend} ${y1} ${x2-bend} ${y2} ${x2} ${y2}`;
  s+=`<g class="pe" data-s="${e(f)}" data-t="${e(t)}"><path d="${d}" class="relhit"><title>${e(f+' → '+t)}</title></path><path d="${d}" class="edge arr"/></g>`});
 L.ids.forEach(id=>s+=pnode(id,L.X[id],L.Y[id],LIN?id===LIN:id===FOC));
 const nu=LIN?upstream(LIN).size-1:0,nd=LIN?downstream(LIN).size-1:0;
 const bar=LIN?`<div class="lbar" id="lbar"><span>Lineage of <code>${e(LIN)}</code> · ${nu} upstream · ${nd} downstream</span><span class="lbtn">${HIST.length?`<button type="button" ${act('linback','')}>← Back</button>`:''}<button type="button" ${act('linclose','')}>× Close lineage view</button></span></div>`:'';
 return `<p class="note">Scroll, or drag the background, to move around. Pinch, or hold Ctrl/⌘ and scroll, to zoom. Hover a table to trace its lineage, click it to show only its lineage, and use ⓘ for its details. Arrows point from a table to the table built on it.</p>
 <div class="ptools bo"><div class="pjump" id="pjump">Jump to: ${L.bands.map(b=>`<button type="button" ${act('jump',b.layer)}>${LNAME[b.layer]} <span>${b.n}</span></button>`).join(' / ')}</div><div class="pzoom"><button type="button" ${act('zoom','out')} aria-label="Zoom out" title="Zoom out">−</button><span id="pzl">${Math.round(Z[zkey()]*100)}%</span><button type="button" ${act('zoom','in')} aria-label="Zoom in" title="Zoom in">+</button><button type="button" ${act('zoom','fit')}>Fit</button><button type="button" ${act('zoom','100')}>100%</button></div></div>
 <div class="pframe bo" id="pframe">${bar}<svg id="psvg" viewBox="0 0 ${L.W} ${L.H}" width="${L.W}" height="${L.H}" role="img" aria-label="Pipeline">${s}</svg></div>`}
const barH=()=>{const b=byId('lbar');return b&&b.offsetHeight||0};
function sizeTo(z){const f=byId('pframe'),svg=byId('psvg');if(!PIPE||!svg||!svg.style)return;PZ=z;Z[zkey()]=z;svg.style.width=Math.round(PIPE.W*z)+'px';svg.style.height=Math.round(PIPE.H*z)+'px';
 const l=byId('pzl');if(l)l.textContent=Math.round(z*100)+'%';checkJump()}
function zoomTo(z,cx,cy){const f=byId('pframe');if(!f||!PIPE||!f.getBoundingClientRect)return;z=Math.min(2,Math.max(.1,z));const old=PZ,bh=barH();
 if(cx==null){cx=f.clientWidth/2;cy=(f.clientHeight+bh)/2}
 const px=(f.scrollLeft+cx)/old,py=(f.scrollTop+cy-bh)/old;sizeTo(z);f.scrollLeft=px*z-cx;f.scrollTop=py*z-cy+bh;checkJump()}
function fitZoom(){const f=byId('pframe');if(!f||!PIPE||!f.getBoundingClientRect)return;const bh=barH(),h=(window.innerHeight||800)-150-bh-4;
 sizeTo(Math.max(.1,Math.min(1,(f.clientWidth-4)/PIPE.W,h/PIPE.H)));f.scrollLeft=0;f.scrollTop=0;checkJump()}
function checkJump(){const f=byId('pframe'),j=byId('pjump');if(!f||!j||f.scrollWidth==null)return;j.hidden=f.scrollWidth<=f.clientWidth+1&&f.scrollHeight<=f.clientHeight+1}
function jump(l){const f=byId('pframe'),b=PIPE&&PIPE.bands.find(x=>x.layer===l);if(!f||!b||!f.getBoundingClientRect)return;
 const y0=Math.min(...b.cols[0].ids.map(i=>PIPE.Y[i]));f.scrollTo({left:Math.max(0,(b.x-8)*PZ),top:Math.max(0,(y0-PL.TOP)*PZ),behavior:'smooth'});
 const h=document.querySelector('header'),r=f.getBoundingClientRect(),off=(h?h.offsetHeight:0)+8;if(r.top<off||r.top>(window.innerHeight||800)/2)window.scrollBy({top:r.top-off,behavior:'smooth'});
 const band=byId('band-'+l);if(band){band.classList.remove('flash');void band.getBoundingClientRect();band.classList.add('flash');setTimeout(()=>band.classList.remove('flash'),1300)}}
function hl(id){const svg=byId('psvg');if(!svg||!svg.querySelectorAll||!PIPE)return;svg.querySelectorAll('.on').forEach(x=>x.classList.remove('on'));svg.classList.toggle('hl',!!id);if(!id)return;
 const up=walk(id,n=>PIPE.preds[n]),dn=walk(id,n=>PIPE.succs[n]);
 svg.querySelectorAll('.pn').forEach(n=>{if(up.has(n.dataset.id)||dn.has(n.dataset.id))n.classList.add('on')});
 svg.querySelectorAll('.pe').forEach(g=>{const s2=g.dataset.s,t=g.dataset.t;if((up.has(s2)&&up.has(t))||(dn.has(s2)&&dn.has(t)))g.classList.add('on')})}
function pipeInit(){const f=byId('pframe'),svg=byId('psvg');if(!f||!svg||!f.getBoundingClientRect)return;
 PZ=Z[zkey()];sizeTo(PZ);const p=PEND;PEND=null;f.scrollLeft=p?p.l:0;f.scrollTop=p?p.t:0;checkJump();
 f.addEventListener('wheel',ev=>{if(!(ev.ctrlKey||ev.metaKey))return;ev.preventDefault();const r=f.getBoundingClientRect(),dy=ev.deltaMode?ev.deltaY*40:ev.deltaY;
  zoomTo(PZ*(Math.abs(dy)>=40?(dy<0?1.2:1/1.2):Math.exp(-dy*.01)),ev.clientX-r.left,ev.clientY-r.top)},{passive:false});
 let g0=1;f.addEventListener('gesturestart',ev=>{ev.preventDefault();g0=PZ});
 f.addEventListener('gesturechange',ev=>{ev.preventDefault();const r=f.getBoundingClientRect();zoomTo(g0*ev.scale,ev.clientX-r.left,ev.clientY-r.top)});
 f.addEventListener('pointerdown',ev=>{const r=f.getBoundingClientRect();if(ev.button!==0||ev.target.closest('.nd,.pe,.lbar')||ev.clientX-r.left>f.clientWidth||ev.clientY-r.top>f.clientHeight)return;
  DRAG={x:ev.clientX,y:ev.clientY,l:f.scrollLeft,t:f.scrollTop};f.setPointerCapture(ev.pointerId);f.classList.add('drag');ev.preventDefault()});
 f.addEventListener('pointermove',ev=>{if(!DRAG)return;f.scrollLeft=DRAG.l-(ev.clientX-DRAG.x);f.scrollTop=DRAG.t-(ev.clientY-DRAG.y)});
 const end=()=>{DRAG=null;f.classList.remove('drag')};f.addEventListener('pointerup',end);f.addEventListener('pointercancel',end);
 svg.addEventListener('mouseover',ev=>{const n=ev.target.closest('.pn');if(n)hl(n.dataset.id)});
 svg.addEventListener('mouseout',ev=>{const n=ev.target.closest('.pn');if(n&&!(ev.relatedTarget&&n.contains(ev.relatedTarget)))hl(null)});
 svg.addEventListener('focusin',ev=>{const n=ev.target.closest('.pn');if(n)hl(n.dataset.id)});svg.addEventListener('focusout',()=>hl(null))}
if(typeof window.addEventListener==='function')window.addEventListener('resize',checkJump);
function openLineage(id){if(!M[id])return;closeInsp();if(LIN)HIST.push(LIN);else{const f=byId('pframe');PEND=null;BASE=f&&f.getBoundingClientRect?{l:f.scrollLeft,t:f.scrollTop}:null}
 LIN=id;Z.lin=1;syncFilter();drawArea(MA,'pipeline')}
let BASE=null;
function lineageBack(){if(!HIST.length)return;LIN=HIST.pop();Z.lin=1;syncFilter();drawArea(MA,'pipeline')}
function closeLineage(){LIN=null;HIST=[];PEND=BASE;BASE=null;syncFilter();drawArea(MA,'pipeline')}
function erd(a){
 const g=new Set(a.gold),ids=a.erd.filter(i=>M[i]),isDim=i=>M[i].type==='dimension';
 const rels=D.rels.filter(r=>ids.includes(r.from)&&ids.includes(r.to)&&(a.focus?(r.from===a.focus||r.to===a.focus):(g.has(r.from)||a.shared)));
 const cols=a.focus?[[a.focus],ids.filter(i=>i!==a.focus).sort(),[]]:a.shared?[ids.filter(i=>!isDim(i)).sort(),ids.filter(isDim).sort(),[]]:[ids.filter(i=>g.has(i)&&!isDim(i)).sort(),ids.filter(i=>g.has(i)&&isDim(i)).sort(),ids.filter(i=>!g.has(i)).sort()];
 const BW=330,CG=90,P={};let H=0;
 const keys=i=>M[i].cols.filter(c=>c[2]==='PK'||c[2]==='FK');
 cols.forEach((col,ci)=>{let y=34;col.forEach(id=>{const k=keys(id).slice(0,8);const h=46+k.length*15;P[id]={x:16+ci*(BW+CG),y,h,k,more:keys(id).length-k.length};y+=h+16});H=Math.max(H,y)});
 const W=32+3*BW+2*CG;
 let s=(a.focus?['SELECTED TABLE','RELATED TABLES','']:a.shared?['FACTS & EXTENDED TABLES','DIMENSIONS','']:['THIS AREA — FACTS & EXTENDED TABLES','THIS AREA — DIMENSIONS','RELATED TABLES']).map((t,i)=>t?`<text x="${16+i*(BW+CG)}" y="18" class="lh">${t}</text>`:'').join('');
 rels.forEach(r=>{const p=P[r.from],q=P[r.to];if(!p||!q)return;const y1=p.y+18,y2=q.y+18,t=`${r.from} → ${r.to}${r.card?` (${human(r.card)})`:''}${r.key?' on '+r.key:''}${r.basis?' · from '+r.basis:''}`;
  if(p.x<q.x)s+=curve(p.x+BW,y1,q.x,y2,'rel',t);else if(p.x>q.x)s+=curve(p.x,y1,q.x+BW,y2,'rel',t);
  else{const x=p.x+BW,bx=x+Math.min(CG-8,26+Math.abs(y2-y1)/12),d=`M${x} ${y1} C${bx} ${y1} ${bx} ${y2} ${x} ${y2}`;s+=`<g><path d="${d}" class="relhit"><title>${e(t)}</title></path><path d="${d}" class="rel"/></g>`}});
 ids.forEach(id=>{const p=P[id];if(!p)return;const m=M[id],c=COL[kind(m)]||COL.reuse;
  let t=`<rect class="bg" x="${p.x}" y="${p.y}" width="${BW}" height="${p.h}" rx="5" style="stroke:${c}"/><rect x="${p.x}" y="${p.y}" width="5" height="${p.h}" rx="2" style="fill:${c}"/><text x="${p.x+14}" y="${p.y+17}" class="t1">${e(tr(id,46))}</text><text x="${p.x+14}" y="${p.y+31}" class="t2">${e(tr(m.grain||subl(m),58))}</text>`;
  p.k.forEach((k,i)=>t+=`<text x="${p.x+14}" y="${p.y+48+i*15}" class="t2"><tspan class="${k[2]==='PK'?'kp':'kf'}">${k[2]}</tspan> ${e(tr(k[0],46))}</text>`);
  if(p.more>0)t+=`<text x="${p.x+BW-10}" y="${p.y+p.h-6}" class="t2" text-anchor="end">+${p.more} keys</text>`;
  s+=`<g class="nd k-${kind(m)}${id===FOC?' focus':''}" ${act('model',id)} role="button" tabindex="0">${t}<title>${e(id)} · ${subl(m)} · ${m.cols.length} columns</title></g>`});
 return ids.length?canvas(W,H,s):'<p class="note">No gold tables in this area.</p>';
}
function occurrence(t,id){return (t.nodes||[]).find(n=>n.id===id)}
function occurrenceLabel(t,id){return occurrence(t,id)?.view_id||t.base_view||'Unresolved view'}
function bindingLabel(n){return n?.binding_status==='complete'?n.model_ids.join(', '):'Unverified warehouse binding'}
function occurrenceLinks(n){return n?.binding_status==='complete'?n.model_ids.map(link).join(', '):'<span class="b warn">Unverified warehouse binding</span>'}
const bindsTo=(t,id)=>(t.nodes||[]).some(n=>n.binding_status==='complete'&&n.model_ids.includes(id));
function topicLineage(a){
 const tps=D.topics.filter(t=>a.focus?bindsTo(t,a.focus):t.area===a.id).sort((x,y)=>x.label.localeCompare(y.label));
 const NW=300,NH=36,GAP=10,CG=80,maxDepth=Math.max(1,...tps.flatMap(t=>t.joins.map(j=>j.depth)));
 const nc=2+maxDepth,W=32+nc*NW+(nc-1)*CG,X=i=>16+i*(NW+CG);
 let s=['SEMANTIC TOPIC','BASE VIEW',...Array.from({length:maxDepth},(_,i)=>'JOINED — LEVEL '+(i+1))].map((h,i)=>`<text x="${X(i)}" y="18" class="lh">${h}</text>`).join('');
 let y=32;
 tps.forEach(t=>{const rows=[1,...Array(maxDepth).fill(0)],pos={};pos[t.base]={x:X(1),y};
  t.joins.forEach(j=>{pos[j.to]={x:X(1+j.depth),y:y+rows[j.depth]*(NH+GAP)};rows[j.depth]++});
  const h=Math.max(1,...rows)*(NH+GAP)-GAP;
  s+=`<rect x="6" y="${y-6}" width="${W-12}" height="${h+12}" rx="8" class="tband"/>`;
  s+=curve(X(0)+NW,y+NH/2,X(1),y+NH/2,'rel',`${t.label} → ${t.base_view} (base view)`);
  t.joins.forEach(j=>{const p=pos[j.from],q=pos[j.to];if(p&&q)s+=curve(p.x+NW,p.y+NH/2,q.x,q.y+NH/2,'rel',`${occurrenceLabel(t,j.from)} → ${occurrenceLabel(t,j.to)} (${j.status === 'resolved'?human(j.card):'unresolved relationship'})`)});
  s+=box(X(0),y,NW,NH,t.topic,t.label,`${t.views.length} views · ${t.dashboards.length} dashboard${t.dashboards.length===1?'':'s'}`,'topic','topic','Topic '+t.label);
  Object.entries(pos).forEach(([id,p])=>{const n=occurrence(t,id),label=occurrenceLabel(t,id);s+=box(p.x,p.y,NW,NH,t.topic,tr(label,42),tr(bindingLabel(n),48),'topic','topic',label+' · '+bindingLabel(n),!!FOC&&n?.binding_status==='complete'&&n.model_ids.includes(FOC))});
  y+=h+24});
 return canvas(W,y,s);
}
let MA=null,MS='pipeline',FOC=null;
/* ---------- table filter: a dropdown of every table, grouped by layer and subject area, that also accepts typed or pasted names ---------- */
const GOLD_ORDER=D.areas.flatMap(a=>a.gold.filter(g=>M[g]).slice().sort());
const homeArea=id=>D.areas.find(a=>a.gold.includes(id));
// The home of a bronze or silver table is the first subject area whose pipeline uses it, skipping shared areas when possible.
function tableHome(id){if(!M[id])return null;if(M[id].layer==='gold'&&homeArea(id))return homeArea(id);
 return D.areas.find(a=>!a.shared&&a.pipeline.includes(id))||D.areas.find(a=>a.pipeline.includes(id))||D.areas.find(a=>(a.erd||[]).includes(id))||null}
const GROUPS=[];LAYERS.forEach(l=>D.areas.forEach(a=>{const ids=D.models.filter(m=>m.layer===l&&tableHome(m.id)===a).map(m=>m.id).sort();
 if(ids.length)GROUPS.push({label:`${LNAME[l]} · ${a.name}`,ids})}));
const ALL_ORDER=GROUPS.flatMap(g=>g.ids);
const current=()=>LIN||FOC||'';
function focusArea(id){const h=homeArea(id),nb=D.rels.filter(r=>r.from===id||r.to===id).map(r=>r.from===id?r.to:r.from);
 return {id:h.id,name:h.name,focus:id,gold:[id],pipeline:[...upstream(id)],erd:[...new Set([id,...nb])].filter(x=>M[x]),shared:false}}
function cleanName(v){const strip=s=>s.trim().replace(/^[`'"\[(]+|[`'"\])]+$/g,'').trim();
 return strip(strip(String(v||'')).split('.').pop()).toLowerCase()}
let CQ='',CACT=-1,CITEMS=[];
const comboMatches=q=>ALL_ORDER.filter(g=>!q||g.toLowerCase().includes(q));
const exactName=q=>ALL_ORDER.find(g=>g.toLowerCase()===q);
function renderCombo(){const ul=byId('glist'),inp=byId('gfilter');if(!ul)return;
 CITEMS=comboMatches(CQ);
 if(!CITEMS.length){ul.innerHTML='<li class="fempty">No table matches</li>';CACT=-1}
 else{if(CACT>=CITEMS.length)CACT=CITEMS.length-1;
  const hl2=g=>{if(!CQ)return e(g);const i=g.toLowerCase().indexOf(CQ);return e(g.slice(0,i))+'<mark>'+e(g.slice(i,i+CQ.length))+'</mark>'+e(g.slice(i+CQ.length))};
  const cur=current();
  ul.innerHTML=GROUPS.map(gr=>{const its=gr.ids.filter(g=>CITEMS.includes(g));return its.length?`<li class="fgrp" role="presentation">${e(gr.label)}</li>`+its.map(g=>{const k=CITEMS.indexOf(g);return `<li role="option" id="gopt-${k}" data-g="${e(g)}" class="fopt${k===CACT?' act':''}${g===cur?' sel':''}" aria-selected="${g===cur}">${hl2(g)}</li>`}).join(''):''}).join('')}
 ul.hidden=false;inp.setAttribute('aria-expanded','true');if(CACT>=0)inp.setAttribute('aria-activedescendant','gopt-'+CACT);else inp.removeAttribute('aria-activedescendant');
 const act2=ul.querySelector('.act');if(act2)act2.scrollIntoView({block:'nearest'})}
function openCombo(q){CQ=q||'';CITEMS=comboMatches(CQ);CACT=CQ?Math.max(0,CITEMS.findIndex(g=>g.toLowerCase()===CQ)):CITEMS.indexOf(current());renderCombo();if(CACT<0)byId('glist').scrollTop=0}
function closeCombo(){const ul=byId('glist'),inp=byId('gfilter');if(ul)ul.hidden=true;if(inp){inp.setAttribute('aria-expanded','false');inp.removeAttribute('aria-activedescendant')}}
function syncFilter(){const s=byId('gfilter'),c=byId('gclear'),m=byId('gmsg');if(s)s.value=current();if(c)c.hidden=!current();if(m)m.textContent='';closeCombo()}
// Gold: the table across all three views. Bronze or silver: its pipeline lineage in its home area. Empty: clear.
function setFocus(id){const h=id&&tableHome(id);LIN=null;HIST=[];BASE=null;PEND=null;FOC=null;
 if(h&&M[id].layer==='gold'&&homeArea(id)){FOC=id;Z.foc=1;MA=h.id}
 else if(h){MA=h.id;MS='pipeline';LIN=id;Z.lin=1}
 syncFilter();if(byId('abody'))drawArea(MA)}
function pickArea(id){FOC=null;LIN=null;HIST=[];BASE=null;PEND=null;syncFilter();drawArea(id)}
function initCombo(){const inp=byId('gfilter'),ul=byId('glist'),tg=byId('gtoggle'),cl=byId('gclear'),wrap=byId('gwrap'),m=byId('gmsg');
 const restore=()=>{if(inp.value!==current()){inp.value=current();cl.hidden=!current()}};
 const typed=()=>inp.value&&inp.value!==current()?cleanName(inp.value):'';
 inp.addEventListener('focus',()=>{if(ul.hidden)openCombo(typed())});
 inp.addEventListener('click',()=>{if(ul.hidden)openCombo(typed())});
 inp.addEventListener('input',ev=>{cl.hidden=!inp.value&&!current();m.textContent='';const q=cleanName(inp.value),exact=exactName(q);
  if(exact&&(ev.inputType==='insertFromPaste'||inp.value.trim().length>exact.length+2)){closeCombo();setFocus(exact);return}
  openCombo(q)});
 inp.addEventListener('keydown',ev=>{const open=!ul.hidden;
  if(ev.key==='ArrowDown'||ev.key==='ArrowUp'){ev.preventDefault();if(!open){openCombo(typed());return}
   if(CITEMS.length){CACT=CACT<0?(ev.key==='ArrowDown'?0:CITEMS.length-1):(CACT+(ev.key==='ArrowDown'?1:-1)+CITEMS.length)%CITEMS.length;renderCombo()}}
  else if(ev.key==='Enter'){ev.preventDefault();const q=cleanName(inp.value),exact=exactName(q);
   if(open&&CACT>=0&&CITEMS[CACT]){closeCombo();setFocus(CITEMS[CACT])}else if(exact){closeCombo();setFocus(exact)}else if(!q)setFocus('');
   else{const hits=comboMatches(q);if(hits.length===1){closeCombo();setFocus(hits[0])}else m.textContent=hits.length?`${hits.length} tables match; pick one from the list.`:'No table matches.'}}
  else if(ev.key==='Escape'){ev.preventDefault();ev.stopPropagation();if(open){closeCombo();restore()}else setFocus('')}
  else if(ev.key==='Tab')closeCombo()});
 ul.addEventListener('mousedown',ev=>{ev.preventDefault();const li=ev.target.closest('[data-g]');if(li){closeCombo();setFocus(li.dataset.g)}});
 tg.addEventListener('mousedown',ev=>{ev.preventDefault();if(ul.hidden){openCombo('');inp.focus()}else closeCombo()});
 cl.addEventListener('click',()=>{setFocus('');inp.focus();openCombo('')});
 document.addEventListener('mousedown',ev=>{if(!wrap.contains(ev.target)){closeCombo();restore()}})}
function rModel(){
 if(!D.areas.length){byId('v-model').innerHTML='<h1>Data model</h1><p class="note">No subject areas in this review.</p>';return}
 byId('v-model').innerHTML=`<h1>Data model</h1><p class="meta">Pick a subject area, then a view, or filter to one table. In the pipeline, click a table to show only its lineage and use ⓘ for its grain, keys, columns and code; in the other views, click a table or topic for its details. Hover a line for the join.</p>
 <div class="lg"><span><i style="background:${COL.reuse}"></i>reuse</span><span><i style="background:${COL.extend}"></i>extend</span><span><i style="background:${COL.create}"></i>create</span><span><i style="background:${COL.shared}"></i>shared interface (other domain)</span><span><i style="background:${COL.topic}"></i>semantic topic</span><span class="note">— dashed border = owned by another domain</span></div>
 ${ALL_ORDER.length?`<div class="fbar"><label for="gfilter">Filter to a table</label><div class="fwrap" id="gwrap"><input id="gfilter" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="glist" autocomplete="off" spellcheck="false" placeholder="All tables (type to search, or pick from the list)"><button type="button" id="gclear" class="fx" aria-label="Clear filter" title="Clear filter" hidden>&times;</button><button type="button" id="gtoggle" class="fdrop" aria-label="Show tables" title="Show tables" tabindex="-1">&#9662;</button><ul id="glist" class="flist" role="listbox" hidden></ul></div><span id="gmsg" class="note" aria-live="polite"></span></div>`:''}
 <div class="pills" id="apills">${D.areas.map(a=>`<button type="button" data-a="${e(a.id)}" ${act('area',a.id)}>${e(a.name)} <span>${a.gold.length} gold</span></button>`).join('')}</div>
 <div class="pills sub" id="spills"></div><div id="abody"></div>`;
 if(ALL_ORDER.length)initCombo();syncFilter();drawArea(MA||D.areas[0].id)}
function drawArea(id,sub){const base=D.areas.find(x=>x.id===id);if(!base)return;MA=id;if(sub)MS=sub;
 const a=FOC?focusArea(FOC):base;
 const tps=D.topics.filter(t=>a.focus?bindsTo(t,a.focus):t.area===a.id);
 const hasPipe=!!LIN||(a.focus?a.pipeline.length>1:a.pipeline.length>0);
 const subs=[hasPipe&&['pipeline','Pipeline'],['rel','Gold relationships'],tps.length&&['topics','Semantic topics']].filter(Boolean);
 if(!subs.some(s=>s[0]===MS))MS=subs[0][0];
 document.querySelectorAll('#apills button').forEach(x=>{x.classList.toggle('on',x.dataset.a===id&&!FOC&&!LIN);x.classList.toggle('home',x.dataset.a===id&&!!(FOC||LIN))});
 byId('spills').innerHTML=subs.map(([k,l])=>`<button type="button" class="${k===MS?'on':''}" ${act('sub',k)}>${l}</button>`).join('');
 const head={pipeline:'Pipeline — staging (bronze) → integration (silver) → warehouse (gold)',rel:'Gold relationships — facts and extended tables → dimensions',topics:'Semantic topics — topic → base view → joined views'}[MS];
 let note;
 if(a.focus){const up=a.pipeline.filter(x=>x!==a.focus),n=l=>up.filter(x=>M[x].layer===l).length,s=(k,w)=>k===1?w:w+'s';
  note=`<div class="fnote">Filtered to <code>${e(a.focus)}</code> (${e(a.name)}). ${MS==='pipeline'?`Showing it and its ${up.length} upstream ${s(up.length,'model')}: ${n('bronze')} bronze, ${n('silver')} silver, ${n('gold')} gold.`:MS==='rel'?`Showing it and the ${a.erd.length-1} ${s(a.erd.length-1,'table')} related to it.`:`Showing the ${tps.length} ${s(tps.length,'topic')} that ${tps.length===1?'uses':'use'} it.`}${hasPipe?'':' It has no upstream models in this review; its pipeline belongs to its own domain.'} <a href="#" ${act('clear','')}>Clear filter</a></div>`}
 else note=base.shared?`<p class="note">Warehouse tables owned by other domains that the ${e(D.meta.domain_label)} tables and topics join to. Their pipelines belong to their own domains.</p>`:(tps.length?`<p class="note">Semantic topics in this area: ${tps.map(t=>topicLink(t.topic)).join(', ')}</p>`:'');
 byId('abody').innerHTML=`<h3 class="ah">${head}</h3>${note}${MS==='pipeline'?pipeline(a):MS==='rel'?erd(a):topicLineage(a)}`;
 if(MS==='pipeline')pipeInit()}

/* ---------- inspectors ---------- */
function openFileLinks(paths){return paths.map(p=>fileLink(p)).join('<br>')}
function inspTopic(n){const t=T[n];if(!t)return;const p=byId('insp'),f=FILES[t.path];
 p.innerHTML=`<button type="button" class="x" ${act('close','')}>Close</button><h2>${e(t.label)}</h2>
 <p><span class="b info">semantic topic</span>${t.group?' · '+e(t.group):''} · ${e(areaName[t.area]||t.area)} · <code>${e(t.topic)}</code></p>
 <p>${e(t.desc)}</p>
 <p><b>Base view:</b> ${e(t.base_view)} — ${occurrenceLinks(occurrence(t,t.base))}</p>
 <h3>Joins (${t.joins.length})</h3>${t.joins.length?`<table><tr><th>From</th><th>To</th><th>Cardinality</th><th>Status / direction</th></tr>${t.joins.map(j=>`<tr><td>${e(occurrenceLabel(t,j.from))}</td><td>${e(occurrenceLabel(t,j.to))}</td><td>${e(j.card?human(j.card):'Unresolved')}</td><td>${e(j.status)} / ${e(j.direction)}</td></tr>`).join('')}</table>`:'<p class="note">No joins; the topic reads its base view only.</p>'}
 <h3>Explicit warehouse bindings</h3><table><tr><th>View occurrence</th><th>Gold model</th></tr>${(t.nodes||[]).map(n=>`<tr><td>${e(n.path.join(' → '))}</td><td>${occurrenceLinks(n)}</td></tr>`).join('')}</table>
 ${t.gaps?.length?`<h3>Unresolved semantic evidence</h3><p class="note">Candidate code remains available. Resolve these gaps before deployment.</p><ul>${t.gaps.map(g=>`<li>${e(g)}</li>`).join('')}</ul>`:''}
 <h3>Dashboards served (${t.dashboards.length})</h3>${t.dashboards.length?`<table><tr><th>ID</th><th>Dashboard</th><th>Status</th></tr>${t.dashboards.map(x=>`<tr><td>${e(x.id)}</td><td>${e(x.title)}</td><td>${b(human(x.status))}</td></tr>`).join('')}</table>`:'<p class="note">No in-scope dashboard maps to this topic.</p>'}
 <h3>AI context</h3><p>${t.ai?e(t.ai):'<span class="note">none</span>'}</p>
 <h3>Fields (${t.fields.length} entries)</h3><p>${t.fields.map(x=>`<code>${e(x)}</code>`).join(' ')||'<span class="note">Field selection is not projected here; inspect the effective topic, including inherited definitions.</span>'}</p>
 <h3>Files</h3><p>${openFileLinks([t.path,...Object.values(t.view_files)].filter(Boolean))}</p>
 ${f?`<h3>Code — ${e(t.path)}</h3><pre>${e(f.content)}</pre>`:''}`;
 p.classList.add('on');p.scrollTop=0}
function insp(n){const m=M[n];if(!m)return;const p=byId('insp');
 const keys=m.cols.filter(c=>c[2]),f=m.code&&FILES[m.code];
 const relTo=c=>{const r=D.rels.find(r=>r.from===n&&(r.key||'').startsWith(c+' '));return r?' → '+link(r.to):''};
 const ts=D.topics.filter(t=>(t.nodes||[]).some(o=>o.binding_status==='complete'&&o.model_ids.includes(n)));
 p.innerHTML=`<button type="button" class="x" ${act('close','')}>Close</button><h2>${e(m.id)}</h2>
 <p>${b(m.disp)} · ${e(m.layer)} · ${e(m.domain)}${m.area&&areaName[m.area]?' · '+e(areaName[m.area]):''}</p>
 <p><b>Grain:</b> ${m.grain?e(m.grain):'<span class="note">not stated in the model documentation</span>'}</p>
 <p><b>Existing source:</b> ${e(m.existing)}</p>
 ${tableHome(m.id)?`<p><button type="button" class="iso" ${act('isolate',m.id)}>Show only this table's lineage</button></p>`:''}
 <p><b>Code file:</b> ${m.code?fileLink(m.code):`<code>${e(m.source_path||'—')}</code> <span class="note">unchanged, not in this package</span>`}</p>
 <p>${e(m.desc)}</p>
 <h3>Keys</h3>${keys.length?keys.map(k=>`<div><code>${e(k[2])}</code> <code>${e(k[0])}</code>${relTo(k[0])}</div>`).join(''):'<p class="note">No keys declared.</p>'}
 <p><b>Semantic topics using this table:</b> ${ts.length?ts.map(t=>topicLink(t.topic)+((t.base_model_ids||[]).includes(n)?' (base view)':'')).join(', '):'none'}</p>
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
 <div class="files"><div><input class="q" placeholder="Filter files…" id="fq"><select class="s" id="fk"><option value="">all</option><option value="new">new</option><option value="changed">changed</option><option value="unassessed">unassessed</option></select><ul id="flist"></ul></div><pre id="fview">Select a file.</pre></div>`;
 byId('fq').oninput=renderFiles;byId('fk').onchange=renderFiles;renderFiles()}
let cur=null;
function renderFiles(){const q=(byId('fq').value||'').toLowerCase(),k=byId('fk').value;
 byId('flist').innerHTML=D.files.filter(f=>(!k||f.status===k)&&f.path.toLowerCase().includes(q)).map(f=>`<li ${act('file',f.path)}${f.path===cur?' class="on"':''}>${b(f.status)} ${e(f.path)}</li>`).join('')}
function openFile(p){if(!built.code){rCode();built.code=1}cur=p;const f=FILES[p];byId('fview').textContent=f?('// '+f.path+' · '+f.status+'\n\n'+f.content):'';
 document.querySelectorAll('#flist li').forEach(li=>li.classList.toggle('on',li.dataset.v===p))}

/* ---------- decisions ---------- */
function rDecisions(){const areas=[...new Set(D.decisions.map(d=>d.area))].sort();
 byId('v-decisions').innerHTML=`<h1>Decisions</h1><p class="meta">${e(D.notes.decisions)}</p>
 <input class="q" placeholder="Filter…" id="dq"><select class="s" id="ds"><option value="">all statuses</option><option>answered</option><option>assumed</option><option>open</option><option>unassessed</option></select><select class="s" id="da"><option value="">all areas</option>${areas.map(a=>`<option>${e(a)}</option>`).join('')}</select> <span class="note" id="dn"></span>
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
const ACTIONS={show:v=>{closeInsp();show(v)},model:insp,topic:inspTopic,area:pickArea,isolate:v=>{closeInsp();show('model');setFocus(v);window.scrollTo(0,0)},clear:()=>setFocus(''),sub:v=>drawArea(MA,v),
 lineage:openLineage,linback:lineageBack,linclose:closeLineage,jump,zoom:v=>v==='fit'?fitZoom():zoomTo(v==='100'?1:v==='in'?PZ*1.2:PZ/1.2),
 file:v=>{closeInsp();show('code');openFile(v)},decision:goDec,close:closeInsp};
document.addEventListener('click',ev=>{const t=ev.target.closest('[data-act]');if(!t)return;ev.preventDefault();ACTIONS[t.dataset.act]?.(t.dataset.v)});
document.addEventListener('keydown',ev=>{if(ev.key==='Escape')closeInsp();
 if((ev.key==='Enter'||ev.key===' ')&&ev.target.dataset&&ev.target.dataset.act){ev.preventDefault();ev.target.click()}});
show(location.hash.slice(1)||'overview');
