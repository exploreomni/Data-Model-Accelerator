"""Advisory consolidation, exact decisions and preserved security differences."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_contract as omni
import omni_topic_population as population
import topic_visuals

MAIN = ('base_view: tickets\n'
        'always_where_filters:\n  tickets.is_deleted:\n    is: false\n'
        'default_filters:\n  tickets.is_cs_ticket:\n    is: true\n'
        'ai_context: Use for all support questions. Variant kyc_tickets fixes the KYC population.\n')


def codes(result):
    return sorted(f['code'] for f in result['findings'])


@unittest.skipUnless(omni.yaml is not None, 'PyYAML required')
class TopicPopulationTests(unittest.TestCase):
    def test_single_topic_without_population_rule_is_complete(self):
        result = population.assess({'orders.topic': 'base_view: orders\n'})
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['shared_base_views'], [])

    def test_two_topics_without_extends_need_advisory_review(self):
        result = population.assess({'a.topic': 'base_view: orders\n', 'b.topic': 'base_view: orders\n'})
        self.assertEqual(result['status'], 'review_required')
        self.assertIn('population.multiple_main_topics', codes(result))
        self.assertTrue(all(f['severity'] == 'advisory' for f in result['findings']))
        self.assertFalse(result['merge_authorized'])

    def test_variant_differing_only_by_defaults_is_optional_consolidation(self):
        result = population.assess({
            'support.topic': MAIN.replace('kyc_tickets', 'uk_tickets'),
            'uk_tickets.topic': ('extends: [support]\ndefault_filters:\n  tickets.country:\n    is: gb\n'
                                 'ai_context: GB default view of support.\n')})
        self.assertIn('population.variant_same_population', codes(result))
        self.assertNotIn('population.multiple_main_topics', codes(result))

    def test_deliberate_population_with_cross_references_only_needs_confirmation(self):
        result = population.assess({
            'support.topic': MAIN,
            'kyc_tickets.topic': ('extends: [support]\nalways_where_filters:\n  tickets.is_deleted:\n    is: false\n'
                                  '  tickets.is_team_kyc:\n    is: true\n'
                                  'ai_context: Fixed KYC-team population; use support for everything else.\n')})
        self.assertEqual(codes(result), ['population.always_where_unconfirmed'] * 2)
        rows = {r['topic']: r for r in result['shared_base_views']}
        self.assertEqual(rows['kyc_tickets']['role'], 'variant')
        self.assertFalse(rows['kyc_tickets']['same_population_as_main'])
        decided = population.assess({'support.topic': MAIN, 'kyc_tickets.topic':
                                     'extends: [support]\nalways_where_filters:\n  tickets.is_deleted:\n    is: false\n'
                                     '  tickets.is_team_kyc:\n    is: true\n'
                                     'ai_context: Fixed KYC-team population; use support for everything else.\n'},
                                    [{'finding_id': f['id'], 'resolution': 'confirmed' if 'support' in f['topics'] else 'open_question',
                                      'reference': 'Q-1', 'reason': 'Deliberate KYC population.'} for f in result['findings']])
        self.assertEqual(decided['status'], 'open_questions')
        self.assertEqual(len(decided['open_questions']), 1)
        self.assertEqual(decided['open_questions'][0]['reference'], 'Q-1')

    def test_promoted_default_and_missing_ai_context_need_review(self):
        result = population.assess({
            'support.topic': MAIN.replace('kyc_tickets', 'other'),
            'cs_only.topic': ('extends: [support]\nalways_where_filters:\n  tickets.is_deleted:\n    is: false\n'
                              '  tickets.is_cs_ticket:\n    is: true\n')})
        found = codes(result)
        for code in ('population.default_promoted_to_always_where', 'population.ai_context_missing_variant',
                     'population.ai_context_missing_main'):
            self.assertIn(code, found)

    def test_inherited_always_where_is_not_reconfirmed(self):
        result = population.assess({'support.topic': MAIN, 'kyc_tickets.topic':
                                    'extends: [support]\nalways_where_filters:\n  tickets.is_deleted:\n    is: false\n'
                                    '  tickets.is_team_kyc:\n    is: true\nai_context: KYC population of support.\n'})
        unconfirmed = [f for f in result['findings'] if f['code'] == 'population.always_where_unconfirmed']
        self.assertEqual({tuple(f['fields']) for f in unconfirmed},
                         {('tickets.is_deleted',), ('tickets.is_team_kyc',)})

    def test_stale_decision_and_bad_extends_remain_visible(self):
        stale = population.assess({'a.topic': 'base_view: orders\n'},
                                  [{'finding_id': 'TP-missing', 'resolution': 'confirmed', 'reference': 'D-1', 'reason': 'x'}])
        self.assertEqual(stale['status'], 'review_required')
        self.assertEqual(stale['stale_decisions'][0]['reference'], 'D-1')
        for value in ('[missing]', '123', '[orders, 42]', 'null', 'orders', '[]'):
            with self.subTest(value=value):
                files = {'a.topic': 'base_view: orders\nextends: ' + value + '\n'}
                result = population.assess(files)
                self.assertEqual(codes(result), ['population.extends_unresolved'])
                decided = population.assess(files, self.decisions(result))
                self.assertEqual(decided['status'], 'review_required')

    def test_contract_carries_no_filter_values(self):
        result = population.assess({'support.topic': MAIN.replace('is: true', 'is: secret_value')})
        self.assertNotIn('secret_value', repr(result))

    def test_report_panel(self):
        result = population.assess({'support.topic': MAIN, 'kyc_tickets.topic':
                                    'extends: [support]\nai_context: <b>support</b> defaults.\n'})
        page = topic_visuals.population_panel({'review': {'omni': {'topic_population': result}}})
        self.assertIn('Topics sharing a base view', page)
        self.assertIn('kyc_tickets', page)
        self.assertNotIn('<b>', page)
        self.assertIn('same declared fixed population', page)
        self.assertEqual(topic_visuals.population_panel({}), '')

    @staticmethod
    def decisions(result):
        return [{'finding_id': f['id'], 'resolution': 'confirmed', 'reference': 'D-1',
                 'reason': 'Retain the reviewed topic purpose.'} for f in result['findings']]

    def test_security_and_modeling_differences_never_suggest_merging(self):
        files = {'main.topic': 'base_view: orders\nai_context: Compare specialized.\n',
                 'specialized.topic': ('extends: [main]\nai_context: Specialized main audience.\n'
                    'access_filters:\n  - field: orders.tenant_id\n    user_attribute: secret_tenant\n'
                    'required_access_grants: [secret_grant]\njoins: {customers: {}}\n'
                    'fields: [orders.id]\nlabel: Finance\n'
                    'views:\n  orders:\n    measures:\n      total:\n        sql: ${amount}\n        aggregate_type: sum\n')}
        result = population.assess(files)
        self.assertNotIn('population.variant_same_population', codes(result))
        incompatible = next(f for f in result['findings'] if f['code'] == 'population.consolidation_incompatible')
        self.assertTrue({'security', 'joins', 'fields', 'measures', 'audience', 'scoped_views'} <= set(incompatible['differences']))
        row = next(r for r in result['shared_base_views'] if r['topic'] == 'specialized')
        self.assertEqual(row['consolidation'], 'keep_separate_pending_review')
        self.assertFalse(row['merge_authorized'])
        for secret in ('secret_tenant', 'secret_grant', '${amount}'):
            self.assertNotIn(secret, repr(result))

    def test_changed_filter_operator_or_access_invalidates_only_affected_decisions(self):
        files = {'support.topic': MAIN, 'orders.topic': 'base_view: orders\nalways_where_filters:\n  orders.live:\n    is: true\n'}
        initial = population.assess(files); decisions = self.decisions(initial)
        baseline = {tuple(f['topics']): f['id'] for f in initial['findings']}
        self.assertEqual(population.assess(files, decisions)['status'], 'complete')
        for replacement in (MAIN.replace('is: false', 'is: secret_value'),
                            MAIN.replace('is: false', 'not: false'),
                            MAIN + 'required_access_grants: [private_group]\n'):
            with self.subTest(replacement=replacement):
                changed = population.assess(dict(files, **{'support.topic': replacement}), decisions)
                self.assertEqual(changed['status'], 'review_required')
                self.assertEqual([d['finding_id'] for d in changed['stale_decisions']], [baseline[('support',)]])
                order = next(f for f in changed['findings'] if f['topics'] == ['orders'])
                self.assertEqual(order['id'], baseline[('orders',)])
                self.assertEqual(order['resolution'], 'confirmed')
                self.assertNotIn('secret_value', repr(changed))
                self.assertNotIn('private_group', repr(changed))

    def test_partial_inheritance_preserves_parent_filters_and_scoped_measures(self):
        files = {'support.topic': MAIN + ('views:\n  tickets:\n    required_access_grants: [private_group]\n'
                 '    measures:\n      total:\n        sql: ${amount}\n        aggregate_type: sum\n'),
                 'kyc_tickets.topic': ('extends: [support]\nai_context: KYC population of support.\n'
                    'always_where_filters:\n  tickets.is_team_kyc:\n    is: true\n'
                    'default_filters:\n  tickets.country:\n    is: gb\n')}
        result = population.assess(files)
        variant = next(r for r in result['shared_base_views'] if r['topic'] == 'kyc_tickets')
        self.assertEqual(variant['always_where_fields'], ['tickets.is_deleted', 'tickets.is_team_kyc'])
        self.assertEqual(variant['default_filter_fields'], ['tickets.country', 'tickets.is_cs_ticket'])
        self.assertEqual(variant['compatibility_differences'], [])
        self.assertNotIn('private_group', repr(result))
        # An inherited access-rule change also changes the variant fingerprint.
        updated = population.assess(dict(files, **{'support.topic': files['support.topic'].replace('private_group', 'new_group')}), self.decisions(result))
        self.assertEqual(len(updated['stale_decisions']), len(result['findings']))


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None, 'Pinned YAML/SQL runtime required')
class PopulationDeliveryTests(unittest.TestCase):
    """Handoff pins the advisory contract while preserving candidate review."""
    def setUp(self):
        import tempfile
        import delivery_portal as portal
        import omni_handoff as handoff
        from test_omni_contract import files, context
        from test_delivery_portal import fixture
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.portal, self.handoff = portal, handoff
        self.state, self.review = fixture(self.root)
        self.context = context(); self.files = files()
        self.files['activity_copy.topic'] = 'base_view: events\njoins: {}\n'
        self.state['inputs']['catalogue']['sha256'] = self.context['catalogue_sha256']
        self.review['context_sha256'] = portal.context_fingerprint(self.state)

    def package(self, decisions=None, name='semantic'):
        result = self.handoff.build_handoff(self.state, self.files, self.context, population_decisions=decisions)
        registration = self.handoff.write_handoff(result, self.root / name)
        review = dict(self.review, artifacts=registration['artifacts'], omni=registration['omni'])
        self.portal.package_delivery(self.state, review, self.root / name, self.root / (name + '.zip'), audience='engineer')
        return result

    def test_unresolved_population_packages_with_review_required(self):
        candidate = self.package()
        self.assertEqual(candidate['summary']['topic_population']['status'], 'review_required')
        findings = self.handoff.build_handoff(self.state, self.files, self.context)['summary']['topic_population']['findings']
        decisions = [{'finding_id': f['id'], 'resolution': 'open_question', 'reference': 'Q-TEST-1', 'reason': 'Pending owner.'} for f in findings]
        result = self.package(decisions, 'resolved')
        self.assertEqual(result['summary']['topic_population']['status'], 'open_questions')
        summary = result['summary']
        self.assertEqual(summary, self.handoff.verify_handoff(summary, self.state, self.files, self.context))


if __name__ == '__main__':
    unittest.main()
