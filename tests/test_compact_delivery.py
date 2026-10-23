"""Independent compact handoff checks using only the repository's synthetic fixture."""
import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from test_delivery_portal import fixture, portal


class Navigation(HTMLParser):
    """Observe primary versus collapsed secondary navigation without a browser."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.links = []
        self.details = []
        self.active = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'details':
            self.details.append({'attrs': attrs, 'links': []})
        if tag == 'a' and 'data-nav' in attrs:
            self.active = {'href': attrs.get('href'), 'text': '',
                           'secondary': 'details' in self.stack, 'hidden': 'hidden' in attrs}
            self.links.append(self.active)
            if self.active['secondary']:
                self.details[-1]['links'].append(self.active)
        if tag not in {'meta', 'link', 'input', 'img', 'br', 'hr'}:
            self.stack.append(tag)

    def handle_data(self, text):
        if self.active is not None:
            self.active['text'] += text

    def handle_endtag(self, tag):
        if tag == 'a':
            self.active = None
        if tag in self.stack:
            at = len(self.stack) - 1 - self.stack[::-1].index(tag)
            self.stack = self.stack[:at]


class CompactDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='compact-synthetic-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state, self.review = fixture(self.root)
        self.sequence = 0

    def artifact(self, path, category='documentation', audiences=None, body='Synthetic guide only.'):
        content = body.encode()
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        record = {'id': 'compact-' + str(len(self.review['artifacts'])), 'path': path,
                  'category': category, 'audiences': audiences or ['engineer', 'reviewer'],
                  'sha256': hashlib.sha256(content).hexdigest()}
        self.review['artifacts'].append(record)
        return record

    def handoff(self, guide_category='documentation', guide_audiences=None):
        guide = self.artifact('guides/implementation.txt', guide_category, guide_audiences)
        self.review['handoff'] = {'design_artifact_id': '0',
                                 'implementation_guide_artifact_id': guide['id']}
        return guide

    def package(self, **kwargs):
        self.sequence += 1
        output = self.root / ('compact-' + str(self.sequence) + '.zip')
        portal.package_delivery(self.state, self.review, self.root, output, **kwargs)
        with zipfile.ZipFile(output) as archive:
            page = archive.read('START_HERE.html').decode()
        payload = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        return output, page, payload

    def helpers(self):
        text = (portal.ASSETS / 'portal.js').read_text()
        match = re.search(r'// BEGIN COMPACT HANDOFF HELPERS[^\n]*\n(.*?)// END COMPACT HANDOFF HELPERS',
                          text, re.S)
        self.assertIsNotNone(match, 'Compact handoff helper boundary is missing')
        return match.group(1)

    def javascript(self, code, payload=None):
        if not shutil.which('node'):
            self.skipTest('Node is required for pure browser-helper checks')
        script = ("const assert=require('node:assert/strict');\n" + self.helpers() +
                  '\nconst input=' + json.dumps(payload) + ';\n' + code)
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_registered_text_handoff_survives_selected_package(self):
        guide = self.handoff()
        output, _, data = self.package(audience='engineer')
        self.assertEqual(data['review']['handoff'], self.review['handoff'])
        self.assertEqual({r['id'] for r in data['files']} & {'0', guide['id']}, {'0', guide['id']})
        self.assertEqual(portal.verify_delivery(output)['status'], 'integrity_verified')

    def test_implementation_category_guide_is_allowed_for_engineer(self):
        guide = self.handoff('implementation', ['engineer'])
        _, _, data = self.package(audience='engineer')
        self.assertEqual(data['review']['handoff']['implementation_guide_artifact_id'], guide['id'])

    def test_malformed_or_extra_handoff_properties_rejected(self):
        for value in (None, [], '0', {'design_artifact_id': ''},
                      {'design_artifact_id': []}, {'design_artifact_id': 0},
                      {'design_artifact_id': 'absent'}, {'design_artifact_id': '0', 'native_validated': True},
                      {'design_artifact_id': '0', 'implementation_guide_artifact_id': '0'}):
            with self.subTest(value=value):
                self.review['handoff'] = value
                with self.assertRaises(ValueError):
                    self.package(audience='engineer')

    def test_registered_artifact_categories_do_not_become_interchangeable(self):
        for role, identifier in [('design_artifact_id', '1'), ('design_artifact_id', '2'),
                                 ('implementation_guide_artifact_id', '3')]:
            with self.subTest(role=role, identifier=identifier):
                self.review['handoff'] = {role: identifier}
                with self.assertRaises(ValueError):
                    self.package(audience='engineer')

    def test_role_binding_rejects_nontext_document_even_if_registered(self):
        for suffix in ('.json', '.sql', '.svg'):
            record = self.artifact('docs/design' + suffix)
            for role in ('design_artifact_id', 'implementation_guide_artifact_id'):
                with self.subTest(role=role, suffix=suffix):
                    self.review['handoff'] = {role: record['id']}
                    with self.assertRaises(ValueError):
                        self.package(audience='engineer')

    def test_category_selection_removes_unselected_role_ids(self):
        guide = self.handoff('implementation', ['engineer'])
        _, _, data = self.package(audience='engineer', include=['implementation'])
        self.assertEqual(data['review']['handoff'], {'implementation_guide_artifact_id': guide['id']})
        self.assertNotIn('decisions', data['review'])
        self.assertNotIn('validation', data['review'])

    def test_reviewer_cannot_retain_engineer_only_guide_reference(self):
        self.handoff(guide_audiences=['engineer'])
        _, _, data = self.package(audience='reviewer')
        self.assertEqual(data['review']['handoff'], {'design_artifact_id': '0'})
        self.assertNotIn('guides/implementation.txt', json.dumps(data['files']))

    def test_audit_package_has_no_working_handoff_reference(self):
        self.handoff()
        _, _, data = self.package(audience='audit')
        self.assertNotIn('handoff', data['review'])

    def test_status_only_page_has_no_dangling_handoff_reference(self):
        self.handoff()
        path = self.root / 'status.html'
        portal.render_engagement(self.state, path, self.review)
        data = json.loads(path.read_text().split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(data['files'], [])
        self.assertEqual(data['review']['handoff'], {})

    def test_duplicate_starters_rejected_case_insensitively_in_selected_outputs(self):
        for filename in ('START_HERE.md', 'Start_Here.TXT', 'sTaRt_HeRe.HtMl'):
            for category in ('documentation', 'implementation', 'validation', 'sample_data'):
                with self.subTest(filename=filename, category=category):
                    record = self.artifact('legacy/' + filename, category, ['engineer'])
                    try:
                        with self.assertRaisesRegex(ValueError, 'Start Here|entrypoint'):
                            self.package(audience='engineer', include=[category])
                    finally:
                        self.review['artifacts'].remove(record)

    def test_omitted_and_audience_excluded_old_starters_do_not_block_export(self):
        self.artifact('legacy/START_HERE.md', 'implementation', ['engineer'])
        _, _, data = self.package(audience='reviewer')
        self.assertFalse(any('START_HERE.md' in r['path'] for r in data['files']))
        self.package(audience='engineer', include=['documentation'])

    def test_old_audit_text_starters_retained_without_becoming_primary(self):
        records = [self.artifact('history/' + name, 'technical_audit', ['audit'], body='Synthetic historical audit.')
                   for name in ('START_HERE.md', 'start_here.TXT')]
        before = {r['path']: (self.root / r['path']).read_bytes() for r in records}
        output, _, data = self.package(audience='audit')
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.namelist().count('START_HERE.html'), 1)
            for record in records:
                self.assertEqual(archive.read('Technical_Audit/' + record['path']), before[record['path']])
                self.assertEqual((self.root / record['path']).read_bytes(), before[record['path']])
        self.assertNotIn('handoff', data['review'])

    def test_legacy_review_still_exports_without_optional_handoff(self):
        self.assertNotIn('handoff', self.review)
        output, _, data = self.package(audience='engineer')
        self.assertNotIn('handoff', data['review'])
        self.assertEqual(portal.verify_delivery(output)['status'], 'integrity_verified')

    def test_required_seed_closure_is_not_weakened_by_compact_delivery(self):
        self.handoff('implementation', ['engineer'])
        self.review['artifacts'][1]['requires'] = ['2']
        with self.assertRaisesRegex(ValueError, 'dependenc'):
            self.package(audience='engineer', include=['implementation'])
        output, _, data = self.package(audience='engineer', include=['implementation', 'sample_data'])
        self.assertTrue({'1', '2'} <= {f['id'] for f in data['files']})
        self.assertEqual(portal.verify_delivery(output)['status'], 'integrity_verified')

    def test_export_does_not_mutate_source_review_or_overwrite_frozen_zip(self):
        self.handoff()
        before = copy.deepcopy(self.review)
        output, _, _ = self.package(audience='engineer')
        frozen = output.read_bytes()
        self.assertEqual(self.review, before)
        with self.assertRaisesRegex(ValueError, 'exists|version'):
            portal.package_delivery(self.state, self.review, self.root, output, audience='engineer')
        self.assertEqual(output.read_bytes(), frozen)
        self.assertEqual(self.review, before)

    def test_five_primary_review_links_secondary_details_closed(self):
        nav = Navigation()
        template = (portal.ASSETS / 'portal.html').read_text()
        nav.feed(template)
        primary_nav = Navigation()
        primary_nav.feed('<nav id="primary-navigation"' + template.split('<nav id="primary-navigation"', 1)[1].split('</nav>', 1)[0] + '</nav>')
        primary = [link for link in primary_nav.links if not link['hidden']]
        self.assertEqual([link['href'] for link in primary_nav.links if link['hidden']],
                         ['#omni-topic-trees', '#dashboard-migration', '#migration-plan'])
        self.assertEqual({link['href'] for link in nav.links if not link['secondary'] and not link['hidden']} - {link['href'] for link in primary},
                         set())
        self.assertEqual([link['href'] for link in primary], ['#model', '#delivery', '#replacement-map', '#input-files', '#validation'])
        self.assertEqual([re.sub(r'^\s*\d+\s*', '', link['text']).strip() for link in primary],
                         ['Model design', 'Code generation', 'Mappings', 'Inputs & context', 'Checks & decisions'])
        secondary = [details for details in nav.details if details['links']]
        self.assertTrue(secondary, 'Secondary navigation needs a collapsed details group')
        self.assertTrue(all('open' not in details['attrs'] for details in secondary))
        self.assertTrue({'#overview', '#lineage', '#readiness', '#changes', '#deployment', '#architecture',
                         '#table-dictionary', '#implementation-code', '#review-feedback'} <=
                        {link['href'] for details in secondary for link in details['links']})

    def test_compact_helper_is_pure_and_has_only_five_evidence_stages(self):
        self.handoff()
        _, _, data = self.package(audience='engineer')
        self.javascript("""
const before=structuredClone(input), first=compactHandoff(input);
assert.deepEqual(input,before);assert.deepEqual(first,compactHandoff(input));
assert.deepEqual(first.stages.map(s=>s.id),['design','implementation','local','native','acceptance']);
assert.deepEqual(Object.keys(first.blockers).sort(),['decisions','failed','pending','skipped']);
for(const stage of first.stages){assert.equal(typeof stage.label,'string');assert.equal(typeof stage.status,'string');assert.equal(typeof stage.detail,'string');}
assert.equal(first.primary.design.id,input.review.handoff.design_artifact_id);
assert.equal(first.primary.implementation.id,input.review.handoff.implementation_guide_artifact_id);
""", data)

    def test_files_or_imported_pass_claims_do_not_establish_validation(self):
        self.handoff()
        _, _, data = self.package(audience='engineer')
        data['review']['validation'] = [
            {'id': 'native-claim', 'scope': 'warehouse', 'status': 'pass'},
            {'id': 'semantic-claim', 'scope': 'semantic', 'status': 'pass'},
            {'id': 'acceptance-claim', 'scope': 'business', 'status': 'pass'}]
        data['workflow'] = {'current_stage': 'accepted', 'stages': [
            {'id': 'native', 'status': 'pass'}, {'id': 'acceptance', 'status': 'pass'}]}
        data['engagement']['status'] = 'deployed_verified'
        self.javascript("""
const result=compactHandoff(input), stages=Object.fromEntries(result.stages.map(s=>[s.id,s]));
for(const key of ['local','native','acceptance'])assert.ok(!['pass','passed','validated','accepted','complete','completed','ready','deployed_verified'].includes(stages[key].status),key+' overclaims '+stages[key].status);
assert.ok(!/validated|accepted|deployed/i.test(stages.implementation.status));
""", data)

    def test_failures_pending_skips_and_open_decisions_stay_visible(self):
        data = {'review': {'decisions': [{'id': 'open', 'status': 'pending'},
                                        {'id': 'done', 'status': 'resolved'}],
                           'validation': [{'id': 'local-failure', 'scope': 'local', 'status': 'fail'},
                                          {'id': 'native-pending', 'scope': 'warehouse', 'status': 'pending'},
                                          {'id': 'skipped-case', 'scope': 'local', 'status': 'skipped'}]},
                'engagement': {}, 'files': []}
        self.javascript("""
const r=compactHandoff(input);assert.deepEqual(r.blockers,{decisions:1,failed:1,pending:1,skipped:1});
const local=r.stages.find(s=>s.id==='local');assert.ok(/fail|block/i.test(local.status));
const native=r.stages.find(s=>s.id==='native');assert.ok(!['pass','passed','validated','complete'].includes(native.status));
""", data)

    def test_subset_omission_recomputes_blockers_and_cannot_select_old_primary(self):
        self.handoff('implementation', ['engineer'])
        self.review['decisions'] = [{'id': 'unresolved', 'status': 'pending', 'question': 'Synthetic choice'}]
        self.review['validation'] = [{'id': 'failure', 'label': 'Synthetic local failure', 'scope': 'local', 'status': 'fail'}]
        self.state['delivery'] = {'status': 'prepared', 'artifact_count': 999}
        _, _, data = self.package(audience='engineer', include=['implementation'])
        self.javascript("""
const r=compactHandoff(input);assert.deepEqual(r.blockers,{decisions:0,failed:0,pending:0,skipped:0});
assert.equal(r.primary.design,null);assert.equal(r.primary.implementation.id,input.review.handoff.implementation_guide_artifact_id);
assert.ok(!JSON.stringify(r).includes('999'));
""", data)

    def test_trim_handoff_drops_omitted_ids_without_guessing_replacement(self):
        self.handoff('implementation', ['engineer'])
        _, _, data = self.package(audience='engineer')
        self.javascript("""
const selected=input.files.filter(f=>f.id===input.review.handoff.implementation_guide_artifact_id);
trimHandoff(input,selected);input.files=selected;
assert.deepEqual(Object.keys(input.review.handoff),['implementation_guide_artifact_id']);
const r=compactHandoff(input);assert.equal(r.primary.design,null);assert.equal(r.primary.implementation.id,selected[0].id);
trimHandoff(input,[]);input.files=[];assert.deepEqual(input.review.handoff,{});
assert.deepEqual(compactHandoff(input).primary,{design:null,implementation:null});
""", data)

    def test_legacy_js_has_no_invented_primary_file(self):
        _, _, data = self.package(audience='engineer')
        self.javascript("assert.deepEqual(compactHandoff(input).primary,{design:null,implementation:null});", data)

    def test_js_ignores_unknown_handoff_id_and_acceptance_claim(self):
        data = {'review': {'handoff': {'design_artifact_id': 'missing',
                                      'implementation_guide_artifact_id': 'also-missing'}},
                'files': [], 'engagement': {'status': 'accepted', 'delivery': {'artifact_count': 1200}}}
        self.javascript("""
const r=compactHandoff(input);assert.deepEqual(r.primary,{design:null,implementation:null});
assert.deepEqual(r.blockers,{decisions:0,failed:0,pending:0,skipped:0});
assert.ok(!['pass','passed','accepted','complete','completed'].includes(r.stages.find(s=>s.id==='acceptance').status));
""", data)


    def test_selected_quality_failure_and_skip_prevent_local_pass(self):
        data = {'review': {'quality_checks': [
            {'id': 'code_conventions', 'status': 'pass', 'evidence_state': 'selected'},
            {'id': 'project_validity', 'status': 'fail', 'evidence_state': 'selected'}]},
                'files': [], 'engagement': {}}
        self.javascript("""
let stage=compactHandoff(input).stages.find(s=>s.id==='local');assert.ok(/fail|block/i.test(stage.status));
input.review.quality_checks[1].status='skipped';stage=compactHandoff(input).stages.find(s=>s.id==='local');
assert.ok(!['pass','passed','reported_pass','complete'].includes(stage.status));
input.review.quality_checks.forEach(c=>{c.evidence_state='not_included';c.status='pass';c.checked=900;});
stage=compactHandoff(input).stages.find(s=>s.id==='local');assert.ok(!['pass','passed','reported_pass','complete'].includes(stage.status));
assert.ok(!JSON.stringify(compactHandoff(input)).includes('900'));
""", data)

    def test_front_page_never_interpolates_original_full_export_file_count(self):
        source = (portal.ASSETS / 'portal.js').read_text()
        self.assertNotIn('${eng.delivery.artifact_count}', source,
                         'Visible handoff totals must derive from selected files')

    def test_selected_data_accuracy_gap_survives_clean_code_without_mixing_counts(self):
        data = {'review': {'quality_checks': [
            {'id': 'code_conventions', 'status': 'pass', 'evidence_state': 'selected'},
            {'id': 'data_accuracy', 'status': 'fail', 'evidence_state': 'selected',
             'failed': 17, 'checked': 29}], 'validation': [
                {'id': 'synthetic-case', 'scope': 'local', 'status': 'fail'}]},
                'files': [], 'engagement': {}}
        self.javascript("""
const r=compactHandoff(input);
assert.deepEqual(r.evidenceGaps.map(g=>[g.id,g.status]),[['data_accuracy','fail']]);
assert.deepEqual(r.blockers,{decisions:0,failed:1,pending:0,skipped:0});
input.review.validation=[];
assert.equal(compactHandoff(input).stages.find(s=>s.id==='local').status,'reported_pass');
assert.equal(compactHandoff(input).evidenceGaps[0].status,'fail');
for(const status of ['pending','skipped','unsupported','unknown']){
  input.review.quality_checks[1].status=status;
  assert.deepEqual(compactHandoff(input).evidenceGaps.map(g=>[g.id,g.status]),[['data_accuracy',status]]);
}
""", data)

    def test_omitted_quality_artifact_drops_failure_from_export_overview(self):
        row = {'id': 'data_accuracy', 'scope': portal.QUALITY_SCOPES['data_accuracy'],
               'status': 'fail', 'unit': 'cases', 'total': 1,
               'summary': 'Synthetic independent comparison failed.',
               'next_action': 'Inspect the synthetic comparison.',
               'gaps': ['One synthetic comparison differs.']}
        row.update({key: 0 for key in portal.QUALITY_COUNTS})
        row.update(checked=1, failed=1)
        document = {'schema_version': 1, 'kind': 'quality_evidence',
                    'context_sha256': portal.context_fingerprint(self.state),
                    'target': copy.deepcopy(self.review['target']), 'checks': [row]}
        artifact = self.artifact('quality/comparison.json', 'validation', ['engineer'],
                                 json.dumps(document))
        self.review['quality_checks'] = [dict(row, context_sha256=document['context_sha256'],
                                             evidence_artifact_id=artifact['id'], sha256=artifact['sha256'])]
        _, _, selected = self.package(audience='engineer')
        self.javascript("assert.equal(compactHandoff(input).evidenceGaps.find(g=>g.id==='data_accuracy').status,'fail');",
                        selected)
        for options in ({'audience': 'reviewer'},
                        {'audience': 'engineer', 'include': ['implementation']}):
            with self.subTest(options=options):
                _, _, omitted = self.package(**options)
                self.javascript("""
const r=compactHandoff(input);
assert.ok(!r.evidenceGaps.some(g=>g.id==='data_accuracy'));
assert.equal(r.blockers.failed,0);
assert.ok(!JSON.stringify(r).includes('Synthetic independent comparison failed'));
""", omitted)

    def test_negative_assurance_gaps_preserve_status_without_imported_readiness(self):
        data = {'files': [], 'review': {}, 'engagement': {'delivery_assurance': {
            'acceptance_ready': True, 'deployment_authorized': True,
            'checks': [{'lane': 'warehouse_execution', 'status': 'failed'},
                       {'lane': 'data_parity', 'status': 'stale'},
                       {'lane': 'access', 'status': 'unsupported'},
                       {'lane': 'native_model', 'status': 'passed'},
                       {'lane': 'business_acceptance', 'status': 'passed'}]}}}
        self.javascript("""
const r=compactHandoff(input);
assert.deepEqual(r.evidenceGaps.map(g=>[g.id,g.status]),[
  ['warehouse_execution','failed'],['data_parity','stale'],['access','unsupported']]);
assert.deepEqual(r.blockers,{decisions:0,failed:0,pending:0,skipped:0});
for(const id of ['native','acceptance']){
  assert.ok(!['pass','passed','ready','accepted','validated','complete','completed'].includes(r.stages.find(s=>s.id===id).status));
}
""", data)

    def test_evidence_gap_list_is_rendered_in_visible_overview(self):
        source = (portal.ASSETS / 'portal.js').read_text()
        page = (portal.ASSETS / 'portal.html').read_text()
        overview = re.search(r'<section id="overview"[^>]*>(.*?)</section>', page, re.S).group(1)
        self.assertRegex(overview, r'<ul id="handoff-evidence-gaps"></ul>')
        self.assertLess(overview.index('handoff-evidence-gaps'), overview.index('<details'))
        render = next(line for line in source.splitlines()
                      if line.startswith('for(const gap of handoff.evidenceGaps)'))
        self.javascript("""
const nodes=[],el=id=>{assert.equal(id,'handoff-evidence-gaps');return {append:node=>nodes.push(node)}};
const make=(tag,text)=>({tag,text}),pretty=value=>value.replaceAll('_',' ');
const handoff=compactHandoff(input);
""" + render + """
assert.deepEqual(nodes,[{tag:'li',text:'data accuracy: fail'}]);
""", {'files': [], 'review': {'quality_checks': [
            {'id': 'data_accuracy', 'status': 'fail', 'evidence_state': 'selected'}]}})

    def test_full_page_boots_selected_guides_and_preserves_reviewer_file_access(self):
        if not shutil.which('node'):
            self.skipTest('Node is required for synthetic DOM boot checks')
        guide = self.handoff('implementation', ['engineer'])
        template = (portal.ASSETS / 'portal.html').read_text()
        controls = []
        for tag, attributes in re.findall(r'<([a-z][a-z0-9-]*)\s+([^>]+)>', template):
            match = re.search(r'\bid="([^"]+)"', attributes)
            if match:
                nav = re.search(r'\bdata-nav="([^"]+)"', attributes)
                controls.append({'id': match.group(1), 'tag': tag,
                                 'hidden': bool(re.search(r'\bhidden\b', attributes)),
                                 'section': 'data-section' in attributes,
                                 'nav': nav.group(1) if nav else None})
        for audience in ('engineer', 'reviewer'):
            with self.subTest(audience=audience):
                _, _, data = self.package(audience=audience)
                inputs = {'controls': controls, 'payload': data,
                          'design': (self.root / 'docs/model.md').read_text(),
                          'guide': (self.root / guide['path']).read_text()}
                harness = "const assert=require('node:assert/strict');\nconst INPUT=" + json.dumps(inputs) + ";\n" + """
const blobs=[],downloads=[];
class Node {
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.textContent='';this.dataset={};this.open=false;this.classList={toggle(){}};}
  append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this[k]=v;}removeAttribute(k){delete this[k];}
  click(){if(this.tag==='a')downloads.push({name:this.download,url:this.href});}
  remove(){}
}
const elements=new Map(INPUT.controls.map(c=>{const n=new Node(c.tag);n.id=c.id;n.hidden=c.hidden;n.section=c.section;if(c.nav)n.dataset.nav=c.nav;return[c.id,n]}));
elements.get('delivery-data').textContent=JSON.stringify(INPUT.payload);
const document={documentElement:{outerHTML:'<html></html>'},body:new Node('body'),
  getElementById:id=>{assert(elements.has(id),'Missing template control: '+id);return elements.get(id)},
  createElement:tag=>new Node(tag),querySelectorAll:selector=>[...elements.values()].filter(n=>selector==='[data-section]'?n.section:selector==='[data-nav]'?n.dataset.nav:false)};
const URL={createObjectURL:blob=>{blobs.push(blob);return 'blob:synthetic-'+blobs.length},revokeObjectURL(){}};
const location={hash:'#overview'};function addEventListener(){}function setTimeout(callback){callback();}
"""
                assertions = """
const children=(node,tag)=>node.children.filter(c=>c.tag===tag);
function inspectGuide(id,expected){
  const details=children(el(id),'details');assert.equal(details.length,1,id+' details');
  assert.equal(details[0].open,false);assert.equal(children(details[0],'summary').length,1);
  assert.equal(children(details[0],'pre')[0].textContent,expected);
  details[0].open=true;assert.equal(children(details[0],'pre')[0].textContent,expected);
  const buttons=children(details[0],'button');assert.equal(buttons.length,1);
  assert.equal(buttons[0].textContent,'Download document');assert.equal(typeof buttons[0].onclick,'function');
  buttons[0].onclick();
}
inspectGuide('design-guide',INPUT.design);
assert.equal(el('overview').hidden,false);
if(INPUT.payload.audience==='engineer'){
  inspectGuide('implementation-guide',INPUT.guide);
  assert.equal(el('implementation-nav').hidden,false);assert.equal(el('files-nav').hidden,true);
}else{
  assert.equal(el('implementation-nav').hidden,false);assert.equal(el('files-nav').hidden,true);
  assert.match(el('implementation-state').textContent,/excluded from reviewer/);
  assert.equal(children(el('implementation-guide'),'details').length,0);
  assert.ok(el('implementation-guide').children.some(n=>n.textContent.includes('No implementation guide is included')));
}
location.hash='#delivery';navigate();assert.equal(el('delivery').hidden,false);
assert.equal(downloads.length,INPUT.payload.audience==='engineer'?2:1);
assert.equal(downloads[0].name,'model.md');
Promise.all(blobs.map(b=>b.text())).then(bodies=>{
  assert.deepEqual(bodies,INPUT.payload.audience==='engineer'?[INPUT.design,INPUT.guide]:[INPUT.design]);
}).catch(error=>{console.error(error);process.exitCode=1});
"""
                # Whole-page fixtures exceed Linux's per-argument limit; stream the script.
                script = harness + '\n' + (portal.ASSETS / 'portal.js').read_text().rsplit('})();', 1)[0] + assertions + '\n})();'
                result = subprocess.run([shutil.which('node'), '-'], input=script,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_browser_subset_rejects_nested_legacy_starters_but_retains_audit_text(self):
        if not shutil.which('node'):
            self.skipTest('Node is required for browser subset checks')
        source = (portal.ASSETS / 'portal.js').read_text()
        block = re.search(r'// BEGIN PORTABLE ASSURANCE HELPERS[^\n]*\n(.*?)// END PORTABLE ASSURANCE HELPERS',
                          source, re.S).group(1)
        script = """
const assert=require('node:assert/strict'),crypto=require('node:crypto');
const bytes=value=>Buffer.from(value,'base64');
const sha256=async value=>crypto.createHash('sha256').update(value).digest('hex');
""" + block + """
(async()=>{
  const body=Buffer.from('Synthetic historical guide.');
  const record={id:'synthetic',path:'01_Model/history/START_HERE.md',category:'documentation',
    size:body.length,sha256:await sha256(body),base64:body.toString('base64'),requires:[]};
  for(const name of ['START_HERE.md','Start_Here.TXT','start_here.HTML']){
    record.path='01_Model/history/'+name;
    await assert.rejects(checkedSubsetFiles([record],[record],new Set(['documentation'])),/Start Here|entrypoint/i);
  }
  record.path='Technical_Audit/history/START_HERE.txt';record.category='technical_audit';
  const result=await checkedSubsetFiles([record],[record],new Set(['technical_audit']));
  assert.equal(result.length,1);assert.equal(result[0][0],record.path);assert.deepEqual(result[0][1],body);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
