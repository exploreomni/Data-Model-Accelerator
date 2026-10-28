"""The alternate presentation consumes canonical evidence, never name guesses."""
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import review_page
import omni_contract
from test_omni_contract import files, context
from omni_topic_trees import build_topic_trees


class ReviewGraphProjectionTests(unittest.TestCase):
    def test_relationship_only_lineage_and_disconnected_models_survive(self):
        models = [{'id': x, 'layer': layer, 'domain': 'Orders'} for x, layer in
                  [('raw.orders', 'bronze'), ('int.orders', 'silver'), ('gold.orders', 'gold'), ('orphan', 'silver')]]
        relationships = [{'from': a, 'to': b, 'kind': 'lineage'} for a, b in
                         [('raw.orders', 'int.orders'), ('int.orders', 'gold.orders')]]
        p = review_page.page_model({'review': {'models': models, 'relationships': relationships}}, {})
        self.assertEqual({x for a in p['areas'] for x in a['pipeline']}, {m['id'] for m in models})
        v = next(v for v in p['pipeline_diagrams'] if v['target_model_id'] == 'gold.orders')
        self.assertEqual(len(v['edges']), 2)
        self.assertTrue(all(len(e['occurrences']) == 1 for e in v['edges']))
        self.assertEqual(next(m for m in p['models'] if m['id'] == 'gold.orders')['depends_on'], ['int.orders'])

    @unittest.skipUnless(omni_contract.yaml and omni_contract.sqlglot, 'Optional semantic parser required')
    def test_inherited_topic_uses_explicit_binding_and_visible_unbound_gap(self):
        native = files(); native['activity.topic'] = 'base_view: events\njoins: {}\n'
        native['regional.topic'] = 'extends: [activity]\n'
        models = [{'id': 'gold.events', 'layer': 'gold', 'domain': 'Activity'}]
        for bindings in ([{'view_id': 'events', 'model_ids': ['gold.events']}], []):
            trees = build_topic_trees(native, context(), bindings, models)
            p = review_page.page_model({'review': {'models': models, 'topic_join_trees': trees}}, native)
            self.assertEqual({t['topic'] for t in p['topics']}, {'activity', 'regional'})
            self.assertTrue(all(t['area'] in {a['id'] for a in p['areas']} for t in p['topics']))
            self.assertTrue(all(t['base'] == ('gold.events' if bindings else 'events') for t in p['topics']))
            self.assertEqual(bool(p['topic_note']), not bool(bindings))

    def test_silver_only_package_and_missing_producer_keep_visible_inventory(self):
        p = review_page.page_model({'review': {'models': [{'id': 'int.orders', 'layer': 'silver'}]}},
                                   {'new.topic': 'extends: [missing]\n'})
        self.assertIn('int.orders', {x for a in p['areas'] for x in a['pipeline']})
        self.assertEqual(p['topics'][0]['diagnostics'][0]['code'], 'topic.canonical_tree_missing')
        self.assertNotIn('not compiled', p['qualification'])

    def test_topic_binding_inspector_has_single_multiple_and_unresolved_states(self):
        import shutil
        if not shutil.which('node'): self.skipTest('Node required')
        import test_review_page_security as security
        data, page = security.fixture()
        page['topics'][0]['bindings'] = [{'id': 'one', 'view_id': 'events', 'model_ids': [security.HOSTILE]},
                                        {'id': 'many', 'view_id': 'summary', 'model_ids': [security.HOSTILE, '__proto__']},
                                        {'id': 'gap', 'view_id': 'unknown', 'model_ids': []}]
        security.ReviewPageSecurityTests().run_js(data, page, r'''
inspBinding(JSON.stringify([P.topics[0].topic,'one']));assert(get('insp').innerHTML.includes('Grain:'));
inspBinding(JSON.stringify([P.topics[0].topic,'many']));assert(get('insp').innerHTML.includes('Choose a bound warehouse table'));
inspBinding(JSON.stringify([P.topics[0].topic,'gap']));assert(get('insp').innerHTML.includes('Unresolved warehouse binding'));
console.log('{}');
''')
