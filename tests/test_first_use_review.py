"""First-use task paths and version-bound feedback; no warehouse claims."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import test_model_workspace as workspace
import delivery_portal as portal
import portal_checks
import review_feedback


class FirstUseReviewTests(unittest.TestCase):
    page = workspace.ModelWorkspaceTests.page
    payload = workspace.ModelWorkspaceTests.payload

    def test_first_open_retains_context_and_all_tables_are_visible_in_picker(self):
        self.page(self.payload(), """
assert(!el('model').scrolled);assert.equal(el('table-navigator').children.length,5);
assert.match(el('review-now').textContent,/5 tables/);
assert.match(el('review-pending').textContent,/not established/);
assert.match(el('file-title').textContent,/dim_customer.sql/);assert(!el('file-title').textContent.endsWith('gold.sql'));
assert(!el('table-more').hidden===false);
""",prefix="location.hash='';")

    def test_drawer_feedback_code_and_return_keep_selection(self):
        self.page(self.payload(), """
globalThis.innerWidth=707;el('table-navigator').children[3].onclick();
assert.equal(el('table-inspector').getAttribute('role'),'dialog');const id=inspectedModel;
el('inspector-open-code').onclick();assert.equal(activeFile.id,'code-'+id);
assert.equal(el('table-inspector').getAttribute('role'),null);
revealModel(id);el('inspector-feedback').onclick();assert.equal(el('feedback-model').value,id);
assert.equal(location.hash,'review-feedback');location.hash='#review-feedback';navigate();assert.equal(el('review-feedback').hidden,false);
assert.equal(inspectedModel,id);
""")

    def test_fit_expand_manual_zoom_and_narrow_controls(self):
        self.page(self.payload(), """
el('diagram').clientWidth=400;globalThis.innerHeight=700;el('diagram-fit').onclick();
assert(diagramZoom>0&&diagramZoom<1);assert.equal(diagramFitMode,true);
el('diagram-zoom-reset').onclick();assert.equal(diagramZoom,1);assert.equal(diagramFitMode,false);
el('diagram-expand').onclick();assert.equal(el('diagram-expand').getAttribute('aria-expanded'),'true');
el('diagram-expand').onclick();assert.equal(el('diagram-expand').getAttribute('aria-expanded'),'false');
""")

    def test_feedback_download_verifies_and_stale_unknown_or_approval_requests_fail(self):
        data = self.payload()
        page = portal._html(data)
        parsed, _ = portal_checks.parse_page(page)
        raw = next(s['source'] for s in parsed.scripts if s['attrs'].get('id') == 'delivery-data')
        response = {'schema_version': 1, 'kind': 'model_review_feedback', 'request_only': True,
                    'engagement_id': data['engagement']['engagement_id'],
                    'context_sha256': data['engagement']['context_sha256'],
                    'page_data_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                    'comments': [{'model_id': 'fact_sales', 'type': 'question', 'text': 'Confirm the grain.'}]}
        self.assertEqual(review_feedback.verify_feedback(page, response)['status'], 'current_feedback_request')
        for key, value in [('page_data_sha256', '0'*64), ('context_sha256', '1'*64), ('request_only', False), ('approved', True)]:
            changed = dict(response, **{key: value})
            with self.assertRaises(ValueError): review_feedback.verify_feedback(page, changed)
        for comment in ({'model_id': 'absent', 'type': 'question', 'text': 'a'},
                        {'model_id': None, 'type': 'approve', 'text': 'a'},
                        {'model_id': None, 'type': 'question', 'text': ''}):
            with self.assertRaises(ValueError): review_feedback.verify_feedback(page, dict(response, comments=[comment]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'feedback.json'
            self.page(data, """
download=(name,body)=>{assert.equal(name,'model-review-feedback.json');require('node:fs').writeFileSync(OUTPUT,body);};
el('feedback-model').value='fact_sales';el('feedback-text').value='Confirm the grain.';
el('save-feedback').onclick().then(()=>assert.match(el('feedback-result').textContent,/Nothing has been approved/));
""".replace('OUTPUT', json.dumps(str(path))), prefix="document.getElementById('delivery-data').textContent="+json.dumps(raw)+";")
            self.assertEqual(review_feedback.verify_feedback(page,json.loads(path.read_text()))['status'],'current_feedback_request')

    def test_scope_evidence_remains_accessible_without_dashboard_noise(self):
        data=self.payload();data['engagement']['delivery_assurance']={'migration_scope':'model_only','checks':[{'lane':'warehouse_execution','status':'failed'}]}
        self.page(data,"""
const textOf=node=>[node.textContent,...(node.children||[]).map(textOf)].join(' ');
assert(!textOf(el('assurance-checks')).includes('Dashboard draft'));
assert(textOf(el('assurance-excluded')).includes('Dashboard draft'));
assert(textOf(el('assurance-checks')).includes('failed'));
""")


    def test_multi_file_inspector_uses_current_file_and_empty_selection_disables_action(self):
        data=self.payload()
        data['review']['models'][0]['artifact_ids']=['code-fact_sales']
        self.page(data, """
inspectModel('dim_customer');el('inspect-code-file').value='code-fact_sales';el('inspect-code-file').onchange();
el('inspector-open-code').onclick();assert.equal(activeFile.id,'code-fact_sales');
inspectModel('');assert.equal(el('inspector-open-code').disabled,true);assert.equal(inspectorFile,null);
""")

    def test_generated_only_package_is_not_mislabeled_and_roundtrip_preserves_dictionary(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();state,review=workspace.workspace_fixture(root)
            review['models'][0]['name']=None;review['models'][0]['columns'][0]['key']=True
            path=root/'original.zip'
            portal.package_delivery(state,review,root,path,'reviewer',['dictionary'])
            with zipfile.ZipFile(path) as archive: data=portal_checks.parse_page(archive.read('START_HERE.html'))[1]
            output=root/'subset.zip'
            self.page(data,"""
assert(!el('implementation-state').textContent.includes('status page'));
assert.match(el('implementation-state').textContent,/reviewer/);assert.equal(el('download-package').disabled,false);
let saved;download=(name,body)=>{saved=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
el('download-package').onclick().then(()=>saved).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT',json.dumps(str(output))))
            self.assertEqual(portal.verify_delivery(output)['status'],'integrity_verified')
            with zipfile.ZipFile(path) as original,zipfile.ZipFile(output) as subset:
                for name in ('data-dictionary.csv','data-dictionary.md'):
                    self.assertEqual(original.read('01_Model/Dictionary/'+name),subset.read('01_Model/Dictionary/'+name))

    def test_svg_file_opens_as_diagram_with_source_toggle_and_exact_download(self):
        self.page(self.payload(), """
const file=allFiles().find(f=>f.path.endsWith('.svg'));showFile(file);
assert.equal(el('file-preview').hidden,false);assert.equal(el('file-code-block').hidden,true);
assert(el('file-preview').querySelector('svg'));assert.equal(el('file-preview-controls').hidden,false);
assert.equal(el('file-content').textContent,new TextDecoder().decode(bytes(file.base64)));
el('file-preview').clientWidth=400;el('file-preview-fit').onclick();
assert(parseFloat(el('file-preview').querySelector('svg').style.width)<1080);
el('file-preview-actual').onclick();assert.equal(el('file-preview').querySelector('svg').style.width,'1080px');
el('file-preview-mode').onclick();assert.equal(el('file-preview').hidden,true);assert.equal(el('file-code-block').hidden,false);
el('file-preview-mode').onclick();assert.equal(el('file-preview').hidden,false);
let saved;download=(name,body)=>saved=body;el('download-file').onclick();assert.deepEqual(saved,bytes(file.base64));
el('copy-code').onclick();assert.equal(el('file-code-block').hidden,false);assert.equal(el('file-preview').hidden,true);
showFile(files.find(f=>f.category==='implementation'));assert.equal(el('file-preview').hidden,true);
assert.equal(el('file-preview-controls').hidden,true);assert.equal(el('file-code-block').hidden,false);
assert.equal(el('table-navigator').children[0].getAttribute('aria-pressed'),null);
assert.equal(el('table-navigator').children[0].getAttribute('aria-current'),'true');
""", prefix="""
const PortalSvg={sanitize(source){const svg=new Node('svg');svg.setAttribute('width','1080');svg.setAttribute('height','900');return svg;}};
""")

    def test_dictionary_index_opens_visible_formatted_table_and_preserves_source(self):
        self.page(self.payload(), """
const file=allFiles().find(f=>f.path.endsWith('data-dictionary.md'));openArtifact(file.id);
assert.equal(location.hash,'#implementation-code');assert.equal(el('implementation-code').scrolled,true);
assert.equal(el('delivery').hidden,false);assert.equal(el('file-preview').hidden,false);
assert.equal(el('file-code-block').hidden,true);assert(el('file-preview').querySelector('table'));
assert.equal(el('file-preview-fit').hidden,true);assert.equal(el('file-preview-actual').hidden,true);
const textOf=node=>[node.textContent,...(node.children||[]).map(textOf)].join(' ');
assert.match(textOf(el('file-preview')),/fact_sales|FACT_SALES/);assert.match(textOf(el('file-preview')),/1–14 of 14/);
el('file-preview-mode').onclick();assert.equal(el('file-code-block').hidden,false);
assert.equal(el('file-content').textContent,new TextDecoder().decode(bytes(file.base64)));
assert.equal(el('file-preview-mode').textContent,'Preview dictionary');
el('implementation-code').scrolled=false;openArtifact(file.id);assert.equal(el('implementation-code').scrolled,true);
""")

    def test_svg_fallback_is_limited_to_verified_generated_projections(self):
        self.page(self.payload(), """
const file=allFiles().find(f=>f.path.endsWith('.svg'));showFile(file);
assert(el('file-preview').querySelector('img'));assert.equal(el('file-preview').hidden,false);
showFile({...file,origin:undefined,base64:btoa('<svg onload="bad()"><script>bad()</script></svg>')});
assert.equal(el('file-preview').hidden,true);assert.equal(el('file-preview').children.length,0);
assert.match(el('file-note').textContent,/shown safely as text/);
assert.match(el('file-content').textContent,/<script>/);
""")

    def test_large_disconnected_model_list_is_searchable_with_complete_page_coverage(self):
        data=self.payload();data['review']['models']=[{'id':'model_'+str(i),'name':'DOMAIN.TABLE_'+str(i),
            'layer':('bronze','silver','gold')[i%3],'domain':'domain_'+str(i%5),'grain':'One declared record',
            'columns':[{'name':'id','type':'NUMBER','key':'PK'}]} for i in range(240)]
        data['review']['relationships']=[]
        data['diagrams']=portal.diagram_views(data['review']['models'],[]);portal._set_diagram_coverage(data)
        self.page(data,"""
assert.equal(el('table-navigator').children.length,50);assert.equal(el('table-more').hidden,false);
assert.equal(new Set(shownViews.flatMap(v=>v.model_ids)).size,240);
el('table-search').value='TABLE_239';el('table-search').oninput();assert.equal(el('table-navigator').children.length,1);
el('table-navigator').children[0].onclick();assert.equal(inspectedModel,'model_239');
assert.equal(chosen.has('diagrams'),true);
""")


if __name__=='__main__': unittest.main()
