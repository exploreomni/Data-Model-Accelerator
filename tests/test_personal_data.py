"""Registered personal data never reaches gold models or Omni."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import personal_data as pd
import delivery_portal as portal
import guided_workflow
import omni_contract as omni

REGISTER = {'schema_version': 1, 'entries': [
    {'column': 'agent_email', 'table': 'customer_support_agent_teams', 'attribute': 'CONTACT_EMAIL', 'origin': 'prompt'},
    {'column': 'Agent_name', 'origin': 'prompt'},
    {'column': 'email', 'origin': 'classification'},
    {'column': 'from', 'origin': 'prompt'},
    {'column': 'title', 'origin': 'prompt'}]}

VIEW = '''schema: analytics
table_name: wh_customer_support__ticket_fct
dimensions:
  customer_support_ticket_latest_agent_email:
    hidden: true
    description: Agent email for the latest assignment.
  latest_agent_fk:
    sql: ${wh_customer_support__ticket_fct.latest_agent_fk}
  ticket_subject:
    sql: ${wh_customer_support__ticket_fct.ticket_title}
    description: Mentions the agent_name only in prose.
'''


class RegisterTests(unittest.TestCase):
    def test_normalize_collapses_duplicates_and_validates(self):
        register = pd.normalize(dict(REGISTER, entries=REGISTER['entries'] + [REGISTER['entries'][0]]))
        self.assertEqual(len(register['entries']), 5)
        self.assertIn('agent_name', [e['column'] for e in register['entries']])
        with self.assertRaises(ValueError):
            pd.normalize({'schema_version': 1, 'entries': [{'column': 'x', 'origin': 'guess'}]})
        with self.assertRaises(ValueError):
            pd.normalize({'schema_version': 1, 'not_personal_data': [{'identifier': 'x'}]})

    def test_csv_import_with_attribute_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'inventory.csv'
            with open(path, 'w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['table_name', 'column_name', 'attribute'])
                writer.writerow(['agents', 'agent_email', 'CONTACT_EMAIL'])
                writer.writerow(['companies', 'company_country', 'GEO_COUNTRY'])
            everything = pd.from_csv(path)
            narrowed = pd.from_csv(path, attributes=['contact_email'])
        self.assertEqual(len(everything['entries']), 2)
        self.assertEqual([e['column'] for e in narrowed['entries']], ['agent_email'])
        self.assertEqual(narrowed['source_reference'], 'inventory.csv')

    def test_dictionary_classifications_are_added(self):
        dictionary = {'models': [{'name': 'people', 'columns': [
            {'name': 'person_email', 'privacy': {'categories': ['PII']}},
            {'name': 'country', 'privacy': {'categories': []}}]}]}
        register = pd.from_dictionary(dictionary)
        self.assertEqual([(e['column'], e['origin']) for e in register['entries']], [('person_email', 'classification')])
        merged = pd.merge(REGISTER, register)
        self.assertEqual(len(merged['entries']), 6)


class MatchingTests(unittest.TestCase):
    def test_renamed_gold_columns_are_caught(self):
        found = pd.check(REGISTER, [
            {'scope': 'gold.tickets', 'identifier': 'customer_support_ticket_latest_agent_email', 'kind': 'gold_column'},
            {'scope': 'gold.tickets', 'identifier': 'customer_support_ticket_first_reply_agent_name', 'kind': 'gold_column'},
            {'scope': 'gold.tickets', 'identifier': 'latest_agent_fk', 'kind': 'gold_column'},
            {'scope': 'gold.tickets', 'identifier': 'ticket_title', 'kind': 'gold_column'}])
        self.assertEqual([f['identifier'] for f in found],
                         ['customer_support_ticket_first_reply_agent_name', 'customer_support_ticket_latest_agent_email'])

    def test_single_generic_word_matches_exactly_only(self):
        self.assertTrue(pd.match(REGISTER, 'title'))
        self.assertFalse(pd.match(REGISTER, 'ticket_title'))
        self.assertTrue(pd.match(REGISTER, 'requester_email'))

    def test_false_positive_exemption_is_scoped(self):
        register = dict(REGISTER, not_personal_data=[{'identifier': 'n_msgs_from_email', 'scope': 'gold.tickets',
                                                      'reason': 'Message count, not an address.', 'reference': 'D-7'}])
        outputs = [{'scope': s, 'identifier': 'n_msgs_from_email', 'kind': 'gold_column'} for s in ('gold.tickets', 'gold.other')]
        self.assertEqual([f['scope'] for f in pd.check(register, outputs)], ['gold.other'])

    def test_sql_keywords_comments_and_literals_are_ignored(self):
        names = pd.sql_identifiers("-- agent_email\nSELECT x AS ticket_id FROM {{ ref('agent_email') }} WHERE y = 'email'")
        self.assertEqual(names, {'x', 'ticket_id', 'y'})

    def test_omni_fields_count_but_prose_does_not(self):
        names = pd.omni_identifiers(VIEW)
        self.assertIn('customer_support_ticket_latest_agent_email', names)
        self.assertIn('ticket_title', names)
        self.assertNotIn('agent_name', names)
        found = pd.check(REGISTER, [{'scope': 'v.view', 'identifier': n, 'kind': 'omni_field'} for n in names])
        self.assertEqual([f['identifier'] for f in found], ['customer_support_ticket_latest_agent_email'])


class DeliveryTests(unittest.TestCase):
    def review(self):
        return {'models': [
            {'id': 'gold.tickets', 'layer': 'gold', 'artifact_id': 'sql-gold',
             'columns': [{'name': 'ticket_pk'}, {'name': 'latest_agent_fk'}]},
            {'id': 'silver.tickets', 'layer': 'silver', 'artifact_id': 'sql-silver',
             'columns': [{'name': 'latest_agent_email'}]}]}

    def selected(self, gold_sql):
        return [{'id': 'sql-gold', 'path': 'models/wh_tickets.sql', 'category': 'implementation', 'content': gold_sql.encode()},
                {'id': 'sql-silver', 'path': 'models/int_tickets.sql', 'category': 'implementation',
                 'content': b'SELECT latest_agent_email FROM t'}]

    def test_clean_gold_and_integration_use_pass(self):
        state = {'answers': {'personal_data': pd.normalize(REGISTER)}}
        portal._check_personal_data(state, self.review(), self.selected('SELECT ticket_pk, latest_agent_fk FROM i'))

    def test_gold_code_or_column_or_omni_field_blocks(self):
        state = {'answers': {'personal_data': pd.normalize(REGISTER)}}
        with self.assertRaisesRegex(ValueError, 'personal data'):
            portal._check_personal_data(state, self.review(), self.selected('SELECT latest_agent_email AS agent_email FROM i'))
        review = self.review(); review['models'][0]['columns'].append({'name': 'latest_agent_name'})
        with self.assertRaisesRegex(ValueError, 'gold.tickets: latest_agent_name'):
            portal._check_personal_data(state, review)
        omni_file = [{'id': 'o', 'path': 'views/tickets.view', 'category': 'implementation', 'content': VIEW.encode()}]
        with self.assertRaisesRegex(ValueError, 'customer_support_ticket_latest_agent_email'):
            portal._check_personal_data(state, self.review(), omni_file)

    def test_no_register_keeps_existing_behaviour(self):
        review = self.review(); review['models'][0]['columns'].append({'name': 'latest_agent_email'})
        portal._check_personal_data({'answers': {}}, review)

    def test_answer_is_validated_and_bound_to_selection(self):
        answers = guided_workflow._answers({'personal_data': REGISTER})
        self.assertEqual(answers['personal_data'], pd.normalize(REGISTER))
        target, _, _ = guided_workflow._selection(answers)
        self.assertIn('personal_data_sha256', target)
        with self.assertRaises(ValueError):
            guided_workflow._answers({'personal_data': {'schema_version': 2}})


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None, 'Pinned YAML/SQL runtime required')
class HandoffTests(unittest.TestCase):
    def test_handoff_refuses_registered_omni_fields(self):
        import omni_handoff as handoff
        from test_omni_contract import files, context
        from test_delivery_portal import fixture
        with tempfile.TemporaryDirectory() as folder:
            state, _ = fixture(Path(folder).resolve())
            ctx = context(); state['inputs']['catalogue']['sha256'] = ctx['catalogue_sha256']
            model = files()
            field = next(n for n in sorted(pd.omni_identifiers(model['events.view'])) if not n.endswith('_pk'))
            state['answers']['personal_data'] = pd.normalize({'schema_version': 1, 'entries': [{'column': field, 'origin': 'prompt'}]})
            with self.assertRaisesRegex(ValueError, 'handoff.personal_data'):
                handoff.build_handoff(state, model, ctx)


if __name__ == '__main__':
    unittest.main()
