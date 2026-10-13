/* Local review only. No network, native execution, or approval mutation. */
'use strict';
const originalShell = '<!doctype html>\n' + document.documentElement.outerHTML;
const data = JSON.parse(document.getElementById('delivery-data').textContent);
const eng = data.engagement, review = data.review || {}, files = data.files || [];
// BEGIN PORTABLE ASSURANCE HELPERS — these functions never authenticate evidence.
const assuranceLanes = [
  ['source_coverage','Source coverage','Match the export against an independent source inventory; resolve missing reports, tiles and dependencies.','base'],
  ['classification','Sensitive data classification','Review overlapping PII, PCI and PHI categories and unresolved lineage.','base'],
  ['input_egress','Inputs approved for the agent','Use the approved staging boundary before sending any source content to an agent.','base'],
  ['yaml','Native file structure','Run strict native file parsing on this exact candidate.','semantic'],
  ['omni_static','Omni model contract','Check physical bindings, fields, joins, types and supported native parameters.','semantic'],
  ['warehouse_execution','Warehouse execution','Run the authorized target checks and retain results from the actual environment.','base'],
  ['native_model','Native Omni validation','Validate the exact model revision in the selected Omni branch.','semantic'],
  ['omni_queries','Omni query execution','Execute the reviewed query cases with the intended connections and settings.','semantic'],
  ['data_parity','Data and metric comparisons','Compare frozen populations, grain, metrics and edge cases; investigate discrepancies.','base'],
  ['dashboard_created','Dashboard draft','Create and read back the complete reviewed draft without changing the published document.','dashboard'],
  ['dashboard_behavior','Dashboard behavior','Verify tiles, filters, listeners, layout, interactions, drill and export behavior.','dashboard'],
  ['access','Effective access','Verify allowed and denied personas, row filters, masking, metadata and inherited permissions.','base'],
  ['ai_context','AI context and answers','Review approved meanings and unresolved questions; run the frozen persona question suite.','semantic'],
  ['output_disclosure','Output disclosure','Scan the exact final package and verify the destination disclosure policy.','base'],
  ['business_acceptance','Business acceptance','Have the actual decision-maker review this exact candidate and its evidence.','base']
];
function portableAssurance(snapshot){
  const supplied=snapshot?.delivery_assurance||{},scope=['model_only','model_semantic','full_dashboard'].includes(supplied.migration_scope)?supplied.migration_scope:null;
  const records=Array.isArray(supplied.checks)?supplied.checks:[];
  const checks=assuranceLanes.map(([lane,label,next_action,group])=>{
    const required=!scope||group==='base'||group==='semantic'&&scope!=='model_only'||group==='dashboard'&&scope==='full_dashboard';
    const imported=records.find(c=>c?.lane===lane),reported=['failed','unsupported','stale'].includes(imported?.status)?imported.status:'pending';
    return{lane,label,required,status:required?reported:'not_applicable',
      reason:!required?'Excluded by the selected migration scope.':!scope?'Select a migration scope before interpreting readiness.':
        imported?.status==='passed'?'A reported pass requires verification outside this offline page.':'No authenticated completion is established by this page.',
      next_action:required?next_action:'No evidence required for this selected scope.'};
  });
  return{migration_scope:scope,checks,acceptance_ready:false,deployment_authorized:false,
    qualification:'Candidate review only. This offline page does not authenticate evidence, business sign-off or deployment authority.'};
}
function subsetPath(path){
  return typeof path==='string'&&path.length>0&&path.length<=500&&!/[\\\x00-\x1f\x7f:]/.test(path)&&!path.startsWith('/')&&
    path.split('/').every(p=>p&&p!=='.'&&p!=='..')&&!['start_here.html','delivery_manifest.json'].includes(path.toLowerCase());
}
async function checkedSubsetFiles(inventory,selection,categories){
  if(!Array.isArray(inventory)||!Array.isArray(selection)||!selection.length||selection.length>500)throw new Error('Select a bounded registered file set.');
  const all=new Map(),ids=new Set(),paths=new Set(),entries=[];
  for(const item of inventory){if(!item||typeof item.id!=='string'||all.has(item.id))throw new Error('The file inventory is ambiguous. Ask the agent to repackage.');all.set(item.id,item);}
  let total=0;
  for(const file of selection){
    const registered=all.get(file?.id);
    if(!registered||JSON.stringify(file)!==JSON.stringify(registered)||ids.has(file.id)||!subsetPath(file.path)||paths.has(file.path.toLowerCase())||
       !categories.has(file.category)||!Number.isSafeInteger(file.size)||file.size<0||typeof file.sha256!=='string'||!/^[a-f0-9]{64}$/.test(file.sha256)||
       !Array.isArray(file.requires)||file.requires.some(id=>typeof id!=='string'))throw new Error('The selected inventory is invalid. Ask the agent to repackage.');
    if(file.category!=='technical_audit'&&/^start_here\.(html|md|txt)$/i.test(file.path.split('/').pop()))throw new Error('One Start Here entrypoint per handoff. Ask the agent to register the maintained document instead.');
    const body=bytes(file.base64);total+=body.length;
    if(body.length!==file.size||await sha256(body)!==file.sha256||total>50*1024*1024)throw new Error('Selected file integrity or size check failed. Ask the agent to repackage.');
    ids.add(file.id);paths.add(file.path.toLowerCase());entries.push([file.path,body]);
  }
  if(selection.some(file=>file.requires.some(id=>!ids.has(id))))throw new Error('Include the required dependent files before exporting.');
  return entries;
}
async function browserSubsetManifest(snapshot,audience,categories,entries){
  const manifest={schema_version:1,kind:'portable_delivery_integrity',export_origin:'browser_subset',
    engagement_id:snapshot.engagement_id,source_fingerprint:snapshot.source_fingerprint,
    ...(snapshot.context_sha256?{context_sha256:snapshot.context_sha256}:{}),target:snapshot.target,audience,
    migration_scope:portableAssurance(snapshot).migration_scope,deliverables:[...categories].sort(),
    acceptance_ready:false,deployment_authorized:false,
    disclosure_policy_status:'not_revalidated_in_browser',
    content_scan:{status:'not_run_in_browser',coverage_complete:false,
      next_action:'Return this exact ZIP to the agent for content scanning and destination disclosure review before sharing or deploying.'},
    integrity_scope:'Selected embedded artifact hashes were checked; checksums below bind the newly rendered files only.',
    authority:'File integrity only; no new content scan, authenticated review, business acceptance or deployment authority.',files:[]};
  for(const [path,body]of entries)manifest.files.push({path,sha256:await sha256(body),bytes:body.length});
  return manifest;
}
// END PORTABLE ASSURANCE HELPERS
// BEGIN COMPACT HANDOFF HELPERS
// Derive the front page from the current projection, never a second status record.
function trimHandoff(snapshot,selected){
  const ids=new Set(selected.map(file=>file.id));
  if(snapshot.review?.handoff)for(const role of Object.keys(snapshot.review.handoff))if(!ids.has(snapshot.review.handoff[role]))delete snapshot.review.handoff[role];
}
function compactHandoff(snapshot){
  const r=snapshot.review||{},inventory=snapshot.files||[],workflow=snapshot.workflow||{};
  const cases=r.validation||[],local=cases.filter(c=>['static','local'].includes(c.scope));
  const native=cases.filter(c=>['warehouse','semantic'].includes(c.scope));
  const quality=(r.quality_checks||[]).filter(c=>c.evidence_state==='selected');
  const localQuality=quality.filter(c=>['code_conventions','project_validity'].includes(c.id));
  const negative=[...local,...localQuality];
  const status=negative.some(c=>c.status==='fail')?'fail':negative.some(c=>['pending','skipped','unknown','unsupported'].includes(c.status))?'pending':negative.some(c=>c.status==='pass')?'reported_pass':'unknown';
  const decisionRows=[...new Map([...(r.decisions||[]),...(workflow.decisions||[])].map(d=>[d.id,d])).values()];
  const primary=role=>inventory.find(file=>file.id===r.handoff?.[role])||null;
  const implementation=inventory.filter(file=>file.category==='implementation');
  const evidenceGaps=[...quality.filter(c=>['fail','pending','skipped','unknown','unsupported'].includes(c.status)).map(c=>({id:c.id,status:c.status,label:c.id.replaceAll('_',' ')})),
    ...(snapshot.engagement?.delivery_assurance?.checks||[]).filter(c=>['failed','stale','unsupported'].includes(c.status)).map(c=>({id:c.lane,status:c.status,label:c.lane.replaceAll('_',' ')}))];
  const stages=[
    {id:'design',label:'Design',status:(r.models||[]).length||primary('design_artifact_id')?'documented':'not_included',detail:'Design content in this view; approval is separate.'},
    {id:'implementation',label:'Code',status:implementation.length?'included':'not_included',detail:implementation.length?`${implementation.length} implementation files in this export; candidates and templates still need their recorded prerequisites.`:'No implementation files in this view. An omitted export is not evidence of missing or completed work.'},
    {id:'local',label:'Local checks',status,detail:`${local.length} reported cases and ${localQuality.length} selected quality lanes. These inventories have separate scopes; a reported pass does not establish complete coverage.`},
    {id:'native',label:'Native checks',status:native.some(c=>c.status==='fail')||quality.some(c=>c.id==='warehouse_validation'&&c.status==='fail')?'fail':'unverified',detail:`${native.length} reported warehouse or semantic cases. Verify execution and scope in the actual target environment.`},
    {id:'acceptance',label:'Business acceptance',status:'not_established',detail:'Use the version-bound human decision record; this offline page cannot authenticate acceptance.'}
  ];
  return{stages,evidenceGaps,blockers:{decisions:decisionRows.filter(d=>!['resolved','accepted'].includes(d.status)).length,
    failed:cases.filter(c=>c.status==='fail').length,pending:cases.filter(c=>c.status==='pending').length,skipped:cases.filter(c=>c.status==='skipped').length},
    primary:{design:primary('design_artifact_id'),implementation:primary('implementation_guide_artifact_id')}};
}
// END COMPACT HANDOFF HELPERS
// BEGIN WORKFLOW HELPERS — display selection never changes execution or export scope.
function assetSelection(modelRows, edges, assetId){
  const all=new Set(modelRows.map(m=>m.id)), direct=new Set(), unknown=new Set();
  for(const m of modelRows){if(!m.asset_ids?.length||m.mapping_status!=='verified')unknown.add(m.id);if(!assetId||assetId==='__unmapped__'&&unknown.has(m.id)||m.asset_ids?.includes(assetId))direct.add(m.id);}
  const visible=new Set(direct),upstream=new Map(modelRows.map(m=>[m.id,new Set(m.depends_on||[])]));
  for(const edge of edges)if(edge.kind==='lineage'&&all.has(edge.from)&&all.has(edge.to))upstream.get(edge.to).add(edge.from);
  const pending=[...visible];while(pending.length){for(const id of upstream.get(pending.pop())||[])if(all.has(id)&&!visible.has(id)){visible.add(id);pending.push(id);}}
  return{direct,visible,unknown,dependencies:new Set([...visible].filter(id=>!direct.has(id)))};
}
function matchesAsset(row,selection,assetId){
  if(!assetId)return true;
  const unknown=!row.asset_ids?.length&&!row.model_ids?.length;
  if(assetId==='__unmapped__')return unknown||row.mapping_status&&row.mapping_status!=='verified'||row.model_ids?.some(id=>selection.visible.has(id));
  // Unmapped questions/changes stay visible so filtering cannot conceal a blocker.
  return unknown||row.asset_ids?.includes(assetId)||row.model_ids?.some(id=>selection.visible.has(id));
}
function decisionResponseDocument(workflow,engagementId,responses){
  if(!workflow?.design_id||!Number.isInteger(workflow.design_revision)||!/^([a-f0-9]{64})$/.test(workflow.design_sha256||''))throw new Error('A current design binding is required. Ask the agent to refresh this review.');
  if(!Array.isArray(responses)||!responses.length)throw new Error('Select at least one answered decision.');
  const seen=new Set(),known=new Map((workflow.decisions||[]).map(d=>[d.id,d]));
  const answers=responses.map(r=>{const d=known.get(r.decision_id);if(!d||seen.has(r.decision_id)||typeof r.answer!=='string'||!r.answer.trim()||r.option_id!=null&&!d.options?.some(o=>o.id===r.option_id))throw new Error('An answer is missing, duplicated or refers to an unknown option.');seen.add(r.decision_id);return{decision_id:r.decision_id,answer:r.answer.trim(),option_id:r.option_id||null,rationale:typeof r.rationale==='string'?r.rationale.trim():''};});
  return{schema_version:1,kind:'decision_responses',intent:'record_answers',engagement_id:engagementId,design_id:workflow.design_id,design_revision:workflow.design_revision,design_sha256:workflow.design_sha256,answers,request_only:true};
}
function trimWorkflowDetails(snapshot,categories){
  if(['documentation','diagrams','dictionary'].some(key=>categories.has(key)))return;
  for(const key of ['assets','models','relationships','decisions','changes'])delete snapshot.review?.[key];
  for(const key of ['decisions','effort','models','relationships','assets','task_plan'])delete snapshot.workflow?.[key];
}
function filteredModelSvg(modelRows,edges,dependencyIds,omittedEdges=0){
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  const layers=['bronze','silver','gold'],positions=new Map(),counts=[0,0,0],width=1200;
  for(const m of modelRows){const column=Math.max(0,layers.indexOf(m.layer));positions.set(m.id,{x:35+column*390,y:80+counts[column]++*175});}
  const bottom=100+Math.max(1,...counts)*175,height=bottom+edges.length*42+50;
  const parts=[`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img"><title>Filtered model and required dependencies</title><desc>Filtered view only. ${omittedEdges} additional connectors are omitted from this image; the guided review retains the full relationship ledger.</desc><rect width="1200" height="${height}" fill="#f4f7fb"/><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#537080"/></marker></defs>`];
  layers.forEach((layer,i)=>parts.push(`<text x="${35+i*390}" y="35" font-family="sans-serif" font-size="20" fill="#172e43">${layer} · ${counts[i]}</text>`));
  edges.forEach((edge,i)=>{const a=positions.get(edge.from),b=positions.get(edge.to);if(!a||!b)return;const color=edge.kind==='lineage'?'#076d66':'#7658a7',same=a.x===b.x;const lane=same?a.x+330+(i%5)*7:(a.x+b.x)/2+170+(i%5)*5;const path=`M ${a.x+325} ${a.y+50} H ${lane} V ${b.y+50} H ${same?b.x+325:b.x}`;parts.push(`<path d="${path}" fill="none" stroke="${color}" stroke-width="2" marker-end="url(#arrow)"/><text x="${a.x+330}" y="${a.y+45}" font-family="sans-serif" font-size="10" fill="${color}">E${i+1}</text>`);});
  for(const m of modelRows){const p=positions.get(m.id),title=m.name||m.id,subtitle=dependencyIds.has(m.id)?'Required dependency':m.mapping_status==='inferred'?'Inferred asset mapping':'Selected model';parts.push(`<g><title>${esc(title)} · ${esc(m.grain||'Grain unresolved')}</title><rect x="${p.x}" y="${p.y}" width="325" height="145" rx="9" fill="white" stroke="#9aabba"/><text x="${p.x+12}" y="${p.y+23}" font-family="sans-serif" font-size="14" font-weight="700" fill="#172e43">${esc(title.slice(0,38))}</text><text x="${p.x+12}" y="${p.y+44}" font-family="sans-serif" font-size="10" fill="#546779">${esc(subtitle)}</text><text x="${p.x+12}" y="${p.y+64}" font-family="sans-serif" font-size="10" fill="#546779">${esc((m.grain||'Grain unresolved').slice(0,51))}</text>`);(m.columns||[]).slice(0,3).forEach((c,i)=>parts.push(`<text x="${p.x+12}" y="${p.y+87+i*17}" font-family="monospace" font-size="11" fill="#172e43">${esc(((c.key?c.key+' ':'')+c.name+' · '+(c.type||'unknown')).slice(0,44))}</text>`));parts.push('</g>');}
  edges.forEach((edge,i)=>parts.push(`<text x="35" y="${bottom+i*42}" font-family="sans-serif" font-size="11" fill="#172e43">E${i+1} · ${esc(edge.from)} → ${esc(edge.to)}</text><text x="35" y="${bottom+i*42+17}" font-family="sans-serif" font-size="10" fill="#546779">${esc([edge.kind,edge.predicate,edge.cardinality,edge.role,edge.status||'Not validated'].filter(Boolean).join(' · ').slice(0,180))}</text>`));
  if(omittedEdges)parts.push(`<text x="35" y="${height-18}" font-family="sans-serif" font-size="11" fill="#546779">${omittedEdges} additional connectors omitted from this image. See the complete guided-review ledger.</text>`);
  parts.push('</svg>');return parts.join('');
}
// END WORKFLOW HELPERS
const labels = {publish_pr:'Publish a pull request',deploy_development:'Deploy to development',promote:'Promote a tested version',handoff_prepared:'Prepared handoff',dbt:'dbt',coalesce:'Coalesce',native_sql:'Native SQL',snowflake:'Snowflake',databricks:'Databricks',bigquery:'BigQuery',redshift:'Amazon Redshift',clickhouse:'ClickHouse',motherduck:'MotherDuck',gcp:'GCP — service unresolved',documentation:'Model documentation',diagrams:'Connected diagrams',dictionary:'Data dictionary',implementation:'Implementation files',validation:'Validation evidence',sample_data:'Sample data',technical_audit:'Technical audit',reviewer:'Reviewer package',engineer:'Engineering package',audit:'Technical audit'};
const el = id => document.getElementById(id);
const text = value => value == null ? 'Not supplied' : typeof value === 'object' ? JSON.stringify(value,null,2) : String(value);
const pretty = value => labels[value] || text(value).replaceAll('_',' ');
const make = (tag, value, cls) => {const n=document.createElement(tag);if(value!==undefined)n.textContent=text(value);if(cls)n.className=cls;return n;};
function clear(id){el(id).replaceChildren();return el(id);}
function empty(id,message){clear(id).append(make('div',message,'empty'));}
function notice(message){el('messages').hidden=false;el('messages').textContent=message;}
function download(name,body,mime){const url=URL.createObjectURL(new Blob([body],{type:mime||'application/octet-stream'}));const a=make('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);}
function bytes(b64){return Uint8Array.from(atob(b64),c=>c.charCodeAt(0));}
function card(parent,title,value,note){const c=make('article',undefined,'card');c.append(make('h3',title),make('strong',value),make('p',note));parent.append(c);}
function table(id,columns,rows,pageSize=30){let page=0;const draw=()=>{const target=clear(id);if(!rows.length){target.append(make('p','No matching records.','empty'));return;}const wrap=make('div',undefined,'table-scroll'),t=make('table'),head=make('tr');columns.forEach(c=>head.append(make('th',c[0])));const thead=make('thead');thead.append(head);t.append(thead);const body=make('tbody');rows.slice(page*pageSize,(page+1)*pageSize).forEach(row=>{const tr=make('tr');columns.forEach(c=>{const td=make('td'),v=c[1](row);td.append(v instanceof Node?v:make('span',v));tr.append(td);});body.append(tr);});t.append(body);wrap.append(t);target.append(wrap);const pager=make('div',undefined,'pager'),prev=make('button','Previous','secondary'),next=make('button','Next','secondary');prev.disabled=page===0;next.disabled=(page+1)*pageSize>=rows.length;prev.onclick=()=>{page--;draw();};next.onclick=()=>{page++;draw();};pager.append(prev,make('span',`${page*pageSize+1}–${Math.min((page+1)*pageSize,rows.length)} of ${rows.length}`),next);target.append(pager);};draw();}
const reviewSections=['overview','readiness','changes','model','validation','delivery','deployment',...(review.metadata?['metadata']:[]),...(review.omni?['omni']:[])];
function navigate(){const id=location.hash.slice(1)||'overview';const valid=reviewSections.includes(id)?id:'overview';document.querySelectorAll('[data-section]').forEach(s=>s.hidden=s.id!==valid);document.querySelectorAll('[data-nav]').forEach(n=>{n.classList.toggle('active',n.dataset.nav===valid);if(n.dataset.nav===valid)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});if(!['overview','model','delivery'].includes(valid))el('supporting-navigation').open=true;}
addEventListener('hashchange',navigate);navigate();
el('implementation-nav').hidden=data.audience!=='engineer';el('files-nav').hidden=data.audience==='engineer';
el('page-title').textContent=review.title||'Your modeling engagement';
el('subtitle').textContent=review.description||'A guided path from the current repository to a model you can inspect, test and adopt.';
Object.values(eng.target||{}).filter(Boolean).forEach(v=>el('target-tags').append(make('span',pretty(v),'pill')));
const fingerprint=typeof eng.source_fingerprint==='object'?eng.source_fingerprint?.value:eng.source_fingerprint;
el('scope-note').textContent=`${pretty(eng.engagement_type)} · ${text(eng.domain)} · Source ${fingerprint?fingerprint.slice(0,12):'not inventoried'} · This view is a recorded snapshot; refresh through the agent after changes.`;
el('stage').textContent=pretty(eng.status);el('revision').textContent=`Engagement revision ${eng.revision}. No deployment is asserted.`;
el('footer-id').textContent=eng.engagement_id;
const assurance=portableAssurance(eng),scopeNames={model_only:'Data model only',model_semantic:'Data model + Omni semantic layer',full_dashboard:'Full dashboard migration'};
el('candidate-status').textContent='Candidate · acceptance not established';
el('assurance-scope').textContent=scopeNames[assurance.migration_scope]||'Migration scope not selected';
el('assurance-boundary').textContent=assurance.qualification;
el('assurance-overview').textContent=`${scopeNames[assurance.migration_scope]||'Scope unresolved'} · ${assurance.checks.filter(c=>c.required).length} evidence lanes require verification. Prepared files do not establish completed migration.`;
table('assurance-checks',[['Evidence lane',c=>c.label],['Required',c=>c.required?'Yes':'Outside scope'],['Status',c=>pretty(c.status)],['Meaning / next action',c=>c.reason+' '+c.next_action]],assurance.checks,20);
const actions=eng.next_actions||[],first=actions[0];
el('next-title').textContent=first?.title||({discovery:'Complete the next discovery step',generation:'Review the model prerequisites',readiness:'Resolve the readiness findings',catalogue:'Ground the model in your raw data'}[first?.scope])||'Review readiness and outstanding decisions';
const nextSection=reviewSections.includes(first?.section)?first.section:eng.delivery?.status==='prepared'?'delivery':'readiness';
el('next-link').href='#'+nextSection;el('next-link').textContent=nextSection==='delivery'?'Inspect handoff →':'Review next step →';
if(eng.delivery?.status==='prepared'){el('handoff-summary').hidden=false;el('handoff-summary').textContent=`${files.length?files.length+' registered files are included in this export.':'A prepared handoff is recorded; this status page has no embedded files.'} ${eng.delivery.qualification||'File integrity only; native runtime, business approval and deployment remain separate.'}`;}
el('next-detail').textContent=typeof first==='object'?(first.action||first.detail||first.description||first.reason||''): first||'The agent retains your decisions and evidence. Continue with the outstanding item before claiming the next stage.';
function effortPackageDetails(row){const box=make('div');box.append(make('p',row.rationale||row.summary||'No rationale supplied.'));const detail=make('details');detail.append(make('summary','Factors and prerequisites'));for(const item of row.dimensions||[])detail.append(make('p',`${pretty(item.name)} · ${pretty(item.level)}: ${item.rationale||'No rationale supplied.'}`));for(const key of ['assumptions','prerequisites','dependencies','included_work','excluded_work'])if(row[key]?.length)detail.append(make('p',`${pretty(key)}: ${row[key].join('; ')}`));box.append(detail);return box;}
const workflow=data.workflow||null;
const models=review.models||[],changes=review.changes||[],cases=review.validation||[];
const decisions=[...new Map([...(review.decisions||[]),...(workflow?.decisions||[])].map(d=>[d.id,d])).values()];
const handoff=compactHandoff(data);
table('delivery-stages',[['Stage',s=>s.label],['Recorded status',s=>pretty(s.status)],['What it means',s=>s.detail]],handoff.stages,5);
el('handoff-blockers').textContent=`${handoff.blockers.decisions} unresolved decisions · ${handoff.blockers.failed} failed, ${handoff.blockers.pending} pending and ${handoff.blockers.skipped} skipped reported cases. Missing evidence remains unverified; these counts are not a completion score.`;
for(const gap of handoff.evidenceGaps)el('handoff-evidence-gaps').append(make('li',`${gap.label}: ${pretty(gap.status)}`));
function primaryGuide(id,file,label){
  const target=clear(id);
  if(!file){target.append(make('p',`No ${label.toLowerCase()} is included in this view. Ask the agent to select the maintained document when packaging.`,'muted'));return;}
  target.append(make('h3',label),make('p',file.description||file.path,'muted'));
  const detail=make('details'),summary=make('summary','Read '+label.toLowerCase()),body=bytes(file.base64),preview=make('pre',body.length>2*1024*1024?'Preview is limited to 2 MiB. Download the complete document.':new TextDecoder().decode(body),'guide-preview');
  const button=make('button','Download document','secondary');button.type='button';button.onclick=()=>download(file.path.split('/').pop(),body);
  detail.append(summary,preview,button);target.append(detail);
}
primaryGuide('design-guide',handoff.primary.design,'Design document');
primaryGuide('implementation-guide',handoff.primary.implementation,'Implementation guide');
let assetId='',selection=assetSelection(models,review.relationships||[],assetId);
if(workflow){
  if(workflow.qualification){el('workflow-qualification').hidden=false;el('workflow-qualification').textContent=workflow.qualification;}
  el('stage').textContent=pretty(workflow.current_stage||eng.status);
  el('revision').textContent=workflow.design_id?`Design ${workflow.design_id} · revision ${workflow.design_revision}. Approval and deployment authority remain separate.`:'No design revision is recorded.';
  if(workflow.next_action){el('next-title').textContent='Continue your modeling engagement';el('next-detail').textContent=typeof workflow.next_action==='string'?workflow.next_action:workflow.next_action.description||workflow.next_action.action||text(workflow.next_action);const destination={design:['#changes','Review design and decisions'],implementation:['#delivery','Review implementation files'],semantic:['#delivery','Review semantic files'],validation:['#validation','Check validation evidence'],packaging:['#delivery','Review selected deliverables'],deployment:['#deployment','Review deployment plan']}[workflow.current_stage]||['#changes','Review decisions'];el('next-link').href=destination[0];el('next-link').textContent=destination[1]+' →';}
  if(workflow.stages?.length){const journey=clear('stage-journey');for(const stage of workflow.stages){const item=make('li',undefined,'stage-'+stage.status);item.append(make('strong',stage.label||pretty(stage.id)),make('small',pretty(stage.status)));if(stage.id===workflow.current_stage)item.setAttribute('aria-current','step');if(stage.next_action)item.append(make('small',stage.next_action));journey.append(item);}}
  if(workflow.task_plan?.tasks?.length){el('rerun-panel').hidden=false;table('rerun-tasks',[['Work',r=>r.id],['Stage',r=>pretty(r.stage)],['Next run',r=>pretty(r.action)],['Reason',r=>r.reason],['Original run',r=>r.original_run_id||'New work required']],workflow.task_plan.tasks);}
  const effort=workflow.effort;
  if(effort){el('effort-panel').hidden=false;card(el('effort-cards'),'Difficulty',pretty(effort.category),effort.rationale||'Review the work packages and assumptions.');card(el('effort-cards'),'Confidence',pretty(effort.confidence),effort.uncertainty||'Confidence reflects the evidence available for this assessment.');card(el('effort-cards'),'Readiness',pretty(effort.readiness),'A prerequisite can block work without making it technically harder.');el('effort-summary').textContent=effort.summary||'This assessment applies to the reviewed design and selected delivery route.';const breadth=make('p',`Breadth: ${text(effort.breadth)}`);el('effort-detail').append(breadth);for(const key of ['assumptions','prerequisites','dependencies','included_work','excluded_work'])if(effort[key]?.length){const group=make('div');group.append(make('h3',pretty(key)));const list=make('ul');for(const item of effort[key])list.append(make('li',item));group.append(list);el('effort-detail').append(group);}table('effort-packages',[['Work package',r=>r.name||r.id],['Difficulty',r=>pretty(r.category)],['Confidence / readiness',r=>`${pretty(r.confidence)} · ${pretty(r.readiness)}`],['Rationale / factors',r=>effortPackageDetails(r)]],effort.work_packages||[]);}
}
card(el('overview-cards'),'Scoped model',models.length?`${models.length} objects`:'Awaiting proposal','Every table, layer and key remains inspectable.');
card(el('overview-cards'),'Proposed changes',changes.length?`${changes.length} ${changes.length===1?'change':'changes'}`:'Awaiting assessment','Preserve sound models; review each change in meaning.');
card(el('overview-cards'),'Unresolved decisions',decisions.filter(d=>!['resolved','accepted'].includes(d.status)).length,'An empty list does not establish complete discovery.');
const questionValues={};
(eng.readiness.questions||[]).forEach((q,i)=>{if(typeof q==='string')q={key:(eng.readiness.missing_answers||[])[i]||`answer_${i}`,question:q};const key=q.key||q.id||q.field||`answer_${i}`,div=make('div',undefined,'question'),label=make('label',q.question||q.prompt||q.title||pretty(key));const multi=['deliverables','trusted_outputs','retained_behavior','corrected_behavior'].includes(key);const input=make((q.choices?.length&&!multi)?'select':'textarea');input.id='answer-'+i;label.htmlFor=input.id;if(input.tagName==='SELECT'){input.append(make('option','Choose an answer…'));input.firstChild.value='';q.choices.forEach(c=>{const option=make('option',pretty(c));option.value=c;input.append(option);});}else input.placeholder=multi?'One item per line. Use [] to record no requested corrections.':q.hint||'Add the missing context…';input.oninput=()=>{const v=input.value;questionValues[key]=multi?(v.trim()==='[]'?[]:v.split(/\n|,/).map(s=>s.trim()).filter(Boolean)):v;};div.append(label,input);if(multi&&q.choices?.length)div.append(make('p','Choose: '+q.choices.join(', '),'muted'));if(q.reason)div.append(make('p',q.reason,'muted'));el('questions').append(div);});
if(!(eng.readiness.questions||[]).length){empty('questions','No interview questions are currently recorded. Unresolved model decisions may still appear in Review changes.');el('save-answers').hidden=true;}
el('save-answers').onclick=()=>{const values={};for(const [k,v]of Object.entries(questionValues)){if(typeof v==='string'&&!v.trim())continue;values[k]=v;}if(!Object.keys(values).length)return notice('Enter at least one answer before saving.');download('interview-answers.json',JSON.stringify(values,null,2),'application/json');el('answer-note').textContent='Saved a request, not a workflow update. Give interview-answers.json to the agent: “Apply these answers to this engagement and refresh the review.” Existing answers are preserved.';};
const platform=eng.readiness.platform||{},caps=platform.capabilities||{};
for(const key of ['assessment','generation','execution']){const value=caps[key];card(el('capabilities'),pretty(key),typeof value==='object'?pretty(value.status):pretty(value||'not assessed'),typeof value==='object'?(value.summary||value.reason||value.note||'See findings and the selected platform contract.'):'No native validation is inferred from static inspection.');}
const coverage=platform.coverage||{};el('coverage').append(make('p',`${coverage.scanned_files??'Unknown'} files inspected · ${coverage.scanned_bytes??'Unknown'} bytes · ${coverage.complete?'Selected static inventory complete':'Inventory gaps remain'}`));const coverageDetails=make('details');coverageDetails.append(make('summary',`${(coverage.gaps||[]).length} gaps · ${(coverage.exclusions||[]).length} exclusions`));for(const item of [...(coverage.gaps||[]),...(coverage.exclusions||[])].slice(0,100)){coverageDetails.append(make('p',`${item.path} — ${pretty(item.reason)}`,'muted'));}if((coverage.gaps||[]).length+(coverage.exclusions||[]).length>100)coverageDetails.append(make('p','First 100 entries shown. Full coverage remains in the engagement assessment.','muted'));el('coverage').append(coverageDetails);
(platform.findings||[]).forEach(f=>{const box=make('article',undefined,'finding');box.append(make('span',pretty(f.severity||f.status||'review'),'pill'),make('h3',f.summary||f.title||f.id),make('p',f.next_action||f.remedy||f.description||'Review the recorded scope with the agent.'));if(f.paths?.length)box.append(make('code',f.paths.join(', ')));el('findings').append(box);});
if(!(platform.findings||[]).length)empty('findings','No findings are recorded. This is not proof of runtime compatibility.');
function openArtifact(id){const file=files.find(f=>f.id===id);if(!file)return notice('This artifact is outside the selected package. Ask the agent for the engineering handoff.');el('file-search').value=file.path;el('file-category').value='';fileList();showFile(file);location.hash='delivery';}
const qualityLanes=[['code_conventions','Code conventions','Code layout and configured rules'],['project_validity','Project validity','Selected framework and project structure'],['warehouse_validation','Warehouse validation','Checks against the selected warehouse'],['data_accuracy','Data accuracy','Independent checks of the model results']];
function qualityOmitted(id){return{id,status:'unknown',scope:'unknown',unit:'items',total:null,summary:'Quality evidence is not included in this page.',next_action:'Include the registered validation evidence to inspect this check.',gaps:['No selected evidence bytes are available.'],evidence_state:'not_included',checked:0,failed:0,skipped:0,unsupported:0,pending:0,unknown:0,not_applicable:0};}
for(const [id,title,meaning]of qualityLanes){const q=(review.quality_checks||[]).find(c=>c.id===id)||qualityOmitted(id),c=make('article',undefined,'quality-card');c.append(make('h3',title),make('span',q.evidence_state==='selected'?'Reported '+pretty(q.status):'Unknown','quality-status '+q.status),make('p',q.total===null?`${q.checked} ${q.unit} checked · total scope unknown`:`${q.checked} / ${q.total} ${q.unit} checked`,'quality-coverage'),make('p',meaning,'muted'),make('p',q.summary));const countNames=[['failed','failed'],['skipped','skipped'],['unsupported','unsupported'],['pending','pending'],['unknown','unresolved'],['not_applicable','not applicable']];const counts=countNames.filter(([key])=>q[key]>0).map(([key,label])=>`${q[key]} ${label}`);if(counts.length)c.append(make('p',counts.join(' · '),'muted'));if(q.gaps?.length){const list=make('ul');q.gaps.forEach(g=>list.append(make('li',g)));c.append(list);}c.append(make('p','Next: '+q.next_action,'quality-next'));if(q.evidence_state==='selected'&&files.some(f=>f.id===q.evidence_artifact_id)){const b=make('button','Inspect quality evidence','secondary');b.onclick=()=>openArtifact(q.evidence_artifact_id);c.append(b);}el('quality-summary').append(c);}
function metadataOmitted(ref){return{plan_artifact_id:ref.plan_artifact_id,sha256:ref.sha256,evidence_state:'not_included',status:'unknown',summary:'Metadata plan evidence is not included in this page.',next_action:'Include the registered metadata plan to inspect its scope, changes and blockers.'};}
function trimMetadataEvidence(next,selected){if(next.review?.metadata&&!selected.some(f=>f.id===next.review.metadata.plan_artifact_id))next.review.metadata=metadataOmitted(next.review.metadata);}
const metadata=review.metadata;
// BEGIN OMNI SUBSET HELPERS — unselected semantic details never survive export.
function omniOmitted(ref){return{artifact_id:ref.artifact_id,sha256:ref.sha256,evidence_state:'not_included',status:'unknown',summary:'Omni semantic evidence is not included in this page.',next_action:'Include the registered Omni semantic review to inspect topics, metrics, dependencies and gaps.'};}
function trimOmniEvidence(next,selected){if(next.review?.omni&&!selected.some(f=>f.id===next.review.omni.artifact_id))next.review.omni=omniOmitted(next.review.omni);}
// END OMNI SUBSET HELPERS
const omni=review.omni;
el('omni-nav').hidden=!omni;
if(omni){
  const selected=omni.evidence_state==='selected';el('omni-status').textContent=selected?'Candidate · native checks pending':'Evidence not included';
  el('omni-summary').textContent=selected?omni.qualification:omni.summary+' '+omni.next_action;el('omni-detail').hidden=!selected;
  if(selected){
    table('omni-topics',[['Topic',r=>r.label],['Base population',r=>r.base_view||'Unresolved'],['Reachable views',r=>r.scope.views.join(', ')],['Fields / AI awareness',r=>r.scope.selections.fields.length+' / '+r.scope.selections.ai_fields.length]],omni.topics);
    table('omni-metrics',[['Metric',r=>r.id],['Topic',r=>r.topic||'Shared model'],['Selection',r=>r.topic?`Query: ${r.selected_for_query?'selected':'not selected'} · AI: ${r.selected_for_ai?'aware':'not selected'}`:'Shared inventory'],['Meaning',r=>r.description||'Definition needs review'],['Aggregation',r=>r.aggregate_type||'Custom expression'],['Population',r=>r.has_local_filter?'Measure-local filter':'No local filter declared']],omni.metrics);
    table('omni-query-views',[['Query view',r=>r.id],['Kind',r=>pretty(r.kind)],['Outputs',r=>r.outputs.join(', ')],['Population',r=>r.complete_population?'No declared limit':'Limited output'],['Qualification',r=>pretty(r.runtime_eligibility)]],Object.entries(omni.query_views).map(([id,r])=>({id,...r})));
    table('omni-dependencies',[['Source view',r=>r.from],['Dependent view',r=>r.to],['Relationship',r=>pretty(r.kind)]],omni.dependencies);
    table('omni-decisions',[['Subject',r=>r.subject],['Placement',r=>r.placement],['Reason',r=>r.reason],['Status',r=>r.status]],omni.decisions);
    table('omni-unknowns',[['Artifact',r=>r.path],['Gap',r=>r.code],['Location',r=>r.location]],omni.unknowns);
    omni.next_actions.forEach(step=>el('omni-next').append(make('li',step)));el('omni-inspect').onclick=()=>openArtifact(omni.artifact_id);
  }
}
el('metadata-nav').hidden=!metadata;
if(metadata){
  const selected=metadata.evidence_state==='selected';
  el('metadata-status').textContent=selected?({ready:'Candidate ready for review',blocked:'Candidate blocked',no_op:'No changes planned'}[metadata.status]||'Unknown'):'Evidence not included';
  el('metadata-summary').textContent=selected?metadata.qualification:metadata.summary+' '+metadata.next_action;
  el('metadata-detail').hidden=!selected;
  if(selected){
    Object.values(metadata.target).forEach(v=>el('metadata-target').append(make('span',pretty(v),'pill')));
    el('metadata-baseline').textContent=`Baseline: ${pretty(metadata.observation.origin)} · ${metadata.observation.observed_at}. ${metadata.observation.qualification}`;
    const c=metadata.counts;
    card(el('metadata-counts'),'Required resources',`${c.resources_required} / ${c.resources_selected}`,`${c.model_resources} model resources · ${c.source_resources} RAW source resources · ${c.resources_excluded} outside native write scope`);
    card(el('metadata-counts'),'Required columns',`${c.columns_required} / ${c.columns_selected}`,`${c.observed_resources} resources and ${c.observed_columns} columns in the reported baseline`);
    card(el('metadata-counts'),'Proposed writes',c.native_statements,`${c.comment_writes} comments · ${c.direct_tag_writes} direct tag assignments · ${c.unchanged_assignments} already matching assignments`);
    const phases={governance_readiness:'Governance readiness',framework_build:'Build the selected project',target_metadata:'Apply target metadata',source_metadata:'Apply authorized RAW metadata',readback:'Collect independent readback',consumer_handoff:'Confirm consumer handoff'};
    metadata.sequence.forEach(phase=>el('metadata-sequence').append(make('li',phases[phase]||pretty(phase))));
    const relation=r=>[...r.namespace,r.name].map(x=>JSON.stringify(x)).join('.');
    table('metadata-scope',[['Resource',r=>r.id],['Layer',r=>r.layer],['Relation',r=>relation(r.relation)],['Columns',r=>r.columns],['Scope',r=>pretty(r.disposition)],['Reason / RAW decision',r=>[r.reason,r.source_write_decision].filter(Boolean).join(' · ')||'No exclusion recorded']],metadata.scope);
    const value=v=>make('span',v===null?'No value':v,'metadata-value');
    const changes=()=>{const term=el('metadata-search').value.toLowerCase();table('metadata-changes',[['Resource / column',r=>r.resource_id+(r.column===null?'':' · '+r.column)],['Change',r=>pretty(r.kind)+(r.tag_name?' · '+r.tag_name.join('.'):'')],['Before',r=>value(r.before)],['After',r=>value(r.after)],['Phase',r=>phases[r.phase]||pretty(r.phase)]],metadata.changes.filter(r=>JSON.stringify(r).toLowerCase().includes(term)));};
    el('metadata-search').oninput=changes;changes();
    if(metadata.blockers.length){const list=make('ul');metadata.blockers.forEach(b=>list.append(make('li',b)));el('metadata-blockers').append(list);}else el('metadata-blockers').append(make('p','No structural planning blockers are recorded. Execution, readback and consumer acceptance remain separate.','muted'));
    el('metadata-blockers').append(make('p',`${c.unknown_sensitivity_columns} columns retain UNKNOWN sensitivity. Unknown does not mean public.`, 'muted'));
    table('metadata-unknowns',[['Resource',r=>r.resource_id],['Column',r=>r.column],['Unknown',r=>r.reason]],metadata.unknowns);
    const privileges=make('ul');metadata.privilege_requirements.forEach(p=>privileges.append(make('li',p)));el('metadata-privileges').append(privileges);
    table('metadata-governance',[['Tag',r=>r.name.join('.')],['Requested value',r=>r.requested_value],['Request',r=>pretty(r.action)]],metadata.governance_requests);
    el('metadata-hash').textContent=`Artifact SHA-256: ${metadata.sha256}. Plan: ${metadata.plan_sha256}. Candidate: ${metadata.candidate_sha256}. Hashes bind selected bytes; they do not authenticate authority.`;
    el('metadata-inspect').onclick=()=>openArtifact(metadata.plan_artifact_id);
  }
}
const deployment=data.deployment||null, deploymentActions=['publish_pr','deploy_development','promote'];
function deploymentChoice(){return deployment?.choices?.find(c=>c.id===el('deployment-action').value);}
function concreteDeploymentPlan(action){const p=deployment?.plan;return p&&p.action===action&&p.id&&p.sha256&&p.files?.length&&p.files.every(f=>f.version&&f.operation)&&p.summary&&p.target_label&&p.impacts?.length&&p.steps?.length&&p.recovery?.length?p:null;}
function updateDeploymentAction(){const choice=deploymentChoice(),available=deployment?.current===true&&choice?.available===true,plan=concreteDeploymentPlan(choice?.id);el('deployment-reason').textContent=(choice?.reason||'Select an action to review its current prerequisites.')+(deployment?.plan&&choice&&deployment.plan.action!==choice.id?' The displayed preview is for '+pretty(deployment.plan.action)+'; request a new plan for this action.':'');el('save-deployment-request').disabled=!available;el('save-deployment-request').textContent=plan?'Save deployment request':'Request a concrete plan';el('deployment-request-note').textContent=plan?'This request binds the displayed plan version, retained target and selected action. The coordinator must recheck files, target and required authority before any action.':'A complete plan for this action is not displayed. This saves a plan-preparation request; it does not ask the browser to execute or approve an action.';}
el('deployment-status').textContent=deployment?'Reported: '+pretty(deployment.status):'No deployment review supplied';
el('deployment-summary').textContent=deployment?.assurance||'A current prepared handoff and a deployment review from the agent are required. No action is available from this page yet.';
Object.entries(deployment?.target||eng.target||{}).filter(([,v])=>v).forEach(([key,value])=>el('deployment-target').append(make('span',`${pretty(key)}: ${pretty(value)}`,'pill')));
el('deployment-next').textContent=deployment?.next_action||'Ask the agent to prepare deployment choices for the retained target after the handoff is current.';
for(const id of deploymentActions){const choice=deployment?.choices?.find(c=>c.id===id),option=make('option',(choice?.label||pretty(id))+(choice?.available?'':' — not available'));option.value=id;el('deployment-action').append(option);}
if(deployment?.plan?.action)el('deployment-action').value=deployment.plan.action;
el('deployment-action').onchange=()=>{el('deployment-request-result').textContent='';updateDeploymentAction();};
if(deployment?.plan){const p=deployment.plan,detail=el('deployment-plan-detail');detail.append(make('h3',`${pretty(p.action)} · ${p.target_label}`),make('p',p.summary),make('p',`Plan ${p.id} · ${deployment.current?'Current recorded context':'Stale context; requests disabled'}`,'deployment-plan-status'),make('p',`Execution plan SHA-256: ${p.sha256}`,'deployment-binding'),make('p',`Prepared artifact manifest: ${deployment.handoff?.manifest_sha256||'Not supplied'}`,'deployment-binding'));if(files.some(f=>f.id===p.evidence_artifact_id)){const b=make('button','Inspect plan evidence','secondary');b.onclick=()=>openArtifact(p.evidence_artifact_id);detail.append(b);}table('deployment-plan-files',[['File',r=>r.path],['Version / operation',r=>`${r.version||'Version unresolved'} · ${r.operation||'Operation unresolved'}`],['SHA-256',r=>r.sha256]],p.files||[]);for(const [key,title]of [['impacts','Action impact'],['steps','Planned steps'],['recovery','Recovery'],['prerequisites','Prerequisites']]){const group=make('div');group.append(make('h3',title));const list=make(key==='steps'?'ol':'ul');(p[key]?.length?p[key]:['Not supplied; resolve with the coordinator.']).forEach(value=>list.append(make('li',value)));group.append(list);el('deployment-plan-lists').append(group);}}else empty('deployment-plan-detail',deployment?.plan_omitted||'No concrete deployment plan is included. Request one before considering approval or execution.');
table('deployment-receipts',[['Action',r=>pretty(r.action)],['Reported result',r=>pretty(r.status)],['Scope / interpretation',r=>`${r.scope||'Scope unresolved'} · ${r.summary||'No summary supplied'}`],['Evidence',r=>{if(!files.some(f=>f.id===r.evidence_artifact_id))return'Evidence outside this page; ask the agent for the registered receipt.';const b=make('button','Inspect reported receipt','secondary');b.onclick=()=>openArtifact(r.evidence_artifact_id);return b;}]],deployment?.receipts||[]);
el('save-deployment-request').onclick=()=>{const choice=deploymentChoice();if(!deployment?.current||!choice?.available)return notice('Refresh the deployment review before requesting this action.');const plan=concreteDeploymentPlan(choice.id),request={schema_version:1,kind:'deployment_request',intent:plan?'reviewed_plan_request':'prepare_plan',action:choice.id,context_sha256:eng.context_sha256,handoff_manifest_sha256:deployment.handoff.manifest_sha256,target:deployment.target,plan_id:plan?.id||null,plan_sha256:plan?.sha256||null,request_only:true,created_at:new Date().toISOString()};download('deployment-request-'+choice.id+'.json',JSON.stringify(request,null,2),'application/json');el('deployment-request-result').textContent='Request saved. Give this JSON file to the agent. It is not authorization, a signed approval, or an execution receipt.';};
updateDeploymentAction();
function modelLink(model){const n=make('div');n.append(make('strong',model.name||model.id),make('small',`${model.layer} · ${model.grain||'Grain unresolved'}`));if(model.artifact_id&&files.some(f=>f.id===model.artifact_id)){const b=make('button','Open code','secondary');b.type='button';b.onclick=()=>openArtifact(model.artifact_id);n.append(b);}return n;}
function changeTable(){const q=el('change-search').value.toLowerCase();table('changes-table',[['Existing',r=>r.source],['Proposed',r=>{const file=files.find(f=>f.path.endsWith('/'+r.target));if(!file)return r.target;const b=make('button',r.target,'secondary');b.type='button';b.onclick=()=>openArtifact(file.id);return b;}],['Disposition',r=>pretty(r.disposition)],['Why / affected consumers',r=>{const n=make('div');n.append(make('strong',r.rationale),make('small',(r.consumers||[]).join(', ')||'Consumer coverage unresolved'));return n;}],['Decision',r=>r.decision||'Unresolved']],changes.filter(r=>matchesAsset(r,selection,assetId)&&JSON.stringify(r).toLowerCase().includes(q)));}el('change-search').oninput=changeTable;changeTable();
const decisionInputs=new Map();
function canAnswerDecisions(){return Boolean(workflow?.design_id&&Number.isInteger(workflow.design_revision)&&/^[a-f0-9]{64}$/.test(workflow.design_sha256||''));}
el('decision-binding').textContent=canAnswerDecisions()?`Answers will bind design ${workflow.design_id}, revision ${workflow.design_revision}. The agent checks freshness before recording them.`:'A current design binding is needed to export answers. Ask the agent to refresh this review; legacy decision statements remain readable.';
function decisionList(){
  const target=clear('decisions'),rows=decisions.filter(d=>matchesAsset(d,selection,assetId));
  for(const d of rows){
    const item=make('details');item.append(make('summary',`${d.id} · ${d.question}`),make('p',`Status: ${pretty(d.status||'unresolved')} · Reviewer: ${d.reviewer_role||'Unassigned'}`));
    item.append(make('p',`Affected entities: ${(d.model_ids||[]).join(', ')||'Mapping unresolved'} · Blocking stages: ${(d.blocking_stages||[]).map(pretty).join(', ')||'Not specified'}`,'muted'));
    if(d.recommendation)item.append(make('p',`Recommendation: ${d.recommendation}`));
    if(d.rationale)item.append(make('p',d.rationale));if(d.evidence_summary)item.append(make('p',`Evidence: ${d.evidence_summary}`,'muted'));
    item.append(make('p',d.answer?`Recorded answer: ${d.answer}`:'No answer has been recorded.'));
    const canAnswer=canAnswerDecisions()&&(workflow.decisions||[]).some(row=>row.id===d.id);
    if(canAnswer){
      let values=decisionInputs.get(d.id);if(!values){values={selected:false,answer:'',option_id:null,rationale:''};decisionInputs.set(d.id,values);}
      const includeLabel=make('label',undefined,'decision-select'),include=make('input');include.type='checkbox';include.checked=values.selected;include.onchange=()=>{values.selected=include.checked;updateDecisionButton();};includeLabel.append(include,make('span','Include this response'));item.append(includeLabel);
      if(d.options?.length){const label=make('label','Choose an option'),input=make('select');input.setAttribute('aria-label',`Option for ${d.id}`);const blank=make('option','Choose an option or write an answer');blank.value='';input.append(blank);for(const option of d.options){const element=make('option',option.label);element.value=option.id;input.append(element);}input.value=values.option_id||'';input.onchange=()=>{values.option_id=input.value||null;const option=d.options.find(o=>o.id===input.value);if(option){values.answer=option.label;answer.value=option.label;}};label.append(input);item.append(label);}
      const answerLabel=make('label','Your answer'),answer=make('textarea');answer.setAttribute('aria-label',`Answer for ${d.id}`);answer.value=values.answer;answer.oninput=()=>{values.answer=answer.value;};answerLabel.append(answer);item.append(answerLabel);
      const rationaleLabel=make('label','Reason or evidence (optional)'),rationale=make('textarea');rationale.setAttribute('aria-label',`Reason for ${d.id}`);rationale.value=values.rationale;rationale.oninput=()=>{values.rationale=rationale.value;};rationaleLabel.append(rationale);item.append(rationaleLabel);
    }
    target.append(item);
  }
  if(!rows.length)empty('decisions',decisions.length?'No decisions match this display filter.':'No decisions are recorded. An empty inbox does not establish complete discovery.');
  updateDecisionButton();
}
function updateDecisionButton(){const selected=[...decisionInputs.values()].filter(v=>v.selected).length;el('save-decisions').disabled=!canAnswerDecisions()||!selected;el('save-decisions').textContent=`Save selected decision answers${selected?' ('+selected+')':''}`;}
el('save-decisions').onclick=()=>{try{const answers=[...decisionInputs].filter(([,v])=>v.selected).map(([decision_id,v])=>({decision_id,answer:v.answer,option_id:v.option_id,rationale:v.rationale}));const result=decisionResponseDocument(workflow,eng.engagement_id,answers);download('decision-responses.json',JSON.stringify(result,null,2),'application/json');el('decision-receipt').textContent=`Saved ${answers.length} responses for design revision ${workflow.design_revision}. Give the file to the agent in this engagement. The file does not approve a design or authorize deployment; the agent will confirm whether each answer was recorded.`;}catch(error){notice(error.message);}};
decisionList();
const views=data.diagrams||(data.diagram?[{label:'All layers',base64:data.diagram,model_ids:models.map(m=>m.id)}]:[]);
let shownViews=[],currentDiagram=null;
function buildViews(){
  if(!assetId)shownViews=views;
  else{const filtered=models.filter(m=>selection.visible.has(m.id));shownViews=[];for(let offset=0;offset<filtered.length;offset+=36){const page=filtered.slice(offset,offset+36),ids=new Set(page.map(m=>m.id)),edges=(review.relationships||[]).filter(r=>ids.has(r.from)&&ids.has(r.to)),svg=filteredModelSvg(page,edges.slice(0,120),selection.dependencies,Math.max(0,edges.length-120));shownViews.push({omitted_graph_connections:Math.max(0,edges.length-120),label:`Selected assets · view ${shownViews.length+1}`,svg,model_ids:page.map(m=>m.id),cross_view_connections:(review.relationships||[]).filter(r=>selection.visible.has(r.from)&&selection.visible.has(r.to)&&ids.has(r.from)!==ids.has(r.to)).length});}}
  const select=clear('diagram-view');shownViews.forEach((v,i)=>{const option=make('option',v.label);option.value=String(i);select.append(option);});showDiagram();
}
function showDiagram(){const view=shownViews[Number(el('diagram-view').value)||0];currentDiagram=view||null;el('diagram-download').disabled=!view;el('diagram-view').hidden=!shownViews.length;if(view){const img=make('img');img.src=view.svg?'data:image/svg+xml;base64,'+btoa(Array.from(new TextEncoder().encode(view.svg),byte=>String.fromCharCode(byte)).join('')):'data:image/svg+xml;base64,'+view.base64;img.alt='Layered architecture with table blocks, key columns and declared connectors';clear('diagram').append(img);el('diagram-coverage').textContent=`${view.model_ids?.length||0} of ${assetId?selection.visible.size:models.length} visible model objects in this view · ${view.cross_view_connections||0} connections continue in other views. ${view.omitted_graph_connections?view.omitted_graph_connections+' additional connectors omitted from this image to keep it readable. ':''}All visible declared connections remain in the ledger below.`;}else{empty('diagram',assetId?'No model objects match this asset. Mapping coverage remains unresolved.':'The agent will add a connected diagram when the model inventory is available.');el('diagram-coverage').textContent='No diagram is available for this display selection.';}}
el('diagram-view').onchange=showDiagram;
el('diagram-download').onclick=()=>{if(currentDiagram)download(assetId?'filtered-model-architecture.svg':'model-architecture.svg',currentDiagram.svg||bytes(currentDiagram.base64),'image/svg+xml');};
function relationshipTable(){table('relationships',[['From',r=>r.from],['To',r=>r.to],['Predicate / cardinality / role',r=>[r.label||r.kind,r.predicate&&`Predicate: ${r.predicate}`,r.cardinality&&`Cardinality: ${r.cardinality}`,r.role&&`Role: ${r.role}`].filter(Boolean).join(' · ')],['Declared implementation',r=>r.status||r.implementation_status||'Not specified'],['Evidence',r=>r.evidence||'Unresolved']],(review.relationships||[]).filter(r=>selection.visible.has(r.from)&&selection.visible.has(r.to)),10);}
function dictionary(){const q=el('model-search').value.toLowerCase(),layer=el('layer-filter').value,rows=[];models.filter(m=>selection.visible.has(m.id)&&(!layer||m.layer===layer)).forEach(m=>(m.columns?.length?m.columns:[{name:'Columns not included',description:'See the separately selected dictionary.'}]).forEach(c=>{const r={model:m,column:c};if(JSON.stringify({id:m.id,name:m.name,grain:m.grain,layer:m.layer,domain:m.domain,column:c}).toLowerCase().includes(q))rows.push(r);}));table('dictionary',[['Table / grain',r=>modelLink(r.model)],['Column',r=>r.column.name],['Type / key',r=>`${r.column.type||'Unresolved'} ${r.column.key||''}`],['Definition',r=>r.column.description||'Not supplied']],rows);}
el('model-search').oninput=dictionary;el('layer-filter').onchange=dictionary;
for(const asset of review.assets||[]){const option=make('option',`${asset.name||asset.id} · ${asset.kind||'asset'} · ${asset.mapping_status||'mapping unverified'}`);option.value=asset.id;el('asset-filter').append(option);}
el('asset-controls').hidden=!models.length&&!(review.assets||[]).length;
function filterAssets(){assetId=el('asset-filter').value;selection=assetSelection(models,review.relationships||[],assetId);el('asset-filter-note').textContent=`${selection.visible.size} of ${models.length} entities visible; ${selection.dependencies.size} required dependencies retained. ${selection.unknown.size} entities have missing or unverified asset mappings. Unmapped decisions and changes remain visible.`;buildViews();relationshipTable();dictionary();changeTable();decisionList();}
el('asset-filter').onchange=filterAssets;filterAssets();
card(el('validation-counts'),'Reported passes',cases.filter(c=>c.status==='pass').length,`${cases.length} total declared cases; scope is shown per case.`);
card(el('validation-counts'),'Failures',cases.filter(c=>c.status==='fail').length,'Unexplained mismatches remain visible.');
card(el('validation-counts'),'Pending or skipped',cases.filter(c=>['pending','skipped'].includes(c.status)).length,'Missing checks cannot count as passing evidence.');
function validation(){const filter=el('validation-filter').value;table('validation-cases',[['Case',r=>r.label||r.id],['Scope',r=>pretty(r.scope)],['Reported status',r=>make('strong',pretty(r.status),r.status)],['Expected → observed',r=>data.audience==='reviewer'?'Values omitted from reviewer export':`${text(r.expected)} → ${text(r.actual)}`],['Evidence / interpretation',r=>`${r.evidence_id||'No evidence association'} · ${r.details||'No explanation supplied'}`]],cases.filter(c=>!filter||c.status===filter));}el('validation-filter').onchange=validation;validation();
el('audience').textContent=pretty(data.audience);
const chosen=new Set(files.map(f=>f.category));
for(const category of chosen){const label=make('label'),input=make('input');input.type='checkbox';input.checked=true;input.value=category;input.onchange=()=>{if(input.checked)chosen.add(category);else chosen.delete(category);updateExport();};label.append(input,make('span',pretty(category)));el('export-choices').append(label);const option=make('option',pretty(category));option.value=category;el('file-category').append(option);}
function selectedFiles(){return files.filter(f=>chosen.has(f.category));}
function updateExport(){const selected=selectedFiles(),ids=new Set(selected.map(f=>f.id)),missing=selected.flatMap(f=>(f.requires||[]).filter(id=>!ids.has(id)).map(id=>`${f.id} requires ${id}`));el('download-package').disabled=!selected.length||missing.length>0;el('export-dependencies').textContent=missing.length?'Include required deliverables: '+missing.join('; '):`${selected.length} of ${files.length} files selected. Unselected payloads are removed from the new download.`;}updateExport();
if(!files.length){empty('export-choices',eng.delivery?.status==='prepared'?'No files are embedded in this status page. Ask the agent to export the prepared artifacts for your selected audience and deliverables.':'No files are embedded in this status page. Ask the agent to generate and package the selected deliverables after discovery.');}
let activeFile=null;
function showFile(file){activeFile=file;el('file-title').textContent=file.path;el('file-note').textContent=(file.description||'')+(file.category==='implementation'?' dbt models belong in their project; native SQL follows the selected platform’s run order.':'');const body=bytes(file.base64);el('file-content').textContent=body.length>2*1024*1024?'Preview limited to 2 MiB. Download the complete file to inspect it.':new TextDecoder().decode(body);el('copy-code').disabled=body.length>2*1024*1024;el('download-file').disabled=false;document.querySelectorAll('#file-list button').forEach(b=>b.classList.toggle('active',b.dataset.file===file.id));}
function fileList(){const q=el('file-search').value.toLowerCase(),cat=el('file-category').value,target=clear('file-list');const found=files.filter(f=>(!cat||f.category===cat)&&(f.path+' '+f.description).toLowerCase().includes(q));found.slice(0,200).forEach(f=>{const b=make('button',f.path);b.type='button';b.dataset.file=f.id;b.onclick=()=>showFile(f);target.append(b);});if(found.length>200)target.append(make('p',`${found.length} matches. Narrow the search to view more.`,'muted'));if(!found.length)target.append(make('p','No matching files.','empty'));}el('file-search').oninput=fileList;el('file-category').onchange=fileList;fileList();
el('copy-code').onclick=async()=>{try{await navigator.clipboard.writeText(el('file-content').textContent);notice('File text copied.');}catch{const range=document.createRange();range.selectNodeContents(el('file-content'));const selection=getSelection();selection.removeAllRanges();selection.addRange(range);notice('Clipboard access is unavailable. The file text is selected; use your normal Copy shortcut.');}};
el('download-file').onclick=()=>activeFile&&download(activeFile.path.split('/').pop(),bytes(activeFile.base64));
// Stored ZIP format keeps offline exports independent of CDNs and native tools.
function crc32(array){let crc=0xffffffff;for(const byte of array){crc^=byte;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return(crc^0xffffffff)>>>0;}
function zip(entries){const chunks=[],central=[];let offset=0,size=0;const enc=new TextEncoder();for(const [path,body]of entries){const name=enc.encode(path),header=new Uint8Array(30+name.length),v=new DataView(header.buffer),crc=crc32(body);v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(6,0x800,true);v.setUint16(12,33,true);v.setUint32(14,crc,true);v.setUint32(18,body.length,true);v.setUint32(22,body.length,true);v.setUint16(26,name.length,true);header.set(name,30);chunks.push(header,body);const c=new Uint8Array(46+name.length),cv=new DataView(c.buffer);cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);cv.setUint16(8,0x800,true);cv.setUint16(14,33,true);cv.setUint32(16,crc,true);cv.setUint32(20,body.length,true);cv.setUint32(24,body.length,true);cv.setUint16(28,name.length,true);cv.setUint32(42,offset,true);c.set(name,46);central.push(c);offset+=header.length+body.length;size+=c.length;}const end=new Uint8Array(22),ev=new DataView(end.buffer);ev.setUint32(0,0x06054b50,true);ev.setUint16(8,entries.length,true);ev.setUint16(10,entries.length,true);ev.setUint32(12,size,true);ev.setUint32(16,offset,true);return new Blob([...chunks,...central,end],{type:'application/zip'});}
async function sha256(body){const hash=await crypto.subtle.digest('SHA-256',body);return Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,'0')).join('');}
el('download-package').onclick=async()=>{
  try{
    if(!crypto.subtle)throw new Error('This browser cannot check file hashes here. Use the original package or ask the agent to export your selected categories.');
    const selected=selectedFiles(),entries=await checkedSubsetFiles(files,selected,chosen),next=structuredClone(data);
    next.files=selected;
    next.engagement.delivery_assurance=portableAssurance(eng);
    next.export_review={origin:'browser_subset',status:'candidate',content_scan:'not_run_in_browser',disclosure_policy:'not_revalidated_in_browser',acceptance_ready:false,deployment_authorized:false};
    trimMetadataEvidence(next,selected);
    trimOmniEvidence(next,selected);
    trimHandoff(next,selected);
    trimWorkflowDetails(next,chosen);
    if(next.deployment){
      const selectedIds=new Set(selected.map(f=>f.id));
      if(next.deployment.plan&&!selectedIds.has(next.deployment.plan.evidence_artifact_id)){
        delete next.deployment.plan;
        next.deployment.plan_omitted='Plan details are outside this export; request the selected deployment evidence from the agent.';
      }
      next.deployment.receipts=(next.deployment.receipts||[]).filter(r=>selectedIds.has(r.evidence_artifact_id));
    }
    if(!chosen.has('diagrams')){delete next.diagram;delete next.diagrams;}
    if(next.review.quality_checks){
      const selectedIds=new Set(selected.map(f=>f.id));
      next.review.quality_checks=next.review.quality_checks.map(q=>selectedIds.has(q.evidence_artifact_id)?q:qualityOmitted(q.id));
    }
    if(!chosen.has('validation'))delete next.review.validation;
    if(!['documentation','diagrams','dictionary'].some(x=>chosen.has(x))){delete next.review.models;delete next.review.relationships;}
    else if(!chosen.has('dictionary'))(next.review.models||[]).forEach(m=>delete m.columns);
    const encoded=JSON.stringify(next).replaceAll('<','\\u003c').replaceAll('>','\\u003e').replaceAll('&','\\u0026');
    const shell=originalShell.replace(/(<script id="delivery-data" type="application\/json">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+encoded+b);
    entries.push(['START_HERE.html',new TextEncoder().encode(shell)]);
    const manifest=await browserSubsetManifest(eng,data.audience,chosen,entries);
    entries.push(['DELIVERY_MANIFEST.json',new TextEncoder().encode(JSON.stringify(manifest,null,2))]);
    download('model-delivery-'+data.audience+'.zip',zip(entries),'application/zip');
    notice('Candidate subset created with checked file hashes. No new content scan or disclosure approval was performed; return this exact ZIP to the agent before sharing.');
  }catch(error){notice(error.message);}
};
