#!/usr/bin/env python3
"""Replay the authored Tableau/dbt/Omni fixture; never execute native source code."""
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile
import yaml

import tableau_execution as t
from tableau_source import inspect_repo, inspect_package
from run_hex_omni_e2e import doc_contract


def write(path,value): Path(path).write_text(json.dumps(value,indent=2,default=str)+'\n')
def require(value,message):
    if not value: raise AssertionError(message)

def compare(got,want):
    require(len(got)==len(want),'Row count mismatch')
    for index,(actual,expected) in enumerate(zip(got,want)):
        require(set(actual)==set(expected),'Column set mismatch')
        for key,val in expected.items():
            observed=actual[key]
            if val is None or observed is None: require(val is None and observed is None,'Null mismatch: '+key)
            elif key in ('payment_rate','share_of_month','scenario_revenue_cents'):
                delta=abs(Decimal(str(val))-Decimal(str(observed)))
                require(delta <= (Decimal('1e-12') if key!='scenario_revenue_cents' else 0),'Value mismatch: '+key)
            else: require(observed==val,'Value mismatch: '+key+' row '+str(index))
    return {'rows':len(got)}

def rejected(fn,phrase=None):
    try: fn()
    except (ValueError,AssertionError,KeyError,FileNotFoundError) as e:
        if phrase and phrase.lower() not in str(e).lower(): raise AssertionError('Wrong rejection: '+str(e))
        return {'rejected':True,'reason':str(e)}
    raise AssertionError('Defect was not caught')

def load_plan(case):
    plan=json.loads((case/'test-plan.json').read_text())
    for name,digest in plan['frozen_input_hashes'].items(): require(t.sha(case/name)==digest,'Frozen input/oracle changed: '+name)
    require(plan['required_test_ids'] and len(plan['required_test_ids'])==len(set(plan['required_test_ids'])),'Invalid test denominator')
    return plan

def documentation(case,con):
    _,_,inventory=doc_contract(case)
    require({m['model_id'] for m in inventory['models']}=={'.'.join(x) for x in t.TARGET_RELATIONS},'Documented model inventory differs from built objects')
    columns=0
    for model in inventory['models']:
        cursor=con.execute('SELECT * FROM '+model['physical_name']+' LIMIT 0')
        require([c[0].upper() for c in cursor.description]==model['columns'],'Documented columns differ: '+model['model_id'])
        columns+=len(model['columns'])
    return {'models':len(inventory['models']),'columns':columns}

def gold(con,expected):
    keys=list(expected[0]);rows,_=t.query(con,'SELECT '+','.join(k.upper() for k in keys)+' FROM DMA_TABLEAU.GOLD.FCT_INVOICES ORDER BY TENANT_ID,INVOICE_ID')
    return rows


def run(case,output):
    case=Path(case).resolve();output=Path(output).resolve()
    if output.exists() or output==case or case in output.parents: raise ValueError('Output must be a new directory outside the case')
    output.mkdir(parents=True)
    report={'schema_version':1,'kind':'tableau_synthetic_e2e','started_at':datetime.now(timezone.utc).isoformat(),'simulation_passed':False,'checks':[],'failures':[],
        'native_tableau_execution':'unavailable','native_snowflake_execution':'unavailable','native_omni_execution':'unavailable','native_dbt_compile_execution':'unavailable','production_approved':False,
        'limitations':['Authored synthetic XML/artifacts and bounded replay, not a universal Tableau compiler or fresh model generation.','Source/target calculations and catalogue are local; no Tableau/Snowflake/Omni runtime, server permissions, extracts or customer output captured.','Presentation companion is explicitly local metadata, not a native Omni workbook export.']}
    def check(identifier,category,fn,negative=False):
        item={'id':identifier,'category':category,'negative_control':negative}
        try: item['evidence']=fn();item['status']='pass'
        except Exception as error:
            item['status']='fail';item['error']=type(error).__name__+': '+str(error);report['failures'].append(identifier)
        report['checks'].append(item)
    try:
        plan=load_plan(case);raw,adjustments=t.load_inputs(case)
        expected=json.loads((case/'expected/expected_rows.json').read_text())['invoices']
        scenarios=json.loads((case/'expected/expected_reports.json').read_text())
        graph=inspect_repo(case/'input/repo');write(output/'source-graph.json',graph)
        inventory={'schema_version':1,'origin':'synthetic','source':'tableau','assets':graph['assets'],'workbooks':graph['workbooks'],'worksheets':graph['worksheets']}
        write(output/'inventory.json',inventory)
        check('source-static-graph','source_contract',lambda:require(graph['counts']['errors']==0,'Static Tableau gaps') or graph['counts'])
        check('source-native-inventory','source_contract',lambda:t.validate_graph(graph))
        check('source-package','source_contract',lambda:package_check(case))
        from tableau_catalogue import build_catalogue
        catalogue=build_catalogue(case,output/'catalogue',t.sha(output/'inventory.json'))
        check('catalogue-bindings','source_contract',lambda:require(catalogue['verification']['catalogue_context_complete'],'Catalogue incomplete') or catalogue['verification'])
        write(output/'catalogue-verification.json',catalogue['verification'])
        comparisons=[];traces=[]
        with t.connection(raw,adjustments) as con:
            compiled=t.build_models(con,case/'target/dbt');write(output/'compiled-models.json',compiled)
            check('model-inventory','grain',lambda:require(len(compiled)==6,'Expected six models') or {'models':len(compiled)})
            actual=gold(con,expected);write(output/'gold-rows.json',actual)
            check('gold-independent-rows','reconciliation',lambda:compare(actual,expected))
            check('complete-model-documentation','logic',lambda:documentation(case,con))
            source,intermediate,source_traces=t.replay_source(case,graph,raw,adjustments)
            write(output/'source-intermediate.json',intermediate)
            projection=[{k:r[k] for k in intermediate['projection']} for r in expected]
            check('source-independent-rows','fanout',lambda:compare(intermediate['invoices'],projection))
            check('source-field-coverage','source_contract',lambda:require(set(intermediate['executed_field_ids'])==set(plan['required_field_ids']),'Source field evaluation coverage differs') or {'fields':len(intermediate['executed_field_ids'])})
            baseline=deepcopy(actual);t.build_models(con,case/'target/dbt')
            check('repeat-build-idempotent','replay',lambda:compare(gold(con,expected),baseline))
            assertions=[]
            for path in sorted((case/'target/dbt/tests').glob('*.sql')):
                def assertion(path=path):
                    rows,sql=t.query(con,t.render_dbt(path.read_text()));require(not rows,'dbt SQL assertion returned violations');assertions.append({'name':path.stem,'sha256':t.sha(path),'sql':sql,'violations':len(rows)})
                    return {'violations':len(rows)}
                check('dbt-'+path.stem,'history' if path.stem in ('invoice_history_exactly_one','source_history_overlap') else 'grain',assertion)
            write(output/'dbt-assertions.json',assertions)
            omni=t.OmniSubset(case/'target/omni')
            for scenario in scenarios['scenarios']:
                role_outputs,_,source_sql=t.replay_source(case,graph,raw,adjustments,scenario['parameters'])
                traces.append({'scenario':scenario['scenario_id'],'source':source_sql,'target':{}})
                for role,want in scenario['outputs'].items():
                    source_rows=role_outputs[role];target_rows,target_sql=omni.report(con,role,scenario['parameters'])
                    check('source-'+scenario['scenario_id']+'-'+role,'logic',lambda g=source_rows,w=want:compare(g,w))
                    check('target-'+scenario['scenario_id']+'-'+role,'logic',lambda g=target_rows,w=want:compare(g,w))
                    comparisons.append({'scenario':scenario['scenario_id'],'role':role,'source':source_rows,'target':target_rows,'expected':want})
                    traces[-1]['target'][role]=target_sql
            for scenario in scenarios['error_scenarios']:
                sid=scenario['scenario_id'];params=scenario['parameters']
                check('source-deny-'+sid,'security',lambda p=params:rejected(lambda:t.replay_source(case,graph,raw,adjustments,p)),True)
                check('target-deny-'+sid,'security',lambda p=params:rejected(lambda:omni.report(con,'revenue_trend',p)),True)
            mutations(case,con,graph,raw,adjustments,scenarios,expected,check)
        write(output/'report-comparisons.json',comparisons);write(output/'rendered-queries.json',traces)
        ids=[c['id'] for c in report['checks']]
        require(len(ids)==len(set(ids)) and set(ids)==set(plan['required_test_ids']),'Required check coverage mismatch: '+str(set(ids)^set(plan['required_test_ids'])))
        report['counts']={'checks':len(ids),'passed':sum(c['status']=='pass' for c in report['checks']),'negative_controls':sum(c['negative_control'] for c in report['checks']),
            'worksheets':len(graph['worksheets']),'valid_scenarios':len(scenarios['scenarios']),'report_comparisons':len(comparisons)*2}
        report['simulation_passed']=not report['failures']
    except Exception as error: report['fatal_error']=type(error).__name__+': '+str(error)
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        report['case_hashes']={str(p.relative_to(case)):t.sha(p) for p in sorted(case.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        scripts=Path(__file__).parent
        report['implementation_hashes']={name:t.sha(scripts/name) for name in ['tableau_source.py','tableau_execution.py','tableau_catalogue.py','run_tableau_omni_e2e.py','requirements-tableau-e2e.txt','hex_execution.py','hex_catalogue.py','run_hex_omni_e2e.py','verify_catalogue.py','verify_model_documentation.py']}
        report['dependencies']={name:importlib.metadata.version(name) for name in ('duckdb','sqlglot','pandas','PyYAML','lxml')}
        write(output/'e2e-report.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',type=Path,default=Path(__file__).resolve().parents[1]/'examples/tableau-omni-e2e');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    try: report=run(a.case,a.output)
    except Exception as error: print(json.dumps({'simulation_passed':False,'error':str(error)}));return 1
    print(json.dumps({k:report.get(k) for k in ('simulation_passed','counts','failures','fatal_error')}))
    return 0 if report['simulation_passed'] else 1


def package_check(case):
    result=inspect_package(case/'input/packages/billing.twbx',case/'input/repo')
    require(result['safe'] and result['matches_repo'],'Packaged workbook differs or is unsafe')
    return result


def mutations(case,con,graph,raw,adjustments,scenarios,expected,check):
    examples={s['scenario_id']:s for s in scenarios['scenarios']}
    default=scenarios['scenarios'][0]
    def altered_source(name,change,scenario=default,role='revenue_trend'):
        changed=deepcopy(graph);change(changed)
        check('negative-source-'+name,'negative_controls',lambda:rejected(lambda:compare(t.replay_source(case,changed,raw,adjustments,scenario['parameters'])[0][role],scenario['outputs'][role])),True)
    def field(g,name): return next(f for f in g['datasources'][0]['fields'] if f['name']==name)
    altered_source('net-sign',lambda g:field(g,'[Net Cents]').update(formula='[Amount Cents] - ZN([Adjustment Cents])'))
    altered_source('payment-tenant',lambda g:g['datasources'][0].update(custom_sql=g['datasources'][0]['custom_sql'].replace('i.TENANT_ID = p.TENANT_ID AND ','')))
    january=next(s for s in scenarios['scenarios'] if s['parameters'].get('end_date')=='2026-02-01' and not s['parameters'].get('segment'))
    segment=next(s for s in scenarios['scenarios'] if s['parameters'].get('segment')=='SMB' and not s['parameters'].get('start_date'))
    def date_order(g):
        sheet=next(s for s in g['worksheets'] if s['name']=='Customer Value')
        next(f for f in sheet['filters'] if f['field_name']=='[Date Window]').update(stage='dimension',context=False)
    altered_source('context-order',date_order,january,'customer_value')
    def segment_order(g):
        sheet=next(s for s in g['worksheets'] if s['name']=='Customer Value')
        next(f for f in sheet['filters'] if f['field_name']=='[Segment Selection]').update(stage='context',context=True)
    altered_source('segment-promoted',segment_order,segment,'customer_value')
    altered_source('fixed-scope',lambda g:field(g,'[Fixed Customer Net]').update(formula='{ FIXED [Tenant ID] : SUM([Net Cents]) }'),default,'customer_value')
    def partition(g):
        calc=next(s for s in g['worksheets'] if s['name']=='Revenue Share')['table_calculations'][0]
        calc.update(addressing=['[Invoice Month]'],partitioning=['[Segment]'])
    altered_source('partition',partition,default,'revenue_share')
    altered_source('population-filter',lambda g:g['datasources'][0].update(filters=[f for f in g['datasources'][0]['filters'] if f['field_name']!='[Posted Population]']))
    altered_source('parameter-drift',lambda g:g['parameters'][0].update(default='B'))
    altered_source('worksheet-omitted',lambda g:g['worksheets'].pop())
    altered_source('field-omitted',lambda g:g['datasources'][0].update(fields=[f for f in g['datasources'][0]['fields'] if f['name']!='[Net Cents]']))
    altered_source('unsafe-function',lambda g:field(g,'[Net Cents]').update(formula='SCRIPT_REAL("external", [Amount Cents])'))
    def bad_xml():
        with tempfile.TemporaryDirectory(prefix='dma-tableau-xml-') as d:
            root=Path(d);(root/'bad.twb').write_text('<!DOCTYPE workbook [<!ENTITY x SYSTEM "file:///private/tmp/never-read">]><workbook>&x;</workbook>')
            result=inspect_repo(root);require(result['counts']['errors']>0,'DOCTYPE not rejected')
            return {'errors':result['gaps']}
    check('negative-xml-doctype','security',bad_xml,True)
    def bad_zip():
        with tempfile.TemporaryDirectory(prefix='dma-tableau-zip-') as d:
            path=Path(d)/'bad.twbx'
            with zipfile.ZipFile(path,'w') as z: z.writestr('../escape.twb','<workbook/>')
            result=inspect_package(path);require(not result['safe'],'Archive traversal not rejected');return result
    check('negative-zip-traversal','security',bad_zip,True)
    def mirror():
        with tempfile.TemporaryDirectory(prefix='dma-tableau-mirror-') as d:
            repo=Path(d)/'repo';shutil.copytree(case/'input/repo',repo)
            path=repo/'billing.tds';path.write_text(path.read_text().replace('[Amount Cents] + ZN','[Amount Cents] - ZN'))
            result=inspect_repo(repo);require(result['counts']['errors']>0,'Datasource mirror drift not rejected');return {'gaps':result['gaps']}
    check('negative-tds-mirror','source_contract',mirror,True)
    def raw_error(name,change):
        r=deepcopy(raw);a=deepcopy(adjustments);change(r,a)
        check('negative-'+name,'negative_controls',lambda:rejected(lambda:t.validate_inputs(r,a)),True)
    raw_error('conflicting-cdc',lambda r,a:r['INVOICE_CDC'].append(dict(r['INVOICE_CDC'][0],AMOUNT_CENTS=r['INVOICE_CDC'][0]['AMOUNT_CENTS']+1)))
    raw_error('duplicate-adjustments',lambda r,a:a.append(deepcopy(a[0])))
    raw_error('orphan-payment',lambda r,a:r['PAYMENT_CDC'].append(dict(r['PAYMENT_CDC'][0],PAYMENT_ID='new_orphan',INVOICE_ID='never_present')))
    raw_error('overlap-history',lambda r,a:r['CUSTOMER_HISTORY'].append(dict(r['CUSTOMER_HISTORY'][0],VALID_FROM='2026-01-02')))
    raw_error('null-key',lambda r,a:r['INVOICE_CDC'][0].update(TENANT_ID=None))
    def missing_csv():
        with tempfile.TemporaryDirectory(prefix='dma-tableau-input-') as d:
            tmp=Path(d);(tmp/'input/repo').mkdir(parents=True);shutil.copyfile(case/'input/raw-data.json',tmp/'input/raw-data.json')
            return rejected(lambda:t.load_inputs(tmp))
    check('negative-missing-csv','source_contract',missing_csv,True)
    def target_change(name,change,role='customer_value',scenario=segment):
        def test():
            with tempfile.TemporaryDirectory(prefix='dma-tableau-omni-') as d:
                target=Path(d)/'omni';shutil.copytree(case/'target/omni',target);change(target)
                return rejected(lambda:compare(t.OmniSubset(target).report(con,role,scenario['parameters'])[0],scenario['outputs'][role]))
        check('negative-target-'+name,'negative_controls',test,True)
    def edit_yaml(folder,name,change):
        path=folder/name;data=yaml.safe_load(path.read_text());change(data);path.write_text(yaml.safe_dump(data))
    target_change('lod-filter',lambda p:edit_yaml(p,'invoices.view',lambda v:v['dimensions']['fixed_customer_revenue_cents']['level_of_detail'].pop('filters')))
    target_change('lod-blanket-cancel',lambda p:edit_yaml(p,'invoices.view',lambda v:v['dimensions']['fixed_customer_revenue_cents']['level_of_detail'].update(cancel_query_filters=True)))
    target_change('access',lambda p:edit_yaml(p,'billing.topic',lambda v:v.pop('access_filters')))
    target_change('join-fanout',lambda p:edit_yaml(p,'relationships',lambda v:v[0].update(on_sql='${invoices.customer_id} = ${customers.customer_id}')),'revenue_trend',default)
    def edit_context(p,change):
        path=p/'report-context.json';v=json.loads(path.read_text());change(v);write(path,v)
    target_change('context-order',lambda p:edit_context(p,lambda v:v['reports']['customer_value'].update(context_order=['segment_dimension','fixed_lod'])) )
    target_change('partition',lambda p:edit_context(p,lambda v:v['reports']['revenue_share']['presentation'][0].update(partition_by=[],address_by=['month','segment'])),'revenue_share',default)
    def model_change():
        with tempfile.TemporaryDirectory(prefix='dma-tableau-model-') as d:
            target=Path(d)/'dbt';shutil.copytree(case/'target/dbt',target)
            path=target/'models/gold/fct_invoices.sql';text=path.read_text();changed=text.replace('i.AMOUNT_CENTS + COALESCE(a.ADJUSTMENT_CENTS, 0)','i.AMOUNT_CENTS - COALESCE(a.ADJUSTMENT_CENTS, 0)')
            require(changed!=text,'Model mutation did not apply');path.write_text(changed)
            with t.connection(raw,adjustments) as local:
                t.build_models(local,target);return rejected(lambda:compare(gold(local,expected),expected),'Value mismatch')
    check('negative-target-model-sign','negative_controls',model_change,True)
    def dictionary_gap():
        with tempfile.TemporaryDirectory(prefix='dma-tableau-docs-') as d:
            tmp=Path(d);shutil.copytree(case/'documentation',tmp/'documentation')
            path=tmp/'documentation/data-dictionary.json';v=json.loads(path.read_text());v['models'][0]['columns'].pop();write(path,v)
            return rejected(lambda:doc_contract(tmp))
    check('negative-dictionary-coverage','logic',dictionary_gap,True)
    def replay_duplicates():
        r=deepcopy(raw);r['INVOICE_CDC']+=deepcopy(r['INVOICE_CDC']);r['PAYMENT_CDC']+=deepcopy(r['PAYMENT_CDC']);r['CUSTOMER_HISTORY']+=deepcopy(r['CUSTOMER_HISTORY'])
        with t.connection(r,adjustments) as local:
            t.build_models(local,case/'target/dbt');return compare(gold(local,expected),expected)
    check('exact-duplicate-replay','replay',replay_duplicates)

if __name__=='__main__':sys.exit(main())
