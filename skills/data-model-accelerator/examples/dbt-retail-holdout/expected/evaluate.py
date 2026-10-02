"""Independent stdlib oracle; reads frozen contract/data only, never target or SQL."""
from collections import defaultdict
from datetime import date
import argparse
import copy
import json
from pathlib import Path
import re

FIELDS={
 'ORDER_CDC':['TENANT_ID','ORDER_ID','ORDER_DATE','STATUS','SEQUENCE','IS_DELETED'],
 'ORDER_LINE_CDC':['TENANT_ID','ORDER_ID','LINE_ID','PRODUCT_ID','QUANTITY','UNIT_PRICE_CENTS','DISCOUNT_CENTS','SEQUENCE','IS_DELETED'],
 'FULFILLMENT_CDC':['TENANT_ID','FULFILLMENT_ID','ORDER_ID','LINE_ID','QUANTITY','SEQUENCE','IS_DELETED'],
 'RETURN_CDC':['TENANT_ID','RETURN_ID','ORDER_ID','LINE_ID','QUANTITY','REFUND_CENTS','SEQUENCE','IS_DELETED']}
KEYS={'ORDER_CDC':['TENANT_ID','ORDER_ID'],'ORDER_LINE_CDC':['TENANT_ID','ORDER_ID','LINE_ID'],'FULFILLMENT_CDC':['TENANT_ID','FULFILLMENT_ID'],'RETURN_CDC':['TENANT_ID','RETURN_ID']}
DEFAULTS={'tenant':'A','start_date':'2026-04-01','end_date':'2026-04-04','status':'completed','product':'ALL'}
STATUSES={'completed','pending','cancelled'}
MEASURES=['ORDERED_QUANTITY','FULFILLED_QUANTITY','RETURNED_QUANTITY','LINE_NET_CENTS','REFUND_CENTS','RETAINED_REVENUE_CENTS']

class InvalidInput(ValueError):pass

def require(condition,message):
 if not condition:raise InvalidInput(message)

def iso(value):
 require(isinstance(value,str),'Date must be ISO text')
 try:parsed=date.fromisoformat(value)
 except ValueError:raise InvalidInput('Date must be ISO YYYY-MM-DD')
 require(parsed.isoformat()==value,'Date must be ISO YYYY-MM-DD');return parsed

def context(params=None):
 require(params is None or isinstance(params,dict),'Report parameters must be an object')
 provided={} if params is None else params
 require(not set(provided)-set(DEFAULTS)-{'persona_tenant','authorized'},'Unknown report parameter')
 p={**DEFAULTS,**provided}
 require(p['tenant'] in ('A','B'),'Unknown tenant')
 require(p.get('persona_tenant',p['tenant'])==p['tenant'],'Persona tenant mismatch')
 require(p.get('authorized',True) is True,'Authorization denied')
 require(p['status'] in STATUSES,'Unknown status')
 require(isinstance(p['product'],str),'Product must be a string')
 require(iso(p['start_date'])<=iso(p['end_date']),'Reversed report date window')
 return p

def current(raw):
 require(isinstance(raw,dict) and set(raw)=={'origin','snapshot_at','tables'} and raw['origin']=='synthetic','Synthetic raw envelope required')
 require(isinstance(raw['tables'],dict) and set(raw['tables'])==set(FIELDS),'Raw table inventory mismatch')
 selected={}
 for table,fields in FIELDS.items():
  rows=raw['tables'][table];require(isinstance(rows,list),'Raw table rows must be a list')
  versions={};latest={}
  for row in rows:
   require(isinstance(row,dict) and set(row)==set(fields),'Raw field inventory mismatch: '+table)
   for name,value in row.items():
    require(value is not None,'Null raw value: '+table+'.'+name)
    if name.endswith('_ID'):
     require(isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9]+',value) is not None,'Unsafe or missing identity: '+table+'.'+name)
    elif name=='IS_DELETED':require(type(value) is bool,'Boolean tombstone required')
    elif name=='ORDER_DATE':iso(value)
    elif name=='STATUS':require(value in STATUSES,'Unknown raw order status')
    else:
     require(type(value) is int and 0<=value<2**63,'Nonnegative signed 64-bit integer required: '+name)
     if name in ('SEQUENCE','QUANTITY','UNIT_PRICE_CENTS'):require(value>0,'Positive integer required: '+name)
   require(row['TENANT_ID'] in ('A','B'),'Unknown raw tenant')
   if table=='ORDER_LINE_CDC':require(row['DISCOUNT_CENTS']<=row['QUANTITY']*row['UNIT_PRICE_CENTS'],'Line discount exceeds gross')
   key=tuple(row[name] for name in KEYS[table]);version=(*key,row['SEQUENCE'])
   require(version not in versions or versions[version]==row,'Conflicting tied CDC version: '+table+':'+repr(version))
   versions[version]=row
   if key not in latest or row['SEQUENCE']>latest[key]['SEQUENCE']:latest[key]=row
  selected[table]={key:copy.deepcopy(row) for key,row in latest.items() if not row['IS_DELETED']}
 return selected

def evaluate(raw_data,params=None):
 p=context(params);tables=current(raw_data)
 orders=tables['ORDER_CDC'];lines=tables['ORDER_LINE_CDC'];fulfilled=defaultdict(int);returns=defaultdict(lambda:[0,0])
 for key,line in lines.items():require((line['TENANT_ID'],line['ORDER_ID']) in orders,'Current line has no current tenant-scoped order: '+repr(key))
 for event in tables['FULFILLMENT_CDC'].values():
  key=(event['TENANT_ID'],event['ORDER_ID'],event['LINE_ID']);require(key in lines,'Orphan current fulfillment: '+repr(key));fulfilled[key]+=event['QUANTITY']
 for event in tables['RETURN_CDC'].values():
  key=(event['TENANT_ID'],event['ORDER_ID'],event['LINE_ID']);require(key in lines,'Orphan current return: '+repr(key));returns[key][0]+=event['QUANTITY'];returns[key][1]+=event['REFUND_CENTS']
 gold=[]
 for key,line in sorted(lines.items()):
  order=orders[key[:2]];ordered=line['QUANTITY'];sent=fulfilled[key];returned,refund=returns[key]
  require(sent<=ordered,'Fulfilled quantity exceeds ordered quantity: '+repr(key))
  require(returned<=sent,'Returned quantity exceeds fulfilled quantity: '+repr(key))
  net=ordered*line['UNIT_PRICE_CENTS']-line['DISCOUNT_CENTS']
  row={'LINE_KEY':'|'.join(key),'TENANT_ID':key[0],'ORDER_ID':key[1],'LINE_ID':key[2],'PRODUCT_ID':line['PRODUCT_ID'],'ORDER_DATE':order['ORDER_DATE'],'ORDER_STATUS':order['STATUS'],
       'ORDERED_QUANTITY':ordered,'FULFILLED_QUANTITY':sent,'RETURNED_QUANTITY':returned,'LINE_NET_CENTS':net,'REFUND_CENTS':refund,'RETAINED_REVENUE_CENTS':net-refund}
  require(all(-(2**63)<=row[n]<2**63 for n in MEASURES),'Derived value exceeds local signed 64-bit bound')
  gold.append(row)
 groups={}
 for row in gold:
  if row['TENANT_ID']!=p['tenant'] or row['ORDER_STATUS']!=p['status'] or not p['start_date']<=row['ORDER_DATE']<p['end_date'] or (p['product']!='ALL' and row['PRODUCT_ID']!=p['product']):continue
  month=row['ORDER_DATE'][:7]+'-01';key=(month,row['PRODUCT_ID'])
  group=groups.setdefault(key,{'ORDER_MONTH':month,'PRODUCT_ID':row['PRODUCT_ID'],**{name:0 for name in MEASURES}})
  for name in MEASURES:group[name]+=row[name]
 report=[]
 for key,group in sorted(groups.items()):
  group['FULFILLMENT_RATE']=group['FULFILLED_QUANTITY']/group['ORDERED_QUANTITY'] if group['ORDERED_QUANTITY'] else None;report.append(group)
 return {'gold':gold,'report':report}

def mutation(raw,kind):
 result=copy.deepcopy(raw)
 if kind=='duplicate_capture':
  for table,rows in result['tables'].items():result['tables'][table]+=copy.deepcopy(rows)
 elif kind=='late_fulfillment_correction':
  row=next(copy.deepcopy(r) for r in result['tables']['FULFILLMENT_CDC'] if r['TENANT_ID']=='A' and r['FULFILLMENT_ID']=='F1' and r['SEQUENCE']==2)
  row.update(SEQUENCE=3,QUANTITY=1);result['tables']['FULFILLMENT_CDC'].append(row)
 elif kind=='late_return_deletion':
  row=next(copy.deepcopy(r) for r in result['tables']['RETURN_CDC'] if r['TENANT_ID']=='A' and r['RETURN_ID']=='R1')
  row.update(SEQUENCE=2,IS_DELETED=True);result['tables']['RETURN_CDC'].append(row)
 elif kind=='conflicting_superseded_version':
  row=next(copy.deepcopy(r) for r in result['tables']['ORDER_LINE_CDC'] if r['TENANT_ID']=='A' and r['ORDER_ID']=='O1' and r['LINE_ID']=='L1' and r['SEQUENCE']==1)
  row['DISCOUNT_CENTS']+=1;result['tables']['ORDER_LINE_CDC'].append(row)
 elif kind=='orphan_fulfillment':
  result['tables']['FULFILLMENT_CDC'].append({'TENANT_ID':'A','FULFILLMENT_ID':'F9','ORDER_ID':'O1','LINE_ID':'MISSING','QUANTITY':1,'SEQUENCE':1,'IS_DELETED':False})
 else:raise InvalidInput('Unknown private mutation')
 return result

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--params',default='{}');parser.add_argument('--mutation');parser.add_argument('--output',required=True);args=parser.parse_args()
 raw=json.loads(Path(args.input).read_text());raw=mutation(raw,args.mutation) if args.mutation else raw
 try:output={'status':'passed','result':evaluate(raw,json.loads(args.params))}
 except InvalidInput as error:output={'status':'failed','error_type':type(error).__name__,'error':str(error)}
 Path(args.output).write_text(json.dumps(output,indent=2)+'\n')
 raise SystemExit(0 if output['status']=='passed' else 2)
