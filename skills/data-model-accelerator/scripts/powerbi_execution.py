"""Bounded synthetic PowerBI and Omni replay; not native vendor execution.

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

class PowerBIExecutionError(ValueError): pass

from hex_execution import FUNCTION_NAMES as SHARED_FUNCTION_NAMES, NODE_NAMES as SHARED_NODE_NAMES
from sqlglot.optimizer.scope import traverse_scope, Scope
FUNCTION_NAMES=SHARED_FUNCTION_NAMES|{'TimeToStr'}
NODE_NAMES=SHARED_NODE_NAMES|{'TimeToStr'}

def checked_sql(sql,relations,frames=(),dialect='snowflake'):
    try: trees=sqlglot.parse(sql,read=dialect,error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as error: raise PowerBIExecutionError('SQL parse failed') from error
    if len(trees)!=1 or not isinstance(trees[0],(exp.Select,exp.Union)): raise PowerBIExecutionError('Exactly one SELECT/UNION is supported')
    tree=trees[0]
    for node in tree.walk():
        if type(node).__name__ not in NODE_NAMES: raise PowerBIExecutionError('Unsupported SQL construct '+type(node).__name__)
        if isinstance(node,exp.Func) and type(node).__name__ not in FUNCTION_NAMES: raise PowerBIExecutionError('Unsupported SQL function '+type(node).__name__)
        if isinstance(node,exp.Identifier) and not IDENTIFIER.fullmatch(node.name): raise PowerBIExecutionError('Unsupported SQL identifier')
        if dialect=='snowflake' and isinstance(node,exp.Column):
            ident=node.this
            if isinstance(ident,exp.Identifier) and ident.args.get('quoted') and ident.name!=ident.name.upper():
                raise PowerBIExecutionError('Quoted column identity does not match uppercase Snowflake catalogue')
        if isinstance(node,exp.With) and (node.args.get('recursive') or len({c.alias.lower() for c in node.expressions})!=len(node.expressions)):
            raise PowerBIExecutionError('Recursive/duplicate SQL bindings unsupported')
    try:
        for scope in traverse_scope(tree):
            for _,(node,source) in scope.selected_sources.items():
                if isinstance(source,Scope): continue
                if not isinstance(source,exp.Table) or not isinstance(source.this,exp.Identifier): raise PowerBIExecutionError('SQL table function denied')
                identity=(source.catalog.upper(),source.db.upper(),source.name.upper())
                for part in ('catalog','db','this'):
                    ident=source.args.get(part)
                    if isinstance(ident,exp.Identifier) and ident.args.get('quoted') and ident.name!=ident.name.upper():
                        raise PowerBIExecutionError('Quoted source identity does not match uppercase Snowflake catalogue')
                if identity not in relations and not (not source.catalog and not source.db and source.name in frames):
                    raise PowerBIExecutionError('SQL source outside declared relations: '+'.'.join(identity))
    except PowerBIExecutionError: raise
    except Exception as error: raise PowerBIExecutionError('SQL relation binding failed') from error
    for node in tree.find_all(exp.TimeToStr):
        fmt=node.args.get('format')
        if not isinstance(fmt,exp.Literal) or fmt.this!='%Y-%m-%d':
            raise PowerBIExecutionError('Unsupported fixture date format')
    for node in list(tree.find_all(exp.ToChar)):
        fmt=node.args.get('format')
        if not isinstance(fmt,exp.Literal) or fmt.this!='YYYY-MM-DD':
            raise PowerBIExecutionError('Unsupported fixture date format')
        node.replace(exp.TimeToStr(this=node.this.copy(),format=exp.Literal.string('%Y-%m-%d')))
    return tree.sql(dialect='duckdb',unsupported_level=sqlglot.ErrorLevel.RAISE)


MODEL_MAP = {
 'billing_invoices':('SILVER','BILLING_INVOICES'), 'billing_payments':('SILVER','BILLING_PAYMENTS'),
 'billing_customer_history':('SILVER','BILLING_CUSTOMER_HISTORY'), 'billing_adjustments':('SILVER','BILLING_ADJUSTMENTS'),
 'dim_customers':('GOLD','DIM_CUSTOMERS'), 'fct_invoices':('GOLD','FCT_INVOICES'),
}
RAW_RELATIONS={('DMA_POWERBI','RAW',t) for t in RAW_COLUMNS}
TARGET_RELATIONS=RAW_RELATIONS|{('DMA_POWERBI',*v) for v in MODEL_MAP.values()}
DEFAULTS={'tenant':'A','start_date':'2026-01-01','end_date':'2026-03-01','segment':'ALL','status':'posted','multipliers':[1]}

def parameters(overrides=None, defaults=None):
    p=dict(DEFAULTS if defaults is None else defaults)
    if overrides is not None:
        if not isinstance(overrides,dict) or set(overrides)-set(DEFAULTS)-{'authorized','persona_tenant','role'}:
            raise PowerBIExecutionError('Unsupported report parameters')
        p.update(overrides)
    if p.get('tenant') not in ('A','B') or p.get('authorized',True) is not True or p.get('persona_tenant',p['tenant'])!=p['tenant'] or p.get('role','Tenant'+p['tenant'])!='Tenant'+p['tenant']:
        raise PowerBIExecutionError('Tenant/persona/role access denied')
    p['role']='Tenant'+p['tenant']
    try:
        for name in ('start_date','end_date'):
            if not isinstance(p[name],str) or date.fromisoformat(p[name]).isoformat()!=p[name]: raise ValueError()
        if p['start_date']>p['end_date']: raise ValueError()
    except (ValueError,TypeError,KeyError): raise PowerBIExecutionError('Invalid date window')
    if not isinstance(p.get('segment'),str) or len(p['segment'])>100: raise PowerBIExecutionError('Invalid segment')
    if p.get('status') not in ('posted','draft'): raise PowerBIExecutionError('Invalid status')
    values=p.get('multipliers')
    if not isinstance(values,list) or any(type(v) is not int or v not in (1,2) for v in values) or len(values)!=len(set(values)):
        raise PowerBIExecutionError('Invalid multiplier selection')
    return p

def literal(value):
    if isinstance(value,Decimal): return str(value)
    if isinstance(value,str): return "'"+value.replace("'","''")+"'"
    raise PowerBIExecutionError('Unsupported bound literal')

def divide(left,right):
    if left is None or right is None or right==0: return None
    with localcontext() as context:
        context.prec=50
        return Decimal(left)/Decimal(right)

def connection(raw,adjustments):
    validate_inputs(raw,adjustments)
    con=duckdb.connect(':memory:',config={'autoinstall_known_extensions':'false','autoload_known_extensions':'false','threads':'1'})
    con.execute("ATTACH ':memory:' AS DMA_POWERBI")
    con.execute('SET enable_external_access=false')
    for schema in ('RAW','SILVER','GOLD'): con.execute('CREATE SCHEMA DMA_POWERBI.'+schema)
    for name,columns in RAW_COLUMNS.items():
        con.execute('CREATE TABLE DMA_POWERBI.RAW.'+name+' ('+','.join(k+' '+v for k,v in columns.items())+')')
        data=adjustments if name=='ADJUSTMENTS' else raw[name]
        if data: con.executemany('INSERT INTO DMA_POWERBI.RAW.'+name+' VALUES ('+','.join('?' for k in columns)+')',[[r[k] for k in columns] for r in data])
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
        except SyntaxError as error: raise PowerBIExecutionError('Invalid dbt config') from error
        if not isinstance(call,ast.Call) or call.args: raise PowerBIExecutionError('Unsupported dbt config')
        seen=set()
        for item in call.keywords:
            if item.arg not in ('schema','alias','materialized') or item.arg in seen or not isinstance(item.value,ast.Constant) or not isinstance(item.value.value,str):
                raise PowerBIExecutionError('Unsupported dbt config/hook')
            seen.add(item.arg)
            if item.arg=='materialized' and item.value.value!='table': raise PowerBIExecutionError('Unsupported dbt materialization')
        return ''
    source=re.sub(r'{{\s*config\(([^{}]*)\)\s*}}',config,source)
    def ref(match):
        name=match.group(1)
        if name not in MODEL_MAP: raise PowerBIExecutionError('Unresolved dbt ref '+name)
        return 'DMA_POWERBI.'+'.'.join(MODEL_MAP[name])
    def raw(match):
        name=match.group(1).upper()
        if name not in RAW_COLUMNS: raise PowerBIExecutionError('Unresolved dbt source '+name)
        return 'DMA_POWERBI.RAW.'+name
    source=re.sub(r"{{\s*ref\(['\"]([a-z_]+)['\"]\)\s*}}",ref,source)
    source=re.sub(r"{{\s*source\(['\"]raw['\"],\s*['\"]([a-z_]+)['\"]\)\s*}}",raw,source)
    if any(mark in source for mark in ('{{','{%','${')): raise PowerBIExecutionError('Unsupported dbt template')
    return source

def build_models(con,dbt_root):
    root=Path(dbt_root);compiled=[]
    paths=list((root/'models').rglob('*.sql'))
    files={p.stem:p for p in paths}
    if len(paths)!=len(files): raise PowerBIExecutionError('Duplicate dbt model identity')
    if set(files)!=set(MODEL_MAP): raise PowerBIExecutionError('dbt model inventory changed')
    for name,(schema,table) in MODEL_MAP.items():
        source=files[name].read_text();sql=render_dbt(source)
        configs=re.findall(r'{{\s*config\(([^{}]*)\)\s*}}',source)
        if len(configs)!=1: raise PowerBIExecutionError('One explicit fixture model config required')
        call=ast.parse('config('+configs[0]+')',mode='eval').body
        values={item.arg:item.value.value for item in call.keywords}
        if values!={'schema':schema,'alias':table,'materialized':'table'}: raise PowerBIExecutionError('dbt model destination/config differs from declared model map')
        query=checked_sql(sql,TARGET_RELATIONS)
        con.execute('CREATE OR REPLACE TABLE DMA_POWERBI.'+schema+'.'+table+' AS '+query)
        compiled.append({'model':name,'path':str(files[name].relative_to(root)),'sha256':sha(files[name]),'sql':query})
    return compiled


from powerbi_languages import DAXParser, DAXSubset, evaluate_m, LanguageError
from tableau_execution import exact_arithmetic

CONTEXT_ORDER=['security','ordinary_report_filters','relationship_propagation','per_measure_context_changes','aggregate_in_context','presentation']
BINDINGS={'tenant':'invoices.tenant_id','date':'invoices.invoice_date','segment':'customers.segment','status':'invoices.status'}


class OmniSubset:
    """Independently render candidate Omni definitions into guarded local SQL.

Changed-context measures use separate aggregate queries even when outer facts
are absent. That local contract is explicit; native Omni acceptance is pending.
    """
    def __init__(self,root):
        self.root=Path(root)
        self.views={p.stem:yaml.safe_load(p.read_text()) for p in sorted(self.root.glob('*.view'))}
        self.topic=yaml.safe_load((self.root/'billing.topic').read_text())
        self.relationships=yaml.safe_load((self.root/'relationships').read_text())
        self.companion=json.loads((self.root/'report-context.json').read_text())
        if set(self.views)!={'invoices','customers'} or self.topic.get('base_view')!='invoices' or self.topic.get('joins')!={'customers':{}}: raise PowerBIExecutionError('Omni view/topic inventory mismatch')
        expected=[{'field':'invoices.tenant_id','user_attribute':'tenant_id'},{'field':'customers.tenant_id','user_attribute':'tenant_id'}]
        if self.topic.get('access_filters')!=expected: raise PowerBIExecutionError('Omni tenant security contract mismatch')
        if len(self.relationships)!=1: raise PowerBIExecutionError('Omni relationship inventory mismatch')
        rel=self.relationships[0]
        if {k:rel.get(k) for k in ('join_from_view','join_to_view','join_type','relationship_type')}!={'join_from_view':'invoices','join_to_view':'customers','join_type':'always_left','relationship_type':'many_to_one'}: raise PowerBIExecutionError('Unsupported Omni relationship')
        if re.sub(r'\s+',' ',rel.get('on_sql','')).strip()!='${invoices.customer_key} = ${customers.customer_key} AND ${invoices.tenant_id} = ${customers.tenant_id}': raise PowerBIExecutionError('Omni composite join mismatch')
        if self.companion.get('kind')!='synthetic_powerbi_report_context' or self.companion.get('native_omni_artifact') is not False or self.companion.get('defaults')!=DEFAULTS: raise PowerBIExecutionError('Omni report companion/default mismatch')
        if self.companion.get('security')!={'ordinary_measure_filters_cannot_remove':['invoices.tenant_id','customers.tenant_id'],'source_role_tables':['Invoices','Customers'],'relationship_required':True}: raise PowerBIExecutionError('Omni companion security mismatch')
        parameter_contract={
            'tenant':{'allowed':['A','B'],'required':True,'role_map':{'A':'TenantA','B':'TenantB'},'persona_must_match':True,'authorization_required':True},
            'date_window':{'format':'YYYY-MM-DD','lower':'inclusive','upper':'exclusive','equal_endpoints':'empty','reversed':'error'},
            'segment':{'type':'string','all_value':'ALL'},'status':{'allowed':['posted','draft']},
            'multipliers':{'allowed':[1,2],'unique':True,'selection':'sole_selected_value_else_alternate','alternate':1}}
        if self.companion.get('parameter_contract')!=parameter_contract: raise PowerBIExecutionError('Omni parameter contract contradicts execution')
        context_contracts={
            'invoices.all_segment_revenue_cents':{'behavior':'remove_only_segment','remove_query_filters':['customers.segment'],'remove_grouping':['customers.segment'],'preserve':['invoices.invoice_month','invoices.invoice_date','invoices.status','security'],'evaluate_on_independent_changed_context':True,'native_runtime_status':'candidate_not_executed'},
            'invoices.posted_revenue_cents':{'behavior':'replace_status','replace_query_filters':{'invoices.status':'posted'},'preserve':['customers.segment','invoices.invoice_month','invoices.invoice_date','security'],'evaluate_on_independent_changed_context':True,'native_runtime_status':'candidate_not_executed'},
            'invoices.posted_intersection_cents':{'behavior':'intersect_status','intersect_query_filters':{'invoices.status':'posted'},'preserve':['customers.segment','invoices.invoice_month','invoices.invoice_date','security'],'native_runtime_status':'candidate_not_executed'}}
        if self.companion.get('measure_context_contracts')!=context_contracts: raise PowerBIExecutionError('Omni measure context contract contradicts execution')
        blank=self.companion.get('blank_contract',{})
        if blank!={'representation':None,'empty_sum':None,'divide_zero_or_blank_denominator':None,'multiply_blank':None,'coalesce_aggregates':False}: raise PowerBIExecutionError('Omni BLANK contract mismatch')
        for view,physical in [('invoices','FCT_INVOICES'),('customers','DIM_CUSTOMERS')]:
            v=self.views[view]
            if (v.get('catalog'),v.get('schema'),v.get('table_name'))!=('DMA_POWERBI','GOLD',physical): raise PowerBIExecutionError('Omni physical namespace mismatch')
        self.trace=[]
    def dimension(self,reference):
        if not isinstance(reference,str) or reference.count('.')!=1: raise PowerBIExecutionError('Unqualified Omni dimension')
        view,name=reference.split('.')
        spec=self.views.get(view,{}).get('dimensions',{}).get(name)
        if not isinstance(spec,dict) or set(spec)-{'sql','description','label','hidden','primary_key','format','group_label'}: raise PowerBIExecutionError('Unsupported Omni dimension')
        column=spec.get('sql','')
        if not re.fullmatch(r'"[A-Z][A-Z_0-9]*"',column): raise PowerBIExecutionError('Unsupported Omni dimension SQL')
        return view+'.'+column
    def base(self):
        return ' FROM DMA_POWERBI.GOLD.FCT_INVOICES invoices LEFT JOIN DMA_POWERBI.GOLD.DIM_CUSTOMERS customers ON '+re.sub(r'\$\{([^}]+)\}',lambda m:self.dimension(m[1]),self.relationships[0]['on_sql'])
    def where(self,context,p):
        clauses=[self.dimension(f)+' = '+literal(p['tenant']) for f in ('invoices.tenant_id','customers.tenant_id')]
        for field,allowed in context.items():
            column=self.dimension(field)
            if isinstance(allowed,set):
                clauses.append(column+' IN ('+','.join(literal(v) for v in sorted(allowed))+')' if allowed else '1 = 0')
            else:
                clauses.extend([column+' >= '+literal(allowed[0]),column+' < '+literal(allowed[1])])
        return ' WHERE '+' AND '.join(clauses)
    def metric(self,reference,context,p,con,stack=()):
        if reference in stack or reference.count('.')!=1: raise PowerBIExecutionError('Cyclic/unqualified Omni measure')
        view,name=reference.split('.');spec=self.views.get(view,{}).get('measures',{}).get(name)
        if not isinstance(spec,dict) or set(spec)-{'sql','aggregate_type','label','format','description','filters','level_of_detail','group_label'}: raise PowerBIExecutionError('Unsupported Omni measure')
        changed=dict(context);aggregate=spec.get('aggregate_type');lod=spec.get('level_of_detail')
        if lod is not None:
            if aggregate!='min' or lod!={'aggregate_type':'sum','always_exclude':['customers.segment'],'filters':{'customers.segment':{'is':'','cancel_query_filter':True}}}: raise PowerBIExecutionError('Unsupported Omni LOD scope')
            aggregate=lod['aggregate_type'];changed.pop('customers.segment',None)
        for field,filter_spec in spec.get('filters',{}).items():
            if field!='invoices.status' or set(filter_spec)-{'is','cancel_query_filter'} or not isinstance(filter_spec.get('is'),str) or ('cancel_query_filter' in filter_spec and type(filter_spec['cancel_query_filter']) is not bool): raise PowerBIExecutionError('Unsupported Omni measure filter')
            values={filter_spec['is']}
            if not filter_spec.get('cancel_query_filter',False) and field in changed: values &= changed[field]
            changed[field]=values
        sql=spec.get('sql','')
        if aggregate:
            if aggregate not in ('sum','min','max'): raise PowerBIExecutionError('Unsupported Omni aggregate')
            match=re.fullmatch(r'\$\{([^}]+)\}',sql)
            if not match: raise PowerBIExecutionError('Unsupported Omni aggregate expression')
            expression=self.dimension(match[1])
            statement='SELECT '+aggregate.upper()+'('+expression+') AS VALUE'+self.base()+self.where(changed,p)
            rows,compiled=query(con,statement);self.trace.append({'measure':reference,'sql':compiled,'changed_context':{k:sorted(v) if isinstance(v,set) else list(v) for k,v in changed.items()},'local_lod_adapter':bool(lod)})
            if len(rows)!=1: raise PowerBIExecutionError('Omni aggregate cardinality mismatch')
            return rows[0]['value']
        if spec.get('filters') or lod: raise PowerBIExecutionError('Derived measure filters unsupported')
        values={}
        def substitute(match):
            ref=match[1] if '.' in match[1] else view+'.'+match[1]
            key='v'+str(len(values));values[key]=self.metric(ref,changed,p,con,stack+(reference,));return key
        expression=re.sub(r'\$\{([^}]+)\}',substitute,sql)
        return exact_arithmetic(sqlglot.parse_one(expression,read='snowflake'),values)
    def render(self,con,role,overrides=None):
        p=parameters(overrides,self.companion['defaults']);selection=self.companion['reports'][role]
        if selection.get('topic')!='billing' or selection.get('runtime_field_bindings')!=BINDINGS or selection.get('context_order')!=CONTEXT_ORDER or selection.get('filters')!={}: raise PowerBIExecutionError('Omni report context/order mismatch')
        dimensions=selection['dimensions'];measures=selection['measures']
        if any(not IDENTIFIER.fullmatch(k) for k in list(dimensions)+list(measures)) or not measures: raise PowerBIExecutionError('Invalid Omni report aliases')
        context={'invoices.invoice_date':(p['start_date'],p['end_date']),'invoices.status':{p['status']}}
        if p['segment']!='ALL': context['customers.segment']={p['segment']}
        self.trace=[]
        if dimensions:
            if selection.get('row_policy')!='visible_selected_fact_keys' or selection.get('empty_population')!='zero_rows' or selection.get('sorts')!=list(dimensions): raise PowerBIExecutionError('Unsupported Omni grouped row policy')
            sql='SELECT '+','.join(self.dimension(f)+' AS '+a for a,f in dimensions.items())+self.base()+self.where(context,p)+' GROUP BY '+','.join(str(i+1) for i in range(len(dimensions)))+' ORDER BY '+','.join(dimensions)
            groups,compiled=query(con,sql);self.trace.append({'group_keys_sql':compiled})
        else:
            if selection.get('row_policy')!='one_row_recomputed' or selection.get('empty_population')!='one_row_per_measure_context' or selection.get('totals')!='recompute_in_own_context' or selection.get('sorts')!=[]: raise PowerBIExecutionError('Unsupported Omni total row policy')
            groups=[{}]
        result=[]
        for group in groups:
            current=dict(context)
            for alias,field in dimensions.items(): current[field]={group[alias]} & current.get(field,{group[alias]})
            row=dict(group)
            for alias,reference in measures.items(): row[alias]=self.metric(reference,current,p,con)
            for step in selection.get('presentation',[]):
                if {k:step.get(k) for k in ('kind','parameter','allowed_values','alternate','blank_input','expression')}!={'kind':'selected_value_multiply','parameter':'multipliers','allowed_values':[1,2],'alternate':1,'blank_input':None,'expression':step['input']+' * sole_selected_value_or_1(multipliers)'}: raise PowerBIExecutionError('Unsupported Omni presentation selection')
                if step['input'] not in measures or step['alias'] in row or not IDENTIFIER.fullmatch(step['alias']): raise PowerBIExecutionError('Invalid Omni presentation binding')
                factor=p['multipliers'][0] if len(p['multipliers'])==1 else step['alternate']
                row[step['alias']]=None if row[step['input']] is None else row[step['input']]*factor
            result.append(row)
        return result,{'queries':self.trace,'presentation':selection.get('presentation',[]),'native_omni_execution':False}


SOURCE_REPORTS={
 'Revenue Trend':('revenue_trend',{'month':('Invoices','Invoice Month'),'segment':('Customers','Segment')},{'revenue_cents':'Revenue Cents','paid_cents':'Paid Cents','outstanding_cents':'Outstanding Cents','payment_rate':'Payment Rate','scenario_revenue_cents':'Scenario Revenue Cents'}),
 'Segment Share':('segment_share',{'month':('Invoices','Invoice Month'),'segment':('Customers','Segment')},{'revenue_cents':'Revenue Cents','all_segment_revenue_cents':'All Segment Revenue Cents','share_all_segments':'Share All Segments'}),
 'KPI Totals':('kpi_totals',{}, {'revenue_cents':'Revenue Cents','paid_cents':'Paid Cents','outstanding_cents':'Outstanding Cents','payment_rate':'Payment Rate','all_segment_revenue_cents':'All Segment Revenue Cents','share_all_segments':'Share All Segments','posted_revenue_cents':'Posted Revenue Cents','posted_intersection_cents':'Posted Intersection Cents','scenario_revenue_cents':'Scenario Revenue Cents'}),
}


def validate_graph(graph):
    filters=[(f['id'],f['table'],f['column'],f['operator'],f['values'],f['scope']) for f in graph.get('filters',[])]
    expected_filters=[('ReportingStart','Invoices','Invoice Date','gte',['2026-01-01'],'report'),('ReportingEnd','Invoices','Invoice Date','lt',['2026-03-01'],'report'),('StatusSelection','Invoices','Status','in',['posted'],'report'),('SegmentSelection','Customers','Segment','all',[],'report'),('MultiplierSelection','Scenario','Multiplier','in',[1],'report')]
    if filters!=expected_filters or len(graph.get('pages',[]))!=1 or any(v.get('filters') for v in graph.get('visuals',[])): raise PowerBIExecutionError('Unsupported source report/page/visual filter context')
    database=graph['model'];model=database['model']
    if database.get('compatibilityLevel')!=1600: raise PowerBIExecutionError('Unqualified tabular compatibility level')
    if set(model)-{'name','culture','defaultPowerBIDataSourceVersion','tables','relationships','roles'}: raise PowerBIExecutionError('Unsupported semantic-model feature')
    tables=model['tables']
    if len(tables)!=3 or {t['name'] for t in tables}!={'Invoices','Customers','Scenario'}: raise PowerBIExecutionError('Source table inventory mismatch')
    expected={'type':'singleColumn','fromTable':'Invoices','fromColumn':'Customer History Key','fromCardinality':'many','toTable':'Customers','toColumn':'Customer History Key','toCardinality':'one','isActive':True,'crossFilteringBehavior':'oneDirection','securityFilteringBehavior':'oneDirection'}
    relationships=model.get('relationships',[])
    if len(relationships)!=1 or {k:v for k,v in relationships[0].items() if k!='name'}!=expected: raise PowerBIExecutionError('Unsupported source relationship/grain/direction')
    roles=model.get('roles',[])
    if len(roles)!=2 or {r['name'] for r in roles}!={'TenantA','TenantB'}: raise PowerBIExecutionError('Source tenant role inventory mismatch')
    for role in roles:
        tenant=role['name'][-1]
        if set(role)!={'name','modelPermission','tablePermissions'} or role['modelPermission']!='read' or len(role['tablePermissions'])!=2: raise PowerBIExecutionError('Unsupported source role')
        if {r['name'] for r in role['tablePermissions']}!={'Invoices','Customers'}: raise PowerBIExecutionError('Source role must constrain both tables')
        for permission in role['tablePermissions']:
            if set(permission)!={'name','filterExpression'} or DAXParser(permission['filterExpression']).parse()!=('binary','=',('column',permission['name'],'Tenant ID'),('literal',tenant)): raise PowerBIExecutionError('Source tenant role expression mismatch')
    columns=[];measures=[]
    for table in tables:
        if set(table)-{'name','lineageTag','columns','partitions','measures'}: raise PowerBIExecutionError('Unsupported source table feature')
        if len(table.get('partitions',[]))!=1 or table['partitions'][0].get('mode')!='import' or table['partitions'][0].get('source',{}).get('type')!='m': raise PowerBIExecutionError('Unsupported source partition/storage mode')
        columns.extend((table['name'],c['name']) for c in table['columns']);measures.extend(m['name'] for m in table.get('measures',[]))
    if len(columns)!=20 or len(set(columns))!=20 or len(measures)!=9 or len(set(measures))!=9: raise PowerBIExecutionError('Source field inventory mismatch')
    if graph.get('counts',{}).get('errors') or any(g.get('kind') not in ('native_runtime_unverified','bounded_semantics') for g in graph.get('gaps',[])):
        raise PowerBIExecutionError('Unresolved Power BI extraction: '+'; '.join(g.get('kind','')+': '+g.get('message','') for g in graph.get('gaps',[]) if g.get('kind') not in ('native_runtime_unverified','bounded_semantics')))
    return {'tables':3,'columns':20,'measures':9,'relationships':1,'roles':2}


class SourceReplay:
    def __init__(self,case,graph,raw,adjustments):
        validate_graph(graph);self.graph=graph;self.model=graph['model']['model'];self.case=Path(case)
        from powerbi_source import inspect_repo
        current=inspect_repo(self.case/'input/repo')
        if current!=graph: raise PowerBIExecutionError('Stale or altered source graph')
        self.tables={};self.measures={};self.traces=[];self.executed_columns=[]
        with connection(raw,adjustments) as con:
            for table in self.model['tables']:
                partition=table['partitions'][0]
                if set(partition)-{'name','mode','source'} or set(partition['source'])!={'type','expression'}: raise PowerBIExecutionError('Unsupported partition metadata')
                expression=partition['source']['expression']
                if isinstance(expression,list): expression='\n'.join(expression)
                records,trace=evaluate_m(expression,lambda sql:query(con,sql,RAW_RELATIONS))
                self.traces.append({'table':table['name'],'partition':partition['name'],'steps':trace})
                rows=[]
                source_columns=[c for c in table['columns'] if c.get('type')!='calculated'];calculated=[c for c in table['columns'] if c.get('type')=='calculated']
                if len({c['sourceColumn'] for c in source_columns})!=len(source_columns): raise PowerBIExecutionError('Duplicate sourceColumn mapping')
                for record in records:
                    if set(record)!={c['sourceColumn'] for c in source_columns}: raise PowerBIExecutionError('M output/sourceColumn inventory mismatch')
                    row={(table['name'],c['name']):record[c['sourceColumn']] for c in source_columns}
                    for column in calculated:
                        row[(table['name'],column['name'])]=DAXSubset([],{},[]).value(DAXParser(column['expression']).parse(),{},row)
                    for column in table['columns']:
                        if set(column)-{'name','dataType','lineageTag','summarizeBy','sourceColumn','type','expression','formatString'}: raise PowerBIExecutionError('Unsupported source column metadata')
                        cell=row[(table['name'],column['name'])];dtype=column['dataType']
                        if dtype not in ('string','int64','dateTime'): raise PowerBIExecutionError('Unsupported source column type')
                        if cell is not None:
                            if dtype=='int64' and (type(cell) is not int or not -(2**63)<=cell<2**63): raise PowerBIExecutionError('Source int64 type/precision mismatch')
                            if dtype=='string' and not isinstance(cell,str): raise PowerBIExecutionError('Source string type mismatch')
                            if dtype=='dateTime' and (not isinstance(cell,str) or date.fromisoformat(cell).isoformat()!=cell): raise PowerBIExecutionError('Source ISO date adaptation mismatch')
                    rows.append(row)
                self.tables[table['name']]=rows
                self.executed_columns.extend(table['name']+'.'+c['name'] for c in table['columns'])
                for measure in table.get('measures',[]):
                    if set(measure)-{'name','expression','lineageTag','formatString'}: raise PowerBIExecutionError('Unsupported source measure metadata')
                    self.measures[measure['name']]=measure['expression']
        customer_key=('Customers','Customer History Key');customers={r[customer_key]:r for r in self.tables['Customers']}
        if len(customers)!=len(self.tables['Customers']) or None in customers: raise PowerBIExecutionError('Source relationship one-side uniqueness failed')
        invoice_keys=[r[('Invoices','Invoice Key')] for r in self.tables['Invoices']]
        if len(invoice_keys)!=len(set(invoice_keys)) or None in invoice_keys: raise PowerBIExecutionError('Source invoice grain/fanout failed')
        self.joined=[]
        for row in self.tables['Invoices']:
            key=row[('Invoices','Customer History Key')]
            if key not in customers: raise PowerBIExecutionError('Source relationship orphan')
            customer=customers[key]
            if row[('Invoices','Tenant ID')]!=customer[('Customers','Tenant ID')]: raise PowerBIExecutionError('Cross-tenant source relationship')
            self.joined.append(dict(row,**{})|customer)
        # Projection is a crosswalk only. Nullable raw adjustment remains source
        # evidence; it is not recast as a computed zero merely to match target.
        self.projection={'tenant_id':('Invoices','Tenant ID'),'invoice_id':('Invoices','Invoice ID'),'customer_id':('Invoices','Customer ID'),'invoice_date':('Invoices','Invoice Date'),'invoice_month':('Invoices','Invoice Month'),'status':('Invoices','Status'),'segment':('Customers','Segment'),'amount_cents':('Invoices','Amount Cents'),'net_cents':('Invoices','Net Cents'),'paid_cents':('Invoices','Paid Cents'),'outstanding_cents':('Invoices','Outstanding Cents'),'invoice_key':('Invoices','Invoice Key'),'customer_key':('Invoices','Customer History Key')}
        self.invoices=sorted([{k:r[v] for k,v in self.projection.items()} for r in self.joined],key=lambda r:(r['tenant_id'],r['invoice_id']))
    def render(self,overrides=None):
        defaults=dict(DEFAULTS);native=self.graph['report_defaults']
        for key in ('start_date','end_date','segment','status','multipliers'):
            if key not in native: raise PowerBIExecutionError('Native report default missing: '+key)
            defaults[key]=native[key]
        if defaults!=DEFAULTS: raise PowerBIExecutionError('Native report defaults drift')
        p=parameters(overrides,defaults)
        # Evaluate actual authored role predicates on both sides, before query
        # context exists. SELECTEDVALUE uses the disconnected source domain.
        role=next(r for r in self.model['roles'] if r['name']==p['role']);permissions={r['name']:DAXParser(r['filterExpression']).parse() for r in role['tablePermissions']}
        evaluator=DAXSubset([],{},[])
        secured=[r for r in self.joined if all(evaluator.value(expression,{},r) is True for expression in permissions.values())]
        domain={r[('Scenario','Multiplier')] for r in self.tables['Scenario']}
        if not set(p['multipliers'])<=domain: raise PowerBIExecutionError('Selection outside native Scenario domain')
        dax=DAXSubset(secured,self.measures,p['multipliers'])
        context={('Invoices','Invoice Date'):(p['start_date'],p['end_date']),('Invoices','Status'):{p['status']}}
        if p['segment']!='ALL': context[('Customers','Segment')]={p['segment']}
        visuals=self.graph['visuals'];outputs={};traces=[]
        if len(visuals)!=3 or {v['title'] for v in visuals}!=set(SOURCE_REPORTS): raise PowerBIExecutionError('Source visual inventory mismatch')
        for visual in visuals:
            role,dims,metrics=SOURCE_REPORTS[visual['title']]
            projections=[(p['kind'],p['table'],p['property']) for p in visual['projections']]
            expected=[('column',*ref) for ref in dims.values()]+[('measure','Scenario',name) for name in metrics.values()]
            if projections!=expected: raise PowerBIExecutionError('Source visual projection/order mismatch')
            groups=sorted({tuple(r[k] for k in dims.values()) for r in dax.selected(context)}) if dims else [()]
            rows=[]
            for key in groups:
                changed=dict(context)
                for field,cell in zip(dims.values(),key): changed[field]={cell} & changed.get(field,{cell})
                row=dict(zip(dims,key));row.update({alias:dax.measure(name,changed) for alias,name in metrics.items()});rows.append(row)
            outputs[role]=rows;traces.append({'visual_id':visual['id'],'role':role,'security_role':p['role'],'rows':len(rows),'secured_fact_count':len(secured),'selected_fact_count':len(dax.selected(context)),'measures_executed':sorted(dax.executed)})
        return outputs,{'invoices':self.invoices,'projection':list(self.projection),'executed_columns':self.executed_columns,'executed_measures':sorted(dax.executed),'partition_traces':self.traces},traces


def replay_source(case,graph,raw,adjustments,overrides=None):
    return SourceReplay(case,graph,raw,adjustments).render(overrides)
