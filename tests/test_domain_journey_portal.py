"""Domain queue review and request-only controls; no browser or native approval proof."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import test_portal_navigation as navigation
import test_guided_review_workflow as guided
from test_delivery_portal import fixture

portal = navigation.portal


def journey():
    return {'schema_version': 1, 'kind': 'domain_journey', 'active_domain_id': 'orders',
        'candidates_sha256': 'd' * 64,
        'needs_selection': False, 'next_action': 'Review the Orders design.',
        'qualification': 'Recorded progress only; completion is not native validation.',
        'counts': {'total': 3, 'active': 1, 'stale': 1, 'completed': 1},
        'domains': [
            {'id': 'orders', 'name': 'Orders', 'description': 'Order facts and reporting.', 'status': 'active',
             'model_ids': ['gold.orders'], 'asset_count': 2, 'shared_dependency_ids': ['silver.orders'],
             'design_status': 'needs_review', 'implementation_status': 'not_started',
             'semantic_status': 'not_started', 'completion_kind': None, 'next_action': 'Review keys and grain.'},
            {'id': 'staging', 'name': 'Staging', 'description': 'Staging entities.', 'status': 'stale',
             'model_ids': ['bronze.orders'], 'asset_count': 1, 'shared_dependency_ids': [],
             'design_status': 'stale', 'implementation_status': 'artifact_recorded',
             'semantic_status': 'not_requested', 'completion_kind': None, 'next_action': 'Refresh source evidence.'},
            {'id': 'shared', 'name': 'Shared', 'description': 'Shared definitions.', 'status': 'completed',
             'model_ids': ['silver.orders'], 'asset_count': 1, 'shared_dependency_ids': [],
             'design_status': 'approved', 'implementation_status': 'artifact_recorded',
             'semantic_status': 'not_requested', 'completion_kind': 'requested_scope',
             'next_action': 'Choose the next domain.'}]}


class DomainJourneyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state, self.review = fixture(self.root)
        self.state['workflow'] = {'design': {'id': 'design-1', 'revision': 2, 'sha256': 'a' * 64},
                                  'domain_journey': {'retained_evidence': 'PRIVATE_DOMAIN_RECORD'}}
        self.review['design_binding'] = copy.deepcopy(self.state['workflow']['design'])
        self.public = patch('engagement_stages.public_view', return_value=guided.workflow_view())
        self.public.start(); self.addCleanup(self.public.stop)

    def package(self, categories, audience='engineer', raw=None):
        path = self.root / ('package-' + str(len(list(self.root.glob('*.zip')))) + '.zip')
        module = types.SimpleNamespace(public_summary=lambda state, allowed: journey() if raw is None else raw)
        with patch.dict(sys.modules, {'domain_workflow': module}), patch.object(module, 'public_summary', wraps=module.public_summary) as selected:
            portal.package_delivery(self.state, self.review, self.root, path, audience, categories)
        with zipfile.ZipFile(path) as archive: page = archive.read('START_HERE.html').decode()
        return path, json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0]), selected

    def test_projection_removes_private_evidence_and_unknown_fields(self):
        raw = journey()
        raw['receipts'] = 'PRIVATE_AUTHORITY'
        raw['domains'][0].update(source_path='PRIVATE_PATH', sql='PRIVATE_QUERY', approval={'receipt': 'PRIVATE_RECEIPT'})
        raw['counts']['PRIVATE_KEY'] = 11
        actual = portal._domain_presentation(raw)
        self.assertNotIn('PRIVATE_', json.dumps(actual))
        self.assertEqual(actual['domains'][0]['shared_dependency_ids'], ['silver.orders'])
        self.assertEqual(actual['domains'][2]['completion_kind'], 'requested_scope')

    def test_trimming_design_details_removes_domain_payload(self):
        data = {'review': {}, 'domain_journey': portal._domain_presentation(journey())}
        portal._trim_workflow_details(data)
        self.assertNotIn('domain_journey', data)

    def test_explicit_reviews_pass_exact_model_scope_and_status_can_show_future_domains(self):
        path, data, selected = self.package(['documentation'])
        selected.assert_called_once_with(self.state, {row['id'] for row in self.review['models']})
        self.assertEqual(data['domain_journey'], portal._domain_presentation(journey()))
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')
        self.review['models'] = []; self.review['relationships'] = []
        _, _, selected = self.package(['documentation'], raw={**journey(), 'domains': []})
        selected.assert_called_once_with(self.state, set())
        module = types.SimpleNamespace(public_summary=lambda state, allowed: journey())
        with patch.dict(sys.modules, {'domain_workflow': module}), patch.object(module, 'public_summary', wraps=module.public_summary) as selected:
            portal._presentation(self.state)
        selected.assert_called_once_with(self.state, None)

    def test_code_only_audit_and_absent_feature_omit_domain_records(self):
        for categories, audience in ((['implementation'], 'engineer'), (['technical_audit'], 'audit')):
            path, data, selected = self.package(categories, audience)
            self.assertNotIn('domain_journey', data)
            self.assertNotIn('Order facts and reporting.', json.dumps(data))
            if audience == 'audit': selected.assert_not_called()
            self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')
        self.state['workflow'].pop('domain_journey')
        _, data, selected = self.package(['documentation'])
        selected.assert_not_called(); self.assertNotIn('domain_journey', data)

    def test_actual_module_scopes_domains_and_shared_dependencies_without_private_paths(self):
        import domain_workflow
        self.state['workflow'].pop('domain_journey')
        self.state['workflow'].update(approvals=[], tasks=[])
        models = copy.deepcopy(self.review['models'])
        for row, domain in zip(models, ('private', 'shared', 'orders')):
            row.update(domain=domain, depends_on=['silver.orders'] if domain == 'orders' else [])
        self.state['workflow']['design']['entities'] = models
        domain_workflow.register(self.state, {'schema_version': 1, 'domains': [
            {'id': name, 'name': name.title(), 'description': 'Domain ' + name,
             'asset_ids': ['report.' + name], 'source_paths': ['PRIVATE_' + name + '.sql'],
             'shared_dependency_ids': ['silver.orders'] if name == 'orders' else []}
            for name in ('orders', 'shared', 'private', 'future')]})
        full = portal._presentation(self.state)['domain_journey']
        self.assertEqual({row['id'] for row in full['domains']}, {'orders', 'shared', 'private', 'future'})
        self.assertTrue(full['needs_selection'])
        self.review['models'] = models[1:]; self.review['relationships'] = []
        scoped = portal._presentation(self.state, self.review)['domain_journey']
        self.assertEqual({row['id'] for row in scoped['domains']}, {'orders', 'shared'})
        self.assertNotIn('PRIVATE_', json.dumps(scoped))
        self.assertNotIn('bronze.orders', json.dumps(scoped))
        self.assertNotIn('future', json.dumps(scoped))
        # Declared but untraversed shared references must not escape the same allowlist.
        request = {'schema_version': 1, 'domains': copy.deepcopy(self.state['workflow']['domain_journey']['domains'])}
        request['domains'][0]['shared_dependency_ids'].append('bronze.orders')
        domain_workflow.register(self.state, request)
        scoped = portal._presentation(self.state, self.review)['domain_journey']
        self.assertNotIn('bronze.orders', json.dumps(scoped))
        self.review['models'] = []
        empty = portal._presentation(self.state, self.review)['domain_journey']
        self.assertEqual(empty['domains'], [])


@unittest.skipUnless(shutil.which('node'), 'Node required for offline DOM checks')
class DomainJourneyBrowserTests(unittest.TestCase):
    page = navigation.PortalNavigationTests.page

    def payload(self, raw=None):
        data = navigation.PortalNavigationTests.payload(self)
        data['domain_journey'] = portal._domain_presentation(journey() if raw is None else raw)
        return data

    def test_first_click_route_and_selection_never_change_recorded_state(self):
        data = self.payload()
        self.page(data, r"""
const before=JSON.stringify(data);
assert.equal(el('domain-journey-nav').hidden,false);
assert.equal(el('domain-journey').hidden,false);assert.equal(el('model').hidden,true);
document.getElementById('nav:domain-journey').onclick();assert.equal(el('domain-journey').focused,true);
assert.match(el('domain-journey-attention').textContent,/stale/);
assert.equal(el('domain-request-copy').disabled,true);
el('domain-choice').value='staging';el('domain-choice').onchange();
assert.equal(el('domain-request-copy').disabled,false);
assert.match(el('domain-request').value,/staging/);
const request=JSON.parse(el('domain-request').value.split('\n\n')[1]);
assert.deepEqual(Object.keys(request).sort(),['candidates_sha256','domain_id','request_reference','schema_version']);
assert.equal(request.candidates_sha256,data.domain_journey.candidates_sha256);
assert.equal(request.domain_id,'staging');
assert.match(el('domain-request-note').textContent,/active domain has not changed/);
assert.equal(data.domain_journey.active_domain_id,'orders');assert.equal(JSON.stringify(data),before);
el('domain-request-copy').onclick().then(()=>assert.equal(el('domain-request').selected,true));
el('domain-choice').value='excluded';el('domain-choice').onchange();
assert.equal(el('domain-request-copy').disabled,true);assert.equal(el('domain-request').value,'');
""", prefix="location.hash='#domain-journey';", second_boot=True)

    def test_predesign_selection_is_first_route_and_empty_inventory_is_explicit(self):
        raw = journey(); raw['active_domain_id'] = None; raw['needs_selection'] = True
        for row in raw['domains']: row['model_ids'] = []; row['status'] = 'proposed'
        data = self.payload(raw)
        data['review']['models'] = []; data['review']['relationships'] = []
        data.pop('diagrams', None); data.pop('diagram_contract_version', None); data.pop('diagram_coverage', None)
        data.pop('generated_deliverables', None); data.pop('package_layout_version', None)
        self.page(data, """
assert.equal(el('domain-journey').hidden,false);
assert.match(el('domain-journey-attention').textContent,/Choose a domain/);
assert.equal(el('domain-choice').children.length,3);
assert.equal(el('domain-request-copy').disabled,true);
""", prefix="location.hash='';")
        raw['domains'] = []
        self.page(self.payload(raw), """
assert.equal(el('domain-journey-domains').querySelector('table'),null);
assert.equal(el('domain-request-copy').disabled,true);
""")

    def test_domain_labels_render_as_text_and_absent_feature_has_no_route(self):
        raw = journey(); raw['domains'][0]['name'] = '<script>synthetic()</script>'
        self.page(self.payload(raw), """
assert.equal(el('domain-journey-domains').querySelector('script'),null);
el('domain-choice').value='orders';el('domain-choice').onchange();
assert.match(el('domain-request').value,/<script>/);
""")
        self.page(navigation.PortalNavigationTests.payload(self), """
assert.equal(el('domain-journey-nav').hidden,true);assert.equal(reviewSections.includes('domain-journey'),false);
location.hash='#domain-journey';listeners.hashchange[0]();assert.equal(el('model').hidden,false);
""")

    def test_unbound_legacy_journey_cannot_create_a_selection_document(self):
        raw = journey(); raw.pop('candidates_sha256')
        self.page(self.payload(raw), """
el('domain-choice').value='orders';el('domain-choice').onchange();
assert.equal(el('domain-request-copy').disabled,true);assert.equal(el('domain-request').value,'');
assert.match(el('domain-request-note').textContent,/refresh the journey/);
""")
    def test_browser_subsets_preserve_documentation_and_omit_code_only_details(self):
        data = self.payload()
        with tempfile.TemporaryDirectory() as tmp:
            for categories in (['documentation'], ['implementation']):
                path = Path(tmp).resolve() / (categories[0] + '.zip')
                self.page(data, """
let writeExport;download=(name,body)=>{writeExport=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.clear();for(const category of CATEGORIES)chosen.add(category);updateExport();
el('download-package').onclick().then(()=>writeExport).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT', json.dumps(str(path))).replace('CATEGORIES', json.dumps(categories)))
                self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')
                with zipfile.ZipFile(path) as archive:
                    page = archive.read('START_HERE.html').decode()
                selected = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
                if categories == ['documentation']:
                    self.assertEqual(selected['domain_journey'], data['domain_journey'])
                    self.page(selected, "assert.equal(el('domain-journey-nav').hidden,false);")
                else:
                    self.assertNotIn('domain_journey', selected)
                    self.assertNotIn('Order facts and reporting.', page)
                    self.page(selected, "assert.equal(el('domain-journey-nav').hidden,true);")


if __name__ == '__main__': unittest.main()
