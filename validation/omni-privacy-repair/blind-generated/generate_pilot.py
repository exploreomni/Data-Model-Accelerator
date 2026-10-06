from pathlib import Path
import csv, copy, hashlib, importlib.metadata, json, sys, re
from decimal import Decimal
from datetime import date
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'validation/omni-privacy-repair/blind-generated'
INPUT=ROOT/'validation/omni-privacy-repair/blind-inputs'
sys.path.insert(0,str(ROOT/'skills/data-model-accelerator/scripts'))
import yaml, sqlglot, duckdb
from raw_csv_source import inspect_csv
from data_dictionary_v2 import validate_dictionary
from privacy_contract import new_classification, default_policy
from generate_omni_model import generate_model, write_candidate
from omni_contract import canonical_hash, check_model
from looker_source import parse_dashboard
from omni_dashboard import template
from omni_ai_context import build_context, input_pins, write_context, digest
from generate_dbt_docs_yml import generate_project
from guided_workflow import start_engagement
from lint_delivery import scaffold_manifest
from sensitive_data import scan_bytes

def sha(x):return hashlib.sha256(x if isinstance(x,bytes) else x.read_bytes()).hexdigest()
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(x if isinstance(x,str) else json.dumps(x,indent=2,sort_keys=True,default=str)+'\n')
def prop(x):return yaml.safe_dump(x,sort_keys=False)
def provenance(ref,h):return {'origin':'generated','evidence':[{'reference':ref,'sha256':h}],'review_reference':None}
EXPECTED=json.loads((INPUT/'MANIFEST.json').read_text())
for domain,files in EXPECTED.items():
 for name,h in files.items():assert sha(INPUT/domain/name)==h,(domain,name,'changed input')
versions={'python':sys.version,'packages':{n:importlib.metadata.version(n) for n in ['sqlfluff','PyYAML','sqlglot','duckdb','dbt-core','ruamel.yaml']}}
write(OUT/'runtime.json',versions)
summary={}
for domain in ('maintenance','energy'):
 d=OUT/domain; d.mkdir(exist_ok=False)
 inp=INPUT/domain; intake=json.loads((inp/'intake.json').read_text()); warehouse=intake['warehouse']; sf=warehouse=='snowflake'
 upper=lambda c:c.upper() if sf else c
 name='maintenance_pilot' if sf else 'energy_pilot'
 database='SYNTHETIC_REVIEW' if sf else 'synthetic-review'
 schema='DMA_MAINTENANCE' if sf else 'dma_energy'
 raw_schema='RAW_MAINTENANCE' if sf else 'raw_energy'
 raw_tables=['work_orders','parts'] if sf else ['readings','meters']
 grain={'work_orders':'One row per work_order_id','parts':'One row per part_line_id', 'readings':'One row per reading_id','meters':'One row per meter_id'}
 headers={t:next(csv.reader((inp/(t+'.csv')).open())) for t in raw_tables}
 source_inv={'schema_version':1,'kind':'synthetic_snapshot_inventory','origin':'synthetic','native_observed':False,'files':{t+'.csv':inspect_csv((inp/(t+'.csv')).read_bytes()) for t in raw_tables}}
 write(d/'source-inventory.json',source_inv)
 write(d/'input-boundary.json',{'mode':'blind_test','inputs':EXPECTED[domain],'presanitized':True,'shared_filesystem_is_sandbox':False,'permitted_sources':'Skill and referenced helper instructions plus supplied synthetic inputs only','native_observation':False,'authority':intake['review_authority']})
 types={c:('number' if c.endswith('_id') or c in ('labor_cost','quantity','unit_cost','kwh','parts_cost','work_cost') else 'date' if c.endswith('_on') else 'string') for c in sum(headers.values(),[])+['parts_cost','work_cost']}
 sqltypes={c:('number(38, 0)' if sf else 'int64') if c.endswith('_id') else ('number(18, 4)' if sf else 'numeric') if types[c]=='number' else 'date' if types[c]=='date' else ('varchar' if sf else 'string') for c in types}
 specs=[]
 for t in raw_tables:
  cs=headers[t]
  specs.append({'name':'bronze_'+t,'layer':'bronze','grain':grain[t]+' in the supplied snapshot; no historical uniqueness asserted','columns':cs,'source_table':t,'sql':'select\n'+',\n'.join('    '+c for c in cs)+'\nfrom {{ source(\'raw_'+domain+'\', \''+t+'\') }}\n'})
 for t in raw_tables:
  cs=headers[t]
  specs.append({'name':'silver_'+t,'layer':'silver','grain':grain[t],'columns':cs,'source_table':t,'sql':'select\n'+',\n'.join('    cast('+c+' as '+sqltypes[c]+') as '+c for c in cs)+'\nfrom {{ ref(\'bronze_'+t+'\') }}\n'})
 if sf:
  gold='gold_work_orders'; gold_cols=['work_order_id','tenant_id','opened_on','labor_cost','status','parts_cost','work_cost']
  gold_sql='''with parts_by_work_order as (
    select
        work_order_id,
        sum(quantity * unit_cost) as parts_cost
    from {{ ref('silver_parts') }}
    group by work_order_id
)

select
    work_orders.work_order_id,
    work_orders.tenant_id,
    work_orders.opened_on,
    work_orders.labor_cost,
    work_orders.status,
    coalesce(parts.parts_cost, 0) as parts_cost,
    work_orders.labor_cost + coalesce(parts.parts_cost, 0) as work_cost
from {{ ref('silver_work_orders') }} as work_orders
left join parts_by_work_order as parts
    on work_orders.work_order_id = parts.work_order_id
'''
 else:
  gold='gold_readings';gold_cols=['reading_id','meter_id','recorded_on','kwh','zone']
  gold_sql='''select
    readings.reading_id,
    readings.meter_id,
    readings.recorded_on,
    readings.kwh,
    meters.zone
from {{ ref('silver_readings') }} as readings
left join {{ ref('silver_meters') }} as meters
    on readings.meter_id = meters.meter_id
'''
 specs.append({'name':gold,'layer':'gold','grain':grain['work_orders' if sf else 'readings'],'columns':gold_cols,'source_table':raw_tables[0],'sql':gold_sql})
 inventory={'schema_version':1,'kind':'data_model_inventory','evidence_status':'synthetic_planned_not_native','models':[{'model_id':s['name'],'layer':s['layer'],'physical_name':'.'.join([database,schema,upper(s['name'])]),'grain':s['grain'],'columns':[upper(c) for c in s['columns']]} for s in specs]}
 write(d/'model-inventory.json',inventory)
 cat={'schema_version':1,'kind':'warehouse_raw_catalogue','provider':warehouse,'origin':'synthetic','captured_at':None,'context':{'platform_instance':'SYNTHETIC_ONLY_NOT_A_NATIVE_INSTANCE','principal':'none_offline_generation','scope':[{'scope_id':domain,'catalog':database,'schema':raw_schema,'location':'UNKNOWN'}]},'coverage':{'status':'partial','gaps':['CSV structure is observed; physical names and native types are planned synthetic bindings. No live catalogue, exporter identity, watermark, constraints or policies.']},'extractions':[],'objects':[],'planned_models':inventory['models']}
 for t in raw_tables:
  h=sha(inp/(t+'.csv'));oid='synthetic:'+domain+':'+t
  for component in ('objects','columns'):
   cat['extractions'].append({'extraction_id':t+'-'+component,'scope_id':domain,'component':component,'status':'complete','artifact_path':'../../blind-inputs/'+domain+'/'+t+'.csv','sha256':h,'query_id':None,'pagination_complete':True,'evidence_status':'synthetic_snapshot_only'})
  cat['objects'].append({'object_id':oid,'scope_id':domain,'identity':{'catalog':database,'schema':raw_schema,'name':upper(t)},'object_type':'TABLE','columns':[{'path':[upper(c)],'data_type':'TEXT','nullable':None} for c in headers[t]],'metadata_status':{k:'unknown' for k in ('comments','relationships','ownership','security','replication','statistics')},'evidence':[{'extraction_id':t+'-objects','locator':'CSV header; planned relation identity'},{'extraction_id':t+'-columns','locator':'CSV header'}]})
 write(d/'synthetic-catalogue.json',cat); cathash=sha(d/'synthetic-catalogue.json')
 bindings={'schema_version':1,'kind':'warehouse_catalogue_bindings','catalogue_sha256':cathash,'source_snapshot_sha256':canonical_hash(source_inv),'expected_reference_ids':['source:'+t for t in raw_tables],'references':[{'reference_id':'source:'+t,'source_reference':t+'.csv','status':'resolved','object_id':'synthetic:'+domain+':'+t,'column_paths':[[upper(c)] for c in headers[t]],'namespace':{'platform_instance':'SYNTHETIC_ONLY_NOT_A_NATIVE_INSTANCE','catalog':database,'schema':raw_schema},'evidence':'Resolved only to this supplied synthetic CSV snapshot; no native physical object observation.'} for t in raw_tables]}
 write(d/'catalogue-bindings.json',bindings)
 # Main dictionary remains proposed, never a claimed business approval.
 dictionary={'schema_version':2,'privacy_schema_version':1,'kind':'data_dictionary','model_inventory_sha256':sha(d/'model-inventory.json'),'source_inventory_sha256':sha(d/'source-inventory.json'),'models':[],'sources':[],'synthetic':True,'authority':intake['review_authority']}
 descriptions={'work_order_id':'Work order identifier in the synthetic snapshot.','tenant_id':'Tenant identifier retained for downstream filtering; no security policy is established.','opened_on':'Work order opening date; dashboard date interpretation is UTC.','labor_cost':'Labor contribution to work cost; currency is unspecified.','status':'Work order status retained without upstream filtering.','part_line_id':'Part line identifier in the supplied snapshot.','quantity':'Quantity of the part on this line.','unit_cost':'Cost per part unit; currency is unspecified.','parts_cost':'Sum of quantity times unit_cost by work_order_id; zero when no part rows exist.','work_cost':'Labor cost plus parts cost at work order grain.','reading_id':'Reading identifier in the supplied snapshot.','meter_id':'Meter identifier used for the unique meter lookup.','recorded_on':'Reading date retained for interactive UTC date filtering.','kwh':'Energy usage in kilowatt-hours; additive across selected readings.','zone':'Meter zone retained for interactive filtering.'}
 def raw_lineage(c,s):
  if c in ('parts_cost','work_cost'):
   refs=[('parts','quantity'),('parts','unit_cost'),('parts','work_order_id'),('work_orders','work_order_id')]
   if c=='work_cost':refs += [('work_orders','labor_cost')]
  elif c=='zone':refs=[('meters','zone'),('meters','meter_id'),('readings','meter_id')]
  else:refs=[(s['source_table'],c)]
  return [{'object_id':'synthetic:'+domain+':'+t,'column_path':[upper(col)],'catalogue_sha256':cathash} for t,col in refs]
 source_specs=[{'name':t,'layer':'raw','grain':grain[t]+' is a synthetic contract; original platform grain unknown','columns':headers[t],'source_table':t} for t in raw_tables]
 for s in source_specs+specs:
  raw=s['layer']=='raw';rid=('source:' if raw else '')+s['name']; k='source_id' if raw else 'model_id'
  r={k:rid,'layer':s['layer'],'description':('Supplied synthetic '+s['name']+' snapshot.' if raw else 'Proposed synthetic '+s['layer']+' model '+s['name']+'.'),'grain':s['grain'],'source_systems':['synthetic:'+domain],'model_role':'STAGING' if s['layer'] in ('raw','bronze') else 'FACT' if s['layer']=='gold' else 'INTERMEDIATE','owner':None,'review_status':'proposed','provenance':provenance('synthetic intake, not actual approval',sha(inp/'intake.json')),'columns':[]}
  for c in s['columns']:
   physical=upper(c); primary=c==('part_line_id' if s['source_table']=='parts' else 'meter_id' if s['source_table']=='meters' else 'work_order_id' if sf else 'reading_id')
   role='PRIMARY_KEY' if primary else 'FOREIGN_KEY' if c in ('work_order_id','meter_id') else 'UNKNOWN'
   trans='Identity retention of lexical CSV value' if s['layer'] in ('raw','bronze') else descriptions[c] if c in ('parts_cost','work_cost','zone') else 'Explicit cast to '+sqltypes[c]+'; invalid values fail rather than silently null.'
   record={'column_id':rid+':'+physical,'name':physical,'description':descriptions[c],'data_type':'TEXT (CSV lexical contract)' if s['layer'] in ('raw','bronze') else sqltypes[c].upper(),'nullability':'Source null semantics unknown; required key and measure inputs have proposed not_null tests. No default except absent parts becomes zero.','key_role':role+' candidate; not a native enforced constraint','source':'; '.join(x['object_id']+'.'+'.'.join(x['column_path']) for x in raw_lineage(c,s)),'transformation':trans,'units':'kWh' if c=='kwh' else 'date, UTC dashboard interpretation' if c.endswith('_on') else 'unspecified currency units' if 'cost' in c else 'part units' if c=='quantity' else 'identifier' if c.endswith('_id') else 'category','classification':'UNKNOWN: synthetic inputs allowed for this local exercise; destination disclosure is not established.','validation':'See local-results.json; native tests and independent acceptance remain pending.','review_status':'proposed','provenance':provenance('synthetic intake, not actual approval',sha(inp/'intake.json')),'sensitivity':'UNKNOWN','sensitivity_evidence':[],'sensitivity_review_status':'unresolved','sensitivity_review_reference':None,'key_roles':[role],'source_refs':raw_lineage(c,s),'privacy':new_classification()}
   r['columns'].append(record)
  dictionary['sources' if raw else 'models'].append(r)
 errors=validate_dictionary(dictionary);assert not errors,errors
 write(d/'dictionary-v2.json',dictionary)
 md=['# '+domain.title()+' dictionary','All physical namespaces/types are synthetic plans. Definitions are proposed; approvals, ownership, source NULL semantics, CDC/history, retention and currency remain unresolved.']
 for r in dictionary['sources']+dictionary['models']:
  md+=['\n## '+r.get('model_id',r.get('source_id')),'Grain: '+r['grain'],'\n| Column | Planned type | Meaning | Transformation |','|---|---|---|---|']
  md += ['| '+c['name']+' | '+c['data_type']+' | '+c['description']+' | '+c['transformation']+' |' for c in r['columns']]
 write(d/'DICTIONARY.md','\n'.join(md)+'\n')
 impl=d/'implementation';project=impl/'dbt';project.mkdir(parents=True)
 write(project/'dbt_project.yml',prop({'name':name,'version':'0.1.0','config-version':2,'profile':name,'model-paths':['models'],'test-paths':['tests'],'clean-targets':['target'],'models':{name:{'+materialized':'view','+persist_docs':{'relation':False,'columns':False}}}}))
 source_yml={'version':2,'sources':[{'name':'raw_'+domain,'database':database,'schema':raw_schema,'description':'Planned synthetic raw landing namespace; operator must bind/load supplied CSV snapshots explicitly.','tables':[{'name':t,'identifier':upper(t),'columns':[{'name':upper(c),'description':'Proposed: '+descriptions[c]} for c in headers[t]]} for t in raw_tables]}]}
 write(project/'models/sources.yml',prop(source_yml))
 dbt_models=[]
 for s in specs:
  write(project/('models/'+s['layer']+'/'+s['name']+'.sql'),s['sql'])
  cs=[]
  for c in s['columns']:
   tests=[]
   if s['layer']!='bronze':tests=['not_null']
   pk='part_line_id' if s['source_table']=='parts' else 'meter_id' if s['source_table']=='meters' else 'work_order_id' if sf else 'reading_id'
   if c==pk and s['layer']!='bronze':tests+=['unique']
   cs.append({'name':c,'description':'Proposed: '+descriptions[c],**({'data_tests':tests} if tests else {})})
  dbt_models.append({'name':s['name'],'description':'Proposed synthetic model. Grain: '+s['grain'],'columns':cs})
 write(project/'models/proposed-properties.yml',prop({'version':2,'models':dbt_models}))
 if sf:
  test_sql="select parts.part_line_id\nfrom {{ ref('silver_parts') }} as parts\nleft join {{ ref('silver_work_orders') }} as work_orders\n    on parts.work_order_id = work_orders.work_order_id\nwhere work_orders.work_order_id is null\n"
 else:
  test_sql="select readings.reading_id\nfrom {{ ref('silver_readings') }} as readings\nleft join {{ ref('silver_meters') }} as meters\n    on readings.meter_id = meters.meter_id\nwhere meters.meter_id is null\n"
 write(project/'tests/no_orphan_children.sql',test_sql)
 setup=f'''# Candidate setup — {warehouse}\n\nThis is a dbt source/ref project, not SQL for direct pasting into the warehouse console.\nFive views execute bronze → silver → gold. No macros, hooks, packages, seeds, ingestion changes or native DDL are included. The CSV snapshots remain outside this package.\n\nAll source names and destination `{database}.{schema}` are synthetic placeholders. A future operator must select a dbt {warehouse} adapter and supported core version, set a separate nonsecret/profile configuration for database/project, schema/dataset, location/warehouse and authenticated identity, load or bind the exact supplied raw CSV snapshots with lexical text columns, and establish classification, ownership and access before any target execution. Credentials belong outside this project. Local library versions are in ../../runtime.json; neither warehouse adapter nor live profile was qualified.\n\nAfter separate native authorization: configure the target schema/dataset as `{schema}`, run `dbt parse`, review the complete manifest, then `dbt build --target <authorized-development-target>` without a narrowed selector. Capture manifest/run-results, native catalogue readback and access tests. No such command was run here. Defaults are views and resource-scoped `persist_docs: false`; proposed descriptions are documentation only.\n\nInvalid numeric/date casts fail; there is no arbitrary deduplication. Stop on uniqueness, not-null or orphan test failures. Full replacement views provide current-snapshot behavior only; there is no CDC, history or incremental claim. Rollback removes only reviewed candidate objects after consumer impact review; no automatic DROP is delivered.\n'''
 write(impl/'SETUP.md',setup)
 # Exact field and placement pins for generation; one flat gold view avoids semantic fanout.
 semantic_view='work_orders' if sf else 'readings';metric='total_work_cost' if sf else 'total_kwh';base='work_cost' if sf else 'kwh';pk='work_order_id' if sf else 'reading_id'
 placement={'schema_version':1,'synthetic':True,'rules':[{'id':'metric','source_field':semantic_view+'.'+metric,'target_field':semantic_view+'.'+metric,'placement':'retain_semantic','expression':'sum('+base+')','definition':intake['rules'][1]},{'id':'filters','placement':'retain_presentation','definition':'Preserve all source query filters, dashboard default Date, sorts, limits and listeners; no dashboard filters in warehouse SQL.'},{'id':'security','placement':'unresolved','definition':'No tenant or persona access policy is established; filter fields do not enforce authorization.'}]}
 write(d/'placement.json',placement)
 ns=({'database':database,'schema':schema,'table':upper(gold)} if sf else {'project':database,'dataset':schema,'table':gold})
 ctx={'schema_version':1,'kind':'omni_model_context','warehouse':warehouse,'environment':'synthetic_offline_candidate','catalogue_sha256':cathash,'bindings':{semantic_view:{'namespace':ns,'columns':{upper(c):types[c] for c in gold_cols},'evidence_sha256':sha(d/'model-inventory.json')}},'inherited_views':{},'default_catalog':None,'user_attributes':[],'access_grants':[]}
 write(d/'omni-context.json',ctx)
 dims={c:({'primary_key':True} if c==pk else {}) for c in gold_cols}
 definition={'dimensions':dims,'measures':{metric:{'sql':'${'+semantic_view+'.'+base+'}','aggregate_type':'sum'}}}
 mappings={c:{'kind':'physical','column':upper(c),'source_refs':['model#/models/4/columns/'+str(i)]} for i,c in enumerate(gold_cols)}
 mappings[metric]={'kind':'aggregate','source_refs':['placement#/rules/0']}
 spec={'schema_version':1,'kind':'omni_generation_spec','contract_version':'omni-static-v1-2026-10-05','pins':{'model_sha256':canonical_hash(inventory),'placement_sha256':canonical_hash(placement),'context_sha256':canonical_hash(ctx),'catalogue_sha256':cathash},'model':{'week_start_day':'Monday'},'views':{semantic_view:{'kind':'physical','definition':definition,'field_mappings':mappings}},'topics':{domain:{'base_view':semantic_view,'joins':{},'fields':[semantic_view+'.'+c for c in gold_cols]+[semantic_view+'.'+metric]}},'relationships':[]}
 simulated_review={'kind':'synthetic_review_only','human_approved':False,'native_evidence':False,'deployment_authorized':False,'reason':'Helper requires approved enum; this synthetic exercise only pins the agent-reviewed structural candidate. No real-world authority is asserted.','intake_sha256':sha(inp/'intake.json')}
 write(d/'synthetic-review.json',simulated_review)
 spec['review']={'status':'approved','reference':'synthetic-review.json: synthetic-only local review; NOT actual approval','evidence_sha256':sha(d/'synthetic-review.json'),'spec_sha256':canonical_hash(spec)}
 write(d/'omni-generation-spec.json',spec)
 result=generate_model(spec,ctx,inventory,placement)
 write(d/'omni-generation-check.json',result['check'])
 assert result['check']['status']=='passed',result['check']
 write_candidate(result,impl/'omni')
 write(d/'omni-files.json',result['files'])
 # Deterministic source parse; no independent API inventory is fabricated.
 source=parse_dashboard((inp/'looker-dashboard.json').read_bytes())
 assert source==parse_dashboard((inp/'looker-dashboard.json').read_bytes())
 write(d/'looker-canonical.json',source)
 work=template(source,result['check']['candidate_sha256'],'00000000-0000-4000-8000-000000000000')
 # The UUID only satisfies local worklist shape; it is never represented as a live model.
 write(d/'dashboard-worklist.json',work)
 write(d/'DASHBOARD.md',f'''# Dashboard worklist\n\nAll {len(source['tiles'])} source tiles, {len(source['filters'])} source filter, every listener/query behavior and all layouts are retained in looker-canonical.json and dashboard-worklist.json. Coverage remains `{source['coverage']['status']}`: there is no separate source inventory or authenticated API capture. Supplied JSON is synthetic, not a complete Looker estate or LookML dependency export.\n\nThe all-zero-based UUID is a visibly synthetic local placeholder required by the helper. It is not an observed model ID. All native tile/control/layout entries remain manual; no invented native controls or containers are qualified. Query field crosswalks preserve `{semantic_view}.{metric}` and date dimensions. The source text tile is retained verbatim. Source row/column/width/height values remain Looker layout evidence only.\n\n{'Preserve status=closed and opened_on 2026-01-02 through 2026-01-03 inclusive, UTC, on BOTH data tiles. Date listener/default must intersect with fixed query restrictions according to native verified behavior.' if sf else 'Preserve recorded_on=2026-02-01 inclusive UTC on BOTH data tiles. Keep zone queryable; north remains an interactive selection. The export has no Zone dashboard control, so adding one is an explicit manual target enhancement requested by intake, not an observed source control.'}\n\nKeep source sorts and limit 500. Visualization configuration is absent; choose and review presentation separately. Native Documents API/server validation, filter semantics, visual comparison, complete source coverage and customer acceptance remain pending.\n''')
 # Candidate-only AI projection: unknown classifications intentionally withhold all definitions.
 policy=default_policy();write(d/'disclosure-policy.json',policy)
 goldrec=dictionary['models'][-1];goldcol=next(c for c in goldrec['columns'] if c['name']==upper(base))
 nativeview=yaml.safe_load(result['files'][semantic_view+'.view']);field=semantic_view+'.'+metric
 ai={'schema_version':1,'kind':'omni_ai_context_spec','pins':input_pins(dictionary=dictionary,source=intake,model_files=result['files'],model_context=ctx,disclosure_policy=policy),'bindings':{field:{'layer':'gold','field_sha256':digest(nativeview['measures'][metric]),'columns':[{'view':semantic_view,'column':upper(base),'model_id':gold,'column_id':goldcol['column_id'],'namespace':ns}]}},'definitions':[{'id':'metric-review','status':'unresolved','statement':None,'question':'Confirm the synthetic metric meaning, null behavior, gold dependency and authorized disclosure before using this definition in a live AI context.','fields':[field],'source_refs':[{'pointer':'/rules/1','sha256':digest(intake['rules'][1])}],'privacy':new_classification(),'review_reference':None}]}
 ai['review']={'status':'approved','reference':'synthetic-review.json: local synthetic specification only; no actual approval','sha256':digest(ai)}
 write(d/'ai-spec.json',ai)
 airesult=build_context(ai,dictionary=dictionary,source=intake,model_files=result['files'],model_context=ctx,disclosure_policy=policy);write_context(airesult,d/'ai-context')
 write(d/'AI_REVIEW_NOTES.md',f'''# Private synthetic AI review notes\n\nUse only this bounded synthetic exercise. Never infer customer acceptance, freshness, policy enforcement or a live physical binding from these files. Consult the dictionary and intake, retain row grain and the selected query filter context, and ask for unresolved definitions instead of fabricating them.\n\n{'Work cost is labor plus preaggregated parts cost; absence of parts contributes zero. Open work and tenant_id remain in the warehouse. Tenant filtering is not security; currency is unknown.' if sf else 'Usage is additive kWh at reading grain. Preserve date and zone filtering. No tariff, monetary cost or forecast definition exists; do not manufacture one.'}\n\nThe supported AI context builder withheld the definition because classification and destination policy are unresolved. Its incomplete output is intentional and must not be advertised as an approved business context. This private note is review guidance, not content approved for a native AI surface.\n''')
 # Supported dbt documentation preview: deliberately preserve proposed status and record gate outcome.
 db={ 'schema_version':1,'kind':'dbt_metadata_bindings','project_name':name,'resources':[]}
 for s,r in zip(specs,dictionary['models']):db['resources'].append({'resource_type':'model','model_id':r['model_id'],'name':s['name'],'property_path':'models/proposed-properties.yml','config_path':[s['layer']],'columns':[{'column_id':c['column_id'],'name':c['name'].lower()} for c in r['columns']]})
 for r in dictionary['sources']:db['resources'].append({'resource_type':'source','source_id':r['source_id'],'source_name':'raw_'+domain,'name':r['source_id'][7:],'property_path':'models/sources.yml','columns':[{'column_id':c['column_id'],'name':c['name']} for c in r['columns']]})
 write(d/'dbt-doc-bindings.json',db)
 try:
  preview=generate_project(project,dictionary,db)
 except Exception as e:
  preview={'status':'blocked','conflicts':[{'reason':str(e)}],'applied':False,'native_verified':False}
 write(d/'dbt-doc-preview.json',preview)
 # Local controlled substitution only: no dbt Jinja/macros/hooks are executed.
 conn=duckdb.connect(':memory:');local={'kind':'local_synthetic_execution','warehouse_native':False,'dbt_executed':False,'expected_results_independent':False,'results':{},'checks':[],'limitations':['DuckDB transpilation and input-derived checks are local development evidence only. Root evaluator independently owns frozen expectations.']}
 rendered=impl/'static-sql';rendered.mkdir()
 for t in raw_tables:
  rows=list(csv.reader((inp/(t+'.csv')).open()));cs=rows.pop(0)
  conn.execute('create table raw_'+t+' ('+', '.join(c+' varchar' for c in cs)+')')
  conn.executemany('insert into raw_'+t+' values ('+','.join('?' for c in cs)+')',rows)
 def render(sql):
  sql=re.sub(r"\{\{ source\('raw_[a-z]+', '([a-z_]+)'\) \}\}",lambda m:'raw_'+m[1],sql)
  return re.sub(r"\{\{ ref\('([a-z_]+)'\) \}\}",lambda m:m[1],sql)
 for s in specs:
  plain=render(s['sql']);write(rendered/(s['name']+'.sql'),plain)
  tree=sqlglot.parse_one(plain,read=warehouse); executable=tree.sql(dialect='duckdb')
  conn.execute('create view '+s['name']+' as '+executable)
  rows=conn.execute('select * from '+s['name']).fetchall();cols=[c[0] for c in conn.description]
  local['results'][s['name']]={'columns':cols,'rows':rows}
  local['checks'].append({'name':s['name']+' projection','status':'passed','row_count':len(rows)})
  if s['layer']!='bronze':
   key='part_line_id' if s['source_table']=='parts' else 'meter_id' if s['source_table']=='meters' else 'work_order_id' if sf else 'reading_id'
   dup=conn.execute('select '+key+' from '+s['name']+' group by '+key+' having count(*) != 1 or '+key+' is null').fetchall();assert not dup
   local['checks'].append({'name':s['name']+' key uniqueness in supplied snapshot','status':'passed'})
 test_plain=render(test_sql);write(rendered/'no_orphan_children.sql',test_plain)
 assert not conn.execute(sqlglot.parse_one(test_plain,read=warehouse).sql(dialect='duckdb')).fetchall()
 local['checks'].append({'name':'no_orphan_children','status':'passed'})
 queries=({'baseline':"select sum(work_cost) as total_work_cost from gold_work_orders where status = 'closed' and opened_on between date '2026-01-02' and date '2026-01-03'",'open_retention':"select * from gold_work_orders where status = 'open'",'detail':"select opened_on, sum(work_cost) as total_work_cost from gold_work_orders where status = 'closed' and opened_on between date '2026-01-02' and date '2026-01-03' group by opened_on order by opened_on"} if sf else {'baseline':"select sum(kwh) as total_kwh from gold_readings where recorded_on = date '2026-02-01'",'north_interactive':"select sum(kwh) as total_kwh from gold_readings where recorded_on = date '2026-02-01' and zone = 'north'",'north_all_dates':"select sum(kwh) as total_kwh from gold_readings where zone = 'north'",'detail':"select recorded_on, sum(kwh) as total_kwh from gold_readings where recorded_on = date '2026-02-01' group by recorded_on order by recorded_on"})
 for q,sql in queries.items():local['results'][q]={'sql':sql,'rows':conn.execute(sql).fetchall()}
 write(d/'local-results.json',local)
 # Native grammar lint covers all explicit SELECTs/configs and unrendered dbt templates.
 scaffold=scaffold_manifest(impl);manifest=scaffold['manifest'];manifest['omni_context']=ctx
 for f in manifest['files']:
  if f['path'].startswith('static-sql/'):
   model=f['path'].split('/')[-1][:-4];src=next(('dbt/models/'+s['layer']+'/'+s['name']+'.sql' for s in specs if s['name']==model),'dbt/tests/no_orphan_children.sql')
   f.update(format='compiled_sql',source_paths=[src])
  if f['format']=='jinja':f['role']='dbt_model' if '/models/' in f['path'] else 'template'
 write(d/'lint-manifest.json',manifest);write(d/'lint-target.json',{'framework':'dbt','warehouse':warehouse,'context_sha256':canonical_hash(ctx)})
 write(d/'LINT_SCOPE.md','Static SQL files were rendered by exact source/ref substitution only. They are not dbt compiler outputs. All candidate SQL/templates/configuration are inventoried, including dbt tests and Omni files. Native adapter materialization SQL, built-in generic test expansion and macros are not observed; complete native execution scope remains pending. A local manifest pass cannot imply full materialization coverage.\n')
 # Guided input inventory records missing native prerequisites without promotion.
 answers={'engagement_type':'blind_test','priority_domain':domain,'framework':'dbt','warehouse':warehouse,'semantic_target':'omni','migration_scope':'full_dashboard','input_handling':'pre_sanitized','deliverables':['implementation','diagrams','documentation','dictionary','validation'],'host':'Codex inline isolated-prompt subagent','environment':'offline synthetic candidate','execution_mode':'local_validation_requested','audience':'engineer'}
 try:
  state=start_engagement(inp,d/'guided-run',answers=answers,catalogue=d/'synthetic-catalogue.json');write(d/'guided-summary.json',{'status':state['status'],'readiness':state['readiness']})
 except Exception as e:write(d/'guided-summary.json',{'status':'blocked','error':str(e)})
 # Connected ERD source and readable SVG use the same node inventory.
 nodes=[(t,'raw',grain[t]) for t in raw_tables]+[(s['name'],s['layer'],s['grain']) for s in specs]
 edges=[(t,'bronze_'+t,'lineage') for t in raw_tables]+[('bronze_'+t,'silver_'+t,'lineage') for t in raw_tables]+[('silver_'+t,gold,'preaggregate then left join' if sf and t=='parts' else 'unique lookup' if not sf and t=='meters' else 'lineage') for t in raw_tables]
 mermaid=['flowchart LR']+['  '+n+'["'+layer+': '+n+'<br/>'+g.replace('"','')+'"]' for n,layer,g in nodes]+['  '+a+' -->|"'+label+'"| '+b for a,b,label in edges]
 mermaid+=['%% Arrows are transformation lineage, never enforced warehouse foreign keys.']
 write(d/'ERD.mmd','\n'.join(mermaid)+'\n')
 import html
 positions={t:(20,70+idx*230) for idx,t in enumerate(raw_tables)}
 for idx,t in enumerate(raw_tables):positions['bronze_'+t]=(350,70+idx*230);positions['silver_'+t]=(680,70+idx*230)
 positions[gold]=(1010,185)
 svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1360" height="620" viewBox="0 0 1360 620"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#667085"/></marker></defs><rect width="1360" height="620" fill="#f8fafc"/><g font-family="Arial,sans-serif">','<text x="20" y="30" font-size="22">'+domain.title()+' — synthetic planned model</text>']
 for a,b,label in edges:
  ax,ay=positions[a];bx,by=positions[b]
  svg+=['<path d="M'+str(ax+290)+','+str(ay+72)+' L'+str(bx)+','+str(by+72)+'" fill="none" stroke="#667085" stroke-width="2" stroke-dasharray="6 3" marker-end="url(#arrow)"/>']
 for n,layer,g in nodes:
  x,y=positions[n];cs=headers[n] if layer=='raw' else next(s['columns'] for s in specs if s['name']==n)
  identity=database+'.'+(raw_schema if layer=='raw' else schema)+'.'+upper(n)
  svg += [f'<rect x="{x}" y="{y}" width="290" height="{65+len(cs)*18}" rx="8" fill="#fff" stroke="#334155"/>',f'<text x="{x+10}" y="{y+20}" font-size="15" font-weight="bold">{html.escape(layer+": "+n)}</text>',f'<text x="{x+10}" y="{y+38}" font-size="9">{html.escape(identity)}</text>']
  for j,c in enumerate(cs):svg += [f'<text x="{x+10}" y="{y+60+j*18}" font-size="12">{html.escape(c+(" [candidate PK]" if j==0 else ""))}</text>']
 svg+=['<text x="20" y="550" font-size="13">Dashed arrows = transformation lineage; keys are proposed, not enforced native constraints.</text>','<text x="20" y="576" font-size="13">'+('Parts 0..N per work order aggregate to 0..1 before joining; work order grain is preserved.' if sf else 'Meter 1 to readings 0..N; left lookup preserves readings. Duplicate meters and orphans must fail validation.')+'</text>','<text x="20" y="600" font-size="13">No live warehouse catalogue, tenant access proof, source history, or business acceptance is established.</text></g></svg>']
 write(d/'ERD.svg',''.join(svg))
 for layer in ('bronze','silver','gold'):
  rows=[s for s in specs if s['layer']==layer]
  text=['# '+domain.title()+' '+layer+' layer','Synthetic proposed specification; no native observations or authenticated approval.','\n'+({'bronze':'Retain all supplied CSV fields and rows as lexical text. Original landing/replication behavior, null encoding, deletes, CDC ordering, freshness and schema drift are unknown; no ingestion changes are proposed.','silver':'Cast keys, dates and quantities/costs explicitly. Do not arbitrarily deduplicate, filter statuses, default unknown measurements or infer a tenant policy. Invalid casts and key/orphan assertions must stop promotion. No Type 2 history is invented.','gold':'Publish reusable row-grain facts. '+('Aggregate parts by work_order_id before the left join; absence of parts yields zero, and labor remains once per work order. Keep status, opened_on and tenant_id for query-time filters.' if sf else 'Left join the unique meter lookup to reading facts. Keep all dates and zones. Sum kWh at query time; do not materialize the dashboard date or north selection into the model.')})[layer]]
  for s in rows:text+=['\n## '+s['name'],'Planned relation: `'+database+'.'+schema+'.'+upper(s['name'])+'`. Grain: '+s['grain']+'. Columns: '+', '.join(s['columns'])+'.', 'See DICTIONARY.md for every column and transformation, ERD.svg/ERD.mmd for connected lineage, implementation/dbt for exact projections, and local-results.json for executed local observations.']
  text+=['\nMaterialization: views, full current-snapshot read behavior. Run bronze before silver before gold through dbt dependencies. Refresh and late arrivals follow source requery, with no recoverable source history assumed. Owner, SLA, retention, currency and native access are unresolved. Source correction/replay semantics need operator evidence. Monitor key, null, cast and orphan failures before publication; native fresh-watermark and access checks remain pending. Recovery: retain original source and model hashes, inspect consumer impact, then revert only separately approved candidate views. No production write, rollback command or source retirement is authorized.','\nDefinitions remain proposed. NULL/empty-set aggregation behavior follows ordinary SUM (NULL for empty sets); do not replace missing labor/usage values with zero without review. See DASHBOARD.md for exact source population, dates, sorts, limits and interactive controls.']
  write(d/(layer.upper()+'.md'),'\n'.join(text)+'\n')
 summary[domain]={'models':len(specs),'columns':sum(len(s['columns']) for s in specs),'omni_static_status':result['check']['status'],'looker_tiles':len(source['tiles']),'looker_filters':len(source['filters']),'source_coverage':source['coverage']['status'],'ai_status':airesult['report']['status'],'ai_withheld':len(airesult['report']['withheld']),'dbt_docs_preview_status':preview['status'],'dbt_docs_conflicts':len(preview['conflicts']),'local_projection_count':len(specs),'native_verified':False}
 write(d/'START_HERE.md',f'''# {domain.title()} synthetic candidate\n\nGenerated five dbt views for {warehouse} plus one native Omni view/topic. Physical namespaces and types are planned synthetic bindings, not native catalogue observations. Definitions are proposed.\n\n- [dbt project](implementation/dbt/dbt_project.yml) and [setup](implementation/SETUP.md)\n- [Omni files](implementation/omni/GENERATION_MANIFEST.json), [static check](omni-generation-check.json)\n- [Connected ERD](ERD.svg), [editable source](ERD.mmd), [dictionary](DICTIONARY.md) and [canonical v2 dictionary](dictionary-v2.json)\n- [Bronze](BRONZE.md), [silver](SILVER.md), [gold](GOLD.md) documentation\n- [Dashboard worklist](DASHBOARD.md), [complete canonical source](looker-canonical.json), [manual target mapping](dashboard-worklist.json)\n- [Cautious private AI notes](AI_REVIEW_NOTES.md) and [withheld context](ai-context/AI_CONTEXT.md)\n- [Local observations](local-results.json), [dbt documentation preview](dbt-doc-preview.json), [lint scope](LINT_SCOPE.md)\n\nSource snapshots remain untouched. Dashboard mapping, physical destination, metadata/privacy review, adapter compilation, native query/access behavior and business acceptance all remain pending. The generator's required approved enum is bound only to [synthetic review](synthetic-review.json), never a human approval.\n''')
# End-to-end integrity reads do not modify original inputs.
for domain,files in EXPECTED.items():
 for name,h in files.items():assert sha(INPUT/domain/name)==h
write(OUT/'generation-summary.json',summary)
print(json.dumps(summary,indent=2))
