"""Rule wording, authority boundaries and dependency-specific reuse."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import business_rules as rules
import engagement_stages as stages
from ae_common import hash_json
import test_engagement_stages as fixtures


class BusinessRulesTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.pack = rules.from_text('Exclude internal orders.', rule_id='orders.population',
                                    domain='commerce', source_reference='synthetic://interview')
        self.pack['rules'][0]['scope'] = {'domains': [], 'model_ids': ['orders'], 'asset_ids': []}

    def register(self, pack=None):
        self.h.action('record-business-rules', document=pack or self.pack)

    def accept(self):
        self.h.action('review-business-rules', document={
            'schema_version': 1, 'kind': 'human_business_rule_review',
            'engagement_id': self.h.state['engagement_id'], 'pack_sha256': hash_json(rules.read(self.h.state)),
            'reviewer': 'Synthetic SME', 'review_reference': 'synthetic://review',
            'decisions': [{'rule_id': r['id'], 'decision': 'accepted', 'rationale': 'Confirmed example.'}
                          for r in rules.read(self.h.state)['rules']]})

    def test_no_pack_leaves_entity_bindings_unchanged(self):
        before = stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.register({'schema_version': 1, 'rules': []})
        self.assertEqual(before, stages.entity_bindings(self.h.state, ['orders', 'products']))

    def test_scoped_rule_only_invalidates_affected_models(self):
        before = stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.register()
        after = stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(before['customers'], after['customers'])

    def test_import_is_proposed_and_review_does_not_approve_design(self):
        self.register()
        self.assertEqual(rules.summary(self.h.state)['rows'][0]['status'], 'proposed')
        self.accept()
        self.assertEqual(rules.summary(self.h.state)['rows'][0]['status'], 'accepted')
        self.assertEqual(self.h.state['workflow']['approvals'], [])

    def test_changed_definition_loses_old_acceptance(self):
        self.register(); self.accept()
        self.pack['rules'][0]['definition']['time'] = 'UTC calendar day'
        self.register()
        self.assertEqual(rules.summary(self.h.state)['rows'][0]['status'], 'proposed')

    def test_supplied_status_or_bad_wording_hash_rejected(self):
        for key, value in [('status', 'accepted'), ('statement', 'Different wording')]:
            pack = copy.deepcopy(self.pack); pack['rules'][0][key] = value
            with self.assertRaises(ValueError): rules.validate(pack)

    def test_shared_definition_conflicts_are_scoped(self):
        first = self.pack['rules'][0]
        first['conflict_key'] = 'population'; first['definition'] = {'population': 'external'}
        second = copy.deepcopy(first); second['id'] = 'orders.other'; second['definition'] = {'population': 'all'}
        self.pack['rules'].append(second)
        self.register(); self.accept()
        self.assertTrue(rules.gaps(self.h.state, ['orders']))
        self.assertEqual(rules.gaps(self.h.state, ['products']), [])

    def test_targeted_context_and_package_selection(self):
        self.register()
        self.assertEqual(rules.context_packet(self.h.state, ['products'])['rules'], [])
        self.assertEqual(rules.context_packet(self.h.state, ['orders'])['rules'][0]['statement'], 'Exclude internal orders.')
        self.assertEqual(rules.summary(self.h.state, ['products'])['rows'], [])

    def test_corrupted_retained_pack_is_not_reused(self):
        self.register()
        path = Path(self.h.state['workflow']['migration_review']['business_rules']['path'])
        path.write_text('{}')
        with self.assertRaises(ValueError): rules.scope_bindings(self.h.state)

    def test_unknown_scope_is_visible_and_not_applied_to_other_models(self):
        self.pack['rules'][0]['scope']['model_ids'] = ['future.model']
        self.register()
        self.assertEqual(rules.scope_bindings(self.h.state), {})
        self.assertEqual(rules.summary(self.h.state)['rows'][0]['model_ids'], [])

    def test_explicit_provisional_request_survives_unresolved_rule_conflict(self):
        first = self.pack['rules'][0]
        first['conflict_key'] = 'population'; first['definition'] = {'population': 'external'}
        second = copy.deepcopy(first); second['id'] = 'orders.other'; second['definition'] = {'population': 'all'}
        self.pack['rules'].append(second)
        self.register(); self.accept()
        scope = ['orders']
        self.h.action('request-draft', entities=scope, document={
            'schema_version': 1, 'kind': 'provisional_code_request',
            'requester': 'Synthetic operator', 'request_reference': 'synthetic://draft',
            'request_text': 'Generate provisional code and expose the population conflict for review.',
            'bindings': stages.draft_bindings(self.h.state, scope)})
        self.h.action('stage', entities=scope, stage='implementation')
        self.assertTrue(rules.gaps(self.h.state, scope))
        self.assertEqual(stages.approved_entities(self.h.state), set())


if __name__ == '__main__': unittest.main()
