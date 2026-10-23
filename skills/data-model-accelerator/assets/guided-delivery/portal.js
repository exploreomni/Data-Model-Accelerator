/* Local review only. No network, native execution, or approval mutation. */
'use strict';
(function bootPortal(){
if(document.documentElement.__dmaPortalBooted)return;
const originalShell = '<!doctype html>\n' + document.documentElement.outerHTML;
document.documentElement.__dmaPortalBooted=true;
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
async function checkedSubsetFiles(inventory,selection,categories,allowEmpty=false){
  if(!Array.isArray(inventory)||!Array.isArray(selection)||(!selection.length&&!allowEmpty)||selection.length>500)throw new Error('Select a bounded registered file set.');
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
async function browserSubsetManifest(snapshot,audience,categories,entries,page=null){
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
  if([1,2].includes(page?.package_layout_version))manifest.package_layout_version=page.package_layout_version;
  if(page?.checkpoint){manifest.delivery_kind='checkpoint';manifest.checkpoint=structuredClone(page.checkpoint);}
  if(page?.topic_coverage)manifest.topic_coverage=structuredClone(page.topic_coverage);
  for(const [path,body]of entries){const record={path,sha256:await sha256(body),bytes:body.length};if([1,2].includes(page?.package_layout_version)){const registered=page.files.find(f=>f.path===path),generated=page.generated_deliverables.find(f=>f.path===path),file=registered||generated;if(file)Object.assign(record,{role:registered?'registered_artifact':'generated_deliverable',category:file.category,embedded:true});else if(path==='START_HERE.html'||path==='README.md')Object.assign(record,{role:path==='START_HERE.html'?'entrypoint':'index',embedded:false});else throw new Error('Unclassified package file: '+path);}manifest.files.push(record);}
  return manifest;
}
function updateCheckpointDeficits(snapshot){
  if(!snapshot.checkpoint)return;
  const present=new Set([...(snapshot.files||[]),...(snapshot.generated_deliverables||[])].filter(f=>f.size>0).map(f=>f.category));
  const previous=new Set(snapshot.checkpoint.missing_categories||[]);
  snapshot.checkpoint.missing_categories=snapshot.checkpoint.requested_categories.filter(c=>previous.has(c)||!present.has(c));
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
  if(!categories.has('documentation'))delete snapshot.workflow?.frontend_continuation;
  const frontendFiles=new Set((snapshot.files||[]).map(f=>f.id));
  for(const row of snapshot.workflow?.frontend_continuation?.items||[])row.artifact_ids=(row.artifact_ids||[]).filter(id=>frontendFiles.has(id));
  if(!(categories.has('documentation')&&categories.has('dictionary')))delete snapshot.workflow?.governance;
  if(snapshot.migration_planning&&!(categories.has('documentation')&&categories.has('dictionary'))){
    delete snapshot.migration_planning;
    snapshot.migration_planning_omitted='Migration planning files were omitted: include both documentation and dictionary to export their complete mapping and column inventory.';
  }
  if(snapshot.audience!=='audit'&&['documentation','diagrams','dictionary'].some(key=>categories.has(key)))return;
  delete snapshot.migration_review;
  delete snapshot.source_lineage;
  delete snapshot.staging_ports;
  delete snapshot.domain_journey;
  delete snapshot.legacy_alignment;
  delete snapshot.migration_planning;
  for(const key of ['assets','models','relationships','domain_proposals','decisions','changes'])delete snapshot.review?.[key];
  for(const key of ['decisions','effort','models','relationships','assets','task_plan','design_checks','artifact_checks','review_assurance','design_readiness','migration_intent','governance'])delete snapshot.workflow?.[key];
}
// Coverage/reuse counts describe supplied associations, never native validation.
function reviewEvidenceCount(value){return Number.isSafeInteger(value)&&value>=0?String(value):'Unassessed';}
function reviewEvidenceList(value){return Array.isArray(value)?value.filter(v=>typeof v==='string'&&v.trim()):[];}
function reviewEvidenceDimensions(row,kind,coverageRows){
  const modelIds=reviewEvidenceList(row.model_ids);
  const assets=kind==='reuse'?[...new Set(coverageRows.filter(item=>reviewEvidenceList(item.model_ids).some(id=>modelIds.includes(id))).map(item=>item.asset).filter(v=>typeof v==='string'&&v.trim()))]:reviewEvidenceList([row.asset]);
  return{asset:assets,domain:reviewEvidenceList([kind==='reuse'?row.owner_domain:row.domain]),model:modelIds};
}
function reviewEvidenceMatches(row,kind,filters,coverageRows){
  const dims=reviewEvidenceDimensions(row,kind,coverageRows);
  for(const key of ['asset','domain','model'])if(filters[key]&&(filters[key]==='__unknown__'?dims[key].length>0:!dims[key].includes(filters[key])))return false;
  const search=typeof filters.search==='string'?filters.search.trim().toLowerCase():'';
  const values=['id','asset','name','domain','existing_id','owner_domain','status','disposition','compatibility','freshness','rationale'].map(key=>typeof row[key]==='string'?row[key]:'');
  return !search||[...values,...dims.model,...dims.asset,...reviewEvidenceList(row.requirement_ids)].join(' ').toLowerCase().includes(search);
}
function reviewEvidenceSelection(assurance,filters={}){
  const coverage=Array.isArray(assurance?.coverage?.rows)?assurance.coverage.rows.slice(0,500):[];
  const reuse=Array.isArray(assurance?.reuse?.rows)?assurance.reuse.rows.slice(0,500):[];
  const groups=Array.isArray(assurance?.coverage?.groups)?assurance.coverage.groups:[];
  return{coverage:coverage.filter(row=>reviewEvidenceMatches(row,'coverage',filters,coverage)),reuse:reuse.filter(row=>reviewEvidenceMatches(row,'reuse',filters,coverage)),groups:groups.filter(row=>reviewEvidenceMatches(row,'coverage',filters,coverage)),coverageRows:coverage,reuseRows:reuse};
}
// Legacy graph labels remain compatible; declared canonical kinds are preserved.
function designObjectKind(model){return ['model','source','interface','semantic','reference'].includes(model.object_kind)?model.object_kind:model.layer==='bronze'?'source':'model';}
function designInventoryObject(model){return ['model','source','interface'].includes(designObjectKind(model));}
function objectKindLabel(model){return({model:'Model',source:'Source',interface:'External interface',semantic:'Semantic object',reference:'Reference only'})[designObjectKind(model)];}
function relationshipColumns(edge){return edge.from_columns?.length||edge.to_columns?.length?(edge.from_columns||[]).join(', ')+' → '+(edge.to_columns||[]).join(', '):'Column bindings not supplied';}
// One normalized graph for both diagram entry points. No physical bindings are guessed.
function modelGraph(modelRows,relationships,omni,proposals=[]){
  const records=relationships.map((e,i)=>({...e,occurrence_id:'canonical:'+(i+1),record_origin:'canonical',record_position:i+1}));
  const domainsByModel=new Map();for(const p of proposals)for(const id of p.model_ids||[]){if(!domainsByModel.has(id))domainsByModel.set(id,[]);domainsByModel.get(id).push(p.domain);}
  const rows=modelRows.map(m=>({...m,proposal_domains:domainsByModel.get(m.id)||[]})),knownModels=new Set(rows.map(m=>m.id));
  for(const proposal of proposals){
    for(const endpoint of proposal.reference_endpoints||[])if(!knownModels.has(endpoint.id)){rows.push({id:endpoint.id,name:endpoint.name||endpoint.id,layer:'reference',object_kind:'reference',reference_only:true,grain:'Definition absent from included model inventory'});knownModels.add(endpoint.id);}
    (proposal.relationships||[]).forEach((e,i)=>records.push({...e,occurrence_id:'proposal:'+proposal.id+':'+(i+1),record_origin:'domain_proposal',proposal_id:proposal.id,proposal_domain:proposal.domain,record_position:i+1}));
  }
  const grouped=new Map();
  for(const e of records){const key=JSON.stringify([e.from,e.to,e.kind,e.role||e.label||'']);if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(e);}
  for(const group of grouped.values()){
    const signature=e=>JSON.stringify([e.predicate||'',e.cardinality||'',e.notation||'',e.from_columns||[],e.to_columns||[],e.status||e.implementation_status||'']);
    const counts=new Map();for(const e of group){const key=signature(e);counts.set(key,(counts.get(key)||0)+1);}
    for(const e of group){e.conflicting_definitions=counts.size>1;e.duplicate_occurrences=counts.get(signature(e));}
  }
  modelRows=rows;relationships=records;
  const nodes=modelRows.map(m=>({...m,object_kind:m.reference_only?'reference':m.object_kind||'warehouse',full_name:m.name||m.id})),edges=[];
  // Retain every authored interpretation, including conflicting cardinality/status/evidence.
  const addEdge=e=>edges.push(e);
  relationships.forEach(e=>addEdge({...e}));
  const lineagePairs=new Set(edges.filter(e=>e.kind==='lineage').map(e=>JSON.stringify([e.from,e.to])));
  modelRows.forEach(m=>(m.depends_on||[]).forEach(id=>{const pair=JSON.stringify([id,m.id]);if(!lineagePairs.has(pair)){addEdge({from:id,to:m.id,kind:'lineage',label:'Recorded model dependency'});lineagePairs.add(pair);}}));
  const known=new Set(nodes.map(m=>m.id)),semanticIds=new Map();
  const semanticId=name=>{if(!semanticIds.has(name)){let id='omni:'+name;while(known.has(id))id='omni:'+id;semanticIds.set(name,id);known.add(id);}return semanticIds.get(name);};
  if(omni?.evidence_state==='selected'){
    const names=new Set([...Object.keys(omni.views||{}),...Object.keys(omni.query_views||{})]);
    // An authoritative registry must never turn an unresolved endpoint into an existing view.
    if(!Object.hasOwn(omni,'views')){
      (omni.dependencies||[]).forEach(e=>{names.add(e.from);names.add(e.to);});
      (omni.topics||[]).forEach(t=>{if(t.base_view)names.add(t.base_view);(t.scope?.views||[]).forEach(v=>names.add(v));});
    }
    [...names].sort().forEach(name=>nodes.push({id:semanticId(name),name,full_name:name,layer:'semantic',object_kind:'semantic',grain:Object.hasOwn(omni,'views')?'Semantic grain requires its model definition':'Legacy reference; complete semantic inventory unavailable',semantic_kind:omni.views?.[name]?.kind||omni.query_views?.[name]?.kind||'view'}));
    (omni.dependencies||[]).forEach(e=>addEdge({...e,from:semanticId(e.from),to:semanticId(e.to),kind:['query_dependency','field_dependency','inheritance'].includes(e.kind)?'lineage':'relationship',label:e.kind}));
  }
  const byId=new Map(nodes.map(m=>[m.id,m])),up=new Map(nodes.map(m=>[m.id,new Set()])),down=new Map(nodes.map(m=>[m.id,new Set()]));let unresolved=0;
  for(const e of edges){if(!byId.has(e.from)||!byId.has(e.to)){unresolved++;continue;}if(e.kind==='lineage'){up.get(e.to).add(e.from);down.get(e.from).add(e.to);}}
  nodes.sort((a,b)=>(designInventoryObject(a)?0:1)-(designInventoryObject(b)?0:1)||a.full_name.localeCompare(b.full_name)||a.id.localeCompare(b.id));
  return{nodes,edges,byId,up,down,unresolved};
}
function walkLineage(start,adjacency){const visited=new Set(start),pending=[...start];while(pending.length){for(const id of adjacency.get(pending.pop())||[])if(!visited.has(id)){visited.add(id);pending.push(id);}}return visited;}
function selectLineage(graph,options={}){
  let focused=new Set(graph.nodes.map(m=>m.id));
  if(options.focus){focused=new Set();if(graph.byId.has(options.focus)){focused.add(options.focus);if(options.direction!=='downstream')for(const id of walkLineage([options.focus],graph.up))focused.add(id);if(options.direction!=='upstream')for(const id of walkLineage([options.focus],graph.down))focused.add(id);}}
  const query=(options.search||'').trim().toLowerCase();
  const selected=new Set(graph.nodes.filter(m=>focused.has(m.id)&&(!options.allowed||options.allowed.has(m.id))&&(!options.layer||m.layer===options.layer)&&(!options.newOnly||m.disposition==='create')&&(!query||(m.full_name+' '+m.id).toLowerCase().includes(query))).map(m=>m.id));
  const visible=new Set(selected);
  if(options.context)for(const id of walkLineage(selected,graph.up))if(!options.allowed||options.allowed.has(id))visible.add(id);
  const dependencies=new Set([...visible].filter(id=>!selected.has(id)));
  return{selected,visible,dependencies,nodes:graph.nodes.filter(m=>visible.has(m.id)),edges:graph.edges.filter(e=>visible.has(e.from)&&visible.has(e.to)&&(options.joins||e.kind==='lineage')),hidden:graph.nodes.length-visible.size};
}
function graphPages(selection,maximum=36,preferred=[]){
  const groups=[],assigned=new Set(),byId=new Map(selection.nodes.map(n=>[n.id,n]));
  // Preserve the existing domain/density partitions from the packager, even after filters.
  for(const view of preferred){const rows=(view.model_ids||[]).filter(id=>byId.has(id)&&!assigned.has(id)).map(id=>byId.get(id));rows.forEach(n=>assigned.add(n.id));if(rows.length)groups.push({label:view.label||'Model view',nodes:rows});}
  const remaining=selection.nodes.filter(n=>!assigned.has(n.id)),domains=new Map();
  for(const node of remaining){const domain=node.object_kind==='semantic'?'Semantic objects':node.domain||'All layers';if(!domains.has(domain))domains.set(domain,[]);domains.get(domain).push(node);}
  for(const [label,nodes]of domains)groups.push({label,nodes});
  const pages=[];
  for(const group of groups)for(let start=0;start<group.nodes.length;start+=maximum){
    const nodes=group.nodes.slice(start,start+maximum),ids=new Set(nodes.map(n=>n.id)),edges=selection.edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
    pages.push({label:`${group.label}${group.nodes.length>maximum?' · view '+(Math.floor(start/maximum)+1):''} · ${nodes.length} objects`,model_ids:nodes.map(n=>n.id),nodes,edges:edges.slice(0,120),omitted_graph_connections:Math.max(0,edges.length-120),cross_view_connections:selection.edges.filter(e=>ids.has(e.from)!==ids.has(e.to)).length});
  }return pages;
}
function edgeEvidence(e){return [e.occurrence_id||'Recorded dependency',e.proposal_domain,e.conflicting_definitions?'Conflicting definitions':null,e.duplicate_occurrences>1?`${e.duplicate_occurrences} matching occurrences`:null,e.evidence?JSON.stringify(e.evidence):null].filter(Boolean).join(' · ');}
function filteredModelSvg(modelRows,edges,dependencyIds=new Set(),omittedEdges=0,compact=false,portable=false){
  if(!modelRows.length)return '';
  if(new Set(modelRows.map(m=>m.id)).size!==modelRows.length||modelRows.some(m=>!m.id||!['bronze','silver','gold','semantic','reference'].includes(m.layer)))throw new Error('ERD inventory contains duplicate IDs or unsupported layers.');
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  const order=['bronze','silver','gold','semantic','reference'],layers=order.filter(l=>modelRows.some(m=>m.layer===l));
  let grouped=layers.map(l=>modelRows.filter(m=>m.layer===l));
  if(compact){const splitLayers=[],splitGroups=[];for(const [i,rows]of grouped.entries()){const count=Math.min(3,Math.ceil(rows.length/5)),size=Math.ceil(rows.length/count);for(let n=0;n<count;n++){splitLayers.push(layers[i]);splitGroups.push(rows.slice(n*size,(n+1)*size));}}layers.splice(0,layers.length,...splitLayers);grouped=splitGroups;}
  const index=new Map(),positions=new Map(),incidents=new Map(modelRows.map(m=>[m.id,[]]));
  grouped.forEach((rows,i)=>rows.forEach(m=>index.set(m.id,i)));
  edges=edges.filter(e=>incidents.has(e.from)&&incidents.has(e.to));
  const lanes=layers.map(()=>[]),skips=[];
  edges.forEach((e,i)=>{const a=index.get(e.from),b=index.get(e.to);incidents.get(e.from).push(i+'from');incidents.get(e.to).push(i+'to');if(Math.abs(a-b)===1)lanes[Math.min(a,b)].push(i);else if(a===b)lanes[a].push(i);else{lanes[a].push(i);lanes[b].push(i);skips.push(i);}});
  const cw=440,wrapCard=(value,limit=44)=>{const str=String(value??'').replace(/\s+/g,' '),out=[];for(let i=0;i<str.length;i+=limit)out.push(str.slice(i,i+limit));return out.length?out:[''];};
  const content=new Map(modelRows.map(m=>{
    const title=m.full_name||m.name||m.id,kind=designObjectKind(m),qualifier=m.reference_only?'Reference only · definition missing':kind==='interface'?'External interface · implementation unresolved':m.scope_role==='shared_reference'?'Shared reference · outside domain':dependencyIds.has(m.id)?'Required dependency context':kind==='semantic'?'Semantic object':kind==='source'?'Source object · '+m.layer:dispositionLabel(m)+' · '+m.layer;
    const declared=Array.isArray(m.keys)?m.keys.filter(key=>typeof key==='string'):[],columns=(m.columns||[]).filter(c=>c.key||declared.includes(c.name)),missingKeys=declared.filter(key=>!(m.columns||[]).some(c=>c.name===key)).map(name=>({name,key:'Declared key',type:'Type unverified'})),keyRows=[...columns,...missingKeys],shown=keyRows.length?keyRows:(m.columns||[]).slice(0,4);
    const lines=[...wrapCard(title,36).map(text=>({text,name:true})),...wrapCard(qualifier).map(text=>({text,note:true})),...wrapCard(m.grain||'Grain unresolved').map(text=>({text,note:true})),...shown.flatMap(c=>wrapCard((c.key||((m.keys||[]).includes(c.name)?'Declared key':''))+' '+c.name+' · '+(c.type||'unknown')).map(text=>({text,key:true})))];
    if(!keyRows.length)lines.push({text:'Keys not supplied',note:true});
    if((m.columns||[]).length>columns.length&&keyRows.length)lines.push({text:`${m.columns.length-columns.length} other columns in inspector`,note:true});
    else if((m.columns||[]).length>shown.length)lines.push({text:`${m.columns.length-shown.length} other columns in inspector`,note:true});
    return[m.id,lines];
  }));
  const ch=Math.max(190,48+22*Math.max(...[...content.values()].map(lines=>lines.length)),60+20*Math.max(0,...[...incidents.values()].map(v=>v.length))),gutters=lanes.map(v=>Math.max(150,50+v.length*16)),xs=[34];
  for(let i=1;i<layers.length;i++)xs.push(xs[i-1]+cw+gutters[i-1]);
  const top=(compact?70:115)+skips.length*20;grouped.forEach((rows,i)=>rows.forEach((m,j)=>positions.set(m.id,{x:xs[i],y:top+j*(ch+48)})));
  const bottom=top+Math.max(1,...grouped.map(g=>g.length))*(ch+48),width=Math.max(compact?500:1080,(xs.at(-1)||34)+cw+(gutters.at(-1)||170)+34);
  const wrap=value=>{const text=String(value).replace(/\s+/g,' '),limit=Math.max(30,Math.floor((width-68)/10)),lines=[];for(let i=0;i<text.length;i+=limit)lines.push(text.slice(i,i+limit));return lines.length?lines:[''];};
  const ledger=compact?[]:edges.map((e,i)=>[...wrap(`E${i+1} · ${e.from} → ${e.to}`),...wrap([e.label||e.kind,e.predicate,relationshipColumns(e),e.cardinality,e.role,e.status||e.implementation_status||'Not validated',edgeEvidence(e)].filter(Boolean).join(' · '))]);
  const height=bottom+ledger.reduce((sum,lines)=>sum+lines.length*23+14,0)+65;
  const parts=[`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img"><title>Layered model and declared dependencies</title><desc>Full names are selectable using the model name controls. ${omittedEdges} connectors omitted from this image; see the complete relationship ledger.</desc>${portable?'':'<style>.model-name { font-weight: 700; fill: #172e43; } .model-note { fill: #546779; }</style>'}<rect width="${width}" height="${height}" fill="#f4f7fb"/><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#537080"/></marker></defs>`];
  layers.forEach((l,i)=>parts.push(`<text x="${xs[i]}" y="35" font-family="sans-serif" font-size="22" fill="#172e43">${l} · ${grouped[i].length}</text>`));
  const port=(id,i,end)=>{const p=positions.get(id),items=incidents.get(id);return p.y+28+(items.indexOf(i+end)+.5)*(ch-56)/items.length;};
  const lane=(l,i)=>xs[l]+cw+24+lanes[l].indexOf(i)*16;
  edges.forEach((e,i)=>{const a=index.get(e.from),b=index.get(e.to),p=positions.get(e.from),q=positions.get(e.to),y1=port(e.from,i,'from'),y2=port(e.to,i,'to');let points;
    if(Math.abs(a-b)===1)points=[[p.x+(a<b?cw:0),y1],[lane(Math.min(a,b),i),y1],[lane(Math.min(a,b),i),y2],[q.x+(b<a?cw:0),y2]];
    else if(a===b)points=[[p.x+cw,y1],[lane(a,i),y1],[lane(a,i),y2],[q.x+cw,y2]];
    else points=[[p.x+cw,y1],[lane(a,i),y1],[lane(a,i),70+skips.indexOf(i)*20],[lane(b,i),70+skips.indexOf(i)*20],[lane(b,i),y2],[q.x+cw,y2]];
    const status=e.status||e.implementation_status,color=e.kind==='lineage'?'#0c827e':status==='authored'?'#7658a7':status==='proposed'?'#9b641c':'#53697f',dash=e.kind==='lineage'||status==='authored'?'':` stroke-dasharray="${status==='proposed'?'7 4':'2 4'}"`;
    parts.push(`<path d="M ${points.map(p=>p.join(' ')).join(' L ')}" fill="none" stroke="${color}" stroke-width="2"${dash}${e.kind==='lineage'?' marker-end="url(#arrow)"':''}><title>${esc(e.label||e.kind)}</title></path><text x="${points[0][0]+5}" y="${y1-5}" font-family="sans-serif" font-size="13" fill="${color}">E${i+1}</text>`);
  });
  for(const m of modelRows){const p=positions.get(m.id);if(!p)continue;const title=m.full_name||m.name||m.id,reference=m.reference_only||m.scope_role==='shared_reference',external=designObjectKind(m)==='interface';
    parts.push(`<g data-model-id="${esc(m.id)}"><title>${esc(title)} · ${esc(m.grain||'Grain unresolved')}</title><rect x="${p.x}" y="${p.y}" width="${cw}" height="${ch}" rx="10" fill="${external?'#eef3ff':reference?'#fff8ed':'white'}" stroke="${external?'#62549a':reference?'#a77831':'#9aabba'}"${m.reference_only||external?' stroke-dasharray="6 4"':''}/>`);
    content.get(m.id).forEach((line,i)=>parts.push(`<text${line.name?` data-model-id="${esc(m.id)}" data-model-name="${esc(title)}" class="model-name" font-weight="700"`:''} x="${p.x+14}" y="${p.y+28+i*22}" font-family="${line.key?'monospace':'sans-serif'}" font-size="${line.name?18:15}" fill="${line.note?'#546779':'#172e43'}">${esc(line.text)}</text>`));parts.push('</g>');
  }
  let ledgerY=bottom;for(const lines of ledger){for(const line of lines){parts.push(`<text x="34" y="${ledgerY}" font-family="sans-serif" font-size="15" fill="#172e43">${esc(line)}</text>`);ledgerY+=23;}ledgerY+=14;}
  if(omittedEdges)parts.push(`<text x="34" y="${height-20}" font-size="16" fill="#546779">${omittedEdges} connectors omitted from this image. See the complete relationship ledger.</text>`);
  const rendered=parts.join('')+'</svg>';assertModelCoverage(modelRows,rendered);return rendered;
}
// Model workspace: explicit table metadata, independent from transformation-lineage filters.
function dispositionLabel(model){return({create:'New',reuse:'Reused',extend:'Extended',replace:'Replaced'})[model.disposition]||'Unspecified';}
function columnRole(model,column){return column.key||((model.keys||[]).includes(column.name)?'Declared key':'—');}
function selectErd(graph,options={}){
  const warehouse=graph.nodes.filter(designInventoryObject);
  const domainNodes=warehouse.filter(m=>!options.domain||m.domain===options.domain||m.proposal_domains?.includes(options.domain)),domainIds=new Set(domainNodes.map(m=>m.id));
  const query=(options.search||'').trim().toLowerCase();
  const direct=new Set(domainNodes.filter(m=>(!options.allowed||options.allowed.has(m.id))&&(!options.layer||m.layer===options.layer)&&(!options.disposition||(options.disposition==='undetermined'?dispositionLabel(m)==='Unspecified':m.disposition===options.disposition))&&(!query||(m.full_name+' '+m.id).toLowerCase().includes(query))).map(m=>m.id));
  const applicable=graph.edges.filter(e=>!options.domain||e.record_origin!=='domain_proposal'||e.proposal_domain===options.domain);
  const visible=new Set(direct),joins=applicable.filter(e=>e.kind==='relationship'||options.dependencies&&e.kind==='lineage');
  // Only domain scope adds neighbors. Search/layer/asset filters remain explicit boundaries.
  const permitted=id=>{const m=graph.byId.get(id);return m&&m.object_kind!=='semantic'&&(!options.allowed||m.object_kind==='reference'||options.allowed.has(id));};
  for(const e of joins)if(direct.has(e.from)||direct.has(e.to)){
    for(const id of [e.from,e.to])if(permitted(id)&&(!domainIds.has(id)||direct.has(id))&&(options.domain||graph.byId.get(id).object_kind==='reference'))visible.add(id);
  }
  // Domain-assigned proposal records explicitly scope disconnected shared/reference components.
  // Under an asset boundary, missing definitions need an allowed known endpoint anchor.
  if(!query&&!options.layer&&!options.disposition){
    const scoped=joins.filter(e=>e.record_origin==='domain_proposal');
    const scopedIds=new Set(scoped.flatMap(e=>[e.from,e.to]));
    for(const id of scopedIds)if(permitted(id)&&designInventoryObject(graph.byId.get(id))&&(!domainIds.has(id)||direct.has(id)))visible.add(id);
    if(!options.allowed){for(const id of scopedIds)if(permitted(id))visible.add(id);}
    else{
      const adjacency=new Map();for(const e of scoped){if(!permitted(e.from)||!permitted(e.to))continue;for(const [a,b]of [[e.from,e.to],[e.to,e.from]]){if(!adjacency.has(a))adjacency.set(a,new Set());adjacency.get(a).add(b);}}
      const pending=[...visible],visited=new Set(pending);for(let i=0;i<pending.length;i++)for(const id of adjacency.get(pending[i])||[])if(!visited.has(id)&&graph.byId.get(id).object_kind==='reference'){visited.add(id);visible.add(id);pending.push(id);}
    }
  }
  const nodes=graph.nodes.filter(m=>visible.has(m.id)).map(m=>({...m,scope_role:m.object_kind==='reference'?'missing_reference':direct.has(m.id)?'domain':'shared_reference'}));
  const edges=joins.filter(e=>visible.has(e.from)&&visible.has(e.to));
  const inScope=e=>domainIds.has(e.from)||domainIds.has(e.to)||e.record_origin==='domain_proposal';
  const hiddenConnections=joins.filter(e=>inScope(e)&&(!visible.has(e.from)||!visible.has(e.to))).length;
  const referenceScope=new Set(joins.filter(inScope).flatMap(e=>[e.from,e.to]).filter(id=>!domainIds.has(id)&&graph.byId.has(id)));
  const hiddenReferences=[...referenceScope].filter(id=>!visible.has(id)).length;
  // Overlay controls drawing only. Retain eligible dependency evidence separately;
  // never use its endpoints to expand the default join diagram.
  const candidates=applicable.filter(e=>permitted(e.from)&&permitted(e.to)&&(direct.has(e.from)||direct.has(e.to)||visible.has(e.from)&&visible.has(e.to)||!query&&!options.layer&&!options.disposition&&e.record_origin==='domain_proposal'));
  const ledgerIds=new Set();
  if(!options.allowed)for(const e of candidates){ledgerIds.add(e.from);ledgerIds.add(e.to);}
  else{
    const adjacency=new Map();for(const e of candidates)for(const [a,b]of [[e.from,e.to],[e.to,e.from]]){if(!adjacency.has(a))adjacency.set(a,new Set());adjacency.get(a).add(b);if(designInventoryObject(graph.byId.get(a)))ledgerIds.add(a);}
    const pending=[...ledgerIds];for(let i=0;i<pending.length;i++)for(const id of adjacency.get(pending[i])||[])if(!ledgerIds.has(id)&&graph.byId.get(id).object_kind==='reference'){ledgerIds.add(id);pending.push(id);}
  }
  return{nodes,edges,visible,selected:direct,dependencies:new Set(),domain:options.domain||'',focus:options.focus||'',
    domain_total:domainNodes.length,domain_count:direct.size,shared_count:nodes.filter(m=>m.scope_role==='shared_reference').length,
    missing_count:nodes.filter(m=>m.reference_only).length,hidden:domainNodes.length-direct.size,hidden_connections:hiddenConnections,hidden_references:hiddenReferences,
    dependencies_displayed:Boolean(options.dependencies),ledger:candidates.filter(e=>ledgerIds.has(e.from)&&ledgerIds.has(e.to))};
}
function erdPages(selection,maximum=36){
  if(!Number.isSafeInteger(maximum)||maximum<1)throw new Error('ERD page size must be a positive integer.');
  // Breadth-first order keeps connected tables together without pruning isolates or cycles.
  const byId=new Map(selection.nodes.map(n=>[n.id,n])),adj=new Map(selection.nodes.map(n=>[n.id,new Set()]));
  for(const e of selection.edges){adj.get(e.from)?.add(e.to);adj.get(e.to)?.add(e.from);}
  const seen=new Set(),ordered=[];
  const seeds=[...selection.nodes].sort((a,b)=>String(a.domain||'').localeCompare(String(b.domain||''))||a.id.localeCompare(b.id));
  for(const seed of seeds){if(seen.has(seed.id))continue;seen.add(seed.id);const queue=[seed.id];for(let i=0;i<queue.length;i++){const id=queue[i];ordered.push(byId.get(id));for(const next of adj.get(id)||[])if(!seen.has(next)){seen.add(next);queue.push(next);}}}
  const pages=[];
  for(let start=0;start<ordered.length;start+=maximum){const nodes=ordered.slice(start,start+maximum),ids=new Set(nodes.map(m=>m.id)),edges=selection.edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
    pages.push({label:`${selection.domain||'Entire model'} · tables ${start+1}–${start+nodes.length} of ${ordered.length}`,model_ids:nodes.map(m=>m.id),nodes,edges:edges.slice(0,120),ledger:(selection.ledger||selection.edges).filter(e=>ids.has(e.from)||ids.has(e.to)),omitted_graph_connections:Math.max(0,edges.length-120),cross_view_connections:selection.edges.filter(e=>ids.has(e.from)!==ids.has(e.to)).length,compact:true});
  }return pages;
}
function assertModelCoverage(modelRows,svg){
  const expected=modelRows.map(m=>m.id),ids=[...svg.matchAll(/<g\b[^>]*data-model-id="([^"]*)"/g)].map(m=>m[1]);
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  if(new Set(expected).size!==expected.length||ids.length!==expected.length||new Set(ids).size!==ids.length||expected.some(id=>!ids.includes(esc(id))))throw new Error('ERD coverage failed: table blocks do not match the selected inventory. Ask the agent to regenerate the diagram.');
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
const migrationReview=data.audience!=='audit'&&(data.page_mode==='status'||['documentation','diagrams','dictionary'].some(key=>data.selected_categories?.includes(key)))?data.migration_review:null;
const domainJourney=data.audience!=='audit'&&(data.page_mode==='status'||['documentation','diagrams','dictionary'].some(key=>data.selected_categories?.includes(key)))?data.domain_journey:null;
const migrationPlanning=data.audience!=='audit'&&(data.page_mode==='status'||['documentation','dictionary'].every(c=>data.selected_categories?.includes(c)))?data.migration_planning:null;
const frontendContinuation=data.audience!=='audit'&&(data.page_mode==='status'||data.selected_categories?.includes('documentation'))?data.workflow?.frontend_continuation:null;
const reviewSections=[...(frontendContinuation?['dashboard-migration']:[]),'omni-topic-trees','input-files','overview','readiness','changes','coverage-reuse','review-feedback','model','validation','delivery','deployment',...(review.metadata?['metadata']:[]),...(review.omni?['omni']:[]),...(migrationReview?['migration-review']:[]),...(domainJourney?['domain-journey']:[]),...(migrationPlanning?['migration-plan']:[])];
const sectionRoutes={architecture:'model',lineage:'model','table-dictionary':'model','implementation-code':'delivery','replacement-map':'delivery'};
let firstNavigation=true,modelWorkspaceReady=false,pendingInspectorModel=null;
function navigate(){
  if(!firstNavigation)closeInspector();
  const defaultSection=domainJourney?.needs_selection?'domain-journey':(review.models||[]).length?'model':'overview';
  const requested=location.hash.slice(1)||defaultSection,parent=sectionRoutes[requested]||requested,valid=reviewSections.includes(parent)?parent:defaultSection;
  document.querySelectorAll('[data-section]').forEach(s=>s.hidden=s.id!==valid);
  document.body.classList.toggle('model-route',valid==='model');
  el('lineage').hidden=requested!=='lineage';el('table-dictionary').hidden=requested!=='table-dictionary';el('architecture').hidden=['lineage','table-dictionary'].includes(requested);
  document.querySelectorAll('[data-nav]').forEach(n=>{const active=n.dataset.nav===requested||n.dataset.nav===valid;n.classList.toggle('active',active);if(active)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});
  if(!['overview','model','delivery'].includes(valid))el('supporting-navigation').open=true;
  const target=sectionRoutes[requested]?el(requested):el(valid);
  if(!firstNavigation||location.hash){target?.focus?.({preventScroll:true});target?.scrollIntoView?.({block:'start'});}
  firstNavigation=false;checkLayout();
  if(typeof requestAnimationFrame==='function')requestAnimationFrame(()=>{if(modelWorkspaceReady&&diagramFitMode)fitDiagram();});
  if(modelWorkspaceReady&&pendingInspectorModel){const modelId=pendingInspectorModel;pendingInspectorModel=null;if(requested==='architecture')revealModel(modelId);}
}
addEventListener('dma-topic-table',event=>{pendingInspectorModel=event.detail.id;if(location.hash==='#architecture')navigate();else location.hash='#architecture';});
addEventListener('hashchange',navigate);navigate();
// Repeated clicks on the same fragment still reveal its parent and focus the anchor.
document.querySelectorAll('[data-nav]').forEach(link=>{link.onclick=()=>{if(location.hash==='#'+link.dataset.nav)navigate();};});
el('implementation-nav').hidden=false;el('files-nav').hidden=true;
el('domain-journey-nav').hidden=!domainJourney;
el('migration-plan-nav').hidden=!migrationPlanning;
el('frontend-nav').hidden=!frontendContinuation;
if(frontendContinuation){
  el('frontend-qualification').textContent=frontendContinuation.qualification;
  const rows=frontendContinuation.items||[], selector=el('frontend-domain');
  [...new Set(rows.map(r=>r.domain_id).filter(Boolean))].sort().forEach(id=>{const option=make('option',id);option.value=id;selector.append(option);});
  const renderFrontend=()=>{
    const scoped=rows.filter(r=>!selector.value||r.domain_id===selector.value);
    table('frontend-table',[['Domain',r=>r.domain_id||'Selected scope'],['Status',r=>pretty(r.status)],['Dashboards requested',r=>r.dashboard_ids.join(', ')||'Not selected'],['Topics selected',r=>r.topic_names.join(', ')||'Not selected'],['Next action',r=>r.next_action]],scoped);
    el('frontend-prompt').value='Use the optional Omni Artifact Accelerator continuation for '+scoped.map(r=>r.id).join(', ')+'. Check compatibility, reuse the saved scope and decisions, and resume its linked frontend project. If not started, show the available continuation choices. Preserve provisional work and unresolved mappings; this request does not authorize deployment or publication.';
    const target=clear('frontend-files');
    const ids=new Set(scoped.flatMap(r=>r.artifact_ids||[]));
    (data.files||[]).filter(f=>ids.has(f.id)||f.id==='generated:frontend-continuation').forEach(f=>{const b=make('button',f.description||f.path,'secondary');b.type='button';b.onclick=()=>openArtifact(f.id);target.append(b);});
  };
  selector.onchange=renderFrontend;renderFrontend();
  el('frontend-copy').onclick=()=>copyText(el('frontend-prompt').value,el('frontend-prompt'),'Continuation request copied.');
}

if(domainJourney){
  const domains=domainJourney.domains||[],active=domains.find(row=>row.id===domainJourney.active_domain_id);
  el('domain-journey-qualification').textContent=domainJourney.qualification||'Recorded domain progress only; approval and execution authority remain separate.';
  card(el('domain-journey-summary'),'Recorded active domain',active?.name||active?.id||'None in this view',active?pretty(active.status):'Ask the agent to apply a domain selection.');
  card(el('domain-journey-summary'),'Included domains',String(domains.length),'This inventory follows the included model scope.');
  card(el('domain-journey-summary'),'Recorded completed domains',String(domains.filter(row=>row.status==='completed').length),'Completion applies to the requested delivery scope, not live validation.');
  const attention=[];
  if(domainJourney.needs_selection)attention.push('Choose a domain and return the selection request to the agent.');
  if(domains.some(row=>row.status==='stale'))attention.push('Some domain records are stale; ask the agent to refresh their evidence before continuing.');
  if(active?.scope_preview?.batching_recommended)attention.push(`This domain contains ${active.scope_preview.models} models and ${active.scope_preview.columns} columns across ${active.scope_preview.source_files} source files. Choose a smaller batch with the agent before expanding the design.`);
  const batch=domainJourney.active_batch;
  if(batch)attention.push(`Batch: ${batch.name} · ${pretty(batch.status)} · ${batch.entity_ids.length} selected models and ${batch.dependency_ids.length} dependencies. ${batch.next_action}`);
  el('domain-journey-attention').hidden=!attention.length;el('domain-journey-attention').textContent=attention.join(' ');
  el('domain-journey-next').textContent=domainJourney.next_action||'Review the included domain queue with the agent.';
  for(const row of domains){const option=make('option',`${row.name||row.id} · ${pretty(row.status)}`);option.value=row.id;el('domain-choice').append(option);}
  const identifiers=values=>(values||[]).join(', ')||'Not assigned';
  table('domain-journey-domains',[['Domain',row=>{const cell=make('div');cell.append(make('strong',row.name||row.id),make('small',row.id),make('p',row.description||'No description supplied.'));return cell;}],['Journey status',row=>pretty(row.status)],['Design / approval',row=>pretty(row.design_status||'not_recorded')],['Code / semantic progress',row=>`${pretty(row.implementation_status||'not_recorded')} · ${pretty(row.semantic_status||'not_recorded')}`],['Scope / shared dependencies',row=>`${identifiers(row.model_ids)} · ${text(row.asset_count)} source assets. Shared dependencies: ${identifiers(row.shared_dependency_ids)}.`],['Completion / next action',row=>`${pretty(row.completion_kind||'not_completed')} · ${row.next_action||'Review with the agent.'}`]],domains);
}
el('domain-choice').onchange=()=>{
  const row=domainJourney?.domains?.find(item=>item.id===el('domain-choice').value);
  const bound=typeof domainJourney?.candidates_sha256==='string'&&/^[a-f0-9]{64}$/.test(domainJourney.candidates_sha256);
  el('domain-request-copy').disabled=!row||!bound;
  const request=row&&bound?{schema_version:1,domain_id:row.id,request_reference:`Offline portal selection for engagement ${eng.engagement_id}, revision ${eng.revision}.`,candidates_sha256:domainJourney.candidates_sha256}:null;
  el('domain-request').value=request?`Please select ${row.name||row.id} for engagement ${eng.engagement_id}. Check this request against the current inventory and apply my choice using guided_workflow.py select-domain with this document:\n\n${JSON.stringify(request,null,2)}\n\nThis is a selection request only. Preserve the recorded approvals, code and validation evidence; no design approval, execution or deployment is authorized.`:'';
  el('domain-request-note').textContent=!row?'':bound?'Request prepared. The recorded active domain has not changed.':'This snapshot has no current domain inventory binding. Ask the agent to refresh the journey before selecting a domain.';
};
el('domain-request-copy').disabled=true;
el('domain-request-copy').onclick=()=>copyText(el('domain-request').value,el('domain-request'),'Domain selection request copied. Return it to the agent to check and apply.');
el('migration-review-nav').hidden=!migrationReview;
if(migrationReview){
  const rules=migrationReview.business_rules,portfolio=migrationReview.portfolio,source=migrationReview.source_discovery,parity=migrationReview.parity;
  const names=values=>(values||[]).join(', ')||'None supplied';
  const status=value=>value?`${pretty(value.status||'unassessed')}${value.qualification?' · '+value.qualification:''}`:'Not supplied in this review scope.';
  const counts=(id,values)=>table(id,[['Recorded count',row=>pretty(row[0])],['Value',row=>row[1]]],Object.entries(values||{}));
  el('migration-qualification').textContent=migrationReview.qualification||'Supplied migration evidence. Native verification and business acceptance remain separate.';
  const attention=[];
  if(rules?.conflicts?.length)attention.push(`${rules.conflicts.length} business rule conflicts require human review.`);
  if((rules?.rows||[]).some(row=>row.status==='proposed'))attention.push('Proposed business rules still need a human decision.');
  if(portfolio?.status==='stale'||portfolio?.coverage?.some(row=>row.freshness==='stale'))attention.push('Shared model proposals are stale; refresh their source and rule bindings.');
  if(source?.freshness==='stale'||source?.status==='stale')attention.push('Source discovery evidence is stale.');
  if(parity?.stale||parity?.status==='stale')attention.push('Parity evidence is stale; rerun the bound comparisons.');
  if(parity&&['fail','failed','blocked'].includes(parity.status))attention.push('Parity findings require review before proceeding.');
  el('migration-attention').hidden=!attention.length;el('migration-attention').textContent=attention.join(' ');
  el('migration-rules-status').textContent=status(rules);
  table('migration-rules',[['Rule',row=>{const cell=make('div');cell.append(make('strong',row.name||row.id),make('small',row.id));return cell;}],['Business statement',row=>row.statement],['Recorded decision',row=>pretty(row.status)],['Models',row=>names(row.model_ids)]],rules?.rows||[]);
  table('migration-conflicts',[['Conflicting model',row=>row.model_id],['Definition',row=>row.key],['Rule IDs',row=>names(row.rule_ids)]],rules?.conflicts||[]);
  el('migration-portfolio-status').textContent=status(portfolio);
  table('migration-candidates',[['Candidate / proposal',row=>{const cell=make('div');cell.append(make('strong',row.id),make('p',pretty(row.disposition)));return cell;}],['Reason and validation',row=>`${row.reason||'No reason supplied.'} Required checks: ${names(row.required_checks)}.`],['Models / source assets',row=>`${names(row.model_ids)} · ${names(row.asset_ids)}`],['Grain / dimensions / measures',row=>`${names(row.grain)} · ${names(row.dimensions)} · ${names(row.measure_ids)}`]],portfolio?.candidates||[]);
  table('migration-portfolio-coverage',[['Source asset',row=>row.name||row.asset_id],['Proposal',row=>pretty(row.disposition)],['Candidate / models',row=>`${row.candidate_id||'No candidate'} · ${names(row.model_ids)}`],['Freshness / reason',row=>`${pretty(row.freshness||'unassessed')} · ${row.reason||'No reason supplied.'}`]],portfolio?.coverage||[]);
  el('migration-source-status').textContent=status(source)+(source?` · Freshness: ${pretty(source.freshness||'unassessed')} · Known file denominator: ${text(source.coverage?.known_file_denominator)} · Repository file denominator: ${text(source.coverage?.repository_file_denominator)} · Supplied repository enumeration complete: ${source.coverage?.enumeration_complete===true?'Yes':source.coverage?.enumeration_complete===false?'No':'Not supplied'} · Source export completeness: ${pretty(source.coverage?.export_completeness||'not_established')}.`:'');
  counts('migration-source-counts',source?.coverage?.counts);
  table('migration-source-gaps',[['Source coverage gap',row=>pretty(row.code)]],source?.gaps||[]);
  el('migration-parity-status').textContent=status(parity)+(parity?.assurance?' · '+text(parity.assurance):'');
  counts('migration-parity-counts',parity?.counts);
  table('migration-parity-crosswalk',[['Dashboard / source',row=>`${row.dashboard_label||'Unassigned'} · ${row.source_label||'Unassigned'}`],['Models / topics',row=>`${names(row.model_ids)} · ${names(row.topic_ids)}`],['Comparison scope',row=>row.required===true?'Selected comparison':row.required===false?'Retained outside selected scope':'Scope not recorded'],['Reported status / cases',row=>`${pretty(row.status)} · ${text(row.case_count)}`],['Issues',row=>(row.issues||[]).map(issue=>`${pretty(issue.code)}: ${pretty(issue.status)}`).join('; ')||'No issues supplied']],parity?.crosswalk||[]);
  // Decode only our generated Markdown escapes into inert, printable text.
  el('migration-print-summary').textContent=(migrationReview.summary_markdown||'Complete summary not supplied. Ask the agent to refresh this review.').replace(/^#{1,2} /gm,'').replace(/\\([\\`*_\[\]()!|])/g,'$1').replaceAll('<br>','\n').replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');
}
el('migration-print').onclick=()=>{if(typeof globalThis.print!=='function')return notice('Use your browser Print command, or ask the agent for the migration review Markdown deliverable.');document.body.classList.toggle('migration-print',true);try{globalThis.print();}catch(error){document.body.classList.toggle('migration-print',false);notice('Printing is unavailable here. Use the migration review Markdown deliverable.');}};
addEventListener('afterprint',()=>document.body.classList.toggle('migration-print',false));
el('page-title').textContent=review.title||'Your modeling engagement';
el('subtitle').textContent=review.description||'A guided path from the current repository to a model you can inspect, test and adopt.';
if(data.checkpoint){el('checkpoint-note').hidden=false;el('checkpoint-note').textContent='Checkpoint — work is incomplete. Missing selected categories: '+(data.checkpoint.missing_categories.join(', ')||'none; remaining tasks and validation still require review')+'. Resume the same engagement to continue.';}
const runControl=eng.run_control;
if(el('task-progress')){
  const progress=runControl?.progress;
  el('task-progress-note').textContent=progress?`${progress.qualification} Snapshot: ${progress.snapshot_at}`:'Detailed task tracking was not recorded for this older package.';
  table('task-progress',[
    ['Domain / task',row=>`${row.domain_id} · ${row.task_id}`],
    ['Stage / specialist',row=>`${pretty(row.stage)} · ${pretty(row.role)}`],
    ['Progress',row=>`${pretty(row.status)} · ${pretty(row.authoring_mode)}`],
    ['Files / questions',row=>`${row.output_count} recorded · ${row.unknown_count===null?'untracked':row.unknown_count} open`],
    ['Review',row=>pretty(row.review_status)],['Next action',row=>row.next_action]
  ],progress?.tasks||[]);
}
el('run-progress').textContent=runControl?`${pretty(runControl.status)} coordination · ${runControl.attempts} attempts · ${runControl.counts.active} active · ${runControl.counts.interrupted} interrupted · ${runControl.reused} reused. Runtime ${runControl.runtime_sha256?.slice(0,12)||'not recorded'}. These counts do not establish host execution or cost.`:'Execution accounting was not recorded for this older package.';
if(runControl?.dispatch_counts){const c=runControl.dispatch_counts;el('run-progress').textContent+=` Reported execution: ${c.specialist_reported} specialists, ${c.inline_reported} inline passes, ${c.unobserved} unobserved. Host reports do not prove isolation or model identity.`;}
if(runControl?.runtime_identity){const r=runControl.runtime_identity;el('run-progress').textContent+=` Installed revision: ${r.installed_revision?.slice(0,12)||'unavailable (portable install)'}. Freshness: ${pretty(r.freshness?.status||'unknown')}. ${(r.advisories||[]).join(' ')}`;}
Object.values(eng.target||{}).filter(v=>v&&v!=='retain_existing').forEach(v=>el('target-tags').append(make('span',pretty(v),'pill')));
const fingerprint=typeof eng.source_fingerprint==='object'?eng.source_fingerprint?.value:eng.source_fingerprint;
el('scope-note').textContent=`${pretty(eng.engagement_type)} · ${text(eng.domain)} · Source ${fingerprint?fingerprint.slice(0,12):'not inventoried'} · This view is a recorded snapshot; refresh through the agent after changes.`;
el('stage').textContent=pretty(eng.status);el('revision').textContent=`Engagement revision ${eng.revision}. No deployment is asserted.`;
el('footer-id').textContent=eng.engagement_id;
const assurance=portableAssurance(eng),scopeNames={model_only:'Data model only',model_semantic:'Data model + Omni semantic layer',full_dashboard:'Full dashboard migration'};
el('candidate-status').textContent='Candidate · acceptance not established';
el('assurance-scope').textContent=scopeNames[assurance.migration_scope]||'Migration scope not selected';
el('assurance-boundary').textContent=assurance.qualification;
el('assurance-overview').textContent=`${scopeNames[assurance.migration_scope]||'Scope unresolved'} · ${assurance.checks.filter(c=>c.required).length} evidence lanes require verification. Prepared files do not establish completed migration.`;
const assuranceColumns=[['Evidence lane',c=>c.label],['Status',c=>pretty(c.status)],['Meaning / next action',c=>c.reason+' '+c.next_action]];
table('assurance-checks',assuranceColumns,assurance.checks.filter(c=>c.required),20);
table('assurance-excluded',assuranceColumns,assurance.checks.filter(c=>!c.required),20);
el('outside-scope').hidden=!assurance.checks.some(c=>!c.required);
el('validation-next').textContent=assurance.migration_scope?'Start with failed or stale evidence. Expand the required checks for the full verification plan.':'Next: confirm the migration scope with the agent. Until then, readiness is unresolved; the full evidence inventory is retained below.';
const actions=eng.next_actions||[],first=actions[0];
el('next-title').textContent=first?.title||({discovery:'Complete the next discovery step',generation:'Review the model prerequisites',readiness:'Resolve the readiness findings',catalogue:'Ground the model in your raw data'}[first?.scope])||'Review readiness and outstanding decisions';
const nextSection=reviewSections.includes(first?.section)?first.section:eng.delivery?.status==='prepared'?'delivery':'readiness';
el('next-link').href='#'+nextSection;el('next-link').textContent=nextSection==='delivery'?'Inspect handoff →':'Review next step →';
if(['prepared','provisional_prepared'].includes(eng.delivery?.status)){el('handoff-summary').hidden=false;el('handoff-summary').textContent=`${eng.delivery.status==='provisional_prepared'?'Provisional files prepared. ':''}${files.length?files.length+' registered files are included in this export.':'A prepared handoff is recorded; this status page has no embedded files.'} ${eng.delivery.qualification||'File integrity only; native runtime, business approval and deployment remain separate.'}`;}
el('next-detail').textContent=typeof first==='object'?(first.action||first.detail||first.description||first.reason||''): first||'The agent retains your decisions and evidence. Continue with the outstanding item before claiming the next stage.';
function effortPackageDetails(row){const box=make('div');box.append(make('p',row.rationale||row.summary||'No rationale supplied.'));const detail=make('details');detail.append(make('summary','Factors and prerequisites'));for(const item of row.dimensions||[])detail.append(make('p',`${pretty(item.name)} · ${pretty(item.level)}: ${item.rationale||'No rationale supplied.'}`));for(const key of ['assumptions','prerequisites','dependencies','included_work','excluded_work'])if(row[key]?.length)detail.append(make('p',`${pretty(key)}: ${row[key].join('; ')}`));box.append(detail);return box;}
const workflow=data.workflow||null;
const models=review.models||[],changes=review.changes||[],cases=review.validation||[];
const decisions=[...new Map([...(review.decisions||[]),...(workflow?.decisions||[])].map(d=>[d.id,d])).values()];
const reviewAssurance=workflow?.review_assurance||null;
const evidenceCoverage=reviewAssurance?.coverage,evidenceReuse=reviewAssurance?.reuse,evidenceReconciliation=reviewAssurance?.reconciliation;
const evidenceStatus=value=>typeof value==='string'&&value.trim()?pretty(value):'Unassessed';
const evidenceNames=value=>reviewEvidenceList(value).join(', ')||'Unknown / unassigned';
const evidenceCounts=(counts,keys)=>keys.map(key=>`${pretty(key)}: ${reviewEvidenceCount(counts?.[key])}`).join(' · ');
const evidenceCountRatio=(part,total)=>Number.isSafeInteger(part)&&part>=0&&Number.isSafeInteger(total)&&total>=0?`${part} of ${total}`:'Unassessed';
const mappingSummary=evidenceCountRatio(evidenceCoverage?.counts?.mapped,evidenceCoverage?.counts?.total);
const reuseSummary=evidenceCountRatio(evidenceReuse?.counts?.unassigned,evidenceReuse?.counts?.total);
const reconciliationFindings=Array.isArray(evidenceReconciliation?.findings)?evidenceReconciliation.findings:null;
const reconciliationUnknowns=Array.isArray(evidenceReconciliation?.unknowns)?evidenceReconciliation.unknowns:null;
card(el('review-evidence-cards'),'Mapped source occurrences',mappingSummary,`${evidenceStatus(evidenceCoverage?.status)} · ${evidenceCounts(evidenceCoverage?.counts,['unresolved','unsupported','excluded_by_review','stale'])}. Authored associations, not validated behavior.`);
card(el('review-evidence-cards'),'Existing models unassigned',reuseSummary,`${evidenceStatus(evidenceReuse?.status)} · Ownership and disposition need explicit evidence.`);
card(el('review-evidence-cards'),'Reconciliation',evidenceStatus(evidenceReconciliation?.status),`${reviewEvidenceCount(reconciliationFindings?.length)} findings · ${reviewEvidenceCount(reconciliationUnknowns?.length)} unknowns. No native compatibility is established here.`);
const supplied=evidenceCoverage?.supplied_files;
const suppliedStatuses=supplied?.statuses&&typeof supplied.statuses==='object'&&!Array.isArray(supplied.statuses)?Object.entries(supplied.statuses).map(([key,value])=>`${pretty(key)}: ${reviewEvidenceCount(value)}`).join(' · ')||'Unassessed':'Unassessed';
el('review-evidence-sources').textContent=`Supplied files — expected: ${reviewEvidenceCount(supplied?.expected)} · observed: ${reviewEvidenceCount(supplied?.observed)} · missing: ${reviewEvidenceCount(supplied?.missing)}. Statuses: ${suppliedStatuses}. Full export completeness is not established; native parity is not validated.`;
const dispositions=evidenceReuse?.counts?.by_disposition;
const dispositionSummary=dispositions&&typeof dispositions==='object'&&!Array.isArray(dispositions)?Object.entries(dispositions).map(([key,value])=>`${pretty(key)}: ${reviewEvidenceCount(value)}`).join(' · ')||'Unassessed':'Unassessed';
el('review-evidence-reuse-scope').textContent=`Canonical existing inventory: ${reviewEvidenceCount(evidenceReuse?.canonical_total)} · stale reuse records: ${reviewEvidenceCount(evidenceReuse?.stale)}. Dispositions — ${dispositionSummary}. Evidence recorded is not validated compatibility.`;
const initialEvidenceSelection=reviewEvidenceSelection(reviewAssurance);
for(const key of ['asset','domain','model']){
  const control=el('review-evidence-'+key),values=new Set();
  for(const [kind,rows]of [['coverage',initialEvidenceSelection.coverageRows],['reuse',initialEvidenceSelection.reuseRows]])for(const row of rows)for(const value of reviewEvidenceDimensions(row,kind,initialEvidenceSelection.coverageRows)[key])values.add(value);
  const unknown=make('option','Unknown / unassigned');unknown.value='__unknown__';control.append(unknown);
  for(const value of [...values].sort()){const option=make('option',key==='model'?(models.find(m=>m.id===value)?.name||value):value);option.value=value;control.append(option);}
}
function evidenceFollowup(row){const link=make('a',row.status==='unassigned'||row.owner_domain===null?'Review assignment':'Review decision');link.href='#changes';return link;}
function renderReviewEvidence(){
  const filters=Object.fromEntries(['asset','domain','model','search'].map(key=>[key,el('review-evidence-'+key).value]));
  const selected=reviewEvidenceSelection(reviewAssurance,filters);
  const detailCount=(record,visible,included)=>Array.isArray(record?.rows)?`${visible.length} of ${included.length}`:'Unassessed';
  el('review-evidence-filter-note').textContent=`Included source details: ${detailCount(evidenceCoverage,selected.coverage,selected.coverageRows)} · included reuse details: ${detailCount(evidenceReuse,selected.reuse,selected.reuseRows)}. Global counts stay unchanged. Asset filtering for reuse follows explicit shared model IDs; absent associations remain unknown.`;
  const render=(id,columns,rows,assessed)=>{if(!assessed)empty(id,'Unassessed — no detail evidence was supplied.');else table(id,columns,rows);};
  render('review-evidence-groups',[['Asset',r=>r.asset||'Unknown'],['Domain',r=>r.domain||'Unknown / unassigned'],['Recorded counts',r=>evidenceCounts(r,['total','mapped','unresolved','unsupported','excluded_by_review','stale'])],['Models',r=>evidenceNames(r.model_ids)]],selected.groups,Array.isArray(evidenceCoverage?.groups));
  render('review-evidence-coverage',[['Occurrence',r=>r.name||r.id||'Unknown'],['Asset / domain',r=>`${r.asset||'Unknown'} · ${r.domain||'Unknown / unassigned'}`],['Models',r=>evidenceNames(r.model_ids)],['Status',r=>evidenceStatus(r.status)],['Rationale',r=>r.rationale||'Not supplied'],['Next step',evidenceFollowup]],selected.coverage,Array.isArray(evidenceCoverage?.rows));
  render('review-evidence-reuse',[['Existing model',r=>`${r.name||'Unknown'} · ${r.existing_id||'Unknown ID'}`],['Owner domain',r=>r.owner_domain||'Unknown / unassigned'],['Disposition',r=>evidenceStatus(r.disposition)],['Models / requirements',r=>`${evidenceNames(r.model_ids)} / ${evidenceNames(r.requirement_ids)}`],['Compatibility / freshness',r=>`${r.compatibility==='evidence_recorded'?'Evidence recorded — not validated':'Unknown'} · ${evidenceStatus(r.freshness)}`],['Rationale',r=>r.rationale||'Not supplied'],['Next step',evidenceFollowup]],selected.reuse,Array.isArray(evidenceReuse?.rows));
  for(const [kind,record]of [['coverage',evidenceCoverage],['reuse',evidenceReuse]])el('review-evidence-'+kind+'-limit').textContent=`Additional detail rows omitted from this page: ${reviewEvidenceCount(record?.omitted_detail_rows)}. Filters affect included details only; request the retained evidence to inspect omitted rows.`;
  const reconciliationRows=[...(reconciliationFindings||[]).map(row=>({...row,kind:'Finding'})),...(reconciliationUnknowns||[]).map(row=>({...row,kind:'Unknown'}))];
  render('review-evidence-reconciliation',[['Type',r=>r.kind],['Issue',r=>r.code||'Unknown'],['Details',r=>r.message||'Not supplied'],['Models',r=>evidenceNames(r.model_ids)],['Next step',()=>{const link=make('a','Prepare feedback');link.href='#review-feedback';return link;}]],reconciliationRows,reconciliationFindings!==null||reconciliationUnknowns!==null);
}
const orphan=evidenceCoverage?.orphan_requirements,uninventoried=evidenceReuse?.uninventoried_existing_ids;
el('review-evidence-open-items').textContent=`Requirements without recorded mappings: ${Array.isArray(orphan)?(orphan.length?evidenceNames(orphan):'None recorded'):'Unassessed'}. Existing IDs missing from the reuse inventory: ${Array.isArray(uninventoried)?(uninventoried.length?evidenceNames(uninventoried):'None recorded'):'Unassessed'}. Review these through Changes & decisions or Prepare review feedback.`;
el('review-evidence-summary').value=[`Coverage & reuse — ${eng.engagement_id||'engagement not supplied'}`,`Mapped source occurrences: ${mappingSummary}. Status: ${evidenceStatus(evidenceCoverage?.status)}.`,evidenceCounts(evidenceCoverage?.counts,['total','mapped','unresolved','unsupported','excluded_by_review','stale']),el('review-evidence-sources').textContent,`Existing models unassigned: ${reuseSummary}. Status: ${evidenceStatus(evidenceReuse?.status)}.`,el('review-evidence-reuse-scope').textContent,`Reconciliation: ${evidenceStatus(evidenceReconciliation?.status)}; ${reviewEvidenceCount(reconciliationFindings?.length)} findings; ${reviewEvidenceCount(reconciliationUnknowns?.length)} unknowns.`,el('review-evidence-open-items').textContent,'Delivered files and mapped associations do not establish validated behavior, approval or deployment readiness. See Validation for its separate evidence.'].join('\n');
el('review-evidence-copy').onclick=()=>copyText(el('review-evidence-summary').value,el('review-evidence-summary'),'Coverage and reuse summary copied.');
for(const key of ['asset','domain','model'])el('review-evidence-'+key).onchange=renderReviewEvidence;
el('review-evidence-search').oninput=renderReviewEvidence;
el('review-evidence-reset').onclick=()=>{for(const key of ['asset','domain','model','search'])el('review-evidence-'+key).value='';renderReviewEvidence();};
renderReviewEvidence();

const governance=workflow?.governance;
if(governance){
  el('governed-review').hidden=false;
  const inventory=governance.inventory,consumers=governance.consumers,naming=governance.naming;
  el('governed-summary').textContent=`Names: ${evidenceStatus(naming?.status)} · Requested inventory: ${evidenceStatus(inventory?.status)} · Public contracts needing review: ${reviewEvidenceCount(consumers?.counts?.needs_review)}. ${governance.qualification}`;
  el('governed-policy').textContent=`Selected policy: ${naming?.policy?.profile||'Not selected'} · Overrides: ${reviewEvidenceCount(naming?.exception_count)}. Artifact check: ${evidenceStatus(governance.naming_artifacts?.status)}. Physical uniqueness covers supplied identities only.`;
  const states=new Map((naming?.resources||[]).map(r=>[r.id,r]));
  table('governed-names',[['Original / source',r=>`${r.original_name} · ${r.source_id}`],['Target',r=>r.target_name],['Physical alias / namespace',r=>`${r.physical_alias||r.target_name} · ${r.namespace.join('.')}`],['Role / domain',r=>`${r.role} · ${r.domain}`],['Conformance',r=>`${evidenceStatus(states.get(r.id)?.status)} · ${(states.get(r.id)?.gaps||[]).join(', ')}`]],governance.identities||[]);
  table('governed-checks',[['Check',r=>r.code],['Status',r=>pretty(r.status)],['File',r=>r.path||'Not supplied']],governance.naming_artifacts?.findings||[]);
  table('governed-counts',[['Domain',r=>r.domain_id],['Requested',r=>r.counts.requested],['Accounted',r=>r.counts.accounted],['Unresolved',r=>r.counts.unresolved]],inventory?.domains||[]);
  const inventoryRows=(inventory?.domains||[]).flatMap(d=>d.rows.map(r=>({...r,domain:d.domain_id})));
  table('governed-inventory',[['Domain',r=>r.domain],['Requested identity',r=>`${r.source_namespace} · ${r.native_id}`],['Classification',r=>pretty(r.classification)],['Models',r=>evidenceNames(r.model_ids)],['Remaining work',r=>r.requirements.join('; ')||'No remaining requirement recorded']],inventoryRows);
  const consumerRows=(consumers?.rows||[]).flatMap(r=>r.findings.map(f=>({...f,contract:r})));
  const value=v=>v===null?'Unknown':typeof v==='object'?JSON.stringify(v):String(v);
  table('governed-consumers',[['Source → target',r=>`${r.contract.source_id} → ${r.contract.entity_id}`],['Change',r=>pretty(r.kind)],['Field',r=>r.column||'Model'],['Before → after',r=>`${value(r.before)} → ${value(r.after)}`],['Review',r=>r.requires_decision?pretty(r.contract.review_status):'Unverified / informational']],consumerRows);
}

const handoff=compactHandoff(data);
table('delivery-stages',[['Stage',s=>s.label],['Recorded status',s=>pretty(s.status)],['What it means',s=>s.detail]],handoff.stages,5);
el('handoff-blockers').textContent=`${handoff.blockers.decisions} unresolved decisions · ${handoff.blockers.failed} failed, ${handoff.blockers.pending} pending and ${handoff.blockers.skipped} skipped reported cases. Missing evidence remains unverified; these counts are not a completion score.`;
for(const gap of handoff.evidenceGaps)el('handoff-evidence-gaps').append(make('li',`${gap.label}: ${pretty(gap.status)}`));
function primaryGuide(id,file,label){
  const target=clear(id);
  if(!file){target.append(make('p',`No ${label.toLowerCase()} is included in this view. Ask the agent to select the maintained document when packaging.`,'muted'));return;}
  target.append(make('h3',label),make('p',file.description||file.path,'muted'));
  const detail=make('details'),summary=make('summary','Read '+label.toLowerCase()),body=bytes(file.base64),binary=/\.(xlsx|docx|pdf)$/i.test(file.path),preview=make('pre',binary?'Download this document to read it in its compatible application.':body.length>2*1024*1024?'Preview is limited to 2 MiB. Download the complete document.':new TextDecoder().decode(body),'guide-preview');
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
  if(workflow.stages?.length){const journey=clear('stage-journey');for(const stage of workflow.stages){const item=make('li',undefined,'stage-'+stage.status);item.append(make('strong',stage.label||pretty(stage.id)),make('small',pretty(stage.status)));if(stage.id===workflow.current_stage)item.setAttribute('aria-current','step');if(stage.next_action)item.append(make('small',stage.next_action));const promised=workflow.delivery_plan?.stages?.find(row=>row.stage===stage.id);if(promised)item.append(make('small',`Delivery plan: ${pretty(promised.plan_status)} · ${promised.task_count} tracked tasks. ${promised.reason||'Requested output remains pending until delivered.'}`));journey.append(item);}}
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
const dbtRuntime=eng.dbt_runtime;
if(dbtRuntime){
  const r=dbtRuntime.selection;
  const status=make('div',undefined,'panel');status.append(make('h3','dbt runtime'),
    make('p',r?`${pretty(r.distribution)} ${r.version} · Requested analysis: ${pretty(r.analysis_mode)}`:'Not selected'),
    make('p',r?`Selection is not a native result. ${dbtRuntime.next_action}`:dbtRuntime.next_action));
  el('dbt-runtime-validation').append(status);
  const box=make('details',undefined,'panel');box.append(make('summary','dbt runtime and setup'));
  box.append(make('p',dbtRuntime.next_action));
  if(r){
    box.append(make('p',`Requested analysis: ${pretty(r.analysis_mode)}. Installed runtime and effective analysis must be verified separately.`));
    box.append(make('p',dbtRuntime.qualification.reason,'muted'));
    box.append(make('p',`Selected features: ${r.features.length?r.features.map(pretty).join(', '):'No optional features'}. Native results are tracked under Validation.`));
    box.append(make('p','Review-only setup; these commands are not executed by this page.'));
    const pre=make('pre');pre.append(make('code',dbtRuntime.setup.commands.join('\n')));box.append(pre);
    const list=make('ul');dbtRuntime.setup.prerequisites.forEach(v=>list.append(make('li',v)));box.append(list);
  }
  el('dbt-runtime-setup').append(box);
}
for(const key of ['assessment','generation','execution']){const value=caps[key];card(el('capabilities'),pretty(key),typeof value==='object'?pretty(value.status):pretty(value||'not assessed'),typeof value==='object'?(value.summary||value.reason||value.note||'See findings and the selected platform contract.'):'No native validation is inferred from static inspection.');}
const coverage=platform.coverage||{};el('coverage').append(make('p',`${coverage.scanned_files??'Unknown'} files inspected · ${coverage.scanned_bytes??'Unknown'} bytes · ${coverage.complete?'Selected static inventory complete':'Inventory gaps remain'}`));const coverageDetails=make('details');coverageDetails.append(make('summary',`${coverage.gaps_total??(coverage.gaps||[]).length} gaps · ${coverage.exclusions_total??(coverage.exclusions||[]).length} exclusions`));for(const item of [...(coverage.gaps||[]),...(coverage.exclusions||[])].slice(0,100)){coverageDetails.append(make('p',`${item.path} — ${pretty(item.reason)}`,'muted'));}if((coverage.gaps_total??(coverage.gaps||[]).length)+(coverage.exclusions_total??(coverage.exclusions||[]).length)>100)coverageDetails.append(make('p','First 100 entries shown. Full coverage remains in the engagement assessment.','muted'));el('coverage').append(coverageDetails);
(platform.findings||[]).forEach(f=>{const box=make('article',undefined,'finding');box.append(make('span',pretty(f.severity||f.status||'review'),'pill'),make('h3',f.summary||f.title||f.id),make('p',f.next_action||f.remedy||f.description||'Review the recorded scope with the agent.'));if(f.paths?.length)box.append(make('code',f.paths.join(', ')));if(f.paths_total>f.paths?.length)box.append(make('p',`Showing ${f.paths.length} of ${f.paths_total} paths. Full detail remains in the original assessment.`,'muted'));el('findings').append(box);});
if(!(platform.findings||[]).length)empty('findings','No findings are recorded. This is not proof of runtime compatibility.');
function allFiles(){return [...files,...(data.generated_deliverables||[])];}
function openArtifact(id){const file=allFiles().find(f=>f.id===id);if(!file)return notice('This artifact is outside the selected package. Ask the agent for the engineering handoff.');el('file-search').value=file.path;el('file-category').value='';fileList();showFile(file);location.hash='#implementation-code';navigate();}
const qualityLanes=[['code_conventions','Code conventions','Code layout and configured rules'],['project_validity','Project validity','Selected framework and project structure'],['warehouse_validation','Warehouse validation','Checks against the selected warehouse'],['data_accuracy','Data accuracy','Independent checks of the model results']];
function qualityOmitted(id){return{id,status:'unknown',scope:'unknown',unit:'items',total:null,summary:'Quality evidence is not included in this page.',next_action:'Include the registered validation evidence to inspect this check.',gaps:['No selected evidence bytes are available.'],evidence_state:'not_included',checked:0,failed:0,skipped:0,unsupported:0,pending:0,unknown:0,not_applicable:0};}
for(const [id,title,meaning]of qualityLanes){const q=(review.quality_checks||[]).find(c=>c.id===id)||qualityOmitted(id),c=make('article',undefined,'quality-card');c.append(make('h3',title),make('span',q.evidence_state==='selected'?'Reported '+pretty(q.status):'Unknown','quality-status '+q.status),make('p',q.total===null?`${q.checked} ${q.unit} checked · total scope unknown`:`${q.checked} / ${q.total} ${q.unit} checked`,'quality-coverage'),make('p',meaning,'muted'),make('p',q.summary));const countNames=[['failed','failed'],['skipped','skipped'],['unsupported','unsupported'],['pending','pending'],['unknown','unresolved'],['not_applicable','not applicable']];const counts=countNames.filter(([key])=>q[key]>0).map(([key,label])=>`${q[key]} ${label}`);if(counts.length)c.append(make('p',counts.join(' · '),'muted'));if(q.gaps?.length){const list=make('ul');q.gaps.forEach(g=>list.append(make('li',g)));c.append(list);}c.append(make('p','Next: '+q.next_action,'quality-next'));if(q.evidence_state==='selected'&&files.some(f=>f.id===q.evidence_artifact_id)){const b=make('button','Inspect quality evidence','secondary');b.onclick=()=>openArtifact(q.evidence_artifact_id);c.append(b);}el('quality-summary').append(c);}
function metadataOmitted(ref){return{plan_artifact_id:ref.plan_artifact_id,sha256:ref.sha256,evidence_state:'not_included',status:'unknown',summary:'Metadata plan evidence is not included in this page.',next_action:'Include the registered metadata plan to inspect its scope, changes and blockers.'};}
function trimMetadataEvidence(next,selected){if(next.review?.metadata&&!selected.some(f=>f.id===next.review.metadata.plan_artifact_id))next.review.metadata=metadataOmitted(next.review.metadata);}
const metadata=review.metadata;
// BEGIN OMNI SUBSET HELPERS — unselected semantic details never survive export.
function omniOmitted(ref){return{artifact_id:ref.artifact_id,sha256:ref.sha256,evidence_state:'not_included',status:'unknown',summary:'Omni semantic evidence is not included in this page.',next_action:'Include the registered Omni semantic review to inspect topics, metrics, dependencies and gaps.'};}
function trimOmniEvidence(next,selected){if(next.review?.omni&&!selected.some(f=>f.id===next.review.omni.artifact_id)){next.review.omni=omniOmitted(next.review.omni);delete next.review.omni_warehouse_bindings;delete next.review.omni_topic_domains;delete next.review.topic_join_trees;delete next.topic_diagrams;delete next.topic_exports;delete next.topic_coverage;if(next.warehouse_diagrams)next.diagrams=next.warehouse_diagrams;delete next.warehouse_diagrams;next.pipeline_semantic_status='Semantic evidence is not included in this subset.';}}
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
function changeTable(){
  const q=el('change-search').value.toLowerCase(),columns=[['Existing',r=>r.source||'Unresolved source'],['Proposed',r=>{const matches=files.filter(f=>f.path===r.target||f.path.endsWith('/'+r.target));const file=matches.length===1?matches[0]:null;if(!file)return r.target||'Unresolved target';const b=make('button',r.target,'secondary');b.type='button';b.onclick=()=>openArtifact(file.id);return b;}],['Disposition',r=>pretty(r.disposition)],['Why / affected consumers',r=>{const n=make('div');n.append(make('strong',r.rationale||'Not supplied'),make('small',(r.consumers||[]).join(', ')||'Consumer coverage unresolved'));return n;}],['Decision',r=>r.decision||'Unresolved']];
  const rows=changes.filter(r=>matchesAsset(r,selection,assetId));
  table('changes-table',columns,rows.filter(r=>JSON.stringify(r).toLowerCase().includes(q)));
  table('replacement-table',columns,rows);
  if(!rows.length)empty('replacement-table','No source-to-target replacements are included in this view. New-model work may have no legacy replacements; excluded or unresolved mappings must be reviewed with the agent.');
}el('change-search').oninput=changeTable;changeTable();
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
    for(const option of d.options||[])if(typeof option.consequences==='string'&&option.consequences.trim()){const consequence=make('div',undefined,'decision-consequence');consequence.append(make('strong',option.label||option.id),make('p',`Consequences: ${option.consequences}`));item.append(consequence);}
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
const graph=modelGraph(models,review.relationships||[],review.omni,review.domain_proposals||[]);
const diagramEnabled=data.page_mode==='status'||!Array.isArray(data.selected_categories)||data.selected_categories.includes('diagrams');
const lineageOptions={focus:'',direction:'both',search:'',layer:'',newOnly:false,context:false,joins:true};
const erdOptions={focus:'',domain:'',dependencies:false,search:'',layer:'',disposition:''};
for(const domain of [...new Set(graph.nodes.flatMap(m=>[m.domain,...(m.proposal_domains||[])]).filter(Boolean))].sort()){const option=make('option',domain);option.value=domain;el('erd-domain').append(option);}
let diagramFitMode=false,tableLimit=50;
let pipelineMode=data.diagram_view_mode==='pipelines',pipelineDomain='';
el('diagram-mode-controls').hidden=!pipelineMode;el('diagram-mode').value=pipelineMode?'pipeline':'relationships';
el('diagram-mode').onchange=()=>{pipelineMode=el('diagram-mode').value==='pipeline';diagramFitMode=false;diagramZoom=1;buildViews();};
let shownViews=[],lineageViews=[],currentDiagram=null,currentLineageDiagram=null,lineageSelection=selectLineage(graph),erdSelection=selectErd(graph),diagramZoom=1,lineageZoom=1,inspectedModel='',inspectorFile=null;
for(const id of ['architecture-model','lineage-model'])for(const model of graph.nodes){
  if(id==='architecture-model'&&!designInventoryObject(model))continue;
  const option=make('option',`${objectKindLabel(model)} · ${model.full_name} (${model.layer})`);option.value=model.id;el(id).append(option);
}
el('lineage-joins').checked=true;
function setViewOptions(id,views){const prior=Number(el(id).value)||0,select=clear(id);views.forEach((v,i)=>{const option=make('option',v.label);option.value=String(i);select.append(option);});select.value=String(Math.min(prior,Math.max(0,views.length-1)));}
function pipelineDomains(view){
  // Gold ownership comes from the output, never from its upstream dependencies.
  const nodes=(view.target_model_id?[view.target_model_id]:(view.model_ids||[])).map(id=>graph.byId.get(id)).filter(Boolean);
  return [...new Set(nodes.flatMap(node=>[node.domain,...(node.proposal_domains||[])]).filter(value=>typeof value==='string'&&value.trim()))].sort();
}
function pipelineMatchesDomain(view,value){const domains=pipelineDomains(view);return !value||(value==='unassigned'?!domains.length:domains.includes(value.slice(7)));}
function pipelineGroup(view){const domains=pipelineDomains(view);return domains.length===1?domains[0]:domains.length?'Shared / multiple domains':'Unassigned';}
function setPipelineOptions(views,priorId){
  const select=clear('diagram-view'),groups=new Map();
  views.forEach((view,index)=>{const label=pipelineGroup(view);if(!groups.has(label)){const group=make('optgroup');group.setAttribute('label',label);groups.set(label,group);select.append(group);}const option=make('option',view.label);option.value=String(index);groups.get(label).append(option);});
  const prior=views.findIndex(view=>view.id===priorId);select.value=String(Math.max(0,prior));
}
function populatePipelineDomains(){
  const views=data.diagrams||[],select=clear('pipeline-domain'),all=make('option','All domains');all.value='';select.append(all);
  const domains=[...new Set(views.flatMap(pipelineDomains))].sort();
  const choices=domains.map(domain=>({value:'domain:'+domain,label:domain}));
  if(views.some(view=>!pipelineDomains(view).length))choices.push({value:'unassigned',label:'Unassigned'});
  for(const choice of choices){const rows=views.filter(view=>pipelineMatchesDomain(view,choice.value)),gold=rows.filter(view=>view.target_model_id).length,supporting=rows.length-gold;const option=make('option',choice.label+' · '+[gold?`${gold} gold`:null,supporting?`${supporting} supporting`:null].filter(Boolean).join(', '));option.value=choice.value;select.append(option);}
  select.value=pipelineDomain;
}
populatePipelineDomains();
el('pipeline-domain').onchange=()=>{pipelineDomain=el('pipeline-domain').value;buildViews();el('diagram').scrollTop=0;el('diagram').scrollLeft=0;};
function renderDesignReadiness(){
  const readiness=workflow?.design_readiness,enabled=data.audience!=='audit'&&(data.page_mode==='status'||!Array.isArray(data.selected_categories)||['documentation','diagrams','dictionary'].some(key=>data.selected_categories.includes(key)));
  el('design-readiness').hidden=!enabled||!readiness;
  if(!enabled||!readiness)return;
  const target=clear('design-readiness-statuses');
  for(const [key,label]of [['structural','Structure'],['coverage','Source coverage'],['evidence','Evidence'],['independent_review','Independent review'],['human_review','Human review'],['native_validation','Native validation']]){
    const item=readiness[key]||{},badge=make('span',`${label}: ${pretty(item.status||'unassessed')}`,'pill');
    if(item.qualification)badge.title=item.qualification;
    target.append(badge);
  }
  const evidenceCounts=readiness.evidence?.counts,bases=[['observed_metadata','observed metadata'],['repository_declaration','repository declarations'],['user_assertion','user assertions'],['proposal','proposals']];
  const classifications=evidenceCounts&&bases.some(([key])=>Object.hasOwn(evidenceCounts,key))?' Evidence classifications: '+bases.map(([key,label])=>label+': '+reviewEvidenceCount(evidenceCounts[key])).join(' · ')+'. Counts classify host-reported claims only; warehouse verification requires separate execution evidence.':'';
  el('design-readiness-note').textContent='Included design scope. Diagram filters change the visible counts, not these checks. '+(readiness.qualification||'Structural consistency does not establish complete discovery, independent review, human approval, or native validation.')+classifications;
}
function renderArchitectureIntent(){
  const intent=workflow?.migration_intent,enabled=data.audience!=='audit'&&(data.page_mode==='status'||!Array.isArray(data.selected_categories)||['documentation','diagrams','dictionary'].some(key=>data.selected_categories.includes(key)));
  el('architecture-intent').hidden=!enabled||!intent;if(!enabled||!intent)return;
  const target=clear('architecture-intent-domains');
  for(const domain of intent.domains||[]){
    const line=make('p'),counts=domain.model_disposition_counts||{};
    line.append(make('strong',domain.domain_id+' · '+pretty(domain.structural_objective||'unassessed')),make('span',' · Conformance review: '+pretty(domain.status||'unassessed')));
    line.append(make('span',' · Target models: '+['create','reuse','extend','replace','undetermined'].map(key=>pretty(key)+': '+reviewEvidenceCount(counts[key])).join(' · ')));
    line.append(make('span',' · Transitional dependencies: '+reviewEvidenceCount(domain.transitional_dependency_count)));
    if(domain.behavior)line.append(make('span',' · Behavior: '+pretty(domain.behavior)));
    line.append(make('span',' · Unresolved: '+(domain.gaps?.length?domain.gaps.map(pretty).join('; '):'None reported; see review qualification')));
    target.append(line);
  }
  if(!intent.domains?.length)target.append(make('p','Architecture intent is unassessed in the included scope.','muted'));
  el('architecture-intent-note').textContent=(intent.qualification||'Host-attributed architecture review only.')+' Native validation and business acceptance remain separate; this summary grants no approval or completion authority.';
}
function buildViews(){
  const priorPipelineId=pipelineMode?currentDiagram?.id:null;
  let allowed;
  if(assetId){allowed=new Set(selection.visible);if(assetId==='__unmapped__')for(const node of graph.nodes)if(node.object_kind==='semantic')allowed.add(node.id);}
  lineageSelection=selectLineage(graph,{...lineageOptions,allowed});
  erdSelection=selectErd(graph,{...erdOptions,allowed});
  shownViews=diagramEnabled?(pipelineMode?(data.diagrams||[]).filter(view=>(!allowed||view.model_ids.every(id=>allowed.has(id)))&&pipelineMatchesDomain(view,pipelineDomain)).map(view=>({...view,nodes:view.model_ids.map(id=>graph.byId.get(id)).filter(Boolean),svg:new TextDecoder().decode(bytes(view.base64)),edges:(view.edges||[]).map(edge=>({...edge})),compact:true})).sort((a,b)=>pipelineGroup(a).localeCompare(pipelineGroup(b))||Number(!a.target_model_id)-Number(!b.target_model_id)||a.label.localeCompare(b.label)):erdPages(erdSelection)):[];
  document.body.classList.toggle('pipeline-mode',pipelineMode);
  el('pipeline-domain-controls').hidden=!pipelineMode;
  el('pipeline-help').hidden=!pipelineMode;
  if(pipelineMode)el('pipeline-help').textContent='Raw → staging → intermediate → gold. Click a table for columns, keys and code.';
  el('diagram-title').textContent=pipelineMode?'Pipeline to a gold table':'Entity relationship diagram';
  el('diagram-view-label').textContent=pipelineMode?'Choose a gold output or additional input group':'Diagram page';
  el('diagram-download').textContent=pipelineMode?'Download this pipeline':'Download current view + ledger';
  el('diagram-download-all').textContent=pipelineMode?(pipelineDomain?'Download domain pipelines':'Download all pipelines'):'Download complete domain ERD';
  document.querySelectorAll('.advanced-erd-controls,.workspace-options').forEach(node=>node.hidden=pipelineMode);
  el('diagram-legend').textContent=pipelineMode?'Read top to bottom. Arrows show recorded transformation dependencies. New and reused objects are labeled. Joins and cardinality remain in table details. Unresolved external interfaces are marked. '+(data.pipeline_semantic_status||''):'Lines show declared joins; optional teal arrows show dependencies. No constraint enforcement is implied.';
  lineageViews=diagramEnabled?graphPages(lineageSelection,36,data.diagrams||[]):[];
  if(pipelineMode)setPipelineOptions(shownViews,priorPipelineId);else setViewOptions('diagram-view',shownViews);
  setViewOptions('lineage-view',lineageViews);
  el('pipeline-domain-summary').hidden=!pipelineMode;
  el('pipeline-domain-summary').textContent=pipelineMode?`${pipelineDomain?(pipelineDomain==='unassigned'?'Unassigned':pipelineDomain.slice(7)):'All domains'} · ${shownViews.filter(view=>view.target_model_id).length} gold pipelines · ${shownViews.filter(view=>!view.target_model_id).length} supporting views. Shared upstream tables remain visible. This filter does not change the full delivery package.`:'';
  el('lineage-summary').textContent=diagramEnabled?`${lineageSelection.selected.size} selected + ${lineageSelection.dependencies.size} dependency-context objects of ${graph.nodes.length} included objects. ${lineageSelection.hidden} hidden by filters; ${graph.unresolved} unresolved endpoint references. Joins are separate from transformation dependencies.`:'Diagrams were not selected for this package.';
  const summary=clear('model-summary'),visible=erdSelection.nodes.filter(m=>erdSelection.selected.has(m.id)),visibleModels=visible.filter(m=>designObjectKind(m)==='model');
  summary.append(make('strong',`Models: ${visibleModels.length}`),make('span',`Sources: ${visible.filter(m=>designObjectKind(m)==='source').length}`,'pill'),make('span',`External interfaces: ${visible.filter(m=>designObjectKind(m)==='interface').length}`,'pill interface-kind'),make('span','Candidate design','pill'));
  for(const [value,label]of [['create','new'],['reuse','reused'],['extend','extended'],['replace','replaced'],['undetermined','unspecified']]){const count=visibleModels.filter(m=>value==='undetermined'?dispositionLabel(m)==='Unspecified':m.disposition===value).length;if(count)summary.append(make('span',`${count} ${label}`,'pill'));}
  for(const kind of ['fact','dimension']){const count=visibleModels.filter(m=>m.entity_type===kind).length;if(count)summary.append(make('span',`${count} ${kind}${count===1?'':'s'}`,'pill'));}
  summary.append(make('span',`${erdSelection.edges.filter(e=>e.kind==='relationship').length} declared relationship occurrences`));
  renderDesignReadiness();
  renderArchitectureIntent();
  const unresolved=decisions.filter(d=>!['resolved','accepted','approved'].includes(d.status)).length;if(unresolved){const link=make('a',`${unresolved} decisions to review`);link.href='#changes';summary.append(link);}
  el('diagram-download-all').disabled=!diagramEnabled||!models.length||(pipelineMode&&!shownViews.length);
  showDiagram();showLineage();relationshipTable();tableNavigator();
  const inspector=clear('inspect-model');const prompt=make('option','Choose a table');prompt.value='';inspector.append(prompt);
  for(const model of graph.nodes.filter(m=>designInventoryObject(m)||erdSelection.visible.has(m.id))){const option=make('option',`${model.full_name} · ${model.reference_only?'Reference only':dispositionLabel(model)}`);option.value=model.id;inspector.append(option);}
  if(!graph.byId.has(inspectedModel))inspectedModel=(pipelineMode?shownViews[0]?.target_model_id:'')||erdSelection.nodes[0]?.id||'';
  inspector.value=inspectedModel;inspectModel(inspectedModel);
  table('model-roster',[['Table',m=>{const b=make('button',m.full_name,'secondary');b.type='button';b.onclick=()=>revealModel(m.id);return b;}],['Change',dispositionLabel],['One row represents',m=>m.grain||'Not supplied'],['Declared keys',m=>(m.columns||[]).filter(c=>c.key||(m.keys||[]).includes(c.name)).map(c=>`${columnRole(m,c)}: ${c.name}`).join('; ')||'Not supplied']],erdSelection.nodes);
  const unverified=(data.diagram_coverage?.registered||[]).filter(r=>r.status==='unverified');
  modelWorkspaceReady=true;
  el('diagram-artifact-note').hidden=!unverified.length;el('diagram-artifact-note').textContent=`${unverified.length} supplied SVG file(s) have unverified table coverage. The ERD above is rebuilt from the included table inventory; use Download complete ERD for that inventory.`;
}
function copyText(value,fallback,message){
  return Promise.resolve().then(()=>{if(!globalThis.navigator?.clipboard?.writeText)throw new Error('Clipboard unavailable');return navigator.clipboard.writeText(value);}).then(()=>notice(message)).catch(()=>{
    if(fallback?.select){fallback.focus?.();fallback.select();}
    else if(fallback&&document.createRange&&globalThis.getSelection){const range=document.createRange();range.selectNodeContents(fallback);const selected=getSelection();selected.removeAllRanges();selected.addRange(range);}
    notice('Clipboard access is unavailable. The complete text is selected; use your normal Copy shortcut.');
  });
}
function diagramCopyControls(prefix,view){
  const target=clear(prefix+'-copy');if(!view)return;
  const label=make('label','Select a full model name to copy'),select=make('select'),input=make('input'),button=make('button','Copy full name','secondary');
  select.setAttribute('aria-label','Model name to copy');input.setAttribute('aria-label','Full model name');input.readOnly=true;button.type='button';
  for(const model of view.nodes){const option=make('option',model.full_name||model.name||model.id);option.value=model.id;select.append(option);}
  select.value=view.nodes[0]?.id||'';
  const update=()=>{const model=graph.byId.get(select.value);input.value=model?.full_name||'';};select.onchange=update;update();
  button.onclick=()=>copyText(input.value,input,'Full model name copied.');label.append(select);target.append(label,input,button);
  return id=>{if(view.model_ids.includes(id)){select.value=id;update();}};
}
function viewSvg(view){if(!view.svg)view.svg=filteredModelSvg(view.nodes,view.edges,new Set(),view.omitted_graph_connections,Boolean(view.compact));assertModelCoverage(view.nodes,view.svg);return view.svg;}
function drawDiagram(containerId,prefix,view){
  const target=clear(containerId),selectName=diagramCopyControls(prefix,view);
  if(!view){target.append(make('p',diagramEnabled?'No tables match this view. Choose Show all tables or clear the lineage filters.':'Diagrams are outside this export selection.','empty'));return;}
  try{viewSvg(view);}catch(error){target.append(make('p',error.message,'fail'));notice(error.message);return;}
  try{
    if(typeof PortalSvg==='undefined')throw new Error('SVG parser unavailable');
    const svg=PortalSvg.sanitize(view.svg,'dma-'+prefix);
    if(prefix==='diagram'){svg.setAttribute('role','group');svg.setAttribute('aria-label','Entity relationship diagram: select a table to inspect');}
    const groups=[...svg.querySelectorAll('[data-model-id]')].filter(n=>(n.localName||n.tag)==='g'),ids=groups.map(n=>n.getAttribute('data-model-id'));
    if(ids.length!==view.model_ids.length||new Set(ids).size!==ids.length||view.model_ids.some(id=>!ids.includes(id)))throw new Error('Sanitized table coverage differs');
    target.append(svg);
    svg.querySelectorAll('[data-model-id]').forEach(label=>{const id=label.getAttribute('data-model-id');label.onclick=()=>{selectName?.(id);if(prefix==='diagram')revealModel(id);};if(prefix==='diagram'&&(label.localName||label.tag)==='g'){label.setAttribute('tabindex','0');label.setAttribute('role','button');label.setAttribute('aria-label','Inspect '+graph.byId.get(id).full_name);label.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();revealModel(id);}};}});
    target.oncopy=event=>{
      const selected=globalThis.getSelection?.();if(!selected?.rangeCount||!String(selected)||!event.clipboardData)return;
      const names=new Set();svg.querySelectorAll('[data-model-id]').forEach(label=>{if((label.localName||label.tag)==='g')return;for(let i=0;i<selected.rangeCount;i++){if(selected.getRangeAt(i).intersectsNode(label)){const model=graph.byId.get(label.getAttribute('data-model-id'));if(model)names.add(model.full_name);}}});
      if(names.size){event.clipboardData.setData('text/plain',[...names].join('\n'));event.preventDefault();}
    };
    if(typeof XMLSerializer!=='undefined')view.downloadSvg=new XMLSerializer().serializeToString(svg);
  }catch(error){
    const img=make('img');img.src='data:image/svg+xml;base64,'+btoa(Array.from(new TextEncoder().encode(view.svg),byte=>String.fromCharCode(byte)).join(''));img.alt='Model diagram. Use the table selector to inspect every included table.';target.replaceChildren(img);target.oncopy=null;
    target.append(make('p','Interactive SVG is unavailable here. Use the table selector to inspect the model.','muted'));
  }
  applyDiagramZoom(containerId,prefix,prefix==='diagram'?diagramZoom:lineageZoom);
  if(prefix==='diagram'&&diagramFitMode)fitDiagram();
}
function applyDiagramZoom(containerId,prefix,value){
  const target=el(containerId),graphic=target.querySelector?.('svg, img'),view=prefix==='diagram'?currentDiagram:currentLineageDiagram;el(prefix+'-zoom').textContent=Math.round(value*100)+'%';
  if(graphic){const width=Number(graphic.getAttribute?.('width'))||graphic.naturalWidth||Number(view?.svg?.match(/width="([\d.]+)"/)?.[1]);const height=Number(graphic.getAttribute?.('height'))||graphic.naturalHeight||Number(view?.svg?.match(/height="([\d.]+)"/)?.[1]);if(width&&height){graphic.style.width=width*value+'px';graphic.style.height=height*value+'px';}}
}
function showDiagram(){
  const view=shownViews[Number(el('diagram-view').value)||0];currentDiagram=view||null;
  el('diagram-download').disabled=!view;el('diagram-view').hidden=shownViews.length<2;el('diagram-view-label').hidden=shownViews.length<2;
  drawDiagram('diagram','diagram',view);
  el('diagram-coverage').textContent=pipelineMode?(view?`${view.model_ids.length} warehouse objects in this pipeline · ${view.internal_connections} dependency paths · ${view.join_relationship_count??(view.join_relationships||[]).length} joins available in table details.${view.cycles?.length?' Cycle detected; execution order is unresolved.':''}`:'No complete pipeline matches these domain and asset filters. Choose All domains, clear the asset filter, or use the detailed relationship view.'):view?`${view.model_ids.length} tables on this page · ${erdSelection.domain_count} of ${erdSelection.domain_total} included tables · ${erdSelection.shared_count} shared references · ${erdSelection.missing_count} missing definitions · ${erdSelection.hidden} hidden domain tables · ${erdSelection.hidden_references} references omitted by scope · ${erdSelection.hidden_connections} joins hidden by scope${erdSelection.hidden?` · ${erdSelection.hidden} hidden by filters`:''}${view.cross_view_connections?` · ${view.cross_view_connections} joins continue on another page`:''}${view.omitted_graph_connections?` · ${view.omitted_graph_connections} connectors in the relationship table only`:''}.`:diagramEnabled?'No tables match. Show all tables to reset this view.':'Diagrams were not included in this package.';
}
function showLineage(){currentLineageDiagram=lineageViews[Number(el('lineage-view').value)||0]||null;el('lineage-download').disabled=!currentLineageDiagram;el('lineage-view').hidden=lineageViews.length<2;drawDiagram('lineage-diagram','lineage',currentLineageDiagram);}
function fitDiagram(){
  const target=el('diagram'),view=currentDiagram;
  if(!view||!target.clientWidth)return;
  const width=Number(view.svg?.match(/width="([\d.]+)"/)?.[1]),height=Number(view.svg?.match(/height="([\d.]+)"/)?.[1]);
  if(!width||!height)return;
  diagramZoom=Math.max(.5,Math.min(1,(target.clientWidth-8)/width,((globalThis.innerHeight||900)*.65)/height));
  diagramFitMode=true;applyDiagramZoom('diagram','diagram',diagramZoom);target.scrollLeft=0;target.scrollTop=0;
}
el('diagram-fit').onclick=fitDiagram;
el('diagram-expand').onclick=()=>{const expanded=el('diagram-expand').getAttribute('aria-expanded')!=='true';el('model-canvas').classList.toggle('expanded',expanded);el('diagram-expand').setAttribute('aria-expanded',String(expanded));el('diagram-expand').textContent=expanded?'Close expanded view':'Expand diagram';if(diagramFitMode)fitDiagram();};
addEventListener('resize',()=>{if(diagramFitMode)fitDiagram();});
function tableNavigator(){
  const query=el('table-search').value.toLowerCase(),rows=graph.nodes.filter(m=>designInventoryObject(m)&&(!query||m.full_name.toLowerCase().includes(query))),target=clear('table-navigator');
  el('table-count').textContent=`${rows.length} of ${models.length} included tables · select a table for columns, keys, joins and code. Diagram filters do not remove tables from this list.`;
  for(const model of rows.slice(0,tableLimit)){const button=make('button',model.full_name,'secondary');button.type='button';button.setAttribute('aria-current',String(model.id===inspectedModel));button.setAttribute('aria-label','Inspect '+model.full_name);button.append(make('small',`${pretty(model.layer)} · ${dispositionLabel(model)}`));button.onclick=()=>{revealModel(model.id);};target.append(button);}
  if(!rows.length)target.append(make('p','No table names match. Clear the search to see every included table.','muted'));
  el('table-more').hidden=rows.length<=tableLimit;
}
el('table-search').oninput=()=>{tableLimit=50;tableNavigator();};el('table-more').onclick=()=>{tableLimit+=50;tableNavigator();};
for(const prefix of ['diagram','lineage']){
  el(prefix+'-view').onchange=()=>{if(prefix==='diagram')showDiagram();else showLineage();const viewport=el(prefix==='diagram'?'diagram':'lineage-diagram');viewport.scrollTop=0;viewport.scrollLeft=0;};
  el(prefix+'-download').onclick=()=>{const view=prefix==='diagram'?currentDiagram:currentLineageDiagram;if(view){if(prefix==='diagram'&&pipelineMode)download((view.export_path||'pipeline.svg').split('/').pop(),view.downloadSvg||viewSvg(view),'image/svg+xml');else if(prefix==='diagram')exportErd('erd-current-view.zip',[view],erdSelection,'Current diagram page; ledger includes its cross-page relationships.');else download('lineage-current-view.svg',view.downloadSvg||viewSvg(view),'image/svg+xml');}};
  for(const [action,delta]of [['in',.25],['out',-.25],['reset',0]])el(prefix+'-zoom-'+action).onclick=()=>{let value=prefix==='diagram'?diagramZoom:lineageZoom;value=delta?Math.max(.25,Math.min(3,value+delta)):1;if(prefix==='diagram'){diagramZoom=value;diagramFitMode=false;}else lineageZoom=value;applyDiagramZoom(prefix==='diagram'?'diagram':'lineage-diagram',prefix,value);};
}
function exportErd(filename,pages,scope,label,complete=false){
  const encoder=new TextEncoder(),ids=pages.flatMap(p=>p.model_ids),nodeIds=new Set(ids),edges=(scope.ledger||scope.edges).filter(e=>complete||nodeIds.has(e.from)||nodeIds.has(e.to));
  const entries=pages.map((page,i)=>['erd-'+String(i+1).padStart(3,'0')+'.svg',encoder.encode(filteredModelSvg(page.nodes,page.edges,new Set(),page.omitted_graph_connections,false,true))]);
  entries.push(['MODEL_INDEX.json',encoder.encode(JSON.stringify({scope:label,domain:scope.domain||null,model_ids:ids,dependencies_displayed:scope.dependencies_displayed,ledger_only_model_ids:[...new Set(edges.flatMap(e=>[e.from,e.to]))].filter(id=>!nodeIds.has(id)),
    domain_model_ids:scope.nodes.filter(n=>nodeIds.has(n.id)&&n.scope_role==='domain').map(n=>n.id),reference_ids:scope.nodes.filter(n=>nodeIds.has(n.id)&&n.scope_role!=='domain').map(n=>n.id),
    models:scope.nodes.filter(n=>nodeIds.has(n.id)),relationships:edges,hidden_tables:scope.hidden,hidden_references:scope.hidden_references,hidden_connections:scope.hidden_connections,
    pages:pages.map(p=>({model_ids:p.model_ids,cross_view_connections:p.cross_view_connections,ledger_only_connections:p.omitted_graph_connections})),qualification:'Candidate display only. Every supplied occurrence is retained; conflicting definitions require review. References are not certified warehouse models. No approval or validation is implied.'},null,2))]);
  download(filename,zip(entries),'application/zip');
}
el('diagram-download-all').onclick=()=>{
  try{if(!diagramEnabled||!models.length)return;
    if(pipelineMode){if(!shownViews.length)return;const entries=shownViews.map(view=>[(view.export_path||view.id+'.svg').split('/').pop(),new TextEncoder().encode(view.downloadSvg||viewSvg(view))]);download(pipelineDomain?'domain-pipelines.zip':'model-pipelines.zip',zip(entries),'application/zip');notice('Exported the visible pipeline set with its shared dependencies. The complete model, dictionary and detailed joins remain in the full handoff.');return;}
    const allowed=assetId?new Set(selection.visible):undefined,complete=selectErd(graph,{domain:erdOptions.domain,allowed,dependencies:erdOptions.dependencies}),pages=erdPages(complete),ids=pages.flatMap(p=>p.model_ids);
    if(ids.length!==complete.nodes.length||new Set(ids).size!==complete.nodes.length)throw new Error('Complete ERD coverage failed.');
    exportErd('complete-domain-erd.zip',pages,complete,'Complete selected domain and connected references within the included asset/audience scope. Search, layer, change and focus filters are ignored.',true);
    notice(`Exported all ${complete.domain_count} included domain tables, ${complete.shared_count} shared references and ${complete.missing_count} missing definitions. Asset and audience scope retained; joins are declared, not validated.`);
  }catch(error){notice(error.message);}
};
function syncLineage(){el('lineage-model').value=lineageOptions.focus;el('lineage-direction').value=lineageOptions.direction;buildViews();}
for(const [id,key]of [['erd-domain','domain'],['erd-layer','layer'],['erd-disposition','disposition']])el(id).onchange=()=>{erdOptions[key]=el(id).value;buildViews();};
el('architecture-model').onchange=()=>{erdOptions.focus=el('architecture-model').value;if(erdOptions.focus)revealModel(erdOptions.focus);};
el('erd-dependencies').onchange=()=>{erdOptions.dependencies=el('erd-dependencies').checked;buildViews();};
el('erd-search').oninput=()=>{erdOptions.search=el('erd-search').value;buildViews();};
el('erd-clear').onclick=()=>{Object.assign(erdOptions,{focus:'',domain:'',dependencies:false,search:'',layer:'',disposition:''});for(const id of ['architecture-model','erd-domain','erd-layer','erd-disposition','erd-search','asset-filter'])el(id).value='';el('erd-dependencies').checked=false;filterAssets();};
el('lineage-model').onchange=()=>{lineageOptions.focus=el('lineage-model').value;syncLineage();};el('lineage-direction').onchange=()=>{lineageOptions.direction=el('lineage-direction').value;syncLineage();};
let lineageSearchTimer;
el('lineage-search').oninput=()=>{clearTimeout(lineageSearchTimer);lineageSearchTimer=setTimeout(()=>{lineageOptions.search=el('lineage-search').value;buildViews();},160);};
el('lineage-layer').onchange=()=>{lineageOptions.layer=el('lineage-layer').value;buildViews();};
for(const [id,key]of [['lineage-new','newOnly'],['lineage-context','context'],['lineage-joins','joins']])el(id).onchange=()=>{lineageOptions[key]=el(id).checked;buildViews();};
el('lineage-clear').onclick=()=>{clearTimeout(lineageSearchTimer);Object.assign(lineageOptions,{focus:'',direction:'both',search:'',layer:'',newOnly:false,context:false,joins:true});el('lineage-search').value='';el('lineage-layer').value='';el('lineage-new').checked=false;el('lineage-context').checked=false;el('lineage-joins').checked=true;syncLineage();};

function relationshipTable(){table('relationships',[['From',r=>graph.byId.get(r.from)?.full_name||r.from],['To',r=>graph.byId.get(r.to)?.full_name||r.to],['Join / cardinality',r=>[r.predicate||r.label||'Predicate not supplied',relationshipColumns(r),r.cardinality||'Cardinality not supplied',r.role].filter(Boolean).join(' · ')],['Status',r=>r.status||r.implementation_status||'Not specified'],['Evidence / reconciliation',r=>edgeEvidence(r)]],erdSelection.edges,10);}
function showInspectorTab(name){for(const tab of ['columns','relationships','code']){el('inspect-'+tab).hidden=tab!==name;el('inspect-'+tab+'-tab').setAttribute('aria-selected',String(tab===name));}}
let inspectorReturn=null;
function closeInspector(){el('table-inspector').classList.toggle('drawer-open',false);el('table-inspector').removeAttribute('role');el('table-inspector').removeAttribute('aria-modal');inspectorReturn?.focus?.({preventScroll:true});}
function revealModel(id){inspectorReturn=document.activeElement;const page=shownViews.findIndex(view=>view.model_ids.includes(id));if(page>=0&&page!==(Number(el('diagram-view').value)||0)){el('diagram-view').value=String(page);showDiagram();}inspectModel(id);const panel=el('table-inspector');if(pipelineMode||(globalThis.innerWidth||1400)<=1200){panel.classList.toggle('drawer-open',true);panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.focus?.({preventScroll:true});}}
el('inspector-close').onclick=closeInspector;
addEventListener('keydown',event=>{if(event.key==='Escape'){closeInspector();if(el('diagram-expand').getAttribute('aria-expanded')==='true')el('diagram-expand').onclick();}if(event.key==='Tab'&&el('table-inspector').getAttribute('aria-modal')==='true'){const nodes=[...el('table-inspector').querySelectorAll('button, select, textarea, a')].filter(n=>!n.disabled&&!n.hidden&&n.getClientRects?.().length);if(!nodes.length)return;const first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&(document.activeElement===first||document.activeElement===el('table-inspector'))){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}});

function inspectModel(id){
  inspectedModel=id;tableNavigator();el('inspect-model').value=id;el('diagram').querySelectorAll?.('[data-model-id]').forEach(node=>{if((node.localName||node.tag)==='g'){const selected=node.getAttribute('data-model-id')===id;node.classList.toggle('selected-model',selected);node.setAttribute('aria-current',String(selected));}});const model=graph.byId.get(id),scopeRole=erdSelection.nodes.find(m=>m.id===id)?.scope_role,summary=clear('inspector-summary');
  if(!model){summary.append(make('p','Choose a table in the ERD or selector.','empty'));clear('inspect-columns');clear('inspect-relationships');clear('inspect-code-file').hidden=true;el('inspect-code-file').onchange=null;showInspectorCode(null);return;}
  summary.append(make('h3',model.full_name),make('span',model.reference_only?'Reference only · definition missing':scopeRole==='shared_reference'?'Shared reference':dispositionLabel(model),'pill'),make('p',model.grain||'Row grain has not been supplied.'));
  summary.append(make('span',objectKindLabel(model),'pill'+(designObjectKind(model)==='interface'?' interface-kind':'')));
  if(designObjectKind(model)==='interface')summary.append(make('p','External interface only; executable implementation and compatibility are unresolved.','muted'));
  for(const [key,label]of [['keys','Declared keys'],['history','History'],['security','Security']])if(model[key]!=null)summary.append(make('p',label+': '+(Array.isArray(model[key])?model[key].join(', ')||'Not supplied':text(model[key])),'muted'));
  if(model.description)summary.append(make('p',model.description,'muted'));
  const modelCases=cases.filter(c=>c.model_ids?.includes(id)),modelDecisions=decisions.filter(d=>d.model_ids?.includes(id)&&!['resolved','accepted','approved'].includes(d.status));
  summary.append(make('p',modelCases.length?`Table checks: ${modelCases.filter(c=>c.status==='fail').length} failed, ${modelCases.filter(c=>c.status==='pass').length} reported passes, ${modelCases.filter(c=>!['fail','pass'].includes(c.status)).length} pending/other. Verify evidence in Validation.`:'Table-specific validation is not supplied. See Validation for engagement checks.','muted'));
  if(modelDecisions.length){const link=make('a',`${modelDecisions.length} open decisions for this table`);link.href='#changes';link.onclick=closeInspector;summary.append(link);}
  if(model.reuse?.existing_id)summary.append(make('p',`Existing model: ${model.reuse.existing_id}`,'muted'));
  if(model.reuse?.rationale)summary.append(make('p',model.reuse.rationale,'muted'));
  if(model.columns?.length)table('inspect-columns',[['Column definitions',c=>{const cell=make('div'),heading=make('div',undefined,'inspector-detail-heading');heading.append(make('strong',c.name),make('span',columnRole(model,c),'pill'));cell.append(heading,make('p',[c.type||c.data_type||'Type not supplied',c.nullable===true?'Nullable':c.nullable===false?'Not nullable':typeof c.nullable==='string'?c.nullable:null].filter(Boolean).join(' · '),'muted'),make('p',c.description||'Definition not supplied.'));return cell;}]],model.columns,20);
  else empty('inspect-columns','Column definitions are not included in this package. Request the dictionary.');
  const joins=graph.edges.filter(e=>e.kind==='relationship'&&(e.from===id||e.to===id));
  if(joins.length)table('inspect-relationships',[['Declared relationships',e=>{const cell=make('div');cell.append(make('strong',graph.byId.get(e.from===id?e.to:e.from)?.full_name||'Unresolved'),make('p',e.predicate||'Join predicate not supplied.','inspector-predicate'),make('p',relationshipColumns(e),'muted'),make('p',`Cardinality: ${e.cardinality||'Not supplied'}${e.role?' · Role: '+e.role:''}`,'muted'),make('p',`Status: ${e.status||e.implementation_status||'Not supplied'}`,'muted'),make('p',edgeEvidence(e),'muted'));return cell;}]],joins,10);
  else empty('inspect-relationships','No joins are recorded for this table. Keys and relationships are not inferred from names.');
  const codeIds=new Set([model.artifact_id,...(Array.isArray(model.artifact_ids)?model.artifact_ids:[])].filter(Boolean)),linked=files.filter(f=>codeIds.has(f.id)&&f.category==='implementation'),select=clear('inspect-code-file');
  for(const file of linked){const option=make('option',file.path);option.value=file.id;select.append(option);}select.hidden=linked.length<2;select.value=linked[0]?.id||'';select.onchange=()=>showInspectorCode(linked.find(f=>f.id===select.value)||null);
  showInspectorCode(linked[0]||null);
}
function showInspectorCode(file){inspectorFile=file;el('inspector-open-code').disabled=!file;const body=file?bytes(file.base64):null,tooLarge=body&&body.length>2*1024*1024;el('inspect-code-copy').disabled=!file||tooLarge;el('inspect-code-download').disabled=!file;el('inspect-code-text').textContent=body?(tooLarge?'Preview limited to 2 MiB. Download the complete file.':new TextDecoder().decode(body)):'';el('inspect-code-note').textContent=file?file.path:data.audience==='reviewer'?'Code is excluded from reviewer packages. Request the engineering package.':data.page_mode==='status'?'This status page has no code payload. Request the engineering package.':'No implementation artifact is linked to this table. Ask the agent to register the mapping; included files remain in Code & files.';}
el('inspector-open-code').onclick=()=>{if(inspectorFile){closeInspector();openArtifact(inspectorFile.id);}};
el('inspector-feedback').onclick=()=>{el('feedback-model').value=models.some(m=>m.id===inspectedModel)?inspectedModel:'';closeInspector();location.hash='review-feedback';};
el('inspect-model').onchange=()=>inspectModel(el('inspect-model').value);
for(const tab of ['columns','relationships','code'])el('inspect-'+tab+'-tab').onclick=()=>showInspectorTab(tab);
el('inspect-code-copy').onclick=()=>{if(inspectorFile&&!el('inspect-code-copy').disabled)copyText(el('inspect-code-text').textContent,el('inspect-code-text'),'Code copied.');};
el('inspect-code-download').onclick=()=>{if(inspectorFile)download(inspectorFile.path.split('/').pop(),bytes(inspectorFile.base64));};
function dictionary(){const q=el('model-search').value.toLowerCase(),layer=el('layer-filter').value,rows=[];models.filter(m=>selection.visible.has(m.id)&&(!layer||m.layer===layer)).forEach(m=>(m.columns?.length?m.columns:[{name:'Columns not included',description:'See the separately selected dictionary.'}]).forEach(c=>{const r={model:m,column:c};if(JSON.stringify({id:m.id,name:m.name,grain:m.grain,layer:m.layer,domain:m.domain,column:c}).toLowerCase().includes(q))rows.push(r);}));table('dictionary',[['Table / grain',r=>modelLink(r.model)],['Column',r=>r.column.name],['Type / key',r=>`${r.column.type||'Unresolved'} ${r.column.key||''}`],['Definition',r=>r.column.description||'Not supplied']],rows);}
el('model-search').oninput=dictionary;el('layer-filter').onchange=dictionary;
for(const asset of review.assets||[]){const option=make('option',`${asset.name||asset.id} · ${asset.kind||'asset'} · ${asset.mapping_status||'mapping unverified'}`);option.value=asset.id;el('asset-filter').append(option);}
el('asset-controls').hidden=!models.length&&!(review.assets||[]).length;
function filterAssets(){assetId=el('asset-filter').value;selection=assetSelection(models,review.relationships||[],assetId);el('asset-filter-note').textContent=`${selection.visible.size} of ${models.length} entities visible; ${selection.dependencies.size} required dependencies retained. ${selection.unknown.size} entities have missing or unverified asset mappings. Unmapped decisions and changes remain visible.`;buildViews();relationshipTable();dictionary();changeTable();decisionList();}
el('asset-filter').onchange=filterAssets;filterAssets();
card(el('validation-counts'),'Reported passes',cases.filter(c=>c.status==='pass').length,`${cases.length} total declared cases; scope is shown per case.`);
const authoringChecks=workflow?.authoring_checks||[];
const designChecks=workflow?.design_checks;
el('design-consistency-note').textContent=designChecks?`${designChecks.finding_count} structural findings · ${designChecks.unknown_count} unknowns. ${designChecks.qualification}`:'Design consistency has not been checked for this package.';
table('design-consistency',[['Finding',r=>pretty(r.code)],['Status',r=>pretty(r.status)],['Scope',r=>pretty(r.scope)],['Action / explanation',r=>r.message]],designChecks?.findings||[]);
table('artifact-syntax',[['Task',r=>r.task_id],['Stage',r=>pretty(r.stage)],['Status',r=>pretty(r.status)],['Counts',r=>Object.entries(r.counts||{}).map(([key,value])=>`${value} ${pretty(key)}`).join(' · ')]],workflow?.artifact_checks||[]);
el('authoring-boundary').textContent=authoringChecks.length?'Reported static authoring observations for the included model scope. Unresolved, unsupported and stale checks remain visible. These observations do not prove native validity, business accuracy or deployment approval.':'Authoring evidence is not included for this scope. Ask the agent to recheck the retained code; no regeneration is needed for a checker-only update.';
table('authoring-checks',[
  ['Task',r=>r.task_id],['Mode',r=>pretty(r.mode)],['Reported status',r=>pretty(r.status)],
  ['Scope',r=>(r.model_ids||[]).join(', ')],
  ['Check counts',r=>Object.entries(r.counts||{}).map(([key,value])=>`${value} ${pretty(key)}`).join(' · ')],
  ['Open assumptions',r=>String(r.unresolved_assumptions??'Unknown')],
  ['Next action',r=>({stale:'Recheck the retained files.',failed:'Repair the affected findings, then recheck.',unsupported:'Validate unsupported constructs with the target-native tools.',not_run:'Supply missing evidence; retain provisional scope.',passed:'Continue independent native, data and access validation.'})[r.status]||'Ask the agent to inspect the missing evidence.']
],authoringChecks);
table('authoring-findings',[
  ['Task',r=>r.task_id],['Model',r=>r.model_id||'Task scope'],['Finding',r=>pretty(r.code)],['Status',r=>pretty(r.status)]
],authoringChecks.flatMap(row=>(row.findings||[]).map(f=>({...f,task_id:row.task_id}))));
card(el('validation-counts'),'Failures',cases.filter(c=>c.status==='fail').length,'Unexplained mismatches remain visible.');
card(el('validation-counts'),'Pending or skipped',cases.filter(c=>['pending','skipped'].includes(c.status)).length,'Missing checks cannot count as passing evidence.');
function validation(){const filter=el('validation-filter').value;table('validation-cases',[['Case',r=>r.label||r.id],['Scope',r=>pretty(r.scope)],['Reported status',r=>make('strong',pretty(r.status),r.status)],['Expected → observed',r=>data.audience==='reviewer'?'Values omitted from reviewer export':`${text(r.expected)} → ${text(r.actual)}`],['Evidence / interpretation',r=>`${r.evidence_id||'No evidence association'} · ${r.details||'No explanation supplied'}`]],cases.filter(c=>!filter||c.status===filter));}el('validation-filter').onchange=validation;validation();
el('audience').textContent=pretty(data.audience);
const chosen=new Set([...allFiles().map(f=>f.category),...(data.selected_categories||[])]);
for(const category of chosen){const label=make('label'),input=make('input');input.type='checkbox';input.checked=true;input.value=category;input.onchange=()=>{if(input.checked)chosen.add(category);else chosen.delete(category);updateExport();};label.append(input,make('span',pretty(category)));el('export-choices').append(label);const option=make('option',pretty(category));option.value=category;el('file-category').append(option);}
function selectedFiles(){return files.filter(f=>chosen.has(f.category));}
function updateExport(){const selected=selectedFiles(),ids=new Set(selected.map(f=>f.id)),missing=selected.flatMap(f=>(f.requires||[]).filter(id=>!ids.has(id)).map(id=>`${f.id} requires ${id}`));el('download-package').disabled=!(selected.length||(data.generated_deliverables||[]).some(f=>chosen.has(f.category)))||missing.length>0;el('export-dependencies').textContent=missing.length?'Include required deliverables: '+missing.join('; '):`${selected.length} of ${files.length} files selected. Unselected payloads are removed from the new download.`;if(data.migration_planning&&!(chosen.has('documentation')&&chosen.has('dictionary')))el('export-dependencies').textContent+=' Migration planning files require both documentation and dictionary; they will be omitted.';}updateExport();
if(!allFiles().length){empty('export-choices',eng.delivery?.status==='prepared'?'No files are embedded in this status page. Ask the agent to export the prepared artifacts for your selected audience and deliverables.':'No files are embedded in this status page. Ask the agent to generate and package the selected deliverables after discovery.');}
let activeFile=null;
function fileRole(file){const links=models.filter(m=>m.artifact_id===file.id||(m.artifact_ids||[]).includes(file.id));if(links.length)return 'Model implementation: '+links.map(m=>m.name||m.id).join(', ');if(review.handoff?.implementation_guide_artifact_id===file.id)return 'Implementation guide';if(review.handoff?.design_artifact_id===file.id)return 'Design document';return file.category==='implementation'?'Supporting / unmapped implementation file':pretty(file.category);}
function setFilePreview(show){
  el('file-preview').hidden=!show;el('file-code-block').hidden=show;
  const diagram=/\.svg$/i.test(activeFile?.path||'');
  el('file-preview-mode').textContent=show?'View source':diagram?'Preview diagram':'Preview dictionary';
  el('file-preview-fit').hidden=!show||!diagram;el('file-preview-actual').hidden=!show||!diagram;
}
function sizeFilePreview(fit){
  const target=el('file-preview'),graphic=target.querySelector('svg, img');if(!graphic)return;
  const viewBox=(graphic.getAttribute('viewBox')||'').trim().split(/[\s,]+/).map(Number);
  const width=Number(graphic.getAttribute('width'))||viewBox[2]||graphic.naturalWidth;
  const height=Number(graphic.getAttribute('height'))||viewBox[3]||graphic.naturalHeight;
  if(width&&height){const scale=fit?Math.max(.5,Math.min(1,(target.clientWidth-8)/width,((globalThis.innerHeight||900)*.65)/height)):1;graphic.style.width=width*scale+'px';graphic.style.height=height*scale+'px';}
  target.scrollLeft=0;target.scrollTop=0;
}
function showFile(file){
  activeFile=file;el('file-title').textContent=file.path;el('file-note').textContent=fileRole(file)+'. '+(file.description||'')+(file.category==='implementation'?' '+implementationGuidance():'');
  const body=bytes(file.base64),tooLarge=body.length>2*1024*1024,binary=/\.(xlsx|docx|zip|pdf)$/i.test(file.path),source=binary?'Download this document to open it in its compatible application. The file is preserved in its original format; text copy is unavailable.':tooLarge?'Preview limited to 2 MiB. Download the complete file to inspect it.':new TextDecoder().decode(body);
  el('file-content').textContent=source;el('copy-code').disabled=tooLarge||binary;el('download-file').disabled=false;
  const preview=clear('file-preview');el('file-preview-controls').hidden=true;setFilePreview(false);
  if(!tooLarge&&/\.svg$/i.test(file.path)){
    try{
      if(typeof PortalSvg==='undefined')throw new Error('SVG parser unavailable');
      const svg=PortalSvg.sanitize(source,'dma-file-preview');svg.setAttribute('role','img');svg.setAttribute('aria-label',file.description||file.path);preview.append(svg);
    }catch(error){
      // Only deterministic, inventory-checked projections may use the inert image fallback.
      if(file.origin==='review_projection'&&file.category==='diagrams'){
        const img=make('img');img.src='data:image/svg+xml;base64,'+file.base64;img.alt=file.description||file.path;img.onload=()=>sizeFilePreview(false);preview.append(img);
      }else el('file-note').textContent+=' Diagram preview unavailable; source is shown safely as text.';
    }
    if(preview.children.length){el('file-preview-controls').hidden=false;setFilePreview(true);}
  }
  if(!tooLarge&&file.origin==='review_projection'&&file.category==='dictionary'){
    const rows=models.flatMap(model=>(model.columns||[]).map(column=>({model,column})));
    table('file-preview',[['Table / grain',r=>{const cell=make('div');cell.append(make('strong',r.model.name||r.model.id),make('p',r.model.grain||'Not supplied'));return cell;}],['Column',r=>r.column.name],['Type / key',r=>`${r.column.type||'Unresolved'} · ${columnRole(r.model,r.column)}`],['Definition',r=>r.column.description||'Not supplied']],rows);
    el('file-preview-controls').hidden=false;setFilePreview(true);
  }
  document.querySelectorAll('#file-list button').forEach(b=>b.classList.toggle('active',b.dataset.file===file.id));
}
el('file-preview-mode').onclick=()=>setFilePreview(el('file-preview').hidden);
el('file-preview-fit').onclick=()=>sizeFilePreview(true);
el('file-preview-actual').onclick=()=>sizeFilePreview(false);
function fileList(){const q=el('file-search').value.toLowerCase(),cat=el('file-category').value,target=clear('file-list');const found=allFiles().filter(f=>(!cat||f.category===cat)&&(f.path+' '+f.description).toLowerCase().includes(q));found.slice(0,200).forEach(f=>{const b=make('button',f.path);b.type='button';b.dataset.file=f.id;b.onclick=()=>showFile(f);target.append(b);});if(found.length>200)target.append(make('p',`${found.length} matches. Narrow the search to view more.`,'muted'));if(!found.length)target.append(make('p','No matching files.','empty'));}el('file-search').oninput=fileList;el('file-category').onchange=fileList;
const implementationFiles=files.filter(f=>f.category==='implementation');
if(implementationFiles.length){const ids=new Set(models.flatMap(m=>[m.artifact_id,...(m.artifact_ids||[])]).filter(Boolean));el('file-category').value='implementation';showFile(implementationFiles.find(f=>ids.has(f.id))||implementationFiles[0]);}
fileList();
renderDeliverableIndex();
const sourceSummary=clear('input-source-summary');sourceSummary.append(make('h3','Input sources'),make('p','Source repositories are referenced, not cloned into this handoff. See the input-source index for supplied snapshots and gaps.'));
for(const root of data.input_roots||[])sourceSummary.append(make('p',root.id||'Primary source'));
const inputFiles=allFiles().filter(f=>/^(01_Input_Sources|02_Input_Context_Files)\//.test(f.path));
const inputIndex=clear('input-file-index');for(const file of inputFiles){const b=make('button',file.path,'secondary');b.type='button';b.onclick=()=>openArtifact(file.id);inputIndex.append(b);}if(!inputFiles.length)inputIndex.append(make('p','No input snapshots or context files are embedded in this page. Original inputs remain in the engagement.'));
const mappingFiles=allFiles().filter(f=>f.path.startsWith('05_Mappings/')&&!f.id.startsWith('generated:section:'));
const mappingIndex=clear('mapping-file-index');for(const file of mappingFiles){const b=make('button',file.path.split('/').slice(1).join('/'),'secondary');b.type='button';b.onclick=()=>openArtifact(file.id);mappingIndex.append(b);}
el('implementation-state').textContent=implementationFiles.length?`${implementationFiles.length} implementation files included. Review the selected code and its validation evidence before deployment.`:data.page_mode==='status'?'This is a status page with no embedded code. Ask the agent to package the registered engineering deliverables; if code is still pending, generate and register the requested candidates first.':data.audience==='reviewer'?'Implementation code is excluded from reviewer packages. Ask the agent for an engineering package to inspect generated code.':!data.selected_categories?.includes('implementation')?'Implementation was not selected for this export. Request an engineering package with implementation included if code is needed.':'No implementation files are included. The requested code is still pending or unavailable; this page does not establish completion.';
el('copy-code').onclick=()=>{setFilePreview(false);return copyText(el('file-content').textContent,el('file-content'),'File text copied.');};
el('download-file').onclick=()=>activeFile&&download(activeFile.path.split('/').pop(),bytes(activeFile.base64));
function renderDeliverableIndex(){
  if(data.package_layout_version===2){
    table('deliverable-index',[['Folder',r=>r.title],['Included files',r=>allFiles().filter(f=>f.path.startsWith(r.folder+'/')&&!f.id.startsWith('generated:section:')).length],['Open',r=>{const button=make('button','Browse','secondary');button.type='button';button.onclick=()=>{el('file-search').value=r.folder+'/';el('file-category').value='';fileList();location.hash='#implementation-code';};return button;}]],data.layout_sections||[]);return;
  }
  const categories=[...new Set([...(eng.delivery?.deliverables||[]),...(data.selected_categories||[]),...allFiles().map(f=>f.category)])];
  table('deliverable-index',[['Deliverable',r=>pretty(r.category)],['Included / location',r=>{const cell=make('div');const records=allFiles().filter(f=>f.category===r.category);if(records.length){for(const file of records){const button=make('button',file.path,'secondary');button.type='button';button.onclick=()=>openArtifact(file.id);cell.append(button);}return cell;}return (data.selected_categories||[]).includes(r.category)?'Selected; no standalone file included. Inspect the page or ask the agent to complete this deliverable.':'Not included in this export.';}]],categories.map(category=>({category})),10);
}
function simpleGeneratedPath(path,snapshot){
  if(snapshot.package_layout_version!==2)return path;
  if(path.startsWith('05_Migration/'))return '05_Mappings/Migration_Plan/'+path.slice(13);
  if(path.startsWith('01_Model/legacy-table-')||path==='01_Model/migration-review.md')return '05_Mappings/'+path.slice(9);
  return path.startsWith('01_Model/')?'03_Design_Documents/'+path.slice(9):path;
}
function simpleMarkdown(value){return String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\\','\\\\').replace(/([`*_[\]()!|])/g,'\\$1').replace(/\r\n|\r|\n/g,'<br>');}
async function finishSimpleGuides(snapshot,records,add){
  if(snapshot.package_layout_version!==2||!snapshot.selected_categories.includes('documentation'))return records;
  const files=[...(snapshot.files||[]),...records];
  for(const section of snapshot.layout_sections||[]){
    const included=files.filter(f=>f.path.startsWith(section.folder+'/')).sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);
    const lines=['# '+section.title,'',section.description,''];
    if(included.length){lines.push('## Included files','');for(const file of included){const relative=file.path.slice(section.folder.length+1),url=relative.split('/').map(p=>encodeURIComponent(p).replace(/[!'()*]/g,c=>'%'+c.charCodeAt(0).toString(16).toUpperCase())).join('/');lines.push('- ['+simpleMarkdown(relative)+']('+url+')');}}
    else lines.push('No files are included in this section yet.','This is an explicit gap or an unselected deliverable, not a completed stage.');
    if(section.id==='input_sources'){
      lines.push('','Source inventory is retained in the engagement. This package does not clone input repositories.');
      const fingerprint=snapshot.engagement?.source_fingerprint||{},digest=fingerprint.sha256||fingerprint.content_sha256;
      if(digest)lines.push('Source content fingerprint: `'+digest+'`.');
      for(const root of snapshot.input_roots||[])lines.push('- Registered source: '+simpleMarkdown(root.id||'primary')+'.');
    }
    await add('generated:section:'+section.id,section.folder+'/README.md','documentation',section.title+' index and inclusion status.',lines.join('\n')+'\n');
  }
  return records;
}
async function rebuildGenerated(snapshot){
  const models=snapshot.review?.models||[],relationships=snapshot.review?.relationships||[],chosen=new Set(snapshot.selected_categories||[]),records=[];
  if(snapshot.audience==='audit')return records;
  for(const file of snapshot.topic_exports||[]){if(chosen.has(file.category))records.push(structuredClone(file));}
  for(const file of snapshot.generated_deliverables||[]){if(file.id.startsWith('generated:source-lineage')&&chosen.has(file.category))records.push(structuredClone(file));}
  const encode=body=>btoa(Array.from(body,b=>String.fromCharCode(b)).join(''));
  const add=async(id,path,category,description,body,ids)=>{path=simpleGeneratedPath(path,snapshot);const bytes=new TextEncoder().encode(body);if(bytes.length>5*1024*1024)throw new Error('Generated file exceeds size limit; ask the agent to partition it.');const record={id,path,category,description,requires:[],origin:'review_projection',sha256:await sha256(bytes),size:bytes.length,base64:encode(bytes)};if(ids)record.diagram_model_ids=ids;records.push(record);};
  if(chosen.has('dictionary')&&snapshot.staging_ports)await add('generated:staging-ports',(snapshot.package_layout_version===2?'05_Mappings/':'01_Model/')+'STAGING_PORT_REGISTER.csv','dictionary','Scoped staging reuse and port decisions; candidate, unresolved and stale status remain explicit.',snapshot.staging_ports.summary_csv);
  if(chosen.has('documentation')&&snapshot.migration_review){
    await add('generated:migration-review','01_Model/migration-review.md','documentation','Scoped business rules, shared model proposals, source coverage and parity evidence.',snapshot.migration_review.summary_markdown);
  }
  if(chosen.has('documentation')&&snapshot.legacy_alignment?.domains?.some(domain=>domain.comparison_requested)){
    await add('generated:legacy-alignment-csv','01_Model/legacy-table-alignment.csv','documentation','Complete scoped comparison of existing tables and proposed models.',snapshot.legacy_alignment.summary_csv);
    await add('generated:legacy-alignment-markdown','01_Model/legacy-table-alignment.md','documentation','Complete scoped comparison, coverage and review evidence.',snapshot.legacy_alignment.summary_markdown);
  }
  if(chosen.has('documentation')&&chosen.has('dictionary')&&(snapshot.migration_planning||snapshot.workflow?.governance)){
    // Preserve the already generated, hash-checked portable Office files. Browser
    // export does not regenerate binary documents or create cloud documents.
    for(const file of snapshot.generated_deliverables||[]){
      if((file.path.startsWith('05_Migration/')||file.path.startsWith('05_Mappings/Migration_Plan/'))&&file.category==='documentation')records.push(structuredClone(file));
    }
  }
  if(!models.length)return finishSimpleGuides(snapshot,records,add);
  if(chosen.has('diagrams')){
    for(const [i,view]of(snapshot.diagrams||[]).entries()){const suffix=String(i+1).padStart(3,'0');await add('generated:erd:'+suffix,(snapshot.diagram_view_mode==='pipelines'?view.export_path:'01_Model/ERD/model-'+suffix+'.svg'),'diagrams','Model view '+(i+1)+'; part of the complete included table inventory.',new TextDecoder().decode(bytes(view.base64)),view.model_ids);}
    await add('generated:erd-source','01_Model/ERD/model-source.json','diagrams','Editable model source with every included table and declared connection.',JSON.stringify({schema_version:1,kind:'portable_model_source',qualification:'Editable presentation source; not implementation or approval.',models,relationships,...(snapshot.review?.domain_proposals?.length?{domain_proposals:snapshot.review.domain_proposals,relationship_ledger:modelGraph(models,relationships,null,snapshot.review.domain_proposals).edges.filter(e=>e.record_origin)}:{})},null,snapshot.package_layout_version===2?undefined:2)+'\n');
  }
  if(chosen.has('dictionary')){
    // A category-only subset never changes the selected dictionary. Preserve the
    // already checked projection bytes, including legacy scalar formatting.
    const dictionaryIds=['generated:dictionary-csv','generated:dictionary-markdown'];
    const dictionary=(data.generated_deliverables||[]).filter(f=>dictionaryIds.includes(f.id));
    if(dictionary.some(f=>f.category!=='dictionary')||new Set(dictionary.map(f=>f.id)).size!==2)throw new Error('The portable dictionary inventory is incomplete. Ask the agent to repackage.');
    if(dictionary.length!==2)throw new Error('The portable dictionary inventory is incomplete. Ask the agent to repackage.');
    records.push(...structuredClone(dictionary));
  }
  return finishSimpleGuides(snapshot,records,add);
}
function subsetReadme(snapshot){return [snapshot.checkpoint?'# Checkpoint — work is incomplete':'# Open START_HERE.html','',snapshot.checkpoint?'Missing selected categories: '+(snapshot.checkpoint.missing_categories.join(', ')||'none; work remains incomplete')+'.':'', 'Extract the entire ZIP, then open START_HERE.html in a browser. The review works offline.', '', snapshot.migration_planning_omitted||'', 'Data model: inspect tables, keys and joins. Code & files: inspect and download selected deliverables. Validation: review pending and reported checks.', '', 'Candidate review only. File integrity is not native execution, business acceptance or deployment authorization. This browser subset requires a fresh content scan and disclosure review before sharing.', '', 'Included files:',...[(snapshot.files||[]),(snapshot.generated_deliverables||[])].flat().map(f=>'- '+f.path),''].join('\n');}

function implementationGuidance(){
  const target=eng.target||{};
  if(target.framework==='dbt')return `dbt → ${pretty(target.warehouse)}. Integrate these files in the selected dbt project; review its setup guide and dependencies before running. dbt model SQL is not intended for a warehouse SQL editor.`;
  if(target.framework==='coalesce')return `Coalesce → ${pretty(target.warehouse)}. Follow the native project import and storage-mapping guide. SQL files alone are not an importable Coalesce project.`;
  if(target.framework==='native_sql')return `${pretty(target.warehouse)} SQL. Follow the selected implementation guide in dependency order; confirm namespace and environment before execution.`;
  return 'Target instructions are unresolved. Ask the agent to confirm the framework and warehouse before execution.';
}
function reviewStart(){
  el('review-now').textContent=models.length?`${models.length} tables${implementationFiles.length?` · ${implementationFiles.length} implementation files`:''}. Inspect grain, keys and joins.`:'Review the selected documents and discovery questions. A model inventory is not included yet.';
  const failures=handoff.blockers.failed,decisionsOpen=handoff.blockers.decisions;
  const material=handoff.evidenceGaps.filter(g=>['fail','failed','stale','unsupported'].includes(g.status)).map(g=>`${g.label}: ${pretty(g.status)}`).join('; ');
  el('review-pending').textContent=`${failures?failures+' failed checks. ':''}${material?material+'. ':''}${!assurance.migration_scope?'Scope unresolved. ':''}${decisionsOpen?decisionsOpen+' open decisions. ':''}Native execution and business acceptance are not established by this offline review.`;
  el('review-next').textContent=decisionsOpen?'Review the proposed tables, then answer the outstanding decisions or request corrections.':models.length?'Check grain, keys and joins; return any corrections. Approval and deployment are separate steps.':'Answer the discovery questions in Engagement overview so the agent can prepare the model.';
}
reviewStart();
for(const model of models){const option=make('option',model.name||model.id);option.value=model.id;el('feedback-model').append(option);}
el('feedback-kind').value='change_request';
const feedbackBinding=eng.context_sha256&&eng.engagement_id;
el('save-feedback').disabled=!feedbackBinding;
el('feedback-binding').textContent=feedbackBinding?`Feedback refers to this exact page snapshot · engagement revision ${eng.revision}${workflow?.design_revision?' · design revision '+workflow.design_revision:''}. The agent must check freshness before applying it.`:'This legacy page has no current context binding. Ask the agent to refresh the review before recording feedback.';
el('save-feedback').onclick=async()=>{try{
  if(!feedbackBinding||!crypto.subtle)throw new Error('Cannot bind feedback in this browser. Ask the agent to refresh the review and record your correction.');
  const message=el('feedback-text').value.trim(),modelId=el('feedback-model').value,kind=el('feedback-kind').value;
  if(!message||message.length>10000)throw new Error('Describe the correction or question in 1–10,000 characters.');
  if(modelId&&!models.some(m=>m.id===modelId)||!['change_request','question'].includes(kind))throw new Error('Select an included table and a feedback type.');
  const response={schema_version:1,kind:'model_review_feedback',request_only:true,engagement_id:eng.engagement_id,context_sha256:eng.context_sha256,page_data_sha256:await sha256(new TextEncoder().encode(el('delivery-data').textContent)),comments:[{model_id:modelId||null,type:kind,text:message}]};
  download('model-review-feedback.json',JSON.stringify(response,null,2),'application/json');el('feedback-result').textContent='Downloaded model-review-feedback.json. Return it to the agent with this package: “Check this feedback against the current review and apply the requested corrections.” Nothing has been approved, submitted or deployed.';
}catch(error){notice(error.message);}};

// Stored ZIP format keeps offline exports independent of CDNs and native tools.
function crc32(array){let crc=0xffffffff;for(const byte of array){crc^=byte;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return(crc^0xffffffff)>>>0;}
function zip(entries){const chunks=[],central=[];let offset=0,size=0;const enc=new TextEncoder();for(const [path,body]of entries){const name=enc.encode(path),header=new Uint8Array(30+name.length),v=new DataView(header.buffer),crc=crc32(body);v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(6,0x800,true);v.setUint16(12,33,true);v.setUint32(14,crc,true);v.setUint32(18,body.length,true);v.setUint32(22,body.length,true);v.setUint16(26,name.length,true);header.set(name,30);chunks.push(header,body);const c=new Uint8Array(46+name.length),cv=new DataView(c.buffer);cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);cv.setUint16(8,0x800,true);cv.setUint16(14,33,true);cv.setUint32(16,crc,true);cv.setUint32(20,body.length,true);cv.setUint32(24,body.length,true);cv.setUint16(28,name.length,true);cv.setUint32(42,offset,true);c.set(name,46);central.push(c);offset+=header.length+body.length;size+=c.length;}const end=new Uint8Array(22),ev=new DataView(end.buffer);ev.setUint32(0,0x06054b50,true);ev.setUint16(8,entries.length,true);ev.setUint16(10,entries.length,true);ev.setUint32(12,size,true);ev.setUint32(16,offset,true);return new Blob([...chunks,...central,end],{type:'application/zip'});}
async function sha256(body){const hash=await crypto.subtle.digest('SHA-256',body);return Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,'0')).join('');}
el('download-package').onclick=async()=>{
  try{
    if(!crypto.subtle)throw new Error('This browser cannot check file hashes here. Use the original package or ask the agent to export your selected categories.');
    const selected=selectedFiles(),entries=await checkedSubsetFiles(files,selected,chosen,true),next=structuredClone(data);
    await checkedSubsetFiles(data.generated_deliverables||[],(data.generated_deliverables||[]).filter(f=>chosen.has(f.category)),chosen,true);
    next.files=selected;
    next.page_mode='package';next.selected_categories=[...chosen].sort();next.file_count=selected.length;
    next.projection={...(next.projection||{}),selected_artifact_count:selected.length,excluded_artifact_count:(data.projection?.excluded_artifact_count||0)+files.length-selected.length};
    next.engagement.delivery_assurance=portableAssurance(eng);
    next.export_review={origin:'browser_subset',status:'candidate',content_scan:'not_run_in_browser',disclosure_policy:'not_revalidated_in_browser',acceptance_ready:false,deployment_authorized:false};
    trimMetadataEvidence(next,selected);
    trimOmniEvidence(next,selected);
    trimHandoff(next,selected);
    trimWorkflowDetails(next,chosen);
    if(next.audience==='audit'||!['documentation','diagrams','dictionary'].some(key=>chosen.has(key)))delete next.workflow?.review_assurance;
    if(next.deployment){
      const selectedIds=new Set(selected.map(f=>f.id));
      if(next.deployment.plan&&!selectedIds.has(next.deployment.plan.evidence_artifact_id)){
        delete next.deployment.plan;
        next.deployment.plan_omitted='Plan details are outside this export; request the selected deployment evidence from the agent.';
      }
      next.deployment.receipts=(next.deployment.receipts||[]).filter(r=>selectedIds.has(r.evidence_artifact_id));
    }
    if(!chosen.has('diagrams')){delete next.diagram;delete next.diagrams;delete next.warehouse_diagrams;}
    if(next.diagram_coverage){const ids=new Set(selected.map(f=>f.id));next.diagram_coverage.registered=next.diagram_coverage.registered.filter(r=>ids.has(r.artifact_id));if(!chosen.has('diagrams'))next.diagram_coverage.generated={status:'not_included',model_count:0,page_count:0};}
    if(next.review.quality_checks){
      const selectedIds=new Set(selected.map(f=>f.id));
      next.review.quality_checks=next.review.quality_checks.map(q=>selectedIds.has(q.evidence_artifact_id)?q:qualityOmitted(q.id));
    }
    if(!chosen.has('validation'))delete next.review.validation;
    if(next.workflow&&(!chosen.has('validation')||!['documentation','diagrams','dictionary'].some(x=>chosen.has(x)))){delete next.workflow.authoring_checks;delete next.workflow.artifact_checks;}
    if(!['documentation','diagrams','dictionary'].some(x=>chosen.has(x))){delete next.review.models;delete next.review.relationships;delete next.review.domain_proposals;}
    else if(!chosen.has('dictionary')){
      (next.review.models||[]).forEach(m=>delete m.columns);
      // Rebuild auxiliary projections from the reduced dictionary; registered files stay byte-identical.
      const reducedGraph=modelGraph(next.review.models||[],next.review.relationships||[],null,next.review.domain_proposals||[]);
      for(const view of [...(next.diagrams||[]),...(next.warehouse_diagrams||[])]){const ids=new Set(view.model_ids),rows=reducedGraph.nodes.filter(m=>ids.has(m.id)),edges=reducedGraph.edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
        if(next.diagram_view_mode==='pipelines'){
          if(!view.without_dictionary_base64)throw new Error('Pipeline subset is unavailable; ask the agent to repackage.');
          view.base64=view.without_dictionary_base64;
        }else{const svg=filteredModelSvg(rows,edges.slice(0,120),new Set(),Math.max(0,edges.length-120),false,true);
          view.base64=btoa(Array.from(new TextEncoder().encode(svg),byte=>String.fromCharCode(byte)).join(''));}

      }
    }
    if(next.diagram_coverage&&chosen.has('diagrams')){
      const seen=new Set((next.diagrams||[]).flatMap(view=>view.model_ids)),modelIds=new Set((next.review.models||[]).map(model=>model.id));
      const references=[...seen].filter(id=>!modelIds.has(id)).length;
      next.diagram_coverage.generated={status:next.diagrams?.length?'verified':'not_included',model_count:seen.size-references,page_count:(next.diagrams||[]).length,...(references?{reference_count:references}:{})};
    }
    if([1,2].includes(data.package_layout_version)){
      next.generated_deliverables=await rebuildGenerated(next);
      updateCheckpointDeficits(next);
      const generated=await checkedSubsetFiles(next.generated_deliverables,next.generated_deliverables,chosen,true);entries.push(...generated);
      entries.push(['README.md',new TextEncoder().encode(subsetReadme(next))]);
    }
    const names=entries.map(([name])=>name.toLowerCase());if(new Set(names).size!==names.length||entries.length>500||entries.reduce((total,[,body])=>total+body.length,0)>50*1024*1024)throw new Error('Package inventory collision or size limit; ask the agent to partition this delivery.');
    const encoded=JSON.stringify(next).replaceAll('<','\\u003c').replaceAll('>','\\u003e').replaceAll('&','\\u0026');
    const shell=originalShell.replace(/(<script id="delivery-data" type="application\/json">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+encoded+b);
    entries.push(['START_HERE.html',new TextEncoder().encode(shell)]);
    const manifest=await browserSubsetManifest(eng,data.audience,chosen,entries,next);
    entries.push(['DELIVERY_MANIFEST.json',new TextEncoder().encode(JSON.stringify(manifest,null,2))]);
    download('model-delivery-'+data.audience+'.zip',zip(entries),'application/zip');
    notice('Candidate subset created with checked file hashes. No new content scan or disclosure approval was performed; return this exact ZIP to the agent before sharing.');
  }catch(error){notice(error.message);}
};

// Comparison filters only affect presentation; full scoped evidence is kept for exports.
const legacyAlignment=data.audience!=='audit'&&(data.page_mode==='status'||['documentation','diagrams','dictionary'].some(key=>data.selected_categories?.includes(key)))&&data.legacy_alignment?.domains?.some(domain=>domain.comparison_requested)?data.legacy_alignment:null;
function alignmentLabel(value){const label=pretty(value);return label.charAt(0).toUpperCase()+label.slice(1);}
function alignmentCoverageLine(kind,counts){
  const label=alignmentLabel(kind)+': ',valid=value=>Number.isSafeInteger(value)&&value>=0;
  if(!counts||!valid(counts.total))return label+'Not assessed';
  if(counts.total===0)return label+'No items supplied';
  if(!['mapped','unmatched','unsupported'].every(key=>valid(counts[key])))return label+'Not assessed';
  const details=[`${counts.mapped} of ${counts.total} mapped`];
  for(const [key,name]of [['unmatched','unmatched'],['unsupported','unsupported'],['excluded','explicitly excluded']])if(valid(counts[key])&&counts[key]>0)details.push(`${counts[key]} ${name}`);
  return label+details.join('; ');
}
function alignmentChanged(row){return ['split','merge','many_to_many'].includes(row.relationship)||row.behavior==='correct';}
function alignmentUnresolved(row){if(row.review_status==='accepted'&&row.freshness==='current'&&['retire_candidate','out_of_scope'].includes(row.disposition))return false;return ['unmatched','unsupported'].includes(row.status)||row.behavior==='undecided'||row.review_status!=='accepted'||row.freshness!=='current';}
function alignmentMatches(row,filters){
  return(!filters.domain||row.domain_id===filters.domain)&&(!filters.table||row.legacy_sources.some(source=>JSON.stringify([row.domain_id,source.table_id])===filters.table))&&(!filters.model||row.targets.some(target=>target.model_id===filters.model))&&(!filters.asset||row.model_ids.some(id=>models.find(model=>model.id===id)?.asset_ids?.includes(filters.asset)))&&(!filters.changed||alignmentChanged(row))&&(!filters.unresolved||alignmentUnresolved(row));
}
function alignmentSource(row){return row.legacy_sources.map(source=>(source.table_name||source.table_id)+(source.kind!=='table'?' · '+(source.label||source.field_id||source.kind):'')).join('; ')||'No existing source supplied';}
function alignmentModelLinks(id){
  const cell=make('div'),model=models.find(item=>item.id===id);cell.append(make('strong',id));if(!model)return cell;
  const actions=make('div',undefined,'small-actions'),inspect=make('button','Inspect model','secondary');inspect.type='button';inspect.onclick=()=>{pendingInspectorModel=id;if(location.hash==='#architecture')navigate();else location.hash='#architecture';};actions.append(inspect);
  const ids=[model.artifact_id,...(model.artifact_ids||[])],code=files.filter(file=>file.category==='implementation'&&ids.includes(file.id));
  for(const [index,file]of code.entries()){const button=make('button','Open code'+(code.length>1?' '+(index+1):''),'secondary');button.type='button';button.setAttribute('title',file.path);button.setAttribute('aria-label','Open code: '+file.path);button.onclick=()=>openArtifact(file.id);actions.append(button);}
  const related=decisions.filter(decision=>decision.model_ids?.includes(id));if(related.length){const button=make('button',`Review ${related.length} related decision${related.length===1?'':'s'}`,'secondary');button.type='button';button.onclick=()=>{location.hash='#changes';navigate();el('decisions').scrollIntoView({block:'start'});};actions.append(button);}
  cell.append(actions);return cell;
}
function alignmentTargets(row){const cell=make('div');for(const target of row.targets){cell.append(alignmentModelLinks(target.model_id),make('small',pretty(target.kind)+(target.field?': '+target.field:'')+(target.kind==='semantic'?' · Proposed placement; native existence unverified':'')));}if(!row.targets.length)cell.append(make('span','No target mapping supplied'));return cell;}
function alignmentFilters(){return{table:el('alignment-table').value,model:el('alignment-model').value,domain:el('alignment-domain').value,asset:el('alignment-asset').value,changed:el('alignment-changed').checked,unresolved:el('alignment-unresolved').checked};}
function renderAlignment(){
  if(!legacyAlignment)return;
  const filters=alignmentFilters(),all=legacyAlignment.rows||[],rows=all.filter(row=>alignmentMatches(row,filters));
  el('alignment-count').textContent=`${rows.length} of ${all.length} comparison rows shown · ${rows.filter(alignmentChanged).length} structural changes / corrections · ${rows.filter(alignmentUnresolved).length} unresolved. Coverage describes supplied baseline evidence, not parity.`;
  table('alignment-forward',[['Existing table / item',row=>alignmentSource(row)],['Proposed models',alignmentTargets],['Change / status',row=>[...new Set([alignmentLabel(row.relationship),alignmentLabel(row.disposition||'unresolved')]),alignmentLabel(row.status),'Behavior: '+alignmentLabel(row.behavior),'Human review: '+alignmentLabel(row.review_status),'Evidence: '+alignmentLabel(row.freshness)].join(' · ')],['Explanation / evidence',row=>{const cell=make('div');cell.append(make('p',row.rationale||'No explanation supplied.'),make('small','Basis: '+alignmentLabel(row.basis)),make('small','Evidence categories: '+((row.evidence_labels||[]).join(', ')||'None supplied')),make('small','Domain: '+row.domain_id));return cell;}]],rows);
  if(!rows.length)empty('alignment-forward',all.length?'No comparison rows match these filters. Clear filters to review the included baseline.':'No baseline comparison rows are available. Supply or refresh the requested baseline with the agent.');
  const targetIds=new Set(rows.flatMap(row=>row.targets.map(target=>target.model_id)));
  if(!filters.table&&!filters.changed&&!filters.unresolved)for(const domain of legacyAlignment.domains.filter(domain=>domain.comparison_requested&&(!filters.domain||domain.domain_id===filters.domain)))for(const id of domain.model_ids||[])if((!filters.model||id===filters.model)&&(!filters.asset||models.find(model=>model.id===id)?.asset_ids?.includes(filters.asset)))targetIds.add(id);
  table('alignment-reverse',[['Proposed model',row=>alignmentModelLinks(row.id)],['Existing sources / explanation',row=>row.rows.length?row.rows.map(item=>alignmentSource(item)+' · '+(item.rationale||'No explanation supplied.')).join('\n'):'No legacy association supplied. This is not evidence of a new model or parity.']],Array.from(targetIds).sort().map(id=>({id,rows:rows.filter(row=>row.targets.some(target=>target.model_id===id))})));
}
if(legacyAlignment){
  el('replacement-title').textContent='Compare with existing tables';el('replacement-nav-label').textContent='Compare with existing tables';el('replacement-description').textContent='Inspect supplied existing-table mappings in both directions. Human review states are recorded evidence; no action on this page approves or retires a table.';el('replacement-table').hidden=true;el('alignment-screen').hidden=false;
  el('alignment-qualification').textContent=legacyAlignment.qualification||'Supplied mappings only. Behavioral parity, native validation and acceptance remain separate.';
  const option=(control,value,label)=>{const node=make('option',label);node.value=value;el(control).append(node);},seenTables=new Set(),seenModels=new Set(),seenAssets=new Set();
  for(const domain of legacyAlignment.domains.filter(item=>item.comparison_requested)){
    option('alignment-domain',domain.domain_id,domain.domain_id);
    for(const source of [...(domain.tables||[]).map(row=>({table_id:row.id,table_name:row.name})),...(legacyAlignment.rows||[]).filter(row=>row.domain_id===domain.domain_id).flatMap(row=>row.legacy_sources)]){const key=JSON.stringify([domain.domain_id,source.table_id]);if(!seenTables.has(key)){seenTables.add(key);option('alignment-table',key,source.table_name+' · '+domain.domain_id);}}
    for(const id of domain.model_ids||[])seenModels.add(id);
  }
  for(const row of legacyAlignment.rows||[])for(const target of row.targets)seenModels.add(target.model_id);
  for(const id of [...seenModels].sort()){option('alignment-model',id,id);for(const asset of models.find(model=>model.id===id)?.asset_ids||[])seenAssets.add(asset);}
  for(const id of [...seenAssets].sort())option('alignment-asset',id,(review.assets||[]).find(asset=>asset.id===id)?.name||id);
  table('alignment-coverage',[['Domain',domain=>domain.domain_id],['Baseline / freshness',domain=>`${alignmentLabel(domain.baseline_status)} · ${alignmentLabel(domain.freshness)} · ${alignmentLabel(domain.alignment_status)}${domain.omitted_details?' · Some details omitted from this scope':''}`],['Supplied coverage',domain=>{const cell=make('div',undefined,'alignment-coverage-lines');for(const kind of ['tables','columns','rules'])cell.append(make('div',alignmentCoverageLine(kind,domain.coverage?.[kind])));return cell;}]],legacyAlignment.domains.filter(domain=>domain.comparison_requested));
  for(const id of ['alignment-table','alignment-model','alignment-domain','alignment-asset','alignment-changed','alignment-unresolved'])el(id).onchange=renderAlignment;
  el('alignment-print-summary').textContent=(legacyAlignment.summary_markdown||'Complete comparison summary unavailable.').replace(/^#{1,3} /gm,'').replace(/\\([\\`*_\[\]()!|])/g,'$1').replaceAll('<br>','\n').replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');
  el('alignment-csv').onclick=()=>download('legacy-table-alignment.csv',legacyAlignment.summary_csv,'text/csv;charset=utf-8');el('alignment-markdown').onclick=()=>download('legacy-table-alignment.md',legacyAlignment.summary_markdown,'text/markdown;charset=utf-8');
  el('alignment-print').onclick=()=>{if(typeof globalThis.print!=='function')return notice('Use the complete comparison Markdown deliverable to print this review.');document.body.classList.toggle('alignment-print',true);try{globalThis.print();}catch(error){document.body.classList.toggle('alignment-print',false);notice('Printing is unavailable here. Use the complete comparison Markdown deliverable.');}};
  renderAlignment();
}
addEventListener('afterprint',()=>document.body.classList.toggle('alignment-print',false));

function renderMigrationPlanning(){
  if(!migrationPlanning)return;
  const selected=el('migration-plan-domain').value,query=el('migration-plan-search').value.toLowerCase();
  const domains=(migrationPlanning.domains||[]).filter(d=>!selected||d.domain_id===selected);
  const match=row=>!query||JSON.stringify(row).toLowerCase().includes(query);
  const rows=key=>domains.flatMap(d=>(d[key]||[]).map(row=>({...row,domain_id:d.domain_id}))).filter(match);
  const consumers=rows('consumers'),items=rows('work_items');
  const cards=clear('migration-plan-cards');
  card(cards,'Included domains',String(domains.length),'Planning follows the included review scope.');
  card(cards,'Consumer routes',String(consumers.length),'Proposed connections are not verified dashboard behavior.');
  card(cards,'Work items',String(items.length),'Reviewable templates; no live tickets created.');
  const missing=domains.reduce((n,d)=>n+(d.missing_consumers||[]).length,0);
  el('migration-plan-status').textContent=domains.map(d=>`${d.domain_id}: ${pretty(d.freshness)} · ${d.plan_sha256?'plan recorded':'plan not recorded'}`).join(' | ')+(missing?` · ${missing} known consumers still need mapping.`:'');
  table('migration-plan-consumers',[
    ['Dashboard / chart',r=>`${r.label||r.id} · ${r.domain_id}`],
    ['Previously used',(r)=>(r.legacy_table_ids||[]).join(', ')||'Historical connection unknown'],
    ['Proposed destination',r=>[...(r.model_ids||[]),...(r.topic_ids||[])].join(', ')||'Destination unresolved'],
    ['Disposition / evidence',r=>`${pretty(r.disposition)} · ${pretty(r.status)}`]],consumers);
  table('migration-plan-items',[
    ['Work item',r=>`${r.id} · ${r.title}`],['Outcome',r=>r.outcome],
    ['Depends on',r=>(r.dependencies||[]).join(', ')||'None recorded'],
    ['Owner / effort',r=>`${r.owner||'Unassigned'} · ${r.effort?.complexity||r.effort?.category||'Unassessed'}`],
    ['Acceptance criteria',r=>(r.acceptance_criteria||[]).map(a=>a.expected).join('\n')]],items);
  table('migration-plan-waves',[['Wave',r=>r.title],['Work items',r=>(r.item_ids||[]).join(', ')],['After',r=>(r.depends_on||[]).join(', ')||'No prerequisite wave recorded']],rows('waves'));
  table('migration-plan-questions',[['Domain / ID',r=>`${r.domain_id} · ${r.id}`],['Decision or question',r=>r.text]],[...rows('decisions'),...rows('questions'),...domains.flatMap(d=>(d.missing_consumers||[]).map(c=>({domain_id:d.domain_id,id:c.id,text:'Map the missing consumer: '+(c.label||c.id)})))]);
  const narrative=clear('migration-plan-narrative');
  for(const d of domains){narrative.append(make('h3',d.domain_id));if(d.narrative)narrative.append(make('p',d.narrative,'planning-narrative'));for(const warning of d.warnings||[])narrative.append(make('p',warning,'scope-note'));}
  const links=clear('migration-plan-files'),exports=allFiles().filter(f=>(f.path.startsWith('05_Migration/')||f.path.startsWith('05_Mappings/Migration_Plan/')));
  for(const file of exports){const button=make('button',file.path.split('/').slice(-2).join(' / '),'secondary');button.type='button';button.title=file.path;button.onclick=()=>download(file.path.split('/').pop(),bytes(file.base64));links.append(button);}
  el('migration-plan-files-note').textContent=exports.length?'Download the inventory first, then the plan and selected ticket import. Google content files require native host creation; they are not cloud documents.':'No planning files are embedded in this page. Ask the agent to finalize the selected documentation, or complete the planning record first.';
}
if(migrationPlanning){
  el('migration-plan-boundary').textContent=migrationPlanning.qualification||'Planning evidence only. Mapping, parity, approval and deployment remain separate.';
  for(const d of migrationPlanning.domains||[]){const option=make('option',d.domain_id);option.value=d.domain_id;el('migration-plan-domain').append(option);}
  el('migration-plan-domain').onchange=renderMigrationPlanning;el('migration-plan-search').oninput=renderMigrationPlanning;renderMigrationPlanning();
}

// Real layout is checked only when the page is opened; a stub DOM cannot establish geometry.
function assertPortalLayout(){
  const sidebar=document.querySelector?.('.sidebar');if(!sidebar?.getBoundingClientRect||typeof getComputedStyle!=='function')return;
  const fixed=getComputedStyle(sidebar).position==='fixed',edge=sidebar.getBoundingClientRect().right;
  for(const section of document.querySelectorAll('.review-section')){if(!section.getClientRects().length)continue;const rect=section.getBoundingClientRect();if(fixed&&rect.left<edge-1)throw new Error('Review layout error: '+section.id+' overlaps the fixed sidebar.');}
}
function checkLayout(){try{assertPortalLayout();}catch(error){notice(error.message);}}
addEventListener('resize',checkLayout);checkLayout();
})();
