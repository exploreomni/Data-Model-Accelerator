"""Large delivery keeps one offline entrypoint and original code, not a giant payload."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import portable_site
import test_delivery_portal as delivery_fixtures
from test_delivery_portal import fixture


class PortableSiteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.candidate = self.root / 'candidate'
        self.candidate.mkdir()
        self.state, self.review = fixture(self.candidate)
        self.review['package_layout_version'] = 2
        self.path = self.root / 'handoff.zip'

    def build(self):
        with patch.object(portable_site, 'should_partition', return_value=True):
            return portal.package_delivery(self.state, self.review, self.candidate, self.path, 'engineer',
                ['documentation', 'diagrams', 'dictionary', 'implementation'])

    def test_partitioned_package_has_complete_inventory_clickable_tables_and_original_files(self):
        manifest = self.build()
        self.assertEqual(manifest['presentation_contract'], 'partitioned_v1')
        self.assertEqual(portal.verify_delivery(self.path)['status'], 'integrity_verified')
        with zipfile.ZipFile(self.path) as archive:
            from portal_checks import parse_page
            _, root = parse_page(archive.read('START_HERE.html'))
            self.assertEqual(root['model_count'], len(self.review['models']))
            self.assertNotIn('base64', json.dumps(root))
            self.assertTrue(root['pipelines'])
            for model in root['models']:
                page = archive.read(model['path']).decode()
                self.assertIn('Columns', page)
                self.assertIn('Copy full name', page)
                self.assertNotIn('START_HERE.html%23', page)
            for item in root['files']:
                self.assertEqual(len(archive.read(item['path'])), item['size'])
        self.assertFalse(manifest['deployment_authorized'])

    def test_missing_table_page_or_changed_count_fails(self):
        manifest = self.build()
        with zipfile.ZipFile(self.path) as archive:
            files = {n: archive.read(n) for n in archive.namelist()}
        missing = next(r['path'] for r in manifest['files'] if '/tables/' in r['path'])
        files.pop(missing)
        with zipfile.ZipFile(self.path, 'w') as archive:
            for name, body in files.items(): archive.writestr(name, body)
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            portal.verify_delivery(self.path)

    def test_small_delivery_stays_on_existing_renderer(self):
        self.assertFalse(portable_site.should_partition({'package_layout_version': 2, 'review': self.review, 'files': []}))

    def test_repeat_generation_has_identical_bytes(self):
        self.build(); original = self.path.read_bytes()
        self.path = self.root / 'same-content.zip'
        self.build()
        self.assertEqual(self.path.read_bytes(), original)

    def test_explicit_proposal_reference_is_covered_without_becoming_a_canonical_table(self):
        from portal_checks import parse_page
        self.review['domain_proposals'] = [{'id': 'external-proposal', 'domain': 'Orders',
            'model_ids': ['gold.orders'],
            'reference_endpoints': [{'id': 'external.contract', 'name': 'External contract'}],
            'relationships': [{'from': 'external.contract', 'to': 'gold.orders', 'kind': 'lineage'}]}]
        self.build()
        self.assertEqual(portal.verify_delivery(self.path)['diagram_coverage']['status'], 'complete')
        with zipfile.ZipFile(self.path) as archive:
            _, data = parse_page(archive.read('START_HERE.html'))
            canonical_ids = {m['id'] for m in self.review['models']}
            self.assertEqual({m['id'] for m in data['models']}, canonical_ids)
            self.assertEqual(set(data['diagram_model_ids']), canonical_ids | {'external.contract'})
            self.assertEqual({identifier for p in data['pipelines'] for identifier in p['model_ids']},
                             canonical_ids | {'external.contract'})
            source = next(r for r in data['files'] if r['id'] == 'generated:erd-source')
            self.assertEqual(json.loads(archive.read(source['path']))['domain_proposals'], self.review['domain_proposals'])

    def test_failed_quality_is_visible_and_reverified_against_selected_evidence(self):
        from portal_checks import parse_page
        harness = delivery_fixtures.DeliveryPortalTests('test_quality_keeps_clean_code_distinct_from_wrong_model_results')
        harness.setUp(); self.addCleanup(harness.doCleanups)
        harness.quality(); harness.review['package_layout_version'] = 2
        with patch.object(portable_site, 'should_partition', return_value=True):
            path = harness.package(audience='engineer')
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        page = files['START_HERE.html'].decode()
        _, data = parse_page(page)
        failure = next(row for row in data['quality_checks'] if row['id'] == 'data_accuracy')
        self.assertEqual((failure['status'], failure['evidence_state']), ('fail', 'selected'))
        visible = page.split('<script id="delivery-data"')[0]
        self.assertIn('The independent metric comparison failed.', visible)
        self.assertIn('Repair the model arithmetic and rerun the independent cases.', visible)
        failure['summary'] = 'A fabricated replacement summary.'
        page = re.sub(r'(<script id="delivery-data" type="application/json">).*?(</script>)',
            lambda match: match[1] + portable_site._encoded(data) + match[2], page, flags=re.S)
        files['START_HERE.html'] = page.encode()
        manifest = json.loads(files['DELIVERY_MANIFEST.json'])
        row = next(r for r in manifest['files'] if r['path'] == 'START_HERE.html')
        row.update(bytes=len(files['START_HERE.html']), sha256=hashlib.sha256(files['START_HERE.html']).hexdigest())
        files['DELIVERY_MANIFEST.json'] = json.dumps(manifest).encode()
        changed = self.root / 'changed-quality.zip'
        with zipfile.ZipFile(changed, 'w') as archive:
            for name, body in files.items(): archive.writestr(name, body)
        with self.assertRaisesRegex(ValueError, 'Quality summary differs|Quality evidence differs'):
            portal.verify_delivery(changed)

    def test_checkpoint_manifest_cannot_drop_its_incomplete_label(self):
        with patch.object(portable_site, 'should_partition', return_value=True):
            portal.package_delivery(self.state, self.review, self.candidate, self.path, 'engineer',
                ['documentation', 'diagrams', 'dictionary'], checkpoint=True)
        self.assertEqual(portal.verify_delivery(self.path)['status'], 'integrity_verified')
        with zipfile.ZipFile(self.path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(files['DELIVERY_MANIFEST.json'])
        self.assertEqual(manifest.pop('delivery_kind'), 'checkpoint')
        self.assertEqual(manifest.pop('checkpoint')['status'], 'incomplete')
        files['DELIVERY_MANIFEST.json'] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.path, 'w') as archive:
            for name, body in files.items(): archive.writestr(name, body)
        with self.assertRaisesRegex(ValueError, 'Checkpoint label differs'):
            portal.verify_delivery(self.path)

    def test_offline_scripts_syntax_and_stub_navigation(self):
        from portal_checks import parse_page, check_javascript
        self.build()
        with zipfile.ZipFile(self.path) as archive:
            page = archive.read('START_HERE.html')
            _, data = parse_page(page)
            prelude = '''
const fixture = DATA;
class N {constructor(id=''){this.id=id;this.children=[];this.dataset={};this.hidden=false;this.events={};this.textContent='';this._value='';this.style={};}get value(){return this._value||this.children[0]?.value||'';}set value(v){this._value=v;}replaceChildren(){this.children=[];this._value='';}appendChild(v){this.children.push(v);}addEventListener(n,f){this.events[n]=f;}setAttribute(k,v){this[k]=v;}getAttribute(k){return this[k];}showModal(){}close(){}}
const ids={};for(const id of ['domain','output','pipeline','empty','search','inspector','table-frame','close-inspector','delivery-data'])ids[id]=new N(id);
ids['delivery-data'].textContent=JSON.stringify(fixture);
const sections=['model','code','migration','validation'].map(id=>new N(id));
global.location={hash:''};global.window={addEventListener(){}};
global.document={getElementById:id=>ids[id],createElement:()=>new N(),querySelectorAll:s=>s==='[data-section]'?sections:[]};
'''.replace('DATA', json.dumps(data))
            checks = '''
if(sections[0].hidden||!sections[1].hidden)throw Error('Initial route');
if(ids.pipeline.src!==fixture.pipelines[0].path)throw Error('Pipeline not loaded');
location.hash='#code';route();if(sections[1].hidden||!sections[0].hidden)throw Error('First-click routing');
ids.domain.value=fixture.domains[0];ids.domain.events.change();
if(!ids.output.children.length)throw Error('Domain has no output');
'''
            self.assertTrue(check_javascript(page, prelude=prelude, assertions=checks)['smoke'])
            pipeline = archive.read(data['pipelines'][0]['path'])
            _, detail = parse_page(pipeline)
            smoke = '''
const fixture=DATA, buttons=[{dataset:{zoom:'0.2'},addEventListener(n,f){this.click=f;}}];
const node={getAttribute:()=>Object.keys(fixture.model_pages)[0],setAttribute(){},addEventListener(n,f){this[n]=f;}};
const fixtureSvg={style:{},getAttribute:k=>k==='width'?'100':'200',querySelectorAll:()=>[node]};
global.document={getElementById:()=>({textContent:JSON.stringify(fixture)}),querySelector:()=>fixtureSvg,querySelectorAll:s=>s==='[data-zoom]'?buttons:[]};global.location={href:''};
'''.replace('DATA', json.dumps(detail))
            self.assertTrue(check_javascript(pipeline, prelude=smoke, assertions="buttons[0].click();if(fixtureSvg.style.width!=='120px')throw Error('Zoom');node.click();if(!location.href)throw Error('Table navigation');")['smoke'])


if __name__ == '__main__': unittest.main()
