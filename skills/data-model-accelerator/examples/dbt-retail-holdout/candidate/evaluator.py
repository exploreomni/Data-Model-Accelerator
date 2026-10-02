"""Bounded synthetic retail evaluation of reviewed candidate dbt SQL.

Does not execute source repository macros, use a native Snowflake connection, or
claim general dbt interpretation. Native local dbt validation is a separate run.
"""
from __future__ import annotations
import argparse
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
import duckdb
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parent
CONTRACT = json.loads((ROOT / 'contract.json').read_text())
MODELS = json.loads((ROOT / 'model-map.json').read_text())
REPORT = json.loads((ROOT / 'semantic/report-map.json').read_text())
SOURCE_NAMES = {'orders':'ORDER_CDC','order_lines':'ORDER_LINE_CDC',
                'fulfillments':'FULFILLMENT_CDC','returns':'RETURN_CDC'}
MAX_INT = 2**63-1

class ValidationError(ValueError):
    """No outputs are accepted when input or caller context violates the contract."""


def iso(value, label):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):
        raise ValidationError(label + ': canonical ISO date required')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(label + ': invalid calendar date') from exc
    if parsed.isoformat()!=value: raise ValidationError(label + ': noncanonical date')
    return parsed


def validate_params(params):
    if not isinstance(params,dict): raise ValidationError('params must be a mapping')
    allowed=set(CONTRACT['report']['defaults'])|{'persona_tenant','authorized'}
    if set(params)-allowed: raise ValidationError('Unsupported report parameters: '+repr(sorted(set(params)-allowed)))
    context=dict(CONTRACT['report']['defaults'],**params)
    tenant=context['tenant']
    if tenant not in CONTRACT['report']['allowed_tenants']: raise ValidationError('Unknown or missing tenant')
    # Omitted persona is the local synthetic caller default; explicit null fails.
    if context.get('persona_tenant',tenant)!=tenant: raise ValidationError('Persona tenant mismatch or missing explicit persona')
    if context.get('authorized',True) is not True: raise ValidationError('Authorization denied or invalid')
    if context['status'] not in CONTRACT['report']['allowed_statuses']: raise ValidationError('Unknown or missing status')
    if not isinstance(context['product'],str): raise ValidationError('Product must be a string')
    if iso(context['start_date'],'start_date')>iso(context['end_date'],'end_date'):
        raise ValidationError('Reversed date interval')
    return context


def validate_raw(raw):
    if not isinstance(raw,dict) or set(raw)!={'origin','snapshot_at','tables'} or raw['origin']!='synthetic':
        raise ValidationError('Synthetic full-capture envelope required')
    if not isinstance(raw['snapshot_at'],str) or not raw['snapshot_at']:
        raise ValidationError('Capture watermark required')
    tables=raw['tables']
    if not isinstance(tables,dict) or set(tables)!=set(CONTRACT['raw_columns']):
        raise ValidationError('Raw table inventory mismatch')
    current={}
    for table,columns in CONTRACT['raw_columns'].items():
        rows=tables[table]
        if not isinstance(rows,list): raise ValidationError(table+': rows must be a list')
        versions={};latest={};keys=CONTRACT['cdc_keys'][table]
        for index,row in enumerate(rows):
            if not isinstance(row,dict) or set(row)!=set(columns): raise ValidationError(table+': raw column inventory mismatch')
            for name,dtype in columns.items():
                value=row[name]
                if dtype=='BOOLEAN':
                    if type(value) is not bool: raise ValidationError(table+'.'+name+': Boolean required')
                elif dtype.startswith('NUMBER'):
                    if type(value) is not int or not -MAX_INT-1<=value<=MAX_INT:
                        raise ValidationError(table+'.'+name+': signed 64-bit integer required')
                    if name in ('SEQUENCE','QUANTITY','UNIT_PRICE_CENTS') and value<=0:
                        raise ValidationError(table+'.'+name+': positive integer required')
                    if name in ('DISCOUNT_CENTS','REFUND_CENTS') and value<0:
                        raise ValidationError(table+'.'+name+': nonnegative integer required')
                elif name=='ORDER_DATE': iso(value,table+'.'+name)
                elif not isinstance(value,str) or not value:
                    raise ValidationError(table+'.'+name+': nonempty text required')
                elif name.endswith('_ID') and not re.fullmatch(r'[A-Za-z0-9]+',value):
                    raise ValidationError(table+'.'+name+': ASCII alphanumeric identifier required')
            if table=='ORDER_LINE_CDC':
                gross=row['QUANTITY']*row['UNIT_PRICE_CENTS']
                if row['DISCOUNT_CENTS']>gross: raise ValidationError('Line discount exceeds gross amount')
            key=tuple(row[k] for k in keys);version=key+(row['SEQUENCE'],)
            payload=tuple(row[c] for c in columns)
            if version in versions and versions[version]!=payload:
                raise ValidationError(table+': conflicting payload at key/sequence '+repr(version))
            versions[version]=payload
            if key not in latest or row['SEQUENCE']>latest[key]['SEQUENCE']: latest[key]=row
        current[table]={key:row for key,row in latest.items() if not row['IS_DELETED']}
    orders=current['ORDER_CDC'];lines=current['ORDER_LINE_CDC']
    for key,line in lines.items():
        if key[:2] not in orders: raise ValidationError('Current line has orphan order: '+repr(key))
    totals={'FULFILLMENT_CDC':{},'RETURN_CDC':{}}
    for table in totals:
        for event in current[table].values():
            key=tuple(event[c] for c in ('TENANT_ID','ORDER_ID','LINE_ID'))
            if key not in lines: raise ValidationError(table+': current event has orphan line '+repr(key))
            totals[table][key]=totals[table].get(key,0)+event['QUANTITY']
    for key,line in lines.items():
        fulfilled=totals['FULFILLMENT_CDC'].get(key,0);returned=totals['RETURN_CDC'].get(key,0)
        if fulfilled>line['QUANTITY']: raise ValidationError('Fulfillment exceeds ordered quantity: '+repr(key))
        if returned>fulfilled: raise ValidationError('Returns exceed fulfilled quantity: '+repr(key))
    return tables


def connect(path=None):
    config={'enable_external_access':False,'autoinstall_known_extensions':False,'autoload_known_extensions':False}
    con=duckdb.connect(str(path) if path else ':memory:',config=config)
    # ATTACH an in-memory catalogue before disabling access is unnecessary for file mode.
    if not path:
        con.close()
        con=duckdb.connect(':memory:',config={'autoinstall_known_extensions':False,'autoload_known_extensions':False})
        con.execute("ATTACH ':memory:' AS DMA_RETAIL")
        con.execute('SET enable_external_access=false')
    return con


def load_raw(con,tables):
    con.execute('CREATE SCHEMA IF NOT EXISTS DMA_RETAIL.RAW')
    for table,cols in CONTRACT['raw_columns'].items():
        types={c:('DECIMAL(38,0)' if t.startswith('NUMBER') else t) for c,t in cols.items()}
        con.execute('CREATE OR REPLACE TABLE DMA_RETAIL.RAW.'+table+' ('+', '.join(c+' '+t for c,t in types.items())+')')
        if tables[table]: con.executemany('INSERT INTO DMA_RETAIL.RAW.'+table+' VALUES ('+','.join('?' for _ in cols)+')',[[row[c] for c in cols] for row in tables[table]])


def render(path,params):
    def ref(name):
        m=MODELS[name];return 'DMA_RETAIL.'+m['schema']+'.'+m['alias']
    def source(source_name,table):
        if source_name!='retail_raw' or table not in SOURCE_NAMES: raise ValidationError('Unbound source')
        return 'DMA_RETAIL.RAW.'+SOURCE_NAMES[table]
    def sql_literal(value):
        if not isinstance(value,str): raise ValidationError('SQL literal must be text')
        return "'"+value.replace("'","''")+"'"
    env=Environment(undefined=StrictUndefined)
    # Only this authored template subset is evaluated, without arbitrary includes.
    env.globals.update(ref=ref,source=source,var=lambda k,default=None:params.get(k,default),
                       sql_literal=sql_literal,config=lambda **kw:'',validate_report_context=lambda:'')
    return env.from_string(Path(path).read_text()).render()


def rows(con,sql):
    cursor=con.execute(sql);names=[d[0].upper() for d in cursor.description]
    def normal(v):
        if isinstance(v,date): return v.isoformat()
        if isinstance(v,Decimal): return int(v) if v==v.to_integral_value() else float(v)
        return v
    return [dict(zip(names,map(normal,row))) for row in cursor.fetchall()]


def evaluate(raw_data,params):
    """Return exact uppercase gold/report interfaces; invalid input raises before output."""
    context=validate_params(params);tables=validate_raw(raw_data)
    con=connect()
    try:
        load_raw(con,tables)
        for schema in ('SILVER','GOLD'):con.execute('CREATE SCHEMA DMA_RETAIL.'+schema)
        for path in sorted((ROOT/'dbt/tests').glob('source_*.sql')):
            if con.execute(render(path,context)).fetchone(): raise ValidationError('Source assertion failed: '+path.stem)
        for name,model in MODELS.items():
            con.execute('CREATE TABLE DMA_RETAIL.'+model['schema']+'.'+model['alias']+' AS '+render(ROOT/model['path'],context))
        for name in ('current_references','quantity_and_money_contract','fact_coverage'):
            if con.execute(render(ROOT/'dbt/tests'/f'{name}.sql',context)).fetchone(): raise ValidationError('Model assertion failed: '+name)
        gold=rows(con,'SELECT * FROM DMA_RETAIL.GOLD.FCT_ORDER_LINE_FULFILLMENT ORDER BY TENANT_ID,ORDER_ID,LINE_ID')
        report=rows(con,'SELECT * FROM ('+render(ROOT/REPORT['path'],context)+') r ORDER BY ORDER_MONTH,PRODUCT_ID')
        for section,data in (('gold',gold),('report',report)):
            if any(list(r)!=CONTRACT[section]['columns'] for r in data):raise ValidationError('Output interface mismatch: '+section)
        if len({(r['TENANT_ID'],r['ORDER_ID'],r['LINE_ID']) for r in gold})!=len(gold):raise ValidationError('Gold grain violation')
        return {'gold':gold,'report':report}
    finally:con.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--params',default='{}');p.add_argument('--output',type=Path)
    args=p.parse_args();result=evaluate(json.loads(args.raw.read_text()),json.loads(args.params));text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    else:print(text,end='')
if __name__=='__main__':main()
