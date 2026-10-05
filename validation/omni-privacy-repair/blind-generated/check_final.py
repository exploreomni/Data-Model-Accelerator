"""Offline final-byte observation; no dbt or native warehouse execution."""
from pathlib import Path
import csv,hashlib,json,re,sys
import duckdb,sqlglot
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'skills/data-model-accelerator/scripts'))
from sensitive_data import scan_bytes
from data_dictionary_v2 import validate_dictionary
from omni_contract import check_model

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def render(sql):
 sql=re.sub(r"\{\{ source\('raw_[a-z]+', '([a-z_]+)'\) \}\}",lambda m:'raw_'+m[1],sql)
 return re.sub(r"\{\{ ref\('([a-z_]+)'\) \}\}",lambda m:m[1],sql)
for domain in ('maintenance','energy'):
 p=OUT/domain; inp=ROOT/'validation/omni-privacy-repair/blind-inputs'/domain
 intake=json.loads((inp/'intake.json').read_text());wh=intake['warehouse'];conn=duckdb.connect(':memory:')
 sources=['work_orders','parts'] if domain=='maintenance' else ['readings','meters']
 for name in sources:
  rows=list(csv.reader((inp/(name+'.csv')).open()));cols=rows.pop(0)
  conn.execute('create table raw_'+name+' ('+', '.join(c+' varchar' for c in cols)+')')
  conn.executemany('insert into raw_'+name+' values ('+','.join('?' for c in cols)+')',rows)
 report={'kind':'final_byte_local_observations','native_verified':False,'dbt_executed':False,'expectations_independent':False,'model_files':{},'source_files':{t+'.csv':sha(inp/(t+'.csv')) for t in sources},'models':[],'checks':[]}
 dictionary=json.loads((p/'dictionary-v2.json').read_text());assert not validate_dictionary(dictionary)
 for layer in ('bronze','silver','gold'):
  for sqlpath in sorted((p/'implementation/dbt/models'/layer).glob('*.sql')):
   text=sqlpath.read_text();query=sqlglot.parse_one(render(text),read=wh).sql(dialect='duckdb')
   conn.execute('create view '+sqlpath.stem+' as '+query)
   rows=conn.execute('select * from '+sqlpath.stem).fetchall();cols=[c[0] for c in conn.description]
   expected=next(m for m in dictionary['models'] if m['model_id']==sqlpath.stem)
   assert [c['name'].lower() for c in expected['columns']]==cols
   report['model_files'][sqlpath.relative_to(p).as_posix()]=sha(sqlpath)
   report['models'].append({'name':sqlpath.stem,'row_count':len(rows),'columns':cols,'rows':rows})
 for sqlpath in (p/'implementation/dbt/tests').glob('*.sql'):
  failed=conn.execute(sqlglot.parse_one(render(sqlpath.read_text()),read=wh).sql(dialect='duckdb')).fetchall();assert not failed
  report['checks'].append({'name':sqlpath.stem,'status':'passed'})
 original=json.loads((p/'local-results.json').read_text())
 report['slices']={n:{'sql':r['sql'],'rows':conn.execute(r['sql']).fetchall()} for n,r in original['results'].items() if 'sql' in r}
 ctx=json.loads((p/'omni-context.json').read_text());files=json.loads((p/'omni-files.json').read_text())
 semantic=check_model(files,ctx);assert semantic['status']=='passed'
 report['omni_static_check']=semantic
 (p/'local-checks-final.json').write_text(json.dumps(report,indent=2,sort_keys=True,default=str)+'\n')
 scans=[]
 for f in sorted(p.rglob('*')):
  if f.is_file():
   r=scan_bytes(f.read_bytes(),f.name)
   scans.append({'path':f.relative_to(p).as_posix(),'status':r['status'],'coverage_complete':r['coverage']['complete'],'findings':r['findings']})
 (p/'scan-summary.json').write_text(json.dumps({'kind':'bounded_local_scan_summary','items':scans,'native_access_or_disclosure_approval':False},indent=2,sort_keys=True)+'\n')
 print(domain,'final projections',len(report['models']),'Omni',semantic['status'],'scan statuses',sorted(set(x['status'] for x in scans)))
