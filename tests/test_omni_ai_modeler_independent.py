"""Independent portable-AI v2 lineage and imported-trial holdouts.

Synthetic classifications/review hashes exercise contracts, not authority.
Lineage expectations are enumerated here, never derived from the implementation.
Trial checks run without optional modeling packages using a portable input.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / 'tests/fixtures/omni_modeler'
sys.path.insert(0, str(REPO / 'skills/data-model-accelerator/scripts'))
import omni_ai_context as ai
import omni_contract as omni

RUNTIME = omni.yaml is not None and omni.sqlglot is not None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def privacy(protected=False):
    return {'schema_version': 1, 'kind': 'sensitive_data_classification',
            'sensitivity': 'RESTRICTED' if protected else 'PUBLIC',
            'categories': ['PII'] if protected else [], 'categories_known': True,
            'review_status': 'approved', 'review_reference': 'synthetic-declaration-only',
            'evidence': [{'reference': 'synthetic-classification', 'sha256': '4' * 64}],
            'lineage': {'status': 'complete', 'upstream_ids': [], 'transformation': 'source'},
            'handling': {key: 'allow' for key in ('agent_input', 'metadata', 'ai_context', 'share')}}


def policy():
    return {'schema_version': 1, 'kind': 'disclosure_policy', 'policy_id': 'synthetic-public-only',
            'review_status': 'approved', 'review_reference': 'synthetic-policy-only',
            'evidence': [{'reference': 'synthetic-policy', 'sha256': '5' * 64}],
            'destinations': {key: {'allowed_sensitivities': ['PUBLIC'], 'allowed_categories': []}
                             for key in ('agent_input', 'metadata', 'ai_context', 'share')},
            'host_boundary': {'mode': 'presanitized_only', 'evidence_reference': 'synthetic-not-host-proof'}}


def review(value):
    value['review'] = {'status': 'approved', 'reference': 'synthetic-review-not-authenticated',
                       'sha256': digest({key: item for key, item in value.items() if key != 'review'})}
    return value


def refresh(spec, inputs):
    spec['pins'] = {key + '_sha256': digest(inputs[name]) for key, name in (
        ('dictionary', 'dictionary'), ('source', 'source'), ('model', 'model_files'),
        ('model_context', 'model_context'), ('disclosure_policy', 'disclosure_policy'))}
    review(spec)


def dictionary_for(context):
    provenance = {'origin': 'reviewer', 'review_reference': 'synthetic-only',
                  'evidence': [{'reference': 'synthetic-input', 'sha256': '6' * 64}]}
    models = []
    for view, binding in context['bindings'].items():
        model_id = 'gold_' + view
        columns = []
        for name, datatype in binding['columns'].items():
            columns.append({'column_id': model_id + '.' + name, 'name': name,
                'description': 'Synthetic column definition', 'data_type': datatype, 'nullability': 'NULLABLE',
                'key_role': 'NONE', 'key_roles': ['NONE'], 'source': 'Independent synthetic corpus',
                'transformation': 'Exact synthetic binding', 'units': 'declared source units',
                'classification': 'Synthetic metadata', 'validation': 'Local contract only',
                'review_status': 'approved', 'provenance': copy.deepcopy(provenance),
                'sensitivity': 'PUBLIC', 'sensitivity_review_status': 'approved',
                'sensitivity_review_reference': 'synthetic-only',
                'sensitivity_evidence': [{'reference': 'synthetic-only', 'sha256': '7' * 64}],
                'source_refs': [{'object_id': 'synthetic.' + view, 'column_path': [name],
                                 'catalogue_sha256': context['catalogue_sha256']}], 'privacy': privacy()})
        models.append({'model_id': model_id, 'layer': 'gold', 'description': 'Synthetic table definitions',
                       'grain': 'Declared synthetic key', 'source_systems': ['synthetic-corpus'],
                       'model_role': 'FACT', 'owner': None, 'review_status': 'approved',
                       'provenance': copy.deepcopy(provenance), 'columns': columns})
    return {'schema_version': 2, 'kind': 'data_dictionary', 'privacy_schema_version': 1,
            'model_inventory_sha256': '8' * 64, 'models': models}


def case_files(case_id):
    cases = json.loads((CORPUS / 'cases.json').read_text())['cases']
    selected = next(case for case in cases if case['id'] == case_id)
    return {name: (CORPUS / path).read_text() for name, path in selected['files'].items()}


def context_case(files, field, field_definition, columns, topic=None):
    model_context = json.loads((CORPUS / 'context.json').read_text())
    statement = 'Synthetic reviewed amount at the declared grain.'
    inputs = {'dictionary': dictionary_for(model_context), 'source': {'definition': statement},
              'model_files': copy.deepcopy(files), 'model_context': model_context,
              'disclosure_policy': policy()}
    bound = [{'view': view, 'column': column, 'model_id': 'gold_' + view,
              'column_id': 'gold_' + view + '.' + column,
              'namespace': copy.deepcopy(model_context['bindings'][view]['namespace'])}
             for view, column in columns]
    spec = {'schema_version': 1, 'kind': 'omni_ai_context_spec', 'pins': {},
            'bindings': {field: {'layer': 'gold', 'field_sha256': digest(field_definition), 'columns': bound}},
            'definitions': [{'id': 'corpus_definition', 'status': 'approved', 'statement': statement,
                'question': None, 'fields': [field], 'source_refs': [{'pointer': '/definition', 'sha256': digest(statement)}],
                'privacy': privacy(), 'review_reference': 'synthetic-only'}], 'review': {}}
    if topic is not None: spec['topic'] = topic
    refresh(spec, inputs)
    return spec, inputs


def protect(inputs, view, column):
    row = next(c for model in inputs['dictionary']['models'] if model['model_id'] == 'gold_' + view
               for c in model['columns'] if c['name'] == column)
    row['privacy'] = privacy(True); row['sensitivity'] = 'RESTRICTED'


def portable_context():
    """Hand-authored imported context for dependency-free evaluation tests."""
    fields = ['orders.paid_shipping_cents', 'orders.shipping_cents']
    namespace = {'database': 'CORPUS', 'schema': 'SYNTHETIC', 'table': 'ORDERS'}
    definitions = []
    for identity, field, statement in (
            ('paid_shipping', fields[0], 'Shipping cents for paid orders only.'),
            ('all_shipping', fields[1], 'Shipping cents across all order statuses.')):
        definitions.append({'id': identity, 'fields': [field], 'source_evidence_sha256': '1' * 64,
                            'statement': statement, 'statement_sha256': digest(statement)})
    context = {'schema_version': 1, 'kind': 'omni_ai_context', 'contract_version': ai.VERSION,
        'pins': {key: '2' * 64 for key in ('dictionary_sha256', 'source_sha256', 'model_sha256',
                 'model_context_sha256', 'disclosure_policy_sha256')}, 'spec_sha256': '3' * 64,
        'rules': list(ai.RULES), 'topic_scope': None,
        'fields': [{'field': field, 'field_sha256': '4' * 64, 'gold_columns': [
            {'view': 'orders', 'column': 'shipping_cents', 'model_id': 'gold_orders',
             'column_id': 'gold_orders.shipping_cents', 'namespace': copy.deepcopy(namespace)}]} for field in fields],
        'approved_definitions': definitions,
        'unresolved_questions': [{'id': 'refund_timing', 'fields': [fields[0]], 'source_evidence_sha256': '5' * 64,
                                  'question': 'Which day determines refund timing?'}],
        'withheld_definition_count': 0, 'native_verified': False,
        'review_authority_authenticated': False, 'access_enforcement_verified': False}
    context['context_sha256'] = digest(context)
    return context


def trials_case(with_result=True):
    context = portable_context()
    amount = {'id': 'paid_amount', 'question': 'What are paid shipping cents?', 'persona_id': 'analyst',
        'expected': {'decision': 'answer', 'allowed_fields': ['orders.paid_shipping_cents'],
            'required_fields': ['orders.paid_shipping_cents'], 'definition_ids': ['paid_shipping'],
            'clarification_ids': [], 'required_attributes': ['region']}}
    if with_result: amount['expected']['result'] = {'value': 350, 'unit': 'cents', 'complete_population': True}
    suite = {'schema_version': 1, 'kind': 'omni_ai_evaluation_suite', 'context_sha256': context['context_sha256'],
        'personas': {'analyst': {'allowed_fields': ['orders.paid_shipping_cents', 'orders.shipping_cents'],
                               'available_attributes': ['region']},
                     'limited': {'allowed_fields': ['orders.paid_shipping_cents'], 'available_attributes': []}},
        'cases': [amount,
            {'id': 'ask_timing', 'question': 'How are refunds dated?', 'persona_id': 'analyst',
             'expected': {'decision': 'clarify', 'allowed_fields': [], 'required_fields': [], 'definition_ids': [],
                          'clarification_ids': ['refund_timing'], 'required_attributes': []}},
            {'id': 'unavailable_scope', 'question': 'Show the region-specific amount.', 'persona_id': 'limited',
             'expected': {'decision': 'refuse', 'allowed_fields': [], 'required_fields': [], 'definition_ids': [],
                          'clarification_ids': [], 'required_attributes': ['region']}}], 'review': {}}
    review(suite)
    # Explicit observed values, not an answer populated by copying expected.result.
    answers = [
        {'case_id': 'paid_amount', 'persona_id': 'analyst', 'decision': 'answer',
         'fields': ['orders.paid_shipping_cents'], 'claims': [{'definition_id': 'paid_shipping',
         'statement_sha256': digest('Shipping cents for paid orders only.')}], 'clarification_ids': [], 'attributes_used': ['region']},
        {'case_id': 'ask_timing', 'persona_id': 'analyst', 'decision': 'clarify', 'fields': [], 'claims': [],
         'clarification_ids': ['refund_timing'], 'attributes_used': []},
        {'case_id': 'unavailable_scope', 'persona_id': 'limited', 'decision': 'refuse', 'fields': [], 'claims': [],
         'clarification_ids': [], 'attributes_used': []}]
    if with_result: answers[0]['result'] = {'value': 350, 'unit': 'cents', 'complete_population': True}
    for answer, case in zip(answers, suite['cases']):
        answer.update(question_sha256=digest(case['question']), context_sha256=context['context_sha256'])
    provider = {'name': 'offline-corpus-provider', 'model': 'synthetic-model', 'settings_sha256': '6' * 64}
    plan = {'schema_version': 1, 'kind': 'omni_ai_trial_plan', 'suite_sha256': digest(suite),
            'minimum_trials': 3, 'provider': provider}
    observations = {'schema_version': 1, 'kind': 'omni_ai_trials', 'plan_sha256': digest(plan), 'trials': [
        {'id': 'observation-' + str(i), 'provider': copy.deepcopy(provider),
         'delivered_context_sha256': context['context_sha256'],
         'observations': {'schema_version': 1, 'kind': 'omni_ai_observations', 'suite_sha256': digest(suite),
                          'answers': copy.deepcopy(answers)}} for i in range(3)]}
    return plan, suite, observations, context


@unittest.skipUnless(RUNTIME, 'Pinned semantic runtime needed for derived lineage')
class IndependentAILineageTests(unittest.TestCase):
    def modeled(self):
        files = case_files('modeled_query_view')
        files['customer_context.topic'] = 'base_view: orders_by_customer\njoins: {}\nfields: [all_views.*]\nai_fields: [orders_by_customer.paid_shipping_cents]\n'
        return context_case(files, 'orders_by_customer.paid_shipping_cents', {},
            [('orders', 'customer_id'), ('orders', 'shipping_cents'), ('orders', 'status')], 'customer_context')

    def assert_unauthed(self, result):
        for key in ('native_verified', 'review_authority_authenticated', 'access_enforcement_verified'):
            self.assertIs(result['context'][key], False)
        self.assertIs(result['report']['authorization_authenticated'], False)

    def test_modeled_view_keeps_independently_enumerated_group_filter_and_value_columns(self):
        spec, inputs = self.modeled(); before = copy.deepcopy((spec, inputs))
        result = ai.build_context(spec, **inputs)
        columns = {(c['view'], c['column']) for c in result['context']['fields'][0]['gold_columns']}
        self.assertEqual(columns, {('orders', 'customer_id'), ('orders', 'shipping_cents'), ('orders', 'status')})
        self.assertEqual(result['report']['status'], 'complete')
        self.assertEqual(before, (spec, inputs)); self.assert_unauthed(result)

    def test_unprojected_protected_filter_and_group_columns_withhold_modeled_definition(self):
        for column in ('status', 'customer_id'):
            spec, inputs = self.modeled(); protect(inputs, 'orders', column); refresh(spec, inputs)
            with self.subTest(column=column):
                result = ai.build_context(spec, **inputs)
                self.assertEqual(result['context']['approved_definitions'], [])
                self.assertEqual(result['context']['fields'], [])
                self.assertEqual(result['context']['withheld_definition_count'], 1)
                self.assertNotIn('Synthetic reviewed amount', result['markdown'])

    def test_omitting_any_population_operand_cannot_create_a_smaller_disclosure_surface(self):
        for column in ('status', 'customer_id'):
            spec, inputs = self.modeled()
            binding = spec['bindings']['orders_by_customer.paid_shipping_cents']
            binding['columns'] = [c for c in binding['columns'] if c['column'] != column]
            review(spec)
            with self.subTest(column=column), self.assertRaises(ai.ContextError):
                ai.build_context(spec, **inputs)

    def test_sql_join_where_and_unprojected_group_operands_are_not_lost(self):
        files = case_files('sql_query_view')
        files.pop('returns_by_order.query.view')
        files['paid_lines.query.view'] = '''sql: |
  SELECT SUM(l."quantity" * l."unit_price_cents") AS amount
  FROM ${orders} AS o
  JOIN ${order_lines} AS l ON o."order_id" = l."order_id"
  WHERE o."status" = 'paid'
  GROUP BY o."customer_id"
dimensions:
  amount: {}
'''
        columns = [('orders', 'order_id'), ('orders', 'status'), ('orders', 'customer_id'),
                   ('order_lines', 'order_id'), ('order_lines', 'quantity'), ('order_lines', 'unit_price_cents')]
        spec, inputs = context_case(files, 'paid_lines.amount', {}, columns)
        baseline = ai.build_context(spec, **inputs)
        self.assertEqual(baseline['report']['status'], 'complete')
        self.assertEqual({(c['view'], c['column']) for c in baseline['context']['fields'][0]['gold_columns']}, set(columns))
        for view, column in (('orders', 'order_id'), ('orders', 'status'), ('orders', 'customer_id')):
            changed = copy.deepcopy(inputs); protect(changed, view, column)
            candidate = copy.deepcopy(spec); refresh(candidate, changed)
            with self.subTest(protected=(view, column)):
                result = ai.build_context(candidate, **changed)
                self.assertEqual(result['context']['withheld_definition_count'], 1)
                self.assertEqual(result['context']['approved_definitions'], [])

    def test_inherited_alias_uses_effective_definition_and_physical_origin(self):
        files = case_files('modeled_query_view')
        files['customer_alias.view'] = 'extends: [orders_by_customer]\ndimensions:\n  paid_shipping_cents:\n    label: Alias amount\n'
        files['alias_context.topic'] = 'base_view: customer_alias\njoins: {}\nfields: [all_views.*]\nai_fields: [customer_alias.paid_shipping_cents]\n'
        spec, inputs = context_case(files, 'customer_alias.paid_shipping_cents', {'label': 'Alias amount'},
            [('orders', 'customer_id'), ('orders', 'shipping_cents'), ('orders', 'status')], 'alias_context')
        result = ai.build_context(spec, **inputs)
        self.assertEqual(result['report']['status'], 'complete')
        self.assertEqual({c['view'] for c in result['context']['fields'][0]['gold_columns']}, {'orders'})
        self.assertNotIn('customer_alias', inputs['model_context']['bindings'])

    def test_topic_local_override_uses_scoped_definition_and_rejects_old_field_hash(self):
        files = case_files('role_aliases')
        files['roles.topic'] += 'ai_fields: [buyers.label]\n'
        spec, inputs = context_case(files, 'buyers.label', {'sql': '"label"', 'label': 'Buyer label'},
                                    [('parties', 'label')], 'roles')
        result = ai.build_context(spec, **inputs)
        self.assertEqual(result['report']['status'], 'complete')
        self.assertEqual(result['context']['fields'][0]['gold_columns'][0]['view'], 'parties')
        inputs['model_files']['roles.topic'] = inputs['model_files']['roles.topic'].replace('label: Buyer label', 'label: Changed buyer label')
        refresh(spec, inputs)
        with self.assertRaises(ai.ContextError): ai.build_context(spec, **inputs)

    def test_bracket_timeframe_uses_base_physical_column_but_preserves_timeframe_identity(self):
        files = case_files('measure_local_filters_and_ratio')
        files['orders.topic'] = 'base_view: orders\njoins: {}\nfields: [all_views.*]\nai_fields: ["orders.placed_on[date]"]\n'
        definition = {'sql': '"placed_on"', 'timeframes': ['raw', 'date']}
        spec, inputs = context_case(files, 'orders.placed_on[date]', definition, [('orders', 'placed_on')], 'orders')
        result = ai.build_context(spec, **inputs)
        self.assertEqual(result['context']['fields'][0]['field'], 'orders.placed_on[date]')
        self.assertEqual(result['context']['fields'][0]['gold_columns'][0]['column'], 'placed_on')
        spec['bindings']['orders.placed_on[month]'] = spec['bindings'].pop('orders.placed_on[date]')
        spec['definitions'][0]['fields'] = ['orders.placed_on[month]']; review(spec)
        with self.assertRaises(ai.ContextError): ai.build_context(spec, **inputs)

    def test_repinning_context_or_topic_does_not_hide_stale_exact_bindings(self):
        for mutation in ('namespace', 'topic-selection', 'field-sql'):
            spec, inputs = self.modeled()
            if mutation == 'namespace':
                inputs['model_context']['bindings']['orders']['namespace']['schema'] = 'OTHER_SYNTHETIC'
                inputs['model_files']['orders.view'] = inputs['model_files']['orders.view'].replace('schema: SYNTHETIC', 'schema: OTHER_SYNTHETIC')
            elif mutation == 'topic-selection':
                inputs['model_files']['customer_context.topic'] = inputs['model_files']['customer_context.topic'].replace('orders_by_customer.paid_shipping_cents', 'orders_by_customer.shipping_cents')
            else:
                definition = omni.yaml.safe_load(inputs['model_files']['orders_by_customer.query.view'])
                definition['dimensions']['paid_shipping_cents']['sql'] = '"SHIPPING_CENTS"'
                inputs['model_files']['orders_by_customer.query.view'] = omni.yaml.safe_dump(definition)
            refresh(spec, inputs)
            with self.subTest(mutation=mutation), self.assertRaises(ai.ContextError):
                ai.build_context(spec, **inputs)

    def test_empty_or_unknown_lineage_cannot_become_approved_context(self):
        for sql in ('1', 'UNKNOWN_CORPUS_FUNCTION("shipping_cents")'):
            files = case_files('measure_local_filters_and_ratio')
            definition = omni.yaml.safe_load(files['orders.view'])
            definition['dimensions']['candidate_value'] = {'sql': sql}
            files['orders.view'] = omni.yaml.safe_dump(definition)
            spec, inputs = context_case(files, 'orders.candidate_value', {'sql': sql}, [])
            with self.subTest(sql=sql), self.assertRaises(ai.ContextError):
                ai.build_context(spec, **inputs)


class IndependentAITrialTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.suite, self.observations, self.context = trials_case()

    def evaluate(self):
        return ai.evaluate_trials(self.plan, self.suite, self.observations, self.context)

    def answer(self, trial=1):
        return self.observations['trials'][trial]['observations']['answers'][0]

    def assert_unauthed(self, report):
        for key in ('live_ai_authenticated', 'natural_language_answer_verified', 'access_enforcement_verified', 'business_accepted'):
            self.assertIs(report[key], False)

    def test_repeated_exact_results_report_comparison_counts_without_authentication(self):
        before = copy.deepcopy((self.plan, self.suite, self.observations, self.context))
        report = self.evaluate()
        self.assertEqual(report['status'], 'passed', report)
        self.assertEqual((report['trials_compared'], report['cases_compared']), (3, 9))
        self.assertEqual((report['results_expected'], report['results_compared']), (3, 3))
        self.assertEqual(before, (self.plan, self.suite, self.observations, self.context)); self.assert_unauthed(report)

    def test_correct_fields_and_definition_cannot_rescue_wrong_numeric_result(self):
        self.answer()['result']['value'] = 1050
        report = self.evaluate()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['failed_trials'], 1)
        self.assertEqual(report['trials_compared'], 3); self.assert_unauthed(report)

    def test_int_float_null_and_incomplete_population_are_not_coerced(self):
        original = copy.deepcopy(self.observations)
        for field, value in (('value', 350.0), ('value', None), ('value', '350'), ('complete_population', False)):
            self.observations = copy.deepcopy(original); self.answer()['result'][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.evaluate()['status'], 'failed')

    def test_expected_null_is_distinct_from_missing_or_zero(self):
        self.suite['cases'][0]['expected']['result']['value'] = None; review(self.suite)
        self.plan['suite_sha256'] = digest(self.suite)
        self.observations['plan_sha256'] = digest(self.plan)
        for trial in self.observations['trials']:
            trial['observations']['suite_sha256'] = digest(self.suite)
            trial['observations']['answers'][0]['result']['value'] = None
        self.assertEqual(self.evaluate()['status'], 'passed')
        self.answer()['result']['value'] = 0
        self.assertEqual(self.evaluate()['status'], 'failed')

    def test_missing_unexpected_and_nonanswer_results_fail(self):
        for mutation in ('missing', 'unexpected', 'refusal-payload'):
            self.plan, self.suite, self.observations, self.context = trials_case(with_result=mutation != 'unexpected')
            if mutation == 'missing': self.answer().pop('result')
            elif mutation == 'unexpected': self.answer()['result'] = {'value': 350}
            else: self.observations['trials'][1]['observations']['answers'][2]['result'] = {'value': 350}
            with self.subTest(mutation=mutation): self.assertEqual(self.evaluate()['status'], 'failed')

    def test_metadata_only_trials_have_zero_numeric_result_coverage(self):
        self.plan, self.suite, self.observations, self.context = trials_case(with_result=False)
        report = self.evaluate()
        self.assertEqual(report['status'], 'passed')
        self.assertEqual((report['results_expected'], report['results_compared']), (0, 0))
        self.assert_unauthed(report)

    def test_wrong_metric_and_omitted_case_cannot_be_hidden_in_repeated_trials(self):
        for mutation in ('wrong-metric', 'missing-case', 'duplicate-case'):
            self.plan, self.suite, self.observations, self.context = trials_case()
            answers = self.observations['trials'][1]['observations']['answers']
            if mutation == 'wrong-metric':
                answers[0]['fields'] = ['orders.shipping_cents']
                answers[0]['claims'] = [{'definition_id': 'all_shipping', 'statement_sha256': digest('Shipping cents across all order statuses.')}]
            elif mutation == 'missing-case': answers.pop()
            else: answers[2] = copy.deepcopy(answers[1])
            with self.subTest(mutation=mutation):
                report = self.evaluate(); self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['trials_compared'], 3)

    def test_missing_trial_duplicate_identity_provider_and_settings_drift_fail(self):
        for mutation in ('missing-trial', 'duplicate-id', 'provider', 'model', 'settings'):
            self.plan, self.suite, self.observations, self.context = trials_case()
            trial = self.observations['trials'][1]
            if mutation == 'missing-trial': self.observations['trials'].pop()
            elif mutation == 'duplicate-id': trial['id'] = self.observations['trials'][0]['id']
            elif mutation == 'provider': trial['provider']['name'] = 'another-declared-provider'
            elif mutation == 'model': trial['provider']['model'] = 'another-model'
            else: trial['provider']['settings_sha256'] = 'f' * 64
            with self.subTest(mutation=mutation): self.assertEqual(self.evaluate()['status'], 'failed')

    def test_context_truncation_and_hash_replacement_cannot_reuse_old_suite(self):
        self.context['approved_definitions'].pop()
        self.context['fields'].pop()
        self.context['context_sha256'] = digest({key: value for key, value in self.context.items() if key != 'context_sha256'})
        self.assertEqual(self.evaluate()['status'], 'failed')
        self.plan, self.suite, self.observations, self.context = trials_case()
        self.observations['trials'][1]['delivered_context_sha256'] = '0' * 64
        self.assertEqual(self.evaluate()['status'], 'failed')

    def test_sensitive_nested_result_and_malformed_identity_never_echo_raw_values(self):
        marker = 'SYNTHETIC_PHI_CANARY'
        for mutation in ('result', 'identity', 'provider'):
            self.plan, self.suite, self.observations, self.context = trials_case()
            if mutation == 'result': self.answer()['result'] = {'payload': [{'value': marker}]}
            elif mutation == 'identity': self.observations['trials'][1]['id'] = [marker]
            else: self.observations['trials'][1]['provider']['settings_sha256'] = marker
            with self.subTest(mutation=mutation):
                report = self.evaluate()
                self.assertEqual(report['status'], 'failed')
                self.assertNotIn(marker, json.dumps(report)); self.assert_unauthed(report)


if __name__ == '__main__':
    unittest.main()
