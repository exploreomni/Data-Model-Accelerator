"""Complete synthetic domains, proposal evidence and disclosure-safe offline exports."""
import base64
import copy
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import portal_checks as checks
import test_portal_navigation as navigation
from test_delivery_portal import fixture


def domain_fixture(root):
    state, review = fixture(root)
    review['models'] = [
        {'id': 'domain.' + str(i), 'name': 'DOMAIN.' + str(i), 'domain': 'Sales', 'layer': 'gold',
         'grain': 'One row per synthetic record', 'columns': [{'name': 'id', 'type': 'NUMBER', 'key': 'PK'}],
         'asset_ids': ['report'], 'mapping_status': 'verified'} for i in range(8)]
    review['models'] += [
        {'id': 'shared.' + str(i), 'name': 'SHARED.' + str(i), 'domain': 'Shared', 'layer': 'gold',
         'grain': 'Shared synthetic dimension', 'columns': [{'name': 'id', 'key': 'PK'}]} for i in range(3)]
    review['assets'] = [{'id': 'report', 'name': 'Sales report'}]
    edge = {'from': 'domain.0', 'to': 'domain.1', 'kind': 'relationship',
            'predicate': 'domain.0.id = domain.1.id', 'cardinality': 'many_to_one', 'status': 'proposed',
            'evidence': 'canonical declaration'}
    review['relationships'] = [edge, {'from': 'domain.1', 'to': 'domain.2', 'kind': 'relationship'},
                               {'from': 'domain.2', 'to': 'domain.0', 'kind': 'lineage'}]
    proposals = [dict(edge, evidence='proposal occurrence'), dict(edge, evidence='proposal occurrence'),
                 dict(edge, cardinality='one_to_one', evidence='conflicting proposal')]
    proposals += [{'from': 'domain.' + str(i+2), 'to': 'shared.' + str(i), 'kind': 'relationship'} for i in range(3)]
    proposals += [{'from': 'domain.' + str(i+4), 'to': 'external.' + str(i), 'kind': 'relationship'} for i in range(2)]
    review['domain_proposals'] = [{'id': 'sales-proposal', 'domain': 'Sales',
        'model_ids': ['domain.' + str(i) for i in range(8)], 'relationships': proposals,
        'reference_endpoints': [{'id': 'external.0'}, {'id': 'external.1'}]}]
    return state, review


class DomainErdTests(unittest.TestCase):
    page = navigation.PortalNavigationTests.page

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state, self.review = domain_fixture(self.root)

    def payload(self, audience='engineer', include=('diagrams', 'dictionary')):
        path = self.root / ('package-' + str(len(list(self.root.glob('package-*')))) + '.zip')
        portal.package_delivery(self.state, self.review, self.root, path, audience, include)
        with zipfile.ZipFile(path) as archive:
            return checks.parse_page(archive.read('START_HERE.html'))[1]

    def test_eight_domain_five_references_two_isolates_and_non_pruning_inspection(self):
        data = self.payload()
        self.assertEqual({'status': 'verified', 'model_count': 11, 'reference_count': 2, 'page_count': 1}, data['diagram_coverage']['generated'])
        self.page(data, """
assert.equal(diagramZoom,1);assert.equal(diagramFitMode,false);
assert(el('model-summary').children.some(node=>node.textContent==='10 declared relationship occurrences'));
el('erd-domain').value='Sales';el('erd-domain').onchange();
assert.equal(erdSelection.domain_count,8);assert.equal(erdSelection.shared_count,3);assert.equal(erdSelection.missing_count,2);
assert.equal(erdSelection.visible.size,13);assert(erdSelection.visible.has('domain.6'));assert(erdSelection.visible.has('domain.7'));
assert(erdSelection.edges.every(e=>e.kind==='relationship'));assert(erdSelection.ledger.some(e=>e.kind==='lineage'));
const before=[...erdSelection.visible];el('architecture-model').value='domain.0';el('architecture-model').onchange();
assert.equal(inspectedModel,'domain.0');assert.deepEqual([...erdSelection.visible],before);
revealModel('domain.7');assert.deepEqual([...erdSelection.visible],before);assert.equal(inspectedModel,'domain.7');
el('erd-dependencies').checked=true;el('erd-dependencies').onchange();assert(erdSelection.edges.some(e=>e.kind==='lineage'));
assert.match(currentDiagram.svg,/Reference only/);assert.match(currentDiagram.svg,/Shared reference/);
assert.match(el('diagram-coverage').textContent,/3 shared references/);assert.match(el('diagram-coverage').textContent,/2 missing definitions/);
""")

    def test_occurrences_conflicts_and_python_browser_normalization_agree(self):
        original = copy.deepcopy(self.review)
        nodes, edges = checks.erd_inventory(self.review)
        self.assertEqual(self.review, original)
        self.assertEqual(len(nodes), 13)
        self.assertEqual(len(edges), 11)
        parallel = [edge for edge in edges if edge['from'] == 'domain.0' and edge['to'] == 'domain.1']
        self.assertEqual(len(parallel), 4)
        self.assertTrue(all(edge['conflicting_definitions'] for edge in parallel))
        self.assertEqual([edge['duplicate_occurrences'] for edge in parallel], [3, 3, 3, 1])
        self.page(self.payload(), 'assert.deepEqual(graph.edges,' + json.dumps(edges) + ');')

    def test_missing_endpoints_are_explicit_and_canonical_validation_is_unchanged(self):
        self.review['domain_proposals'][0]['reference_endpoints'].pop()
        with self.assertRaisesRegex(ValueError, 'explicit reference_endpoints'):
            portal.validate_review(self.state, self.review)
        self.state, self.review = domain_fixture(self.root)
        self.review['relationships'].append({'from': 'domain.0', 'to': 'absent', 'kind': 'relationship'})
        with self.assertRaisesRegex(ValueError, 'absent model'):
            portal.validate_review(self.state, self.review)

    def test_proposal_validation_rejects_invalid_identity_and_embedded_private_definitions(self):
        for mutate in (
            lambda p: p.update(model_ids=['absent']),
            lambda p: p['reference_endpoints'][0].update(columns=[{'name': 'PRIVATE_COLUMN'}]),
            lambda p: p['reference_endpoints'][0].update(id='shared.0'),
            lambda p: p['relationships'].append({'from': 'shared.0', 'to': 'shared.1', 'kind': 'ambiguous'}),
        ):
            changed = copy.deepcopy(self.review); mutate(changed['domain_proposals'][0])
            with self.assertRaises(ValueError): portal.validate_review(self.state, changed)

    def test_asset_exclusions_do_not_reappear_as_reference_blocks_or_exported_joins(self):
        data = self.payload(); path = self.root / 'scoped.zip'
        self.page(data, """
el('erd-domain').value='Sales';el('erd-domain').onchange();el('asset-filter').value='report';el('asset-filter').onchange();
assert.equal(erdSelection.domain_count,8);assert.equal(erdSelection.shared_count,0);assert.equal(erdSelection.missing_count,2);
assert.equal(erdSelection.hidden_connections,3);assert.equal(erdSelection.hidden_references,3);assert(!erdSelection.visible.has('shared.0'));
el('erd-search').value='DOMAIN.0';el('erd-search').oninput();assert.equal(erdSelection.domain_count,1);
let saved;download=(name,body)=>{assert.equal(name,'complete-domain-erd.zip');saved=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
el('diagram-download-all').onclick();Promise.resolve().then(()=>saved);
""".replace('OUTPUT', json.dumps(str(path))))
        with zipfile.ZipFile(path) as archive:
            index = json.loads(archive.read('MODEL_INDEX.json'))
            self.assertEqual(len(index['domain_model_ids']), 8)
            self.assertEqual(len(index['reference_ids']), 2)
            self.assertFalse(any('shared.' in edge['from'] + edge['to'] for edge in index['relationships']))
            self.assertEqual(index['hidden_connections'], 3)

    def test_empty_joins_long_names_keys_grain_cycles_and_large_partition_coverage(self):
        self.page(self.payload(), """
const title='WAREHOUSE.'+'long_identifier_'.repeat(12),grain='one record for '+'grain_description_'.repeat(10),key='primary_key_'.repeat(12);
const sample=[{id:'a',name:title,layer:'gold',grain,columns:[{name:key,key:'PK'}]},{id:'b',layer:'gold'},{id:'isolate',layer:'gold'}];
const noJoins=selectErd(modelGraph(sample,[]),{focus:'a'});assert.equal(noJoins.nodes.length,3);assert.equal(noJoins.edges.length,0);
const svg=filteredModelSvg(sample,[],new Set(),0,true),allLabels=svg.replace(/<[^>]*>/g,'');
assert(allLabels.includes(title));assert(allLabels.includes(grain));assert(allLabels.includes(key));assert(!svg.includes('…'));
const many=Array.from({length:200},(_,i)=>({id:'m'+String(i).padStart(3,'0'),layer:'gold',domain:'Synthetic'}));
const joins=many.map((m,i)=>({from:m.id,to:many[(i+1)%many.length].id,kind:'relationship'}));
const scope=selectErd(modelGraph(many,joins),{domain:'Synthetic',focus:'m050'}),pages=erdPages(scope);
assert.equal(new Set(pages.flatMap(p=>p.model_ids)).size,200);assert.equal(pages.length,6);
assert(pages.every(p=>p.nodes.length<=36));assert(pages.some(p=>p.cross_view_connections>0));
""")

    def test_keys_without_columns_remain_declared_and_missing_metadata_is_explicit(self):
        models = [{'id': 'keys_only', 'layer': 'gold', 'keys': ['source_event_identifier']},
                  {'id': 'unknown_keys', 'layer': 'gold'}]
        svg = portal.model_svg(models, [])
        self.assertIn('Declared key source_event_identifier', svg)
        self.assertIn('Type unverified', re.sub('<[^>]*>', '', svg))
        self.assertIn('Keys not supplied', svg)
        self.page(self.payload(), """
const keyOnly=filteredModelSvg([{id:'keys_only',layer:'gold',keys:['source_event_identifier']}],[]);
assert.match(keyOnly,/Declared key source_event_identifier/);assert.match(keyOnly.replace(/<[^>]*>/g,''),/Type unverified/);assert(!keyOnly.includes('PK'));
const unknown=filteredModelSvg([{id:'missing',layer:'reference',reference_only:true}],[]);
assert.match(unknown,/Keys not supplied/);assert.match(unknown,/Reference only/);assert(!unknown.includes('PK'));
""")

    def test_domain_proposal_disconnected_shared_components_and_asset_anchor(self):
        self.review['domain_proposals'][0]['relationships'] += [
            {'from': 'shared.0', 'to': 'shared.1', 'kind': 'relationship'},
            {'from': 'shared.1', 'to': 'external.disconnected', 'kind': 'relationship'},
            {'from': 'external.pair1', 'to': 'external.pair2', 'kind': 'relationship'}]
        self.review['domain_proposals'][0]['reference_endpoints'] += [
            {'id': identifier} for identifier in ['external.disconnected', 'external.pair1', 'external.pair2']]
        self.page(self.payload(), """
el('erd-domain').value='Sales';el('erd-domain').onchange();
assert.equal(erdSelection.domain_count,8);assert.equal(erdSelection.shared_count,3);assert.equal(erdSelection.missing_count,5);
assert(erdSelection.visible.has('external.pair1'));assert(erdSelection.visible.has('external.disconnected'));
assert(erdSelection.edges.some(e=>e.from==='shared.0'&&e.to==='shared.1'));
el('asset-filter').value='report';el('asset-filter').onchange();
assert.equal(erdSelection.domain_count,8);assert.equal(erdSelection.shared_count,0);assert.equal(erdSelection.missing_count,2);
assert(!erdSelection.visible.has('external.pair1'));assert(!erdSelection.visible.has('external.disconnected'));assert.equal(erdSelection.hidden_references,6);assert.equal(erdSelection.hidden_connections,6);
assert(!erdSelection.visible.has('shared.0'));
""")

    def test_column_bindings_and_notation_are_conflicts_not_duplicate_claims(self):
        first = self.review['relationships'][0]
        first.update(from_columns=['customer_id'], to_columns=['id'], label='customer')
        proposal = self.review['domain_proposals'][0]
        proposal['relationships'] = [dict(first, from_columns=['billing_id']), dict(first, notation='one-to-many')]
        proposal['reference_endpoints'] = []
        edges = checks.erd_inventory(self.review)[1]
        related = [edge for edge in edges if edge['from'] == 'domain.0' and edge['to'] == 'domain.1']
        self.assertEqual([edge['duplicate_occurrences'] for edge in related], [1, 1, 1])
        self.assertTrue(all(edge['conflicting_definitions'] for edge in related))
        self.page(self.payload(), 'assert.deepEqual(graph.edges,' + json.dumps(edges) + ');' + """
const joinedSvg=filteredModelSvg(graph.nodes,graph.edges),arrowCount=(joinedSvg.match(/marker-end=/g)||[]).length;
assert.equal(arrowCount,graph.edges.filter(e=>e.kind==='lineage').length);
""")
        svg = portal.model_svg(*checks.erd_inventory(self.review))
        self.assertEqual(svg.count('marker-end='), 1)

    def test_lineage_only_context_waits_for_overlay_but_ledger_retains_evidence(self):
        self.review['models'] += [
            {'id': 'dependency.explicit', 'layer': 'silver', 'domain': 'Upstream'},
            {'id': 'dependency.derived', 'layer': 'silver', 'domain': 'Upstream'},
            {'id': 'dependency.disconnected_a', 'layer': 'silver', 'domain': 'Upstream'},
            {'id': 'dependency.disconnected_b', 'layer': 'silver', 'domain': 'Upstream'}]
        self.review['models'][0]['depends_on'] = ['dependency.derived']
        self.review['relationships'].append({'from': 'domain.0', 'to': 'dependency.explicit', 'kind': 'lineage'})
        self.review['domain_proposals'][0]['relationships'].append(
            {'from': 'dependency.disconnected_a', 'to': 'dependency.disconnected_b', 'kind': 'lineage'})
        path=self.root/'complete-lineage.zip'
        self.page(self.payload(), """
el('erd-domain').value='Sales';el('erd-domain').onchange();
assert.equal(erdSelection.visible.size,13);assert.equal(erdSelection.shared_count,3);assert.equal(erdSelection.hidden_references,0);
assert(!erdSelection.visible.has('dependency.explicit'));assert(!erdSelection.visible.has('dependency.derived'));assert(!erdSelection.visible.has('dependency.disconnected_a'));
assert(erdSelection.ledger.some(e=>e.to==='dependency.explicit'));assert(erdSelection.ledger.some(e=>e.from==='dependency.derived'));assert(erdSelection.ledger.some(e=>e.from==='dependency.disconnected_a'));
let saved;download=(name,body)=>{saved=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
el('diagram-download-all').onclick();Promise.resolve().then(()=>saved);
el('erd-dependencies').checked=true;el('erd-dependencies').onchange();
assert.equal(erdSelection.visible.size,17);assert.equal(erdSelection.shared_count,7);assert(erdSelection.edges.some(e=>e.from==='dependency.derived'));
el('erd-dependencies').checked=false;el('erd-dependencies').onchange();assert.equal(erdSelection.visible.size,13);
const restricted=selectErd(graph,{domain:'Sales',allowed:new Set(Array.from({length:8},(_,i)=>'domain.'+i))});
assert(!restricted.ledger.some(e=>e.from.startsWith('dependency.')||e.to.startsWith('dependency.')));
""".replace('OUTPUT',json.dumps(str(path))))
        with zipfile.ZipFile(path) as archive:
            index=json.loads(archive.read('MODEL_INDEX.json'))
        self.assertEqual(len(index['model_ids']),13)
        self.assertFalse(index['dependencies_displayed'])
        self.assertEqual(set(index['ledger_only_model_ids']), {
            'dependency.explicit','dependency.derived','dependency.disconnected_a','dependency.disconnected_b'})

    def test_audit_and_code_only_never_embed_proposal_payload_and_subset_reopens(self):
        self.review['domain_proposals'][0]['relationships'][0]['evidence'] = 'PROPOSAL_PRIVATE_MARKER'
        for audience, include in [('audit', ['technical_audit']), ('engineer', ['implementation'])]:
            data = self.payload(audience, include)
            self.assertNotIn('PROPOSAL_PRIVATE_MARKER', json.dumps(data))
            self.assertNotIn('domain_proposals', data.get('review', {}))
        data = self.payload(); path = self.root / 'subset.zip'
        self.page(data, """
let saved;download=(name,body)=>{saved=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.delete('dictionary');el('download-package').onclick().then(()=>saved).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT', json.dumps(str(path))))
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')
        with zipfile.ZipFile(path) as archive:
            updated = checks.parse_page(archive.read('START_HERE.html'))[1]
            source = json.loads(archive.read('01_Model/ERD/model-source.json'))
        self.assertEqual(len(source['relationship_ledger']), 11)
        self.assertEqual(updated['diagram_coverage']['generated']['reference_count'], 2)


if __name__ == '__main__': unittest.main()
