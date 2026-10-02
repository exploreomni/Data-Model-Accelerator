#!/usr/bin/env python3
"""Run the authored Power BI -> warehouse -> Omni local qualification case."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
import importlib.metadata
import json
from pathlib import Path
import shutil
import tempfile
import yaml

import powerbi_execution as p
from powerbi_source import inspect_repo
from powerbi_catalogue import build_catalogue
from run_hex_omni_e2e import doc_contract


def write(path,value): Path(path).write_text(json.dumps(value,indent=2,default=str)+'\n')
def require(value,message):
    if not value: raise AssertionError(message)
def compare(actual,expected):
    require(len(actual)==len(expected),'Row count mismatch')
    for i,(left,right) in enumerate(zip(actual,expected)):
        require(set(left)==set(right),'Column set mismatch')
        for key,want in right.items():
            got=left[key]
            if got is None or want is None: require(got is None and want is None,'BLANK mismatch: '+key)
            elif key in ('payment_rate','share_all_segments'): require(abs(Decimal(str(got))-Decimal(str(want)))<=Decimal('1e-12'),'Ratio mismatch: '+key)
            else: require(got==want,'Value mismatch: '+key+' row '+str(i))
    return {'rows':len(actual)}
def rejected(fn,phrase=None):
    try: fn()
    except (ValueError,AssertionError,KeyError,FileNotFoundError) as error:
        if phrase: require(phrase.lower() in str(error).lower(),'Wrong rejection: '+str(error))
        return {'rejected':True,'reason':str(error)}
    raise AssertionError('Defect was not caught')
def documentation(case,con):
    _,_,inventory=doc_contract(case)
    require({m['model_id'] for m in inventory['models']}=={'.'.join(r) for r in p.TARGET_RELATIONS},'Documented model inventory differs')
    columns=0
    for model in inventory['models']:
        cursor=con.execute('SELECT * FROM '+model['physical_name']+' LIMIT 0')
        require([c[0].upper() for c in cursor.description]==model['columns'],'Documented column inventory differs')
        columns+=len(model['columns'])
    return {'models':len(inventory['models']),'columns':columns}
def gold(con,expected):
    return p.query(con,'SELECT '+','.join(k.upper() for k in expected[0])+' FROM DMA_POWERBI.GOLD.FCT_INVOICES ORDER BY TENANT_ID,INVOICE_ID')[0]
def load_plan(case):
    plan=json.loads((case/'test-plan.json').read_text())
    for name,digest in plan['frozen_input_hashes'].items(): require(p.sha(case/name)==digest,'Frozen input/oracle changed: '+name)
    require(len(set(plan['required_test_ids']))==len(plan['required_test_ids']),'Duplicate required test id')
    return plan


def negative_cases(case,raw,adjustments,expected,scenario):
    """Each defect has a specified error or independent-result disagreement."""
    def source_model(change,phrase=None):
        with tempfile.TemporaryDirectory(prefix='dma-powerbi-source-') as tmp:
            clone=Path(tmp)/'case';shutil.copytree(case,clone)
            path=clone/'input/repo/Billing.SemanticModel/model.bim';model=json.loads(path.read_text());change(model);write(path,model)
            return rejected(lambda:compare(p.replay_source(clone,inspect_repo(clone/'input/repo'),raw,adjustments)[0]['kpi_totals'],scenario['kpi_totals']),phrase)
    def measure(model,name,text):
        next(m for table in model['model']['tables'] for m in table.get('measures',[]) if m['name']==name)['expression']=text
    def source_text(old,new,phrase=None):
        return source_model(lambda m:m['model']['tables'][0]['partitions'][0]['source'].update(expression=m['model']['tables'][0]['partitions'][0]['source']['expression'].replace(old,new)),phrase)
    def target(change,parameters=None,phrase=None):
        with tempfile.TemporaryDirectory(prefix='dma-powerbi-target-') as tmp:
            clone=Path(tmp)/'case';shutil.copytree(case,clone);change(clone)
            with p.connection(raw,adjustments) as con:
                p.build_models(con,clone/'target/dbt')
                return rejected(lambda:compare(p.OmniSubset(clone/'target/omni').render(con,'kpi_totals',parameters)[0],scenario['kpi_totals']),phrase)
    def yaml_change(clone,name,change):
        path=clone/'target/omni'/name;value=yaml.safe_load(path.read_text());change(value);path.write_text(yaml.safe_dump(value,sort_keys=False))
    def json_change(clone,name,change):
        path=clone/name;value=json.loads(path.read_text());change(value);write(path,value)
    def invalid_raw(change,phrase=None):
        copied=deepcopy(raw);change(copied);return rejected(lambda:p.validate_inputs(copied,adjustments),phrase)
    cases={
      'source-dax-wrong-sum':lambda:source_model(lambda m:measure(m,'Revenue Cents','SUM(Invoices[Paid Cents])'),'mismatch'),
      'source-dax-unsupported-iterator':lambda:source_model(lambda m:measure(m,'Revenue Cents','SUMX(Invoices,Invoices[Net Cents])')),
      'source-dax-calculated-column':lambda:source_model(lambda m:next(c for c in m['model']['tables'][0]['columns'] if c['name']=='Outstanding Cents').update(expression='Invoices[Net Cents] + Invoices[Paid Cents]'),'mismatch'),
      'source-m-adjustment-sign':lambda:source_text('[AMOUNT_CENTS] +','[AMOUNT_CENTS] -','mismatch'),
      'source-m-unsafe-function':lambda:source_text('Date.StartOfMonth','Web.Contents','Unsupported M function'),
      'source-m-wrong-account':lambda:source_text('DMA_POWERBI_SYNTHETIC','WRONG_ACCOUNT','account'),
      'source-m-wrong-catalog':lambda:source_text('DMA_POWERBI.RAW','WRONG_DB.RAW','outside declared'),
      'source-m-missing-query-binding':lambda:source_text('in\n    AddedMonth','in\n    MissingOutput','Unbound M'),
      'source-role-omitted':lambda:source_model(lambda m:m['model'].update(roles=[]),'role'),
      'source-role-cross-tenant':lambda:source_model(lambda m:m['model']['roles'][0]['tablePermissions'][0].update(filterExpression='Invoices[Tenant ID] = "B"'),'role'),
      'source-inactive-relationship':lambda:source_model(lambda m:m['model']['relationships'][0].update(isActive=False),'relationship'),
      'source-bidirectional-relationship':lambda:source_model(lambda m:m['model']['relationships'][0].update(crossFilteringBehavior='bothDirections'),'relationship'),
      'source-many-to-many':lambda:source_model(lambda m:m['model']['relationships'][0].update(toCardinality='many'),'relationship'),
      'source-incomplete-join-key':lambda:source_model(lambda m:m['model']['relationships'][0].update(fromColumn='Customer ID',toColumn='Customer ID'),'relationship'),
      'source-directquery':lambda:source_model(lambda m:m['model']['tables'][0]['partitions'][0].update(mode='directQuery'),'partition'),
      'source-security-filter-removal':lambda:source_model(lambda m:measure(m,'All Segment Revenue Cents','CALCULATE([Revenue Cents],REMOVEFILTERS(Invoices[Tenant ID]))'),'REMOVEFILTERS'),
      'source-selectedvalue-alternate':lambda:source_model(lambda m:measure(m,'Scenario Revenue Cents','[Revenue Cents]*SELECTEDVALUE(Scenario[Multiplier],2)')),
      'target-missing-security':lambda:target(lambda c:yaml_change(c,'billing.topic',lambda v:v.update(access_filters=[])),phrase='security'),
      'target-incomplete-join':lambda:target(lambda c:yaml_change(c,'relationships',lambda v:v[0].update(on_sql='${invoices.customer_key} = ${customers.customer_key}')),phrase='join'),
      'target-wrong-catalog':lambda:target(lambda c:yaml_change(c,'invoices.view',lambda v:v.update(catalog='WRONG_DB')),phrase='namespace'),
      'target-lod-tenant-removal':lambda:target(lambda c:yaml_change(c,'invoices.view',lambda v:v['measures']['all_segment_revenue_cents']['level_of_detail'].update(always_exclude=['invoices.tenant_id'])),phrase='LOD'),
      'target-ratio-inversion':lambda:target(lambda c:yaml_change(c,'invoices.view',lambda v:v['measures']['payment_rate'].update(sql='${invoices.revenue_cents} / NULLIF(${invoices.paid_cents_total}, 0)')),phrase='mismatch'),
      'target-total-policy':lambda:target(lambda c:json_change(c,'target/omni/report-context.json',lambda v:v['reports']['kpi_totals'].update(row_policy='sum_visible_rows')),phrase='total'),
      'target-context-order':lambda:target(lambda c:json_change(c,'target/omni/report-context.json',lambda v:v['reports']['kpi_totals'].update(context_order=[])),phrase='context'),
      'target-presentation-domain':lambda:target(lambda c:json_change(c,'target/omni/report-context.json',lambda v:v['reports']['kpi_totals']['presentation'][0].update(allowed_values=[1,2,3])),phrase='presentation'),
      'raw-null-key':lambda:invalid_raw(lambda r:r['INVOICE_CDC'][0].update(TENANT_ID=None),'required'),
      'raw-conflicting-cdc':lambda:invalid_raw(lambda r:r['INVOICE_CDC'].append(dict(r['INVOICE_CDC'][0],AMOUNT_CENTS=1)),'Conflicting'),
      'raw-history-overlap':lambda:invalid_raw(lambda r:r['CUSTOMER_HISTORY'].append(dict(r['CUSTOMER_HISTORY'][0],VALID_FROM='2025-02-01')),'overlap'),
      'raw-orphan-payment':lambda:invalid_raw(lambda r:[row.update(INVOICE_ID='MISSING') for row in r['PAYMENT_CDC'] if row['TENANT_ID']=='A' and row['PAYMENT_ID']=='P1']),
    }
    # Alternate-result test needs a multi-selection to exercise the alternate.
    def alternate():
        dax=p.DAXSubset([{('Invoices','Net Cents'):10}],{'Revenue Cents':'SUM(Invoices[Net Cents])','Scenario Revenue Cents':'[Revenue Cents]*SELECTEDVALUE(Scenario[Multiplier],2)'},[1,2])
        return rejected(lambda:require(dax.measure('Scenario Revenue Cents',{})==10,'Value mismatch: alternate'),'mismatch')
    cases['source-selectedvalue-alternate']=alternate
    return cases


def run(case,output):
    case=Path(case).resolve();output=Path(output).resolve()
    if output.exists() or output==case or case in output.parents: raise ValueError('Output must be a new directory outside the case')
    output.mkdir(parents=True)
    report={'schema_version':1,'kind':'powerbi_synthetic_e2e','started_at':datetime.now(timezone.utc).isoformat(),'simulation_passed':False,'checks':[],'failures':[],'native_powerbi_execution':'unavailable','native_snowflake_execution':'unavailable','native_omni_execution':'unavailable','native_dbt_compile_execution':'unavailable','production_approved':False,
      'limitations':['Authored PBIP/TMSL/PBIR and bounded M/DAX replay, not a general Power BI compiler or fresh model generation.','Official JSON schema validation is separate from TOM/Desktop/Analysis Services, refresh/folding, role memberships and rendering.','Omni changed-context/empty-result and disconnected selection behavior uses explicit local adapters; native acceptance remains open.']}
    def check(identifier,category,fn,negative=False):
        item={'id':identifier,'category':category,'negative_control':negative}
        try: item['evidence']=fn();item['status']='pass'
        except Exception as error: item['status']='fail';item['error']=type(error).__name__+': '+str(error);report['failures'].append(identifier)
        report['checks'].append(item)
    try:
        plan=load_plan(case);raw,adjustments=p.load_inputs(case);expected=json.loads((case/'expected/expected_rows.json').read_text())['invoices'];scenarios=json.loads((case/'expected/expected_reports.json').read_text())
        graph=inspect_repo(case/'input/repo');write(output/'source-graph.json',graph)
        inventory={'schema_version':1,'origin':'synthetic','source':'powerbi','assets':graph['assets'],'counts':graph['counts'],'projects':graph['projects']};write(output/'inventory.json',inventory)
        check('source-native-inventory','source_contract',lambda:p.validate_graph(graph))
        check('source-official-json-schemas','source_contract',lambda:require(graph['counts']['schema_validated_files']==10,'Official schema file coverage differs') or {'files':10,'native_tom':False})
        catalogue=build_catalogue(case,output/'catalogue',p.sha(output/'inventory.json'));write(output/'catalogue-verification.json',catalogue['verification'])
        check('catalogue-bindings','source_contract',lambda:require(catalogue['verification']['catalogue_context_complete'],'Catalogue incomplete') or catalogue['verification'])
        source=p.SourceReplay(case,graph,raw,adjustments);comparisons=[];traces=[]
        with p.connection(raw,adjustments) as con:
            compiled=p.build_models(con,case/'target/dbt');write(output/'compiled-models.json',compiled)
            check('model-inventory','grain',lambda:require(len(compiled)==6,'Expected six models') or {'models':6})
            actual=gold(con,expected);write(output/'gold-rows.json',actual)
            check('gold-independent-rows','reconciliation',lambda:compare(actual,expected))
            check('complete-model-documentation','logic',lambda:documentation(case,con))
            first,intermediate,source_traces=source.render();write(output/'source-intermediate.json',intermediate)
            check('source-independent-rows','fanout',lambda:compare(intermediate['invoices'],[{k:r[k] for k in intermediate['projection']} for r in expected]))
            check('source-field-coverage','source_contract',lambda:require(len(intermediate['executed_columns'])==20 and len(intermediate['executed_measures'])==9,'Source field coverage differs') or {'columns':20,'measures':9})
            p.build_models(con,case/'target/dbt');check('repeat-build-idempotent','replay',lambda:compare(gold(con,expected),actual))
            assertions=[]
            for path in sorted((case/'target/dbt/tests').glob('*.sql')):
                def assertion(path=path):
                    rows,sql=p.query(con,p.render_dbt(path.read_text()));require(not rows,'dbt assertion violations');assertions.append({'name':path.stem,'sha256':p.sha(path),'sql':sql,'violations':0});return {'violations':0}
                check('dbt-'+path.stem,'history' if 'history' in path.stem else 'grain',assertion)
            write(output/'dbt-assertions.json',assertions)
            omni=p.OmniSubset(case/'target/omni')
            for scenario in scenarios['scenarios']:
                original,_,trace=source.render(scenario['parameters']);traces.append({'scenario':scenario['name'],'source':trace,'target':{}})
                for role,want in scenario['outputs'].items():
                    target,rendered=omni.render(con,role,scenario['parameters']);traces[-1]['target'][role]=rendered
                    for side,got in [('source',original[role]),('target',target)]:
                        check(side+'-'+scenario['name']+'-'+role,'reconciliation',lambda got=got,want=want:compare(got,want))
                    comparisons.append({'scenario':scenario['name'],'report':role,'expected':want,'source':original[role],'target':target})
            for invalid in scenarios['invalid_scenarios']:
                code=invalid['expected_error_code']
                phrase='date window' if code in ('invalid_date','reversed_dates') else 'status' if code=='unknown_status' else 'multiplier' if code=='invalid_multipliers' else 'access denied'
                check('source-denied-'+invalid['name'],'security',lambda invalid=invalid,phrase=phrase:rejected(lambda:source.render(invalid['parameters']),phrase),True)
                check('target-denied-'+invalid['name'],'security',lambda invalid=invalid,phrase=phrase:rejected(lambda:omni.render(con,'kpi_totals',invalid['parameters']),phrase),True)
        write(output/'report-comparisons.json',comparisons);write(output/'rendered-queries.json',traces)
        baseline=scenarios['scenarios'][0]['outputs']
        for name,fn in negative_cases(case,raw,adjustments,expected,baseline).items(): check(name,'negative_controls',fn,True)
        duplicate=deepcopy(raw)
        for table in ('INVOICE_CDC','PAYMENT_CDC','CUSTOMER_HISTORY'): duplicate[table].append(deepcopy(duplicate[table][0]))
        def replay():
            with p.connection(duplicate,adjustments) as con:
                p.build_models(con,case/'target/dbt');compare(gold(con,expected),expected)
            got,_,_=p.replay_source(case,inspect_repo(case/'input/repo'),duplicate,adjustments)
            for role,want in baseline.items():compare(got[role],want)
            return {'source_and_target':'idempotent'}
        check('duplicate-ingestion-idempotent','replay',replay)
        require([c['id'] for c in report['checks']]==plan['required_test_ids'],'Registered test denominator changed')
    except Exception as error: report['failures'].append('runner');report['runner_error']=type(error).__name__+': '+str(error)
    report['completed_at']=datetime.now(timezone.utc).isoformat();report['check_count']=len(report['checks']);report['negative_control_count']=sum(c['negative_control'] for c in report['checks']);report['simulation_passed']=not report['failures']
    report['dependencies']={name:importlib.metadata.version(name) for name in ('duckdb','sqlglot','PyYAML','jsonschema')}
    report['implementation_hashes']={name:p.sha(Path(__file__).parent/name) for name in ('powerbi_source.py','powerbi_execution.py','powerbi_languages.py','powerbi_catalogue.py','run_powerbi_omni_e2e.py')}
    write(output/'e2e-report.json',report);return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case',type=Path,default=Path(__file__).resolve().parent.parent/'examples/powerbi-omni-e2e');parser.add_argument('--output',required=True,type=Path);args=parser.parse_args();report=run(args.case,args.output)
    print(json.dumps({'simulation_passed':report['simulation_passed'],'checks':report['check_count'],'negative_controls':report['negative_control_count'],'failures':report['failures'],'runner_error':report.get('runner_error')},indent=2));return 0 if report['simulation_passed'] else 1
if __name__=='__main__': raise SystemExit(main())
