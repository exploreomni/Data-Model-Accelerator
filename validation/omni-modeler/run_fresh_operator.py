#!/usr/bin/env python3
"""Two independently authored synthetic onboarding exercises. Offline only.

This harness calls real DMA APIs. Candidate drafting and callback are an inline
simulation by one operator; expected/result rows are NOT independent QA proof.
No warehouse, Omni tenant, credentials, network, approval, or deployment is used.
"""
import sys
sys.dont_write_bytecode = True
import argparse, copy, csv, hashlib, io, json, os, platform, subprocess, time, zipfile
from datetime import datetime, timezone
from pathlib import Path

_bootstrap = argparse.ArgumentParser(add_help=False)
_bootstrap.add_argument('--repo', type=Path, required=True)
_boot_args, _ = _bootstrap.parse_known_args()
REPO = _boot_args.repo.resolve()
if not (REPO / 'skills/data-model-accelerator/scripts/omni_modeler.py').is_file():
    raise SystemExit('Selected --repo does not contain the required Omni Modeler scripts')
SCRIPTS = REPO / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import duckdb, yaml, sqlglot
import guided_workflow as flow
import delivery_portal as portal
import omni_modeler as modeler
import omni_inventory as inventory
import omni_contract as contract
import omni_query_views as qv
import omni_lifecycle as lifecycle
import omni_handoff as handoff
import omni_knowledge as knowledge
import privacy_contract as privacy
import verify_catalogue

HERE = Path(__file__).resolve().parent
H = contract.canonical_hash
def sha(data): return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()
def body(obj): return json.dumps(obj, indent=2, sort_keys=True) + '\n'
def write(root, path, value):
    dest = root / path; dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(value if isinstance(value, bytes) else value.encode())
    return dest
def js(root, path, value): return write(root, path, body(value))
def yml(value): return yaml.safe_dump(value, sort_keys=False)
def disclosure():
    evidence = [{'reference':'independently-authored-synthetic-exercise-no-human-approval', 'sha256':H('synthetic-public-metadata-only')}]
    c = privacy.new_classification('PUBLIC')
    c.update(categories=[], categories_known=True, review_status='approved', review_reference='synthetic-fixture-declaration-only', evidence=evidence,
        lineage={'status':'complete','upstream_ids':[],'transformation':'source'}, handling={d:'allow' for d in privacy.DESTINATIONS})
    p = privacy.default_policy()
    p.update(policy_id='fresh-operator-synthetic-policy',review_status='approved',review_reference='synthetic-fixture-declaration-only',evidence=evidence,
        destinations={d:{'allowed_sensitivities':['PUBLIC'],'allowed_categories':[]} for d in privacy.DESTINATIONS},
        host_boundary={'mode':'presanitized_only','evidence_reference':'synthetic-local-only-not-host-proof'})
    return c,p

def catalogue(root, warehouse, tables):
    # All metadata and rows authored together here. No native observations claimed.
    catname = 'SYNTH_WORKSHOP' if warehouse == 'snowflake' else 'synthetic-workshop'
    schemas = sorted(set(t['schema'] for t in tables))
    cat = {'schema_version':1,'kind':'warehouse_raw_catalogue','provider':warehouse,'origin':'synthetic',
        'captured_at':datetime.now(timezone.utc).isoformat(), 'context':{'platform_instance':'local-simulation', 'principal':'no-native-principal',
        'scope':[{'scope_id':s,'catalog':catname,'schema':s,'location':'local-simulation'} for s in schemas]},
        'coverage':{'status':'complete_for_visible_scope','gaps':[]},'extractions':[],'objects':[]}
    for s in schemas:
        scoped=[t for t in tables if t['schema']==s]
        for component in ('objects','columns'):
            export = [{'name':t['name'], 'columns':t['columns'], 'status':t['status']} for t in scoped]
            path=js(root,'exports/'+s+'-'+component+'.json',{'origin':'synthetic','records':export})
            cat['extractions'].append({'extraction_id':s+'-'+component,'scope_id':s,'component':component,'status':'complete',
                'artifact_path':str(path.relative_to(root)),'sha256':sha(path.read_bytes()),'query_id':None,'pagination_complete':True})
        for t in scoped:
            cat['objects'].append({'object_id':s+'.'+t['name'],'scope_id':s,'identity':{'catalog':catname,'schema':s,'name':t['name']},
                'object_type':'TABLE','columns':[{'path':[n],'data_type':typ,'nullable':None} for n,typ in t['columns'].items()],
                'metadata_status':{k:'unknown' for k in ('comments','relationships','ownership','security','replication','statistics')},
                'evidence':[{'extraction_id':s+'-'+c,'locator':t['name']} for c in ('objects','columns')], 'simulation_status':t['status']})
    cp=js(root,'catalogue.json',cat)
    return cp,catname

def make_context(catpath, catname, warehouse, bindings):
    return {'schema_version':1,'kind':'omni_model_context','warehouse':warehouse,'environment':'development',
        'catalogue_sha256':sha(catpath.read_bytes()),'bindings':{view:{'namespace':(
            {'database':catname,'schema':s,'table':t} if warehouse=='snowflake' else {'project':catname,'dataset':s,'table':t}),
            'columns':cols,'evidence_sha256':sha(catpath.read_bytes())} for view,s,t,cols in bindings},
        'inherited_views':{},'default_catalog':None,'user_attributes':[],'access_grants':[]}

def start(root, source, catpath, warehouse, kind):
    answers={'engagement_type':kind,'priority_domain':'Synthetic workshop service records','framework':'dbt' if warehouse=='snowflake' else 'native_sql',
        'warehouse':warehouse,'semantic_target':'omni','migration_scope':'model_semantic','input_handling':'pre_sanitized',
        'deliverables':['documentation','diagrams','dictionary','implementation','validation'], 'audience':'engineer',
        'host':'Codex operator with deterministic simulation callback','environment':'local synthetic files only','execution_mode':'candidate_only'}
    if kind=='refactor': answers.update(trusted_outputs=['Synthetic authored and effective workbook snapshots v1'],
        retained_behavior=['Preserve filters, inherited values, query output identities and unknown blocks'],corrected_behavior=[])
    state=flow.start_engagement(source,root/'engagement',answers,catalogue=catpath)
    portal.render_engagement(state,root/'engagement/START_HERE.html')
    js(root,'discovery-v1.json',state)
    bindings={'schema_version':1,'kind':'warehouse_catalogue_bindings','catalogue_sha256':sha(catpath.read_bytes()),
        'source_snapshot_sha256':state['inputs']['source']['fingerprint']['value'],'expected_reference_ids':[], 'references':[]}
    cat=json.loads(catpath.read_text())
    for o in cat['objects']:
        rid='physical-'+o['object_id'];bindings['expected_reference_ids'].append(rid)
        bindings['references'].append({'reference_id':rid,'source_reference':'synthetic-defined:'+o['object_id'],'status':'resolved','object_id':o['object_id'],
            'column_paths':[c['path'] for c in o['columns']], 'namespace':{'platform_instance':'local-simulation','catalog':o['identity']['catalog'],'schema':o['identity']['schema']},
            'evidence':'Exact independently authored synthetic metadata; proposed target tables are not native observations.'})
    bp=js(root,'catalogue-bindings.json',bindings)
    checked=verify_catalogue.verify(catpath,bp)
    js(root,'catalogue-check.json',checked)
    assert checked['catalogue_context_complete'], 'Synthetic catalogue must verify before candidate preparation'
    assert checked['source_snapshot_sha256']==state['inputs']['source']['fingerprint']['value']
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    command=[sys.executable,str(SCRIPTS/'plan_specialists.py'),str(source),'--output',str(root/'routing'),'--no-git','--semantic-target','omni','--warehouse',warehouse]
    result=subprocess.run(command,capture_output=True,text=True,env=env)
    js(root,'routing-command.json',{'command':command,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    assert result.returncode==2, 'Expected explicit unclassified sidecar coverage gap'
    return state

def specialist(root, files, context, intent, definitions):
    projection={'model_context':context,'definitions':definitions,'source_kind':'independently-authored-public-synthetic','human_approval':False}
    c,p=disclosure()
    selected=knowledge.load_knowledge(['models','views','relationships','topics','query_views'],['inspect','preserve','generate','static_validate'],[context['warehouse']])
    js(root,'knowledge.json',selected)
    task=modeler.prepare_task(root.name,projection,c,p,intent=intent,warehouse=context['warehouse'],operations=('inspect','preserve','generate','static_validate'))
    js(root,'task.json',task);js(root,'projection.json',projection)
    absent=modeler.run_task(task,projection,c,p,host='codex')
    js(root,'no-adapter.json',absent)
    assert absent['receipt']['state']=='unavailable' and not absent['receipt']['runner_invoked']
    def callback(actual_task, approved_projection, current_knowledge):
        return {'execution_id':'local-deterministic-simulation-'+root.name,'result':{'schema_version':1,'kind':'omni_modeler_result',
            'task_sha256':actual_task['task_sha256'],'model_files':files,'model_context':context,
            'decisions':[{'id':'meaning','status':'unresolved','reason':'No actual SME approval exists; preserve stated unknowns.', 'source_refs':['/definitions']}],
            'gaps':[{'code':'business_meaning_unresolved','scope':'Synthetic exercise; no native execution, independent acceptance, or real SME review.'}]}}
    result=modeler.run_task(task,projection,c,p,host='codex',mode='simulation',runner=callback)
    assert result['receipt']['state']=='needs_review', 'Unresolved meaning must remain visible'
    js(root,'modeler-result.json',result)
    js(root,'orchestrator-observation.json',{'historical_authoring_task':'/root/omni_fresh_operator','source':'original authoring-session assignment; replay establishes no real agent execution','actual_agent_execution_established':False,
        'not_callback_execution_id':True,'callback_is':'local deterministic simulation, no external host SDK qualification'})
    js(root,'model-files.json',files);js(root,'model-context.json',context)
    js(root,'static-check.json',contract.check_model(files,context))
    js(root,'lineage.json',qv.analyze_query_views(files,context))
    return result

def package(root,state,files,context,models,relationships,extra_artifacts,decisions,validation):
    state=flow.assess_engagement(root/'engagement')
    h=handoff.build_handoff(state,files,context,decisions)
    artroot=root/'artifacts';handoff.write_handoff(h,artroot)
    artifacts=h['registrations']
    for aid,path,content,category in extra_artifacts:
        file=write(artroot,path,content)
        artifacts.append({'id':aid,'path':path,'category':category,'audiences':['engineer'] if category=='implementation' else ['reviewer','engineer'],
            'sha256':sha(file.read_bytes()),'requires':[],'description':'Independently authored synthetic pilot; scope and limits in runbook.'})
    c,p=disclosure()
    review={'schema_version':1,'title':root.name+' — synthetic candidate review','description':'Local newcomer exercise. Generated/static/simulated only; no native execution, human approval or deployment.',
        'source_fingerprint':portal.source_fingerprint(state),'context_sha256':portal.context_fingerprint(state),
        'target':{k:state['answers'][k] for k in ('framework','warehouse')},'models':models,'relationships':relationships,'changes':[],
        'decisions':[{'id':'meaning','question':'Which business definitions and source constraints are authoritative?','status':'unresolved','answer':'No actual SME definitions or approval supplied.'}],
        'validation':validation,'artifacts':artifacts,'omni':h['review_reference'],
        'disclosure':{'audience':'engineer','policy':p,'presentation':c,'artifacts':{a['id']:copy.deepcopy(c) for a in artifacts}}}
    rp=js(root,'review.json',review)
    state=flow.record_handoff(root/'engagement',rp,artroot,audience='engineer')
    portal.render_engagement(state,root/'REVIEW.html',review)
    portal.package_delivery(state,review,artroot,root/'engineering-handoff.zip',audience='engineer')
    verified=portal.verify_delivery(root/'engineering-handoff.zip');js(root,'zip-check.json',verified)
    assert verified['status']=='integrity_verified'
    with zipfile.ZipFile(root/'engineering-handoff.zip') as z:
        for name in z.namelist(): write(root/'extracted',name,z.read(name))
    return state,review

def validation_rows(check, local):
    return ([{'id':'static','label':'Omni static model contract','scope':'static','status':'pass' if check['status']=='passed' else 'pending',
        'expected':'Supported model subset','actual':check['status'],'details':'Real local checker; unsupported blocks remain intact. Native validation remains separate.'},
        {'id':'simulation','label':'Bounded local row simulation','scope':'local','status':'pass','expected':'Structural preservation for self-authored sample','actual':local,
        'details':'Same operator authored sample, baseline and candidate. This is not independent accuracy proof.'}]+
        [{'id':s,'label':label,'scope':s,'status':'pending','expected':'Qualified evidence','actual':None,'details':'Not performed or approved in this local exercise.'}
          for s,label in [('warehouse','Native warehouse execution'),('semantic','Native Omni compilation and query/access checks'),('business','Actual SME review'),('operational','Authorized deployment')]])

def pilot_a(root):
    root.mkdir();source=root/'source';source.mkdir()
    tickets=[(101,'NORTH','2026-09-28',12500,'OPEN'),(102,'SOUTH','2026-09-29',8900,'DONE'),(103,'NORTH','2026-09-30',None,'CANCELLED')]
    sites=[('NORTH','Northern shop'),('SOUTH','Southern shop')]
    for name,columns,rows in [('tickets',['TICKET_ID','SITE_ID','CREATED_DATE','QUOTED_AMOUNT','STATE'],tickets),('sites',['SITE_ID','SITE_NAME'],sites)]:
        out=io.StringIO();w=csv.writer(out);w.writerow(columns);w.writerows(rows);write(source,name+'.csv',out.getvalue())
    write(source,'SOURCE_NOTE.md','# Synthetic raw-only input\n\nNo SME definitions. QUOTED_AMOUNT unit, settlement, state lifecycle, stable key, timezone, retention and access are unknown. No legacy output exists.\n')
    tc={'TICKET_ID':'number','SITE_ID':'string','CREATED_DATE':'date','QUOTED_AMOUNT':'number','STATE':'string'};sc={'SITE_ID':'string','SITE_NAME':'string'}
    tables=[{'schema':s,'name':name,'columns':cols,'status':status} for s,name,cols,status in [
        ('RAW','TICKETS',tc,'authored raw fixture'),('RAW','SITES',sc,'authored raw fixture'),
        ('GOLD','FCT_TICKET_RECORDS',tc,'proposed target simulated only'),('GOLD','DIM_SITES',sc,'proposed target simulated only')]]
    cp,catname=catalogue(root,'snowflake',tables);state=start(root,source,cp,'snowflake','new_model')
    context=make_context(cp,catname,'snowflake',[('tickets','GOLD','FCT_TICKET_RECORDS',tc),('sites','GOLD','DIM_SITES',sc)])
    files={
        'model':'label: Synthetic workshop provisional model\nweek_start_day: Monday\n',
        'tickets.view':yml({'catalog':catname,'schema':'GOLD','table_name':'FCT_TICKET_RECORDS','description':'Proposed source-record projection. Business grain and quoted amount unit remain unresolved.',
            'dimensions':{n.lower():{'sql':'"'+n+'"','description':'Source value preserved; business interpretation unresolved.'} for n in tc},
            'measures':{'source_record_count':{'aggregate_type':'count','description':'Count of selected source records; not completed jobs or revenue.'}}}),
        'sites.view':yml({'catalog':catname,'schema':'GOLD','table_name':'DIM_SITES','dimensions':{n.lower():{'sql':'"'+n+'"'} for n in sc}}),
        'tickets.topic':yml({'base_view':'tickets','label':'Provisional ticket records','joins':{},'fields':['tickets.*'],'ai_fields':['tickets.ticket_id','tickets.state','tickets.source_record_count']}),
        'relationships':'[]\n'}
    result=specialist(root,files,context,'new_model',{'unresolved':['quoted amount unit','stable keys and join cardinality','state lifecycle','date/timezone semantics','retention and access'],
        'scope':'Preserve raw values; no revenue measure and no asserted site join until reviewed.'})
    models=[];rels=[]
    for entity,cols in [('tickets',tc),('sites',sc)]:
        for layer,physical in [('bronze','RAW.'+entity.upper()),('silver','STG_'+entity.upper()),('gold','FCT_TICKET_RECORDS' if entity=='tickets' else 'DIM_SITES')]:
            models.append({'id':layer+'.'+entity,'name':physical,'layer':layer,'domain':'Workshop records',
                'grain':'One row per provided source record; uniqueness beyond synthetic sample unverified',
                'columns':[{'name':n,'type':t,'key':'unverified','description':'Preserved source attribute; semantics/units unresolved'} for n,t in cols.items()]})
        for a,b in [('bronze','silver'),('silver','gold')]:rels.append({'from':a+'.'+entity,'to':b+'.'+entity,'kind':'lineage','label':'Preserve all rows/columns','evidence':'Candidate SQL projection','status':'proposed'})
    # Freeze structural expectations before executing candidate transformations.
    js(root,'frozen-expectations.json',{'origin':'self-authored-simulation-not-independent','tickets':tickets,'sites':sites,'record_count':len(tickets)})
    db=duckdb.connect(':memory:');db.execute('create table tickets (TICKET_ID bigint,SITE_ID varchar,CREATED_DATE date,QUOTED_AMOUNT bigint,STATE varchar)');db.executemany('insert into tickets values (?,?,?,?,?)',tickets)
    db.execute('create table sites (SITE_ID varchar,SITE_NAME varchar)');db.executemany('insert into sites values (?,?)',sites)
    db.execute('create view stg_tickets as select TICKET_ID,SITE_ID,CREATED_DATE,QUOTED_AMOUNT,STATE from tickets')
    db.execute('create view fct_ticket_records as select TICKET_ID,SITE_ID,CREATED_DATE,QUOTED_AMOUNT,STATE from stg_tickets')
    db.execute('create view stg_sites as select SITE_ID,SITE_NAME from sites')
    db.execute('create view dim_sites as select SITE_ID,SITE_NAME from stg_sites')
    observed=[list(row) for row in db.execute('select * from fct_ticket_records order by TICKET_ID').fetchall()]
    normalized=[[str(v) if hasattr(v,'isoformat') else v for v in row] for row in observed]
    assert normalized==[list(row) for row in tickets]
    assert db.execute('select * from stg_tickets order by TICKET_ID').fetchall()==db.execute('select * from fct_ticket_records order by TICKET_ID').fetchall()
    assert db.execute('select * from stg_sites order by SITE_ID').fetchall()==sites
    assert db.execute('select * from dim_sites order by SITE_ID').fetchall()==sites
    local={'row_projection_equal':True,'rows':normalized,'record_count':db.execute('select count(*) from fct_ticket_records').fetchone()[0],
        'runtime':'DuckDB '+duckdb.__version__,'independent_accuracy':False,'native_snowflake_execution':False,
        'all_projection_views_exercised':['stg_tickets','fct_ticket_records','stg_sites','dim_sites']}
    js(root,'local-simulation.json',local)
    extra=[('dbt-project','dbt/dbt_project.yml','name: synthetic_workshop\nversion: "1.0"\nconfig-version: 2\nprofile: synthetic_workshop\nmodel-paths: [models]\nmacro-paths: [macros]\nmodels:\n  synthetic_workshop:\n    +materialized: view\n    +database: SYNTH_WORKSHOP\n    +schema: GOLD\n','implementation'),
        ('dbt-schema-macro','dbt/macros/generate_schema_name.sql','{% macro generate_schema_name(custom_schema_name, node) -%}\n  {{ custom_schema_name | trim if custom_schema_name is not none else target.schema }}\n{%- endmacro %}\n','implementation'),
        ('dbt-sources','dbt/models/sources.yml',yml({'version':2,'sources':[{'name':'workshop_raw','database':catname,'schema':'RAW','tables':[{'name':'TICKETS'},{'name':'SITES'}]}]}),'implementation')]
    compiled=[]
    for entity,cols in [('tickets',tc),('sites',sc)]:
        sel=', '.join('"'+n+'"' for n in cols)
        stages=[('stg_'+entity,"{{ source('workshop_raw', '"+entity.upper()+"') }}"),('fct_ticket_records' if entity=='tickets' else 'dim_sites',"{{ ref('stg_"+entity+"') }}")]
        for name,relation in stages:
            sql='select '+sel+'\nfrom '+relation+'\n';extra.append(('sql-'+name,'dbt/models/'+name+'.sql',sql,'implementation'))
            sqlglot.parse_one('select '+sel+' from '+catname+'.RAW.'+entity.upper(),read='snowflake');compiled.append(name)
    extra.append(('dbt-tests','dbt/models/schema.yml',yml({'version':2,'models':[{'name':'fct_ticket_records','description':'Provisional complete source-row projection; business grain unknown.',
        'columns':[{'name':'TICKET_ID','description':'Candidate identity; no uniqueness test asserted without SME confirmation.'}]}]}),'implementation'))
    extra.append(('ai-context','docs/AI_CONTEXT.md','# Provisional AI context\n\nOnly count selected source records or return literal source attributes. Do not call QUOTED_AMOUNT revenue, infer its currency or divide by 100. Ask what OPEN, DONE and CANCELLED mean. No join to sites is published until stable keys and cardinality are reviewed. Topic AI selection omits quoted amount. These instructions do not enforce access. Formal reviewed AI definition context is intentionally pending because no SME definitions exist.\n','documentation'))
    extra.append(('dictionary','docs/WAREHOUSE_DICTIONARY.json',body({'origin':'self-authored-synthetic-candidate','models':models,'relationships':rels}),'dictionary'))
    extra.append(('diagram','docs/MODEL.svg',portal.model_svg(models,rels),'diagrams'))
    for layer in ('bronze','silver','gold'):
        extra.append((layer+'-guide','docs/'+layer.upper()+'.md','# '+layer.title()+' — provisional workshop records\n\n'+
            ('Retain the provided raw rows and their exact column names. This is a synthetic two-table source, not a capture of replication/CDC behavior. ' if layer=='bronze' else
             'Explicit projection preserves all rows and values. No de-duplication, cancellation exclusion, currency conversion or key assertions. ')+
            'TICKETS: TICKET_ID, SITE_ID, CREATED_DATE, QUOTED_AMOUNT, STATE. SITES: SITE_ID, SITE_NAME. Full column types are in the dictionary. History, timezone, null intent, ownership, refresh, retention, security and recovery are unresolved. No production ingestion or deployment is proposed.\n','documentation'))
    extra.append(('runbook','docs/RUNBOOK.md','# Workshop provisional dbt/Snowflake candidate\n\nGenerated: four dbt view models, two sources, explicit GOLD schema naming macro and native Omni views/topic. Static SQL parsing uses Snowflake grammar; local row simulation exercised all four projections using DuckDB only. Source metadata is synthetic; GOLD metadata is a proposed target shape, not a warehouse observation.\n\nNext: an analytics engineer and SME resolve units, lifecycle states, stable keys/cardinality, timezone/history, access, ownership and namespace, then review revised definitions. Configure an authorized development Snowflake profile outside this package (account, user, role, warehouse, database, schema and secure authentication). No credentials or placeholder profile are shipped. Run dbt debug, dbt parse and dbt build only after native execution authorization. Deployment and native Omni validation need separate approval and evidence.\n\nOrder: existing SYNTH_WORKSHOP.RAW.TICKETS/RAW.SITES → GOLD.stg_tickets/stg_sites → GOLD.fct_ticket_records/dim_sites → native Omni. The schema macro chooses the exact selected schema; review isolated development names before executing. No seeds are included; CSV inputs remain local exercise inputs. Rollback: remove only newly created isolated development candidates after review; no source mutation was made here. No human approval or independent accuracy proof exists.\n','documentation'))
    extra.append(('local-evidence','validation/LOCAL_SIMULATION.json',body(local),'validation'))
    extra.append(('static-evidence','validation/OMNI_STATIC.json',body(contract.check_model(files,context)),'validation'))
    state,review=package(root,state,files,context,models,rels,extra,[{'subject':'Source values','placement':'warehouse','reason':'Preserve values without invented business corrections','status':'proposed'},
        {'subject':'Quoted amount and state meaning','placement':'unresolved','reason':'No actual SME definitions supplied','status':'unknown'}],validation_rows(contract.check_model(files,context),local['record_count']))
    assert result['receipt']['static_check']['status']=='passed'
    return {'status':state['status'],'static_status':result['receipt']['static_check']['status'],'callback_state':result['receipt']['state'],'candidate_sha256':H(files),'task_sha256':result['receipt']['task_sha256'],
        'catalogue_context_complete':json.loads((root/'catalogue-check.json').read_text())['catalogue_context_complete'],'local_rows':len(normalized),'sql_parsed_models':compiled}

def pilot_b(root):
    root.mkdir();source=root/'source';source.mkdir()
    cols={'ticket_id':'number','site_id':'string','amount_minor':'number','state':'string'}
    cp,catname=catalogue(root,'bigquery',[{'schema':'analytics','name':'ticket_facts','columns':cols,'status':'authored existing synthetic table'}])
    context=make_context(cp,catname,'bigquery',[('tickets','analytics','ticket_facts',cols)])
    shared={'catalog':catname,'schema':'analytics','table_name':'ticket_facts','dimensions':{n:{'sql':'`'+n+'`'} for n in cols},
        'measures':{'amount_total':{'sql':'${amount_minor}','aggregate_type':'sum','label':'Revenue'}}}
    authored={'tickets.view':'# Workbook override; preserve this comment and inherited SQL.\nlabel: Workshop jobs\nmeasures:\n  amount_total:\n    label: Revenue\n',
        'tickets.topic':yml({'base_view':'tickets','joins':{},'fields':['tickets.*']}),
        'site_totals.query.view':'query:\n  base_view: tickets\n  topic: tickets\n  fields:\n    tickets.site_id: site_id\n    tickets.amount_total: recorded_amount\ndimensions:\n  site_id: {}\n  recorded_amount: {}\n',
        'recent_window.query.view':'# Deliberately unsupported window; preserve it for native review.\nsql: SELECT ticket_id, SUM(amount_minor) OVER (PARTITION BY site_id) AS site_amount FROM ${tickets}\ndimensions:\n  ticket_id: {}\n  site_amount: {}\n',
        'model':'week_start_day: Monday\ncustom_calendars:\n  fiscal_shop:\n    pattern: 445\n'}
    effective=dict(authored);eff=copy.deepcopy(shared);eff['label']='Workshop jobs';effective['tickets.view']=yml(eff)
    context['inherited_views']={'tickets':{'definition':shared,'sha256':H(shared)}}
    for path,value in authored.items():write(source,'authored/'+path,value)
    for path,value in effective.items():write(source,'effective/'+path,value)
    content=[{'id':'site_dashboard','definition_sha256':H('synthetic site totals tile v1'),'dependencies':['authored:view:site_totals'],'attached_to_branch':True},
        {'id':'window_dashboard','definition_sha256':H('synthetic window tile v1'),'dependencies':['authored:view:recent_window'],'attached_to_branch':True}]
    js(source,'content.json',content)
    state=start(root,source,cp,'bigquery','refactor')
    ic={'scope':{'model_id':'synthetic_workshop_model','layer':'workbook','branch_id':None,'workbook_id':'synthetic_workbook'},'capture_reference':'synthetic snapshots authored locally'}
    expected={'schema_version':1,'kind':'omni_expected_inventory','scope_sha256':H(ic['scope']),'provenance':'synthetic','reference':'separate fixture manifest; not independent completeness proof',
        'complete':True,'pagination_complete':True,'files':{p:sha(v) for p,v in authored.items()}}
    baseline=inventory.inspect_model(authored,context=ic,expected_inventory=expected,effective_files=effective)
    js(root,'baseline-inventory.json',baseline)
    assert inventory.decode_files(baseline['authored_files'])=={p:v.encode() for p,v in authored.items()}
    assert inventory.decode_files(baseline['effective_files'])=={p:v.encode() for p,v in effective.items()}
    noop=inventory.propose_patch(authored,effective,[]);js(root,'noop-proposal.json',noop)
    proposal=inventory.propose_patch(authored,effective,[{'path':'tickets.view','pointer':'/label','value':'Workshop recorded amounts — proposed label','expected_sha256':sha(authored['tickets.view'])}])
    js(root,'safe-proposal.json',proposal)
    candidate={p:v.decode() for p,v in inventory.decode_files(proposal['candidate_files']).items()}
    assert candidate['recent_window.query.view']==authored['recent_window.query.view']
    assert candidate['model']==authored['model'] and '# Workbook override' in candidate['tickets.view']
    effective_candidate=dict(effective);eff2=copy.deepcopy(eff);eff2['label']='Workshop recorded amounts — proposed label';effective_candidate['tickets.view']=yml(eff2)
    after=inventory.inspect_model(candidate,context=ic,effective_files=effective_candidate)
    js(root,'candidate-inventory.json',after)
    result=specialist(root,candidate,context,'refactor',{'observed':'Amount total sums minor-unit source values including cancelled rows; Revenue is a legacy label, not a business truth.',
        'proposal':'Presentation-only view label change; preserve measure SQL and all unsupported content. Query views stay in workbook scope.'})
    target={'environment':'development','warehouse':'bigquery','connection_id':'synthetic_connection','environment_connection_id':'synthetic_connection'}
    lc={'schema_version':1,'kind':'omni_lifecycle_contract','operation':'validate',
        'bindings':lifecycle.contract_bindings(baseline,after,context,target,{'remote':'unobserved'},json.loads((root/'knowledge.json').read_text())['knowledge_sha256']),
        'route':{'mode':'unknown','evidence_sha256':None,'attached_content_ids':['site_dashboard','window_dashboard']},
        'environment':{'warehouse':'bigquery','environment':'development','connection_id':'synthetic_connection','environment_connection_id':'synthetic_connection',
            'catalogue_sha256':context['catalogue_sha256'],'physical_resolution':[],'dbt':None},
        'content_inventory':{'complete':True,'expected_ids':['site_dashboard','window_dashboard'],'items':content,'evidence_sha256':sha((source/'content.json').read_bytes())},'cases':[]}
    assessed=lifecycle.assess_lifecycle(lc,baseline,after);js(root,'lifecycle-contract.json',lc);js(root,'lifecycle-assessment.json',assessed)
    assert assessed['status']=='pending'
    assert set(assessed['affected_content_sha256'])=={H('site_dashboard'),H('window_dashboard')}
    assert result['receipt']['static_check']['status']=='unsupported'
    lookup={H(c['id']):c['id'] for c in content};js(root,'content-impact.json',{'affected_content':[lookup[h] for h in assessed['affected_content_sha256']],
        'status':assessed['status'],'native_verified':False,'coverage':'synthetic content inventory; independent real scope absent'})
    # Simulation author records a business correction scenario, never human approval.
    rows=[(201,'NORTH',15000,'DONE'),(202,'NORTH',6000,'CANCELLED'),(203,'SOUTH',4200,'DONE')]
    js(root,'synthetic-rows.json',rows)
    db=duckdb.connect(':memory:');db.execute('create table facts(ticket_id bigint,site_id varchar,amount_minor bigint,state varchar)');db.executemany('insert into facts values (?,?,?,?)',rows)
    baseline_rows=db.execute('select site_id,sum(amount_minor) from facts group by site_id order by site_id').fetchall()
    correction={'record_type':'simulation','status':'proposed','not_human_approval':True,'statement':'For this simulated question only, exclude CANCELLED from a new metric called completed_amount_minor; do not overwrite the legacy amount_total.',
        'source':'self-authored scenario, no SME participant or authentication','affected_candidate':H(candidate)}
    js(root,'simulated-sme-correction.json',correction)
    correction_edits=[{'path':'tickets.view','pointer':'/measures/completed_amount_minor/'+leaf,'value':value,
        'expected_sha256':sha(candidate['tickets.view'])} for leaf,value in {
        'sql':"CASE WHEN ${state} <> 'CANCELLED' THEN ${amount_minor} ELSE NULL END",
        'aggregate_type':'sum','description':'SIMULATED PROPOSAL ONLY: excludes cancelled; currency and settlement unknown.'}.items()]
    correction_patch=inventory.propose_patch(candidate,effective_candidate,correction_edits)
    corrected={p:v.decode() for p,v in inventory.decode_files(correction_patch['candidate_files']).items()}
    assert '# Workbook override' in corrected['tickets.view']
    js(root,'correction-patch-v2.json',correction_patch);js(root,'corrected-model-files-v2.json',corrected)
    corrected_check=contract.check_model(corrected,context);js(root,'corrected-static-v2.json',corrected_check)
    corrected_rows=db.execute("select site_id,sum(amount_minor) from facts where state <> 'CANCELLED' group by site_id order by site_id").fetchall()
    local={'baseline_rows':baseline_rows,'simulated_correction_rows':corrected_rows,'same_operator_expected_and_actual':True,'independent_accuracy':False,'native_bigquery_execution':False}
    js(root,'local-simulation.json',local)
    models=[{'id':'gold.tickets','name':'synthetic-workshop.analytics.ticket_facts','layer':'gold','domain':'Workshop recorded amounts','grain':'Declared source record; native key not verified',
        'columns':[{'name':n,'type':typ,'key':'unverified','description':'Existing synthetic source attribute; units/lifecycle not business-approved'} for n,typ in cols.items()]}]
    extra=[('warehouse-dictionary','docs/WAREHOUSE_DICTIONARY.json',body({'origin':'synthetic existing source','models':models}),'dictionary'),
        ('local-results','validation/LOCAL_SIMULATION.json',body(local),'validation'),('impact','validation/CONTENT_IMPACT.json',(root/'content-impact.json').read_text(),'validation'),
        ('life','validation/LIFECYCLE.json',body(assessed),'validation'),('static','validation/STATIC.json',body(contract.check_model(candidate,context)),'validation'),
        ('correction','docs/SIMULATED_CORRECTION.json',body(correction),'documentation')]
    for layer in ('bronze','silver','gold'):
        extra.append((layer,'docs/'+layer.upper()+'.md','# '+layer.title()+' scope\n\n'+('No bronze/silver input supplied; upstream lineage, replication, retention and transformations remain unknown. No warehouse rewrite generated.' if layer!='gold' else
            'One existing synthetic table with ticket_id, site_id, amount_minor, state. Preserve its values and legacy aggregate. Grain, stable key, null semantics, currency, refresh, security and recovery need actual review.')+'\n','documentation'))
    extra.append(('runbook','docs/RUNBOOK.md','# Existing BigQuery/Omni workbook candidate\n\nAuthored overrides and effective state were captured separately and exact-byte checked. The proposed v1 change touches only a view label. Inherited field SQL, comment, query views, custom calendar and unsupported window remain preserved. No warehouse SQL rewrite is justified from this evidence.\n\nReview both affected dashboard IDs in CONTENT_IMPACT. Query views stay in workbook scope; no physical materialization is invented. Unknown route and physical environment remain pending. The correction is a self-authored simulation, not an SME approval: v2 adds a separate filtered metric and retains the legacy metric. Do not apply v2 from a stale v1 package. Next: obtain actual definitions and independent scope/baselines, capture authorized development environment, run native Model/Content Validator and result/access cases, then request exact-version approval.\n','documentation'))
    state,review=package(root,state,candidate,context,models,[],extra,[{'subject':'Legacy recorded amount','placement':'semantic','reason':'Keep existing sum and unsupported workbook constructs','status':'proposed'},
        {'subject':'Query views','placement':'workbook','reason':'No measured reason or approved semantic change justifies materialization','status':'proposed'}],validation_rows(contract.check_model(candidate,context),len(baseline_rows)))
    # Record evidence with the real workflow, then change discovery: old records must stale.
    evidence=js(root,'candidate-v1-evidence.json',{'candidate_sha256':H(candidate),'status':'static-only','independent_accuracy':False})
    flow.record_evidence(root/'engagement',evidence,'synthetic_candidate_static')
    stale=flow.update_answers(root/'engagement',{'corrected_behavior':['SIMULATION ONLY, not SME approval: add separate completed_amount_minor excluding CANCELLED; preserve legacy metric.']})
    js(root,'post-correction-state.json',stale)
    portal.render_engagement(stale,root/'POST_CORRECTION.html')
    rejected=None
    try:portal.validate_review(stale,review)
    except ValueError as exc:rejected=str(exc)
    assert rejected is not None
    stale_result={'old_review_rejected':rejected,'v1_candidate_sha256':H(candidate),'v2_candidate_sha256':H(corrected),
        'evidence':[e for e in stale.get('evidence',[]) if e.get('status')=='stale'],'current_status':stale['status'],
        'old_zip_is_historical_only':True,'v2_human_approved':False}
    js(root,'staleness-check.json',stale_result)
    assert len(stale_result['evidence'])==2, 'Both previous evidence records must become stale'
    return {'status_before_correction':state['status'],'status_after_correction':stale['status'],'static_status':result['receipt']['static_check']['status'],
        'callback_state':result['receipt']['state'],'candidate_v1_sha256':H(candidate),'candidate_v2_sha256':H(corrected),'task_sha256':result['receipt']['task_sha256'],
        'authored_round_trip_exact':True,'effective_round_trip_exact':True,'unsupported_preserved':True,'affected_content':[lookup[h] for h in assessed['affected_content_sha256']],
        'lifecycle_status':assessed['status'],'stale_review_rejected':rejected,'stale_evidence_records':len(stale_result['evidence'])}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    begun=time.perf_counter();errors=[];results={}
    metadata={'started_at_utc':datetime.now(timezone.utc).isoformat(),'python':sys.version,'python_executable':sys.executable,
        'runtime_packages':{'duckdb':duckdb.__version__,'sqlglot':sqlglot.__version__,'pyyaml':yaml.__version__},
        'historical_authoring_task':'/root/omni_fresh_operator','actual_agent_execution_established':False,'callback_execution':'simulation','network':False,'credentials':False,
        'production_files_modified':False,'independent_accuracy':False,'human_approval':False,'deployed':False}
    js(root,'runtime.json',metadata)
    for name,fn in [('A_raw_new_model',pilot_a),('B_existing_workbook',pilot_b)]:
        t=time.perf_counter()
        try:results[name]=fn(root/name)
        except Exception as exc:
            import traceback
            errors.append({'pilot':name,'error':type(exc).__name__+': '+str(exc),'traceback':traceback.format_exc()})
        results.setdefault(name,{})['elapsed_seconds']=round(time.perf_counter()-t,3)
        js(root,'RESULTS.json',{'results':results,'errors':errors,'elapsed_seconds':round(time.perf_counter()-begun,3)})
    print(body({'output':str(root),'results':results,'errors':errors,'elapsed_seconds':round(time.perf_counter()-begun,3)}))
    return bool(errors)
if __name__=='__main__':raise SystemExit(main())
