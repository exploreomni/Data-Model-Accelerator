"""Reviewed synthetic Hex/dbt/Omni replay. No native platform execution.

The SQL and Python interpreters accept a deliberately small positive subset.
They are regression tools for this bundled fixture, not a customer-code sandbox.
"""
import ast
import csv
from datetime import date, datetime
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope
import yaml

CONNECTION_ID = '11111111-1111-4111-8111-111111111111'
PLATFORM = 'DMA_HEX_SYNTHETIC'
RAW_COLUMNS = {
 'INVOICE_CDC': {'TENANT_ID':'VARCHAR','INVOICE_ID':'VARCHAR','CUSTOMER_ID':'VARCHAR','INVOICE_DATE':'DATE','AMOUNT_CENTS':'BIGINT','STATUS':'VARCHAR','IS_DELETED':'BOOLEAN','SEQUENCE':'BIGINT'},
 'PAYMENT_CDC': {'TENANT_ID':'VARCHAR','PAYMENT_ID':'VARCHAR','INVOICE_ID':'VARCHAR','PAID_CENTS':'BIGINT','IS_DELETED':'BOOLEAN','SEQUENCE':'BIGINT'},
 'CUSTOMER_HISTORY': {'TENANT_ID':'VARCHAR','CUSTOMER_ID':'VARCHAR','SEGMENT':'VARCHAR','VALID_FROM':'DATE','VALID_TO':'DATE'},
 'ADJUSTMENTS': {'TENANT_ID':'VARCHAR','INVOICE_ID':'VARCHAR','ADJUSTMENT_CENTS':'BIGINT','REASON':'VARCHAR'},
}
MODEL_MAP = {
 'billing_invoices':('SILVER','BILLING_INVOICES'), 'billing_payments':('SILVER','BILLING_PAYMENTS'),
 'billing_customer_history':('SILVER','BILLING_CUSTOMER_HISTORY'), 'billing_adjustments':('SILVER','BILLING_ADJUSTMENTS'),
 'dim_customers':('GOLD','DIM_CUSTOMERS'), 'fct_invoices':('GOLD','FCT_INVOICES'), 'fct_customer_month':('GOLD','FCT_CUSTOMER_MONTH'),
}
DEFAULTS = {'tenant':'A','start_date':'2026-01-01','end_date':'2026-03-01','segment':'ALL'}
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

class HexExecutionError(ValueError): pass

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def normalize(value):
    if isinstance(value, dict): return {str(k).lower():normalize(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [normalize(v) for v in value]
    if value is None or pd.isna(value): return None
    if isinstance(value,(date,datetime,pd.Timestamp)): return value.strftime('%Y-%m-%d')
    if isinstance(value,Decimal): return str(value) if value!=value.to_integral_value() else int(value)
    if hasattr(value,'item'): return value.item()
    return value

def rows(frame): return normalize(frame.to_dict(orient='records'))

def parameters(overrides=None, defaults=None):
    overrides = {} if overrides is None else overrides
    if not isinstance(overrides,dict) or set(overrides)-{'tenant','start_date','end_date','segment','authorized','what_if_multiplier'}:
        raise HexExecutionError('Unknown parameter contract')
    p=dict(DEFAULTS if defaults is None else defaults);p.update(overrides)
    if p.get('authorized',True) is not True or p.get('tenant') not in ('A','B'):
        raise HexExecutionError('Tenant/persona denied by synthetic execution boundary')
    if p.get('segment') not in ('ALL','SMB','Enterprise'): raise HexExecutionError('Unsupported segment')
    for key in ('start_date','end_date'):
        if not isinstance(p.get(key),str): raise HexExecutionError('Date must be ISO text')
        try: parsed=date.fromisoformat(p[key])
        except ValueError as error: raise HexExecutionError('Date must be ISO text') from error
        if parsed.isoformat()!=p[key]: raise HexExecutionError('Date must be YYYY-MM-DD')
    if p['start_date']>p['end_date']: raise HexExecutionError('Reversed date window')
    if 'what_if_multiplier' in p:
        try: multiplier=Decimal(str(p['what_if_multiplier']))
        except Exception as error: raise HexExecutionError('Invalid what-if multiplier') from error
        if not multiplier.is_finite() or not 0<=multiplier<=10: raise HexExecutionError('What-if multiplier outside fixture contract')
        p['what_if_multiplier']=float(multiplier)
    return p

def load_inputs(case):
    case=Path(case)
    raw=json.loads((case/'input/raw-data.json').read_text())
    reader=csv.DictReader(io.StringIO((case/'input/repo/adjustments.csv').read_text()))
    if reader.fieldnames!=list(RAW_COLUMNS['ADJUSTMENTS']): raise HexExecutionError('Adjustment CSV columns changed')
    adjustments=list(reader)
    for row in adjustments: row['ADJUSTMENT_CENTS']=int(row['ADJUSTMENT_CENTS'])
    return raw,adjustments

def validate_inputs(raw, adjustments):
    if set(raw)!={'origin','snapshot_at','INVOICE_CDC','PAYMENT_CDC','CUSTOMER_HISTORY'} or raw['origin']!='synthetic':
        raise HexExecutionError('Only the synthetic raw input contract is accepted')
    latest={};versions={}
    for table in RAW_COLUMNS:
        data=adjustments if table=='ADJUSTMENTS' else raw[table]
        if not isinstance(data,list) or (not data and table!='ADJUSTMENTS'): raise HexExecutionError('Missing raw table '+table)
        for row in data:
            if not isinstance(row,dict) or set(row)!=set(RAW_COLUMNS[table]): raise HexExecutionError('Raw column inventory changed: '+table)
            for key,kind in RAW_COLUMNS[table].items():
                value=row[key]
                if value is None:
                    if key!='VALID_TO': raise HexExecutionError('Required raw field null: '+key)
                elif kind=='BIGINT' and (type(value) is not int or not -(2**63)<=value<2**63): raise HexExecutionError('Signed 64-bit integer cents/sequence required by local adapter')
                elif kind=='BOOLEAN' and type(value) is not bool: raise HexExecutionError('Boolean tombstone required')
                elif kind=='DATE':
                    try: date.fromisoformat(value)
                    except (ValueError,TypeError) as error: raise HexExecutionError('Invalid source date') from error
                elif kind=='VARCHAR' and (not isinstance(value,str) or not value): raise HexExecutionError('Required source text')
            for key in ('TENANT_ID','INVOICE_ID','CUSTOMER_ID','PAYMENT_ID'):
                if key in row and not re.fullmatch(r'[A-Za-z0-9]+',row[key]): raise HexExecutionError('Unsafe/colliding fixture identity')
        if table in ('INVOICE_CDC','PAYMENT_CDC'):
            idkey='INVOICE_ID' if table=='INVOICE_CDC' else 'PAYMENT_ID';selected={}
            for row in data:
                key=(row['TENANT_ID'],row[idkey]);version=(table,*key,row['SEQUENCE'])
                if row['SEQUENCE']<1: raise HexExecutionError('Invalid source sequence')
                if version in versions and versions[version]!=row: raise HexExecutionError('Conflicting CDC version')
                versions[version]=row
                if key not in selected or row['SEQUENCE']>selected[key]['SEQUENCE']: selected[key]=row
            latest[table]={k:r for k,r in selected.items() if not r['IS_DELETED']}
    seen=set()
    for row in adjustments:
        key=(row['TENANT_ID'],row['INVOICE_ID'])
        if key in seen: raise HexExecutionError('Duplicate manual adjustment key')
        if key not in latest['INVOICE_CDC']: raise HexExecutionError('Adjustment has no current invoice')
        seen.add(key)
    for row in latest['PAYMENT_CDC'].values():
        if (row['TENANT_ID'],row['INVOICE_ID']) not in latest['INVOICE_CDC']: raise HexExecutionError('Payment has no current invoice')
    histories={};dedup=set()
    for row in raw['CUSTOMER_HISTORY']:
        record=tuple(row[k] for k in RAW_COLUMNS['CUSTOMER_HISTORY'])
        if record in dedup: continue
        dedup.add(record);key=(row['TENANT_ID'],row['CUSTOMER_ID'])
        start=date.fromisoformat(row['VALID_FROM']);end=date.fromisoformat(row['VALID_TO']) if row['VALID_TO'] else date.max
        if start>=end: raise HexExecutionError('Invalid history interval')
        histories.setdefault(key,[]).append((start,end))
    for intervals in histories.values():
        intervals.sort()
        if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])): raise HexExecutionError('Overlapping customer history')
    for row in latest['INVOICE_CDC'].values():
        effective=date.fromisoformat(row['INVOICE_DATE'])
        if sum(a<=effective<b for a,b in histories.get((row['TENANT_ID'],row['CUSTOMER_ID']),[]))!=1:
            raise HexExecutionError('Invoice has no unique temporal customer')
    return {'raw_counts':{t:len(adjustments if t=='ADJUSTMENTS' else raw[t]) for t in RAW_COLUMNS},'current_invoice_count':len(latest['INVOICE_CDC'])}

def connection(raw,adjustments):
    validate_inputs(raw,adjustments)
    con=duckdb.connect(':memory:',config={'autoinstall_known_extensions':'false','autoload_known_extensions':'false','threads':'1'})
    con.execute("ATTACH ':memory:' AS DMA_HEX")
    con.execute('SET enable_external_access=false')
    for schema in ('RAW','SILVER','GOLD'): con.execute('CREATE SCHEMA DMA_HEX.'+schema)
    for name,columns in RAW_COLUMNS.items():
        con.execute('CREATE TABLE DMA_HEX.RAW.'+name+' ('+','.join(k+' '+v for k,v in columns.items())+')')
        data=adjustments if name=='ADJUSTMENTS' else raw[name]
        if data: con.executemany('INSERT INTO DMA_HEX.RAW.'+name+' VALUES ('+','.join('?' for k in columns)+')',[[r[k] for k in columns] for r in data])
    return con

FUNCTION_NAMES={'And','Or','Cast','TryCast','Coalesce','Lower','Upper','RowNumber','Sum','ToChar','Trim','Count','Nullif','Case','If','Min','Max','DateTrunc','TimestampTrunc','DateToDi','Concat','ConcatWs','DateStrToDate'}
NODE_NAMES=FUNCTION_NAMES|{'Add','Sub','Mul','Div','Neg','DPipe','Alias','CTE','Column','DataType','DataTypeParam','Distinct','EQ','NEQ','GT','GTE','LT','LTE','From','Group','Having','Identifier','Is','Join','Limit','Literal','Boolean','Not','Null','Order','Ordered','Paren','Select','Star','Subquery','Table','TableAlias','Union','Where','Window','With','Qualify','In','Filter','Var','Interval','Like'}

def checked_sql(sql,relations,frames=(),dialect='snowflake'):
    try: trees=sqlglot.parse(sql,read=dialect,error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as error: raise HexExecutionError('SQL parse failed') from error
    if len(trees)!=1 or not isinstance(trees[0],(exp.Select,exp.Union)): raise HexExecutionError('Exactly one SELECT/UNION is supported')
    tree=trees[0]
    for node in tree.walk():
        if type(node).__name__ not in NODE_NAMES: raise HexExecutionError('Unsupported SQL construct '+type(node).__name__)
        if isinstance(node,exp.Func) and type(node).__name__ not in FUNCTION_NAMES: raise HexExecutionError('Unsupported SQL function '+type(node).__name__)
        if isinstance(node,exp.Identifier) and not IDENTIFIER.fullmatch(node.name): raise HexExecutionError('Unsupported SQL identifier')
        if dialect=='snowflake' and isinstance(node,exp.Column):
            ident=node.this
            if isinstance(ident,exp.Identifier) and ident.args.get('quoted') and ident.name!=ident.name.upper():
                raise HexExecutionError('Quoted column identity does not match uppercase Snowflake catalogue')
        if isinstance(node,exp.With) and (node.args.get('recursive') or len({c.alias.lower() for c in node.expressions})!=len(node.expressions)):
            raise HexExecutionError('Recursive/duplicate SQL bindings unsupported')
    try:
        for scope in traverse_scope(tree):
            for _,(node,source) in scope.selected_sources.items():
                if isinstance(source,Scope): continue
                if not isinstance(source,exp.Table) or not isinstance(source.this,exp.Identifier): raise HexExecutionError('SQL table function denied')
                identity=(source.catalog.upper(),source.db.upper(),source.name.upper())
                for part in ('catalog','db','this'):
                    ident=source.args.get(part)
                    if isinstance(ident,exp.Identifier) and ident.args.get('quoted') and ident.name!=ident.name.upper():
                        raise HexExecutionError('Quoted source identity does not match uppercase Snowflake catalogue')
                if identity not in relations and not (not source.catalog and not source.db and source.name in frames):
                    raise HexExecutionError('SQL source outside declared relations: '+'.'.join(identity))
    except HexExecutionError: raise
    except Exception as error: raise HexExecutionError('SQL relation binding failed') from error
    for node in list(tree.find_all(exp.ToChar)):
        fmt=node.args.get('format')
        if not isinstance(fmt,exp.Literal) or fmt.this!='YYYY-MM-DD':
            raise HexExecutionError('Unsupported fixture date format')
        node.replace(exp.TimeToStr(this=node.this.copy(),format=exp.Literal.string('%Y-%m-%d')))
    return tree.sql(dialect='duckdb',unsupported_level=sqlglot.ErrorLevel.RAISE)

RAW_RELATIONS={('DMA_HEX','RAW',t) for t in RAW_COLUMNS}
TARGET_RELATIONS=RAW_RELATIONS|{('DMA_HEX',*v) for v in MODEL_MAP.values()}

def sql_frame(con,sql,frames=None,dialect='snowflake'):
    frames={} if frames is None else frames
    compiled=checked_sql(sql,TARGET_RELATIONS,frames,dialect)
    for name,frame in frames.items():
        if not IDENTIFIER.fullmatch(name) or not isinstance(frame,pd.DataFrame): raise HexExecutionError('Invalid dataframe binding')
        con.register(name,frame)
    try:
        cursor=con.execute(compiled)
        # DuckDB's .df() converts HUGEINT/DECIMAL sums to float. Preserve exact
        # cents through Python integers/Decimal when materializing SQL results.
        frame=pd.DataFrame.from_records(cursor.fetchall(),columns=[c[0] for c in cursor.description])
        return frame,compiled
    finally:
        for name in frames: con.unregister(name)

class PythonSubset:
    """Interpret reviewed dataframe operations without Python eval/exec/import."""
    def __init__(self,env,adjustments): self.env=env;self.adjustments=adjustments
    def expression(self,node):
        if isinstance(node,ast.Constant) and type(node.value) in (str,int,float,bool,type(None)): return node.value
        if isinstance(node,ast.Name):
            if node.id=='int': return int
            if node.id not in self.env: raise HexExecutionError('Unbound Python variable '+node.id)
            return self.env[node.id]
        if isinstance(node,(ast.List,ast.Tuple)): return [self.expression(x) for x in node.elts]
        if isinstance(node,ast.Subscript):
            value=self.expression(node.value);key=self.expression(node.slice)
            if not isinstance(value,(pd.DataFrame,pd.Series)) or not isinstance(key,(str,list)): raise HexExecutionError('Unsupported Python indexing')
            return value[key]
        if isinstance(node,ast.BinOp) and type(node.op) in (ast.Add,ast.Sub,ast.Mult,ast.Div):
            left=self.expression(node.left);right=self.expression(node.right)
            if not all(isinstance(v,(pd.Series,int,float)) for v in (left,right)): raise HexExecutionError('Unsupported Python arithmetic operand')
            if isinstance(node.op,ast.Add): return left+right
            if isinstance(node.op,ast.Sub): return left-right
            if isinstance(node.op,ast.Mult): return left*right
            return left/right
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            if any(k.arg is None for k in node.keywords): raise HexExecutionError('Dynamic Python keyword arguments denied')
            args=[self.expression(a) for a in node.args];kwargs={k.arg:self.expression(k.value) for k in node.keywords}
            if isinstance(node.func.value,ast.Name) and node.func.value.id=='pd' and node.func.attr=='read_csv':
                if args!=['adjustments.csv'] or kwargs or self.env.get('pd')!='reviewed-pandas': raise HexExecutionError('External file read denied')
                frame=pd.DataFrame(self.adjustments,columns=list(RAW_COLUMNS['ADJUSTMENTS']))
                frame['ADJUSTMENT_CENTS']=pd.Series([r['ADJUSTMENT_CENTS'] for r in self.adjustments],dtype=object)
                return frame
            obj=self.expression(node.func.value);method=node.func.attr
            if method=='merge' and isinstance(obj,pd.DataFrame):
                if len(args)!=1 or not isinstance(args[0],pd.DataFrame) or set(kwargs)!={'on','how','validate'}:
                    raise HexExecutionError('Explicit merge grain and validation required')
                if kwargs['on']!=['TENANT_ID','INVOICE_ID'] or kwargs['how']!='left' or kwargs['validate']!='many_to_one':
                    raise HexExecutionError('Merge must preserve tenant/invoice grain')
                return obj.merge(*args,**kwargs)
            if method=='fillna' and isinstance(obj,pd.Series) and args==[0] and not kwargs:
                with pd.option_context('future.no_silent_downcasting',True): return obj.fillna(0)
            if method=='astype' and isinstance(obj,pd.Series) and args==[int] and not kwargs:
                if (obj.dropna()%1!=0).any(): raise HexExecutionError('Lossy integer coercion')
                return pd.Series([int(v) for v in obj],index=obj.index,dtype=object)
            if method=='copy' and isinstance(obj,(pd.Series,pd.DataFrame)) and not args and not kwargs: return obj.copy()
            raise HexExecutionError('Unsupported Python method '+method)
        raise HexExecutionError('Unsupported Python expression '+type(node).__name__)
    def run(self,source):
        try: tree=ast.parse(source)
        except SyntaxError as error: raise HexExecutionError('Python parse failed') from error
        for node in tree.body:
            if isinstance(node,ast.Import) and len(node.names)==1 and node.names[0].name=='pandas' and node.names[0].asname=='pd':
                self.env['pd']='reviewed-pandas';continue
            if not isinstance(node,ast.Assign) or len(node.targets)!=1: raise HexExecutionError('Unsupported Python statement '+type(node).__name__)
            value=self.expression(node.value);target=node.targets[0]
            if isinstance(target,ast.Name) and not target.id.startswith('_'): self.env[target.id]=value
            elif isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name) and isinstance(target.slice,ast.Constant) and isinstance(target.slice.value,str):
                obj=self.env.get(target.value.id)
                if not isinstance(obj,pd.DataFrame): raise HexExecutionError('Assignment target must be a dataframe')
                obj[target.slice.value]=value
            else: raise HexExecutionError('Unsupported Python assignment target')
        return self.env

def render_parameters(sql,p):
    def replace(match):
        key=match.group(1)
        if key not in p or key not in DEFAULTS: raise HexExecutionError('Unknown SQL parameter '+key)
        return "'"+p[key].replace("'","''")+"'"
    result=re.sub(r'{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}',replace,sql)
    if any(mark in result for mark in ('{{','{%','${')): raise HexExecutionError('Unsupported SQL template')
    return result

def render_dbt(source):
    # This is a bounded fixture renderer, not the dbt compiler. Reject macros,
    # hooks, packages and unresolved templates instead of executing them.
    def config(match):
        try: call=ast.parse('config('+match.group(1)+')',mode='eval').body
        except SyntaxError as error: raise HexExecutionError('Invalid dbt config') from error
        if not isinstance(call,ast.Call) or call.args: raise HexExecutionError('Unsupported dbt config')
        seen=set()
        for item in call.keywords:
            if item.arg not in ('schema','alias','materialized') or item.arg in seen or not isinstance(item.value,ast.Constant) or not isinstance(item.value.value,str):
                raise HexExecutionError('Unsupported dbt config/hook')
            seen.add(item.arg)
            if item.arg=='materialized' and item.value.value!='table': raise HexExecutionError('Unsupported dbt materialization')
        return ''
    source=re.sub(r'{{\s*config\(([^{}]*)\)\s*}}',config,source)
    def ref(match):
        name=match.group(1)
        if name not in MODEL_MAP: raise HexExecutionError('Unresolved dbt ref '+name)
        return 'DMA_HEX.'+'.'.join(MODEL_MAP[name])
    def raw(match):
        name=match.group(1).upper()
        if name not in RAW_COLUMNS: raise HexExecutionError('Unresolved dbt source '+name)
        return 'DMA_HEX.RAW.'+name
    source=re.sub(r"{{\s*ref\(['\"]([a-z_]+)['\"]\)\s*}}",ref,source)
    source=re.sub(r"{{\s*source\(['\"]raw['\"],\s*['\"]([a-z_]+)['\"]\)\s*}}",raw,source)
    if any(mark in source for mark in ('{{','{%','${')): raise HexExecutionError('Unsupported dbt template')
    return source

def build_models(con,dbt_root):
    root=Path(dbt_root);compiled=[]
    paths=list((root/'models').rglob('*.sql'))
    files={p.stem:p for p in paths}
    if len(paths)!=len(files): raise HexExecutionError('Duplicate dbt model identity')
    if set(files)!=set(MODEL_MAP): raise HexExecutionError('dbt model inventory changed')
    for name,(schema,table) in MODEL_MAP.items():
        source=files[name].read_text();sql=render_dbt(source)
        configs=re.findall(r'{{\s*config\(([^{}]*)\)\s*}}',source)
        if len(configs)!=1: raise HexExecutionError('One explicit fixture model config required')
        call=ast.parse('config('+configs[0]+')',mode='eval').body
        values={item.arg:item.value.value for item in call.keywords}
        if values!={'schema':schema,'alias':table,'materialized':'table'}: raise HexExecutionError('dbt model destination/config differs from declared model map')
        query=checked_sql(sql,TARGET_RELATIONS)
        con.execute('CREATE OR REPLACE TABLE DMA_HEX.'+schema+'.'+table+' AS '+query)
        compiled.append({'model':name,'path':str(files[name].relative_to(root)),'sha256':sha(files[name]),'sql':query})
    return compiled

def replay_source(case,graph,raw,adjustments,overrides=None):
    """Replay expanded native fixture cells with a fresh environment per project."""
    case=Path(case)
    contract=json.loads((case/'input/repo/report-contract.json').read_text())
    if graph['counts']['errors'] or not graph['static_coverage_complete']:
        raise HexExecutionError('Hex extraction contains unresolved static dependencies')
    projects={p['project_id']:p for p in graph['projects']};cells={c['id']:c for c in graph['cells']}
    if len(projects)!=4 or len(contract['projects'])!=3: raise HexExecutionError('Three-project fixture inventory changed')
    results={};traces=[];intermediate={}
    with connection(raw,adjustments) as con:
        for selection in contract['projects']:
            project=projects.get(selection['project_id'])
            if project is None: raise HexExecutionError('Selected Hex project missing')
            defaults={cells[c]['config']['name']:cells[c]['config']['defaultValue'] for c in project['cell_ids'] if cells[c]['cell_type']=='INPUT'}
            if defaults!=selection['inputs']: raise HexExecutionError('Native Hex defaults differ from report contract')
            p=parameters(overrides,defaults);env={};executed=[]
            def run_project(project_id,stack=()):
                if project_id in stack: raise HexExecutionError('Cyclic component imports')
                for cid in projects[project_id]['cell_ids']:
                    cell=cells[cid];kind=cell['cell_type'];cfg=cell['config']
                    if kind=='INPUT': env[cfg['name']]=p[cfg['name']]
                    elif kind=='COMPONENT_IMPORT':
                        component=cfg['component'];pid=component['id']
                        if pid not in projects or component['version']!=projects[pid]['source_version_id']: raise HexExecutionError('Component version unavailable')
                        run_project(pid,(*stack,project_id))
                    elif kind=='SQL':
                        dataframe=cfg.get('dataFrameCell',False)
                        if not dataframe and cfg.get('dataConnectionId')!=CONNECTION_ID: raise HexExecutionError('Hex connection binding mismatch')
                        sql=render_parameters(cell['source'],p)
                        frames={k:v for k,v in env.items() if isinstance(v,pd.DataFrame)} if dataframe else {}
                        checked_sql(sql,set() if dataframe else RAW_RELATIONS,frames,'duckdb' if dataframe else 'snowflake')
                        frame,compiled=sql_frame(con,sql,frames,'duckdb' if dataframe else 'snowflake')
                        env[cfg['resultVariableName']]=frame
                        traces.append({'project':selection['role'],'cell_id':cid,'kind':kind,'sql':compiled,'row_count':len(frame)})
                    elif kind=='CODE':
                        PythonSubset(env,adjustments).run(cell['source'])
                        traces.append({'project':selection['role'],'cell_id':cid,'kind':kind,'source_sha256':hashlib.sha256(cell['source'].encode()).hexdigest()})
                    elif kind=='CHARTV2':
                        traces.append({'project':selection['role'],'cell_id':cid,'kind':kind,'status':'config_preserved_native_rendering_unavailable'})
                    else: raise HexExecutionError('Unexecuted selected Hex cell type '+kind)
                    executed.append(cid)
            run_project(project['project_id'])
            output=env.get(selection['output_variable'])
            if not isinstance(output,pd.DataFrame): raise HexExecutionError('Report output dataframe missing')
            result=rows(output)
            # Explicit source-to-target rename; retain original in the trace.
            if selection['role']=='executive':
                for row in result:
                    if 'active_customers' not in row: raise HexExecutionError('Original executive metric omitted')
                    row['paying_active_customers']=row.pop('active_customers')
            results[selection['role']]=result
            intermediate[selection['role']]={'invoice_base':rows(env['invoice_base']),'enriched':rows(env['enriched']),'executed_cell_ids':executed}
            if 'what_if_revenue' in env: intermediate[selection['role']]['retained_what_if_values']=normalize(env['what_if_revenue'].tolist())
    return results,intermediate,traces

class OmniSubset:
    """Render selected native field/relationship definitions; not Omni's compiler."""
    def __init__(self,root):
        self.root=Path(root)
        self.views={p.stem:yaml.safe_load(p.read_text()) for p in self.root.glob('*.view')}
        self.relationships=yaml.safe_load((self.root/'relationships').read_text())
        self.topic=yaml.safe_load((self.root/'billing.topic').read_text())
        if set(self.views)!={'invoices','customers','customer_month'}: raise HexExecutionError('Omni view inventory changed')
        if self.topic.get('base_view')!='invoices' or self.topic.get('access_filters')!=[{'field':'invoices.tenant_id','user_attribute':'tenant_id'}]:
            raise HexExecutionError('Omni tenant access contract changed')
        if set(self.topic.get('joins',{}))!={'customers','customer_month'}: raise HexExecutionError('Omni topic joins changed')
        for name,view in self.views.items():
            ident=(view.get('catalog'),view.get('schema'),view.get('table_name'))
            if ident not in TARGET_RELATIONS: raise HexExecutionError('Omni relation outside target scope')
    def sql(self,text,view,stack=()):
        if not isinstance(text,str): raise HexExecutionError('Omni SQL must be text')
        text=re.sub(r'"([A-Z_]+)"',lambda m:view+'."'+m.group(1)+'"',text)
        return re.sub(r'\$\{([a-z_]+(?:\.[a-z_]+)?)\}',lambda m:self.field(m.group(1) if '.' in m.group(1) else view+'.'+m.group(1),stack),text)
    def field(self,reference,stack=()):
        if reference in stack: raise HexExecutionError('Recursive Omni field')
        view,name=reference.split('.');definition=self.views.get(view,{})
        fields=definition.get('dimensions',{});measures=definition.get('measures',{})
        if name not in fields and name not in measures: raise HexExecutionError('Unresolved Omni field '+reference)
        spec=fields.get(name,measures.get(name));expression=self.sql(spec['sql'],view,(*stack,reference))
        aggregate=spec.get('aggregate_type')
        if aggregate:
            if aggregate not in ('sum','count','count_distinct'): raise HexExecutionError('Unsupported Omni aggregation')
            filters=[]
            for key,predicate in spec.get('filters',{}).items():
                if not isinstance(predicate,dict) or set(predicate)!={'is'} or not isinstance(predicate['is'],str): raise HexExecutionError('Unsupported Omni measure filter')
                field=self.field(key if '.' in key else view+'.'+key,(*stack,reference))
                filters.append(field+" = '"+predicate['is'].replace("'","''")+"'")
            if filters: expression='CASE WHEN '+' AND '.join(filters)+' THEN '+expression+' END'
            expression=('COUNT(DISTINCT '+expression+')') if aggregate=='count_distinct' else aggregate.upper()+'('+expression+')'
        elif spec.get('filters'): raise HexExecutionError('Unaggregated filtered Omni field unsupported')
        return '('+expression+')'
    def base(self):
        def table(view):
            spec=self.views[view];return spec['catalog']+'.'+spec['schema']+'.'+spec['table_name']+' '+view
        clause=' FROM '+table('invoices');seen=set()
        for relationship in self.relationships:
            target=relationship['join_to_view']
            if target not in ('customers','customer_month') or target in seen or relationship.get('join_from_view')!='invoices' or relationship.get('join_type')!='always_left' or relationship.get('relationship_type')!='many_to_one':
                raise HexExecutionError('Unsupported Omni relationship')
            seen.add(target);clause+=' LEFT JOIN '+table(target)+' ON '+self.sql(relationship['on_sql'],'invoices')
        if seen!={'customers','customer_month'}: raise HexExecutionError('Omni relationship omitted')
        return clause
    def report(self,con,role,p,selection):
        if selection.get('topic')!='billing': raise HexExecutionError('Unsupported report topic')
        dims=selection['dimensions'];metrics=selection.get('measures',{})
        if not isinstance(dims,dict) or not dims: raise HexExecutionError('Missing report dimensions')
        select=[self.field(field)+' AS '+alias for alias,field in dims.items()]
        select += [self.field(field)+' AS '+alias for alias,field in metrics.items()]
        for alias in list(dims)+list(metrics):
            if not IDENTIFIER.fullmatch(alias): raise HexExecutionError('Unsafe report alias')
        bindings=selection['runtime_field_bindings']
        if set(bindings)!={'date','segment'}: raise HexExecutionError('Runtime field binding inventory changed')
        where=[self.field('invoices.tenant_id')+" = '"+p['tenant']+"'",self.field(bindings['date'])+" >= DATE '"+p['start_date']+"'",self.field(bindings['date'])+" < DATE '"+p['end_date']+"'"]
        if p['segment']!='ALL': where.append(self.field(bindings['segment'])+" = '"+p['segment']+"'")
        for field,predicate in selection.get('filters',{}).items():
            if set(predicate)=={'is'} and isinstance(predicate['is'],str):
                where.append(self.field(field)+" = '"+predicate['is'].replace("'","''")+"'")
            elif set(predicate)=={'greater_than'} and type(predicate['greater_than']) is int:
                where.append(self.field(field)+' > '+str(predicate['greater_than']))
            else: raise HexExecutionError('Unsupported report filter')
        sql='SELECT '+('DISTINCT ' if selection.get('distinct',False) else '')+', '.join(select)+self.base()+' WHERE '+' AND '.join(where)
        if metrics: sql+=' GROUP BY '+','.join(str(i+1) for i in range(len(dims)))
        sorts=selection['sorts']
        if not isinstance(sorts,list) or not sorts or any(s not in dims for s in sorts): raise HexExecutionError('Unsupported report ordering')
        sql+=' ORDER BY '+','.join(sorts)
        frame,compiled=sql_frame(con,sql)
        return rows(frame),compiled
