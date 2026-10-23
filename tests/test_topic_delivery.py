"""Offline topic review across both page formats; no native execution implied."""
import base64
import copy
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import omni_contract
import omni_handoff
import portable_site
import topic_visuals
from portal_checks import parse_page, check_javascript
from test_delivery_portal import fixture as warehouse_fixture
from test_omni_contract import context, files


def fixture(root):
    state, review = warehouse_fixture(root)
    native, ctx = files(), context()
    native['accounts.view'] = native['events.view'].replace('table_name: EVENTS', 'table_name: ACCOUNTS')
    ctx['bindings']['accounts'] = copy.deepcopy(ctx['bindings']['events'])
    ctx['bindings']['accounts']['namespace']['table'] = 'ACCOUNTS'
    native.pop('activity.topic')
    native['sales/activity.topic'] = 'base_view: events\njoins: {accounts: {}}\n'
    native['operations/health.topic'] = 'base_view: accounts\njoins: {}\n'
    native['relationships.yml'] = ('- join_from_view: events\n  join_to_view: accounts\n'
        '  join_type: left\n  relationship_type: many_to_one\n  on_sql: ${events.id} = ${accounts.id}\n')
    state['inputs']['catalogue']['sha256'] = ctx['catalogue_sha256']
    review['context_sha256'] = portal.context_fingerprint(state)
    review['package_layout_version'] = 2
    review['models'][-1]['domain'] = 'Sales'
    result = omni_handoff.build_handoff(state, native, ctx)
    registration = omni_handoff.write_handoff(result, root / 'semantic')
    # Retain the producer's immutable candidate paths in one common artifact root.
    shutil.copytree(root / 'semantic', root, dirs_exist_ok=True)
    review['artifacts'] += registration['artifacts']
    review['omni'] = registration['omni']
    review['omni_warehouse_bindings'] = [{'view_id': 'events', 'model_ids': ['gold.orders']}]
    review['omni_topic_domains'] = {'source_folders': {'sales': 'Sales', 'operations': 'Operations'}}
    return state, review


@unittest.skipUnless(omni_contract.yaml is not None and omni_contract.sqlglot is not None,
                     'Pinned YAML/SQL runtime required')
class TopicDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.state, self.review = fixture(self.root)

    def build(self, large=False, include=None):
        path = self.root / ('large.zip' if large else 'small.zip')
        with patch.object(portable_site, 'should_partition', return_value=large):
            manifest = portal.package_delivery(self.state, self.review, self.root, path, 'engineer', include)
        with zipfile.ZipFile(path) as archive:
            bodies = {name: archive.read(name) for name in archive.namelist()}
        return path, manifest, bodies, parse_page(bodies['START_HERE.html'])[1]

    def test_both_page_formats_keep_unbound_topics_and_identical_exports(self):
        exports = []
        for large in (False, True):
            path, manifest, bodies, data = self.build(large)
            self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])
            self.assertEqual(2, manifest['topic_coverage']['expected_topics'])
            self.assertEqual(2, manifest['topic_coverage']['represented_topics'])
            self.assertEqual(0, manifest['topic_coverage']['fully_bound_topics'])
            self.assertIn('data-nav="omni-topic-trees"', bodies['START_HERE.html'].decode())
            self.assertEqual({'Sales', 'Operations'}, {r['domain'] for r in data['topic_diagrams']})
            topic_files = {k:v for k,v in bodies.items() if '/Topics/' in k or k.endswith('TOPIC_TO_TABLE.csv')}
            self.assertEqual(4, len(topic_files))
            self.assertIn(b'accounts', bodies['05_Mappings/TOPIC_TO_TABLE.csv'])
            for name, body in topic_files.items():
                if name.endswith('.svg'):
                    self.assertIn(b'<style>', body)
                    portal._validate_svg(body, trusted_styles=(topic_visuals.STYLE,))
            self.assertEqual('javascript_checked', check_javascript(bodies['START_HERE.html'])['status'])
            exports.append(topic_files)
        self.assertEqual(exports[0], exports[1])

    def test_semantic_omission_removes_topics_and_export_inventory(self):
        for large in (False, True):
            path, manifest, bodies, data = self.build(large, ['implementation'])
            self.assertNotIn('topic_coverage', data)
            self.assertNotIn('topic_coverage', manifest)
            self.assertFalse(any('/Topics/' in p or p.endswith('TOPIC_TO_TABLE.csv') for p in bodies))
            self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])

    def test_derived_topic_deletion_is_detected_and_read_only_bindings_stay_exact(self):
        _, _, _, data = self.build()
        original = copy.deepcopy(data)
        data['topic_diagrams'].pop()
        with self.assertRaisesRegex(ValueError, 'Topic diagrams or coverage differ'):
            portal.generated_deliverables(data)
        data = copy.deepcopy(original)
        for key in ('topic_diagrams', 'topic_exports', 'topic_coverage'): data.pop(key)
        data['review'].pop('topic_join_trees')
        with self.assertRaisesRegex(ValueError, 'Topic diagrams or coverage differ'):
            portal.generated_deliverables(data)
        data = original
        data['review']['omni_warehouse_bindings'][0]['model_ids'] = ['silver.orders']
        topic_visuals.prepare(data)
        self.assertEqual(0, data['topic_coverage']['fully_bound_topics'])
        self.assertTrue(data['review']['topic_join_trees']['topics'][0]['binding_diagnostics'])

    def test_shared_controls_smoke_and_idempotence(self):
        _, _, _, data = self.build()
        script = (portal.ASSETS / 'topic-panel.js').read_text()
        prelude = r'''
const assert=require('node:assert/strict');
class E{constructor(){this.children=[];this.style={};this.value='';}append(...n){this.children.push(...n);}replaceChildren(){this.children=[];}getAttribute(k){return k==='width'?'800':'600';}click(){this.clicked=true;}remove(){}}
const ids={};for(const id of ['omni-topic-trees','topic-trees-nav','delivery-data','topic-domain','topic-picker','topic-coverage','topic-empty','topic-download','topic-zoom-in','topic-zoom-out','topic-zoom-reset','topic-diagram','topic-bindings','topic-findings'])ids[id]=new E();
ids['delivery-data'].textContent=JSON.stringify(DATA);
global.document={body:new E(),querySelector:s=>ids[s.slice(1)],getElementById:id=>ids[id],createElement:()=>new E()};
global.setTimeout=fn=>fn();
global.PortalSvg={sanitize:()=>new E()};global.navigator={clipboard:{writeText:async()=>{}}};
'''.replace('DATA', json.dumps(data))
        assertions = r'''
assert.equal(ids['topic-picker'].children.length,2);
assert.match(ids['topic-coverage'].textContent,/2 \/ 2/);
ids['topic-domain'].value='Operations';ids['topic-domain'].onchange();
assert.equal(ids['topic-picker'].children.length,1);
assert.match(ids['topic-findings'].children[0].textContent,/binding/);
ids['topic-zoom-in'].onclick();assert.equal(ids['topic-diagram'].children[0].style.width,'960px');
ids['topic-download'].onclick();
const before=ids['topic-picker'].children.length;
'''
        run = subprocess.run(['node', '-'], input=prelude + script + assertions + script +
            "assert.equal(ids['topic-picker'].children.length,before);", text=True, capture_output=True)
        self.assertEqual(0, run.returncode, run.stderr)

    def test_finalizer_distinguishes_missing_topics_from_binding_gaps(self):
        from finalize_delivery import check_selected_delivery
        _, manifest, _, _ = self.build()
        # Restrict to represented diagrams, independent of native validation.
        check_selected_delivery(self.state, self.review, 'engineer', ['diagrams'], manifest)
        manifest['topic_coverage']['status'] = 'failed'
        with self.assertRaisesRegex(ValueError, 'Topic coverage is incomplete'):
            check_selected_delivery(self.state, self.review, 'engineer', ['diagrams'], manifest)
        manifest.pop('topic_coverage')
        with self.assertRaisesRegex(ValueError, 'missing topic coverage'):
            check_selected_delivery(self.state, self.review, 'engineer', ['diagrams'], manifest)

    def test_source_closure_and_staging_register_are_packaged_without_target_scope_growth(self):
        from test_guided_context_delivery import GuidedContextDeliveryTests
        import engagement_stages as stages
        harness = GuidedContextDeliveryTests(); harness.setUp(); self.addCleanup(harness.doCleanups)
        state = harness.register()
        state = harness.command('configure-staging-ports', harness.policy())
        state = harness.command('record-staging-ports', {'schema_version': 1, 'domain_id': 'sales', 'rows': [harness.fixture.row()]})
        design = state['workflow']['design']; view = stages.public_view(state)
        review = {'schema_version': 1, 'package_layout_version': 2, 'title': 'Source context review',
            'source_fingerprint': portal.source_fingerprint(state), 'context_sha256': portal.context_fingerprint(state),
            'target': {k:state['answers'][k] for k in ('framework','warehouse')},
            'design_binding': {k:design[k] for k in ('id','revision','sha256')},
            'models': view['models'], 'relationships': view['relationships'], 'assets': view['assets'], 'artifacts': []}
        before = copy.deepcopy(state['workflow']['design'])
        path = harness.root / 'sources.zip'
        portal.package_delivery(state, review, harness.root, path, 'reviewer', ['diagrams','dictionary'])
        self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])
        with zipfile.ZipFile(path) as archive:
            source = json.loads(archive.read('03_Design_Documents/Upstream/SOURCE_LINEAGE.json'))
            self.assertEqual({'gold','other'}, set(source['generation_entity_ids']))
            self.assertTrue(any(n['native_id'] == 'source.p.raw.events' for n in source['nodes']))
            self.assertNotIn(str(harness.source), json.dumps(source))
            self.assertIn(b'port_missing', archive.read('05_Mappings/STAGING_PORT_REGISTER.csv'))
            self.assertIn(b'source.p.raw.events', archive.read('05_Mappings/SOURCE_LINEAGE.csv'))
        self.assertEqual(before, state['workflow']['design'])
        with patch.object(portable_site, 'should_partition', return_value=True):
            large = harness.root / 'sources-large.zip'
            portal.package_delivery(state, review, harness.root, large, 'reviewer', ['diagrams','dictionary'])
        self.assertEqual('integrity_verified', portal.verify_delivery(large)['status'])


if __name__ == '__main__': unittest.main()
