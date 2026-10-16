"""Scorer/corpus checks, not LLM accuracy or native-platform qualification.

The hand-authored answer key is separate from public scenario evidence. A blind
worker receives public_case(case), its selected specialist profile, and the
response contract below. Never send the fixture's ``expected`` field to it.

Worker response: {case_id, disposition, facts: [candidate IDs], claims:
[candidate IDs], rationale: str, context_requests: [str]}. Candidate IDs have
neutral labels; their descriptions are propositions to evaluate, not facts
asserted true by their inclusion in the choices map. Required propositions must
appear in facts. Claims are optional additional assertions using the same map;
forbidden choices fail in either list. An ID may appear once in each list.

The scorer evaluates the declared decision and proposition selections. It only
checks prose structurally: it cannot detect a contradictory rationale, verify
the quality of a context request, or prove that a worker reasoned correctly.
Positive answers here are constructed from the key to test the scorer, not from
an LLM. No adapter output, vendor execution, or profile keyword checks are used.
"""
import copy
import json
from pathlib import Path
import re
import unittest


CORPUS_PATH = Path(__file__).parent / 'fixtures' / 'specialist_interpretation_cases.json'
SOURCES = frozenset({
    'bigquery', 'periscope', 'looker', 'tableau', 'powerbi', 'hex', 'domo',
    'sigma', 'webfocus', 'snowflake', 'redshift', 'clickhouse', 'motherduck',
    'databricks', 'dbt', 'coalesce', 'fabric',
})
DISPOSITIONS = frozenset({
    'reuse_existing', 'move_upstream', 'retain_semantic', 'retain_presentation',
    'split', 'consolidate_candidate', 'retire_candidate', 'unresolved',
})
PUBLIC_FIELDS = ('id', 'source', 'evidence', 'question', 'facts')
ANSWER_FIELDS = frozenset({
    'case_id', 'disposition', 'facts', 'claims', 'rationale', 'context_requests',
})


def public_case(case):
    """Return only blind-worker inputs; do not share nested mutable references."""
    return {key: copy.deepcopy(case[key]) for key in PUBLIC_FIELDS}


def score_answer(case, answer):
    """Pure comparison against one trusted, corpus-validated answer key.

    Return a diagnostic result instead of raising for a malformed worker answer.
    No partial credit changes passed: disposition, required facts, exclusions,
    and response structure must all pass. Prose is never keyword-scored.
    """
    required = set(case['expected']['required_facts'])
    forbidden = set(case['expected']['forbidden_claims'])
    known = set(case['facts'])
    errors = []
    selected = {'facts': set(), 'claims': set()}

    if not isinstance(answer, dict):
        return {'passed': False, 'errors': ['answer_not_object'],
                'matched_required_facts': 0, 'required_fact_count': len(required)}

    missing = ANSWER_FIELDS - set(answer)
    unexpected = set(answer) - ANSWER_FIELDS
    if missing:
        errors.append('missing_fields:' + ','.join(sorted(missing)))
    if unexpected:
        errors.append('unexpected_fields')
    if answer.get('case_id') != case['id']:
        errors.append('case_id_mismatch')
    disposition = answer.get('disposition')
    if not isinstance(disposition, str) or disposition not in DISPOSITIONS:
        errors.append('invalid_disposition')
    elif disposition != case['expected']['disposition']:
        errors.append('disposition_mismatch')

    for field in ('facts', 'claims'):
        values = answer.get(field)
        if not isinstance(values, list):
            errors.append(field + '_not_array')
            continue
        for value in values:
            if not isinstance(value, str) or not value.strip():
                errors.append('malformed_id:' + field)
                continue
            if value in selected[field]:
                errors.append('duplicate_id:' + field + ':' + value)
            selected[field].add(value)
            if value not in known:
                errors.append('unknown_id:' + field + ':' + value)

    for value in sorted(required - selected['facts']):
        errors.append('missing_required_fact:' + value)
    for value in sorted(forbidden & (selected['facts'] | selected['claims'])):
        errors.append('forbidden_claim:' + value)

    rationale = answer.get('rationale')
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append('rationale_required')
    requests = answer.get('context_requests')
    if not isinstance(requests, list) or any(
            not isinstance(request, str) or not request.strip() for request in requests):
        errors.append('invalid_context_requests')
    elif disposition == 'unresolved' and not requests:
        errors.append('unresolved_requires_context_request')

    return {'passed': not errors, 'errors': errors,
            'matched_required_facts': len(required & selected['facts']),
            'required_fact_count': len(required)}


def _load():
    with CORPUS_PATH.open(encoding='utf-8') as stream:
        return json.load(stream)


def _positive(case):
    """A synthetic scorer control, never a model-generated interpretation."""
    return {
        'case_id': case['id'], 'disposition': case['expected']['disposition'],
        'facts': list(case['expected']['required_facts']), 'claims': [],
        'rationale': 'Synthetic control selecting the independently authored expected propositions.',
        'context_requests': ['Supply the missing source bindings and qualification evidence.']
        if case['expected']['disposition'] == 'unresolved' else [],
    }


class InterpretationCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = _load()

    def test_schema_coverage_unique_case_and_fact_ids_and_size(self):
        self.assertEqual(set(self.corpus), {'schema_version', 'cases'})
        self.assertIs(type(self.corpus['schema_version']), int)
        self.assertEqual(self.corpus['schema_version'], 1)
        self.assertIsInstance(self.corpus['cases'], list)
        self.assertEqual(len(self.corpus['cases']), 17)
        self.assertLessEqual(CORPUS_PATH.stat().st_size, 40000)
        sources = [case['source'] for case in self.corpus['cases']]
        self.assertEqual(set(sources), SOURCES)
        self.assertEqual(len(sources), len(set(sources)))
        seen_cases, seen_facts = set(), set()
        for case in self.corpus['cases']:
            with self.subTest(case=case['id']):
                self.assertEqual(set(case), set(PUBLIC_FIELDS) | {'expected'})
                self.assertRegex(case['id'], r'^' + re.escape(case['source']) + r'-[a-z0-9-]+$')
                self.assertNotIn(case['id'], seen_cases)
                seen_cases.add(case['id'])
                for key in ('evidence', 'question'):
                    self.assertIsInstance(case[key], str)
                    self.assertTrue(case[key].strip())
                self.assertIsInstance(case['facts'], dict)
                self.assertGreaterEqual(len(case['facts']), 7)
                for identity, description in case['facts'].items():
                    self.assertRegex(identity, r'^' + re.escape(case['source']) + r'\.[0-9]{2}$')
                    self.assertNotIn(identity, seen_facts)
                    seen_facts.add(identity)
                    self.assertIsInstance(description, str)
                    self.assertTrue(description.strip())

    def test_every_candidate_has_an_explicit_independent_judgment(self):
        for case in self.corpus['cases']:
            with self.subTest(case=case['id']):
                key = case['expected']
                self.assertEqual(set(key), {'disposition', 'required_facts', 'forbidden_claims'})
                self.assertIn(key['disposition'], DISPOSITIONS)
                for field in ('required_facts', 'forbidden_claims'):
                    self.assertIsInstance(key[field], list)
                    self.assertTrue(all(isinstance(value, str) for value in key[field]))
                    self.assertEqual(len(key[field]), len(set(key[field])))
                required, forbidden = set(key['required_facts']), set(key['forbidden_claims'])
                self.assertGreaterEqual(len(required), 4)
                self.assertGreaterEqual(len(forbidden), 2)
                self.assertFalse(required & forbidden)
                self.assertEqual(required | forbidden, set(case['facts']))

    def test_blind_projection_excludes_key_and_does_not_alias_fixture(self):
        for case in self.corpus['cases']:
            visible = public_case(case)
            self.assertEqual(set(visible), set(PUBLIC_FIELDS))
            self.assertNotIn('expected', visible)
            before = copy.deepcopy(case)
            visible['facts'].clear()
            self.assertEqual(case, before)


class InterpretationScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = _load()['cases']
        cls.by_source = {case['source']: case for case in cls.cases}

    def assert_rejected(self, case, answer, error=None):
        result = score_answer(case, answer)
        self.assertFalse(result['passed'], result)
        self.assertTrue(result['errors'])
        if error is not None:
            self.assertIn(error, result['errors'])
        return result

    def test_all_hand_authored_positive_controls_pass(self):
        for case in self.cases:
            with self.subTest(case=case['id']):
                result = score_answer(case, _positive(case))
                self.assertTrue(result['passed'], result)
                self.assertEqual(result['errors'], [])
                self.assertEqual(result['matched_required_facts'], result['required_fact_count'])

    def test_wrong_disposition_fails_despite_complete_evidence(self):
        for case in self.cases:
            answer = _positive(case)
            answer['disposition'] = next(value for value in sorted(DISPOSITIONS)
                                         if value != case['expected']['disposition'])
            with self.subTest(case=case['id']):
                self.assert_rejected(case, answer, 'disposition_mismatch')

    def test_each_required_fact_is_necessary(self):
        for case in self.cases:
            for identity in case['expected']['required_facts']:
                answer = _positive(case)
                answer['facts'].remove(identity)
                with self.subTest(case=case['id'], missing=identity):
                    result = self.assert_rejected(case, answer, 'missing_required_fact:' + identity)
                    self.assertEqual(result['matched_required_facts'], result['required_fact_count'] - 1)

    def test_dropped_filter_security_and_dependency_negative_controls(self):
        # These IDs select explicit semantic obligations, not matching prose.
        for category, source, identity in (
                ('filter_order', 'bigquery', 'bigquery.06'),
                ('control_order', 'sigma', 'sigma.03'),
                ('security', 'powerbi', 'powerbi.04'),
                ('dependency', 'coalesce', 'coalesce.04')):
            case = self.by_source[source]
            answer = _positive(case)
            answer['facts'].remove(identity)
            with self.subTest(category=category):
                self.assert_rejected(case, answer, 'missing_required_fact:' + identity)

    def test_invented_grain_and_security_equivalence_fail(self):
        for source, identity in (('bigquery', 'bigquery.08'), ('webfocus', 'webfocus.05'),
                                 ('dbt', 'dbt.08'), ('powerbi', 'powerbi.08')):
            case = self.by_source[source]
            answer = _positive(case)
            answer['claims'] = [identity]
            with self.subTest(source=source):
                self.assert_rejected(case, answer, 'forbidden_claim:' + identity)

    def test_every_forbidden_proposition_fails_in_either_output_list(self):
        for case in self.cases:
            for identity in case['expected']['forbidden_claims']:
                for field in ('facts', 'claims'):
                    answer = _positive(case)
                    answer[field].append(identity)
                    with self.subTest(case=case['id'], field=field, identity=identity):
                        self.assert_rejected(case, answer, 'forbidden_claim:' + identity)

    def test_listing_every_choice_cannot_pass(self):
        for case in self.cases:
            answer = _positive(case)
            answer['facts'] = list(case['facts'])
            with self.subTest(case=case['id']):
                self.assert_rejected(case, answer)

    def test_claims_do_not_replace_required_evidence_selections(self):
        case = self.cases[0]
        answer = _positive(case)
        moved = answer['facts'].pop()
        answer['claims'].append(moved)
        self.assert_rejected(case, answer, 'missing_required_fact:' + moved)

    def test_duplicate_and_unknown_ids_are_rejected(self):
        case = self.cases[0]
        for field in ('facts', 'claims'):
            for mode in ('duplicate', 'unknown'):
                answer = _positive(case)
                identity = answer['facts'][0]
                answer[field] = [identity, identity] if mode == 'duplicate' else ['unrecognized.99']
                with self.subTest(field=field, mode=mode):
                    expected = ('duplicate_id:' + field + ':' + identity if mode == 'duplicate'
                                else 'unknown_id:' + field + ':unrecognized.99')
                    self.assert_rejected(case, answer, expected)

    def test_malformed_id_and_collection_types_fail_without_exception(self):
        case = self.cases[0]
        for field in ('facts', 'claims'):
            for value in (None, True, 1, {}, [], '', ' '):
                answer = _positive(case)
                answer[field].append(value)
                with self.subTest(field=field, value=value):
                    self.assert_rejected(case, answer, 'malformed_id:' + field)
            for value in (None, True, 1, {}, 'bigquery.01', ('bigquery.01',)):
                answer = _positive(case)
                answer[field] = value
                with self.subTest(field=field, collection=value):
                    self.assert_rejected(case, answer, field + '_not_array')

    def test_answer_schema_case_identity_and_prose_shapes(self):
        case = self.cases[0]
        for value in (None, [], 'answer', 1, True):
            self.assert_rejected(case, value, 'answer_not_object')
        for field in ANSWER_FIELDS:
            answer = _positive(case)
            del answer[field]
            self.assert_rejected(case, answer)
        for field, value, error in (
                ('case_id', 'another-case', 'case_id_mismatch'),
                ('disposition', [], 'invalid_disposition'),
                ('disposition', 'approved', 'invalid_disposition'),
                ('rationale', '', 'rationale_required'),
                ('rationale', ['explanation'], 'rationale_required'),
                ('context_requests', 'question', 'invalid_context_requests'),
                ('context_requests', [None], 'invalid_context_requests'),
                ('context_requests', [' '], 'invalid_context_requests')):
            answer = _positive(case)
            answer[field] = value
            with self.subTest(field=field, value=value):
                self.assert_rejected(case, answer, error)
        answer = _positive(case)
        answer['expected'] = copy.deepcopy(case['expected'])
        self.assert_rejected(case, answer, 'unexpected_fields')

    def test_unresolved_requires_context_request(self):
        for case in self.cases:
            if case['expected']['disposition'] == 'unresolved':
                answer = _positive(case)
                answer['context_requests'] = []
                self.assert_rejected(case, answer, 'unresolved_requires_context_request')

    def test_scoring_is_pure_and_fact_order_is_irrelevant(self):
        for case in self.cases:
            answer = _positive(case)
            answer['facts'].reverse()
            answer['claims'] = [answer['facts'][0]]
            before = copy.deepcopy((case, answer))
            first = score_answer(case, answer)
            self.assertEqual(first, score_answer(case, answer))
            self.assertTrue(first['passed'], first)
            self.assertEqual((case, answer), before)


if __name__ == '__main__':
    unittest.main()
