"""Bounded synthetic context projection and structured evaluation tests."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_ai_context as ai
import omni_contract as omni
from test_privacy_contract import approved_classification, approved_policy


def reviewed(spec):
    spec['review'] = {'status': 'approved', 'reference': 'synthetic://definition-review',
                      'sha256': ai.digest({k: v for k, v in spec.items() if k != 'review'})}
    return spec


def fixture():
    privacy = approved_classification()
    provenance = {'origin': 'reviewer', 'review_reference': 'synthetic-review',
                  'evidence': [{'reference': 'synthetic-source', 'sha256': 'a' * 64}]}
    columns = []
    for name, data_type in [('ID', 'number'), ('AMOUNT', 'number'), ('POSTED_AT', 'timestamp')]:
        columns.append({'column_id': 'mart_shipments.' + name, 'name': name,
                        'description': 'Reviewed synthetic ' + name, 'data_type': data_type,
                        'nullability': 'NOT NULL', 'key_role': 'PRIMARY_KEY' if name == 'ID' else 'NONE',
                        'source': 'Synthetic raw ledger', 'transformation': 'Reviewed source copy', 'units': 'count',
                        'classification': 'Internal metadata', 'validation': 'Synthetic contract test',
                        'review_status': 'approved', 'provenance': copy.deepcopy(provenance),
                        'sensitivity': 'INTERNAL', 'sensitivity_review_status': 'approved',
                        'sensitivity_review_reference': 'synthetic-review',
                        'sensitivity_evidence': [{'reference': 'synthetic-source', 'sha256': 'b' * 64}],
                        'key_roles': ['PRIMARY_KEY'] if name == 'ID' else ['NONE'],
                        'source_refs': [{'object_id': 'synthetic.raw.ledger', 'column_path': [name], 'catalogue_sha256': 'a' * 64}],
                        'privacy': copy.deepcopy(privacy)})
    dictionary = {'schema_version': 2, 'kind': 'data_dictionary', 'privacy_schema_version': 1,
                  'model_inventory_sha256': 'c' * 64, 'models': [
                      {'model_id': 'mart_shipments', 'layer': 'gold', 'description': 'Reviewed shipment transactions',
                       'grain': 'One row per shipment', 'source_systems': ['synthetic-ledger'],
                       'model_role': 'FACT', 'owner': None, 'review_status': 'approved',
                       'provenance': copy.deepcopy(provenance), 'columns': columns}]}
    source = {'definitions': {'net_amount': 'Net shipment amount after recorded adjustments.',
                              'refunds': 'Treatment of refunds has not been agreed.'}}
    files = {'shipments.view': '''catalog: ANALYTICS
schema: GOLD
table_name: SHIPMENTS
dimensions:
  id:
    sql: '"ID"'
    primary_key: true
  amount:
    sql: '"AMOUNT"'
  posted_at:
    sql: '"POSTED_AT"'
    timeframes: [date, month]
measures:
  net_total:
    sql: ${amount}
    aggregate_type: sum
  count:
    aggregate_type: count
''', 'shipments.topic': '''base_view: shipments
joins: {}
fields:
  - shipments.amount
  - shipments.net_total
  - shipments.posted_at[date]
'''}
    namespace = {'database': 'ANALYTICS', 'schema': 'GOLD', 'table': 'SHIPMENTS'}
    context = {'schema_version': 1, 'kind': 'omni_model_context', 'warehouse': 'snowflake', 'environment': 'development',
               'catalogue_sha256': 'a' * 64, 'bindings': {'shipments': {'namespace': namespace,
                    'columns': {'ID': 'number', 'AMOUNT': 'number', 'POSTED_AT': 'timestamp'}, 'evidence_sha256': 'b' * 64}},
               'inherited_views': {}, 'default_catalog': None, 'user_attributes': ['region'], 'access_grants': []}
    inputs = {'dictionary': dictionary, 'source': source, 'model_files': files, 'model_context': context,
              'disclosure_policy': approved_policy()}
    binding = {'layer': 'gold', 'field_sha256': ai.digest({'sql': '${amount}', 'aggregate_type': 'sum'}),
               'columns': [{'view': 'shipments', 'column': 'AMOUNT', 'model_id': 'mart_shipments',
                            'column_id': 'mart_shipments.AMOUNT', 'namespace': namespace}]}
    spec = {'schema_version': 1, 'kind': 'omni_ai_context_spec', 'pins': ai.input_pins(**inputs),
            'bindings': {'shipments.net_total': binding}, 'definitions': [
                {'id': 'net_amount', 'status': 'approved', 'statement': source['definitions']['net_amount'],
                 'question': None, 'fields': ['shipments.net_total'],
                 'source_refs': [{'pointer': '/definitions/net_amount', 'sha256': ai.digest(source['definitions']['net_amount'])}],
                 'privacy': copy.deepcopy(privacy), 'review_reference': 'synthetic-definition-review'},
                {'id': 'refunds', 'status': 'unresolved', 'statement': None,
                 'question': 'Should refunds reduce the shipment amount on posting day or return day?',
                 'fields': ['shipments.net_total'],
                 'source_refs': [{'pointer': '/definitions/refunds', 'sha256': ai.digest(source['definitions']['refunds'])}],
                 'privacy': copy.deepcopy(privacy), 'review_reference': None}]}
    return reviewed(spec), inputs


def evaluation_fixture(context):
    suite = {'schema_version': 1, 'kind': 'omni_ai_evaluation_suite', 'context_sha256': context['context_sha256'],
             'personas': {'analyst': {'allowed_fields': ['shipments.net_total'], 'available_attributes': ['region']},
                          'missing_attribute': {'allowed_fields': ['shipments.net_total'], 'available_attributes': []}},
             'cases': [
                 {'id': 'approved_question', 'question': 'What is the net amount?', 'persona_id': 'analyst',
                  'expected': {'decision': 'answer', 'allowed_fields': ['shipments.net_total'],
                    'required_fields': ['shipments.net_total'], 'definition_ids': ['net_amount'],
                    'clarification_ids': [], 'required_attributes': ['region']}},
                 {'id': 'ambiguous_question', 'question': 'Do refunds reduce this measure?', 'persona_id': 'analyst',
                  'expected': {'decision': 'clarify', 'allowed_fields': [], 'required_fields': [],
                    'definition_ids': [], 'clarification_ids': ['refunds'], 'required_attributes': []}},
                 {'id': 'unavailable_attribute', 'question': 'Show my region amount.', 'persona_id': 'missing_attribute',
                  'expected': {'decision': 'refuse', 'allowed_fields': [], 'required_fields': [],
                    'definition_ids': [], 'clarification_ids': [], 'required_attributes': ['region']}}]}
    reviewed(suite)
    observations = {'schema_version': 1, 'kind': 'omni_ai_observations', 'suite_sha256': ai.digest(suite), 'answers': []}
    for case in suite['cases']:
        expectation = case['expected']
        observations['answers'].append({'case_id': case['id'], 'persona_id': case['persona_id'],
            'question_sha256': ai.digest(case['question']), 'context_sha256': context['context_sha256'],
            'decision': expectation['decision'], 'fields': expectation['required_fields'],
            'claims': [{'definition_id': identity, 'statement_sha256': next(
                definition['statement_sha256'] for definition in context['approved_definitions'] if definition['id'] == identity)}
                for identity in expectation['definition_ids']], 'clarification_ids': expectation['clarification_ids'],
            'attributes_used': expectation['required_attributes'] if expectation['decision'] == 'answer' else []})
    return suite, observations


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None, 'Pinned semantic runtime required')
class AIContextTests(unittest.TestCase):
    def setUp(self): self.spec, self.inputs = fixture()

    def build(self): return ai.build_context(self.spec, **self.inputs)

    def reapprove(self):
        self.spec['pins'] = ai.input_pins(**self.inputs)
        reviewed(self.spec)

    def test_curated_claims_and_unresolved_questions_are_separate(self):
        first = self.build()
        self.assertEqual(first, self.build())
        self.assertEqual(first['report']['status'], 'incomplete')
        self.assertEqual([x['id'] for x in first['context']['approved_definitions']], ['net_amount'])
        self.assertEqual([x['id'] for x in first['context']['unresolved_questions']], ['refunds'])
        self.assertNotIn('Treatment of refunds has not been agreed.', first['markdown'])
        self.assertFalse(first['context']['native_verified'])
        self.assertFalse(first['context']['review_authority_authenticated'])

    def test_each_input_pin_is_required_and_stale_input_blocks(self):
        for key in self.inputs:
            value = copy.deepcopy(self.inputs)
            if key == 'model_files': value[key]['model'] = 'label: Changed\n'
            else: value[key]['synthetic_change'] = True
            with self.subTest(input=key), self.assertRaises(ai.ContextError): ai.build_context(self.spec, **value)

    def test_exact_physical_field_dictionary_and_catalogue_mapping(self):
        for mutation in ('physical', 'dictionary', 'catalogue', 'field_hash', 'layer'):
            spec, inputs = fixture()
            binding = spec['bindings']['shipments.net_total']
            if mutation == 'physical': binding['columns'][0]['column'] = 'ID'
            if mutation == 'dictionary': binding['columns'][0]['column_id'] = 'mart_shipments.ID'
            if mutation == 'catalogue': inputs['dictionary']['models'][0]['columns'][1]['source_refs'][0]['catalogue_sha256'] = 'f' * 64
            if mutation == 'field_hash': binding['field_sha256'] = 'f' * 64
            if mutation == 'layer': binding['layer'] = 'silver'
            spec['pins'] = ai.input_pins(**inputs)
            reviewed(spec)
            with self.subTest(mutation=mutation), self.assertRaises(ai.ContextError): ai.build_context(spec, **inputs)

    def test_unknown_or_restricted_column_withholds_names_and_claim_text(self):
        for level, categories in [('RESTRICTED', ['PHI']), ('CONFIDENTIAL', ['PII', 'PCI'])]:
            spec, inputs = fixture()
            column = inputs['dictionary']['models'][0]['columns'][1]
            column.update(sensitivity=level, privacy=approved_classification(level, categories))
            spec['pins'] = ai.input_pins(**inputs); reviewed(spec)
            result = ai.build_context(spec, **inputs)
            self.assertEqual(result['context']['approved_definitions'], [])
            self.assertEqual(result['context']['fields'], [])
            self.assertNotIn('shipments.net_total', json.dumps(result))
            self.assertNotIn('Net shipment amount', json.dumps(result))
            self.assertEqual(result['report']['withheld'][0]['definition_index'], 0)

    def test_metadata_approval_does_not_grant_ai_context_disclosure(self):
        self.inputs['disclosure_policy']['destinations']['ai_context']['allowed_sensitivities'] = []
        self.reapprove()
        result = self.build()
        self.assertEqual(len(result['report']['withheld']), 2)
        self.assertEqual(result['context']['fields'], [])

    def test_sensitive_or_template_prose_withheld_without_echo(self):
        for marker in ('SYNTHETIC_PHI_CANARY', 'person@example.invalid', '{{omni_attributes.secret}}', '<script>unsafe</script>'):
            spec, inputs = fixture()
            spec['definitions'][0]['statement'] = marker
            reviewed(spec)
            result = ai.build_context(spec, **inputs)
            self.assertEqual(len(result['report']['withheld']), 1)
            self.assertNotIn(marker, json.dumps(result))

    def test_unapproved_dictionary_meaning_becomes_question_never_approved_claim(self):
        self.inputs['dictionary']['models'][0]['columns'][1]['review_status'] = 'proposed'
        self.inputs['dictionary']['models'][0]['columns'][1]['key_roles'] = ['UNKNOWN']
        self.reapprove()
        result = self.build()
        self.assertEqual(result['context']['approved_definitions'], [])
        self.assertEqual(len(result['context']['unresolved_questions']), 2)
        self.assertNotIn('Net shipment amount', result['markdown'])

    def test_unresolved_record_cannot_smuggle_a_statement(self):
        self.spec['definitions'][1]['statement'] = 'Invented refund rule'
        reviewed(self.spec)
        with self.assertRaises(ai.ContextError): self.build()

    def test_fabricated_source_ref_or_missing_review_blocks(self):
        for mutate in (lambda spec: spec['definitions'][0]['source_refs'][0].update(pointer='/missing'),
                       lambda spec: spec['definitions'][0].update(review_reference=None),
                       lambda spec: spec.update(review={'status': 'approved', 'reference': 'x', 'sha256': 'f' * 64})):
            self.spec, self.inputs = fixture(); mutate(self.spec)
            if self.spec['review']['sha256'] != 'f' * 64: reviewed(self.spec)
            with self.assertRaises(ai.ContextError): self.build()

    def test_count_retains_all_columns_in_lineage(self):
        self.spec['bindings'] = {'shipments.count': {'layer': 'gold', 'field_sha256': ai.digest({'aggregate_type': 'count'}),
            'columns': [dict(self.spec['bindings']['shipments.net_total']['columns'][0], column=name, column_id='mart_shipments.' + name)
                        for name in ('ID', 'AMOUNT', 'POSTED_AT')]}}
        for record in self.spec['definitions']: record['fields'] = ['shipments.count']
        self.reapprove()
        result = self.build()
        self.assertEqual(len(result['context']['fields'][0]['gold_columns']), 3)
        self.spec['bindings']['shipments.count']['columns'].pop()
        reviewed(self.spec)
        with self.assertRaises(ai.ContextError): self.build()

    def test_dictionary_layer_and_nonempty_catalogue_lineage_required(self):
        for value in ('bronze', 'silver', None, 'missing_source'):
            self.spec, self.inputs = fixture()
            model = self.inputs['dictionary']['models'][0]
            if value == 'missing_source': model['columns'][1]['source_refs'] = []
            elif value is None: model.pop('layer')
            else: model['layer'] = value
            self.reapprove()
            with self.subTest(value=value), self.assertRaises(ai.ContextError): self.build()

    def test_distinct_measure_key_requires_complete_privacy_lineage(self):
        self.inputs['model_files']['shipments.view'] = self.inputs['model_files']['shipments.view'].replace(
            'aggregate_type: sum', 'aggregate_type: sum_distinct_on\n    custom_primary_key_sql: ${id}')
        binding = self.spec['bindings']['shipments.net_total']
        binding['field_sha256'] = ai.digest({'sql': '${amount}', 'aggregate_type': 'sum_distinct_on', 'custom_primary_key_sql': '${id}'})
        self.reapprove()
        with self.assertRaises(ai.ContextError): self.build()
        binding['columns'].append(dict(binding['columns'][0], column='ID', column_id='mart_shipments.ID'))
        self.reapprove()
        self.assertEqual(len(self.build()['context']['fields'][0]['gold_columns']), 2)

    def test_writer_rejects_tampered_counts_status_and_native_flags(self):
        mutations = [lambda report: report.update(status='complete'),
                     lambda report: report.update(native_verified=True),
                     lambda report: report.update(authorization_authenticated=True),
                     lambda report: report.update(approved_definitions=99),
                     lambda report: report.update(markdown_sha256='f' * 64)]
        with tempfile.TemporaryDirectory() as tmp:
            for mutate in mutations:
                result = self.build(); mutate(result['report'])
                target = Path(tmp).resolve() / 'rejected'
                with self.assertRaises(ai.ContextError): ai.write_context(result, target)
                self.assertFalse(target.exists())

    def test_writer_cleans_incomplete_output_on_file_creation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve() / 'failed'
            real_open = ai.os.open
            def failing_open(path, flags, mode=0o777, **kwargs):
                if str(path).endswith('AI_CONTEXT.md'): raise OSError('synthetic disk failure')
                return real_open(path, flags, mode, **kwargs)
            with patch.object(ai.os, 'open', side_effect=failing_open), self.assertRaises(OSError):
                ai.write_context(self.build(), target)
            self.assertFalse(target.exists())

    def test_write_is_private_exclusive_and_no_originals_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve() / 'context'
            ai.write_context(self.build(), output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual({p.name for p in output.iterdir()}, {'AI_CONTEXT.json', 'AI_CONTEXT.md', 'BUILD_REPORT.json'})
            for item in output.iterdir(): self.assertEqual(item.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ai.ContextError): ai.write_context(self.build(), output)

    def test_frozen_structured_evaluation_passes_without_claiming_live_ai(self):
        context = self.build()['context']; suite, observations = evaluation_fixture(context)
        report = ai.evaluate_answers(suite, observations, context)
        self.assertEqual(report['status'], 'passed', report)
        self.assertEqual(report['cases_compared'], 3)
        self.assertFalse(report['live_ai_authenticated'])
        self.assertFalse(report['natural_language_answer_verified'])
        self.assertFalse(report['access_enforcement_verified'])

    def test_observed_prohibited_field_fabricated_definition_and_unavailable_attribute_fail(self):
        context = self.build()['context']; suite, observations = evaluation_fixture(context)
        mutations = [lambda answer: answer['fields'].append('restricted.private_field'),
                     lambda answer: answer['claims'][0].update(definition_id='invented_rule'),
                     lambda answer: answer['claims'][0].update(statement_sha256='f' * 64),
                     lambda answer: answer['attributes_used'].append('unavailable_attribute'),
                     lambda answer: answer.update(persona_id='other_persona')]
        for mutate in mutations:
            observed = copy.deepcopy(observations); mutate(observed['answers'][0])
            result = ai.evaluate_answers(suite, observed, context)
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('restricted.private_field', json.dumps(result))
            self.assertNotIn('invented_rule', json.dumps(result))

    def test_ambiguous_meaning_requires_clarification_and_absent_attribute_requires_refusal(self):
        context = self.build()['context']; suite, observations = evaluation_fixture(context)
        for index in (1, 2):
            observed = copy.deepcopy(observations); observed['answers'][index]['decision'] = 'answer'
            self.assertEqual(ai.evaluate_answers(suite, observed, context)['status'], 'failed')
        suite['cases'][2]['expected'].update(decision='answer', allowed_fields=['shipments.net_total'],
            required_fields=['shipments.net_total'], definition_ids=['net_amount'])
        reviewed(suite); observations['suite_sha256'] = ai.digest(suite)
        self.assertEqual(ai.evaluate_answers(suite, observations, context)['status'], 'failed')

    def test_duplicate_missing_changed_question_and_extra_prose_observations_fail(self):
        context = self.build()['context']; suite, observations = evaluation_fixture(context)
        variants = []
        changed = copy.deepcopy(observations); changed['answers'].pop(); variants.append(changed)
        changed = copy.deepcopy(observations); changed['answers'][1] = changed['answers'][0]; variants.append(changed)
        changed = copy.deepcopy(observations); changed['answers'][0]['question_sha256'] = 'f' * 64; variants.append(changed)
        changed = copy.deepcopy(observations); changed['answers'][0]['answer_text'] = 'Plausible prose is not evidence'; variants.append(changed)
        for value in variants: self.assertEqual(ai.evaluate_answers(suite, value, context)['status'], 'failed')

    def test_scanner_blocks_sensitive_observed_values_and_reports_no_raw_text(self):
        context = self.build()['context']; suite, observations = evaluation_fixture(context)
        marker = 'SYNTHETIC_PII_CANARY'
        observations['answers'][0]['fields'] = [marker]
        result = ai.evaluate_answers(suite, observations, context)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn(marker, json.dumps(result))

    def test_cli_creates_private_bundle_and_evaluation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            values = dict(self.inputs, spec=self.spec)
            for name, value in values.items(): (root / (name + '.json')).write_text(json.dumps(value))
            command = [sys.executable, ai.__file__, 'build', '--output', str(root / 'output')]
            for flag, key in [('spec','spec'),('dictionary','dictionary'),('source','source'),('model-files','model_files'),
                              ('model-context','model_context'),('policy','disclosure_policy')]:
                command += ['--' + flag, str(root / (key + '.json'))]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertEqual(json.loads(run.stdout)['status'], 'incomplete')
            context = json.loads((root / 'output' / 'AI_CONTEXT.json').read_text())
            suite, observations = evaluation_fixture(context)
            for name, value in [('suite', suite), ('observations', observations)]:
                (root / (name + '.json')).write_text(json.dumps(value))
            run = subprocess.run([sys.executable, ai.__file__, 'evaluate', '--suite', str(root / 'suite.json'),
                '--observations', str(root / 'observations.json'), '--context', str(root / 'output' / 'AI_CONTEXT.json'),
                '--output', str(root / 'evaluation.json')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertEqual(json.loads(run.stdout)['status'], 'passed')
            self.assertEqual((root / 'evaluation.json').stat().st_mode & 0o777, 0o600)


class AIContextUnavailableRuntimeTests(unittest.TestCase):
    def test_invalid_contract_error_does_not_contain_user_text(self):
        marker = 'SYNTHETIC_PII_CANARY'
        with self.assertRaises(ai.ContextError) as raised:
            ai.build_context({'private': marker}, dictionary={}, source={}, model_files={}, model_context={}, disclosure_policy={})
        self.assertNotIn(marker, str(raised.exception))


if __name__ == '__main__': unittest.main()
