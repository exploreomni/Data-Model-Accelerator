"""Explicit legacy exclusions and source-qualified candidate privacy treatments."""
import copy
import csv
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import personal_data as pd
import delivery_portal as portal
import guided_workflow
import omni_contract as omni
import privacy_contract as privacy

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
        self.assertEqual(narrowed['schema_version'], 2)
        self.assertEqual(narrowed['treatments'], [])
        self.assertTrue(all(e['classification']['review_status'] == 'unresolved' for e in narrowed['entries']))

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
        if omni.yaml is None: self.skipTest('Optional YAML parser required for field extraction')
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
        if omni.yaml is None or omni.sqlglot is None: self.skipTest('Optional SQL/YAML parser required for artifact projections')
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
            field = 'id'
            state['answers']['personal_data'] = pd.normalize({'schema_version': 1, 'entries': [{'column': field, 'origin': 'prompt'}]})
            with self.assertRaisesRegex(ValueError, 'handoff.personal_data'):
                handoff.build_handoff(state, model, ctx)


class TreatmentTests(unittest.TestCase):
    def register(self):
        value = privacy.new_classification('CONFIDENTIAL')
        value.update(categories=['PII'], categories_known=True)
        value['lineage'] = {'status': 'complete', 'upstream_ids': [], 'transformation': 'source'}
        return {'schema_version': 2, 'entries': [{'table': 'raw.customers', 'column': 'email',
                'origin': 'classification', 'classification': value}], 'treatments': []}

    def output(self, table='raw.customers'):
        return {'scope': 'gold.customers', 'identifier': 'contact_key', 'kind': 'gold_code', 'destination': 'gold',
                'source_columns': [{'table': table, 'column': 'email'}], 'lineage_complete': True,
                'transformation': 'copy', 'expression_sha256': 'a' * 64}

    def decide(self, register, action='retain_with_controls', transformation='copy', expression=None):
        decision = privacy.new_treatment({'table': 'raw.customers', 'column': 'email'}, 'gold')
        decision.update(treatment=action, transformation=transformation, review_reference='DEC-privacy-7',
                        controls=['Reviewed warehouse access policy'], expression_sha256=expression)
        register['treatments'].append(decision)

    def test_source_qualification_and_explicit_destination_treatment(self):
        register = self.register()
        self.assertEqual(pd.normalize(register)['entries'][0]['table'], 'raw.customers')
        self.assertEqual(pd.assess(register, [self.output('raw_customers')])['status'], 'clear')
        self.assertEqual(pd.assess(register, [self.output()])['status'], 'unresolved')
        self.decide(register)
        result = pd.assess(register, [self.output()])
        self.assertEqual(result['status'], 'clear')
        self.assertFalse(result['authorization_authenticated'])
        self.assertFalse(result['native_controls_verified'])
        self.assertEqual(pd.assess(register, [dict(self.output(), destination='omni')])['status'], 'unresolved')
        register['treatments'][0]['treatment'] = 'exclude'
        self.assertEqual(pd.assess(register, [self.output()])['status'], 'violations')
        self.assertEqual(pd.assess(register, [self.output('other.customers')])['status'], 'clear')

    def test_transformation_review_preserves_sensitivity_and_detects_change(self):
        register = self.register(); output = dict(self.output(), transformation='hash')
        self.decide(register, 'tokenize', 'hash', output['expression_sha256'])
        report = pd.assess(register, [output])
        self.assertEqual(report['status'], 'clear')
        self.assertEqual(report['impact'][0]['categories'], ['PII'])
        self.assertEqual(report['impact'][0]['sensitivity'], 'CONFIDENTIAL')
        self.assertFalse(report['impact'][0]['declassified'])
        self.assertEqual(report['impact'][0]['classification_review_status'], 'proposed')
        for changed in (dict(output, expression_sha256='b' * 64), dict(output, lineage_complete=False),
                        dict(output, transformation='copy')):
            self.assertEqual(pd.assess(register, [changed])['status'], 'unresolved')
        register['treatments'][0]['review_reference'] = None
        self.assertEqual(pd.assess(register, [output])['status'], 'unresolved')

    @unittest.skipUnless(omni.sqlglot is not None, 'Optional SQL parser required')
    def test_actual_projections_trace_aliases_ctes_hashes_and_quoted_names(self):
        sql = 'WITH src AS (SELECT SHA2("email", 256) AS masked FROM {{ source("raw", "customers") }}) SELECT masked AS contact_key FROM src'
        rows = pd.sql_outputs(sql, 'gold.sql', dialect='snowflake')
        self.assertEqual([r['identifier'] for r in rows], ['contact_key'])
        self.assertEqual(rows[0]['source_columns'], [{'table': 'raw.customers', 'column': 'email'}])
        self.assertTrue(rows[0]['lineage_complete'])
        self.assertEqual(rows[0]['transformation'], 'hash')
        self.assertEqual(pd.assess(self.register(), rows)['status'], 'unresolved')
        for query in ('SELECT * FROM raw.customers', 'SELECT {{ secret_macro() }} AS x',
                      'SELECT email FROM raw.customers c JOIN raw.agents a ON c.id=a.id'):
            self.assertTrue(any(not r['lineage_complete'] for r in pd.sql_outputs(query, 'gold.sql')))
        legacy = {'schema_version': 1, 'entries': [{'table': 'raw.customers', 'column': 'email', 'origin': 'prompt'}]}
        self.assertEqual(pd.assess(legacy, pd.sql_outputs('SELECT email FROM raw.agents', 'other.sql'))['status'], 'clear')
        self.assertEqual(pd.assess(legacy, rows)['status'], 'violations')

    def test_unavailable_parsers_and_omni_unknowns_are_visible(self):
        from unittest.mock import patch
        with patch.dict(sys.modules, {'sqlglot': None}):
            self.assertEqual(pd.sql_outputs('SELECT email FROM raw.customers', 'gold.sql')[0]['lineage_reasons'], ['sql.parser_unavailable'])
        with patch('omni_contract._load', side_effect=ValueError('Unavailable')):
            rows = pd.omni_outputs('dimensions: {}', 'events.view')
            self.assertFalse(rows[0]['lineage_complete'])
        if omni.yaml is not None:
            rows = pd.omni_outputs('schema: raw\ntable_name: customers\ndimensions:\n  email: {}\n  alias: {sql: "${other.email}"}\n', 'events.view')
            self.assertEqual(rows[0]['source_columns'], [{'table': 'raw.customers', 'column': 'email'}])
            self.assertFalse(rows[1]['lineage_complete'])
            self.assertEqual(pd.assess(self.register(), rows)['status'], 'unresolved')

    def test_cli_reports_impact_without_input_values(self):
        output = self.output(); output['raw_value'] = 'VALUE_MUST_NOT_LEAVE'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'register.json').write_text(json.dumps(self.register()))
            (root / 'outputs.json').write_text(json.dumps([output]))
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = pd.main(['assess', '--register', str(root / 'register.json'), '--outputs', str(root / 'outputs.json')])
        self.assertEqual(code, 0)
        self.assertNotIn('VALUE_MUST_NOT_LEAVE', stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())['status'], 'unresolved')


if __name__ == '__main__':
    unittest.main()
