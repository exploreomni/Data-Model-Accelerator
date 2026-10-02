from pathlib import Path
import json,hashlib
base=Path('/private/tmp/dma-dbt-holdout/input')
def write(rel,obj):
 p=base/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,indent=2)+'\n')
columns={
 'ORDER_CDC':{'TENANT_ID':'VARCHAR','ORDER_ID':'VARCHAR','ORDER_DATE':'VARCHAR','STATUS':'VARCHAR','SEQUENCE':'NUMBER(38,0)','IS_DELETED':'BOOLEAN'},
 'ORDER_LINE_CDC':{'TENANT_ID':'VARCHAR','ORDER_ID':'VARCHAR','LINE_ID':'VARCHAR','PRODUCT_ID':'VARCHAR','QUANTITY':'NUMBER(38,0)','UNIT_PRICE_CENTS':'NUMBER(38,0)','DISCOUNT_CENTS':'NUMBER(38,0)','SEQUENCE':'NUMBER(38,0)','IS_DELETED':'BOOLEAN'},
 'FULFILLMENT_CDC':{'TENANT_ID':'VARCHAR','FULFILLMENT_ID':'VARCHAR','ORDER_ID':'VARCHAR','LINE_ID':'VARCHAR','QUANTITY':'NUMBER(38,0)','SEQUENCE':'NUMBER(38,0)','IS_DELETED':'BOOLEAN'},
 'RETURN_CDC':{'TENANT_ID':'VARCHAR','RETURN_ID':'VARCHAR','ORDER_ID':'VARCHAR','LINE_ID':'VARCHAR','QUANTITY':'NUMBER(38,0)','REFUND_CENTS':'NUMBER(38,0)','SEQUENCE':'NUMBER(38,0)','IS_DELETED':'BOOLEAN'}}
def rows(table,values):return [dict(zip(columns[table],row)) for row in values]
raw={'origin':'synthetic','snapshot_at':'2026-09-11T12:00:00Z','tables':{
 'ORDER_CDC':rows('ORDER_CDC',[
 ['A','O1','2026-04-01','completed',1,False],['A','O2','2026-04-02','pending',1,False],['A','O3','2026-04-03','completed',1,False],['A','O4','2026-04-04','completed',1,False],['A','O4','2026-04-04','cancelled',2,False],['B','O1','2026-04-01','completed',1,False]]),
 'ORDER_LINE_CDC':rows('ORDER_LINE_CDC',[
 ['A','O1','L1','P1',3,1000,300,1,False],['A','O1','L1','P1',3,1000,600,2,False],['A','O1','L1','P1',3,1000,600,2,False],
 ['A','O1','L2','P2',2,2500,500,1,False],['A','O2','L1','P1',1,1000,0,1,False],['A','O3','L1','P3',1,2000,0,1,False],
 ['A','O3','L2','P2',1,500,0,1,False],['A','O3','L2','P2',1,500,0,2,True],['A','O4','L1','P2',1,2500,0,1,False],['A','O4','L1','P2',1,2500,0,2,True],['B','O1','L1','P1',2,1500,0,1,False]]),
 'FULFILLMENT_CDC':rows('FULFILLMENT_CDC',[
 ['A','F1','O1','L1',1,1,False],['A','F1','O1','L1',2,2,False],['A','F2','O1','L1',1,1,False],['A','F3','O1','L2',1,1,False],['A','F4','O1','L2',1,1,False],['A','F4','O1','L2',1,2,True],['A','F5','O3','L1',1,1,False],['B','F1','O1','L1',1,1,False]]),
 'RETURN_CDC':rows('RETURN_CDC',[
 ['A','R1','O1','L1',1,800,1,False],['A','R2','O1','L1',1,900,1,False],['A','R2','O1','L1',1,700,2,False],['A','R3','O1','L2',1,2250,1,False],['A','R4','O3','L1',1,2000,1,False],['A','R4','O3','L1',1,2000,2,True],['B','R1','O1','L1',1,1500,1,False]])}}
write('raw-data.json',raw)
contract={'schema_version':1,'kind':'synthetic_dbt_holdout_contract','domain':'retail_order_line_fulfillment_returns','namespace':{'provider':'snowflake','platform_instance':'DMA_RETAIL_SYNTHETIC','connection_id':'retail-source-synthetic','database':'DMA_RETAIL','raw_schema':'RAW'},
 'raw_columns':columns,'cdc_keys':{'ORDER_CDC':['TENANT_ID','ORDER_ID'],'ORDER_LINE_CDC':['TENANT_ID','ORDER_ID','LINE_ID'],'FULFILLMENT_CDC':['TENANT_ID','FULFILLMENT_ID'],'RETURN_CDC':['TENANT_ID','RETURN_ID']},
 'gold':{'model_name':'fct_order_line_fulfillment','grain':['TENANT_ID','ORDER_ID','LINE_ID'],'columns':['LINE_KEY','TENANT_ID','ORDER_ID','LINE_ID','PRODUCT_ID','ORDER_DATE','ORDER_STATUS','ORDERED_QUANTITY','FULFILLED_QUANTITY','RETURNED_QUANTITY','LINE_NET_CENTS','REFUND_CENTS','RETAINED_REVENUE_CENTS'],'column_units':{'LINE_NET_CENTS':'USD cents','REFUND_CENTS':'USD cents','RETAINED_REVENUE_CENTS':'USD cents'}},
 'report':{'model_name':'retail_fulfillment_summary','grain':['ORDER_MONTH','PRODUCT_ID'],'columns':['ORDER_MONTH','PRODUCT_ID','ORDERED_QUANTITY','FULFILLED_QUANTITY','RETURNED_QUANTITY','LINE_NET_CENTS','REFUND_CENTS','RETAINED_REVENUE_CENTS','FULFILLMENT_RATE'],
 'defaults':{'tenant':'A','start_date':'2026-04-01','end_date':'2026-04-04','status':'completed','product':'ALL'},'allowed_tenants':['A','B'],'allowed_statuses':['completed','pending','cancelled'],'product_domain':'any string; ALL means no product filter','date_bounds':'start inclusive, end exclusive','ratio':'SUM(FULFILLED_QUANTITY)/SUM(ORDERED_QUANTITY), null for zero denominator; compare tolerance1e-12'},
 'security':'Report tenant is authorized harness context, persona_tenant must match tenant and authorized must be true; source WHERE is not proven warehouse RLS. Gold retains both tenants and all current statuses.',
 'reusable_staging':['stg_orders','stg_order_lines'],'native_runtime':'Unavailable; authored source dbt not previously executed or business-approved.'}
write('contract.json',contract)
context={'platform_instance':'DMA_RETAIL_SYNTHETIC','connection_id':'retail-source-synthetic','catalog':'DMA_RETAIL','schema':'RAW','location':'synthetic-local-no-cloud-region'}
objects=[{'TABLE_CATALOG':'DMA_RETAIL','TABLE_SCHEMA':'RAW','TABLE_NAME':t,'TABLE_TYPE':'BASE TABLE'} for t in columns]
cols=[]
for table,fields in columns.items():
 for ordinal,(name,dtype) in enumerate(fields.items(),1):cols.append({'TABLE_CATALOG':'DMA_RETAIL','TABLE_SCHEMA':'RAW','TABLE_NAME':table,'COLUMN_NAME':name,'ORDINAL_POSITION':ordinal,'DATA_TYPE':'NUMBER' if dtype.startswith('NUMBER') else dtype,'NUMERIC_PRECISION':38 if dtype.startswith('NUMBER') else None,'NUMERIC_SCALE':0 if dtype.startswith('NUMBER') else None,'IS_NULLABLE':'YES'})
for name,values in [('objects',objects),('columns',cols)]:write('catalogue/exports/'+name+'.json',{'origin':'synthetic','captured_at':raw['snapshot_at'],'context':context,'rows':values,'collection_note':'Authored synthetic receipt; no metadata query or account access occurred.'})
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
extractions=[{'extraction_id':n,'scope_id':'retail-raw','component':n,'status':'complete','artifact_path':'exports/'+n+'.json','sha256':sha(base/'catalogue/exports'/f'{n}.json'),'query_id':None,'pagination_complete':True} for n in ('objects','columns')]
catalogue={'schema_version':1,'kind':'warehouse_raw_catalogue','provider':'snowflake','origin':'synthetic','captured_at':raw['snapshot_at'],'context':{'platform_instance':context['platform_instance'],'principal':'synthetic_fixture_author','connection_id':context['connection_id'],'scope':[{'scope_id':'retail-raw','catalog':'DMA_RETAIL','schema':'RAW','location':context['location']}]},'coverage':{'status':'complete_for_visible_scope','gaps':[],'scope_meaning':'Exactly four authored synthetic raw tables; not warehouse discovery.'},'extractions':extractions,'objects':[]}
for table,fields in columns.items():catalogue['objects'].append({'object_id':'snowflake:DMA_RETAIL_SYNTHETIC:DMA_RETAIL.RAW.'+table,'scope_id':'retail-raw','identity':{'catalog':'DMA_RETAIL','schema':'RAW','name':table},'object_type':'BASE TABLE','columns':[{'path':[name],'data_type':dtype,'nullable':True} for name,dtype in fields.items()],'metadata_status':{k:'unknown' for k in ['comments','relationships','ownership','security','replication','statistics']},'evidence':[{'extraction_id':n,'locator':"rows[TABLE_NAME='"+table+"']"} for n in ('objects','columns')],'logical_contract_note':'All values logically required; physical columns permit null. Enforce using data checks. CDC behavior is provided scenario evidence, not inferred from metadata.'})
write('catalogue/warehouse-catalogue.json',catalogue)
write('catalogue/provenance.json',{'origin':'synthetic','captured_at':raw['snapshot_at'],'context':context,'query_execution':False,'exports':{e['artifact_path']:e['sha256'] for e in extractions},'metadata_columns':len(cols),'raw_row_counts':{k:len(v) for k,v in raw['tables'].items()}})
print('Raw rows',{t:len(v) for t,v in raw['tables'].items()},'columns',len(cols))
