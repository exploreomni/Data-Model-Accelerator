"""Stage review, response transport and asset exploration are not authority gates."""
import base64
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
from test_delivery_portal import fixture


def workflow_view():
    return {'schema_version': 1, 'engagement_id': 'synthetic-pilot', 'design_id': 'design-1',
            'design_revision': 2, 'design_sha256': 'a' * 64, 'current_stage': 'design',
            'next_action': 'Review the proposed grain.',
            'stages': [{'id': 'design', 'status': 'needs_review', 'label': 'Design',
                        'approval_receipt': 'PRIVATE_APPROVAL_MARKER'}],
            'decisions': [{'id': 'grain', 'question': 'Which grain is required?',
                           'status': 'open', 'recommendation': 'One row per order.',
                           'reviewer_role': 'Domain owner', 'model_ids': ['gold.orders'],
                           'blocking_stages': ['implementation'],
                           'options': [{'id': 'orders', 'label': 'Order', 'private': 'PRIVATE_OPTION_MARKER'}],
                           'evidence_payload': 'PRIVATE_EVIDENCE_MARKER'}],
            'effort': {'category': 'somewhat_easy', 'confidence': 'medium', 'readiness': 'blocked',
                       'breadth': 'Three entities', 'assumptions': ['Definitions will be reviewed.'],
                       'summary': 'A bounded model with an unresolved population decision.',
                       'work_packages': [{'id': 'orders', 'category': 'easy',
                                          'raw_observations': 'PRIVATE_PACKAGE_MARKER'}],
                       'internal_prompt': 'PRIVATE_PROMPT_MARKER'},
            'models': [{'id': 'gold.orders', 'name': 'Orders', 'layer': 'gold', 'grain': 'One row per order',
                        'asset_ids': ['report'], 'columns': [{'name': 'order_id', 'type': 'NUMBER'}],
                        'sql': 'PRIVATE_SQL_MARKER'}],
            'assets': [{'id': 'report', 'name': 'Order report', 'kind': 'report', 'mapping_status': 'verified',
                        'raw': 'PRIVATE_ASSET_MARKER'}], 'relationships': [],
            'runner': {'secret': 'PRIVATE_RUNNER_MARKER'}}


class GuidedReviewProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state, self.review = fixture(self.root)
        self.state['workflow'] = {'design': {'id': 'design-1', 'revision': 2, 'sha256': 'a' * 64}}
        self.review['design_binding'] = copy.deepcopy(self.state['workflow']['design'])
        self.module = types.SimpleNamespace(public_view=lambda state: workflow_view())

    def payload(self, path):
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive: page = archive.read('START_HERE.html').decode()
        else: page = path.read_text()
        return json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])

    def test_design_status_renders_before_code_exists_and_allowlists_state(self):
        path = self.root / 'START_HERE.html'
        with patch.dict(sys.modules, {'engagement_stages': self.module}):
            portal.render_engagement(self.state, path)
        data = self.payload(path)
        self.assertEqual(data['workflow']['current_stage'], 'design')
        self.assertEqual(data['review']['models'][0]['id'], 'gold.orders')
        self.assertEqual(data['review']['assets'][0]['id'], 'report')
        self.assertEqual(data['files'], [])
        self.assertEqual(len(data['diagrams']), 1)
        self.assertNotIn('PRIVATE_', path.read_text())
        self.assertNotIn('approval_receipt', data['workflow']['stages'][0])

    def test_code_only_and_audit_exports_do_not_retain_design_prose(self):
        for audience, include in [('engineer', ['implementation']), ('audit', ['technical_audit'])]:
            with self.subTest(audience=audience):
                path = self.root / (audience + '.zip')
                with patch.dict(sys.modules, {'engagement_stages': self.module}):
                    portal.package_delivery(self.state, self.review, self.root, path, audience, include)
                data = self.payload(path)
                self.assertNotIn('assets', data['review'])
                if audience == 'audit': self.assertNotIn('workflow', data)
                else:
                    self.assertEqual(data['workflow']['current_stage'], 'design')
                    self.assertNotIn('decisions', data['workflow'])
                    self.assertNotIn('effort', data['workflow'])
                self.assertNotIn('Which grain is required?', json.dumps(data))
                self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    def test_reviewer_gets_curated_effort_and_questions_without_internal_payload(self):
        path = self.root / 'reviewer.zip'
        with patch.dict(sys.modules, {'engagement_stages': self.module}):
            portal.package_delivery(self.state, self.review, self.root, path)
        data = self.payload(path)
        self.assertEqual(data['workflow']['effort']['readiness'], 'blocked')
        self.assertEqual(data['workflow']['decisions'][0]['options'], [{'id': 'orders', 'label': 'Order'}])
        self.assertNotIn('PRIVATE_', json.dumps(data))

    def test_invalid_asset_and_dependency_associations_are_not_silently_dropped(self):
        for key, value in [('asset_ids', ['missing']), ('depends_on', ['missing']), ('asset_ids', 'report')]:
            with self.subTest(key=key, value=value):
                review = copy.deepcopy(self.review); review['models'][0][key] = value
                with self.assertRaisesRegex(ValueError, 'association'):
                    portal.validate_review(self.state, review)
        self.review['assets'] = [{'id': '__unmapped__'}]
        with self.assertRaisesRegex(ValueError, 'reserved'):
            portal.validate_review(self.state, self.review)

    def test_design_revision_drift_and_absent_binding_reject_stale_review(self):
        portal.validate_review(self.state, self.review)
        for binding in (None, {'id': 'design-1', 'revision': 1, 'sha256': 'a' * 64},
                        {'id': 'design-1', 'revision': 2, 'sha256': 'b' * 64}):
            with self.subTest(binding=binding):
                review = copy.deepcopy(self.review)
                if binding is None: review.pop('design_binding')
                else: review['design_binding'] = binding
                with self.assertRaisesRegex(ValueError, 'design_binding'):
                    portal.validate_review(self.state, review)
        # Legacy review v1 still renders when it has no independently versioned design.
        self.state.pop('workflow'); self.review.pop('design_binding')
        portal.validate_review(self.state, self.review)


@unittest.skipUnless(shutil.which('node'), 'Node is needed for browser helper execution')
class GuidedReviewBrowserHelpersTests(unittest.TestCase):
    def run_js(self, assertions):
        source = (portal.ASSETS / 'portal.js').read_text()
        helpers = source.split('// BEGIN WORKFLOW HELPERS')[1].split('\n', 1)[1].split('// END WORKFLOW HELPERS')[0]
        result = subprocess.run([shutil.which('node'), '-e', "const assert=require('node:assert/strict');\n" + helpers + assertions],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_page_boots_and_asset_filter_leaves_export_selection_unchanged(self):
        # Execute the shipped script against only IDs that exist in the template.
        # Visual browser QA remains separate; this catches boot/event ordering bugs.
        import re
        template = (portal.ASSETS / 'portal.html').read_text()
        ids = re.findall(r'\bid="([^"]+)"', template)
        projection = portal._workflow_presentation(workflow_view())
        data = {'engagement': {'engagement_id': 'synthetic-pilot', 'revision': 2,
                              'target': {}, 'readiness': {'questions': [], 'platform': {}}},
                'workflow': projection, 'review': {key: projection.pop(key) for key in ('models', 'assets', 'relationships')},
                'audience': 'reviewer', 'files': []}
        harness = """
const assert=require('node:assert/strict');
class Node {constructor(tag){this.tag=tag;this.children=[];this.value='';this.textContent='';this.dataset={};this.classList={toggle(){}};}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(k,v){this[k]=v;}removeAttribute(k){delete this[k];}}
const elements=new Map(IDS.map(id=>[id,new Node('element')]));elements.get('delivery-data').textContent=JSON.stringify(PAYLOAD);
const document={documentElement:{outerHTML:'<html></html>'},body:new Node('body'),getElementById:id=>{assert(elements.has(id),'Missing template control: '+id);return elements.get(id);},createElement:tag=>new Node(tag),querySelectorAll:()=>[]};
const location={hash:'#overview'};function addEventListener(){}
""".replace('IDS', json.dumps(ids)).replace('PAYLOAD', json.dumps(data))
        assertions = """
assert.equal(el('stage').textContent,'design');assert.equal(el('effort-panel').hidden,false);
assert.equal(el('save-decisions').disabled,true);assert.equal(selection.visible.size,1);
const exportBefore=[...chosen];el('asset-filter').value='report';el('asset-filter').onchange();
assert.equal(selection.direct.has('gold.orders'),true);assert.deepEqual([...chosen],exportBefore);
assert.equal(el('decisions').children.length,1);assert(currentDiagram.svg.includes('Orders'));
el('asset-filter').value='__unmapped__';el('asset-filter').onchange();
assert.equal(selection.unknown.has('gold.orders'),true);assert.deepEqual([...chosen],exportBefore);
"""
        result = subprocess.run([shutil.which('node'), '-e', harness + '\n' + (portal.ASSETS / 'portal.js').read_text() + assertions],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_asset_filter_closes_upstream_cycles_and_preserves_unmapped_blockers(self):
        self.run_js("""
const models=[{id:'raw',asset_ids:[]},{id:'clean',asset_ids:[],depends_on:['raw']},
 {id:'orders',asset_ids:['report'],mapping_status:'verified',depends_on:['clean']},
 {id:'other',asset_ids:['other'],mapping_status:'inferred'}];
const edges=[{from:'orders',to:'clean',kind:'lineage'},{from:'other',to:'orders',kind:'relationship'}];
const selected=assetSelection(models,edges,'report');
assert.deepEqual([...selected.visible].sort(),['clean','orders','raw']);
assert.equal(selected.dependencies.size,2);assert.equal(selected.unknown.size,3);
assert.equal(selected.visible.has('other'),false);
assert.equal(matchesAsset({id:'unknown-question'},selected,'report'),true);
assert.equal(matchesAsset({model_ids:['clean']},selected,'report'),true);
assert.equal(matchesAsset({model_ids:['other']},selected,'report'),false);
assert.equal(assetSelection(models,edges,'unknown').visible.size,0);
assert.equal(assetSelection(models,edges,'__unmapped__').direct.has('other'),true);
""")

    def test_answer_export_binds_revision_and_cannot_export_approval(self):
        self.run_js("""
const workflow={design_id:'d1',design_revision:4,design_sha256:'a'.repeat(64),decisions:[{id:'q1',options:[{id:'one',label:'One'}]}]};
const response=decisionResponseDocument(workflow,'engagement',[{decision_id:'q1',answer:' One ',option_id:'one',rationale:'Reviewed source',approved:true}]);
assert.equal(response.kind,'decision_responses');assert.equal(response.design_revision,4);
assert.equal(response.request_only,true);assert.equal(response.answers[0].answer,'One');
assert.equal('approved' in response.answers[0],false);assert.equal('approval' in response,false);
assert.throws(()=>decisionResponseDocument({...workflow,design_sha256:''},'engagement',response.answers),/binding/);
assert.throws(()=>decisionResponseDocument(workflow,'engagement',[]),/at least/);
assert.throws(()=>decisionResponseDocument(workflow,'engagement',[{decision_id:'q1',answer:'yes',option_id:'invented'}]),/unknown/);
assert.throws(()=>decisionResponseDocument(workflow,'engagement',[...response.answers,...response.answers]),/duplicated/);
""")

    def test_subset_trims_unselected_decision_and_effort_details(self):
        self.run_js("""
const original={review:{assets:[{id:'report'}],models:[{id:'m'}],decisions:[{question:'Private'}],changes:[{rationale:'Private'}]},workflow:{current_stage:'design',decisions:[{question:'Private'}],effort:{summary:'Private'}}};
const reduced=structuredClone(original);trimWorkflowDetails(reduced,new Set(['implementation']));
assert.equal(reduced.workflow.current_stage,'design');assert.equal('effort' in reduced.workflow,false);
assert.equal('assets' in reduced.review,false);assert.equal('decisions' in reduced.review,false);
trimWorkflowDetails(original,new Set(['dictionary']));assert.equal(original.review.models.length,1);
""")

    def test_filtered_svg_escapes_source_content_and_retains_table_connections(self):
        self.run_js("""
const svg=filteredModelSvg([{id:'a',name:'<script>bad</script>',layer:'bronze',grain:'per id',columns:[{name:'id',type:'NUMBER'}]},{id:'b',layer:'gold'}],[{from:'a',to:'b',kind:'lineage',predicate:'a.id = b.id'}],new Set(['a']));
assert.equal(svg.includes('<script>'),false);assert.equal(svg.includes('&lt;script&gt;'),true);
assert.equal(svg.includes('Required dependency'),true);assert.equal(svg.includes('marker-end='),true);
assert.equal(svg.includes('a.id = b.id'),true);assert.equal(svg.includes('<rect'),true);
""")


if __name__ == '__main__': unittest.main()
