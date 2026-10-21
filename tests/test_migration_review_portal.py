"""Optional migration review projection and exports; synthetic DOM is not visual QA."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import test_portal_navigation as navigation
import test_guided_review_workflow as guided
from test_delivery_portal import fixture

portal = navigation.portal


def summary():
    return {'schema_version': 1, 'qualification': 'Supplied evidence; not native validation.',
        'business_rules': {'status': 'conflicts', 'count': 2, 'proposed': 1,
            'qualification': 'Rule acceptance is not design approval.',
            'rows': [{'id': 'net.orders', 'name': 'Net orders', 'statement': 'Exclude internal orders.',
                      'status': 'accepted', 'model_ids': ['gold.orders']},
                     {'id': 'window', 'name': 'Reporting window', 'statement': 'Use UTC days.',
                      'status': 'proposed', 'model_ids': ['gold.orders']}],
            'conflicts': [{'model_id': 'gold.orders', 'key': 'population', 'rule_ids': ['net.orders', 'window']}]},
        'portfolio': {'status': 'stale', 'asset_count': 2, 'covered_assets': 2,
            'qualification': 'Recommendations require consumer validation.',
            'candidates': [{'id': 'shared.orders', 'disposition': 'shared_aggregate_candidate',
                'reason': 'Declared additive measures at the same grain.', 'asset_ids': ['daily', 'trend'],
                'model_ids': ['gold.orders'], 'grain': ['day'], 'dimensions': ['region'],
                'measure_ids': ['order_count'], 'rule_ids': ['net.orders'],
                'required_checks': ['population', 'security', 'source_target_parity']}],
            'coverage': [{'asset_id': 'daily', 'name': 'Daily report', 'model_ids': ['gold.orders'],
                'candidate_id': 'shared.orders', 'disposition': 'shared_aggregate_candidate',
                'reason': 'Validate every consumer.', 'freshness': 'stale'}]},
        'source_discovery': {'status': 'partial', 'version': {'workflow': 1}, 'freshness': 'stale',
            'qualification': 'Counts only; supplied export completeness remains unresolved.',
            'coverage': {'counts': {'parsed': 2, 'unsupported': 0, 'unreadable': 1},
                         'known_file_denominator': 3, 'repository_file_denominator': 4,
                         'enumeration_complete': False, 'export_completeness': 'not_established'},
            'gaps': [{'code': 'missing_dependency'}]},
        'parity': {'status': 'stale', 'stale': True, 'counts': {'pass': 1, 'pending': 1},
            'assurance': 'Supplied comparison records only.', 'native_verified': False, 'acceptance_ready': False,
            'crosswalk': [{'dashboard_label': 'Daily report', 'source_label': 'Daily export',
                'model_ids': ['gold.orders'], 'topic_ids': ['orders'], 'status': 'pending', 'case_count': 2, 'required': True,
                'issues': [{'code': 'filter_behavior', 'status': 'pending'}]}]}}


class MigrationReviewProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state, self.review = fixture(self.root)
        self.state['workflow'] = {'design': {'id': 'design-1', 'revision': 2, 'sha256': 'a' * 64},
                                  'migration_review': {'business_rules': {'path': 'PRIVATE_RETAINED_PATH'}}}
        self.review['design_binding'] = copy.deepcopy(self.state['workflow']['design'])
        self.public = patch('engagement_stages.public_view', return_value=guided.workflow_view())
        self.public.start(); self.addCleanup(self.public.stop)

    def package(self, categories=('documentation',), audience='engineer', raw=None):
        path = self.root / ('package-' + str(len(list(self.root.glob('*.zip')))) + '.zip')
        with patch('migration_review.public_summary', return_value=summary() if raw is None else raw) as selected:
            portal.package_delivery(self.state, self.review, self.root, path, audience, categories)
        with zipfile.ZipFile(path) as archive:
            page = archive.read('START_HERE.html').decode()
        data = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        return path, data, selected

    def test_projection_allowlists_nested_records_and_never_promotes_assurance(self):
        raw = summary()
        raw['internal'] = 'PRIVATE_TOP'
        raw['business_rules']['rows'][0].update(source={'reference': 'PRIVATE_SOURCE'}, definition={'formula': 'PRIVATE_SQL'})
        raw['portfolio']['candidates'][0].update(evidence_refs=['PRIVATE_EVIDENCE'], existing_model_ids=['PRIVATE_MODEL'])
        raw['source_discovery']['coverage']['paths'] = ['PRIVATE_PATH']
        raw['source_discovery']['coverage']['counts']['raw'] = 'PRIVATE_COUNT'
        raw['source_discovery']['coverage']['counts']['PRIVATE_COUNT_KEY'] = 42
        raw['source_discovery']['version']['path'] = 'PRIVATE_VERSION_PATH'
        raw['source_discovery']['gaps'][0]['path'] = 'PRIVATE_GAP'
        raw['parity']['crosswalk'][0]['raw_sql'] = 'PRIVATE_QUERY'
        raw['parity']['crosswalk'][0]['issues'][0]['receipt'] = 'PRIVATE_RECEIPT'
        raw['parity'].update(native_verified=True, acceptance_ready=True)
        projected = portal._migration_presentation(raw)
        self.assertNotIn('PRIVATE_', json.dumps(projected))
        self.assertFalse(projected['parity']['native_verified'])
        self.assertFalse(projected['parity']['acceptance_ready'])
        self.assertIn('Conflict: gold.orders', projected['summary_markdown'])
        self.assertIn('guided_workflow review-business-rules', projected['summary_markdown'])

    def test_scoped_package_has_complete_readable_markdown_and_checked_bytes(self):
        path, data, selected = self.package()
        selected.assert_called_once_with(self.state, {row['id'] for row in self.review['models']})
        with zipfile.ZipFile(path) as archive:
            markdown = archive.read('01_Model/migration-review.md').decode()
        self.assertEqual(markdown, data['migration_review']['summary_markdown'])
        for phrase in ('Exclude internal orders.', 'Reporting window', 'shared.orders', 'missing_dependency',
                       'filter_behavior', 'Native verification established: No', 'stale'):
            self.assertIn(portal._markdown_cell(phrase), markdown)
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    def test_absent_feature_preserves_old_payload_and_generated_inventory(self):
        self.state['workflow'].pop('migration_review')
        _, data, selected = self.package()
        selected.assert_not_called()
        self.assertNotIn('migration_review', data)
        self.assertFalse(any(row['id'] == 'generated:migration-review' for row in data['generated_deliverables']))

    def test_code_only_and_audit_drop_summary_and_generated_file(self):
        for categories, audience in ((['implementation'], 'engineer'), (['technical_audit'], 'audit')):
            with self.subTest(audience=audience):
                path, data, selected = self.package(categories, audience)
                self.assertNotIn('migration_review', data)
                self.assertNotIn('Exclude internal orders.', json.dumps(data))
                if audience == 'audit': selected.assert_not_called()
                with zipfile.ZipFile(path) as archive:
                    self.assertNotIn('01_Model/migration-review.md', archive.namelist())
                self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    def test_explicit_empty_scope_is_distinct_from_predesign_status(self):
        self.review['models'] = []; self.review['relationships'] = []
        _, data, selected = self.package(raw={'schema_version': 1, 'business_rules': {'status': 'unassessed', 'rows': []}})
        selected.assert_called_once_with(self.state, set())
        self.assertEqual(data['review']['models'], [])
        self.assertEqual(data['generated_deliverables'][0]['id'], 'generated:migration-review')
        self.state['workflow'].pop('design')
        with patch('migration_review.public_summary', return_value={'schema_version': 1}) as selected:
            portal._presentation(self.state)
        selected.assert_called_once_with(self.state, None)

    def test_actual_rule_scope_drops_excluded_and_unbound_definitions(self):
        import business_rules
        self.state['workflow']['migration_review'] = {}
        self.state['workflow']['design']['entities'] = copy.deepcopy(self.review['models'])
        pack = business_rules.from_text('Included order definition.', rule_id='included', domain='sales', source_reference='synthetic://definition')
        pack['rules'][0]['scope'] = {'domains': [], 'model_ids': ['gold.orders'], 'asset_ids': []}
        for rule_id, model_ids in (('excluded', ['silver.orders']), ('spanning', ['silver.orders', 'gold.orders']), ('unbound', ['future'])):
            row = copy.deepcopy(pack['rules'][0]); row['id'] = rule_id; row['name'] = 'PRIVATE_' + rule_id
            row['scope']['model_ids'] = model_ids; pack['rules'].append(row)
        business_rules.register(self.state, pack, self.root)
        self.review['models'] = [self.review['models'][2]]; self.review['relationships'] = []
        result = portal._presentation(self.state, self.review)
        rows = result['migration_review']['business_rules']['rows']
        self.assertEqual([row['id'] for row in rows], ['included'])
        self.assertNotIn('PRIVATE_', json.dumps(result['migration_review']))


@unittest.skipUnless(shutil.which('node'), 'Node required for offline DOM checks')
class MigrationReviewBrowserTests(unittest.TestCase):
    page = navigation.PortalNavigationTests.page

    def payload(self, raw=None):
        data = navigation.PortalNavigationTests.payload(self)
        data['migration_review'] = portal._migration_presentation(summary() if raw is None else raw)
        data['generated_deliverables'] = portal.generated_deliverables(data)
        return data

    def test_first_click_route_stale_warnings_and_safe_text_print(self):
        raw = summary(); raw['business_rules']['rows'][0]['statement'] = '<img src=x onerror=alert(1)> is supplied wording.'
        data = self.payload(raw)
        self.page(data, """
assert.equal(el('migration-review-nav').hidden,false);
assert.equal(el('migration-review').hidden,false);assert.equal(el('model').hidden,true);
document.getElementById('nav:migration-review').onclick();assert.equal(el('migration-review').focused,true);
assert.match(el('migration-attention').textContent,/conflicts.*human decision.*stale/);
assert.equal(el('migration-rules').querySelector('img'),null);
assert.match(el('migration-print-summary').textContent,/filter_behavior/);
assert.match(el('migration-print-summary').textContent,/<img/);
assert.equal(el('migration-print-summary').querySelector('img'),null);
assert.match(el('migration-source-status').textContent,/Known file denominator: 3.*Repository file denominator: 4/);
let printed=0;globalThis.print=()=>printed++;el('migration-print').onclick();
assert.equal(printed,1);assert.match(document.body.className,/migration-print/);
listeners.afterprint[0]();assert.equal(document.body.className.includes('migration-print'),false);
location.hash='#architecture';listeners.hashchange[0]();assert.equal(el('model').hidden,false);
""", prefix="location.hash='#migration-review';", second_boot=True)

    def test_empty_and_absent_feature_keep_unknown_distinct_from_zero(self):
        self.page(self.payload({'schema_version': 1, 'business_rules': {'status': 'unassessed', 'rows': [], 'conflicts': []}}), """
assert.match(el('migration-rules-status').textContent,/unassessed/);
assert.equal(el('migration-attention').hidden,true);
assert.match(el('migration-source-status').textContent,/Not supplied/);
assert.equal(el('migration-rules').querySelector('table'),null);
""")
        data = navigation.PortalNavigationTests.payload(self)
        self.page(data, """
assert.equal(el('migration-review-nav').hidden,true);
assert.equal(reviewSections.includes('migration-review'),false);
location.hash='#migration-review';listeners.hashchange[0]();assert.equal(el('model').hidden,false);
""")

    def test_print_summary_retains_paginated_rows_and_parity_scope(self):
        raw = summary()
        raw['business_rules']['rows'] = [dict(raw['business_rules']['rows'][0], id='rule.' + str(i),
                                             name='Rule ' + str(i)) for i in range(35)]
        raw['parity']['crosswalk'][0].update(required=False, status='unsupported')
        self.page(self.payload(raw), """
assert.equal(el('migration-rules').querySelectorAll('tr').length,31);
assert.match(el('migration-print-summary').textContent,/Rule 34/);
assert.match(el('migration-print-summary').textContent,/Selected comparison: No/);
assert.match(el('migration-print-summary').textContent,/Only selected comparisons determine parity status/);
const scopeCell=el('migration-parity-crosswalk').querySelectorAll('td')[2];
assert.equal(scopeCell.children[0].textContent,'Retained outside selected scope');
""")
    def test_browser_documentation_and_code_subsets_reopen_with_correct_summary_scope(self):
        data = self.payload()
        with tempfile.TemporaryDirectory() as tmp:
            for categories in (['documentation'], ['implementation']):
                path = Path(tmp).resolve() / (categories[0] + '.zip')
                self.page(data, """
let writeExport;download=(name,body)=>{writeExport=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.clear();for(const category of CATEGORIES)chosen.add(category);updateExport();
el('download-package').onclick().then(()=>writeExport).then(()=>assert.match(el('messages').textContent,/Candidate subset created/)).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT', json.dumps(str(path))).replace('CATEGORIES', json.dumps(categories)))
                self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')
                with zipfile.ZipFile(path) as archive:
                    page = archive.read('START_HERE.html').decode()
                    selected = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
                    if categories == ['documentation']:
                        self.assertEqual(archive.read('01_Model/migration-review.md').decode(), data['migration_review']['summary_markdown'])
                        self.page(selected, "assert.equal(el('migration-review-nav').hidden,false);")
                    else:
                        self.assertNotIn('migration_review', selected)
                        self.assertNotIn('Exclude internal orders.', page)
                        self.assertNotIn('01_Model/migration-review.md', archive.namelist())
                        self.page(selected, "assert.equal(el('migration-review-nav').hidden,true);")


if __name__ == '__main__': unittest.main()
