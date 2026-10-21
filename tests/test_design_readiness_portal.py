"""Scoped local presentation checks; synthetic DOM is not native/browser QA."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import test_portal_navigation as navigation
from test_delivery_portal import fixture
from test_design_builder import request
import design_builder
import design_readiness
import engagement_stages
from design_consistency import project_review
from ae_common import hash_json

portal = navigation.portal


def design():
    value = request()
    value['nodes'][1].update(history='Current state only', security='Tenant restriction proposed')
    value['nodes'][1]['columns'][0].update(key='PK', nullable=False)
    value['nodes'][2]['columns'] = [{'name': 'customer_id', 'type': 'integer', 'description': 'Supplied interface identifier'}]
    value['edges'][1].update(from_columns=['order_id'], to_columns=['customer_id'])
    doc = design_builder.assemble(value)
    doc['sha256'] = hash_json(doc)
    return doc


def view(state):
    projected = project_review(state['workflow']['design'])
    return {**projected, 'schema_version': 1, 'design_readiness': design_readiness.summarize(state),
            'stages': [], 'decisions': [], 'authoring_checks': [], 'artifact_checks': []}


class ReadinessProjectionTests(unittest.TestCase):
    def test_canonical_details_and_scoped_summary_drop_private_fields(self):
        doc = design()
        state = {'workflow': {'design': doc, 'approvals': []}}
        raw = view(state)
        raw['models'][1]['source_paths'] = ['PRIVATE_SOURCE_PATH']
        raw['models'][1]['columns'][0]['raw_payload'] = 'PRIVATE_COLUMN'
        readiness = raw['design_readiness']
        readiness['source_path'] = 'PRIVATE_ROOT'
        readiness['counts']['private'] = 5
        readiness['counts']['by_layer']['private'] = 2
        readiness['coverage']['findings'] = [{'code': 'unresolved', 'message': 'Resolve source coverage',
            'model_ids': ['orders'], 'domain_ids': ['sales'], 'path': 'PRIVATE_FINDING'}]
        projected = portal._workflow_presentation(raw)
        self.assertNotIn('PRIVATE_', json.dumps(projected))
        self.assertNotIn('private', projected['design_readiness']['counts'])
        self.assertNotIn('private', projected['design_readiness']['counts']['by_layer'])
        model = projected['models'][1]
        for key in ('object_kind', 'keys', 'history', 'security'):
            self.assertEqual(model[key], doc['entities'][1][key])
        self.assertEqual(model['columns'][0]['key'], 'PK')
        self.assertIs(model['columns'][0]['nullable'], False)
        self.assertEqual(projected['relationships'][1]['from_columns'], ['order_id'])
        self.assertEqual(projected['relationships'][1]['to_columns'], ['customer_id'])
        self.assertEqual(projected['design_readiness']['counts']['models'], 1)
        self.assertEqual(projected['design_readiness']['counts']['sources'], 1)
        self.assertEqual(projected['design_readiness']['counts']['interfaces'], 1)

    def test_evidence_basis_counts_are_allowlisted_and_typed(self):
        raw = view({'workflow': {'design': design(), 'approvals': []}})
        expected = {'observed_metadata': 0, 'repository_declaration': 2, 'user_assertion': 1, 'proposal': 3}
        raw['design_readiness']['evidence'].update(counts={**expected, 'private': 99,
            'raw_payload': 'PRIVATE_COUNTS'}, source_path='PRIVATE_PATH')
        projected = portal._workflow_presentation(raw)['design_readiness']['evidence']
        self.assertEqual(projected['counts'], expected)
        self.assertNotIn('PRIVATE_', json.dumps(projected))
        raw['design_readiness']['evidence']['counts'] = {
            'observed_metadata': False, 'repository_declaration': -1, 'user_assertion': '1', 'proposal': 0}
        self.assertEqual(portal._workflow_presentation(raw)['design_readiness']['evidence']['counts'], {'proposal': 0})

    def test_explicit_review_recomputes_readiness_for_exact_included_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, review = fixture(Path(tmp).resolve())
            state['workflow'] = {'design': design(), 'approvals': []}
            derived = project_review(state['workflow']['design'])
            review.update({key: derived[key] for key in ('models', 'relationships', 'assets', 'design_binding')})
            review['models'] = [row for row in review['models'] if row['id'] == 'customers']
            review['relationships'] = []
            with patch.object(engagement_stages, 'public_view', view):
                data = portal._presentation(state, review)
            summary = data['workflow']['design_readiness']
            self.assertEqual(summary['counts']['objects'], 1)
            self.assertEqual(summary['counts']['models'], 0)
            self.assertEqual(summary['counts']['sources'], 0)
            self.assertEqual(summary['counts']['interfaces'], 1)
            self.assertEqual(summary['independent_review']['expected_objects'], 1)
            self.assertEqual(summary['native_validation']['status'], 'unassessed')

    def test_server_reduced_exports_remove_readiness_and_companions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state, review = fixture(root)
            state['workflow'] = {'design': design(), 'approvals': []}
            derived = project_review(state['workflow']['design'])
            review.update({key: derived[key] for key in ('models', 'relationships', 'assets', 'design_binding')})
            for audience, categories in [('engineer', ['documentation']), ('engineer', ['implementation']), ('audit', ['technical_audit'])]:
                path = root / (audience + categories[0] + '.zip')
                with patch.object(engagement_stages, 'public_view', view):
                    portal.package_delivery(state, review, root, path, audience, categories)
                with zipfile.ZipFile(path) as archive:
                    page = archive.read('START_HERE.html').decode()
                payload = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
                self.assertEqual('design_readiness' in payload.get('workflow', {}), categories == ['documentation'])
                self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    def test_portable_svg_distinguishes_interface_and_preserves_bindings(self):
        projected = project_review(design())
        svg = portal.model_svg(projected['models'], projected['relationships'])
        self.assertIn('External interface', svg)
        self.assertIn('fill="#eef3ff" stroke="#62549a" stroke-dasharray="6 4"', svg)
        self.assertIn('order_id → customer_id', svg)
        self.assertEqual(svg.count('<g data-model-id='), 3)


@unittest.skipUnless(shutil.which('node'), 'Node required for synthetic DOM checks')
class ReadinessPortalTests(unittest.TestCase):
    page = navigation.PortalNavigationTests.page

    def payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, review = fixture(Path(tmp).resolve())
            state['workflow'] = {'design': design(), 'approvals': []}
            projected = project_review(state['workflow']['design'])
            review.update({key: projected[key] for key in ('models', 'relationships', 'assets', 'design_binding')})
            with patch.object(engagement_stages, 'public_view', view):
                data = portal._presentation(state, review)
            data['diagrams'] = portal.diagram_views(projected['models'], projected['relationships'])
            portal._set_diagram_coverage(data)
            return data

    def test_object_types_inspector_and_domain_counts(self):
        self.page(self.payload(), """
const content=node=>[node.textContent,...node.children.map(content)].join(' ');
assert.equal(graph.byId.get('customers').object_kind,'interface');
assert.equal(erdSelection.nodes.length,3);
assert.match(content(el('model-summary')),/Models: 1.*Sources: 1.*External interfaces: 1/);
assert.match(currentDiagram.svg,/External interface/);assert.match(currentDiagram.svg,/#eef3ff/);
inspectModel('orders');assert.match(content(el('inspector-summary')),/Current state only/);
assert.match(content(el('inspector-summary')),/Tenant restriction proposed/);
assert.match(content(el('inspect-columns')),/PK/);assert.match(content(el('inspect-columns')),/Not nullable/);
assert.match(content(el('inspect-relationships')),/order_id → customer_id/);
inspectModel('customers');assert.match(content(el('inspector-summary')),/External interface only/);
el('erd-domain').value='shared';el('erd-domain').onchange();
assert.match(content(el('model-summary')),/Models: 0.*Sources: 0.*External interfaces: 1/);
assert.match(el('design-readiness-note').textContent,/Diagram filters change the visible counts, not these checks/);
assert.equal(workflow.design_readiness.counts.models,1);
""")

    def test_consistent_structure_does_not_turn_gaps_or_native_green(self):
        data = self.payload()
        summary = data['workflow']['design_readiness']
        summary['structural'] = {'status': 'consistent', 'findings': 0, 'unknowns': 0}
        summary['coverage']['status'] = 'partial'
        summary['evidence']['status'] = 'gaps'
        self.page(data, """
const content=node=>[node.textContent,...node.children.map(content)].join(' ');
assert.equal(el('design-readiness').hidden,false);
const status=content(el('design-readiness-statuses'));
assert.match(status,/Structure: consistent/);assert.match(status,/Source coverage: partial/);
assert.match(status,/Evidence: gaps/);assert.match(status,/Independent review: unassessed/);
assert.match(status,/Human review: unassessed/);assert.match(status,/Native validation: unassessed/);
assert.equal(el('design-readiness-statuses').children.length,6);
assert.equal(el('design-readiness-statuses').children.some(n=>/pass|success|ready/.test(n.className)),false);
assert.match(el('design-readiness-note').textContent,/separate/);
""")

    def test_client_subset_and_audit_remove_readiness(self):
        self.page(self.payload(), """
for(const audience of ['engineer','audit']){
 const snapshot=JSON.parse(JSON.stringify(data));snapshot.audience=audience;
 for(const key of ['migration_review','domain_journey','legacy_alignment','migration_planning'])snapshot[key]={private:'unselected'};
 trimWorkflowDetails(snapshot,new Set(audience==='audit'?['documentation']:['implementation']));
 assert.equal(snapshot.workflow.design_readiness,undefined);
 for(const key of ['migration_review','domain_journey','legacy_alignment','migration_planning'])assert.equal(snapshot[key],undefined);
 assert.equal(snapshot.review.models,undefined);
}
""")

    def test_evidence_recorded_shows_classifications_without_native_claim(self):
        data = self.payload()
        data['workflow']['design_readiness']['evidence'].update(status='recorded', counts={
            'observed_metadata': 0, 'repository_declaration': 2, 'user_assertion': 1, 'proposal': 3,
            'private': 'PRIVATE_EXTRA'})
        self.page(data, """
const content=node=>[node.textContent,...node.children.map(content)].join(' ');
assert.match(content(el('design-readiness-statuses')),/Evidence: recorded/);
assert.match(content(el('design-readiness-statuses')),/Native validation: unassessed/);
assert.match(el('design-readiness-note').textContent,/Evidence classifications: observed metadata: 0 · repository declarations: 2 · user assertions: 1 · proposals: 3/);
assert.match(el('design-readiness-note').textContent,/Counts classify host-reported claims only; warehouse verification requires separate execution evidence/);
assert.doesNotMatch(el('design-readiness-note').textContent,/PRIVATE_EXTRA/);
assert.equal(el('design-readiness-statuses').children.length,6);
workflow.design_readiness.evidence.counts={proposal:0};renderDesignReadiness();
assert.match(el('design-readiness-note').textContent,/observed metadata: Unassessed/);
assert.match(el('design-readiness-note').textContent,/proposals: 0/);
""")


if __name__ == '__main__':
    unittest.main()
