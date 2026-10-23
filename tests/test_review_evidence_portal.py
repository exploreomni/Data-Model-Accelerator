"""Coverage/reuse presentation checks; synthetic DOM is not browser or native QA."""
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

import test_portal_navigation as navigation
import test_guided_review_workflow as guided
from test_delivery_portal import fixture

portal = navigation.portal


def evidence_view():
    return {
        'coverage': {
            'status': 'needs_review',
            'counts': {'total': 3, 'mapped': 1, 'unresolved': 1, 'unsupported': 1,
                       'excluded_by_review': 0, 'stale': 1},
            'supplied_files': {'expected': 4, 'observed': 3, 'missing': 1,
                               'statuses': {'parsed': 2, 'partial': 1, 'unsupported': 0}},
            'groups': [{'asset': 'orders.csv', 'domain': 'Sales', 'total': 2, 'mapped': 1,
                        'unresolved': 1, 'unsupported': 0, 'excluded_by_review': 0,
                        'stale': 1, 'model_ids': ['gold.orders']}],
            'rows': [
                {'id': 'c1', 'asset': 'orders.csv', 'name': 'Order total', 'domain': 'Sales',
                 'model_ids': ['gold.orders'], 'status': 'mapped', 'rationale': 'Recorded association'},
                {'id': 'c2', 'asset': 'customers.csv', 'name': 'Customer group', 'domain': 'People',
                 'model_ids': ['silver.orders'], 'status': 'unsupported', 'rationale': 'Needs interpretation'},
                {'id': 'c3', 'asset': 'orders.csv', 'name': 'Unknown expression', 'domain': None,
                 'model_ids': [], 'status': 'unresolved', 'rationale': 'No owner supplied'}],
            'omitted_detail_rows': 2, 'orphan_requirements': ['req-unmapped'],
            'export_completeness': 'not_established', 'native_parity': 'not_validated'},
        'reuse': {
            'status': 'needs_review', 'counts': {'total': 2, 'unassigned': 1,
                                                'by_disposition': {'reuse': 1, 'undetermined': 1}},
            'stale': 1, 'canonical_total': 3, 'uninventoried_existing_ids': ['legacy-missing'],
            'rows': [
                {'name': 'Legacy orders', 'existing_id': 'old-orders', 'owner_domain': 'Sales',
                 'disposition': 'reuse', 'model_ids': ['gold.orders'], 'requirement_ids': ['req-orders'],
                 'compatibility': 'evidence_recorded', 'freshness': 'current', 'rationale': 'Retain contract'},
                {'name': 'Legacy unknown', 'existing_id': 'old-unknown', 'owner_domain': None,
                 'disposition': 'undetermined', 'model_ids': [], 'requirement_ids': [],
                 'compatibility': 'unknown', 'freshness': 'stale', 'rationale': 'Owner not supplied'}],
            'omitted_detail_rows': 0},
        'reconciliation': {
            'status': 'needs_review',
            'findings': [{'code': 'conflicting_grain', 'message': 'Resolve conflicting grain',
                          'model_ids': ['gold.orders']}],
            'unknowns': [{'code': 'native_compatibility', 'message': 'Native checks pending',
                          'model_ids': []}]}}


class ReviewEvidenceProjectionTests(unittest.TestCase):
    def test_allowlist_drops_nested_private_fields_and_retains_consequences(self):
        raw = guided.workflow_view()
        raw['review_assurance'] = evidence_view()
        raw['review_assurance']['private'] = 'PRIVATE_ASSURANCE'
        for kind in ('coverage', 'reuse', 'reconciliation'):
            item = raw['review_assurance'][kind]
            item['private'] = 'PRIVATE_SECTION'
            for key in ('groups', 'rows', 'findings', 'unknowns'):
                for row in item.get(key, []):
                    row['raw_payload'] = {'secret': 'PRIVATE_ROW'}
        coverage = raw['review_assurance']['coverage']
        coverage['counts']['private'] = 'PRIVATE_COUNTS'
        coverage['supplied_files']['private'] = 'PRIVATE_FILES'
        coverage['supplied_files']['statuses']['private'] = 'PRIVATE_STATUS'
        raw['review_assurance']['reuse']['counts']['private'] = 'PRIVATE_REUSE_COUNTS'
        raw['review_assurance']['reuse']['counts']['by_disposition']['private'] = 'PRIVATE_DISPOSITION'
        raw['decisions'][0]['options'][0]['consequences'] = 'Preserves the order grain.'
        projected = portal._workflow_presentation(raw)
        self.assertNotIn('PRIVATE_', json.dumps(projected))
        self.assertEqual(projected['review_assurance'], evidence_view())
        self.assertEqual(projected['decisions'][0]['options'][0],
                         {'id': 'orders', 'label': 'Order', 'consequences': 'Preserves the order grain.'})

    def test_packaged_code_and_audit_exports_drop_assurance(self):
        view = guided.workflow_view()
        view['review_assurance'] = evidence_view()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state, review = fixture(root)
            state['workflow'] = {'design': {'id': 'design-1', 'revision': 2, 'sha256': 'a' * 64}}
            review['design_binding'] = copy.deepcopy(state['workflow']['design'])
            module = types.SimpleNamespace(public_view=lambda state: view)
            for audience, categories in [('engineer', ['documentation']),
                                         ('engineer', ['implementation']), ('audit', ['technical_audit'])]:
                with self.subTest(audience=audience, categories=categories):
                    path = root / ('-'.join([audience, *categories]) + '.zip')
                    with patch.dict(sys.modules, {'engagement_stages': module}):
                        portal.package_delivery(state, review, root, path, audience, categories)
                    with zipfile.ZipFile(path) as archive:
                        page = archive.read('START_HERE.html').decode()
                    payload = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
                    self.assertEqual('review_assurance' in payload.get('workflow', {}), categories == ['documentation'])
                    if categories != ['documentation']:
                        self.assertNotIn('old-unknown', page)
                    self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')


@unittest.skipUnless(shutil.which('node'), 'Node required for offline script smoke checks')
class ReviewEvidencePortalTests(unittest.TestCase):
    page = navigation.PortalNavigationTests.page

    def payload(self, assessed=True):
        payload = navigation.PortalNavigationTests.payload(self)
        payload['workflow'] = portal._workflow_presentation(guided.workflow_view())
        if assessed:
            payload['workflow']['review_assurance'] = evidence_view()
        return payload

    def test_syntax_sidebar_navigation_first_click_and_old_aliases(self):
        result = subprocess.run([shutil.which('node'), '--check', str(portal.ASSETS / 'portal.js')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        template = (portal.ASSETS / 'portal.html').read_text()
        primary = template.split('id="primary-navigation"')[1].split('</nav>')[0]
        # Optional planning and dashboard continuation are hidden unless selected;
        # the existing five primary choices remain the default.
        self.assertEqual(primary.count('data-nav='), 7)
        self.assertIn('data-nav="migration-plan" hidden', primary)
        self.assertIn('data-nav="dashboard-migration" hidden', primary)
        self.assertNotIn('data-nav="coverage-reuse"', primary)
        self.assertIn('href="#coverage-reuse" data-nav="coverage-reuse"', template)
        self.assertIn('Inspect source coverage and existing-model reuse', template)
        self.assertIn('id="coverage-reuse" class="review-section" data-section', template)
        self.page(self.payload(), """
assert.equal(el('coverage-reuse').hidden,false);
assert.equal(el('model').hidden,true);
document.getElementById('nav:coverage-reuse').onclick();
assert.equal(el('coverage-reuse').hidden,false);
for(const [anchor,parent]of Object.entries(sectionRoutes)){
 location.hash='#'+anchor;listeners.hashchange[0]();assert.equal(el(parent).hidden,false);
 assert.equal(el('coverage-reuse').hidden,true);assert.equal(el(anchor).focused,true);
}
location.hash='#coverage-reuse';listeners.hashchange[0]();
assert.equal(el('coverage-reuse').hidden,false);assert.equal(el('delivery').hidden,true);
""", prefix="location.hash='#coverage-reuse';", second_boot=True)

    def test_missing_evidence_stays_unassessed_and_known_zero_stays_zero(self):
        self.page(self.payload(False), """
const content=node=>[node.textContent,...node.children.map(content)].join(' ');
for(const id of ['review-evidence-cards','review-evidence-sources','review-evidence-reuse-scope','review-evidence-filter-note','review-evidence-coverage','review-evidence-reuse','review-evidence-reconciliation'])assert.match(content(el(id)),/Unassessed/);
assert.doesNotMatch(el('review-evidence-filter-note').textContent,/0 of 0/);
assert.match(el('review-evidence-summary').value,/native parity is not validated/);
assert.doesNotMatch(el('review-evidence-summary').value,/passed|complete coverage/i);
assert.equal(reviewEvidenceCount(null),'Unassessed');assert.equal(reviewEvidenceCount(-1),'Unassessed');
assert.equal(reviewEvidenceCount('0'),'Unassessed');assert.equal(reviewEvidenceCount(0),'0');
""")
        payload = self.payload()
        payload['workflow']['review_assurance'] = {
            'coverage': {'counts': {'mapped': 0, 'total': 0}, 'rows': [], 'orphan_requirements': [],
                         'supplied_files': {'statuses': {}}},
            'reuse': {'rows': [], 'uninventoried_existing_ids': []}}
        self.page(payload, """
assert.match(el('review-evidence-summary').value,/Mapped source occurrences: 0 of 0/);
assert.match(el('review-evidence-summary').value,/unresolved: Unassessed/);
assert.match(el('review-evidence-sources').textContent,/Statuses: Unassessed/);
assert.match(el('review-evidence-open-items').textContent,/None recorded/);
assert.match(el('review-evidence-filter-note').textContent,/source details: 0 of 0/);
""")

    def test_filters_keep_global_counts_and_follow_explicit_associations(self):
        self.page(self.payload(), """
const content=node=>[node.textContent,...node.children.map(content)].join(' ');
const original=el('review-evidence-summary').value;
el('review-evidence-asset').value='orders.csv';el('review-evidence-asset').onchange();
assert.match(content(el('review-evidence-coverage')),/Order total/);
assert.doesNotMatch(content(el('review-evidence-coverage')),/Customer group/);
assert.match(content(el('review-evidence-reuse')),/Legacy orders/);
assert.doesNotMatch(content(el('review-evidence-reuse')),/Legacy unknown/);
el('review-evidence-domain').value='Sales';el('review-evidence-domain').onchange();
assert.doesNotMatch(content(el('review-evidence-coverage')),/Unknown expression/);
el('review-evidence-model').value='gold.orders';el('review-evidence-model').onchange();
assert.match(el('review-evidence-filter-note').textContent,/source details: 1 of 3/);
el('review-evidence-search').value='req-orders';el('review-evidence-search').oninput();
assert.match(content(el('review-evidence-coverage')),/No matching records/);
assert.match(content(el('review-evidence-reuse')),/Legacy orders/);
el('review-evidence-reset').onclick();
el('review-evidence-model').value='__unknown__';el('review-evidence-model').onchange();
assert.match(content(el('review-evidence-coverage')),/Unknown expression/);
assert.match(content(el('review-evidence-reuse')),/Legacy unknown/);
assert.doesNotMatch(content(el('review-evidence-reuse')),/Legacy orders/);
el('review-evidence-domain').value='__unknown__';el('review-evidence-domain').onchange();
assert.match(content(el('review-evidence-reuse')),/Unknown/);
assert.equal(el('review-evidence-summary').value,original);
assert.match(original,/Mapped source occurrences: 1 of 3/);
assert.match(el('review-evidence-coverage-limit').textContent,/omitted from this page: 2/);
assert.equal(el('review-evidence-reuse').querySelector('a').href,'#changes');
assert.equal(el('review-evidence-reconciliation').querySelector('a').href,'#review-feedback');
assert.match(content(el('review-evidence-reconciliation')),/Native checks pending/);
""")

    def test_detail_cap_and_copy_fallback_preserve_evidence_boundaries(self):
        payload = self.payload()
        payload['workflow']['review_assurance']['coverage']['rows'] = [
            dict(evidence_view()['coverage']['rows'][0], id='item-' + str(i), name='Item ' + str(i))
            for i in range(503)]
        payload['workflow']['review_assurance']['coverage']['omitted_detail_rows'] = 3
        self.page(payload, """
assert.equal(initialEvidenceSelection.coverageRows.length,500);
assert.match(el('review-evidence-filter-note').textContent,/source details: 500 of 500/);
assert.match(el('review-evidence-coverage-limit').textContent,/omitted from this page: 3/);
assert.match(el('review-evidence-summary').value,/Delivered files and mapped associations do not establish validated behavior/);
el('review-evidence-copy').onclick().then(()=>{
 assert.equal(el('review-evidence-summary').selected,true);
 assert.match(el('messages').textContent,/normal Copy shortcut/);
}).catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_safe_text_consequences_and_existing_option_response(self):
        payload = self.payload()
        hostile = '<img src=x onerror="throw 1"> & </script>'
        payload['workflow']['review_assurance']['coverage']['rows'][0]['rationale'] = hostile
        payload['workflow']['decisions'][0]['options'][0]['consequences'] = hostile
        self.page(payload, """
const content=node=>[node.textContent,...node.children.map(content)].join(' ');
assert.match(content(el('review-evidence-coverage')),/<img src=x onerror=/);
assert.equal(el('review-evidence-coverage').querySelector('img'),null);
assert.match(content(el('decisions')),/Consequences: <img src=x onerror=/);
assert.equal(el('decisions').querySelector('img'),null);
const choice=el('decisions').querySelector('select');
assert.equal(choice.children[1].value,'orders');assert.equal(choice.children[1].textContent,'Order');
choice.value='orders';choice.onchange();
assert.equal(decisionInputs.get('grain').answer,'Order');assert.equal(decisionInputs.get('grain').option_id,'orders');
assert.equal(el('decisions').querySelectorAll('select').length,1);
""")

    def test_browser_subset_and_helper_remove_review_assurance_for_private_modes(self):
        payload = self.payload()
        self.page(payload, """
for(const [audience,categories,keep] of [['engineer',['documentation'],true],['engineer',['implementation'],false],['audit',['documentation','technical_audit'],false]]){
 const snapshot=JSON.parse(JSON.stringify(data));snapshot.audience=audience;
 trimWorkflowDetails(snapshot,new Set(categories));
 assert.equal(Boolean(snapshot.workflow.review_assurance),keep);
}
""")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve() / 'code-only.zip'
            self.page(payload, """
let writeExport;
download=(name,body)=>{writeExport=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.clear();chosen.add('implementation');updateExport();
el('download-package').onclick().then(()=>writeExport).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT', json.dumps(str(output))))
            self.assertTrue(output.exists())
            with zipfile.ZipFile(output) as archive:
                page = archive.read('START_HERE.html').decode()
            selected = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
            self.assertNotIn('review_assurance', selected.get('workflow', {}))
            self.assertNotIn('old-unknown', page)
            self.assertEqual(portal.verify_delivery(output)['status'], 'integrity_verified')
            self.page(selected, "assert.equal(reviewAssurance,null);assert.match(el('review-evidence-summary').value,/Unassessed/);")


if __name__ == '__main__':
    unittest.main()
