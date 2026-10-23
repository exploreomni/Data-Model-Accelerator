/* Shared offline topic controls for single-page and partitioned deliveries. */
(function(){
  'use strict';
  const panel=document.querySelector('#omni-topic-trees');
  if(!panel||panel.__topicBooted)return;panel.__topicBooted=true;
  const data=JSON.parse(document.getElementById('delivery-data').textContent),pages=data.topic_diagrams||[];
  const el=id=>document.getElementById(id),domain=el('topic-domain'),picker=el('topic-picker');
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const nav=document.querySelector('#topic-trees-nav');if(nav)nav.hidden=!data.topic_coverage;
  const c=data.topic_coverage;
  el('topic-coverage').textContent=c?`${c.represented_topics??c.represented??0} / ${c.expected_topics??c.expected??0} topics represented · ${c.fully_bound_topics??0} fully bound · ${c.structurally_complete_topics??0} structurally complete. Native validation pending.`:'Selected semantic evidence is not available. Ask the agent to include the Omni review.';
  for(const value of [...new Set(pages.map(p=>p.domain))].sort()){const o=node('option',value);o.value=value;domain.append(o);}
  let current=null,zoom=1,graphic=null;
  const decode=b64=>new TextDecoder().decode(Uint8Array.from(atob(b64),ch=>ch.charCodeAt(0)));
  const descriptions={'topic.binding_missing':'Warehouse binding is missing','topic.binding_ambiguous':'More than one warehouse binding matches','topic.binding_non_gold':'Binding points outside the gold layer','topic.legacy_topology_unavailable':'Regenerate the semantic review to include join paths'};
  const finding=r=>{const view=current.nodes?.find(n=>n.id===r.node_id)?.view_id;return(descriptions[r.code]||String(r.code||r).replace(/^topic\./,'').replaceAll('_',' '))+(view?' — '+view:'');};
  function resize(){if(!graphic)return;graphic.style.width=(Number(graphic.getAttribute('width'))||800)*zoom+'px';graphic.style.height=(Number(graphic.getAttribute('height'))||500)*zoom+'px';}
  function show(){
    current=pages.find(p=>p.id===picker.value)||null;zoom=1;graphic=null;
    const canvas=el('topic-diagram');canvas.replaceChildren();el('topic-bindings').replaceChildren();el('topic-findings').replaceChildren();
    el('topic-empty').hidden=!!current;el('topic-download').disabled=!current;
    if(!current)return;
    for(const id of ['topic-zoom-in','topic-zoom-out','topic-zoom-reset'])el(id).hidden=!!current.page_path;
    if(current.page_path){const frame=node('iframe');frame.src=current.page_path;frame.title=current.name+' join tree';canvas.append(frame);el('topic-download').disabled=!current.download_available;}
    else try{graphic=PortalSvg.sanitize(decode(current.base64),'topic-tree');canvas.append(graphic);resize();}
    catch(error){const img=node('img');img.src='data:image/svg+xml;base64,'+current.base64;img.alt='Topic join tree; full view names and bindings appear below.';img.style.maxWidth='none';canvas.append(img);}
    const issues=[...(current.diagnostics||[]),...(current.binding_diagnostics||[])];
    el('topic-findings').append(node('p',issues.length?issues.map(finding).join(' · '):'No recorded structural or binding gaps. Runtime behavior still requires validation.'));
    const table=node('table'),head=node('tr');for(const title of ['View / role','Warehouse table','Binding','Copy'])head.append(node('th',title));table.append(head);
    for(const view of current.nodes||[]){const row=node('tr');row.append(node('td',(view.path||[view.view_id]).join(' → ')));const cell=node('td');
      for(const id of view.model_ids||[]){const model=(data.models||data.review?.models||[]).find(m=>m.id===id);const link=node(model?'a':'span',id);
        if(model?.path)link.href=model.path;else if(model){link.href='#architecture';link.onclick=event=>{event.preventDefault();globalThis.dispatchEvent?.(new CustomEvent('dma-topic-table',{detail:{id}}));};}
        cell.append(link,node('br'));}
      if(!(view.model_ids||[]).length)cell.textContent='Unbound';row.append(cell,node('td',view.binding_status||'gap'));
      const copy=node('button','Copy view');copy.type='button';copy.onclick=async()=>{try{await navigator.clipboard.writeText(view.view_id);copy.textContent='Copied';}catch(e){const text=node('span',view.view_id);copy.replaceWith(text);const range=document.createRange();range.selectNodeContents(text);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);text.title='Selected — copy with your keyboard';}};
      const action=node('td');action.append(copy);row.append(action);table.append(row);
    }el('topic-bindings').append(table);
  }
  function filter(){const previous=picker.value;picker.replaceChildren();const matching=pages.filter(p=>!domain.value||p.domain===domain.value);for(const p of matching){const o=node('option',p.name);o.value=p.id;picker.append(o);}picker.value=matching.some(p=>p.id===previous)?previous:(matching[0]?.id||'');show();}
  domain.onchange=filter;picker.onchange=show;
  el('topic-zoom-in').onclick=()=>{zoom=Math.min(3,zoom+.2);resize();};el('topic-zoom-out').onclick=()=>{zoom=Math.max(.4,zoom-.2);resize();};el('topic-zoom-reset').onclick=()=>{zoom=1;resize();};
  el('topic-download').onclick=()=>{if(!current)return;const a=node('a'),url=current.page_path?null:URL.createObjectURL(new Blob([decode(current.base64)],{type:'image/svg+xml'}));a.href=current.page_path?current.export_path:url;a.download=current.export_path.split('/').pop();document.body.append(a);a.click();a.remove();if(url)setTimeout(()=>URL.revokeObjectURL(url),5000);};
  filter();
})();
