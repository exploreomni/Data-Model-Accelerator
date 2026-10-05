#!/usr/bin/env python3
"""Exercise the guided UX across target routes using explicitly synthetic inputs.

Writes a new output directory only. No cloud calls, input execution or dependency
installation. Generated illustrative SQL is not compiled or warehouse validated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import copy

from platform_matrix import FRAMEWORKS, WAREHOUSES
from guided_workflow import start_engagement, resume_engagement, record_handoff
from delivery_portal import context_fingerprint, source_fingerprint, model_svg, package_delivery, verify_delivery, render_engagement


def synthetic_disclosure(artifacts, audience):
    """Fixture declarations only, never use for customer content or approval."""
    from privacy_contract import default_policy, new_classification
    evidence = [{'reference': 'synthetic-ux-fixture', 'sha256': 'a' * 64}]
    policy = default_policy()
    policy.update(review_status='approved', review_reference='synthetic-ux-fixture', evidence=evidence)
    policy['destinations']['share'] = {'allowed_sensitivities': ['PUBLIC'], 'allowed_categories': []}
    item = new_classification('PUBLIC')
    item.update(categories_known=True, review_status='approved', review_reference='synthetic-ux-fixture',
                evidence=evidence, lineage={'status':'complete','upstream_ids':[],'transformation':'source'})
    item['handling']['share'] = 'allow'
    return {'audience': audience, 'policy': policy, 'presentation': copy.deepcopy(item),
            'artifacts': {a['id']: copy.deepcopy(item) for a in artifacts}}


def run(output):
    output=Path(output).absolute()
    output.mkdir(parents=True,exist_ok=False)
    source=output/'synthetic-source';source.mkdir()
    (source/'dbt_project.yml').write_text('name: synthetic_sales\nversion: "1.0"\nconfig-version: 2\nmodel-paths: [models]\n')
    (source/'models').mkdir()
    (source/'models'/'legacy_report.sql').write_text('-- Synthetic source; never executed by the UX exercise.\nselect order_id, customer_id, order_date, amount from raw.orders\n')
    catalogue=output/'synthetic-catalogue.json'
    catalogue.write_text(json.dumps({'kind':'synthetic_catalogue_context','origin':'synthetic_fixture','objects':[
        {'name':'raw.orders','columns':['order_id','customer_id','order_date','amount']},
        {'name':'raw.customers','columns':['customer_id','customer_name']}]}))
    answers={'engagement_type':'refactor','priority_domain':'Synthetic sales','framework':'dbt','warehouse':'bigquery',
        'semantic_target':'omni','migration_scope':'model_semantic','input_handling':'pre_sanitized',
        'deliverables':['documentation','diagrams','dictionary','implementation','validation'],
        'trusted_outputs':['synthetic-legacy-sales'],'retained_behavior':['Order grain and recorded amount; customer joins must not duplicate orders'],
        'corrected_behavior':[],'host':'local synthetic exercise','execution_mode':'assessment_only'}
    results=[]
    for framework in FRAMEWORKS:
        for warehouse in WAREHOUSES:
            selections=dict(answers,framework=framework,warehouse=warehouse)
            state=start_engagement(source,output/(framework+'-'+warehouse),selections,catalogue=catalogue)
            render_engagement(state,output/(framework+'-'+warehouse)/'START_HERE.html')
            results.append({'framework':framework,'warehouse':warehouse,'state':state['status'],
                'assessment':state['readiness']['platform']['capabilities']['assessment']['status'],
                'generation':state['readiness']['platform']['capabilities']['generation']['status'],
                'execution':state['readiness']['platform']['capabilities']['execution']['status'],
                'execution_performed':False})
    run_dir=output/'dbt-bigquery'
    state=resume_engagement(run_dir)
    artifact_root=output/'synthetic-artifacts';artifact_root.mkdir()
    models=[]
    for layer in ('bronze','silver','gold'):
        for entity in ('orders','customers'):
            models.append({'id':layer+'.'+entity,'name':layer+'.'+entity,'layer':layer,'domain':'sales',
                'grain':'One row per '+('order' if entity=='orders' else 'customer'),
                'columns':[{'name':('order_id' if entity=='orders' else 'customer_id'),'type':'INT64','key':'PK','description':'Synthetic stable identity'},
                           {'name':('customer_id' if entity=='orders' else 'customer_name'),'type':('INT64' if entity=='orders' else 'STRING'),
                            'key':('FK' if entity=='orders' else ''),'description':'Declared customer attribution; validation pending'}]})
    next(m for m in models if m['id']=='gold.orders')['artifact_id']='model-code'
    relationships=[]
    for entity in ('orders','customers'):
        for a,b in (('bronze','silver'),('silver','gold')):
            relationships.append({'from':a+'.'+entity,'to':b+'.'+entity,'kind':'lineage','label':'Preserve identity; proposed projection','evidence':'Synthetic model specification'})
    relationships.append({'from':'gold.orders','to':'gold.customers','kind':'relationship',
                          'label':'Order customer attribution', 'predicate':'orders.customer_id = customers.customer_id',
                          'cardinality':'many:0..1', 'role':'customer', 'status':'proposed',
                          'evidence':'Proposed key; uniqueness/fanout must be validated'})
    changes=[{'id':'sales-grain','source':'models/legacy_report.sql','target':'models/gold/orders.sql','disposition':'split',
              'rationale':'Separate source cleanup from reusable order and customer models; keep interactive metrics downstream.',
              'consumers':['synthetic-legacy-sales','proposed Omni sales topic'],'decision':'Proposed; synthetic demonstration only'}]
    artifacts=[]
    def add(aid,path,body,category,audiences,requires=None):
        target=artifact_root/path;target.parent.mkdir(parents=True,exist_ok=True)
        body=body.encode() if isinstance(body,str) else body;target.write_bytes(body)
        artifacts.append({'id':aid,'path':path,'sha256':hashlib.sha256(body).hexdigest(),'category':category,
                          'audiences':audiences,'requires':requires or [],'description':'Synthetic UX example; no target execution.'})
    for layer in ('bronze','silver','gold'):
        add(layer+'-guide','docs/'+layer+'.md','# '+layer.title()+' — synthetic model\n\nOrders and customers retain their source identities.\n\nGrain, keys and lineage appear in the model inventory. Runtime types, refresh/history, access policies and recovery are not qualified in this UX exercise. Existing project conventions must be retained in a real refactor.\n', 'documentation',['reviewer','engineer'])
    add('run-guide','docs/implementation.md','# Synthetic implementation example\n\nThe included dbt SQL illustrates ref/source placement. It is not a complete deployable project: raw source declarations, actual models, adapter/profile, environment and benchmarks must come from the real engagement. Do not paste dbt Jinja into a SQL editor. No scripts were executed.\n','documentation',['engineer'])
    add('dictionary','docs/dictionary.json',json.dumps({'origin':'synthetic','models':models},indent=2),'dictionary',['reviewer','engineer'])
    add('diagram','docs/model.svg',model_svg(models,relationships),'diagrams',['reviewer','engineer'])
    add('model-code','models/gold/orders.sql',"-- Illustrative dbt model, not a qualified project.\nselect order_id, customer_id, order_date, amount\nfrom {{ ref('silver_orders') }}\n",'implementation',['engineer'],['run-guide'])
    add('validation-guide','validation/remaining-checks.md','# Validation remains open\n\nSynthetic review content only. Capture independent source results, validate catalogue bindings, test identity/fanout/security and run the authorized target build before claiming accuracy. No native warehouse or Coalesce execution was performed.\n','validation',['reviewer','engineer'])
    review={'schema_version':1,'title':'Sales model · guided review','description':'Synthetic walkthrough of the shared workflow. This is a UX example, not customer or warehouse acceptance.',
            'source_fingerprint':source_fingerprint(state),'context_sha256':context_fingerprint(state),
            'target':{'framework':'dbt','warehouse':'bigquery'},'models':models,'relationships':relationships,'changes':changes,
            'decisions':[{'id':'refund-definition','question':'Should refunded orders retain the original amount or report net revenue?','status':'unresolved',
                          'answer':'Synthetic question: preserve both source behavior and the proposed definition until the business owner decides.'}],
            'validation':[{'id':'order-grain','label':'One row per order','scope':'warehouse','status':'pending','expected':'Unique order_id','actual':None,'details':'No warehouse execution in this UX exercise.'},
                          {'id':'customer-fanout','label':'Customer join preserves the order population','scope':'warehouse','status':'pending','expected':'No added or missing order IDs','actual':None,'details':'Independent row comparison required.'},
                          {'id':'metric-parity','label':'Agreed revenue definition','scope':'semantic','status':'pending','expected':'Accepted filter/currency/history context','actual':None,'details':'Business definition remains unresolved.'}],
            'artifacts':artifacts}
    review['disclosure'] = synthetic_disclosure(artifacts, 'engineer')
    (output/'review-content.json').write_text(json.dumps(review,indent=2))
    state=record_handoff(run_dir,output/'review-content.json',artifact_root,audience='engineer')
    state=resume_engagement(run_dir)
    if state['status']!='handoff_prepared' or state['readiness']['execution_authorized']:
        raise ValueError('Prepared handoff must survive resume without execution authority')
    render_engagement(state,output/'REVIEW.html',review)
    package_checks=[]
    for audience in ('engineer','reviewer'):
        review['disclosure'] = synthetic_disclosure(artifacts, audience)
        path=output/(audience+'-example.zip')
        package_delivery(state,review,artifact_root,path,audience=audience)
        package_checks.append(dict(audience=audience,**verify_delivery(path)))
        destination=output/(audience+'-preview');destination.mkdir()
        # Extract only our own freshly generated, verified archive for local preview.
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
    # A fresh operator sees unanswered questions, not inherited synthetic decisions.
    blank=start_engagement(source,output/'new-engagement')
    render_engagement(blank,output/'new-engagement'/'START_HERE.html')
    result={'kind':'synthetic_guided_delivery_exercise','platform_routes':results,'packages':package_checks,
            'handoff_state':state['status'],'handoff_assurance':state['delivery']['assurance'],
            'native_execution_performed':False,'model_accuracy_tested':False,'preview':'engineer-preview/START_HERE.html'}
    (output/'exercise-results.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.output),indent=2))


if __name__=='__main__':main()
