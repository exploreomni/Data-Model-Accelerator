"""Bounded synthetic Tableau and Omni replay; not native vendor execution.

Shared SQL/input validation comes from the qualified Hex billing fixture. Source
calculation evaluation and Omni rendering are independent code paths. No eval,
exec, dynamic imports, source hooks or arbitrary warehouse connections are used.
"""
import ast
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import json
import math
from pathlib import Path
import re

import duckdb
import yaml
import sqlglot
from sqlglot import exp
from hex_execution import RAW_COLUMNS, IDENTIFIER, checked_sql, sha, load_inputs, validate_inputs, normalize

class TableauExecutionError(ValueError): pass

MODEL_MAP = {
 'billing_invoices':('SILVER','BILLING_INVOICES'), 'billing_payments':('SILVER','BILLING_PAYMENTS'),
 'billing_customer_history':('SILVER','BILLING_CUSTOMER_HISTORY'), 'billing_adjustments':('SILVER','BILLING_ADJUSTMENTS'),
 'dim_customers':('GOLD','DIM_CUSTOMERS'), 'fct_invoices':('GOLD','FCT_INVOICES'),
}
RAW_RELATIONS={('DMA_TABLEAU','RAW',t) for t in RAW_COLUMNS}
TARGET_RELATIONS=RAW_RELATIONS|{('DMA_TABLEAU',*v) for v in MODEL_MAP.values()}
DEFAULTS={'tenant':'A','start_date':'2026-01-01','end_date':'2026-03-01','segment':'ALL','multiplier':1}

def parameters(overrides=None, defaults=None):
    p=dict(DEFAULTS if defaults is None else defaults)
    if overrides is not None:
        if not isinstance(overrides,dict) or set(overrides)-set(DEFAULTS)-{'authorized','persona_tenant'}:
            raise TableauExecutionError('Unsupported report parameters')
        p.update(overrides)
    if p.get('tenant') not in ('A','B') or p.get('authorized',True) is not True or p.get('persona_tenant',p['tenant'])!=p['tenant']:
        raise TableauExecutionError('Tenant/persona access denied')
    try:
        for name in ('start_date','end_date'):
            if not isinstance(p[name],str) or date.fromisoformat(p[name]).isoformat()!=p[name]: raise ValueError()
        if p['start_date']>p['end_date']: raise ValueError()
    except (ValueError,TypeError,KeyError): raise TableauExecutionError('Invalid date window')
    if not isinstance(p.get('segment'),str) or len(p['segment'])>100: raise TableauExecutionError('Invalid segment')
    try:
        if isinstance(p['multiplier'],bool) or not isinstance(p['multiplier'],(int,float,str,Decimal)): raise ValueError()
        multiplier=Decimal(str(p['multiplier']))
        if not multiplier.is_finite() or abs(multiplier)>1000: raise ValueError()
        p['multiplier']=multiplier
    except (ValueError,InvalidOperation,KeyError): raise TableauExecutionError('Invalid multiplier')
    return p

def literal(value):
    if isinstance(value,Decimal): return str(value)
    if isinstance(value,str): return "'"+value.replace("'","''")+"'"
    raise TableauExecutionError('Unsupported bound literal')

def divide(left,right):
    if left is None or right is None or right==0: return None
    with localcontext() as context:
        context.prec=50
        return Decimal(left)/Decimal(right)

def connection(raw,adjustments):
    validate_inputs(raw,adjustments)
    con=duckdb.connect(':memory:',config={'autoinstall_known_extensions':'false','autoload_known_extensions':'false','threads':'1'})
    con.execute("ATTACH ':memory:' AS DMA_TABLEAU")
    con.execute('SET enable_external_access=false')
    for schema in ('RAW','SILVER','GOLD'): con.execute('CREATE SCHEMA DMA_TABLEAU.'+schema)
    for name,columns in RAW_COLUMNS.items():
        con.execute('CREATE TABLE DMA_TABLEAU.RAW.'+name+' ('+','.join(k+' '+v for k,v in columns.items())+')')
        data=adjustments if name=='ADJUSTMENTS' else raw[name]
        if data: con.executemany('INSERT INTO DMA_TABLEAU.RAW.'+name+' VALUES ('+','.join('?' for k in columns)+')',[[r[k] for k in columns] for r in data])
    return con

def query(con,sql,relations=None):
    compiled=checked_sql(sql,TARGET_RELATIONS if relations is None else relations)
    cursor=con.execute(compiled)
    records=[dict(zip([c[0].lower() for c in cursor.description],r)) for r in cursor.fetchall()]
    return normalize(records),compiled

def render_dbt(source):
    # This is a bounded fixture renderer, not the dbt compiler. Reject macros,
    # hooks, packages and unresolved templates instead of executing them.
    def config(match):
        try: call=ast.parse('config('+match.group(1)+')',mode='eval').body
        except SyntaxError as error: raise TableauExecutionError('Invalid dbt config') from error
        if not isinstance(call,ast.Call) or call.args: raise TableauExecutionError('Unsupported dbt config')
        seen=set()
        for item in call.keywords:
            if item.arg not in ('schema','alias','materialized') or item.arg in seen or not isinstance(item.value,ast.Constant) or not isinstance(item.value.value,str):
                raise TableauExecutionError('Unsupported dbt config/hook')
            seen.add(item.arg)
            if item.arg=='materialized' and item.value.value!='table': raise TableauExecutionError('Unsupported dbt materialization')
        return ''
    source=re.sub(r'{{\s*config\(([^{}]*)\)\s*}}',config,source)
    def ref(match):
        name=match.group(1)
        if name not in MODEL_MAP: raise TableauExecutionError('Unresolved dbt ref '+name)
        return 'DMA_TABLEAU.'+'.'.join(MODEL_MAP[name])
    def raw(match):
        name=match.group(1).upper()
        if name not in RAW_COLUMNS: raise TableauExecutionError('Unresolved dbt source '+name)
        return 'DMA_TABLEAU.RAW.'+name
    source=re.sub(r"{{\s*ref\(['\"]([a-z_]+)['\"]\)\s*}}",ref,source)
    source=re.sub(r"{{\s*source\(['\"]raw['\"],\s*['\"]([a-z_]+)['\"]\)\s*}}",raw,source)
    if any(mark in source for mark in ('{{','{%','${')): raise TableauExecutionError('Unsupported dbt template')
    return source

def build_models(con,dbt_root):
    root=Path(dbt_root);compiled=[]
    paths=list((root/'models').rglob('*.sql'))
    files={p.stem:p for p in paths}
    if len(paths)!=len(files): raise TableauExecutionError('Duplicate dbt model identity')
    if set(files)!=set(MODEL_MAP): raise TableauExecutionError('dbt model inventory changed')
    for name,(schema,table) in MODEL_MAP.items():
        source=files[name].read_text();sql=render_dbt(source)
        configs=re.findall(r'{{\s*config\(([^{}]*)\)\s*}}',source)
        if len(configs)!=1: raise TableauExecutionError('One explicit fixture model config required')
        call=ast.parse('config('+configs[0]+')',mode='eval').body
        values={item.arg:item.value.value for item in call.keywords}
        if values!={'schema':schema,'alias':table,'materialized':'table'}: raise TableauExecutionError('dbt model destination/config differs from declared model map')
        query=checked_sql(sql,TARGET_RELATIONS)
        con.execute('CREATE OR REPLACE TABLE DMA_TABLEAU.'+schema+'.'+table+' AS '+query)
        compiled.append({'model':name,'path':str(files[name].relative_to(root)),'sha256':sha(files[name]),'sql':query})
    return compiled


TOKEN = re.compile(r"\s*(\[[^\]\r\n]+\](?:\.\[[^\]\r\n]+\])*|'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|#[0-9-]+#|\d+(?:\.\d+)?|>=|<=|<>|!=|[{}():,+*/=<>-]|[A-Za-z_][A-Za-z_0-9]*)")
PRECEDENCE={'OR':1,'AND':2,'=':3,'!=':3,'<>':3,'>':3,'<':3,'>=':3,'<=':3,'+':4,'-':4,'*':5,'/':5}

class FormulaParser:
    """Small positive grammar for this fixture's Tableau expressions."""
    def __init__(self,text):
        if not isinstance(text,str) or len(text)>20000: raise TableauExecutionError('Invalid formula size')
        self.tokens=[];offset=0
        while offset<len(text.rstrip()):
            match=TOKEN.match(text,offset)
            if not match: raise TableauExecutionError('Unsupported Tableau formula token at '+str(offset))
            self.tokens.append(match.group(1));offset=match.end()
        self.at=0
    def peek(self): return self.tokens[self.at].upper() if self.at<len(self.tokens) else ''
    def take(self,value=None):
        if self.at>=len(self.tokens): raise TableauExecutionError('Incomplete Tableau formula')
        result=self.tokens[self.at];self.at+=1
        if value and result.upper()!=value: raise TableauExecutionError('Expected Tableau token '+value)
        return result
    def expression(self,minimum=0,depth=0):
        if depth>40: raise TableauExecutionError('Formula nesting limit')
        tok=self.take();upper=tok.upper()
        if upper=='IF':
            condition=self.expression(depth=depth+1);self.take('THEN');yes=self.expression(depth=depth+1)
            self.take('ELSE');no=self.expression(depth=depth+1);self.take('END');left=('if',condition,yes,no)
        elif tok=='{':
            self.take('FIXED');dims=[]
            while self.peek()!=':':
                field=self.take()
                if not field.startswith('['): raise TableauExecutionError('FIXED dimension reference required')
                dims.append(('ref',field))
                if self.peek()!=',': break
                self.take(',')
            self.take(':');aggregate=self.expression(depth=depth+1);self.take('}')
            left=('fixed',dims,aggregate)
        elif tok=='(':
            left=self.expression(depth=depth+1);self.take(')')
        elif tok=='-' or upper=='NOT': left=('unary',upper,self.expression(6,depth+1))
        elif tok.startswith('['): left=('ref',tok)
        elif tok[0] in ("'",'"'): left=('literal',tok[1:-1].replace(tok[0]*2,tok[0]))
        elif tok.startswith('#'): left=('literal',date.fromisoformat(tok[1:-1]).isoformat())
        elif tok[0].isdigit(): left=('literal',Decimal(tok) if '.' in tok else int(tok))
        elif upper in ('TRUE','FALSE','NULL'): left=('literal',{'TRUE':True,'FALSE':False,'NULL':None}[upper])
        elif self.peek()=='(':
            if upper not in {'SUM','MIN','MAX','ZN','DATETRUNC','WINDOW_SUM','IFNULL'}: raise TableauExecutionError('Unsupported Tableau function '+upper)
            self.take('(');args=[]
            if self.peek()!=')':
                while True:
                    args.append(self.expression(depth=depth+1))
                    if self.peek()!=',': break
                    self.take(',')
            self.take(')');left=('call',upper,args)
        else: raise TableauExecutionError('Unsupported Tableau expression '+tok)
        while self.peek() in PRECEDENCE and PRECEDENCE[self.peek()]>=minimum:
            op=self.take().upper();right=self.expression(PRECEDENCE[op]+1,depth+1);left=('binary',op,left,right)
        return left
    def parse(self):
        result=self.expression()
        if self.at!=len(self.tokens): raise TableauExecutionError('Unconsumed Tableau formula tokens')
        return result

PARAMETER_NAMES={'Tenant':'tenant','Start Date':'start_date','End Date':'end_date','Segment':'segment','Multiplier':'multiplier'}

class TableauFormula:
    def __init__(self,fields,params,context):
        self.fields=fields;self.params=params;self.context=context;self.parsed={};self.executed=set()
    def value(self,reference,rows,row=None,partition=None,stack=()):
        pieces=re.findall(r'\[([^]]+)\]',reference)
        if len(pieces)==2 and pieces[0]=='Parameters':
            if pieces[1] not in PARAMETER_NAMES: raise TableauExecutionError('Unknown Tableau parameter')
            return self.params[PARAMETER_NAMES[pieces[1]]]
        if len(pieces)!=1: raise TableauExecutionError('Unresolved qualified Tableau field '+reference)
        key=pieces[0]
        if key in stack: raise TableauExecutionError('Cyclic Tableau calculation')
        spec=self.fields.get(key)
        if not spec: raise TableauExecutionError('Unbound Tableau field '+reference)
        self.executed.add(spec.get('id',key))
        formula=spec.get('formula')
        if formula is not None:
            if key not in self.parsed: self.parsed[key]=FormulaParser(formula).parse()
            return self.evaluate(self.parsed[key],rows,row,partition,(*stack,key))
        physical=spec.get('remote_name')
        if row is None or physical is None or physical.lower() not in row:
            raise TableauExecutionError('Missing scalar Tableau field '+reference)
        return row[physical.lower()]
    def evaluate(self,node,rows,row=None,partition=None,stack=()):
        kind=node[0]
        if kind=='literal': return node[1]
        if kind=='ref': return self.value(node[1],rows,row,partition,stack)
        if kind=='if':
            condition=self.evaluate(node[1],rows,row,partition,stack)
            return self.evaluate(node[2] if condition is True else node[3],rows,row,partition,stack)
        if kind=='unary':
            value=self.evaluate(node[2],rows,row,partition,stack)
            if value is None: return None
            return not value if node[1]=='NOT' else -value
        if kind=='binary':
            op=node[1];left=self.evaluate(node[2],rows,row,partition,stack);right=self.evaluate(node[3],rows,row,partition,stack)
            if op=='AND': return False if left is False or right is False else None if left is None or right is None else bool(left and right)
            if op=='OR': return True if left is True or right is True else None if left is None or right is None else bool(left or right)
            if left is None or right is None: return None
            if op in ('=','!=','<>','>','<','>=','<='):
                return {'=':lambda:left==right,'!=':lambda:left!=right,'<>':lambda:left!=right,'>':lambda:left>right,'<':lambda:left<right,'>=':lambda:left>=right,'<=':lambda:left<=right}[op]()
            if op=='+': return left+right
            if op=='-': return left-right
            if op=='*': return left*right
            if op=='/': return divide(left,right)
        if kind=='fixed':
            if row is None: raise TableauExecutionError('FIXED requires a scalar mark before outer aggregation')
            key=tuple(self.evaluate(d,rows,row,partition,stack) for d in node[1])
            scoped=[r for r in self.context if tuple(self.evaluate(d,self.context,r,None,stack) for d in node[1])==key]
            return self.evaluate(node[2],scoped,None,None,stack)
        if kind=='call':
            name,args=node[1:]
            expected=2 if name in ('DATETRUNC','IFNULL') else 1
            if len(args)!=expected: raise TableauExecutionError('Unsupported Tableau function arity')
            if name in ('SUM','MIN','MAX'):
                values=[self.evaluate(args[0],rows,r,partition,stack) for r in rows];values=[v for v in values if v is not None]
                if not values: return None
                return sum(values) if name=='SUM' else min(values) if name=='MIN' else max(values)
            if name=='WINDOW_SUM':
                if partition is None: raise TableauExecutionError('Missing table-calculation partition')
                values=[self.evaluate(args[0],part,None,None,stack) for part in partition];values=[v for v in values if v is not None]
                return sum(values) if values else None
            values=[self.evaluate(a,rows,row,partition,stack) for a in args]
            if name=='ZN': return 0 if values[0] is None else values[0]
            if name=='IFNULL': return values[1] if values[0] is None else values[0]
            if name=='DATETRUNC':
                if values[0]!='month': raise TableauExecutionError('Unsupported date truncation')
                return None if values[1] is None else str(values[1])[:7]+'-01'
        raise TableauExecutionError('Unsupported Tableau AST')

class OmniSubset:
    """Render native model fields/LOD and a declared local presentation contract."""
    def __init__(self,root):
        self.root=Path(root)
        self.views={p.stem:yaml.safe_load(p.read_text()) for p in self.root.glob('*.view')}
        self.relationships=yaml.safe_load((self.root/'relationships').read_text())
        self.topic=yaml.safe_load((self.root/'billing.topic').read_text())
        self.contract=json.loads((self.root/'report-context.json').read_text())
        if set(self.views)!={'invoices','customers'}: raise TableauExecutionError('Omni view inventory changed')
        if self.topic.get('base_view')!='invoices' or self.topic.get('access_filters')!=[{'field':'invoices.tenant_id','user_attribute':'tenant_id'}]:
            raise TableauExecutionError('Omni tenant access contract changed')
        if set(self.topic.get('joins',{}))!={'customers'}: raise TableauExecutionError('Omni topic joins changed')
        if self.contract.get('defaults')!=DEFAULTS: raise TableauExecutionError('Omni default parameter drift')
        for name,view in self.views.items():
            if (view.get('catalog'),view.get('schema'),view.get('table_name')) not in TARGET_RELATIONS:
                raise TableauExecutionError('Omni relation outside target scope')
    def sql(self,text,view,stack=()):
        if not isinstance(text,str): raise TableauExecutionError('Omni SQL must be text')
        text=re.sub(r'"([A-Z_]+)"',lambda m:view+'."'+m.group(1)+'"',text)
        return re.sub(r'\$\{([a-z_]+(?:\.[a-z_]+)?)\}',lambda m:self.field(m.group(1) if '.' in m.group(1) else view+'.'+m.group(1),stack),text)
    def field(self,reference,stack=()):
        if reference in stack: raise TableauExecutionError('Recursive Omni field')
        try: view,name=reference.split('.')
        except ValueError: raise TableauExecutionError('Invalid Omni field reference')
        definition=self.views.get(view,{})
        fields=definition.get('dimensions',{});measures=definition.get('measures',{})
        if name not in fields and name not in measures: raise TableauExecutionError('Unresolved Omni field '+reference)
        spec=fields.get(name,measures.get(name))
        if 'level_of_detail' in spec:
            if reference!='invoices.fixed_customer_revenue_cents': raise TableauExecutionError('Unsupported LOD field')
            return 'lod."LOD_VALUE"'
        expression=self.sql(spec['sql'],view,(*stack,reference));aggregate=spec.get('aggregate_type')
        if aggregate:
            if aggregate not in ('sum','min','max','count','count_distinct'): raise TableauExecutionError('Unsupported Omni aggregation')
            filters=[]
            for key,predicate in spec.get('filters',{}).items():
                if not isinstance(predicate,dict) or set(predicate)!={'is'} or not isinstance(predicate['is'],str): raise TableauExecutionError('Unsupported Omni measure filter')
                field=self.field(key if '.' in key else view+'.'+key,(*stack,reference))
                filters.append(field+' = '+literal(predicate['is']))
            if filters: expression='CASE WHEN '+' AND '.join(filters)+' THEN '+expression+' END'
            expression=('COUNT(DISTINCT '+expression+')') if aggregate=='count_distinct' else aggregate.upper()+'('+expression+')'
        elif spec.get('filters'): raise TableauExecutionError('Unaggregated filtered field unsupported')
        return '('+expression+')'
    def base(self):
        def table(view):
            spec=self.views[view];return spec['catalog']+'.'+spec['schema']+'.'+spec['table_name']+' '+view
        if not isinstance(self.relationships,list) or len(self.relationships)!=1: raise TableauExecutionError('Omni relationship inventory changed')
        relationship=self.relationships[0]
        if relationship.get('join_to_view')!='customers' or relationship.get('join_from_view')!='invoices' or relationship.get('join_type')!='always_left' or relationship.get('relationship_type')!='many_to_one':
            raise TableauExecutionError('Unsupported Omni relationship')
        return ' FROM '+table('invoices')+' LEFT JOIN '+table('customers')+' ON '+self.sql(relationship['on_sql'],'invoices')
    def where(self,p,selection,cancelled=()):
        fields=selection.get('runtime_field_bindings',{})
        if fields!={'tenant':'invoices.tenant_id','date':'invoices.invoice_date','segment':'invoices.segment'}:
            raise TableauExecutionError('Runtime field binding mismatch')
        if any(field in cancelled for field in ('invoices.tenant_id','invoices.invoice_date','invoices.status')):
            raise TableauExecutionError('LOD cannot cancel population/context/access filters')
        where=[self.field(fields['tenant'])+' = '+literal(p['tenant']),self.field(fields['date'])+" >= DATE "+literal(p['start_date']),self.field(fields['date'])+" < DATE "+literal(p['end_date'])]
        if p['segment']!='ALL' and fields['segment'] not in cancelled: where.append(self.field(fields['segment'])+' = '+literal(p['segment']))
        for field,predicate in selection.get('filters',{}).items():
            if set(predicate)!={'is'} or not isinstance(predicate['is'],str): raise TableauExecutionError('Unsupported report filter')
            if field not in cancelled: where.append(self.field(field)+' = '+literal(predicate['is']))
        return ' WHERE '+' AND '.join(where)
    def lod(self,p,selection):
        field=self.views['invoices']['dimensions'].get('fixed_customer_revenue_cents',{})
        spec=field.get('level_of_detail',{})
        if set(spec)-{'aggregate_type','fixed','filters','cancel_query_filters'} or spec.get('aggregate_type')!='sum' or spec.get('cancel_query_filters',False):
            raise TableauExecutionError('Unsupported/blanket LOD filter cancellation')
        fixed=spec.get('fixed')
        if not isinstance(fixed,list) or not fixed or len(fixed)!=len(set(fixed)): raise TableauExecutionError('Missing/duplicate LOD grouping')
        groups=[self.field(f if '.' in f else 'invoices.'+f) for f in fixed]
        cancelled=[]
        for name,predicate in spec.get('filters',{}).items():
            if predicate!={'is':'','cancel_query_filter':True}: raise TableauExecutionError('Unsupported LOD replacement filter')
            cancelled.append(name if '.' in name else 'invoices.'+name)
        projection=[g+' AS FK'+str(i) for i,g in enumerate(groups)]
        projection.append('SUM('+self.sql(field['sql'],'invoices')+') AS LOD_VALUE')
        sql='SELECT '+','.join(projection)+self.base()+self.where(p,selection,cancelled)+' GROUP BY '+','.join(groups)
        join=' LEFT JOIN lod ON '+' AND '.join(g+' = lod.FK'+str(i) for i,g in enumerate(groups))
        return sql,join
    def report(self,con,role,overrides=None):
        p=parameters(overrides);selection=self.contract['reports'][role]
        if selection.get('topic')!='billing': raise TableauExecutionError('Unsupported report topic')
        if selection.get('filter_roles')!={'population':['tenant','status'],'context':['date'],'dimension':['segment']} or selection.get('context_order')!=['datasource_population','date_context','fixed_lod','segment_dimension','mark_aggregation','presentation']:
            raise TableauExecutionError('Unsupported worksheet context order/filter roles')
        dims=selection['dimensions'];metrics=selection['measures']
        if not dims or not metrics or any(not IDENTIFIER.fullmatch(a) for a in list(dims)+list(metrics)): raise TableauExecutionError('Invalid report columns')
        select=[self.field(field)+' AS '+alias for alias,field in dims.items()]+[self.field(field)+' AS '+alias for alias,field in metrics.items()]
        prefix='';base=self.base()
        if any('lod.' in s for s in select):
            lodsql,join=self.lod(p,selection);prefix='WITH lod AS ('+lodsql+') ';base+=join
        sql=prefix+'SELECT '+','.join(select)+base+self.where(p,selection)+' GROUP BY '+','.join(str(i+1) for i in range(len(dims)))
        sorts=selection['sorts']
        if not isinstance(sorts,list) or set(sorts)!=set(dims): raise TableauExecutionError('Unsupported report ordering')
        sql+=' ORDER BY '+','.join(sorts)
        result,compiled=query(con,sql)
        # DuckDB division returns double even when its operands are exact cents.
        # Re-evaluate selected derived measure arithmetic from its native SQL AST
        # and exact selected measures, keeping the actual numerator/denominator.
        for alias,reference in metrics.items():
            view,name=reference.split('.');spec=self.views[view]['measures'][name]
            text=spec['sql'];refs=re.findall(r'\$\{([^}]+)\}',text)
            qualified=[r if '.' in r else view+'.'+r for r in refs]
            if '/' in text and qualified and all(r in metrics.values() for r in qualified):
                mapping={r:next(a for a,f in metrics.items() if f==r) for r in qualified}
                expression=re.sub(r'\$\{([^}]+)\}',lambda m:mapping[m.group(1) if '.' in m.group(1) else view+'.'+m.group(1)],text)
                tree=sqlglot.parse_one(expression,read='snowflake')
                for row in result: row[alias]=exact_arithmetic(tree,row)
        for row in result:
            if any(isinstance(v,float) and (not math.isfinite(v) or math.ulp(v)/2>1e-12) for v in row.values()):
                raise TableauExecutionError('Local ratio precision limit: exact derived inputs unavailable')
        for step in selection.get('presentation',[]):
            alias=step['alias'];input_field=step['input']
            if not IDENTIFIER.fullmatch(alias) or alias in dims or alias in metrics or input_field not in metrics: raise TableauExecutionError('Invalid presentation binding')
            if step['kind']=='scalar_multiply':
                if step.get('parameter')!='multiplier' or step.get('expression')!=input_field+' * multiplier': raise TableauExecutionError('Unsupported scalar presentation')
                for row in result: row[alias]=Decimal(str(row[input_field]))*p['multiplier'] if row[input_field] is not None else None
            elif step['kind']=='partition_share':
                if step.get('stage')!='after_dimension_filters_and_mark_aggregation': raise TableauExecutionError('Unsupported presentation stage')
                partition=step['partition_by'];address=step['address_by']
                if len(set(partition+address))!=len(partition+address) or set(partition+address)!=set(dims): raise TableauExecutionError('Invalid presentation addressing')
                if step.get('expression')!=input_field+' / partition_sum('+input_field+')' or step.get('zero_denominator') is not None: raise TableauExecutionError('Unsupported share expression')
                totals=defaultdict(int)
                for row in result: totals[tuple(row[k] for k in partition)]+=row[input_field] or 0
                for row in result:
                    denominator=totals[tuple(row[k] for k in partition)]
                    row[alias]=divide(Decimal(str(row[input_field])),Decimal(denominator)) if row[input_field] is not None else None
            else: raise TableauExecutionError('Unsupported presentation kind')
        return result,{'sql':compiled,'presentation':selection.get('presentation',[]),'native_omni_execution':False}


def exact_arithmetic(node,row):
    if isinstance(node,exp.Column):
        if node.table or node.name not in row: raise TableauExecutionError('Unbound exact measure input')
        value=row[node.name]
        return None if value is None else Decimal(str(value))
    if isinstance(node,exp.Literal) and not node.is_string: return Decimal(node.this)
    if isinstance(node,exp.Null): return None
    if isinstance(node,exp.Paren): return exact_arithmetic(node.this,row)
    if isinstance(node,exp.Nullif):
        left=exact_arithmetic(node.this,row);right=exact_arithmetic(node.expression,row)
        return None if left==right else left
    if isinstance(node,exp.Coalesce):
        values=[exact_arithmetic(n,row) for n in [node.this,*node.expressions]]
        return next((v for v in values if v is not None),None)
    if isinstance(node,(exp.Add,exp.Sub,exp.Mul,exp.Div)):
        left=exact_arithmetic(node.this,row);right=exact_arithmetic(node.expression,row)
        if left is None or right is None: return None
        if isinstance(node,exp.Add): return left+right
        if isinstance(node,exp.Sub): return left-right
        if isinstance(node,exp.Mul): return left*right
        return divide(left,right)
    raise TableauExecutionError('Unsupported exact derived measure arithmetic')

SOURCE_REPORTS={
 'Revenue Trend':('revenue_trend',{'month':'[Invoice Month]','segment':'[Segment]'},{'revenue_cents':'[Revenue]','paid_cents':'[Paid]','outstanding_cents':'[Outstanding]','payment_rate':'[Payment Rate]','scenario_revenue_cents':'[Scenario Revenue]'}),
 'Customer Value':('customer_value',{'customer_id':'[Customer ID]','segment':'[Segment]'},{'selected_revenue_cents':'[Revenue]','fixed_customer_revenue_cents':'[Displayed Fixed Customer Net]'}),
 'Revenue Share':('revenue_share',{'month':'[Invoice Month]','segment':'[Segment]'},{'revenue_cents':'[Revenue]','share_of_month':'[Revenue Share]'}),
}


def validate_graph(graph):
    if graph.get('counts',{}).get('errors') or not graph.get('static_coverage_complete'):
        raise TableauExecutionError('Tableau extraction contains static gaps')
    if len(graph['workbooks'])!=1 or len(graph['datasources'])!=1 or len(graph['worksheets'])!=3 or {s['name'] for s in graph['worksheets']}!=set(SOURCE_REPORTS):
        raise TableauExecutionError('Tableau workbook/worksheet inventory changed')
    if graph['workbooks'][0].get('attributes',{}).get('version')!='26.1':
        raise TableauExecutionError('Unqualified Tableau workbook version')
    ds=graph['datasources'][0];connection=ds['connection']
    expected={'id':'tableau-billing-snowflake','platform_instance':'DMA_TABLEAU_SYNTHETIC','catalog':'DMA_TABLEAU','schema':'RAW','native_class':'snowflake'}
    if any(connection.get(k)!=v for k,v in expected.items()): raise TableauExecutionError('Tableau connection binding mismatch')
    if len({f['name'] for f in ds['fields']})!=len(ds['fields']): raise TableauExecutionError('Duplicate source field')
    known={f['name'] for f in ds['fields']}
    for sheet in graph['worksheets']:
        role,dims,metrics=SOURCE_REPORTS[sheet['name']]
        if [f['name'] for f in sheet['grouping']]!=list(dims.values()) or [f['name'] for f in sheet['selected_fields']]!=list(metrics.values()):
            raise TableauExecutionError('Tableau selected field/grouping inventory changed')
        if any(f not in known for f in [*dims.values(),*metrics.values()]): raise TableauExecutionError('Selected Tableau field missing')
        if set(sheet['datasource_names'])!={'federated.billing','Parameters'}: raise TableauExecutionError('Unsupported worksheet data sources')
    if len(graph['parameters'])!=5 or {p['caption'] for p in graph['parameters']}!=set(PARAMETER_NAMES): raise TableauExecutionError('Tableau parameter inventory changed')
    defaults={PARAMETER_NAMES[p['caption']]:p['default'] for p in graph['parameters']}
    if defaults!=DEFAULTS: raise TableauExecutionError('Tableau native parameter default drift')
    for p in graph['parameters']:
        parsed=FormulaParser(p['formula']).parse()
        if parsed[0]!='literal' or parsed[1]!=p['default']: raise TableauExecutionError('Tableau parameter formula/value mismatch')
    return {'workbooks':1,'worksheets':3,'fields':len(graph['fields']),'parameters':5,'native_schema':graph['workbooks'][0].get('official_schema_validation')}


def replay_source(case,graph,raw,adjustments,overrides=None):
    validate_graph(graph);p=parameters(overrides)
    for parameter in graph['parameters']:
        value=p[PARAMETER_NAMES[parameter['caption']]]
        domain=parameter.get('domain_type')
        if domain=='list':
            members=[]
            for member in parameter.get('members',[]):
                node=FormulaParser(member).parse()
                if node[0]!='literal': raise TableauExecutionError('Unsupported native parameter member')
                members.append(node[1])
            if not members or value not in members: raise TableauExecutionError('Tableau parameter outside native domain: '+parameter['caption'])
        elif domain=='any':
            if parameter.get('members') or parameter.get('range'): raise TableauExecutionError('Contradictory native parameter domain')
        else: raise TableauExecutionError('Unqualified native Tableau parameter domain')
    repo=(Path(case)/'input/repo').resolve()
    for asset in graph['assets']:
        path=repo/asset['path']
        if path.is_symlink() or repo not in path.resolve().parents or not path.is_file() or sha(path)!=asset['sha256']:
            raise TableauExecutionError('Stale or out-of-scope source asset: '+asset['path'])
    ds=graph['datasources'][0]
    fields={f['name'][1:-1]:dict(f,remote_name=f.get('raw_column')) for f in ds['fields']}
    for f in fields.values():
        if f['formula'] is not None: FormulaParser(f['formula']).parse()
    with connection(raw,adjustments) as con: raw_rows,sql=query(con,ds['custom_sql'],RAW_RELATIONS)
    interpreter=TableauFormula(fields,p,raw_rows)
    projection={'tenant_id':'[Tenant ID]','invoice_id':'[Invoice ID]','customer_id':'[Customer ID]','invoice_date':'[Invoice Date]','invoice_month':'[Invoice Month]','status':'[Status]','segment':'[Segment]','amount_cents':'[Amount Cents]','net_cents':'[Net Cents]','paid_cents':'[Paid Cents]','outstanding_cents':'[Outstanding Cents]'}
    invoices=[{alias:interpreter.value(ref,raw_rows,row) for alias,ref in projection.items()} for row in raw_rows]
    invoices.sort(key=lambda r:(r['tenant_id'],r['invoice_id']))
    executed=interpreter.executed|{x['id'] for x in graph['parameters']};outputs={};traces=[]
    def filtered(rows,filters,formula):
        for f in filters:
            if f.get('member') is not True or f.get('field_name') is None: raise TableauExecutionError('Unsupported native Tableau filter membership')
            rows=[r for r in rows if formula.value(f['field_name'],rows,r) is True]
        return rows
    for sheet in graph['worksheets']:
        role,dims,metrics=SOURCE_REPORTS[sheet['name']]
        formula=TableauFormula(fields,p,raw_rows)
        population=filtered(raw_rows,ds['filters'],formula)
        if any(f['stage'] not in ('context','dimension') for f in sheet['filters']): raise TableauExecutionError('Unsupported Tableau filter stage')
        context=filtered(population,[f for f in sheet['filters'] if f['stage']=='context'],formula)
        formula.context=context
        selected=filtered(context,[f for f in sheet['filters'] if f['stage']=='dimension'],formula)
        groups=defaultdict(list)
        for row in selected: groups[tuple(formula.value(ref,selected,row) for ref in dims.values())].append(row)
        calculations=sheet['table_calculations'];partition_indices=None
        if role=='revenue_share':
            if len(calculations)!=1 or calculations[0]['column']!='[Revenue Share]': raise TableauExecutionError('Missing table-calculation addressing')
            calculation=calculations[0];partition=calculation['partitioning'];address=calculation['addressing']
            if len(set(partition+address))!=len(partition+address) or set(partition+address)!=set(dims.values()): raise TableauExecutionError('Invalid native table-calculation partition/address')
            partition_indices=[list(dims.values()).index(x) for x in partition]
        elif calculations: raise TableauExecutionError('Unexpected source table calculation')
        marks=[]
        for key,rows in sorted(groups.items()):
            partition=[v for k,v in groups.items() if tuple(k[i] for i in partition_indices)==tuple(key[i] for i in partition_indices)] if partition_indices is not None else None
            mark=dict(zip(dims,key))
            for alias,ref in metrics.items(): mark[alias]=formula.value(ref,rows,None,partition)
            marks.append(mark)
        outputs[role]=marks;executed|=formula.executed
        traces.append({'worksheet_id':sheet['id'],'source_sql':sql,'population_count':len(population),'context_count':len(context),'selected_count':len(selected),
            'native_filters':ds['filters']+sheet['filters'],'table_calculations':calculations,'mark_count':len(marks),'executed_field_ids':sorted(formula.executed)})
    return outputs,{'invoices':invoices,'projection':list(projection),'executed_field_ids':sorted(executed)},traces
