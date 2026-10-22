"""Readable package paths preserve immutable artifacts and older delivery exports."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
from package_layout import SECTIONS
from test_delivery_portal import fixture
import test_portal_navigation as navigation


class ReadableHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.state, self.review = fixture(self.root)
        self.review['package_layout_version'] = 2

    def package(self, include=None):
        path = self.root / 'simple.zip'
        portal.package_delivery(self.state, self.review, self.root, path, 'engineer',
                                include or ['documentation', 'diagrams', 'dictionary', 'implementation'])
        with zipfile.ZipFile(path) as z:
            files = {name: z.read(name) for name in z.namelist()}
        data = json.loads(files['START_HERE.html'].decode().split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        return path, files, data

    def test_five_plain_folders_and_code_bytes_preserved(self):
        path, files, data = self.package()
        self.assertEqual({name.split('/')[0] for name in files if '/' in name}, {r[0] for r in SECTIONS.values()})
        self.assertEqual(files['04_Code_Generation/models/gold.sql'], (self.root/'models/gold.sql').read_bytes())
        self.assertNotIn('SENSITIVE_RAW_MARKER', files['START_HERE.html'].decode())
        self.assertNotIn('INTERNAL_AUDIT_MARKER', files['START_HERE.html'].decode())
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')
        self.assertLess(len(files['README.md']), 2500)
        self.assertEqual(data['package_layout_version'], 2)

    def test_absent_code_is_explained_without_counting_as_implementation(self):
        _, files, data = self.package(['documentation', 'diagrams', 'dictionary'])
        self.assertIn(b'No files are included', files['04_Code_Generation/README.md'])
        self.assertFalse(any(f['category'] == 'implementation' for f in data['files'] + data['generated_deliverables']))

    def test_context_section_is_explicit_and_does_not_rewrite_content(self):
        self.review['artifacts'][0]['section'] = 'input_context'
        _, files, _ = self.package()
        self.assertEqual(files['02_Input_Context_Files/docs/model.md'], b'Model documentation')
        self.assertNotIn('03_Design_Documents/docs/model.md', files)

    def test_section_cannot_relabel_code_as_an_input(self):
        self.review['artifacts'][1]['section'] = 'input_sources'
        with self.assertRaisesRegex(ValueError, 'section is incompatible'):
            self.package()

    def test_classic_delivery_paths_remain_supported(self):
        self.review.pop('package_layout_version')
        path, files, data = self.package()
        self.assertIn('02_Implementation/models/gold.sql', files)
        self.assertEqual(data['package_layout_version'], 1)
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    def test_input_and_mapping_links_work_on_first_click(self):
        _, _, data = self.package()
        harness = navigation.PortalNavigationTests('test_first_click_deep_links_back_and_repeated_initialization')
        harness.page(data, """
location.hash='#input-files';navigate();assert.equal(el('input-files').hidden,false);
assert.ok(el('input-file-index').children.length);
location.hash='#replacement-map';navigate();assert.equal(el('delivery').hidden,false);
assert.equal(el('replacement-map').focused,true);
assert.equal(el('deliverable-index').children.length>0,true);
rebuildGenerated(structuredClone(data)).then(rows=>{
 const actual=rows.filter(r=>r.id.startsWith('generated:section:'));
 for(const row of actual)assert.equal(row.base64,data.generated_deliverables.find(f=>f.id===row.id).base64);
}).catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_pipeline_subset_without_dictionary_stays_top_down_and_reopens(self):
        import base64
        _, _, data = self.package()
        self.assertEqual(data['diagram_view_mode'], 'pipelines')
        self.assertEqual([v['target_model_id'] for v in data['diagrams']], ['gold.orders'])
        body = base64.b64decode(data['diagrams'][0]['base64']).decode()
        self.assertIn('Gold output', body)
        self.assertIn('PK: id', body)
        destination = self.root / 'subset.zip'
        harness = navigation.PortalNavigationTests('test_first_click_deep_links_back_and_repeated_initialization')
        harness.page(data, """
let writeExport;
download=(name,body)=>{writeExport=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.delete('dictionary');updateExport();
el('download-package').onclick().then(()=>writeExport).then(()=>{assert.match(el('messages').textContent,/Candidate subset created/);}).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT', json.dumps(str(destination))))
        self.assertEqual(portal.verify_delivery(destination)['status'], 'integrity_verified')
        with zipfile.ZipFile(destination) as archive:
            html = archive.read('START_HERE.html').decode()
        next_data = json.loads(html.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        self.assertNotIn('columns', next_data['review']['models'][0])
        svg = base64.b64decode(next_data['diagrams'][0]['base64']).decode()
        self.assertNotIn('PK: id', svg)
        self.assertIn('Gold output', svg)
        harness.page(next_data, "assert.equal(pipelineMode,true);assert.equal(shownViews.length,1);assert.match(currentDiagram.svg,/Gold output/);")

    def test_semantic_views_require_selected_evidence_and_exact_bindings(self):
        import copy
        review = copy.deepcopy(self.review)
        review['omni_warehouse_bindings'] = [{'view_id':'orders', 'model_ids':['gold.orders']}]
        with self.assertRaisesRegex(ValueError, 'pinned semantic evidence'):
            portal.validate_review(self.state, review)
        review['omni'] = {'evidence_state':'selected', 'views':{'orders':{}},
                          'topics':[{'id':'sales','label':'Sales','scope':{'views':['orders']}}]}
        data = {'review':review}
        portal._review_diagrams(data, pipelines=True)
        view = data['diagrams'][0]
        self.assertEqual(len(view['semantic_ids']), 2)
        self.assertEqual(data['warehouse_diagrams'][0]['semantic_ids'], [])
        self.assertNotEqual(view['base64'], data['warehouse_diagrams'][0]['base64'])
        review['omni']['evidence_state']='not_included'
        portal._review_diagrams(data, pipelines=True)
        self.assertEqual(data['diagrams'][0]['semantic_ids'], [])
        self.assertNotIn('omni_warehouse_bindings', data['review'])

    def test_shared_ancestors_repeat_but_each_gold_has_a_pipeline(self):
        import copy
        from portal_checks import diagram_coverage
        gold = copy.deepcopy(self.review['models'][-1])
        gold.update(id='gold.customers', name='gold.customers')
        self.review['models'].append(gold)
        self.review['relationships'].append({'from':'silver.orders','to':'gold.customers','kind':'lineage'})
        _, _, data = self.package()
        self.assertEqual(data['diagram_coverage']['generated']['model_count'], 4)
        self.assertEqual(len(data['diagrams']), 2)
        self.assertTrue(all('silver.orders' in row['model_ids'] for row in data['diagrams']))
        broken=copy.deepcopy(data)
        broken['diagrams'].pop()
        with self.assertRaisesRegex(ValueError, 'cover every|primary pipeline'):
            diagram_coverage(broken)

    def domain_package(self):
        import copy
        self.review['models'][0]['domain']='platform'
        self.review['models'][1]['domain']='platform'
        self.review['models'][2]['domain']='sales'
        for identifier,domain in [('gold.revenue','finance'),('gold.unknown',None)]:
            model=copy.deepcopy(self.review['models'][2])
            model.update(id=identifier,name=identifier)
            if domain:model['domain']=domain
            else:model.pop('domain',None)
            self.review['models'].append(model)
            self.review['relationships'].append({'from':'silver.orders','to':identifier,'kind':'lineage'})
        self.review['models'].append({'id':'raw.support','name':'raw.support','layer':'bronze','domain':'support'})
        return self.package()

    def test_pipeline_domain_filter_groups_outputs_preserves_dependencies_and_resets(self):
        _,_,data=self.domain_package()
        navigation.PortalNavigationTests().page(data,"""
const original=JSON.stringify(data),selectedCategories=[...chosen];
assert.equal(shownViews.length,4);assert.equal(el('pipeline-domain-controls').hidden,false);
assert.deepEqual(el('diagram-view').children.map(group=>group.getAttribute('label')).sort(),['Unassigned','finance','sales','support'].sort());
assert.ok(!el('pipeline-domain').children.some(option=>option.value==='domain:platform'));
el('pipeline-domain').value='domain:sales';el('pipeline-domain').onchange();
assert.equal(shownViews.length,1);assert.equal(currentDiagram.target_model_id,'gold.orders');
assert.deepEqual(currentDiagram.model_ids.slice().sort(),['bronze.orders','gold.orders','silver.orders']);
assert.match(currentDiagram.svg,/bronze.orders/);assert.match(el('pipeline-domain-summary').textContent,/1 gold pipelines/);
assert.equal(el('diagram-download-all').textContent,'Download domain pipelines');
el('pipeline-domain').value='domain:finance';el('pipeline-domain').onchange();
assert.equal(currentDiagram.target_model_id,'gold.revenue');
el('pipeline-domain').value='';el('pipeline-domain').onchange();
assert.equal(shownViews.length,4);assert.equal(currentDiagram.target_model_id,'gold.revenue');
el('pipeline-domain').value='unassigned';el('pipeline-domain').onchange();
assert.equal(shownViews.length,1);assert.equal(currentDiagram.target_model_id,'gold.unknown');
el('pipeline-domain').value='domain:support';el('pipeline-domain').onchange();
assert.equal(shownViews.length,1);assert.equal(currentDiagram.target_model_id,null);
assert.match(el('pipeline-domain-summary').textContent,/0 gold pipelines · 1 supporting views/);
el('pipeline-domain').value='domain:missing';el('pipeline-domain').onchange();
assert.equal(currentDiagram,null);assert.equal(el('diagram-download-all').disabled,true);
assert.match(el('diagram-coverage').textContent,/domain and asset filters/);
assetId='limited';selection.visible=new Set(['bronze.orders','silver.orders','gold.orders']);
el('pipeline-domain').value='domain:finance';el('pipeline-domain').onchange();
assert.equal(shownViews.length,0);
el('pipeline-domain').value='domain:sales';el('pipeline-domain').onchange();
assert.equal(shownViews.length,1);assert.equal(currentDiagram.target_model_id,'gold.orders');
assetId='';
el('diagram-mode').value='relationships';el('diagram-mode').onchange();
assert.equal(el('pipeline-domain-controls').hidden,true);assert.ok(shownViews.length);
assert.equal(JSON.stringify(data),original);assert.deepEqual([...chosen],selectedCategories);
""")

    def test_domain_pipeline_download_is_scoped_but_package_export_keeps_all_domains(self):
        _,_,data=self.domain_package()
        destination=self.root/'domain-pipelines.zip'
        full=self.root/'full-package.zip'
        navigation.PortalNavigationTests().page(data,"""
el('pipeline-domain').value='domain:sales';el('pipeline-domain').onchange();
let domainWrite;
download=(name,body)=>{assert.equal(name,'domain-pipelines.zip');domainWrite=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(DOMAIN_ZIP,Buffer.from(buffer)));};
el('diagram-download-all').onclick();
assert.match(el('messages').textContent,/Exported the visible pipeline set/);
domainWrite.then(()=>{
let writeExport;
download=(name,body)=>{writeExport=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(FULL_ZIP,Buffer.from(buffer)));};
return el('download-package').onclick().then(()=>writeExport);
}).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('DOMAIN_ZIP',json.dumps(str(destination))).replace('FULL_ZIP',json.dumps(str(full))))
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(len(archive.namelist()),1)
            svg=archive.read(archive.namelist()[0]).decode()
            self.assertIn('gold.orders',svg)
            self.assertIn('bronze.orders',svg)
            self.assertNotIn('gold.revenue',svg)
        self.assertEqual(portal.verify_delivery(full)['status'],'integrity_verified')
        with zipfile.ZipFile(full) as archive:
            from portal_checks import parse_page
            exported=parse_page(archive.read('START_HERE.html').decode())[1]
        self.assertEqual(exported['review']['models'],data['review']['models'])
        self.assertEqual(len(exported['diagrams']),4)

    def test_compact_payload_keeps_columns_and_relationships_without_changing_state(self):
        import copy
        import csv
        import io
        self.state['readiness']['platform']={'findings':[{'id':'review','paths':['input-'+str(i)+'.sql' for i in range(120)]}],
                                            'coverage':{'gaps':[{'path':str(i),'reason':'unreviewed'} for i in range(150)]}}
        before=copy.deepcopy(self.state)
        _, files, data=self.package()
        self.assertEqual(self.state,before)
        source=json.loads(files['03_Design_Documents/ERD/model-source.json'])
        self.assertEqual(source['models'],self.review['models'])
        self.assertEqual(source['relationships'],self.review['relationships'])
        rows=list(csv.reader(io.StringIO(files['03_Design_Documents/Dictionary/data-dictionary.csv'].decode())))
        self.assertEqual(len(rows)-1, sum(len(m['columns']) for m in self.review['models']))
        self.assertIn(b'[data-dictionary.csv](data-dictionary.csv)',files['03_Design_Documents/Dictionary/data-dictionary.md'])
        platform=data['engagement']['readiness']['platform']
        self.assertEqual(platform['findings'][0]['paths_total'],120)
        self.assertEqual(len(platform['findings'][0]['paths']),20)
        self.assertEqual(platform['coverage']['gaps_total'],150)
        self.assertEqual(len(platform['coverage']['gaps']),100)
