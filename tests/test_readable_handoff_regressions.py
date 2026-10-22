"""Synthetic browser exports preserve selected pipeline and download contracts."""
import base64
import json
import shutil
import unittest

import test_migration_planning_portal as planning_fixtures
import test_omni_handoff as semantic_fixtures
import test_portal_navigation as navigation

portal = semantic_fixtures.portal


@unittest.skipUnless(shutil.which('node'), 'Node required for offline browser exports')
class ReadableHandoffRegressionTests(unittest.TestCase):
    @unittest.skipUnless(semantic_fixtures.omni.yaml is not None
                         and semantic_fixtures.omni.sqlglot is not None,
                         'Pinned YAML and SQL runtime required for semantic fixture')
    def test_omitted_shared_semantics_recounts_disconnected_bronze_variants(self):
        helper = semantic_fixtures.OmniHandoffTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.review['package_layout_version'] = 2
        helper.review['models'] = [
            {'id': 'bronze.' + suffix, 'name': 'bronze.' + suffix, 'layer': 'bronze',
             'columns': [{'name': 'DICTIONARY_ONLY_' + suffix, 'type': 'NUMBER', 'key': 'PK'}]}
            for suffix in ('a', 'b')]
        helper.review['relationships'] = []
        helper.review['omni_warehouse_bindings'] = [
            {'view_id': 'events', 'model_ids': ['bronze.a', 'bronze.b']}]
        original = helper.package(audience='engineer', include=['documentation', 'diagrams', 'dictionary'])
        data = helper.payload(original)
        self.assertEqual(len(data['diagrams']), 1)
        self.assertEqual(len(data['warehouse_diagrams']), 2)
        self.assertEqual(portal.verify_delivery(original)['status'], 'integrity_verified')
        runner = navigation.PortalNavigationTests()
        for keep_dictionary in (True, False):
            with self.subTest(dictionary=keep_dictionary):
                destination = helper.root / ('warehouse-' + str(keep_dictionary) + '.zip')
                runner.page(data, """
let writeExport;
download=(name,body)=>{writeExport=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.delete('documentation');
if(!KEEP_DICTIONARY)chosen.delete('dictionary');
updateExport();
el('download-package').onclick().then(()=>writeExport).then(()=>{
 assert.match(el('messages').textContent,/Candidate subset created/);
}).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT', json.dumps(str(destination))).replace('KEEP_DICTIONARY', json.dumps(keep_dictionary)))
                self.assertTrue(destination.is_file())
                self.assertEqual(portal.verify_delivery(destination)['status'], 'integrity_verified')
                reduced = helper.payload(destination)
                self.assertEqual(reduced['review']['omni']['evidence_state'], 'not_included')
                self.assertNotIn('omni_warehouse_bindings', reduced['review'])
                self.assertNotIn('warehouse_diagrams', reduced)
                self.assertEqual(reduced['diagram_coverage']['generated'],
                                 {'status': 'verified', 'model_count': 2, 'page_count': 2})
                self.assertEqual({identifier for page in reduced['diagrams'] for identifier in page['model_ids']},
                                 {'bronze.a', 'bronze.b'})
                for page in reduced['diagrams']:
                    self.assertEqual(page['semantic_ids'], [])
                    for key in ('base64', 'without_dictionary_base64'):
                        svg = base64.b64decode(page[key]).decode()
                        self.assertNotIn('data-semantic-id', svg)
                        if key == 'without_dictionary_base64' or not keep_dictionary:
                            self.assertNotIn('DICTIONARY_ONLY_', svg)
                runner.page(reduced, """
assert.equal(pipelineMode,true);assert.equal(shownViews.length,2);
assert.equal(data.diagram_coverage.generated.page_count,2);
assert.equal(omni.evidence_state,'not_included');
""")

    def test_migration_downloads_resolve_exact_binary_files_in_both_layouts(self):
        helper = planning_fixtures.PlanningPortalTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        runner = navigation.PortalNavigationTests()
        for layout, prefix in ((1, '05_Migration/'), (2, '05_Mappings/Migration_Plan/')):
            with self.subTest(layout=layout):
                helper.review['package_layout_version'] = layout
                data = helper.payload()
                selected = [row for row in data['generated_deliverables'] if row['path'].startswith(prefix)]
                self.assertTrue(any(row['path'].endswith('inventory.xlsx') for row in selected))
                self.assertTrue(any(row['path'].endswith('migration-plan.docx') for row in selected))
                runner.page(data, """
location.hash='#migration-plan';navigate();
assert.equal(el('migration-plan').hidden,false);
const expected=allFiles().filter(file=>file.path.startsWith(PREFIX));
const links=el('migration-plan-files').children;
assert.equal(links.length,expected.length);
assert.match(el('migration-plan-files-note').textContent,/Download the inventory first/);
let downloaded;
download=(name,body)=>{downloaded={name,body};};
for(const file of expected){
 const button=links.find(node=>node.title===file.path);assert.ok(button,file.path);
 button.onclick();assert.equal(downloaded.name,file.path.split('/').pop());
 assert.equal(Buffer.from(downloaded.body).toString('hex'),Buffer.from(file.base64,'base64').toString('hex'));
}
""".replace('PREFIX', json.dumps(prefix)))


if __name__ == '__main__':
    unittest.main()
