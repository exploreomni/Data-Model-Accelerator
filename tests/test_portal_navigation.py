"""Offline portal controls: synthetic DOM, not a substitute for browser rendering QA."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
from test_delivery_portal import fixture
import test_guided_review_workflow as guided_tests


@unittest.skipUnless(shutil.which('node'), 'Node required for offline script smoke checks')
class PortalNavigationTests(unittest.TestCase):
    def page(self, data, assertions, prefix='', second_boot=False):
        template=portal._html(data)
        stub=(Path(__file__).parent/'portal_dom_stub.js').read_text()
        script=(portal.ASSETS/'portal.js').read_text()
        # Assertions run in the initializer's lexical scope; production exposes no test API.
        body=script.rsplit('})();',1)[0]+assertions+'\n})();'
        source='const PAGE='+json.dumps(template)+';const PAYLOAD='+json.dumps(data)+';\n'+stub+'\n'+prefix+'\n'+body
        if second_boot:source+='\nconst listenersBefore=JSON.stringify(Object.fromEntries(Object.entries(listeners).map(([k,v])=>[k,v.length])));\n'+script+'\nassert.equal(JSON.stringify(Object.fromEntries(Object.entries(listeners).map(([k,v])=>[k,v.length]))),listenersBefore);'
        result=subprocess.run([shutil.which('node'),'-'],input=source,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def payload(self, include=('documentation','diagrams','dictionary','implementation'), audience='engineer'):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();state,review=fixture(root)
            review['models'][2]['name']='gold.'+'full_model_name_'*5
            review['models'][2]['disposition']='create'
            review['models'][1]['disposition']='reuse'
            review['changes']=[{'id':'r1','source':'legacy.sql','target':'models/gold.sql','disposition':'replace','rationale':'Canonical grain','consumers':[]}]
            path=root/'delivery.zip';portal.package_delivery(state,review,root,path,audience,include)
            import zipfile
            with zipfile.ZipFile(path) as archive:page=archive.read('START_HERE.html').decode()
            return json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])

    def test_first_click_deep_links_back_and_repeated_initialization(self):
        self.page(self.payload(),"""
for(const [anchor,parent]of Object.entries(sectionRoutes)){
 location.hash='#'+anchor;listeners.hashchange[0]();assert.equal(el(parent).hidden,false);assert.equal(el(parent==='model'?'delivery':'model').hidden,true);assert.equal(el(anchor).focused,true);assert.equal(el(anchor).scrolled,true);
 document.getElementById('nav:'+anchor).onclick();assert.equal(el(parent).hidden,false);
}
assert.equal(el('implementation-nav').hidden,false);
assert.match(el('file-content').textContent,/select 1 as id/);assert.match(el('implementation-state').textContent,/1 implementation files/);
assert.equal(el('replacement-table').children.length>0,true);
location.hash='#overview';listeners.hashchange[0]();assert.equal(el('overview').hidden,false);
""",second_boot=True)

    def test_authoring_observations_render_in_existing_validation_route(self):
        data = self.payload()
        data['workflow'] = guided_tests.workflow_view()
        self.page(data, """
location.hash='#validation';listeners.hashchange[0]();assert.equal(el('validation').hidden,false);
assert.equal(authoringChecks.length,1);assert.equal(authoringChecks[0].mode,'provisional');
assert.match(el('authoring-boundary').textContent,/do not prove native validity/);
assert.ok(el('authoring-checks').children.length);assert.ok(el('authoring-findings').children.length);
""")

    def test_independent_erd_lineage_controls_filters_and_export_selection(self):
        self.page(self.payload(),"""
const initial=[...chosen];assert.equal(graph.nodes.length,3);
el('architecture-model').value='silver.orders';el('architecture-model').onchange();
el('erd-dependencies').checked=true;el('erd-dependencies').onchange();
assert.equal(el('lineage-model').value,'');assert.equal(el('lineage-direction').value,'');
assert.deepEqual([...erdSelection.visible].sort(),['bronze.orders','gold.orders','silver.orders']);assert.equal(inspectedModel,'silver.orders');
assert.equal(lineageSelection.visible.size,3);
el('erd-clear').onclick();
el('lineage-clear').onclick();el('lineage-new').checked=true;el('lineage-new').onchange();assert.deepEqual([...lineageSelection.visible],['gold.orders']);
el('lineage-context').checked=true;el('lineage-context').onchange();assert.equal(lineageSelection.dependencies.size,2);
assert.deepEqual([...chosen],initial);assert.equal(shownViews.length,1);
assert.match(currentDiagram.svg,/full_model_name_/);assert(currentDiagram.svg.includes('<style>'));
assert.equal(el('diagram').querySelector('img')!==null,true); // DOMParser absent: known-generated image fallback.
el('diagram-zoom-in').onclick();assert.equal(el('diagram-zoom').textContent,'125%');el('diagram-zoom-reset').onclick();assert.equal(el('diagram-zoom').textContent,'100%');
""")

    def test_reviewer_omission_and_code_only_do_not_regenerate_diagrams(self):
        data=self.payload(('documentation',),'reviewer')
        self.assertNotIn('select 1 as id',json.dumps(data))
        self.page(data,"""
assert.equal(el('implementation-nav').hidden,false);assert.match(el('implementation-state').textContent,/excluded from reviewer/);
assert.equal(diagramEnabled,false);assert.equal(currentDiagram,null);assert.equal(graph.nodes.length,3);
""")
        self.page(self.payload(('implementation',)),"""
assert.equal(graph.nodes.length,0);assert.equal(diagramEnabled,false);assert.equal(currentDiagram,null);
assert.equal(el('file-content').textContent,'select 1 as id');
""")

    def test_inline_copy_full_name_and_clipboard_fallback(self):
        # This integration double exercises caller behavior; test_portal_svg owns the sanitizer.
        prefix="""
const PortalSvg={sanitize(text){const svg=new Node('svg');svg.setAttribute('width','1080');svg.setAttribute('height','900');for(const m of PAYLOAD.review.models){const group=new Node('g'),label=new Node('text');group.setAttribute('data-model-id',m.id);label.setAttribute('data-model-id',m.id);group.append(label);svg.append(group);}return svg;}};
let selectedRange;globalThis.getSelection=()=>({rangeCount:1,toString:()=> 'shortened',getRangeAt:()=>({intersectsNode:n=>n.getAttribute('data-model-id')==='gold.orders'})});
"""
        self.page(self.payload(),"""
assert(el('diagram').querySelector('svg'));let copied='';let prevented=false;
el('diagram').oncopy({clipboardData:{setData:(kind,value)=>{assert.equal(kind,'text/plain');copied=value;}},preventDefault:()=>prevented=true});
assert.equal(copied,graph.byId.get('gold.orders').full_name);assert.equal(prevented,true);
const label=el('diagram').querySelector('svg').children[2];label.onclick();
assert.equal(inspectedModel,'gold.orders');assert.equal(label.getAttribute('role'),'button');
label.onkeydown({key:'Enter',preventDefault(){}});assert.equal(inspectedModel,'gold.orders');
const input=el('diagram-copy').children[1];assert.equal(input.value,copied);
copyText(input.value,input,'Copied').then(()=>{assert.equal(input.selected,true);assert.match(el('messages').textContent,/normal Copy shortcut/);});
""",prefix)

    def test_every_emitted_script_smokes_and_subset_reopens_with_exact_inventory(self):
        import portal_checks
        data=self.payload()
        page=portal._html(data)
        stub=(Path(__file__).parent/'portal_dom_stub.js').read_text()
        prelude='const PAGE='+json.dumps(page)+';const PAYLOAD='+json.dumps(data)+';\n'+stub
        result=portal_checks.check_javascript(page,prelude=prelude,
            assertions="assert.equal(document.getElementById('implementation-nav').hidden,false);assert.equal(document.getElementById('file-content').textContent,'select 1 as id');")
        self.assertEqual(result['scripts'],2)
        self.assertTrue(result['smoke'])
        with tempfile.TemporaryDirectory() as tmp:
            destination=Path(tmp).resolve()/'subset.zip'
            self.page(data,"""
let writeExport;
download=(name,body)=>{writeExport=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.clear();chosen.add('documentation');updateExport();
el('download-package').onclick().then(()=>writeExport).then(()=>{assert.match(el('messages').textContent,/Candidate subset created/);}).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT',json.dumps(str(destination))))
            self.assertTrue(destination.exists())
            self.assertEqual(portal.verify_delivery(destination)['status'],'integrity_verified')
            import zipfile
            with zipfile.ZipFile(destination) as archive:
                reduced=archive.read('START_HERE.html').decode()
            self.assertEqual(portal_checks.check_javascript(reduced)['scripts'],2)
            selected=portal_checks.parse_page(reduced)[1]
            self.assertEqual(selected['file_count'],1)
            self.assertEqual(selected['selected_categories'],['documentation'])
            self.assertNotIn('select 1 as id',reduced)
            self.page(selected,"assert.equal(files.length,1);assert.equal(currentDiagram,null);assert.equal(el('implementation-nav').hidden,false);")

    def test_layout_contract_covers_shared_sections_and_both_breakpoints(self):
        css=(portal.ASSETS/'portal.css').read_text()
        self.assertIn('html{font-size:18px}',css)
        self.assertIn('body{margin:0',css)
        self.assertIn('font:18px/1.55',css)
        self.assertIn('main{margin-left:var(--sidebar-width)',css)
        for width in (1000,700):
            self.assertIn('@media(max-width:'+str(width)+'px){.review-section',css)
        for identifier in ('architecture','lineage','implementation-code','replacement-map'):
            self.assertNotIn('#'+identifier+'{',css)
        self.page(self.payload(),"""
const sidebar=document.querySelector('.sidebar'); // The stub inventories ID controls only.
const simulatedSidebar={getBoundingClientRect:()=>({right:250})};document.querySelector=()=>simulatedSidebar;
globalThis.getComputedStyle=()=>({position:'fixed'});
const section=el('lineage');section.getClientRects=()=>[{}];section.getBoundingClientRect=()=>({left:240});
const originalQuery=document.querySelectorAll;document.querySelectorAll=q=>q==='.review-section'?[section]:originalQuery(q);
assert.throws(assertPortalLayout,/lineage overlaps the fixed sidebar/);
section.getBoundingClientRect=()=>({left:270});assert.doesNotThrow(assertPortalLayout);
globalThis.getComputedStyle=()=>({position:'static'});section.getBoundingClientRect=()=>({left:0});assert.doesNotThrow(assertPortalLayout);
""")

    def test_graph_cycles_direction_namespaces_pagination_and_no_join_inference(self):
        guided_tests.GuidedReviewBrowserHelpersTests.run_js(self,"""
const graph=modelGraph([{id:'a',layer:'bronze',name:'Alpha',disposition:'create',depends_on:['b']},{id:'b',layer:'silver',depends_on:['a']},{id:'c',layer:'gold',disposition:'replace'}],[{from:'b',to:'c',kind:'relationship'}],{evidence_state:'selected',views:{a:{},isolated:{}},dependencies:[]});
assert.deepEqual([...selectLineage(graph,{focus:'a',direction:'downstream'}).visible].sort(),['a','b']);
assert.equal(graph.nodes.length,5);assert.equal(graph.nodes.slice(0,3).every(n=>n.object_kind==='warehouse'),true);
assert.equal(selectLineage(graph,{newOnly:true}).visible.size,1);
assert.equal(selectLineage(graph,{search:'Alpha'}).visible.has('a'),true);
assert.equal(selectLineage(graph,{layer:'semantic'}).visible.size,2);
assert.equal(modelGraph([],[{from:'missing',to:'also-missing',kind:'lineage'}]).unresolved,1);
assert.equal(modelGraph([],[],{evidence_state:'not_included',views:{private:{}}}).nodes.length,0);
const invalid=modelGraph([],[],{evidence_state:'selected',views:{events:{}},dependencies:[{from:'events',to:'absent_view',kind:'declared_join'}]});
assert.equal(invalid.nodes.length,1);assert.equal(invalid.unresolved,1);assert.equal(invalid.byId.has('omni:absent_view'),false);
const competing=modelGraph([{id:'a',layer:'gold'},{id:'b',layer:'gold'}],[{from:'a',to:'b',kind:'relationship',status:'authored',cardinality:'many_to_one'},{from:'a',to:'b',kind:'relationship',status:'proposed',cardinality:'one_to_many'}]);
assert.equal(selectLineage(competing,{joins:true}).edges.length,2);
const partitions=graphPages(selectLineage(competing,{joins:true}),36,[{label:'Customer domain',model_ids:['b']},{label:'Order domain',model_ids:['a']}]);
assert.match(partitions[0].label,/Customer domain/);assert.deepEqual(partitions[0].model_ids,['b']);assert.equal(partitions[0].cross_view_connections,2);
assert.deepEqual(partitions[1].model_ids,['a']);
const keySvg=filteredModelSvg([{id:'keys',layer:'gold',columns:[{name:'description'},{name:'amount'},{name:'created'},{name:'updated'},{name:'critical_identity',key:'PK',type:'NUMBER'}]}],[]);
assert.match(keySvg,/PK critical_identity/);



const nodes=Array.from({length:1000},(_,i)=>({id:'m'+i,name:'Model '+i,layer:'gold',depends_on:i?['m'+(i-1)]:[]}));
const large=modelGraph(nodes,[]),selected=selectLineage(large,{focus:'m999',direction:'upstream'}),pages=graphPages(selected);
assert.equal(selected.visible.size,1000);assert.equal(pages.length,28);assert.equal(pages.reduce((n,p)=>n+p.model_ids.length,0),1000);assert(pages[0].cross_view_connections>0);
""")

if __name__=='__main__':unittest.main()
