"""Build a clean, explicitly synthetic five-table review package. No code execution or native qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from delivery_portal import package_delivery, verify_delivery, context_fingerprint, source_fingerprint
from run_guided_delivery_demo import synthetic_disclosure


def run(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    # Work files are separate from the only customer-facing handoff and archive.
    work = destination / 'technical-evidence'
    work.mkdir()
    artifacts = []
    def add(identifier, path, body, category='implementation', audiences=None, requires=None):
        file = work / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(body)
        artifacts.append({'id': identifier, 'path': path, 'category': category,
                          'audiences': audiences or ['engineer'], 'requires': requires or [],
                          'description': 'Synthetic review fixture; not natively executed.',
                          'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    state = {'schema_version': 1, 'engagement_id': 'synthetic-commerce-review', 'revision': 1,
             'status': 'generation', 'answers': {'engagement_type': 'new_model', 'framework': 'dbt',
              'warehouse': 'snowflake', 'semantic_target': 'retain_existing', 'migration_scope': 'model_only'},
             'inputs': {'source': {'fingerprint': {'algorithm': 'sha256', 'value': 'f'*64, 'scope': 'synthetic fixture', 'complete': True}},
                        'catalogue': {'sha256': 'c'*64}}, 'readiness': {'platform': {}},
             'next_actions': [{'title': 'Review the model and return corrections', 'section': 'model'}]}
    models=[]
    names=['dim_customer','dim_product','fact_sales','fact_returns','fact_payments']
    grains=['One row per customer', 'One row per product', 'One row per sale record',
            'One row per return record', 'One row per product-attributed payment record']
    for i,name in enumerate(names):
        key='customer_id' if i==0 else 'product_id' if i==1 else name[5:]+'_id'
        columns=[{'name':key,'type':'NUMBER','key':'PK','nullable':False,'description':'Stable synthetic '+name.replace('_',' ')+' identifier.'}]
        if i>=2:
            columns += [{'name':'customer_id','type':'NUMBER','key':'FK','description':'References the conformed customer dimension.'},
                        {'name':'product_id','type':'NUMBER','key':'FK','description':'References the conformed product dimension.'},
                        {'name':'amount','type':'NUMBER(18,2)','description':'Recorded amount in the source currency; currency alignment and netting require review.'}]
        models.append({'id':name,'name':'GOLD.'+name.upper(),'layer':'gold','domain':'commerce',
                       'entity_type':'dimension' if i<2 else 'fact','grain':grains[i],
                       'description':'Synthetic gold review scope. Physical input bindings remain unverified.',
                       'disposition':'reuse' if i<2 else 'create','columns':columns,'artifact_id':'code-'+name})
        if i<2: models[-1]['reuse']={'existing_id':'prepared.'+name,'rationale':'Reuse the declared conformed dimension; verify its key uniqueness before adoption.'}
        fields=',\n    '.join(c['name'] for c in columns)
        add('code-'+name,'dbt/models/'+name+'.sql',"-- Synthetic candidate. Confirm source bindings and business meaning before execution.\nselect\n    "+fields+"\nfrom {{ source('prepared', '"+name+"') }}\n",requires=['project','sources','properties','run-guide'])
    add('project','dbt/dbt_project.yml','name: commerce_review\nversion: "1.0.0"\nconfig-version: 2\nprofile: commerce_review\nmodel-paths: [models]\nmodels:\n  commerce_review:\n    +materialized: view\n')
    add('sources','dbt/models/sources.yml','version: 2\nsources:\n  - name: prepared\n    database: "{{ env_var(\'DMA_SOURCE_DATABASE\') }}"\n    schema: "{{ env_var(\'DMA_SOURCE_SCHEMA\') }}"\n    tables:\n'+''.join('      - name: '+name+'\n' for name in names))
    properties='version: 2\nmodels:\n'
    for model in models:
        properties+='  - name: '+model['id']+'\n    description: '+json.dumps(model['grain'])+'\n    columns:\n'
        for c in model['columns']:
            properties+='      - name: '+c['name']+'\n        description: '+json.dumps(c['description'])+'\n'
            if c.get('key')=='PK': properties+='        data_tests: [not_null, unique]\n'
            if c.get('key')=='FK': properties+='        data_tests:\n          - relationships:\n              arguments:\n                to: ref(\''+('dim_customer' if c['name']=='customer_id' else 'dim_product')+'\')\n                field: '+c['name']+'\n'
    add('properties','dbt/models/properties.yml',properties)
    add('profile','dbt/profiles.example.yml',"commerce_review:\n  target: dev\n  outputs:\n    dev:\n      type: snowflake\n      account: \"{{ env_var('SNOWFLAKE_ACCOUNT') }}\"\n      user: \"{{ env_var('SNOWFLAKE_USER') }}\"\n      authenticator: externalbrowser\n      role: \"{{ env_var('SNOWFLAKE_ROLE') }}\"\n      warehouse: \"{{ env_var('SNOWFLAKE_WAREHOUSE') }}\"\n      database: \"{{ env_var('DMA_TARGET_DATABASE') }}\"\n      schema: \"{{ env_var('DMA_TARGET_SCHEMA') }}\"\n      threads: 1\n")
    add('design-guide','design.md','# Synthetic commerce model\n\nThis package demonstrates the review experience for a scoped gold model: three facts and two reused dimensions. It is not a validated customer migration. Bronze and silver are outside this UI exercise; the five prepared input tables are simulated external prerequisites.\n\nUse Data model to inspect grain, columns and proposed joins. Inspect the complete ERD and dictionary in this folder. Table names identify proposed objects, not verified Snowflake relations.\n\nFacts retain source identifiers and recorded amounts. Each fact joins to customer and product on the declared keys. Do not sum payment and sales amounts together: they represent different events. Confirm product attribution for payments, source currency, taxes, refunds, history and deletion behavior with the business owner.\n\nNext: return corrections using Prepare review feedback. Native compilation, data accuracy, access validation, business approval and deployment are pending.\n','documentation',['reviewer','engineer'])
    add('run-guide','dbt/IMPLEMENTATION.md','# dbt + Snowflake implementation candidate\n\nSynthetic UI exercise. No warehouse commands have been executed. Models and properties cover the five-table gold scope. Source bindings, runtime qualification and business definitions remain unverified. The files are reviewable; deployment is not authorized.\n\n1. Review the design, exact code and open questions with the owner. These SQL files belong in dbt, not a Snowflake worksheet.\n2. In an isolated development environment, select and pin a supported dbt Core/dbt-snowflake combination. This fixture uses modern data_tests and relationships.arguments syntax; version compatibility has not been qualified.\n3. Configure your private profile using profiles.example.yml. Supply the named environment values without committing credentials. The five prepared source tables must exist with the dictionary columns.\n4. Keep target database/schema separate from those sources. Have the engineer verify source availability, permissions and model bindings.\n5. Only after execution is authorized, run dbt parse, then a scoped development dbt build, review tests, and compare independent populations and amounts. Test fanout, orphan keys, null behavior, access and currencies.\n6. Retain build evidence and obtain business sign-off before a separate deployment request. No automated promotion or source retirement is included.\n','implementation',['engineer'],['profile'])
    add('validation-guide','remaining-checks.md','# Validation checklist\n\nThis package validates no real data.\n\n- Verify the actual Snowflake source objects and columns.\n- Run the selected dbt version against an authorized development target.\n- Prove primary-key uniqueness and foreign-key coverage.\n- Compare row counts and identifiers before and after each join.\n- Reconcile amounts by customer, product, currency and period against an independent baseline.\n- Review access controls and negative cases.\n- Have the business owner resolve definitions and approve the exact candidate.\n\nPackage checks establish file integrity only.\n','validation',['reviewer','engineer'])
    review={'schema_version':1,'title':'Commerce model review','description':'Synthetic example · 3 facts and 2 dimensions · dbt + Snowflake candidates · no warehouse execution.',
            'source_fingerprint':source_fingerprint(state),'context_sha256':context_fingerprint(state),'target':{'framework':'dbt','warehouse':'snowflake'},
            'models':models,'relationships':[{'from':name,'to':dim,'kind':'relationship','status':'proposed','predicate':name+'.'+key+' = '+dim+'.'+key,'cardinality':'many:1'} for name in names[2:] for dim,key in [('dim_customer','customer_id'),('dim_product','product_id')]],
            'handoff':{'design_artifact_id':'design-guide','implementation_guide_artifact_id':'run-guide'},
            'changes':[],'decisions':[], 'validation':[{'id':'source-binding','label':'Verify physical input columns','scope':'warehouse','status':'pending','details':'Synthetic source declarations only; no Snowflake catalogue or execution.'}], 'artifacts':artifacts}
    review['disclosure']=synthetic_disclosure(artifacts,'engineer')
    package=destination/'commerce-model-review.zip'
    package_delivery(state,review,work,package,'engineer',['documentation','diagrams','dictionary','implementation','validation'])
    result=verify_delivery(package)
    handoff=destination/'handoff';handoff.mkdir()
    with zipfile.ZipFile(package) as archive: archive.extractall(handoff)  # Only our newly generated, verified archive.
    (work/'review.json').write_text(json.dumps(review,indent=2)+'\n')
    (work/'package-check.json').write_text(json.dumps(result,indent=2)+'\n')
    (destination/'README.md').write_text('Current package: commerce-model-review.zip\n\nExtract it and open START_HERE.html. The same extracted package is in handoff/.\n\ntechnical-evidence/ is generator input and verification evidence, not part of the handoff. This is a synthetic usability test, not native model validation.\n')
    return {'entrypoint':str(handoff/'START_HERE.html'),'package':str(package),'verification':result}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    print(json.dumps(run(parser.parse_args().output),indent=2))
