"""Native occurrence trees, exact explicit bindings and visible coverage gaps."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_contract as omni
import omni_topic_trees as trees
import omni_query_views as query
from test_omni_contract import context, files


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None, 'Pinned YAML/SQL runtime required')
class TopicTreeTests(unittest.TestCase):
    def setUp(self):
        self.files = files(); self.context = context()
        self.files['activity.topic'] = 'base_view: events\njoins: {}\n'
        self.bindings = [{'view_id': 'events', 'model_ids': ['gold.events']}]
        self.models = [{'id': 'gold.events', 'layer': 'gold', 'domain': 'Activity'}]

    def add_view(self, name):
        self.files[name + '.view'] = self.files['events.view'].replace('table_name: EVENTS', 'table_name: ' + name.upper())
        self.context['bindings'][name] = copy.deepcopy(self.context['bindings']['events'])
        self.context['bindings'][name]['namespace']['table'] = name.upper()
        self.bindings.append({'view_id': name, 'model_ids': ['gold.' + name]})
        self.models.append({'id': 'gold.' + name, 'layer': 'gold', 'domain': 'Activity'})

    def relation(self, left, right, **kwargs):
        return {'join_from_view': left, 'join_to_view': right, 'join_type': 'left',
                'relationship_type': 'many_to_one', 'on_sql': '${' + left + '.id} = ${' + right + '.id}', **kwargs}

    def build(self):
        return trees.build_topic_trees(self.files, self.context, self.bindings, self.models)

    def test_nested_native_paths_preserve_parent_and_leaf(self):
        self.add_view('accounts'); self.add_view('regions')
        self.files['activity.topic'] = omni.yaml.safe_dump({'base_view': 'events', 'joins': {'accounts': {'regions': None}}})
        self.files['relationships.yml'] = omni.yaml.safe_dump([self.relation('events', 'accounts'), self.relation('accounts', 'regions')])
        report = self.build(); topic = report['topics'][0]
        self.assertEqual('complete', report['coverage']['status'])
        self.assertEqual('complete', topic['structural_status'])
        self.assertEqual('complete', topic['binding_status'])
        self.assertEqual(['events', 'accounts', 'regions'], topic['nodes'][-1]['path'])
        self.assertEqual(topic['nodes'][1]['id'], topic['edges'][-1]['from'])
        self.assertEqual('passed', omni.check_model(self.files, self.context)['status'])
        self.assertNotIn('on_sql', json.dumps(report))
        self.assertFalse(report['native_verified'])

    def test_reverse_semantics_default_explicit_and_symmetric(self):
        self.add_view('accounts')
        self.files['activity.topic'] = 'base_view: accounts\njoins: {events: {}}\n'
        for kind, reversible, expected in [('many_to_one', None, False), ('many_to_one', True, True),
                                            ('one_to_one', None, True), ('many_to_many', False, True),
                                            ('one_to_many', None, True)]:
            relation = self.relation('events', 'accounts', relationship_type=kind)
            if reversible is not None: relation['reversible'] = reversible
            self.files['relationships.yml'] = omni.yaml.safe_dump([relation])
            with self.subTest(kind=kind, reversible=reversible):
                edge = self.build()['topics'][0]['edges'][0]
                self.assertEqual('reverse' if expected else 'unresolved', edge['relationship_direction'])
                if kind == 'many_to_one' and expected: self.assertEqual('one_to_many', edge['relationship_type'])

    def test_topic_extends_local_aliases_and_repeated_physical_source(self):
        self.files['activity.topic'] = omni.yaml.safe_dump({'base_view': 'events', 'joins': {'buyer': {}, 'seller': {}},
            'views': {'buyer': {'extends': ['events']}, 'seller': {'extends': ['events']}},
            'relationships': [self.relation('events', 'buyer'), self.relation('events', 'seller')]})
        self.files['regional.topic'] = 'extends: [activity]\nlabel: Regional\n'
        report = self.build()
        self.assertEqual(['activity', 'regional'], report['expected_topic_ids'])
        for topic in report['topics']:
            self.assertEqual(3, len({n['id'] for n in topic['nodes']}))
            self.assertEqual({'events', 'buyer', 'seller'}, {n['view_id'] for n in topic['nodes']})
            self.assertTrue(all(n['model_ids'] == ['gold.events'] for n in topic['nodes']))
            self.assertEqual('complete', topic['structural_status'])
        self.assertEqual(6, len({n['id'] for t in report['topics'] for n in t['nodes']}))

    def test_source_override_cannot_inherit_physical_binding(self):
        self.files['alias.view'] = 'extends: [events]\ntable_name: OTHER\n'
        self.files['activity.topic'] = 'base_view: alias\njoins: {}\n'
        report = self.build(); node = report['topics'][0]['nodes'][0]
        self.assertIsNone(node['binding_origin'])
        self.assertEqual([], node['model_ids'])
        self.assertEqual('gap', node['binding_status'])
        self.assertIsNone(query.analyze_query_views(self.files, self.context)['binding_origins']['alias'])

    def test_same_view_on_different_branches_keeps_distinct_occurrences(self):
        for name in ('accounts', 'contacts', 'regions'): self.add_view(name)
        self.files['activity.topic'] = omni.yaml.safe_dump({'base_view': 'events',
            'joins': {'accounts': {'regions': {}}, 'contacts': {'regions': {}}},
            'relationships': [self.relation('events', 'accounts'), self.relation('events', 'contacts'),
                              self.relation('accounts', 'regions'), self.relation('contacts', 'regions')]})
        topic = self.build()['topics'][0]
        regions = [n for n in topic['nodes'] if n['view_id'] == 'regions']
        self.assertEqual(2, len(regions))
        self.assertNotEqual(regions[0]['id'], regions[1]['id'])
        self.assertEqual(regions[0]['model_ids'], regions[1]['model_ids'])
        self.assertEqual('complete', topic['structural_status'])

    def test_same_name_topic_override_requires_its_scoped_binding(self):
        self.files['activity.topic'] = 'base_view: events\njoins: {}\nviews:\n  events:\n    table_name: OTHER\n'
        report = self.build(); node = report['topics'][0]['nodes'][0]
        self.assertEqual([], node['model_ids'])
        self.assertEqual(['activity/events'], node['binding_candidates'])
        self.bindings.append({'view_id': 'activity/events', 'model_ids': ['gold.events']})
        self.assertEqual('complete', self.build()['topics'][0]['nodes'][0]['binding_status'])

    def test_binding_gaps_do_not_claim_native_invalidity(self):
        for bindings, models, code in [([], self.models, 'topic.binding_missing'),
            (self.bindings * 2, self.models, 'topic.binding_ambiguous'),
            (self.bindings, [], 'topic.model_missing'),
            (self.bindings, [{'id': 'gold.events', 'layer': 'silver'}], 'topic.binding_non_gold')]:
            report = trees.build_topic_trees(self.files, self.context, bindings, models)
            topic = report['topics'][0]
            self.assertEqual('complete', topic['structural_status'])
            self.assertEqual('pending', topic['native_status'])
            self.assertEqual('gap', topic['binding_status'])
            self.assertIn(code, {d['code'] for d in topic['binding_diagnostics']})

    def test_query_view_collects_multiple_physical_dependencies(self):
        self.add_view('accounts')
        self.files['summary.query.view'] = omni.yaml.safe_dump({
            'sql': 'SELECT e."ID" AS id, a."VALUE" AS value FROM ${events} e JOIN ${accounts} a ON e."ID" = a."ID"',
            'dimensions': {'id': {}, 'value': {}}})
        self.files['activity.topic'] = 'base_view: summary\njoins: {}\n'
        node = self.build()['topics'][0]['nodes'][0]
        self.assertEqual(['accounts', 'events'], node['physical_view_ids'])
        self.assertEqual(['gold.accounts', 'gold.events'], node['model_ids'])
        self.assertEqual('complete', node['binding_status'])

    def test_missing_joins_is_not_explicit_empty_and_unsupported_topics_survive(self):
        self.files['implicit.topic'] = 'base_view: events\n'
        self.files['null_root.topic'] = 'base_view: events\njoins:\n'
        self.files['delta.topic'] = 'base_view: events\njoins: [+accounts]\n'
        self.files['composite.topic'] = 'extends: [activity, implicit]\n'
        report = self.build(); topics = {t['id']: t for t in report['topics']}
        self.assertEqual('complete', topics['activity']['structural_status'])
        self.assertEqual('implicit', topics['implicit']['joins_state'])
        self.assertEqual('unsupported', topics['implicit']['structural_status'])
        self.assertEqual('unsupported', topics['null_root']['structural_status'])
        self.assertNotEqual('complete', topics['delta']['structural_status'])
        self.assertNotEqual('complete', topics['composite']['structural_status'])
        self.assertEqual(set(report['expected_topic_ids']), set(topics))
        self.files['broken.topic'] = 'base_view: [\n'
        broken = self.build()
        self.assertIn('broken', broken['expected_topic_ids'])
        self.assertNotEqual('complete', next(t for t in broken['topics'] if t['id'] == 'broken')['structural_status'])

    def test_domain_precedence_and_determinism(self):
        self.files['sales/activity.topic'] = self.files.pop('activity.topic')
        raw = trees.build_topic_trees(self.files, self.context)
        folder = {'source_folders': {'sales': 'Folder'}}
        explicit = {'topics': {'activity': 'Explicit'}, **folder}
        self.assertEqual('Unassigned', raw['topics'][0]['domain'])
        self.assertEqual('Activity', self.build()['topics'][0]['domain'])
        self.assertEqual('Folder', trees.bind_topic_trees(raw, self.bindings, self.models, folder)['topics'][0]['domain'])
        result = trees.bind_topic_trees(raw, self.bindings, self.models, explicit)
        self.assertEqual('Explicit', result['topics'][0]['domain'])
        self.assertEqual(result, trees.build_topic_trees(dict(reversed(list(self.files.items()))), self.context, self.bindings, self.models, explicit))
        self.assertEqual('gap', raw['binding_status'])

    def test_stale_pins_and_missing_occurrences_fail_independent_coverage(self):
        report = self.build()
        with self.assertRaisesRegex(ValueError, 'stale_pins'):
            trees.bind_topic_trees(report, self.bindings, self.models, expected_pins={'model_candidate_sha256': '0' * 64})
        changed = copy.deepcopy(report); changed['topics'] = []
        self.assertEqual('failed', trees.topic_tree_coverage(changed)['status'])
        changed = copy.deepcopy(report); changed['topics'][0]['nodes'][0]['id'] = 'wrong'
        self.assertEqual('failed', trees.topic_tree_coverage(changed)['status'])
        changed = copy.deepcopy(report); changed['topics'][0]['nodes'] = []
        self.assertEqual('failed', trees.topic_tree_coverage(changed)['status'])

    def test_ambiguous_relationship_is_visible_with_node_preserved(self):
        self.add_view('accounts')
        self.files['activity.topic'] = 'base_view: events\njoins: {accounts: {}}\n'
        self.files['relationships.yml'] = omni.yaml.safe_dump([self.relation('events', 'accounts'), self.relation('events', 'accounts')])
        topic = self.build()['topics'][0]
        self.assertEqual(2, len(topic['nodes']))
        self.assertEqual('unresolved', topic['structural_status'])
        self.assertIn('topic.relationship_ambiguous', {d['code'] for d in topic['diagnostics']})


if __name__ == '__main__': unittest.main()
