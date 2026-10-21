"""Independent OOXML/CSV reads exercise portable export contracts, not live imports."""
import copy
import csv
import io
import json
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import migration_plan_exports as exports

S = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
W = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def fixture(platform='generic', output='local'):
    def model(identity, key, parent=None):
        return {'id':identity, 'name':identity+' café 顧客', 'domain':'commerce', 'layer':'gold',
                'disposition':'create' if parent else 'reuse',
                'grain':'One row per '+key, 'depends_on':[parent] if parent else [],
                'columns':[{'name':key,'type':'INT64','key':'PK','description':'Identifier — supplied'},
                           {'name':'amount','type':'NUMERIC','description':'USD amount'}]}
    def item(identity, deps=(), operation='create'):
        return {'id':identity,'title':'Build '+identity,'outcome':'Preserve external revenue','scope':'Commerce pilot',
                'model_ids':['orders'],'mapping_ids':['split.order'],'consumer_ids':['dashboard.sales'],
                'acceptance_criteria':[{'id':identity+'.check','expected':'Independent expected totals agree',
                    'evidence_label':'Native check pending','evidence_recorded':False}],
                'dependencies':list(deps),'operation':operation,
                'effort':{'complexity':'Difficult','confidence':'medium','basis':'Two consumer mappings'},
                **({'external_id':'EXISTING-17'} if operation=='update' else {})}
    domain={'domain_id':'commerce','plan_sha256':'a'*64,'freshness':'current',
        'config':{'domain_id':'commerce','mode':'migration','output_format':output,'ticket_platform':platform},
        'model_ids':['customers','orders','refunds'],
        'models':[model('customers','customer_id'),model('orders','order_id','customers'),model('refunds','refund_id','orders')],
        'inventory':{'baseline_status':'partial','tables':[{'id':'legacy.orders','name':'Historical orders','model_ids':['orders','refunds']},
                     {'id':'legacy.returns','name':'Historical returns','model_ids':['refunds']}],
            'mappings':[{'id':'split.order','disposition':'split','relationship':'many_to_many','status':'mapped','review_status':'proposed',
                'legacy_sources':[{'table_id':'legacy.orders','kind':'table'},{'table_id':'legacy.returns','kind':'table'}],
                'targets':[{'model_id':'orders','kind':'table'},{'model_id':'refunds','kind':'table'}],
                'rationale':'Keep both old table populations visible'}], 'unmatched':[],'coverage':{},'omitted_details':False},
        'relationships':[{'from':'orders','to':'customers','kind':'relationship','cardinality':'many_to_one','predicate':'orders.customer_id = customers.customer_id'}],
        'graph_edges':[{'id':'mapped-source','source':{'kind':'legacy_table','id':'legacy.orders'},'target':{'kind':'mapping','id':'split.order'},'status':'proposed'},
                       {'id':'mapped-target','source':{'kind':'mapping','id':'split.order'},'target':{'kind':'model','id':'orders'},'status':'proposed'}],
        'source_lineage':{'status':'supplied','nodes':[{'id':'raw.orders','kind':'source','label':'Raw orders'},
                          {'id':'legacy.orders','kind':'legacy_table','label':'Historical orders'}],
                         'edges':[{'id':'extract','source_id':'raw.orders','target_id':'legacy.orders','status':'observed','evidence_labels':['Supplied source definition']}]},
        'consumers':[{'id':'dashboard.sales','kind':'dashboard','label':'Sales','model_ids':['orders'],
                      'topic_ids':['orders'],'legacy_table_ids':['legacy.orders'],'disposition':'reconnect','status':'proposed'}],
        'work_items':[item('work.second',['work.first']),item('work.first'),item('work.update',['work.second'],'update'),item('work.review',operation='review')],
        'waves':[{'id':'wave.second','title':'Verify','item_ids':['work.second'],'depends_on':['wave.first']},
                 {'id':'wave.first','title':'Build','item_ids':['work.first'],'depends_on':[]}],
        'decisions':[{'id':'choice','text':'Preserve behavior','model_ids':['orders'],'consumer_ids':[]}],
        'questions':[{'id':'owner','text':'Who accepts parity?','model_ids':[],'consumer_ids':['dashboard.sales']}],
        'narrative':'Proposed migration. Not executed.','warnings':['Physical binding pending'],
        'missing_consumers':[{'id':'dashboard.unmapped','label':'Unmapped report','status':'unmatched'}],
        'archived_edits':[{'id':'retired-item','notes':'Preserve my note','owner':'Requested reviewer'}]}
    return {'schema_version':1,'qualification':'Synthetic test only','domains':[domain]}


def files(summary):
    return {r['path'].split('/',2)[-1]:r for r in exports.export_files(summary)}


def workbook(content):
    """Read OOXML independently: no dependency on the exporter projection helpers."""
    result={}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        index=ET.fromstring(archive.read('xl/workbook.xml'))
        for i,sheet in enumerate(index.findall('s:sheets/s:sheet',S),1):
            doc=ET.fromstring(archive.read('xl/worksheets/sheet%d.xml'%i))
            rows=[]
            for row in doc.findall('s:sheetData/s:row',S):
                cells=[]
                for cell in row.findall('s:c',S):
                    assert cell.get('t')=='inlineStr'
                    assert cell.find('s:f',S) is None
                    cells.append(''.join(cell.itertext()))
                rows.append(cells)
            result[sheet.get('name')]=(rows,doc)
    return result


def document(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            ET.fromstring(archive.read(name))
        root=ET.fromstring(archive.read('word/document.xml'))
    return root, [n.text or '' for n in root.findall('.//w:t',W)]


class MigrationPlanExportTests(unittest.TestCase):
    def test_actual_core_public_projection_keys_coverage_context_and_human_edits(self):
        import test_migration_planning as core_fixture
        case=core_fixture.MigrationPlanningTests();case.setUp()
        try:
            entities={x['id']:x for x in case.state['workflow']['design']['entities']}
            entities['customers']['columns'][0]['key']='PK'
            entities['orders']['columns'].append({'name':'customers_id','type':'integer','key':'FK','description':'Supplied attribution key'})
            case.enable();case.save(core_fixture.plan())
            core_fixture.planning.edit_items(case.state, {'schema_version':1,'domain_id':'commerce',
                'plan_sha256':case.row()['plan_sha256'],'request_reference':'synthetic://edit',
                'edits':[{'id':'req.orders','notes':'Keep the human rationale.'}]},case.run)
            summary=core_fixture.planning.public_summary(case.state)
            result=files(summary);tabs=workbook(result['inventory.xlsx']['content'])
            self.assertIn('Declared key',str(tabs['Columns'][0]))
            columns={r[3]:r for r in tabs['Columns'][0][1:] if r[2]=='orders'}
            self.assertEqual(columns['customers_id'][5],'FK')
            customer_column=next(r for r in tabs['Columns'][0][1:] if r[2]=='customers')
            self.assertEqual(customer_column[5],'PK')
            model_rows=[r for r in tabs['Inventory'][0][1:] if r[2]=='model']
            self.assertTrue(all(r[-1]=='create' for r in model_rows))
            root,text=document(result['migration-plan.docx']['content'])
            self.assertIn('Disposition',text);self.assertIn('create',text)
            self.assertEqual(len(tabs['Unmatched'][0])-1,3)
            self.assertIn(['columns','total','2'],[r[2:] for r in tabs['Coverage'][0][1:]])
            self.assertIn('Keep the human rationale.',str(tabs['Work items'][0]))
            self.assertIn('Consumer coverage: total',str(tabs['Summary'][0]))
            self.assertNotIn('synthetic://private/oracle',str(tabs))
        finally:case.doCleanups()

    def test_context_is_retained_without_inheriting_validation_results(self):
        sample=fixture(output='both');d=sample['domains'][0]
        d['migration_context']={'validation_status':'pass','definitions':[{'id':'net','name':'Net revenue','statement':'Completed orders only',
            'definition':{'population':'Completed orders','source_path':'PRIVATE_RAW_PATH'},'status':'proposed','model_ids':['orders']}],
            'consumer_crosswalk':[{'subject_kind':'chart','subject_id':'chart:net','dashboard_id':'dashboard.sales',
                'dashboard_label':'Sales','source_label':'Net revenue','model_ids':['orders'],'topic_ids':['orders'],'status':'pass'}]}
        result=files(sample);tabs=workbook(result['inventory.xlsx']['content'])
        self.assertIn('population: Completed orders',str(tabs['Definitions'][0]))
        self.assertIn('chart:net',str(tabs['Crosswalk'][0]))
        self.assertIn('not_revalidated',str(tabs['Crosswalk'][0]))
        self.assertNotIn('PRIVATE_RAW_PATH',str(tabs));self.assertNotIn('pass',str(tabs['Crosswalk'][0]))

    def test_asana_dates_headers_and_azure_thousand_row_batches(self):
        sample=fixture('asana');sample['domains'][0]['work_items'][1]['due_date']='2027-02-03'
        result=files(sample);rows=list(csv.DictReader(io.StringIO(result['imports/asana/create-001.csv']['content'].decode('utf-8-sig'))))
        self.assertEqual(list(rows[0]),['Name','Description','Section','Assignee','Collaborators','Start Date','Due Date'])
        self.assertEqual(rows[0]['Due Date'],'02/03/2027');self.assertEqual(rows[0]['Assignee'],'')
        sample=fixture('azure_devops',output='google');d=sample['domains'][0]
        base=d['work_items'][1];d['work_items']=[];d['waves']=[]
        for i in range(1001):
            item=copy.deepcopy(base);item['id']='work.%04d'%i;item['acceptance_criteria']=[]
            d['work_items'].append(item)
        result=files(sample)
        counts=[len(list(csv.DictReader(io.StringIO(result['imports/azure_devops/create-%03d.csv'%i]['content'].decode('utf-8-sig'))))) for i in (1,2)]
        self.assertEqual(counts,[1000,1])

    def test_ooxml_roundtrip_counts_headers_filters_snapshot_and_unicode(self):
        result=files(fixture());tabs=workbook(result['inventory.xlsx']['content'])
        self.assertEqual(len(tabs['Inventory'][0])-1,5)
        self.assertEqual(len(tabs['Columns'][0])-1,6)
        self.assertEqual(len(tabs['Work items'][0])-1,4)
        self.assertEqual(len(tabs['Acceptance'][0])-1,4)
        self.assertEqual(len(tabs['Dependencies'][0])-1,2)
        self.assertEqual(len(tabs['Consumers'][0])-1,1)
        self.assertEqual(len(tabs['Sources'][0])-1,2)
        for rows,root in tabs.values():
            self.assertEqual(rows[0][:2],['Snapshot ID','Domain'])
            self.assertEqual(root.find('s:sheetViews/s:sheetView/s:pane',S).get('state'),'frozen')
            self.assertIsNotNone(root.find('s:autoFilter',S))
            for row in rows[1:]:self.assertEqual(row[:2],['a'*64,'commerce'])
        self.assertIn('customers café 顧客',str(tabs['Inventory'][0]))
        self.assertEqual(tabs['Inventory'][0][0][-1],'Disposition')
        customer=next(r for r in tabs['Inventory'][0][1:] if r[2]=='model' and r[3]=='customers')
        self.assertEqual(customer[-1],'reuse')
        root,text=document(result['migration-plan.docx']['content'])
        joined='\n'.join(text)
        for value in ('a'*64,'customers café 顧客','many_to_one','orders.customer_id = customers.customer_id',' → ',
                      'work.first','work.second','work.update','EXISTING-17','Preserve my note','dashboard.unmapped'):
            self.assertIn(value,joined)
        self.assertGreater(len(root.findall('.//w:tbl',W)),4)
        self.assertGreater(len(root.findall('.//w:tblHeader',W)),4)

    def test_dependency_topological_order_and_many_to_many_preserved(self):
        result=files(fixture());tabs=workbook(result['inventory.xlsx']['content'])
        rows=tabs['Work items'][0];ids=[r[2] for r in rows[1:]]
        self.assertLess(ids.index('work.first'),ids.index('work.second'))
        self.assertLess(ids.index('work.second'),ids.index('work.update'))
        mapping=tabs['Mappings'][0][1]
        self.assertIn('legacy.orders; legacy.returns',mapping)
        self.assertIn('orders; refunds',mapping)
        edge_rows=tabs['Relationships'][0]
        self.assertEqual(len(edge_rows)-1,4)  # One declared relationship, two hub links, one supplied upstream edge.
        self.assertIn('split.order',str(edge_rows))
        self.assertNotIn('refunds.customer_id',str(edge_rows))

    def test_dangling_cycles_duplicate_ids_and_unknown_model_fail_closed(self):
        for mutation in (lambda d:d['work_items'][0].update(dependencies=['missing']),
                         lambda d:d['work_items'][1].update(dependencies=['work.second']),
                         lambda d:d['work_items'][1].update(id='work.second'),
                         lambda d:d['work_items'][0].update(model_ids=['private.model']),
                         lambda d:d['waves'][0].update(item_ids=['missing']),
                         lambda d:d['waves'][0].update(depends_on=['missing']),
                         lambda d:d['relationships'][0].update(to='missing')):
            sample=fixture();mutation(sample['domains'][0])
            with self.assertRaises(ValueError):exports.export_files(sample)

    def test_all_platforms_keep_create_and_update_separate_and_limitations_honest(self):
        for platform in sorted(exports.PLATFORMS):
            with self.subTest(platform=platform):
                result=files(fixture(platform));readme=result['README.md']['content'].decode()
                self.assertIn(exports.LIMITATIONS[platform],readme)
                self.assertIn('Update/review proposals never enter create imports',readme)
                self.assertIn('work.update',result['tickets.md']['content'].decode())
                follow=list(csv.DictReader(io.StringIO(result['imports/manual-follow-up.csv']['content'].decode('utf-8-sig'))))
                self.assertEqual({r['Planning ID'] for r in follow},{'work.second','work.update','work.review'})
                self.assertEqual(next(r for r in follow if r['Planning ID']=='work.update')['External ID'],'EXISTING-17')
                creates=[r for name,r in result.items() if 'create-' in name]
                if platform=='github':
                    self.assertEqual(len([n for n in result if n.startswith('imports/github/')]),2)
                else:
                    rows=list(csv.DictReader(io.StringIO(creates[0]['content'].decode('utf-8-sig'))))
                    self.assertEqual(len(rows),2)
                    self.assertIn('work.first',str(rows[0]));self.assertIn('work.second',str(rows[1]))
                    self.assertNotIn('work.update',str(rows))
                    if platform=='linear':
                        self.assertEqual(list(rows[0]),['Title','Description','Priority','Status','Assignee','Created','Completed','Labels','Estimate'])
                        self.assertTrue(all(rows[0][k]=='' for k in ('Priority','Status','Assignee','Created','Completed','Estimate')))
                    if platform=='azure_devops':
                        self.assertEqual(list(rows[0]),['Work Item Type','Title','Description'])
                    self.assertNotIn('Parent',rows[0])

    def test_csv_formula_protection_unicode_controls_and_markdown_escaping(self):
        sample=fixture('generic');d=sample['domains'][0]
        d['work_items'][1].update(title='  =HYPERLINK("bad")',outcome='[click](file:///private/secret) <script> & café\x00\ud800')
        d['work_items'][0]['title']='\t+SUM(1)'
        result=files(sample);rows=list(csv.DictReader(io.StringIO(result['imports/generic/create-001.csv']['content'].decode('utf-8-sig'))))
        self.assertEqual(rows[0]['Title'],'\'  =HYPERLINK("bad")')
        self.assertEqual(rows[1]['Title'],"'\t+SUM(1)")
        xlsx=workbook(result['inventory.xlsx']['content']);self.assertIn('  =HYPERLINK("bad")',str(xlsx['Work items'][0]))
        root,text=document(result['migration-plan.docx']['content'])
        self.assertIn('café\ufffd\ufffd',''.join(text))
        markdown=result['tickets.md']['content'].decode()
        self.assertNotIn('[click](file:',markdown);self.assertNotIn('<script>',markdown)
        self.assertIn('\\[click\\]',markdown)

    def test_google_only_has_typed_pending_payloads_no_fake_urls_or_fallback(self):
        result=files(fixture(output='google'))
        self.assertNotIn('inventory.xlsx',result);self.assertNotIn('migration-plan.docx',result)
        sheet=json.loads(result['cloud/sheet-content.json']['content']);doc=json.loads(result['cloud/document-content.json']['content'])
        for value in (sheet,doc):
            self.assertEqual(value['status'],'pending_host_creation');self.assertEqual(value['snapshot_id'],'a'*64)
            self.assertNotIn('url',value);self.assertEqual(value['provider'],'provider_neutral')
        self.assertTrue(all(c['type']=='string' for s in sheet['sheets'] for row in s['rows'] for c in row))
        self.assertTrue(any(b['type']=='relationship_diagram' for b in doc['blocks']))
        both=files(fixture(output='both'))
        self.assertTrue({'inventory.xlsx','migration-plan.docx','cloud/sheet-content.json','cloud/document-content.json'}<=both.keys())

    def test_private_unknown_keys_never_export_and_input_not_mutated(self):
        sample=fixture(output='both');d=sample['domains'][0]
        d.update(source_path='/Users/private/CREDENTIAL_MARKER',evidence_refs=['PRIVATE_REFERENCE'],private_query='RAW_SQL_MARKER')
        d['models'][0]['columns'][0]['source_path']='PRIVATE_COLUMN_MARKER'
        d['inventory']['mappings'][0]['evidence_refs']=['PRIVATE_EVIDENCE_MARKER']
        original=copy.deepcopy(sample);result=exports.export_files(sample)
        self.assertEqual(sample,original)
        for row in result:
            if row['path'].endswith(('.xlsx','.docx')):
                with zipfile.ZipFile(io.BytesIO(row['content'])) as z:body=b''.join(z.read(n) for n in z.namelist())
            else:body=row['content']
            for marker in (b'CREDENTIAL_MARKER',b'PRIVATE_REFERENCE',b'RAW_SQL_MARKER',b'PRIVATE_COLUMN_MARKER',b'PRIVATE_EVIDENCE_MARKER'):
                self.assertNotIn(marker,body)

    def test_deterministic_bytes_paths_zip_metadata_and_two_domains(self):
        sample=fixture();other=copy.deepcopy(sample['domains'][0]);other['domain_id']='sales:west';other['plan_sha256']='b'*64
        sample['domains'].append(other)
        first=exports.export_files(sample);second=exports.export_files(sample)
        self.assertEqual(first,second);self.assertEqual(len({x['path'] for x in first}),len(first))
        for row in first:
            self.assertEqual(set(row),{'path','content','media_type','domain_id'})
            self.assertTrue(row['path'].startswith('05_Migration/'));self.assertNotIn('..',row['path'])
            if row['path'].endswith(('.xlsx','.docx')):
                with zipfile.ZipFile(io.BytesIO(row['content'])) as z:
                    self.assertTrue(all(i.date_time==(2000,1,1,0,0,0) for i in z.infolist()))
                    for name in z.namelist():ET.fromstring(z.read(name))

    def test_stale_status_preserved_absent_plan_empty_and_unsafe_ids_rejected(self):
        sample=fixture();sample['domains'][0]['freshness']='stale'
        result=files(sample);self.assertIn('Freshness: stale',result['README.md']['content'].decode())
        self.assertEqual(exports.export_files({'schema_version':1,'domains':[]}),[])
        self.assertEqual(exports.export_files({'schema_version':1,'domains':[{'domain_id':'commerce','freshness':'unassessed','plan_sha256':None}]}),[])
        for identity in ('../escape','/private','<script>','=formula'):
            sample=fixture();sample['domains'][0]['domain_id']=identity
            with self.assertRaises(ValueError):exports.export_files(sample)
        sample=fixture();sample['domains'][0]['work_items'][2].pop('external_id')
        with self.assertRaisesRegex(ValueError,'external ID'):exports.export_files(sample)

    def test_no_relationships_means_no_invented_diagram(self):
        sample=fixture();d=sample['domains'][0];d['relationships']=[];d['graph_edges']=[];d['source_lineage']={}
        _,text=document(files(sample)['migration-plan.docx']['content'])
        self.assertIn('No relationship edges were supplied. No connections or cardinalities have been inferred.',text)


if __name__=='__main__':unittest.main()
