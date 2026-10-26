"""One topic per base view and population; presentation-model PII controls."""
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

    def test_two_topics_without_extends_fail(self):
        result = population.assess({'a.topic': 'base_view: orders\n', 'b.topic': 'base_view: orders\n'})
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('population.multiple_main_topics', codes(result))

    def test_variant_differing_only_by_defaults_fails(self):
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

    def test_promoted_default_and_missing_ai_context_fail(self):
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

    def test_stale_decision_and_bad_extends_are_rejected(self):
        with self.assertRaises(ValueError):
            population.assess({'a.topic': 'base_view: orders\n'},
                              [{'finding_id': 'TP-missing', 'resolution': 'confirmed', 'reference': 'D-1', 'reason': 'x'}])
        result = population.assess({'a.topic': 'extends: [missing]\n'})
        self.assertEqual(codes(result), ['population.extends_unresolved'])

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
        self.assertIn('same always-where population as the main topic', page)
        self.assertEqual(topic_visuals.population_panel({}), '')


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None, 'Pinned YAML/SQL runtime required')
class PopulationDeliveryTests(unittest.TestCase):
    """Handoff pins the contract; packaging blocks until findings are resolved."""
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

    def test_unresolved_population_blocks_and_decision_unblocks(self):
        with self.assertRaisesRegex(ValueError, 'population'):
            self.package()
        findings = self.handoff.build_handoff(self.state, self.files, self.context)['summary']['topic_population']['findings']
        decisions = [{'finding_id': f['id'], 'resolution': 'open_question', 'reference': 'Q-TEST-1', 'reason': 'Pending owner.'} for f in findings]
        result = self.package(decisions, 'resolved')
        self.assertEqual(result['summary']['topic_population']['status'], 'open_questions')
        summary = result['summary']
        self.assertEqual(summary, self.handoff.verify_handoff(summary, self.state, self.files, self.context))


if __name__ == '__main__':
    unittest.main()
