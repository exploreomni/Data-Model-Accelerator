"""Planning navigation and artifacts use the same scoped public snapshot offline."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import migration_planning as planning
import test_migration_planning_workflow as workflow_fixture
import test_portal_navigation as navigation
from test_privacy_contract import approved_classification, approved_policy


class PlanningPortalTests(unittest.TestCase):
    def setUp(self):
        self.helper = workflow_fixture.PlanningWorkflowTests()
        self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        self.helper.record(); self.h = self.helper.h
        self.review = {'schema_version': 1, 'title': 'Synthetic commerce migration',
            'source_fingerprint': portal.source_fingerprint(self.h.state),
            'context_sha256': portal.context_fingerprint(self.h.state),
            'design_binding': {k: self.h.state['workflow']['design'][k] for k in ('id', 'revision', 'sha256')},
            'target': {k: self.h.state['answers'][k] for k in ('framework', 'warehouse')},
            'models': [dict(id=e['id'], name=e['name'], layer=e['layer'], grain=e['grain'], columns=e['columns'])
                       for e in self.h.doc['entities']],
            'relationships': self.h.doc['relationships'], 'artifacts': [],
            'disclosure': {'audience': 'engineer', 'artifacts': {},
                'presentation': approved_classification(), 'policy': approved_policy()}}

    def payload(self, include=('documentation', 'diagrams', 'dictionary'), audience='engineer'):
        output = self.h.root / ('portal-' + str(len(list(self.h.root.glob('portal-*.zip')))) + '.zip')
        portal.package_delivery(self.h.state, self.review, self.h.artifacts, output, audience, include)
        with zipfile.ZipFile(output) as archive:
            page = archive.read('START_HERE.html').decode()
            data = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
            for record in data['generated_deliverables']:
                self.assertEqual(archive.read(record['path']), base64.b64decode(record['base64']))
                self.assertEqual(hashlib.sha256(archive.read(record['path'])).hexdigest(), record['sha256'])
        return data

    def test_package_has_matching_planning_files_and_no_private_references(self):
        data = self.payload()
        paths = [r['path'] for r in data['generated_deliverables']]
        self.assertTrue(any(p.endswith('inventory.xlsx') for p in paths))
        self.assertTrue(any(p.endswith('migration-plan.docx') for p in paths))
        self.assertNotIn('synthetic://private/oracle', json.dumps(data))
        snapshot = data['migration_planning']['domains'][0]
        self.assertEqual(snapshot['work_items'][0]['id'], 'req.orders')
        self.assertEqual(snapshot['consumer_coverage']['missing'], 2)
        self.assertNotIn('migration_planning', portal._presentation(self.h.state, audience='audit'))

    def test_finalizer_has_one_guided_entrypoint_and_matching_office_downloads(self):
        import design_consistency
        import finalize_delivery
        self.review.update(design_consistency.project_review(self.h.state['workflow']['design']))
        content = b'# Commerce design\n\nSynthetic orders, customers and products; acceptance is pending.\n'
        (self.h.artifacts / 'design.md').write_bytes(content)
        self.review['artifacts'] = [{'id': 'design', 'path': 'design.md', 'category': 'documentation',
            'audiences': ['engineer'], 'sha256': hashlib.sha256(content).hexdigest()}]
        self.review['handoff'] = {'design_artifact_id': 'design'}
        self.review['disclosure']['artifacts']['design'] = approved_classification()
        result = finalize_delivery.finalize_delivery(self.h.state, self.review, self.h.artifacts,
            self.h.root / 'release', 'engineer', ['documentation', 'diagrams', 'dictionary'], javascript=True)
        self.assertEqual(result['status'], 'handoff_verified')
        folder = Path(result['folder'])
        self.assertTrue((folder / 'START_HERE.html').is_file())
        self.assertEqual(len(list(folder.glob('05_Migration/*/*.xlsx'))), 1)
        self.assertEqual(len(list(folder.glob('05_Migration/*/*.docx'))), 1)
        manifest = json.loads((folder / 'DELIVERY_MANIFEST.json').read_text())
        self.assertFalse(manifest['acceptance_ready'])
        self.assertFalse(manifest['deployment_authorized'])

    def test_actual_subset_projection_omits_cross_scope_notes_and_consumers(self):
        review = copy.deepcopy(self.review)
        review['models'] = [m for m in review['models'] if m['id'] == 'orders']
        review['relationships'] = []
        projected = portal._presentation(self.h.state, review)['migration_planning']
        # A plan and its editable binaries are indivisible at a domain boundary.
        self.assertEqual(projected['domains'], [])

    def test_dictionary_exclusion_removes_nested_plan_and_office_files(self):
        for include in (('documentation',), ('diagrams', 'dictionary')):
            data = self.payload(include)
            self.assertNotIn('migration_planning', data)
            self.assertIn('both documentation and dictionary', data['migration_planning_omitted'])
            self.assertFalse(any(f['path'].startswith('05_Migration/') for f in data['generated_deliverables']))

    @unittest.skipUnless(shutil.which('node'), 'Node required for offline navigation')
    def test_first_click_search_download_inventory_and_binary_subset(self):
        runner = navigation.PortalNavigationTests()
        runner.page(self.payload(), """
assert.equal(el('migration-plan-nav').hidden,false);
location.hash='#migration-plan';listeners.hashchange[0]();
assert.equal(el('migration-plan').hidden,false);assert.equal(el('model').hidden,true);
assert.match(PAGE, /id="migration-plan" class="review-section"/);
assert.match(el('migration-plan-status').textContent,/commerce: current/);
assert.ok(el('migration-plan-consumers').children.length);
assert.ok(el('migration-plan-files').children.some(b=>b.textContent.includes('inventory.xlsx')));
assert.ok(el('migration-plan-files').children.some(b=>b.textContent.includes('migration-plan.docx')));
showFile(allFiles().find(f=>f.path.endsWith('inventory.xlsx')));
assert.equal(el('copy-code').disabled,true);assert.equal(el('download-file').disabled,false);
assert.match(el('file-content').textContent,/Download this document/);
el('migration-plan-search').value='no matching consumer';el('migration-plan-search').oninput();
assert.match(el('migration-plan-consumers').children[0].textContent,/No matching records/);
el('migration-plan-search').value='';el('migration-plan-search').oninput();
const beforePlanning=data.generated_deliverables.filter(f=>f.path.startsWith('05_Migration/'));
rebuildGenerated(structuredClone(data)).then(files=>{
 const after=files.filter(f=>f.path.startsWith('05_Migration/'));
 assert.deepEqual(after,beforePlanning);
 const docs=structuredClone(data);trimWorkflowDetails(docs,new Set(['documentation']));
 assert.equal(docs.migration_planning,undefined);
 assert.match(docs.migration_planning_omitted,/both documentation and dictionary/);
 const code=structuredClone(data);trimWorkflowDetails(code,new Set(['implementation']));
 assert.equal(code.migration_planning,undefined);
 code.selected_categories=['implementation'];return rebuildGenerated(code);
}).then(files=>assert.equal(files.some(f=>f.path.startsWith('05_Migration/')),false));
""", second_boot=True)

    @unittest.skipUnless(shutil.which('node'), 'Node required for offline navigation')
    def test_existing_delivery_keeps_planning_route_hidden(self):
        runner = navigation.PortalNavigationTests()
        runner.page(runner.payload(), """
assert.equal(el('migration-plan-nav').hidden,true);
assert.equal(migrationPlanning,undefined);
assert.equal(reviewSections.includes('migration-plan'),false);
""")


if __name__ == '__main__': unittest.main()
