"""Model review regression: five warehouse tables, exact code bindings, no live execution."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import test_portal_navigation as navigation
from test_delivery_portal import fixture
import delivery_portal as portal
import portal_checks


def workspace_fixture(root):
    state, review = fixture(root)
    names = ['dim_customer', 'dim_product', 'fact_sales', 'fact_returns', 'fact_payments']
    review['title'] = 'Commerce model · five-table review'
    review['description'] = 'Synthetic example: three facts, two dimensions. Candidate design; no warehouse execution.'
    review['models'] = []
    for i, name in enumerate(names):
        key = 'customer_id' if name == 'dim_customer' else 'product_id' if name == 'dim_product' else name[5:] + '_id'
        model = {'id': name, 'name': 'GOLD.' + name.upper(), 'layer': 'gold',
                 'grain': 'One row per ' + name.replace('dim_', '').replace('fact_', '') + ' identifier',
                 'disposition': 'reuse' if i < 2 else 'create',
                 'columns': [{'name': key, 'type': 'NUMBER', 'key': 'PK', 'description': 'Declared row identifier', 'nullable': False}]}
        if i >= 2:
            model['columns'].extend([{'name': 'customer_id', 'type': 'NUMBER', 'key': 'FK', 'description': 'Customer reference'},
                                     {'name': 'product_id', 'type': 'NUMBER', 'key': 'FK', 'description': 'Product reference'},
                                     {'name': 'amount', 'type': 'NUMBER(18,2)', 'description': 'Synthetic example amount'}])
        else:
            model['reuse'] = {'existing_id': 'existing.' + name, 'rationale': 'Retain the recorded conformed dimension.'}
        path = 'models/' + name + '.sql'
        body = ('-- Synthetic code preview only; raw bindings require review\nselect 1 as ' + key + '\n').encode()
        (root / path).write_bytes(body)
        artifact = {'id': 'code-' + name, 'path': path, 'category': 'implementation', 'audiences': ['engineer'],
                    'sha256': hashlib.sha256(body).hexdigest()}
        model['artifact_id'] = artifact['id']
        review['artifacts'].append(artifact)
        review['models'].append(model)
    review['relationships'] = [{'from': fact, 'to': dim, 'kind': 'relationship', 'status': 'proposed',
                                'predicate': fact + '.' + key + ' = ' + dim + '.' + key, 'cardinality': 'many:1'}
                               for fact in names[2:] for dim, key in [('dim_customer', 'customer_id'), ('dim_product', 'product_id')]]
    return state, review


@unittest.skipUnless(shutil.which('node'), 'Node required for offline script checks')
class ModelWorkspaceTests(unittest.TestCase):
    def page(self, *args, **kwargs):
        if args and args[0].get('package_layout_version') == 1:
            args[0]['generated_deliverables'] = portal.generated_deliverables(args[0])
        navigation.PortalNavigationTests.page(self, *args, **kwargs)

    def payload(self, audience='engineer'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state, review = workspace_fixture(root)
            path = root / 'review.zip'
            portal.package_delivery(state, review, root, path, audience, ('documentation', 'diagrams', 'dictionary') + (() if audience == 'reviewer' else ('implementation',)))
            with zipfile.ZipFile(path) as archive:
                return portal_checks.parse_page(archive.read('START_HERE.html'))[1]

    def test_default_model_route_all_five_and_legacy_singleton_partition(self):
        data = self.payload()
        data['diagrams'] = portal.diagram_views(data['review']['models'][:1], []) + portal.diagram_views(data['review']['models'][1:], [])
        portal._set_diagram_coverage(data)
        self.page(data, """
assert.equal(el('model').hidden,false);assert.equal(el('overview').hidden,true);
assert.equal(el('lineage').hidden,true);assert.equal(el('table-dictionary').hidden,true);
assert.equal(shownViews.length,1);assert.equal(currentDiagram.model_ids.length,5);
assert.equal((currentDiagram.svg.match(/<g data-model-id=/g)||[]).length,5);
assert.match(el('diagram-coverage').textContent,/5 of 5 included tables/);
assert.equal(el('inspect-model').children.length,6);assert.equal(el('diagram-view').hidden,true);
assert.match(currentDiagram.svg,/fact_sales|FACT_SALES/);
""", prefix="location.hash='';")

    def test_focus_inspects_without_pruning_and_lineage_does_not_infer_joins(self):
        self.page(self.payload(), """
el('architecture-model').value='dim_customer';el('architecture-model').onchange();
assert.deepEqual([...erdSelection.visible].sort(),['dim_customer','dim_product','fact_payments','fact_returns','fact_sales']);
assert.equal(lineageSelection.visible.size,5);
el('lineage-model').value='dim_customer';el('lineage-model').onchange();
assert.deepEqual([...lineageSelection.visible],['dim_customer']);assert.equal(erdSelection.visible.size,5);
el('erd-disposition').value='create';el('erd-disposition').onchange();assert.equal(erdSelection.visible.size,3);
el('erd-clear').onclick();assert.equal(erdSelection.visible.size,5);assert.equal(lineageSelection.visible.size,1);
""")

    def test_table_inspector_explicit_keys_joins_reuse_and_code(self):
        self.page(self.payload(), """
const textOf=node=>[node.textContent,...(node.children||[]).map(textOf)].join(' ');
inspectModel('dim_customer');assert.match(textOf(el('inspector-summary')),/Reused/);assert.match(textOf(el('inspector-summary')),/existing.dim_customer/);
inspectModel('fact_sales');assert.match(textOf(el('inspect-columns')),/PK/);assert.match(textOf(el('inspect-columns')),/FK/);
assert.match(textOf(el('inspect-relationships')),/fact_sales.customer_id = dim_customer.customer_id/);
assert.match(el('inspect-code-note').textContent,/fact_sales.sql/);assert.match(el('inspect-code-text').textContent,/select 1 as sales_id/);
el('inspect-code-tab').onclick();assert.equal(el('inspect-code').hidden,false);assert.equal(el('inspect-columns').hidden,true);
let copied;Object.defineProperty(globalThis,'navigator',{value:{clipboard:{writeText:async value=>{copied=value;}}},configurable:true});
el('inspect-code-copy').onclick();Promise.resolve().then(()=>assert.match(copied,/select 1 as sales_id/));
assert.equal(columnRole({keys:['id']},{name:'id'}),'Declared key');assert.equal(columnRole({},{name:'customer_id'}),'—');
const model=graph.byId.get('fact_sales');delete model.artifact_id;inspectModel(model.id);
assert.equal(inspectorFile,null);assert.match(el('inspect-code-note').textContent,/No implementation artifact is linked/);
assert.equal(el('inspect-code-copy').disabled,true);
""")

    def test_complete_export_ignores_filters_and_current_export_is_labeled(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [str(Path(tmp)/name) for name in ('current.zip', 'complete.zip')]
            self.page(self.payload(), """
let writes=[];download=(name,body)=>{const output=name==='erd-current-view.zip'?OUTPUTS[0]:OUTPUTS[1];writes.push(body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(output,Buffer.from(buffer))));};
el('erd-search').value='dim_customer';el('erd-search').oninput();assert.equal(currentDiagram.model_ids.length,1);
el('diagram-download').onclick();el('diagram-download-all').onclick();
assert.equal(currentDiagram.model_ids.length,1);assert.match(el('messages').textContent,/all 5 included domain tables/);
Promise.all(writes);
""".replace('OUTPUTS', json.dumps(paths)))
            for path, count in zip(paths, [1, 5]):
                with zipfile.ZipFile(path) as archive:
                    index = json.loads(archive.read('MODEL_INDEX.json'))
                    self.assertEqual(len(index['model_ids']), count)
                    self.assertIn('scope', index)

    def test_reviewer_never_exposes_inspector_code_and_no_design_opens_overview(self):
        data = self.payload('reviewer')
        self.assertNotIn('select 1 as sales_id', json.dumps(data))
        self.page(data, """
inspectModel('fact_sales');assert.equal(inspectorFile,null);assert.equal(el('inspect-code-copy').disabled,true);assert.match(el('inspect-code-note').textContent,/excluded from reviewer/);
""")
        empty = {'engagement': data['engagement'], 'review': {}, 'files': [], 'audience': 'engineer', 'page_mode': 'status', 'file_count': 0, 'selected_categories': [], 'projection': {'selected_artifact_count': 0, 'excluded_artifact_count': 0}}
        self.page(empty, "assert.equal(el('overview').hidden,false);assert.equal(el('diagram-download-all').disabled,true);", prefix="location.hash='';")

    def test_dense_download_keeps_every_declared_relationship_in_index(self):
        data = self.payload()
        data['review']['relationships'] = [{**data['review']['relationships'][0], 'role': 'role-' + str(i)} for i in range(121)]
        data['diagrams'] = portal.diagram_views(data['review']['models'], data['review']['relationships'])
        portal._set_diagram_coverage(data)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'complete.zip'
            self.page(data, """
download=(name,body)=>{assert.equal(name,'complete-domain-erd.zip');body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
el('diagram-download-all').onclick();
""".replace('OUTPUT', json.dumps(str(path))))
            with zipfile.ZipFile(path) as archive:
                index = json.loads(archive.read('MODEL_INDEX.json'))
                self.assertEqual(len(index['model_ids']), 5)
                self.assertEqual(len(index['relationships']), 121)
                self.assertEqual(index['pages'][0]['ledger_only_connections'], 1)


    def test_complete_erd_keeps_long_join_predicate_and_trailing_metadata(self):
        data = self.payload()
        edge = data['review']['relationships'][0]
        edge.update(predicate='customer_key = ' + 'very_long_identifier_' * 12 + 'FINAL_TAIL', role='bill_to', status='authored')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'complete.zip'
            self.page(data, """
download=(name,body)=>{assert.equal(name,'complete-domain-erd.zip');body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
el('diagram-download-all').onclick();
""".replace('OUTPUT',json.dumps(str(path))))
            with zipfile.ZipFile(path) as archive:
                index=json.loads(archive.read('MODEL_INDEX.json'))
                self.assertEqual(index['relationships'][0]['predicate'], edge['predicate'])
                svg=archive.read('erd-001.svg').decode()
                for value in ('FINAL_TAIL', 'many:1', 'bill_to', 'authored'):
                    self.assertIn(value,svg)

    def test_subset_without_dictionary_rebuilds_auxiliary_svgs(self):
        import base64
        data = self.payload()
        data['review']['models'][0]['columns'][0]['name'] = 'COLUMN_MARKER_DICTIONARY_ONLY'
        data['diagrams'] = portal.diagram_views(data['review']['models'], data['review']['relationships'])
        portal._set_diagram_coverage(data)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / 'subset.zip'
            self.page(data, """
let exported;download=(name,body)=>{exported=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.delete('dictionary');el('download-package').onclick().then(()=>exported).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT', json.dumps(str(path))))
            self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')
            with zipfile.ZipFile(path) as archive:
                reduced = portal_checks.parse_page(archive.read('START_HERE.html'))[1]
            self.assertTrue(all('columns' not in row for row in reduced['review']['models']))
            for diagram in reduced['diagrams']:
                self.assertNotIn(b'COLUMN_MARKER_DICTIONARY_ONLY', base64.b64decode(diagram['base64']))
            self.assertEqual(data['files'], reduced['files'])
            self.assertEqual(data['diagram_coverage']['generated'], reduced['diagram_coverage']['generated'])

    def test_coverage_fails_for_invalid_ids_layers_and_missing_table_groups(self):
        self.page(self.payload(), """
assert.throws(()=>filteredModelSvg([{id:'a',layer:'gold'},{id:'a',layer:'gold'}],[]),/duplicate IDs/);
assert.throws(()=>filteredModelSvg([{id:'a',layer:'marts'}],[]),/unsupported layers/);
assert.throws(()=>assertModelCoverage([{id:'a'}],'<svg></svg>'),/ERD coverage failed/);
const hostile=[{id:'a<&"',name:'<script>bad</script>',layer:'gold'}];
const svg=filteredModelSvg(hostile,[]);assert(!svg.includes('<script>'));assertModelCoverage(hostile,svg);
const large=modelGraph(Array.from({length:75},(_,i)=>({id:'m'+i,layer:'gold'})),[]);
const pages=erdPages(selectErd(large));assert.equal(pages.length,3);assert.equal(new Set(pages.flatMap(p=>p.model_ids)).size,75);
""")


if __name__ == '__main__':
    unittest.main()
