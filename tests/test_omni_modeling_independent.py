"""Candidate-driven, fixture-bounded modeling checks; never native compilation.

The test compiler consumes candidate files only. Expected CSV/JSON is opened
after compilation/execution for comparison. It is deliberately not a general
Omni compiler and refuses expressions outside this small synthetic corpus.
"""
import copy
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / 'tests/fixtures/omni_modeler'
sys.path.insert(0, str(REPO / 'skills/data-model-accelerator/scripts'))
import omni_contract as contract
import generate_omni_model as generator

YAML_AVAILABLE = contract.yaml is not None
SEMANTIC_RUNTIME = YAML_AVAILABLE and contract.sqlglot is not None


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def case_files(case_id):
    cases = json.loads((CORPUS / 'cases.json').read_text())['cases']
    selected = next(case for case in cases if case['id'] == case_id)
    return {name: (CORPUS / path).read_text() for name, path in selected['files'].items()}


def expected_rows(filename):
    with (CORPUS / 'expected' / filename).open() as stream:
        return [{key: int(value) if value.isdigit() else value for key, value in row.items()}
                for row in csv.DictReader(stream)]


def fixture_database():
    """Only input CSVs, never expected results, supply execution data."""
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    for name in ('orders', 'order_lines', 'returns', 'parties', 'customer_history'):
        with (CORPUS / 'data' / (name + '.csv')).open() as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            numeric = {field for field in fields if field.endswith('_cents') or field == 'quantity'}
            db.execute('CREATE TABLE "' + name.upper() + '" (' + ','.join(
                '"' + field + '" ' + ('INTEGER' if field in numeric else 'TEXT') for field in fields) + ')')
            db.executemany('INSERT INTO "' + name.upper() + '" VALUES (' + ','.join('?' for _ in fields) + ')',
                [[None if row[field] == '' else int(row[field]) if field in numeric else row[field]
                  for field in fields] for row in reader])
    return db


class FixtureCompileError(ValueError):
    pass


class FixtureCompiler:
    """Independent translation of this fixture's explicit candidate subset.

    No filesystem/expected-result input. No native optimization, access-policy,
    join planning, dialect qualification, fanout protection or deployment claim.
    """
    REF = re.compile(r'\$\{([^{}]+)\}')
    IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]*\Z')

    def __init__(self, files):
        if contract.yaml is None:
            raise FixtureCompileError('test YAML runtime unavailable')
        self.views = {}
        for path, content in files.items():
            suffix = '.query.view' if path.endswith('.query.view') else '.view' if path.endswith('.view') else None
            if suffix is None:
                continue
            name = path[:-len(suffix)]
            if not self.IDENTIFIER.fullmatch(name) or name in self.views:
                raise FixtureCompileError('ambiguous view identity')
            definition = contract.yaml.safe_load(content)
            if type(definition) is not dict:
                raise FixtureCompileError('view mapping required')
            self.views[name] = definition

    @staticmethod
    def literal(value):
        if value is None: return 'NULL'
        if type(value) is bool: return '1' if value else '0'
        if type(value) in (int, float): return str(value)
        if type(value) is str: return "'" + value.replace("'", "''") + "'"
        raise FixtureCompileError('unsupported filter literal')

    def field(self, view, name, trail=()):
        key = (view, name)
        if key in trail or view not in self.views:
            raise FixtureCompileError('field cycle or missing view')
        definition = self.views[view]
        trail = trail + (key,)
        dimensions = definition.get('dimensions', {})
        measures = definition.get('measures', {})
        if name in dimensions:
            item = dimensions[name]
            sql = item.get('sql')
            if sql is None and ('query' in definition or 'sql' in definition):
                return '"' + name + '"', False
            if type(sql) is not str:
                raise FixtureCompileError('dimension SQL required')
            return self.expand_field_sql(sql, view, trail), False
        if name not in measures:
            raise FixtureCompileError('missing source field')
        item = measures[name]
        aggregate = item.get('aggregate_type')
        filters = item.get('filters', {})
        condition = self.filter_sql(filters, view, trail)
        if aggregate == 'count':
            return ('SUM(CASE WHEN ' + condition + ' THEN 1 ELSE 0 END)' if condition else 'COUNT(*)'), True
        if aggregate == 'sum':
            value = self.expand_field_sql(item['sql'], view, trail)
            return ('SUM(CASE WHEN ' + condition + ' THEN ' + value + ' ELSE 0 END)' if condition else 'SUM(' + value + ')'), True
        if aggregate is not None or filters:
            raise FixtureCompileError('aggregate outside fixture subset')
        sql = item.get('sql', '')
        ratio = re.fullmatch(r'\s*\$\{([^{}]+)\}\s*/\s*NULLIF\(\s*\$\{([^{}]+)\}\s*,\s*0\s*\)\s*', sql)
        if ratio:
            # SQLite integer division differs from this decimal warehouse
            # expression; promotion is explicit in this bounded test adapter.
            left = self.reference(ratio.group(1), view, trail)[0]
            right = self.reference(ratio.group(2), view, trail)[0]
            return '(1.0 * (' + left + ') / NULLIF((' + right + '), 0))', True
        raise FixtureCompileError('custom expression outside fixture subset')

    def reference(self, ref, current, trail=()):
        view, name = ref.split('.', 1) if '.' in ref else (current, ref)
        if view != current:
            raise FixtureCompileError('joined-field execution outside fixture subset')
        return self.field(view, name, trail)

    def expand_field_sql(self, sql, current, trail):
        if type(sql) is not str or '{{' in sql or ';' in sql:
            raise FixtureCompileError('unsupported field SQL')
        return self.REF.sub(lambda match: '(' + self.reference(match.group(1), current, trail)[0] + ')', sql)

    def filter_sql(self, filters, view, trail=()):
        if type(filters) is not dict:
            raise FixtureCompileError('operator-object filters required')
        result = []
        for ref, condition in filters.items():
            sql, is_measure = self.reference(ref, view, trail)
            if is_measure or type(condition) is not dict or len(condition) != 1:
                raise FixtureCompileError('dimension filter operator required')
            operator, value = next(iter(condition.items()))
            if operator == 'is':
                result.append(sql + (' IS NULL' if value is None else ' = ' + self.literal(value)))
            elif operator == 'not':
                result.append(sql + (' IS NOT NULL' if value is None else ' <> ' + self.literal(value)))
            else:
                raise FixtureCompileError('filter operator outside fixture subset')
        return ' AND '.join('(' + part + ')' for part in result)

    def compile_view(self, view, trail=()):
        if view in trail or view not in self.views:
            raise FixtureCompileError('view cycle or missing dependency')
        trail = trail + (view,)
        definition = self.views[view]
        if 'query' in definition and 'sql' in definition:
            raise FixtureCompileError('multiple query sources')
        if 'sql' in definition:
            sql = definition['sql']
            if type(sql) is not str or not re.match(r'\s*(SELECT|WITH)\b', sql, re.I) or ';' in sql:
                raise FixtureCompileError('single SELECT required')
            return self.REF.sub(lambda match: '(' + self.compile_view(match.group(1), trail) + ')', sql)
        if 'query' not in definition:
            table = definition.get('table_name')
            if type(table) is not str or not self.IDENTIFIER.fullmatch(table):
                raise FixtureCompileError('physical source required')
            return 'SELECT * FROM "' + table + '"'
        query = definition['query']
        if type(query) is not dict or set(query) - {'base_view', 'topic', 'fields', 'filters', 'sorts', 'limit'}:
            raise FixtureCompileError('query shape outside fixture subset')
        base = query.get('base_view'); mapping = query.get('fields')
        if type(mapping) is not dict or not mapping:
            raise FixtureCompileError('query field mapping required')
        aliases = list(mapping.values())
        if any(type(alias) is not str or not self.IDENTIFIER.fullmatch(alias) for alias in aliases) or len(set(aliases)) != len(aliases):
            raise FixtureCompileError('invalid or duplicate output alias')
        for name, field in definition.get('dimensions', {}).items():
            if not field.get('sql') and name not in aliases:
                raise FixtureCompileError('declared output missing from query')
        selects, groups, has_measure = [], [], False
        for ref, alias in mapping.items():
            if type(ref) is not str or '.' not in ref:
                raise FixtureCompileError('qualified query field required')
            source, field = ref.split('.', 1)
            if source != base:
                raise FixtureCompileError('joined query outside fixture subset')
            sql, measure = self.field(source, field)
            selects.append(sql + ' AS "' + alias + '"')
            if not measure: groups.append(sql)
            has_measure |= measure
        result = 'SELECT ' + ', '.join(selects) + ' FROM (' + self.compile_view(base, trail) + ')'
        where = self.filter_sql(query.get('filters', {}), base)
        if where: result += ' WHERE ' + where
        if groups and has_measure: result += ' GROUP BY ' + ', '.join(groups)
        sorts = query.get('sorts', [])
        if type(sorts) is not list:
            raise FixtureCompileError('explicit sort list required')
        ordered = []
        for sort in sorts:
            if type(sort) is not dict or set(sort) != {'field', 'desc'} or type(sort['desc']) is not bool or sort['field'] not in mapping:
                raise FixtureCompileError('supported output sort required')
            ordered.append('"' + mapping[sort['field']] + '"' + (' DESC' if sort['desc'] else ' ASC'))
        if ordered: result += ' ORDER BY ' + ', '.join(ordered)
        if 'limit' in query:
            if type(query['limit']) is not int or not 1 <= query['limit'] <= 1000 or not sorts:
                raise FixtureCompileError('bounded positive limit required')
            result += ' LIMIT ' + str(query['limit'])
        return result


def execute_candidate(files, view, db):
    sql = FixtureCompiler(files).compile_view(view)
    return [dict(row) for row in db.execute(sql)], sql


def bind_synthetic_review(spec):
    """Hash consistency only; fixture review is not human/deployment authority."""
    spec['review'] = {'status': 'approved', 'reference': 'independent-synthetic-only',
                      'evidence_sha256': '5' * 64,
                      'spec_sha256': canonical_hash({key: value for key, value in spec.items() if key != 'review'})}


def physical_orders_spec():
    files = case_files('measure_local_filters_and_ratio')
    definition = contract.yaml.safe_load(files['orders.view'])
    for key in ('catalog', 'schema', 'table_name'): definition.pop(key)
    context = json.loads((CORPUS / 'context.json').read_text())
    model = {'kind': 'independent_synthetic_model', 'columns': {
        name: {'unit': 'source-column'} for name in context['bindings']['orders']['columns']}}
    placement = {'kind': 'independent_synthetic_placement', 'measures': {
        name: {'layer': 'semantic', 'definition': copy.deepcopy(value)} for name, value in definition['measures'].items()}}
    mappings = {}
    for name, field in definition['dimensions'].items():
        column = field['sql'].strip('"')
        mappings[name] = {'kind': 'physical', 'column': column, 'source_refs': ['model#/columns/' + column]}
    for name, field in definition['measures'].items():
        mappings[name] = {'kind': 'aggregate' if 'aggregate_type' in field else 'derived',
                          'source_refs': ['placement#/measures/' + name]}
    spec = {'schema_version': 1, 'kind': 'omni_generation_spec', 'contract_version': contract.CONTRACT_VERSION,
            'review': {}, 'pins': {'model_sha256': canonical_hash(model), 'placement_sha256': canonical_hash(placement),
                                    'context_sha256': canonical_hash(context), 'catalogue_sha256': context['catalogue_sha256']},
            'model': {}, 'views': {'orders': {'kind': 'physical', 'definition': definition, 'field_mappings': mappings}},
            'topics': {'orders': contract.yaml.safe_load(files['orders.topic'])}, 'relationships': []}
    bind_synthetic_review(spec)
    return spec, context, model, placement


def repin(args):
    spec, context, model, placement = args
    spec['pins'] = {'model_sha256': canonical_hash(model), 'placement_sha256': canonical_hash(placement),
                    'context_sha256': canonical_hash(context), 'catalogue_sha256': context['catalogue_sha256']}
    bind_synthetic_review(spec)


def derived_view_spec(form):
    """Build reviewed synthetic input mappings, never expected-result baselines."""
    args = physical_orders_spec()
    spec, context, model, placement = args
    model['source_views'] = {}; placement['source_views'] = {}
    if form == 'sql':
        for view in ('order_lines', 'returns'):
            original = contract.yaml.safe_load((CORPUS / 'source/physical' / (view + '.view')).read_text())
            model['source_views'][view] = copy.deepcopy(original)
            placement['source_views'][view] = {'measures': copy.deepcopy(original.get('measures', {}))}
            definition = copy.deepcopy(original)
            for key in ('catalog', 'schema', 'table_name'): definition.pop(key)
            mappings = {}
            for field, value in definition['dimensions'].items():
                direct = re.fullmatch(r'"([^"]+)"', value['sql'])
                mappings[field] = {'kind': 'physical' if direct else 'derived',
                                   'source_refs': ['model#/source_views/' + view + '/dimensions/' + field]}
                if direct: mappings[field]['column'] = direct.group(1)
            for field, value in definition.get('measures', {}).items():
                mappings[field] = {'kind': 'aggregate' if 'aggregate_type' in value else 'derived',
                                   'source_refs': ['placement#/source_views/' + view + '/measures/' + field]}
            spec['views'][view] = {'kind': 'physical', 'definition': definition, 'field_mappings': mappings}
        spec['relationships'] = contract.yaml.safe_load((CORPUS / 'source/physical/relationships').read_text())
    name = 'orders_by_customer' if form == 'modeled' else 'returns_by_order'
    definition = contract.yaml.safe_load((CORPUS / 'source/query' / (name + '.query.view')).read_text())
    model['query_views'] = {name: {'definition': copy.deepcopy(definition),
                                   'outputs': {field: {'declared_output': field} for field in definition['dimensions']}}}
    mappings = {field: {'kind': 'query_output', 'output': field,
                        'source_refs': ['model#/query_views/' + name + '/outputs/' + field]}
                for field in definition['dimensions']}
    spec['views'][name] = {'kind': 'query_view' if form == 'modeled' else 'sql_view',
                           'definition': definition, 'field_mappings': mappings}
    repin(args)
    return args, name


class ModelingBoundaryTests(unittest.TestCase):
    def test_frozen_corpus_integrity(self):
        manifest = json.loads((CORPUS / 'FROZEN_SHA256.json').read_text())
        for path, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((CORPUS / path).read_bytes()).hexdigest(), expected, path)

    def test_missing_runtime_never_qualifies_candidate(self):
        files = case_files('measure_local_filters_and_ratio')
        context = json.loads((CORPUS / 'context.json').read_text())
        with patch.object(contract, 'yaml', None):
            report = contract.check_model(files, context)
        self.assertEqual(report['status'], 'unsupported')
        self.assertFalse(report['native_verified'])
        self.assertFalse(report['security_verified'])
        self.assertIn('runtime.yaml_unavailable', {f['code'] for f in report['findings']})


@unittest.skipUnless(YAML_AVAILABLE, 'Optional YAML needed for candidate-driven fixture compilation')
class CandidateDrivenQueryTests(unittest.TestCase):
    def setUp(self):
        self.db = fixture_database(); self.addCleanup(self.db.close)

    def test_modeled_query_candidate_executes_to_frozen_rows_without_oracle_read_in_compiler(self):
        files = case_files('modeled_query_view')
        with patch.object(Path, 'read_text', side_effect=AssertionError('compiler cannot read expected artifacts')):
            actual, sql = execute_candidate(files, 'orders_by_customer', self.db)
        self.assertIn('CASE WHEN', sql)
        self.assertEqual(sorted(actual, key=lambda row: row['customer_id']), expected_rows('query_orders_by_customer.csv'))

    def test_sql_query_candidate_executes_to_frozen_rows(self):
        actual, sql = execute_candidate(case_files('sql_query_view'), 'returns_by_order', self.db)
        self.assertNotIn('${', sql)
        self.assertEqual(sorted(actual, key=lambda row: row['order_id']), expected_rows('query_returns_by_order.csv'))

    def test_mutating_measure_filter_changes_compiled_result(self):
        files = case_files('modeled_query_view')
        files['orders.view'] = files['orders.view'].replace('is: paid', 'is: pending')
        actual, sql = execute_candidate(files, 'orders_by_customer', self.db)
        self.assertNotEqual(actual, expected_rows('query_orders_by_customer.csv'))
        self.assertEqual(sum(row['paid_shipping_cents'] for row in actual), 300)
        self.assertEqual(sum(row['shipping_cents'] for row in actual), 1050)
        self.assertIn("'pending'", sql)

    def test_query_filter_changes_population_while_measure_filter_stays_local(self):
        files = case_files('modeled_query_view')
        definition = contract.yaml.safe_load(files['orders_by_customer.query.view'])
        definition['query']['filters'] = {'orders.status': {'is': 'paid'}}
        files['orders_by_customer.query.view'] = contract.yaml.safe_dump(definition)
        actual, sql = execute_candidate(files, 'orders_by_customer', self.db)
        self.assertIn(' WHERE ', sql)
        self.assertEqual(sum(row['order_count'] for row in actual), 4)
        self.assertEqual(sum(row['shipping_cents'] for row in actual), 350)
        self.assertNotEqual(actual, expected_rows('query_orders_by_customer.csv'))

    def test_query_limit_really_truncates_result_and_does_not_pass_full_population(self):
        files = case_files('modeled_query_view')
        definition = contract.yaml.safe_load(files['orders_by_customer.query.view'])
        definition['query']['limit'] = 1
        definition['query']['sorts'] = [{'field': 'orders.shipping_cents', 'desc': True},
                                         {'field': 'orders.customer_id', 'desc': False}]
        files['orders_by_customer.query.view'] = contract.yaml.safe_dump(definition)
        actual, sql = execute_candidate(files, 'orders_by_customer', self.db)
        self.assertTrue(sql.endswith(' LIMIT 1'))
        self.assertEqual(len(actual), 1)
        self.assertNotEqual(actual, expected_rows('query_orders_by_customer.csv'))
        self.assertLess(sum(row['shipping_cents'] for row in actual), 1050)
        frozen = json.loads((CORPUS / 'expected/variants.json').read_text())['top_one_customer_shipping']
        self.assertEqual(actual, frozen['expected_rows'])
        definition['query']['sorts'][0]['desc'] = False
        files['orders_by_customer.query.view'] = contract.yaml.safe_dump(definition)
        changed, _ = execute_candidate(files, 'orders_by_customer', self.db)
        self.assertNotEqual(changed, actual)
        definition['query'].pop('sorts')
        files['orders_by_customer.query.view'] = contract.yaml.safe_dump(definition)
        with self.assertRaises(FixtureCompileError):
            execute_candidate(files, 'orders_by_customer', self.db)

    def test_missing_query_output_and_missing_field_fail_compilation(self):
        for mutation in ('missing-output', 'missing-field', 'duplicate-output'):
            files = case_files('modeled_query_view')
            body = files['orders_by_customer.query.view']
            if mutation == 'missing-output': body = body.replace('    orders.paid_shipping_cents: paid_shipping_cents\n', '')
            elif mutation == 'missing-field': body = body.replace('orders.paid_shipping_cents:', 'orders.missing:')
            else: body = body.replace('orders.paid_shipping_cents: paid_shipping_cents', 'orders.paid_shipping_cents: shipping_cents')
            files['orders_by_customer.query.view'] = body
            with self.subTest(mutation=mutation), self.assertRaises(FixtureCompileError):
                execute_candidate(files, 'orders_by_customer', self.db)

    def test_sql_mutation_changes_candidate_result_and_broken_dependency_fails(self):
        files = case_files('sql_query_view')
        files['returns_by_order.query.view'] = files['returns_by_order.query.view'].replace('SUM(r."refund_cents")', 'SUM(r."quantity")')
        actual, sql = execute_candidate(files, 'returns_by_order', self.db)
        self.assertNotEqual(actual, expected_rows('query_returns_by_order.csv'))
        self.assertEqual(sum(row['refund_cents'] for row in actual), 4)
        files['returns_by_order.query.view'] = files['returns_by_order.query.view'].replace('${returns}', '${missing_returns}')
        with self.assertRaises(FixtureCompileError):
            execute_candidate(files, 'returns_by_order', self.db)

    def test_same_candidate_observes_counterfactual_input_instead_of_memorized_totals(self):
        files = case_files('sql_query_view')
        with (CORPUS / 'data/extra_return_append.csv').open() as stream:
            row = next(csv.DictReader(stream))
        self.db.execute('INSERT INTO RETURNS VALUES (?, ?, ?, ?, ?)',
                        (row['return_id'], row['line_id'], row['returned_on'], int(row['quantity']), int(row['refund_cents'])))
        actual, _ = execute_candidate(files, 'returns_by_order', self.db)
        expected = json.loads((CORPUS / 'expected/variants.json').read_text())['counterfactual_extra_return']
        self.assertEqual(sum(row['refund_cents'] for row in actual), expected['total_paid_refund_cents'])
        self.assertEqual(sum(row['returned_quantity'] for row in actual), expected['total_returned_quantity'])
        self.assertNotEqual(actual, expected_rows('query_returns_by_order.csv'))

    def test_physical_binding_mutation_is_observable(self):
        files = case_files('modeled_query_view')
        files['orders.view'] = files['orders.view'].replace('table_name: ORDERS', 'table_name: MISSING_ORDERS')
        with self.assertRaises(sqlite3.OperationalError):
            execute_candidate(files, 'orders_by_customer', self.db)


@unittest.skipUnless(SEMANTIC_RUNTIME, 'Pinned YAML/sqlglot needed for static and generated-model evidence')
class IndependentCoreGenerationTests(unittest.TestCase):
    def setUp(self):
        self.context = json.loads((CORPUS / 'context.json').read_text())
        self.db = fixture_database(); self.addCleanup(self.db.close)

    def test_measure_local_filters_custom_ratio_and_role_aliases_pass_static(self):
        for case in ('measure_local_filters_and_ratio', 'role_aliases'):
            with self.subTest(case=case):
                report = contract.check_model(case_files(case), self.context)
                self.assertEqual(report['status'], 'passed', report)
                self.assertFalse(report['native_verified'])
                self.assertFalse(report['security_verified'])

    def test_invalid_filter_shape_missing_filter_field_and_nested_ratio_do_not_pass(self):
        for mutation in ('scalar-filter', 'missing-filter-field', 'nested-ratio'):
            files = case_files('measure_local_filters_and_ratio')
            body = files['orders.view']
            if mutation == 'scalar-filter': body = body.replace('status:\n        is: paid', 'status: paid')
            elif mutation == 'missing-filter-field': body = body.replace('      status:\n        is: paid', '      missing_status:\n        is: paid')
            else: body = body.replace('${paid_shipping_cents} / NULLIF(${shipping_cents}, 0)', 'SUM(${paid_shipping_cents}) / NULLIF(SUM(${shipping_cents}), 0)')
            files['orders.view'] = body
            with self.subTest(mutation=mutation):
                self.assertNotEqual(contract.check_model(files, self.context)['status'], 'passed')

    def test_ai_awareness_selection_does_not_exclude_runtime_dependencies(self):
        for ai_fields in (['orders.paid_shipping_share'],
                          ['all_views.*', '-orders.shipping_amount_cents', '-orders.status']):
            files = case_files('measure_local_filters_and_ratio')
            topic = contract.yaml.safe_load(files['orders.topic'])
            topic['fields'] = ['all_views.*']
            topic['ai_fields'] = ai_fields
            files['orders.topic'] = contract.yaml.safe_dump(topic)
            with self.subTest(ai_fields=ai_fields):
                report = contract.check_model(files, self.context)
                self.assertEqual(report['status'], 'passed', report)
                self.assertIn('orders.shipping_amount_cents', report['topic_scopes']['orders']['selections']['fields'])
                self.assertFalse(report['security_verified'])

    def test_runtime_field_exclusion_blocks_dependent_measure(self):
        files = case_files('measure_local_filters_and_ratio')
        topic = contract.yaml.safe_load(files['orders.topic'])
        topic['fields'] = ['all_views.*', '-orders.shipping_amount_cents']
        topic['ai_fields'] = ['orders.paid_shipping_share']
        files['orders.topic'] = contract.yaml.safe_dump(topic)
        report = contract.check_model(files, self.context)
        self.assertNotEqual(report['status'], 'passed')
        self.assertIn('topic.excluded_dependency', {finding['code'] for finding in report['findings']})

    def test_generated_core_definitions_drive_exact_query_results(self):
        args = physical_orders_spec(); before = copy.deepcopy(args)
        generated = generator.generate_model(*args)
        self.assertEqual(generated['check']['status'], 'passed', generated['check'])
        files = dict(generated['files'])
        files['orders_by_customer.query.view'] = (CORPUS / 'source/query/orders_by_customer.query.view').read_text()
        actual, _ = execute_candidate(files, 'orders_by_customer', self.db)
        self.assertEqual(sorted(actual, key=lambda row: row['customer_id']), expected_rows('query_orders_by_customer.csv'))
        self.assertEqual(args, before)
        for key in ('native_verified', 'deployment_authorized', 'review_authority_authenticated'):
            self.assertFalse(generated['manifest'][key])

    def test_generated_custom_ratio_uses_both_aggregate_operands_and_zero_guard(self):
        generated = generator.generate_model(*physical_orders_spec())
        compiler = FixtureCompiler(generated['files'])
        ratio_sql, _ = compiler.field('orders', 'paid_shipping_share')
        actual = self.db.execute('SELECT ' + ratio_sql + ' AS ratio FROM ORDERS').fetchone()['ratio']
        expected = json.loads((CORPUS / 'expected/metrics.json').read_text())['totals']['paid_shipping_share']
        self.assertEqual(Fraction(actual).limit_denominator(), Fraction(expected['numerator'], expected['denominator']))
        zero = self.db.execute('SELECT ' + ratio_sql + ' AS ratio FROM ORDERS WHERE order_id = ?', ('o14',)).fetchone()['ratio']
        self.assertIsNone(zero)


@unittest.skipUnless(SEMANTIC_RUNTIME, 'Pinned YAML/sqlglot needed for derived-view generation')
class IndependentDerivedGenerationTests(unittest.TestCase):
    def setUp(self):
        self.context = json.loads((CORPUS / 'context.json').read_text())
        self.db = fixture_database(); self.addCleanup(self.db.close)

    def test_frozen_modeled_and_sql_query_views_pass_static_without_native_claims(self):
        for case in ('modeled_query_view', 'sql_query_view'):
            files = case_files(case)
            with self.subTest(case=case):
                result = contract.check_model(files, self.context)
                self.assertEqual(result['status'], 'passed', result)
                self.assertEqual(result['candidate_sha256'], canonical_hash(files))
                self.assertFalse(result['native_verified'])
                self.assertFalse(result['security_verified'])

    def test_generated_derived_views_execute_the_frozen_rows(self):
        for form, expected, key in (('modeled', 'query_orders_by_customer.csv', 'customer_id'),
                                    ('sql', 'query_returns_by_order.csv', 'order_id')):
            args, name = derived_view_spec(form); before = copy.deepcopy(args)
            with self.subTest(form=form):
                generated = generator.generate_model(*args)
                self.assertEqual(generated['check']['status'], 'passed', generated['check'])
                self.assertIn(name + '.query.view', generated['files'])
                self.assertNotIn(name + '.view', generated['files'])
                self.assertNotIn(name, args[1]['bindings'])
                with patch.object(Path, 'read_text', side_effect=AssertionError('compiler may not read oracle')):
                    rows, _ = execute_candidate(generated['files'], name, self.db)
                self.assertEqual(sorted(rows, key=lambda row: row[key]), expected_rows(expected))
                self.assertEqual(args, before)
                for claim in ('native_verified', 'deployment_authorized', 'review_authority_authenticated'):
                    self.assertFalse(generated['manifest'][claim])

    def test_generated_filter_mutation_changes_output_without_leaking_to_other_measure(self):
        args, name = derived_view_spec('modeled')
        spec, _, _, placement = args
        for field in ('paid_order_count', 'paid_shipping_cents'):
            spec['views']['orders']['definition']['measures'][field]['filters']['status']['is'] = 'pending'
            placement['measures'][field]['definition']['filters']['status']['is'] = 'pending'
        repin(args)
        generated = generator.generate_model(*args)
        self.assertEqual(generated['check']['status'], 'passed', generated['check'])
        rows, _ = execute_candidate(generated['files'], name, self.db)
        self.assertEqual(sum(row['paid_shipping_cents'] for row in rows), 300)
        self.assertEqual(sum(row['shipping_cents'] for row in rows), 1050)
        self.assertNotEqual(rows, expected_rows('query_orders_by_customer.csv'))

    def test_sorted_limit_remains_unqualified_while_local_interpretation_retains_truncation(self):
        args, name = derived_view_spec('modeled')
        spec, _, model, _ = args
        query = spec['views'][name]['definition']['query']
        query['sorts'] = [{'field': 'orders.shipping_cents', 'desc': True},
                          {'field': 'orders.customer_id', 'desc': False}]
        query['limit'] = 1
        model['query_views'][name]['definition'] = copy.deepcopy(spec['views'][name]['definition'])
        repin(args)
        generated = generator.generate_model(*args)
        # This locally interpreted shape is not a qualified native query-view
        # serialization contract. It must remain preserved but unsupported.
        self.assertEqual(generated['check']['status'], 'unsupported', generated['check'])
        self.assertIn('query.sort_limit_native_contract_unqualified',
                      {finding['code'] for finding in generated['check']['findings']})
        descriptor = generated['check']['query_views'][name]
        self.assertFalse(descriptor['complete_population'])
        self.assertEqual(descriptor['truncation'], 'limited')
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'must-not-be-written'
            with self.assertRaises(ValueError):
                generator.write_candidate(generated, destination)
            self.assertFalse(destination.exists())
        candidate = contract.yaml.safe_load(generated['files'][name + '.query.view'])
        self.assertEqual(candidate['query']['limit'], 1)
        self.assertEqual(candidate['query']['sorts'], query['sorts'])
        rows, _ = execute_candidate(generated['files'], name, self.db)
        expected = json.loads((CORPUS / 'expected/variants.json').read_text())['top_one_customer_shipping']
        self.assertEqual(rows, expected['expected_rows'])
        self.assertNotEqual(rows, expected_rows('query_orders_by_customer.csv'))

    def test_missing_output_mapping_source_field_and_unsorted_limit_are_not_static_success(self):
        for mutation in ('missing-output', 'missing-field', 'unsorted-limit', 'bad-sort-direction'):
            files = case_files('modeled_query_view')
            definition = contract.yaml.safe_load(files['orders_by_customer.query.view'])
            query = definition['query']
            if mutation == 'missing-output': del query['fields']['orders.paid_shipping_cents']
            elif mutation == 'missing-field': query['fields']['orders.missing_value'] = query['fields'].pop('orders.paid_shipping_cents')
            elif mutation == 'unsorted-limit': query['limit'] = 1
            else: query['sorts'] = [{'field': 'orders.shipping_cents', 'desc': 'yes'}]
            files['orders_by_customer.query.view'] = contract.yaml.safe_dump(definition)
            with self.subTest(mutation=mutation):
                self.assertNotEqual(contract.check_model(files, self.context)['status'], 'passed')

    def test_query_output_mapping_and_physical_binding_cannot_be_fabricated(self):
        for mutation in ('output-alias', 'physical-column', 'physical-binding'):
            args, name = derived_view_spec('modeled')
            spec, context, _, _ = args
            mapping = spec['views'][name]['field_mappings']['paid_shipping_cents']
            if mutation == 'output-alias': mapping['output'] = 'absent_output'
            elif mutation == 'physical-column': mapping['column'] = 'shipping_cents'
            else: context['bindings'][name] = copy.deepcopy(context['bindings']['orders'])
            repin(args)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                generator.generate_model(*args)

    def test_sql_unknown_function_raw_relation_and_missing_alias_do_not_pass(self):
        for mutation in ('unknown-function', 'raw-relation', 'missing-output-alias'):
            files = case_files('sql_query_view')
            body = files['returns_by_order.query.view']
            if mutation == 'unknown-function': body = body.replace('SUM(r."refund_cents")', 'UNQUALIFIED_CORPUS_FUNCTION(r."refund_cents")')
            elif mutation == 'raw-relation': body = body.replace('${returns}', 'OUTSIDE_FIXTURE')
            else: body = body.replace(' AS refund_cents', '')
            files['returns_by_order.query.view'] = body
            with self.subTest(mutation=mutation):
                self.assertNotEqual(contract.check_model(files, self.context)['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
