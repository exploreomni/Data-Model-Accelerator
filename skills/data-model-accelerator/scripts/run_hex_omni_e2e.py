#!/usr/bin/env python3
"""Replay the bundled three-project Hex migration; preserve negative evidence.

This is an offline simulation of authored native-format source/target artifacts,
not fresh model generation per run, native vendor execution or business approval.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile

import yaml
from hex_source import inspect_repo
import hex_execution as h
from verify_model_documentation import verify as verify_documentation


def write_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2,default=str)+'\n')

def compare(actual,expected):
    if len(actual)!=len(expected): raise AssertionError(f'Row count mismatch: {len(actual)} vs {len(expected)}')
    for index,(got,want) in enumerate(zip(actual,expected)):
        if set(got)!=set(want): raise AssertionError(f'Column set mismatch at row {index}: {set(got)^set(want)}')
        for field,value in want.items():
            observed=got[field]
            if field=='payment_rate' and value is not None and observed is not None:
                if abs(Decimal(str(observed))-Decimal(str(value)))>Decimal('0.000000000001'): raise AssertionError('Ratio mismatch')
            elif observed!=value: raise AssertionError(f'Value mismatch row {index}, {field}: {observed} vs {value}')
    return {'row_count':len(actual)}


def gold_rows(con,expected):
    result={}
    for name,table in [('invoices','FCT_INVOICES'),('customer_months','FCT_CUSTOMER_MONTH')]:
        columns=list(expected[name][0]);projection=','.join('INVOICE_MONTH AS month' if c=='month' else c.upper() for c in columns)
        order='TENANT_ID,INVOICE_ID' if name=='invoices' else 'TENANT_ID,CUSTOMER_ID,INVOICE_MONTH'
        frame,_=h.sql_frame(con,'SELECT '+projection+' FROM DMA_HEX.GOLD.'+table+' ORDER BY '+order)
        result[name]=h.rows(frame)
    return result


def doc_contract(case):
    root=Path(case)/'documentation';inventory=json.loads((root/'model-inventory.json').read_text())
    records={'inventory':('model_spec',root/'model-inventory.json'),'dictionary':('data_dictionary',root/'data-dictionary.json'),
             'readable':('data_dictionary',root/'data-dictionary.md'),'erd':('erd',root/'model-erd.md')}
    layers=[]
    for layer in ('bronze','silver','gold'):
        records[layer]=('layer_documentation',root/(layer+'.md'))
        layers.append({'layer':layer,'document_artifact_id':layer,'erd_artifact_id':'erd','model_ids':[m['model_id'] for m in inventory['models'] if m['layer']==layer]})
    package={'model_documentation':{'inventory_artifact_id':'inventory','dictionary_artifact_id':'dictionary','readable_dictionary_artifact_id':'readable','layers':layers}}
    artifacts={k:{'role':v[0]} for k,v in records.items()};paths={k:v[1] for k,v in records.items()}
    errors=verify_documentation(package,artifacts,paths)
    if errors: raise AssertionError('; '.join(errors))
    return package,records,inventory


def validate_documentation(case,con):
    _,_,inventory=doc_contract(case);count=0
    expected_ids={'DMA_HEX.RAW.'+t for t in h.RAW_COLUMNS}|{'DMA_HEX.'+'.'.join(v) for v in h.MODEL_MAP.values()}
    if {m['model_id'] for m in inventory['models']}!=expected_ids: raise AssertionError('Documented model inventory omits built objects')
    for model in inventory['models']:
        cursor=con.execute('SELECT * FROM '+model['physical_name']+' LIMIT 0')
        actual=[c[0].upper() for c in cursor.description]
        if actual!=model['columns']: raise AssertionError('Executed/documented column mismatch: '+model['model_id'])
        count+=len(actual)
    return {'models':len(inventory['models']),'columns':count}


def load_plan(case):
    plan=json.loads((case/'test-plan.json').read_text())
    required_pins={'input/scenario.md','input/raw-data.json','input/repo/adjustments.csv','expected/oracle.py','expected/expected_rows.json','expected/expected_reports.json'}
    if set(plan['frozen_input_hashes'])!=required_pins: raise ValueError('Independent oracle/input pin inventory changed')
    for name,digest in plan['frozen_input_hashes'].items():
        if h.sha(case/name)!=digest: raise ValueError('Frozen independent input changed: '+name)
    if not plan['required_test_ids'] or len(plan['required_test_ids'])!=len(set(plan['required_test_ids'])): raise ValueError('Empty or duplicated required checks')
    return plan


def run(case,output):
    case=Path(case).resolve();output=Path(output).resolve()
    if output==case or case in output.parents or output.exists(): raise ValueError('Output must be a new directory outside the case')
    output.mkdir(parents=True);checks=[];traces=[]
    report={'schema_version':1,'kind':'hex_synthetic_e2e','simulation_passed':False,'started_at':datetime.now(timezone.utc).isoformat(),
        'checks':checks,'native_hex_execution':'unavailable','native_snowflake_execution':'unavailable','native_omni_execution':'unavailable',
        'native_dbt_compile_execution':'unavailable','production_approved':False,'limitations':[
        'Bounded reviewed fixture replay, not a universal Hex/Python/dbt/Omni compiler or arbitrary-code sandbox.',
        'Synthetic warehouse catalogue and input records; no live source outputs or warehouse metadata collected.',
        'Local persona predicate checks do not prove real Hex/warehouse/Omni authorization.',
        'Native chart, app interactions, deployment, incremental ingestion, security and business approval remain unqualified.'],
        'failures':[]}
    def check(identifier,category,fn,negative=False):
        try:
            detail=fn();checks.append({'id':identifier,'category':category,'status':'pass','negative_control':negative,'detail':detail})
        except Exception as error:
            checks.append({'id':identifier,'category':category,'status':'fail','negative_control':negative,'error':type(error).__name__+': '+str(error)})
            report['failures'].append(identifier)
    def require(condition,message):
        if not condition: raise AssertionError(message)
        return True
    def rejected(fn,expected_exception,match):
        try: fn()
        except expected_exception as error:
            if match and match.lower() not in str(error).lower(): raise AssertionError('Wrong failure reason: '+str(error))
            return {'caught':type(error).__name__,'reason':str(error)}
        raise AssertionError('Intended defect was not detected')
    try:
        plan=load_plan(case)
        check('frozen-oracle','source_contract',lambda: {'hashes_verified':len(plan['frozen_input_hashes'])})
        expected=json.loads((case/'expected/expected_rows.json').read_text())
        scenarios=json.loads((case/'expected/expected_reports.json').read_text())
        require([s['scenario_id'] for s in scenarios['scenarios']]==plan['scenario_ids'],'Scenario inventory changed')
        graph=inspect_repo(case/'input/repo');write_json(output/'source-graph.json',graph)
        native_ids=sorted(c['id'] for c in graph['cells'])
        check('native-cell-coverage','source_contract',lambda:require(graph['counts']['errors']==0 and native_ids==plan['native_cell_ids'] and graph['counts']['projects']==3 and graph['counts']['components']==1,'Native source coverage changed'))
        snapshot={'schema_version':1,'kind':'synthetic_hex_source_inventory','origin':'synthetic','files':graph['assets'],'native_cell_ids':native_ids,'native_runtime_validated':False}
        write_json(output/'inventory.json',snapshot)
        raw,adjustments=h.load_inputs(case)
        check('raw-contract','source_contract',lambda:h.validate_inputs(raw,adjustments))
        from hex_catalogue import build_catalogue
        catalogue=build_catalogue(case,output/'catalogue',h.sha(output/'inventory.json'))
        write_json(output/'catalogue-verification.json',catalogue['verification'])
        check('catalogue-bindings','source_contract',lambda:require(catalogue['verification']['catalogue_context_complete'],'Catalogue failed'))
        source_contract=json.loads((case/'input/repo/report-contract.json').read_text())
        target_context=json.loads((case/'target/omni/report-context.json').read_text())
        def context_check():
            require(target_context['defaults']==h.DEFAULTS,'Target defaults changed')
            for item in source_contract['projects']:
                target=target_context['reports'][item['role']]
                require((item['project_id'],item['output_variable'])==(target['source_project_id'],target['source_output_variable']),'Source/target report selection changed')
            return True
        check('report-context','logic',context_check)
        comparisons=[]
        with h.connection(raw,adjustments) as con:
            compiled=h.build_models(con,case/'target/dbt');write_json(output/'compiled-models.json',compiled)
            actual_gold=gold_rows(con,expected);write_json(output/'gold-rows.json',actual_gold)
            for kind in ('invoices','customer_months'):check('gold-'+kind,'grain',lambda kind=kind:compare(actual_gold[kind],expected[kind]))
            check('model-documentation','source_contract',lambda:validate_documentation(case,con))
            compiler=h.OmniSubset(case/'target/omni')
            for scenario in scenarios['scenarios']:
                sid=scenario['scenario_id'];overrides=scenario['parameters']
                source,intermediate,source_trace=h.replay_source(case,graph,raw,adjustments,overrides)
                traces.extend([dict(t,scenario_id=sid) for t in source_trace])
                target={};p=h.parameters(overrides,target_context['defaults'])
                for role in ('revenue','retention','executive'):
                    target[role],query=compiler.report(con,role,p,target_context['reports'][role])
                    traces.append({'scenario_id':sid,'target_role':role,'sql':query})
                    check(sid+'-source-'+role,'reconciliation',lambda role=role:compare(source[role],scenario['outputs'][role]))
                    check(sid+'-target-'+role,'reconciliation',lambda role=role:compare(target[role],scenario['outputs'][role]))
                comparisons.append({'scenario_id':sid,'parameters':overrides,'source':source,'target':target,'expected':scenario['outputs']})
                if sid=='default_a':
                    write_json(output/'source-intermediate.json',intermediate)
                    fields=['tenant_id','invoice_id','customer_id','invoice_date','amount_cents','status','paid_cents','segment','adjustment_cents','net_cents','outstanding_cents']
                    want=[{k:r[k] for k in fields} for r in expected['invoices']]
                    for role in ('revenue','retention','executive'):
                        observed=sorted([{k:r[k] for k in fields} for r in intermediate[role]['enriched']],key=lambda r:(r['tenant_id'],r['invoice_id']))
                        check('intermediate-'+role,'fanout',lambda observed=observed:compare(observed,want))
                    check('metric-conflict-preserved','logic',lambda:require(any(r['invoiced_active_customers']!=r['paying_active_customers'] for r in target['executive']),'Distinct active definitions collapsed'))
            write_json(output/'report-comparisons.json',comparisons)
            for scenario in scenarios['error_scenarios']:
                sid=scenario['scenario_id'];p=scenario['parameters']
                check(sid+'-source','security',lambda p=p:rejected(lambda:h.replay_source(case,graph,raw,adjustments,p),h.HexExecutionError,''),True)
                check(sid+'-target','security',lambda p=p:rejected(lambda:h.parameters(p,target_context['defaults']),h.HexExecutionError,''),True)
            data_test_results=[]
            for test in sorted((case/'target/dbt/tests').glob('*.sql')):
                def execute_test(test=test):
                    query=h.render_dbt(test.read_text());frame,compiled=h.sql_frame(con,query)
                    data_test_results.append({'name':test.stem,'sql':compiled,'rows':h.rows(frame)})
                    require(len(frame)==0,'dbt assertion found invalid rows: '+test.name)
                    return {'rows':0}
                check('dbt-assertion-'+test.stem,'logic',execute_test)
            write_json(output/'dbt-assertions.json',data_test_results)
            # Rebuild after exact replay. No claim of production incremental execution.
            replayed=deepcopy(raw)
            for name in ('INVOICE_CDC','PAYMENT_CDC','CUSTOMER_HISTORY'):replayed[name]=list(reversed(replayed[name]+deepcopy(replayed[name])))
            def replay_check():
                with h.connection(replayed,adjustments) as repeat:
                    h.build_models(repeat,case/'target/dbt');again=gold_rows(repeat,expected)
                    for kind in again:compare(again[kind],expected[kind])
                return {'same_gold_rows':True,'mode':'full rebuild after duplicate/out-of-order input replay'}
            check('replay-rebuild','replay',replay_check)
            def late_check():
                changed=deepcopy(raw)
                old=next(r for r in changed['INVOICE_CDC'] if r['TENANT_ID']=='A' and r['INVOICE_ID']=='I1' and r['SEQUENCE']==2)
                changed['INVOICE_CDC'].append(dict(old,SEQUENCE=3,AMOUNT_CENTS=13000))
                oldpay=next(r for r in changed['PAYMENT_CDC'] if r['TENANT_ID']=='A' and r['PAYMENT_ID']=='P2')
                changed['PAYMENT_CDC'].append(dict(oldpay,SEQUENCE=2,IS_DELETED=True))
                with h.connection(changed,adjustments) as late:
                    h.build_models(late,case/'target/dbt');row=late.execute("SELECT NET_CENTS,PAID_CENTS,OUTSTANDING_CENTS FROM DMA_HEX.GOLD.FCT_INVOICES WHERE TENANT_ID='A' AND INVOICE_ID='I1'").fetchone()
                    require(tuple(row)==(12000,7000,5000),'Late correction/payment deletion failed')
                return {'net_cents':12000,'paid_cents':7000,'outstanding_cents':5000}
            check('late-correction-delete','history',late_check)
            def cancelling_adjustments():
                bad=deepcopy(adjustments);bad[0]['ADJUSTMENT_CENTS']+=1000
                bad.append({'TENANT_ID':'A','INVOICE_ID':'I3','ADJUSTMENT_CENTS':-1000,'REASON':'synthetic_wrong_allocation'})
                altered,_,_=h.replay_source(case,graph,raw,bad)
                baseline=scenarios['scenarios'][0]['outputs']['revenue']
                require(sum(r['net_cents'] for r in altered['revenue'])==sum(r['net_cents'] for r in baseline),'Probe does not preserve grand total')
                return rejected(lambda:compare(altered['revenue'],baseline),AssertionError,'value mismatch')
            check('negative-cancelling-adjustments','negative_controls',cancelling_adjustments,True)
            mutations=[]
            bad=deepcopy(raw);bad['INVOICE_CDC'].append(dict(bad['INVOICE_CDC'][0],AMOUNT_CENTS=1));mutations.append(('cdc-conflict',bad,adjustments,'Conflicting CDC'))
            bad=deepcopy(raw);bad['CUSTOMER_HISTORY'].append(dict(bad['CUSTOMER_HISTORY'][0],SEGMENT='Changed'));mutations.append(('history-overlap',bad,adjustments,'Overlapping'))
            bad=deepcopy(raw);next(r for r in bad['INVOICE_CDC'] if r['TENANT_ID']=='A' and r['INVOICE_ID']=='I9')['CUSTOMER_ID']='Missing';mutations.append(('orphan-customer',bad,adjustments,'unique temporal customer'))
            mutations.append(('duplicate-adjustment',raw,adjustments+[dict(adjustments[0])],'Duplicate manual'))
            mutations.append(('missing-adjustments',raw,None,'Missing raw'))
            for name,bad,adj,message in mutations:
                check('negative-'+name,'negative_controls',lambda bad=bad,adj=adj,message=message:rejected(lambda:h.validate_inputs(bad,adj),h.HexExecutionError,message),True)
            check('negative-python-network','negative_controls',lambda:rejected(lambda:h.PythonSubset({},adjustments).run('import urllib.request'),h.HexExecutionError,'Unsupported Python statement'),True)
            check('negative-python-file','negative_controls',lambda:rejected(lambda:h.PythonSubset({'pd':'reviewed-pandas'},adjustments).run('x = pd.read_csv("/etc/passwd")'),h.HexExecutionError,'External file read denied'),True)
            check('negative-python-tenant-merge','negative_controls',lambda:rejected(lambda:h.PythonSubset({'invoice_base':__import__('pandas').DataFrame(raw['INVOICE_CDC']),'adjustments':__import__('pandas').DataFrame(adjustments)},adjustments).run('x = invoice_base.merge(adjustments, on=["INVOICE_ID"], how="left", validate="many_to_one")'),h.HexExecutionError,'tenant/invoice'),True)
            check('negative-sql-external','negative_controls',lambda:rejected(lambda:h.checked_sql("SELECT * FROM read_csv('/etc/passwd')",h.TARGET_RELATIONS),h.HexExecutionError,'Unsupported SQL construct'),True)
            # Actual target/source expression mutations must execute and fail parity.
            def target_formula():
                with tempfile.TemporaryDirectory(prefix='dma-hex-mutation-') as tmp:
                    target=Path(tmp)/'omni';shutil.copytree(case/'target/omni',target)
                    path=target/'invoices.view';spec=yaml.safe_load(path.read_text());spec['measures']['revenue_cents']['sql']='COALESCE(${raw_net_cents_sum}, 0) + 1';path.write_text(yaml.safe_dump(spec))
                    altered,_=h.OmniSubset(target).report(con,'revenue',h.parameters(),target_context['reports']['revenue'])
                    return rejected(lambda:compare(altered,scenarios['scenarios'][0]['outputs']['revenue']),AssertionError,'value mismatch')
            check('negative-target-formula','negative_controls',target_formula,True)
            def source_formula():
                altered=deepcopy(graph)
                cell=next(c for c in altered['cells'] if c['cell_type']=='CODE' and 'enriched["NET_CENTS"] =' in c['source'])
                cell['source']=cell['source'].replace('enriched["AMOUNT_CENTS"] + enriched["ADJUSTMENT_CENTS"]','enriched["AMOUNT_CENTS"] - enriched["ADJUSTMENT_CENTS"]')
                actual,_,_=h.replay_source(case,altered,raw,adjustments)
                return rejected(lambda:compare(actual['revenue'],scenarios['scenarios'][0]['outputs']['revenue']),AssertionError,'value mismatch')
            check('negative-source-formula','negative_controls',source_formula,True)
            def source_tenant():
                altered=deepcopy(graph)
                cell=next(c for c in altered['cells'] if c['cell_type']=='SQL' and 'DMA_HEX.RAW.INVOICE_CDC' in c['source'])
                cell['source']=cell['source'].replace('i.TENANT_ID = p.TENANT_ID AND ','')
                actual,_,_=h.replay_source(case,altered,raw,adjustments)
                return rejected(lambda:compare(actual['revenue'],scenarios['scenarios'][0]['outputs']['revenue']),AssertionError,'mismatch')
            check('negative-source-tenant-join','negative_controls',source_tenant,True)
            def target_access():
                with tempfile.TemporaryDirectory(prefix='dma-hex-access-') as tmp:
                    target=Path(tmp)/'omni';shutil.copytree(case/'target/omni',target)
                    path=target/'billing.topic';spec=yaml.safe_load(path.read_text());spec.pop('access_filters');path.write_text(yaml.safe_dump(spec))
                    return rejected(lambda:h.OmniSubset(target),h.HexExecutionError,'tenant access')
            check('negative-target-access','negative_controls',target_access,True)
        write_json(output/'rendered-queries.json',traces)
        actual_ids=[c['id'] for c in checks]
        require(len(actual_ids)==len(set(actual_ids)) and set(actual_ids)==set(plan['required_test_ids']),'Required test coverage mismatch: '+str(set(actual_ids)^set(plan['required_test_ids'])))
        report['counts']={'checks':len(checks),'passed':sum(c['status']=='pass' for c in checks),'negative_controls':sum(c['negative_control'] for c in checks),'projects':3,'cells':len(native_ids),'report_scenarios':len(scenarios['scenarios'])}
        report['simulation_passed']=all(c['status']=='pass' for c in checks)
    except Exception as error:
        report['fatal_error']=type(error).__name__+': '+str(error)
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        report['case_hashes']={str(p.relative_to(case)):h.sha(p) for p in sorted(case.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        scripts=Path(__file__).parent
        report['implementation_hashes']={name:h.sha(scripts/name) for name in ['hex_source.py','hex_execution.py','hex_catalogue.py','run_hex_omni_e2e.py','requirements-hex-e2e.txt','requirements-e2e.txt','verify_catalogue.py','verify_model_documentation.py'] if (scripts/name).exists()}
        report['dependencies']={name:importlib.metadata.version(name) for name in ('duckdb','sqlglot','pandas','numpy','PyYAML','jsonschema')}
        write_json(output/'e2e-report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--case',type=Path,default=Path(__file__).resolve().parents[1]/'examples/hex-omni-e2e');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try: result=run(args.case,args.output)
    except Exception as error: print(json.dumps({'simulation_passed':False,'error':str(error)}));return 1
    print(json.dumps({'simulation_passed':result['simulation_passed'],'counts':result.get('counts'),'failures':result['failures'],'fatal_error':result.get('fatal_error'),'report':str(args.output/'e2e-report.json')}))
    return 0 if result['simulation_passed'] else 1
if __name__=='__main__':sys.exit(main())
