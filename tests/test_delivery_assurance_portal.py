"""Offline review honesty and actual browser subset helper execution."""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import delivery_assurance
from test_delivery_portal import fixture


class AssurancePortalProjectionTests(unittest.TestCase):
    def test_all_scopes_project_pending_lanes_and_ignore_imported_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = fixture(Path(tmp))
            for scope, required in [('model_only', 8), ('model_semantic', 13), ('full_dashboard', 15)]:
                state['answers']['migration_scope'] = scope
                state['delivery_assurance'] = {'acceptance_ready': True, 'deployment_authorized': True,
                    'checks': [{'lane': name, 'status': 'passed'} for name in delivery_assurance.LANES]}
                value = portal._summary(state)['delivery_assurance']
                self.assertEqual(len(value['checks']), 15)
                self.assertEqual(sum(row['required'] for row in value['checks']), required)
                self.assertTrue(all(row['status'] == ('pending' if row['required'] else 'not_applicable') for row in value['checks']))
                self.assertFalse(value['acceptance_ready'])
                self.assertFalse(value['deployment_authorized'])

    def test_generated_page_contains_visible_candidate_and_evidence_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); state, review = fixture(root)
            state['answers']['migration_scope'] = 'full_dashboard'
            review['context_sha256'] = portal.context_fingerprint(state)
            target = root / 'START_HERE.html'
            portal.render_engagement(state, target, review)
            html = target.read_text()
            for token in ('id="candidate-status"', 'id="assurance-checks"', 'id="assurance-scope"',
                          'Migration evidence and next actions', 'Candidate · acceptance not established'):
                self.assertIn(token, html)
            data = json.loads(re.search(r'<script id="delivery-data" type="application/json">(.*?)</script>', html, re.S).group(1))
            self.assertFalse(data['engagement']['delivery_assurance']['acceptance_ready'])
            self.assertIn('connect-src \'none\'', html)

    def test_agent_package_has_its_own_scan_provenance_without_deployment_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); state, review = fixture(root)
            result = portal.package_delivery(state, review, root, root / 'delivery.zip')
            self.assertEqual(result['export_origin'], 'agent_packager')
            self.assertFalse(result['deployment_authorized'])
            self.assertFalse(result['acceptance_ready'])
            self.assertTrue(result['disclosure_scans'])


@unittest.skipUnless(shutil.which('node'), 'Node is required to execute browser export helpers')
class BrowserSubsetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (portal.ASSETS / 'portal.js').read_text()
        helper = source.split('// BEGIN PORTABLE ASSURANCE HELPERS')[1].split('// END PORTABLE ASSURANCE HELPERS')[0]
        helper = helper[helper.index('\n'):]
        cls.base = "const assert=require('node:assert/strict');const crypto=require('node:crypto').webcrypto;" + helper
        for name in ('bytes', 'crc32', 'zip', 'sha256'):
            cls.base += '\n' + re.search(r'(?:async )?function ' + name + r'\([^\n]+', source).group(0)
        cls.base += """
async function syntheticFile(id,path,body,category='documentation',requires=[]){
  const value=new TextEncoder().encode(body);
  return{id,path,category,requires,size:value.length,sha256:await sha256(value),base64:Buffer.from(value).toString('base64')};
}
"""

    def execute(self, body):
        script = self.base + '\n(async()=>{' + body + "\n})().catch(e=>{process.stderr.write(String(e.stack));process.exitCode=1;});"
        run = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_imported_passes_and_authorization_cannot_turn_viewer_green(self):
        self.execute("""
for(const [scope,required]of [['model_only',8],['model_semantic',13],['full_dashboard',15],[null,15]]){
  const supplied={delivery_assurance:{migration_scope:scope,acceptance_ready:true,deployment_authorized:true,
    checks:assuranceLanes.map(([lane])=>({lane,status:'passed',required:false}))}};
  const value=portableAssurance(supplied);
  assert.equal(value.checks.length,15);assert.equal(value.checks.filter(c=>c.required).length,required);
  assert.equal(value.acceptance_ready,false);assert.equal(value.deployment_authorized,false);
  assert.ok(value.checks.filter(c=>c.required).every(c=>c.status==='pending'&&c.next_action.length>20));
}
""")

    def test_negative_evidence_stays_visible_but_cannot_change_scope_requirements(self):
        self.execute("""
const value=portableAssurance({delivery_assurance:{migration_scope:'full_dashboard',checks:[
  {lane:'access',status:'failed',required:false},{lane:'native_model',status:'unsupported'},
  {lane:'classification',status:'stale'},{lane:'business_acceptance',status:'not_applicable'}]}});
assert.equal(value.checks.find(c=>c.lane==='access').status,'failed');
assert.equal(value.checks.find(c=>c.lane==='access').required,true);
assert.equal(value.checks.find(c=>c.lane==='native_model').status,'unsupported');
assert.equal(value.checks.find(c=>c.lane==='classification').status,'stale');
assert.equal(value.checks.find(c=>c.lane==='business_acceptance').status,'pending');
""")

    def test_tampered_payload_unsafe_duplicate_paths_and_missing_dependencies_block(self):
        self.execute("""
const original=await syntheticFile('docs','01-documentation/model.md','Synthetic model guide');
for(const mutate of [f=>f.base64=Buffer.from('Changed').toString('base64'),f=>f.path='../escape.md',
 f=>f.path='/absolute.md',f=>f.path='START_HERE.html',f=>f.path='C:/x',f=>f.path='safe/../escape',
 f=>f.path='safe'+String.fromCharCode(92)+'escape',
 f=>f.size=999,f=>f.requires=['absent']]){
 const bad=structuredClone(original);mutate(bad);
 await assert.rejects(checkedSubsetFiles([bad],[bad],new Set(['documentation'])));
}
const duplicate={...original,id:'duplicate',path:original.path.toUpperCase()};
await assert.rejects(checkedSubsetFiles([original,duplicate],[original,duplicate],new Set(['documentation'])));
await assert.rejects(checkedSubsetFiles([original],[original],new Set(['implementation'])));
const changed={...original,path:'another.md'};
await assert.rejects(checkedSubsetFiles([original],[changed],new Set(['documentation'])));
""")

    def test_subset_zip_hashes_actual_bytes_and_explicitly_requires_new_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve() / 'subset.zip'
            self.execute("""
const docs=await syntheticFile('docs','01-documentation/model.md','Synthetic model guide');
const omitted=await syntheticFile('implementation','03-implementation/model.sql','select 1','implementation');
const entries=await checkedSubsetFiles([docs,omitted],[docs],new Set(['documentation']));
entries.push(['START_HERE.html',new TextEncoder().encode('<!doctype html><p>Candidate subset</p>')]);
const snapshot={engagement_id:'synthetic',target:{warehouse:'snowflake'},delivery_assurance:{migration_scope:'full_dashboard',acceptance_ready:true}};
const manifest=await browserSubsetManifest(snapshot,'reviewer',new Set(['documentation']),entries);
assert.equal(manifest.export_origin,'browser_subset');assert.equal(manifest.acceptance_ready,false);
assert.equal(manifest.deployment_authorized,false);assert.equal(manifest.content_scan.status,'not_run_in_browser');
assert.equal(manifest.content_scan.coverage_complete,false);assert.equal(manifest.disclosure_policy_status,'not_revalidated_in_browser');
assert.equal('disclosure_scans' in manifest,false);assert.equal(manifest.migration_scope,'full_dashboard');
entries.push(['DELIVERY_MANIFEST.json',new TextEncoder().encode(JSON.stringify(manifest))]);
require('node:fs').writeFileSync(OUTPUT,new Uint8Array(await zip(entries).arrayBuffer()));
""".replace('OUTPUT', json.dumps(str(target))))
            result = portal.verify_delivery(target)
            self.assertEqual(result['status'], 'integrity_verified')
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(set(archive.namelist()), {'01-documentation/model.md', 'START_HERE.html', 'DELIVERY_MANIFEST.json'})
                self.assertNotIn(b'select 1', b''.join(archive.read(name) for name in archive.namelist()))


if __name__ == '__main__': unittest.main()
