"""Portable handoff behavior; these synthetic cases do not qualify any warehouse."""
import base64
import contextlib
import copy
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import delivery_portal as portal


def fixture(root):
    state={'schema_version':1,'engagement_id':'synthetic-pilot','revision':1,'status':'discovery',
           'answers':{'framework':'dbt','warehouse':'snowflake','semantic_target':'omni'},
           'inputs':{'source':{'fingerprint':{'algorithm':'sha256','value':'f'*64,'scope':'inventory','complete':True}},
                     'catalogue':{'sha256':'c'*64}},'readiness':{'platform':{}},'next_actions':['Review source coverage']}
    content={'docs/model.md':('documentation',b'Model documentation',['reviewer','engineer']),
             'models/gold.sql':('implementation',b'select 1 as id',['engineer']),
             'seeds/raw.csv':('sample_data',b'SENSITIVE_RAW_MARKER',['engineer']),
             'audit/evidence.json':('technical_audit',b'{"private":"INTERNAL_AUDIT_MARKER"}',['audit'])}
    artifacts=[]
    for i,(path,(category,body,audiences)) in enumerate(content.items()):
        dest=root/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(body)
        artifacts.append({'id':str(i),'path':path,'category':category,'audiences':audiences,'sha256':hashlib.sha256(body).hexdigest()})
    models=[{'id':l+'.orders','name':l+'.orders','layer':l,'grain':'One row per order','columns':[{'name':'id','type':'NUMBER','key':'PK','description':'Source identifier'}]} for l in portal.LAYERS]
    review={'schema_version':1,'title':'Synthetic review','source_fingerprint':portal.source_fingerprint(state),
            'context_sha256':portal.context_fingerprint(state),'target':{'framework':'dbt','warehouse':'snowflake'},
            'models':models,'relationships':[{'from':'bronze.orders','to':'silver.orders','kind':'lineage','label':'Clean identifiers'},
                                            {'from':'silver.orders','to':'gold.orders','kind':'lineage','label':'Business contract'}],
            'artifacts':artifacts,'validation':[{'id':'pending-native','label':'Native build','scope':'warehouse','status':'pending',
                                               'expected':'PRIVATE_VALUE_MARKER','actual':None,'details':'Not executed'}]}
    return state,review


class DeliveryPortalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.state,self.review=fixture(self.root)

    def package(self,**kwargs):
        path=self.root/('delivery-'+str(len(list(self.root.glob('*.zip'))))+'.zip')
        portal.package_delivery(self.state,self.review,self.root,path,**kwargs)
        return path

    def artifact(self, path, body, category='documentation', audiences=None):
        body=body.encode() if isinstance(body,str) else body
        dest=self.root/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(body)
        record={'id':'extra-'+str(len(self.review['artifacts'])),'path':path,'category':category,
                'audiences':audiences or ['engineer'],'sha256':hashlib.sha256(body).hexdigest()}
        self.review['artifacts'].append(record)
        return record

    def deployment(self):
        preview=self.artifact('deployment/plan-review.json','{"summary":"Curated deployment plan"}','validation')
        receipt=self.artifact('deployment/receipt-review.json','{"status":"succeeded","scope":"synthetic"}','validation')
        self.state['status']='handoff_prepared';self.state['delivery']={'status':'prepared','artifact_count':4}
        self.state['deployment_review']={'schema_version':1,'status':'plan_prepared',
            'target':{'framework':'dbt','warehouse':'snowflake','semantic_target':'omni','environment':'development'},
            'handoff':{'context_sha256':portal.context_fingerprint(self.state),'manifest_sha256':'a'*64},
            'choices':[{'id':action,'available':action!='promote','reason':'Promotion requires separate qualified development results.' if action=='promote' else 'Request only.'} for action in portal.DEPLOYMENT_ACTIONS],
            'plan':{'id':'deployment-1','sha256':'b'*64,'action':'deploy_development','target_label':'Retained development environment',
                    'summary':'Create the selected development model.','evidence_artifact_id':preview['id'],'evidence_sha256':preview['sha256'],
                    'files':[{'path':'models/gold.sql','sha256':self.review['artifacts'][1]['sha256'],'version':'candidate-1','operation':'create_or_replace'}],
                    'impacts':['Replaces the selected development model.'],'steps':['Run the reviewed adapter action.'],
                    'recovery':['Restore the prior development model version.'],'prerequisites':['Separate exact-action authorization.']},
            'receipts':[{'id':'receipt-1','action':'deploy_development','status':'succeeded','scope':'synthetic',
                         'summary':'Reported synthetic result; no remote deployment.','evidence_artifact_id':receipt['id'],'sha256':receipt['sha256']}]}
        return preview,receipt

    def payload(self,path):
        with zipfile.ZipFile(path) as z:page=z.read('START_HERE.html').decode()
        return json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])

    def quality(self, audiences=None):
        self.review['artifacts']=[a for a in self.review['artifacts'] if a['path']!='quality/evidence.json']
        rows=[]
        for lane,scope in portal.QUALITY_SCOPES.items():
            row={'id':lane,'scope':scope,'status':'unknown','unit':'checks','total':None,
                 'summary':'The required check has not been run.','next_action':'Run the selected check and retain its evidence.',
                 'gaps':['The expected scope still needs an inventory.']}
            row.update({key:0 for key in portal.QUALITY_COUNTS})
            rows.append(row)
        rows[0].update(status='pass',unit='files',checked=2,total=2,summary='Configured code conventions pass.',
                       next_action='Review independent model results separately.',gaps=[])
        rows[1].update(status='pending',total=1,pending=1,summary='Project validation has not run.',
                       next_action='Run the pinned project validator.',gaps=['One project validation remains pending.'])
        rows[2].update(status='unsupported',total=4,unsupported=4,summary='These statements need target-side validation.',
                       next_action='Use the selected warehouse validator for all four statements.',gaps=['Local lint cannot validate native object references.'])
        rows[3].update(status='fail',total=3,checked=3,failed=1,unit='cases',summary='The independent metric comparison failed.',
                       next_action='Repair the model arithmetic and rerun the independent cases.',gaps=['One metric case returns the wrong result despite clean syntax.'])
        document={'schema_version':1,'kind':'quality_evidence','context_sha256':portal.context_fingerprint(self.state),
                  'target':copy.deepcopy(self.review['target']),'checks':rows}
        artifact=self.artifact('quality/evidence.json',json.dumps(document),'validation',audiences or ['engineer','reviewer'])
        self.review['quality_checks']=[dict(copy.deepcopy(row),context_sha256=document['context_sha256'],
                                         evidence_artifact_id=artifact['id'],sha256=artifact['sha256']) for row in rows]
        return artifact,document

    def update_quality_document(self,artifact,document):
        body=json.dumps(document).encode();(self.root/artifact['path']).write_bytes(body)
        artifact['sha256']=hashlib.sha256(body).hexdigest()
        for row in self.review['quality_checks']:row['sha256']=artifact['sha256']

    def test_quality_keeps_clean_code_distinct_from_wrong_model_results(self):
        self.quality()
        path=self.package(audience='engineer')
        rows={q['id']:q for q in self.payload(path)['review']['quality_checks']}
        self.assertEqual(rows['code_conventions']['status'],'pass')
        self.assertEqual(rows['data_accuracy']['status'],'fail')
        self.assertEqual(rows['warehouse_validation']['status'],'unsupported')
        self.assertEqual(rows['project_validity']['status'],'pending')
        self.assertEqual(rows['data_accuracy']['failed'],1)
        self.assertEqual(rows['warehouse_validation']['unsupported'],4)
        self.assertTrue(all(q['evidence_state']=='selected' for q in rows.values()))
        self.assertEqual(portal.verify_delivery(path)['status'],'integrity_verified')

    def test_quality_rejects_false_pass_and_inconsistent_scope_counts(self):
        for changes in [{'checked':0,'total':0},{'checked':True},{'failed':3},{'total':5},
                        {'checked':1,'skipped':1},{'scope':'warehouse'},{'failed':1},
                        {'next_action':''},{'gaps':['An uninspected file remains.']}]:
            with self.subTest(changes=changes):
                self.quality();self.review['quality_checks'][0].update(changes)
                with self.assertRaisesRegex(ValueError,'Quality|quality'):self.package(audience='engineer')

    def test_quality_unknown_scope_skips_and_not_applicable_remain_explicit(self):
        artifact,document=self.quality()
        document['checks'][0].update(status='skipped',checked=0,skipped=2,summary='Both files were deliberately excluded.',gaps=['The excluded files remain uninspected.'])
        document['checks'][1].update(status='not_applicable',pending=0,total=1,not_applicable=1,gaps=['No framework project applies to the selected native SQL route.'])
        document['checks'][2].update(status='unknown',total=None,unsupported=0,gaps=['No remote statement inventory is available.'])
        self.review['quality_checks']=[dict(row,context_sha256=document['context_sha256'],evidence_artifact_id=artifact['id'],sha256=artifact['sha256']) for row in document['checks']]
        self.update_quality_document(artifact,document)
        rows=self.payload(self.package(audience='engineer'))['review']['quality_checks']
        self.assertEqual([r['status'] for r in rows],['skipped','not_applicable','unknown','fail'])
        self.assertIsNone(rows[2]['total'])

    def test_quality_actual_evidence_context_target_and_summary_must_match(self):
        for mutation in ('context','target','summary'):
            with self.subTest(mutation=mutation):
                artifact,document=self.quality()
                if mutation=='context':document['context_sha256']='a'*64
                elif mutation=='target':document['target']['warehouse']='bigquery'
                else:document['checks'][0]['summary']='Contradictory alternate summary.'
                self.update_quality_document(artifact,document)
                with self.assertRaisesRegex(ValueError,'Quality.*(context|target|summary)'):self.package(audience='engineer')

    def test_quality_requires_current_registered_artifact_hash(self):
        self.quality();row=self.review['quality_checks'][0]
        for field,value,message in [('context_sha256','a'*64,'context'),('sha256','b'*64,'hash'),
                                    ('evidence_artifact_id','absent','registered')]:
            old=row[field];row[field]=value
            with self.assertRaisesRegex(ValueError,message):self.package(audience='engineer')
            row[field]=old

    def test_quality_omitted_selection_and_audience_remove_claim_payloads(self):
        self.quality(audiences=['engineer'])
        self.review['quality_checks'][0]['private_config']='DO_NOT_EXPORT_QUALITY_CONFIGURATION'
        for audience,include in [('engineer',['implementation']),('reviewer',None)]:
            with self.subTest(audience=audience):
                path=self.package(audience=audience,include=include)
                rows=self.payload(path)['review']['quality_checks']
                self.assertTrue(all(q['status']=='unknown' and q['total'] is None for q in rows))
                self.assertTrue(all('sha256' not in q and 'evidence_artifact_id' not in q for q in rows))
                with zipfile.ZipFile(path) as z:
                    body=b'\n'.join(z.read(name) for name in z.namelist())
                    self.assertNotIn(b'The independent metric comparison failed.',body)
                    self.assertNotIn(b'DO_NOT_EXPORT_QUALITY_CONFIGURATION',body)
                self.assertEqual(portal.verify_delivery(path)['status'],'integrity_verified')

    def test_quality_status_only_page_never_claims_unread_evidence_pass(self):
        self.quality();path=self.root/'QUALITY.html';portal.render_engagement(self.state,path,self.review)
        payload=json.loads(path.read_text().split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        self.assertTrue(all(q['status']=='unknown' for q in payload['review']['quality_checks']))
        self.assertEqual(payload['files'],[])

    def test_quality_legacy_validation_inventory_is_unchanged(self):
        payload=self.payload(self.package(audience='engineer'))
        self.assertNotIn('quality_checks',payload['review'])
        self.assertEqual(payload['review']['validation'],self.review['validation'])

    def test_quality_rejects_duplicate_lanes_and_malformed_selected_json(self):
        artifact,_=self.quality()
        self.review['quality_checks'][1]['id']='code_conventions'
        self.review['quality_checks'][1]['scope']='static'
        with self.assertRaisesRegex(ValueError,'Duplicate quality'):self.package(audience='engineer')
        self.review['quality_checks']=self.review['quality_checks'][:1]
        body=b'not json';(self.root/artifact['path']).write_bytes(body)
        artifact['sha256']=hashlib.sha256(body).hexdigest();self.review['quality_checks'][0]['sha256']=artifact['sha256']
        with self.assertRaisesRegex(ValueError,'Disclosure scan'):self.package(audience='engineer')

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for the deployment UI guard regression')
    def test_deployment_absent_plan_does_not_stop_quality_and_file_controls(self):
        source=(portal.ASSETS/'portal.js').read_text()
        function=re.search(r'function concreteDeploymentPlan\(action\)\{[^\n]+',source).group(0)
        script="const assert=require('node:assert/strict');let deployment;"+function+"""
assert.equal(concreteDeploymentPlan(undefined), null);
deployment={};assert.equal(concreteDeploymentPlan('publish_pr'), null);
deployment={plan:{action:'publish_pr'}};assert.equal(concreteDeploymentPlan('publish_pr'), null);
deployment={plan:{id:'plan',sha256:'a',action:'publish_pr',files:[{version:'v1',operation:'create'}],summary:'Publish review',target_label:'Development',impacts:['Creates PR'],steps:['Review'],recovery:['Close PR']}};
assert.equal(concreteDeploymentPlan('publish_pr'), deployment.plan);
assert.equal(concreteDeploymentPlan('promote'), null);
"""
        result=subprocess.run([shutil.which('node'),'-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_deployment_projection_retains_target_and_excludes_runner_secrets(self):
        self.deployment();raw=self.state['deployment_review']
        raw.update(private_key='DO_NOT_EXPORT',runner={'command':'DO_NOT_EXPORT','token':'DO_NOT_EXPORT'})
        raw['target']['credentials']='DO_NOT_EXPORT';raw['plan']['source_root']='/private/DO_NOT_EXPORT'
        raw['receipts'][0]['signature']='DO_NOT_EXPORT'
        path=self.package(audience='engineer')
        payload=self.payload(path);deployment=payload['deployment']
        self.assertTrue(deployment['current'])
        self.assertEqual(deployment['target']['warehouse'],'snowflake')
        self.assertIn('does not authenticate',deployment['assurance'])
        with zipfile.ZipFile(path) as z:self.assertNotIn(b'DO_NOT_EXPORT',z.read('START_HERE.html'))
        self.assertEqual(portal.verify_delivery(path)['status'],'integrity_verified')

    def test_deployment_detail_obeys_selected_evidence_and_audience(self):
        self.deployment()
        payload=self.payload(self.package(audience='engineer',include=['implementation']))
        self.assertNotIn('plan',payload['deployment']);self.assertEqual(payload['deployment']['receipts'],[])
        self.assertNotIn('deployment',self.payload(self.package(audience='reviewer')))
        self.assertNotIn('deployment',self.payload(self.package(audience='audit')))

    def test_deployment_evidence_hash_drift_blocks_export(self):
        preview,_=self.deployment()
        self.state['deployment_review']['plan']['evidence_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'Deployment evidence changed'):self.package(audience='engineer')
        self.state['deployment_review']['plan']['evidence_sha256']=preview['sha256']
        self.state['deployment_review']['receipts'][0]['sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'Deployment evidence changed'):self.package(audience='engineer')

    def test_deployment_plan_file_hash_must_match_selected_implementation(self):
        self.deployment()
        self.state['deployment_review']['plan']['files'][0]['sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'Deployment plan file changed'):self.package(audience='engineer')

    def test_deployment_requests_disabled_for_stale_handoff_or_changed_target(self):
        for mutation in ('status','handoff','target','reported_stale'):
            with self.subTest(mutation=mutation):
                self.deployment()
                if mutation=='status':self.state['delivery']['status']='stale'
                elif mutation=='handoff':self.state['deployment_review']['handoff']['context_sha256']='c'*64
                elif mutation=='target':self.state['deployment_review']['target']['warehouse']='bigquery'
                else:self.state['deployment_review']['status']='stale'
                result=portal._deployment_presentation(self.state,'engineer')
                self.assertFalse(result['current']);self.assertEqual(result['status'],'stale')
                self.assertFalse(any(c['available'] for c in result['choices']))
                self.assertEqual(result['target']['warehouse'],'snowflake')

    def test_deployment_unexpected_nested_display_values_are_rejected(self):
        self.deployment();self.state['deployment_review']['status']={'private':'not a public status'}
        with self.assertRaisesRegex(ValueError,'must be text'):portal._deployment_presentation(self.state,'engineer')

    def test_deployment_rejects_unknown_actions_and_private_file_paths(self):
        self.deployment();raw=self.state['deployment_review']
        raw['choices'][0]['id']='execute_shell'
        with self.assertRaisesRegex(ValueError,'deployment action'):portal._deployment_presentation(self.state,'engineer')
        raw['choices'][0]['id']='publish_pr';raw['plan']['files'][0]['path']='/private/project/model.sql'
        with self.assertRaisesRegex(ValueError,'relative'):portal._deployment_presentation(self.state,'engineer')

    def test_deployment_values_are_escaped_and_status_page_has_no_payload(self):
        self.deployment();raw=self.state['deployment_review'];raw['plan']['summary']='</script><script>alert(1)</script>'
        path=self.root/'DEPLOYMENT.html';portal.render_engagement(self.state,path,self.review)
        page=path.read_text()
        self.assertNotIn(raw['plan']['summary'],page)
        payload=json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(payload['files'],[])
        self.assertIn("connect-src 'none'",page)
        self.assertIn('request_only:true',page)
        self.assertIn('It is not authorization, a signed approval, or an execution receipt.',page)

    def test_reviewer_excludes_payloads_in_every_byte(self):
        path=self.package()
        with zipfile.ZipFile(path) as z:
            self.assertNotIn('02_Implementation/models/gold.sql',z.namelist())
            body=b'\n'.join(z.read(n) for n in z.namelist())
            for marker in (b'SENSITIVE_RAW_MARKER',b'INTERNAL_AUDIT_MARKER',b'PRIVATE_VALUE_MARKER',base64.b64encode(b'SENSITIVE_RAW_MARKER')):
                self.assertNotIn(marker,body)
        self.assertEqual(portal.verify_delivery(path)['status'],'integrity_verified')

    def test_engineer_selects_real_implementation_without_raw_or_audit(self):
        path=self.package(audience='engineer',include=['implementation'])
        with zipfile.ZipFile(path) as z:
            self.assertEqual(z.read('02_Implementation/models/gold.sql'),b'select 1 as id')
            self.assertEqual(len(z.namelist()),3)
            page=z.read('START_HERE.html')
            self.assertNotIn(b'PRIVATE_VALUE_MARKER',page)
            self.assertNotIn(b'Clean identifiers',page)

    def test_audit_is_separate(self):
        path=self.package(audience='audit')
        with zipfile.ZipFile(path) as z:self.assertIn('Technical_Audit/audit/evidence.json',z.namelist())
        with self.assertRaises(ValueError):self.package(audience='engineer',include=['technical_audit'])

    def test_reviewer_rejects_raw_selection(self):
        with self.assertRaises(ValueError):self.package(include=['sample_data'])

    def test_reviewer_code_cannot_be_misclassified_as_documentation(self):
        self.review['artifacts'][1].update(category='documentation',audiences=['reviewer'])
        with self.assertRaisesRegex(ValueError,'relabeled'):self.package()

    def test_missing_dependencies_block_export(self):
        self.review['artifacts'][1]['requires']=['2']
        with self.assertRaisesRegex(ValueError,'dependencies'):self.package(audience='engineer',include=['implementation'])
        self.package(audience='engineer',include=['implementation','sample_data'])

    def test_changed_artifact_blocks(self):
        (self.root/'models/gold.sql').write_text('wrong query')
        with self.assertRaisesRegex(ValueError,'changed'):self.package(audience='engineer')

    def test_changed_catalogue_blocks_review(self):
        self.state['inputs']['catalogue']['sha256']='new'
        with self.assertRaisesRegex(ValueError,'stale'):self.package()

    def test_changed_source_and_target_block_review(self):
        self.state['inputs']['source']['fingerprint']['value']='new'
        with self.assertRaisesRegex(ValueError,'stale'):self.package()
        self.state,self.review=fixture(self.root)
        self.state['answers']['warehouse']='bigquery'
        with self.assertRaisesRegex(ValueError,'target'):self.package()

    def test_traversal_symlink_secret_and_nested_archive_reject(self):
        record=self.review['artifacts'][0]
        for path in ('../secret.txt','/absolute.md','profiles.yml','bad.zip'):
            record['path']=path
            with self.assertRaises(ValueError):self.package()
        record['path']='linked.md';(self.root/'linked.md').symlink_to(self.root/'docs/model.md')
        with self.assertRaisesRegex(ValueError,'Symlink'):self.package()

    def test_active_svg_rejects(self):
        record=self.review['artifacts'][0];record['path']='attack.svg'
        body=b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        (self.root/'attack.svg').write_bytes(body);record['sha256']=hashlib.sha256(body).hexdigest()
        with self.assertRaisesRegex(ValueError,'SVG'):self.package()

    def test_malformed_svg_is_an_actionable_export_error(self):
        self.artifact('docs/broken.svg','<svg><g></svg>','diagrams')
        with self.assertRaisesRegex(ValueError,'Malformed SVG XML'):
            portal.select_artifacts(self.review,self.root,'engineer',['diagrams'])
        review_path=self.root/'review.json';review_path.write_text(json.dumps(self.review))
        output=self.root/'bad.zip';stderr=io.StringIO()
        with patch('guided_workflow.assess_engagement',return_value=self.state),contextlib.redirect_stderr(stderr):
            result=portal.main(['package','--state',str(self.root/'state.json'),'--review',str(review_path),
                                '--artifacts',str(self.root),'--audience','engineer','--output',str(output)])
        self.assertEqual(result,2)
        self.assertIn('Delivery blocked: Malformed SVG XML',stderr.getvalue())
        self.assertFalse(output.exists())

    def test_svg_external_instructions_and_base_are_rejected(self):
        payloads=[b'<?xml-stylesheet href="https://invalid.example/style.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
                  b'<svg xmlns="http://www.w3.org/2000/svg" xml:base="https://invalid.example/"><rect fill="url(#remote)"/></svg>',
                  b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="u\\72l(https://invalid.example/)"/></svg>']
        for payload in payloads:
            with self.assertRaises(ValueError):portal._validate_svg(payload)
        for encoding in ('utf-16','utf-16-le','utf-16-be'):
            with self.assertRaises(ValueError):portal._validate_svg(payloads[0].decode().encode(encoding))

    def test_svg_self_and_skip_layer_paths_avoid_zero_loop_and_middle_card(self):
        edges=[{'from':'bronze.orders','to':'gold.orders','kind':'lineage'},
               {'from':'silver.orders','to':'silver.orders','kind':'relationship'}]
        layout=portal._diagram_layout(self.review['models'],edges)
        self.assertLess(min(y for _,y in layout['routes'][0]['points']),min(y for _,y in layout['positions'].values()))
        self.assertNotEqual(layout['routes'][1]['points'][0],layout['routes'][1]['points'][-1])
        self.assert_routes_avoid_unrelated_blocks(layout)

    def assert_routes_avoid_unrelated_blocks(self,layout):
        for route in layout['routes']:
            for mid,(x,y) in layout['positions'].items():
                if mid in (route['edge']['from'],route['edge']['to']):continue
                right,bottom=x+layout['card_width'],y+layout['card_height']
                for (ax,ay),(bx,by) in zip(route['points'],route['points'][1:]):
                    if ax==bx:
                        intersects=x<ax<right and max(min(ay,by),y)<min(max(ay,by),bottom)
                    else:
                        self.assertEqual(ay,by)
                        intersects=y<ay<bottom and max(min(ax,bx),x)<min(max(ax,bx),right)
                    self.assertFalse(intersects,(route['label'],mid))

    def test_parallel_roles_are_distinct_and_declared_semantics_visible(self):
        models=[{'id':name,'name':name,'layer':'gold','grain':'One row per ID','columns':[]} for name in ['orders','unrelated','addresses']]
        edges=[{'from':'orders','to':'addresses','kind':'relationship','role':role,
                'predicate':f'orders.{role}_id = addresses.id','cardinality':'many:0..1','status':status}
               for role,status in [('bill_to','authored'),('ship_to','proposed')]]
        layout=portal._diagram_layout(models,edges)
        self.assertNotEqual(layout['routes'][0]['points'],layout['routes'][1]['points'])
        self.assert_routes_avoid_unrelated_blocks(layout)
        svg=portal.model_svg(models,edges)
        for value in ['bill_to','ship_to','orders.bill_to_id = addresses.id','many:0..1','authored (declared)','proposed (declared)']:
            self.assertIn(value,svg)
        self.assertIn('stroke-dasharray="7 4"',svg)
        portal._validate_svg(svg.encode())

    def test_dense_connection_views_preserve_full_inventory_and_edge_accounting(self):
        models=[{'id':str(i),'layer':'gold','domain':'shared','columns':[]} for i in range(14)]
        edges=[{'from':str(i),'to':str(j),'kind':'relationship'} for i in range(14) for j in range(i+1,14)]
        views=portal.diagram_views(models,edges)
        self.assertGreater(len(views),1)
        self.assertEqual(sorted(mid for v in views for mid in v['model_ids']),sorted(m['id'] for m in models))
        self.assertEqual(sum(v['internal_connections'] for v in views)+sum(v['cross_view_connections'] for v in views)//2,len(edges))

    def test_native_omni_files_ship_byte_identically_only_as_implementation(self):
        records=[self.artifact(path,'dimensions:\n  id: {}\n','implementation') for path in ['omni/orders.view','omni/orders.topic','omni/relationships','omni/model']]
        records[1]['requires']=[records[0]['id'],records[2]['id'],records[3]['id']]
        path=self.package(audience='engineer',include=['implementation'])
        with zipfile.ZipFile(path) as z:
            for record in records:self.assertEqual(z.read('02_Implementation/'+record['path']),(self.root/record['path']).read_bytes())
        self.assertEqual(portal.verify_delivery(path)['status'],'integrity_verified')
        records[0].update(category='documentation',audiences=['reviewer'])
        with self.assertRaisesRegex(ValueError,'explicitly registered'):self.package()

    def test_native_omni_exception_does_not_allow_other_extensionless_or_active_files(self):
        for name in ['omni/README','omni/Relationships','omni/Model','omni/model.exe','omni/model.html','omni/relationships.exe','omni/relationships.html','omni/run.sh']:
            with self.subTest(name=name):
                record=self.artifact(name,'payload','implementation')
                with self.assertRaisesRegex(ValueError,'Unsupported artifact'):self.package(audience='engineer')
                self.review['artifacts'].remove(record)
        record=self.artifact('omni/relationships',b'\x00binary','implementation')
        with self.assertRaisesRegex(ValueError,'UTF-8 model text'):self.package(audience='engineer')

    def test_native_omni_retains_hash_dependency_and_symlink_boundaries(self):
        record=self.artifact('omni/orders.view','dimensions: {}','implementation')
        (self.root/record['path']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):self.package(audience='engineer')
        record['sha256']=hashlib.sha256(b'changed').hexdigest();record['requires']=['2']
        with self.assertRaisesRegex(ValueError,'dependencies'):self.package(audience='engineer')
        record['requires']=[];(self.root/record['path']).unlink();(self.root/record['path']).symlink_to(self.root/'models/gold.sql')
        with self.assertRaisesRegex(ValueError,'Symlink'):self.package(audience='engineer')

    def test_markdown_links_resolve_at_exported_category_destinations(self):
        self.artifact('guides/run.md','[SQL](../../02_Implementation/models/gold.sql#query)\n[Model](../docs/model.md)')
        path=self.package(audience='engineer')
        with zipfile.ZipFile(path) as z:
            page=z.read('START_HERE.html').decode()
            payload=json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
            guide=next(f for f in payload['files'] if f['path']=='01_Model/guides/run.md')
            self.assertEqual(set(guide['requires']),{'0','1'})
        self.assertEqual(portal.verify_delivery(path)['status'],'integrity_verified')
        with self.assertRaisesRegex(ValueError,'include the linked artifact'):self.package(audience='engineer',include=['documentation'])

    def test_markdown_relocation_error_suggests_correct_relative_path(self):
        self.artifact('guides/run.md','[SQL](../models/gold.sql)')
        with self.assertRaisesRegex(ValueError,r'after category relocation use ../../02_Implementation/models/gold.sql'):
            self.package(audience='engineer')

    def test_markdown_references_images_anchors_external_and_encoded_paths(self):
        self.artifact('docs/guide #1.md','# Target')
        self.artifact('docs/map.svg','<svg xmlns="http://www.w3.org/2000/svg"/>','diagrams')
        self.artifact('docs/links.md','''[Same section](#example)
[Web](https://example.org/a?q=b#c)
[Guide][ref] ![Map](map.svg) [ref][] [ref]
[ref]: <guide%20%231.md#target> "Optional title"
Inline `[ignored](missing.md)`.
```markdown
[ignored](missing.md)
```
Footnote[^1].
[^1]: An explanation, not a file.
''')
        self.package(audience='engineer')

    def test_markdown_unsafe_and_missing_internal_links_are_rejected(self):
        for target in ['../../../../escape.md','/absolute.md','//host/path','javascript:alert(1)','file:///etc/passwd',
                       '%2e%2e/%2e%2e/%2e%2e/escape.md','..%5csecret.md','missing.md','bad%00.md']:
            with self.subTest(target=target):
                record=self.artifact('docs/bad.md','[Bad]('+target+')')
                with self.assertRaisesRegex(ValueError,'Markdown'):self.package(audience='engineer')
                self.review['artifacts'].remove(record)
        self.artifact('docs/ref.md','[Guide][missing-reference]')
        with self.assertRaisesRegex(ValueError,'reference label'):self.package(audience='engineer')

    def test_context_manifest_matches_portal_and_legacy_manifest_still_verifies(self):
        path=self.package()
        expected=portal.context_fingerprint(self.state)
        self.assertEqual(portal.verify_delivery(path)['context_sha256'],expected)
        with zipfile.ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
        manifest=json.loads(entries['DELIVERY_MANIFEST.json']);self.assertEqual(manifest['context_sha256'],expected)
        manifest['context_sha256']='0'*64;entries['DELIVERY_MANIFEST.json']=json.dumps(manifest).encode()
        bad=self.root/'context-bad.zip'
        with zipfile.ZipFile(bad,'w') as z:
            for n,body in entries.items():z.writestr(n,body)
        with self.assertRaisesRegex(ValueError,'workflow context differs'):portal.verify_delivery(bad)
        del manifest['context_sha256'];entries['DELIVERY_MANIFEST.json']=json.dumps(manifest).encode()
        legacy=self.root/'legacy.zip'
        with zipfile.ZipFile(legacy,'w') as z:
            for n,body in entries.items():z.writestr(n,body)
        self.assertIsNone(portal.verify_delivery(legacy)['context_sha256'])

    def test_legacy_verification_retains_integrity_only_link_behavior(self):
        path=self.package()
        with zipfile.ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
        manifest=json.loads(entries['DELIVERY_MANIFEST.json']);del manifest['context_sha256']
        name='01_Model/docs/model.md';entries[name]=b'[Legacy unresolved reference](absent.md)'
        record=next(f for f in manifest['files'] if f['path']==name)
        record.update(sha256=hashlib.sha256(entries[name]).hexdigest(),bytes=len(entries[name]))
        entries['DELIVERY_MANIFEST.json']=json.dumps(manifest).encode()
        legacy=self.root/'legacy-links.zip'
        with zipfile.ZipFile(legacy,'w') as z:
            for n,body in entries.items():z.writestr(n,body)
        self.assertIsNone(portal.verify_delivery(legacy)['context_sha256'])

    def test_prepared_handoff_summary_does_not_embed_private_delivery_record(self):
        self.state['status']='handoff_prepared'
        self.state['delivery']={'status':'prepared','artifact_count':4,'assurance':'file_integrity_only',
                                'qualification':'Native acceptance pending','review_path':'/private/customer/review.json',
                                'artifacts':[{'secret':'PRIVATE_DELIVERY_MARKER'}]}
        summary=portal._summary(self.state)
        self.assertEqual(summary['delivery']['status'],'prepared')
        self.assertNotIn('review_path',summary['delivery'])
        self.assertNotIn('PRIVATE_DELIVERY_MARKER',json.dumps(summary))

    def test_html_escapes_untrusted_review(self):
        self.review['title']='</script><script>alert("XSS")</script>'
        path=self.root/'START_HERE.html';portal.render_engagement(self.state,path,self.review)
        page=path.read_text();self.assertNotIn(self.review['title'],page)
        self.assertIn('\\u003c/script\\u003e',page)

    def test_integrity_verifies_after_relocation_and_detects_substitution(self):
        path=self.package();other=self.root/'other';other.mkdir();moved=other/'package.zip';shutil.move(str(path),str(moved))
        shutil.rmtree(self.root/'docs')
        self.assertEqual(portal.verify_delivery(moved)['files'],2)
        with zipfile.ZipFile(moved) as z:entries={n:z.read(n) for n in z.namelist()}
        entries['01_Model/docs/model.md']=b'tampered'
        with zipfile.ZipFile(moved,'w') as z:
            for n,b in entries.items():z.writestr(n,b)
        with self.assertRaisesRegex(ValueError,'bytes differ'):portal.verify_delivery(moved)

    def test_export_does_not_mutate_input_review(self):
        original=copy.deepcopy(self.review)
        self.package(audience='engineer',include=['documentation'])
        self.assertEqual(self.review,original)

    def test_connected_svg_has_full_model_and_edge_coverage(self):
        import xml.etree.ElementTree as ET
        svg=portal.model_svg(self.review['models'],self.review['relationships'])
        root=ET.fromstring(svg);ns={'s':'http://www.w3.org/2000/svg'}
        self.assertEqual(len(root.findall('s:g',ns)),3)
        self.assertEqual(len(root.findall('s:path',ns)),2)
        portal._validate_svg(svg.encode())

    def test_large_model_views_preserve_all_objects_and_cross_view_counts(self):
        models=[{'id':'model-'+str(i),'name':'model-'+str(i),'layer':portal.LAYERS[i%3],'domain':'sales','columns':[]} for i in range(100)]
        edges=[{'from':models[i]['id'],'to':models[i+1]['id'],'kind':'lineage'} for i in range(99)]
        views=portal.diagram_views(models,edges)
        ids=[mid for v in views for mid in v['model_ids']]
        self.assertEqual(len(ids),100);self.assertEqual(len(set(ids)),100)
        self.assertTrue(all(len(v['model_ids'])<=36 for v in views))
        self.assertEqual(sum(v['internal_connections'] for v in views)+sum(v['cross_view_connections'] for v in views)//2,len(edges))

    def test_renderer_never_copies_private_state(self):
        self.state['inputs']['source']['path']='/private/customer/repo'
        self.state['history']=[{'private':'HISTORY_MARKER'}]
        dest=self.root/'start.html';portal.render_engagement(self.state,dest)
        self.assertNotIn('/private/customer',dest.read_text());self.assertNotIn('HISTORY_MARKER',dest.read_text())

    def test_empty_selection_rejects_and_existing_output_preserved(self):
        with self.assertRaises(ValueError):self.package(include=[])
        path=self.package();before=path.read_bytes()
        with self.assertRaises(ValueError):portal.package_delivery(self.state,self.review,self.root,path)
        self.assertEqual(path.read_bytes(),before)

    def test_default_export_reuses_saved_deliverable_selection(self):
        self.state['answers']['deliverables']=['documentation']
        path=self.package(audience='engineer')
        with zipfile.ZipFile(path) as z:
            self.assertEqual(set(z.namelist()),{'01_Model/docs/model.md','START_HERE.html','DELIVERY_MANIFEST.json'})

    def test_pass_cannot_fabricate_human_approval(self):
        self.review['validation'][0].update(scope='business',status='pass')
        with self.assertRaisesRegex(ValueError,'Human approval'):self.package()


if __name__=='__main__':unittest.main()
