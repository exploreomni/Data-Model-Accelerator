"""Independent source-derived oracle; local synthetic SQL execution, not native proof.

This evaluator never imports the generation script or generated local-results.
It supports only literal ref/source templates and SELECT candidates in this pilot.
"""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys

import duckdb
import sqlglot
from sqlglot import exp
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'skills/data-model-accelerator/scripts'))
from ae_common import hash_json
from omni_contract import check_model
from sensitive_data import scan_bytes

REF = re.compile(r"\{\{\s*ref\('([a-z][a-z0-9_]*)'\)\s*\}\}")
SOURCE = re.compile(r"\{\{\s*source\('([a-z][a-z0-9_]*)',\s*'([a-z][a-z0-9_]*)'\)\s*\}\}")


def rows(path):
    with path.open() as f: return list(csv.DictReader(f))


def expected(case, tables):
    if case == 'maintenance':
        parts = {}
        for r in tables['parts']:
            key = int(r['work_order_id'])
            parts[key] = parts.get(key, Decimal(0)) + Decimal(r['quantity'])*Decimal(r['unit_cost'])
        return sorted((int(r['work_order_id']), int(r['tenant_id']), r['opened_on'], r['status'],
                       Decimal(r['labor_cost']) + parts.get(int(r['work_order_id']),Decimal(0))) for r in tables['work_orders'])
    meters = {int(r['meter_id']):r['zone'] for r in tables['meters']}
    return sorted((int(r['reading_id']), int(r['meter_id']), r['recorded_on'], Decimal(r['kwh']),
                   meters.get(int(r['meter_id']))) for r in tables['readings'])


def execute(case, tables, folder):
    db=duckdb.connect()
    for table, values in tables.items():
        names=list(values[0])
        assert all(re.fullmatch(r'[a-z][a-z0-9_]*',name) for name in [table]+names)
        db.execute('create table src_'+table+' ('+', '.join('"'+name+'" varchar' for name in names)+')')
        db.executemany('insert into src_'+table+' values ('+','.join('?' for _ in names)+')',[[v[n] for n in names] for v in values])
    files={p.stem:p for p in (folder/'implementation/dbt/models').rglob('*.sql')}
    pending=dict(files); built=set(); dialect='snowflake' if case=='maintenance' else 'bigquery'
    while pending:
        available=[name for name,p in pending.items() if set(REF.findall(p.read_text()))<=built]
        assert available, 'Unresolved dependency or cycle'
        for name in sorted(available):
            sql=pending.pop(name).read_text()
            sql=REF.sub(lambda m:'"'+m[1]+'"',sql)
            sql=SOURCE.sub(lambda m:'"src_'+m[2]+'"',sql)
            assert '{{' not in sql and '{%' not in sql, 'Unsupported template; not executed'
            expressions=sqlglot.parse(sql,read=dialect)
            assert len(expressions)==1 and isinstance(expressions[0],exp.Select), 'Only SELECT candidates allowed'
            ctes={c.alias for c in expressions[0].find_all(exp.CTE)}
            for table in expressions[0].find_all(exp.Table):
                assert not table.catalog and not table.db and table.name in built|{'src_'+v for v in tables}|ctes
            db.execute('create view "'+name+'" as '+expressions[0].sql(dialect='duckdb'))
            built.add(name)
    query=('select work_order_id,tenant_id,cast(opened_on as varchar),status,work_cost from gold_work_orders order by work_order_id'
        if case=='maintenance' else 'select reading_id,meter_id,cast(recorded_on as varchar),kwh,zone from gold_readings order by reading_id')
    return db,db.execute(query).fetchall(),files


def main():
    manifest=json.loads((HERE/'blind-inputs/MANIFEST.json').read_text())
    output={'schema_version':1,'kind':'independent_blind_generation_evaluation','synthetic':True,
            'native_qualified':False,'dbt_runtime_executed':False,'context_isolation':'Prompt boundary only; shared filesystem.',
            'oracle':'Python decimal arithmetic over raw CSV and declared rules; no generated result imports.',
            'limits':['Reviewer inspected candidate SQL before evaluator authoring; do not call this a fully blinded evaluator.',
                      'Independent expectation snapshots are derived before executing each candidate variation.',
                      'Local DuckDB translation does not establish Snowflake/BigQuery execution or Omni tenant behavior.'], 'cases':[]}
    for case in ('maintenance','energy'):
        source=HERE/'blind-inputs'/case; folder=HERE/'blind-generated'/case
        assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.iterdir())}==manifest[case]
        baseline={p.stem:rows(p) for p in source.glob('*.csv')}
        counter={k:[dict(r) for r in values] for k,values in baseline.items()}
        if case=='maintenance':
            counter['parts'] += [{'part_line_id':'14','work_order_id':'1','quantity':'1','unit_cost':'7'},
                                 {'part_line_id':'15','work_order_id':'2','quantity':'4','unit_cost':'2'}]
        else:
            counter['meters'].append({'meter_id':'103','zone':'north'})
            counter['readings'].append({'reading_id':'24','meter_id':'103','recorded_on':'2026-02-03','kwh':'9'})
        validations=[]
        for scenario,tables in [('baseline',baseline),('unseen_counterfactual',counter)]:
            oracle=expected(case,tables)
            frozen_hash=hashlib.sha256(json.dumps(oracle,default=str).encode()).hexdigest()
            db,actual,files=execute(case,tables,folder)
            assert actual==oracle,(case,scenario,'population/metric mismatch')
            if case=='maintenance':
                total=db.execute("select sum(work_cost) from gold_work_orders where status='closed' and opened_on between date '2026-01-02' and date '2026-01-03'").fetchone()[0]
                assert total==sum(r[4] for r in oracle if r[3]=='closed' and '2026-01-02'<=r[2]<='2026-01-03')
                assert db.execute("select count(*) from gold_work_orders where status='open'").fetchone()[0]==1
            else:
                total=db.execute("select sum(kwh) from gold_readings where recorded_on=date '2026-02-01' and zone='north'").fetchone()[0]
                assert total==sum(r[3] for r in oracle if r[2]=='2026-02-01' and r[4]=='north')
            validations.append({'scenario':scenario,'rows':len(actual),'expected_sha256':frozen_hash,'status':'passed'})
            db.close()
        # Deliberately duplicate a source key: the actual authored uniqueness test must detect it.
        negative={k:[dict(r) for r in values] for k,values in baseline.items()}
        table,key,model=('work_orders','work_order_id','silver_work_orders') if case=='maintenance' else ('meters','meter_id','silver_meters')
        negative[table].append(dict(negative[table][0]));db,_,_=execute(case,negative,folder)
        properties=yaml.safe_load((folder/'implementation/dbt/models/proposed-properties.yml').read_text())
        column=next(c for m in properties['models'] if m['name']==model for c in m['columns'] if c['name']==key)
        assert 'unique' in column['data_tests']
        assert db.execute('select '+key+' from '+model+' group by '+key+' having count(*)>1').fetchall()
        db.close();validations.append({'scenario':'duplicate_source_key_negative','status':'detected'})
        directory=folder/'implementation/omni'
        model_files={p.name:p.read_text() for p in directory.iterdir() if p.suffix in ('.view','.topic') or p.name in ('model','relationships')}
        static=check_model(model_files,json.loads((folder/'omni-context.json').read_text()))
        assert static['status']=='passed'
        source_export=json.loads((source/'looker-dashboard.json').read_text())
        worklist=json.loads((folder/'dashboard-worklist.json').read_text())
        assert set(worklist['tiles'])=={t['id'] for t in source_export['dashboard_elements']}
        assert set(worklist['filters'])=={t['id'] for t in source_export['dashboard_filters']}
        assert all(e['status']=='manual' for e in worklist['tiles'].values())
        for required in ('ERD.svg','DICTIONARY.md','BRONZE.md','SILVER.md','GOLD.md','START_HERE.md','ai-context/AI_CONTEXT.json'):
            assert (folder/required).is_file(),required
        output['cases'].append({'domain':case,'validation':validations,'models':len(files),
            'candidate_sql_sha256':hash_json({name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}),
            'omni_static':'passed','dashboard_inventory':'3 tiles and 1 filter preserved; native construction pending',
            'status':'passed'})
    output['status']='passed'
    body=json.dumps(output,indent=2,sort_keys=True).encode()+b'\n'
    assert scan_bytes(body,'independent-results.json')['status']=='clear'
    (HERE/'independent-results.json').write_bytes(body)
    print(json.dumps({'status':'passed','domains':2,'scenarios':6,'native_qualified':False}))


if __name__=='__main__':main()
