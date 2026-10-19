"""Small retained synthetic delivery; local checks never establish native acceptance.

``build_delivery(Path('/private/tmp/new-demo'))`` writes a new, self-contained
review fixture. It does not call a warehouse, dbt, Omni, or a model provider.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import engagement_stages as stages
import finalize_delivery as finalizer
import guided_workflow as guided
import mapping_coverage
import reuse_coverage
import workflow_reconciliation
from ae_common import hash_json
from design_consistency import project_review
from disclosure_fixtures import synthetic_disclosure
from source_adapters.looker import parse as parse_looker


QUALIFICATION = ('Synthetic provisional candidate. Local static checks and DuckDB '
    'results do not establish BigQuery execution, dbt compilation, Omni native '
    'validation, human design approval, or production acceptance.')
SEEDS = {
    'orders': 'order_id,customer_id,status\n1,10,completed\n2,20,completed\n3,10,pending\n',
    'lines': 'line_id,order_id,product_id,quantity,unit_price\n101,1,p1,2,10\n102,1,p2,1,30\n103,2,p1,1,10\n104,3,p2,1,30\n',
    'refunds': 'refund_id,line_id,amount\n201,101,5\n202,101,2\n203,103,1\n',
    'customers': 'customer_id,customer_name\n10,Customer 10\n20,Customer 20\n',
    'products': 'product_id,product_name\np1,Product 1\np2,Product 2\n',
}
SQL = {
    'dim_customers': "SELECT customer_id, customer_name FROM {{ source('synthetic', 'customers') }}",
    'dim_products': "SELECT product_id, product_name FROM {{ source('synthetic', 'products') }}",
    'fct_refunds': "SELECT refund_id, line_id, amount FROM {{ source('synthetic', 'refunds') }}",
    'fct_order_lines': """WITH refund_by_line AS (
  SELECT line_id, SUM(amount) AS refund_amount
  FROM {{ source('synthetic', 'refunds') }} GROUP BY line_id
)
SELECT l.line_id, l.order_id, o.customer_id, l.product_id, o.status,
       l.quantity * l.unit_price AS gross_amount,
       COALESCE(r.refund_amount, 0) AS refund_amount,
       l.quantity * l.unit_price - COALESCE(r.refund_amount, 0) AS net_amount
FROM {{ source('synthetic', 'lines') }} l
JOIN {{ source('synthetic', 'orders') }} o ON l.order_id = o.order_id
LEFT JOIN refund_by_line r ON l.line_id = r.line_id""",
}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_sql(sql):
    """Replace only the finite fixture's source/ref tokens; never execute macros."""
    for name in SEEDS:
        sql = sql.replace("{{ source('synthetic', '" + name + "') }}", 'raw_' + name)
    for name in SQL:
        sql = sql.replace("{{ ref('" + name + "') }}", name)
    if '{{' in sql or '{%' in sql:
        raise ValueError('Unexpected fixture template expression')
    return sql


def _design():
    columns = {
        'dim_customers': [('customer_id', 'INT64'), ('customer_name', 'STRING')],
        'dim_products': [('product_id', 'STRING'), ('product_name', 'STRING')],
        'fct_refunds': [('refund_id', 'INT64'), ('line_id', 'INT64'), ('amount', 'NUMERIC')],
        'fct_order_lines': [('line_id', 'INT64'), ('order_id', 'INT64'), ('customer_id', 'INT64'),
            ('product_id', 'STRING'), ('status', 'STRING'), ('gross_amount', 'NUMERIC'),
            ('refund_amount', 'NUMERIC'), ('net_amount', 'NUMERIC')],
    }
    entities = []
    for name, fields in columns.items():
        domain = 'refunds' if name == 'fct_refunds' else 'sales'
        entities.append({'id': name, 'name': name, 'domain': domain, 'layer': 'gold',
            'grain': 'One row per ' + fields[0][0], 'keys': [fields[0][0]],
            'columns': [{'name': key, 'type': kind, 'description': 'Synthetic ' + key} for key, kind in fields],
            'depends_on': ['dim_customers', 'dim_products'] if name == 'fct_order_lines' else [],
            'asset_ids': ['report:' + domain], 'security': 'Public synthetic values; no personal data',
            'history': 'Current state fixture only', 'disposition': 'create', 'reuse': None,
            'source_paths': [domain + '.view.lkml'], 'catalogue_pointers': ['/objects/' + name]})
    return {'schema_version': 1, 'id': 'synthetic-commerce', 'revision': 1, 'entities': entities,
        'relationships': [{'from': start, 'to': end, 'kind': 'relationship', 'cardinality': 'many_to_one',
            'from_columns': [key], 'to_columns': [key]} for start, end, key in [
                ('fct_order_lines', 'dim_customers', 'customer_id'),
                ('fct_order_lines', 'dim_products', 'product_id'),
                ('fct_refunds', 'fct_order_lines', 'line_id')]],
        'assets': [{'id': 'report:' + domain, 'name': domain.title(), 'kind': 'report',
                    'mapping_status': 'inferred'} for domain in ('sales', 'refunds')],
        'decisions': [], 'existing_models': [{'id': 'legacy_customers', 'name': 'legacy_customers',
            'grain': 'Unverified customer grain', 'keys': ['customer_id'], 'definitions': 'Synthetic inventory only',
            'history': 'Unknown', 'security': 'Unknown', 'dependencies': [],
            'evidence_refs': ['synthetic:legacy-customers']}]}


def _write_code(candidate, design):
    import yaml
    written = {'warehouse': [], 'semantic': []}

    def write(path, body, task):
        destination = candidate / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body, encoding='utf-8')
        written[task].append(path)

    project_example = ROOT / 'skills/data-model-accelerator/examples/tableau-omni-e2e/target/dbt/dbt_project.yml'
    project = yaml.safe_load(project_example.read_text())
    project.update(name='synthetic_commerce', profile='synthetic_bigquery')
    project['models'] = {'synthetic_commerce': {'+materialized': 'table'}}
    write('dbt/dbt_project.yml', yaml.safe_dump(project), 'warehouse')
    write('dbt/models/sources.yml', yaml.safe_dump({'version': 2, 'sources': [{
        'name': 'synthetic', 'database': 'synthetic-project', 'schema': 'synthetic_raw',
        'tables': [{'name': n} for n in SEEDS]}]}), 'warehouse')
    models = []
    for entity in design['entities']:
        name, key = entity['id'], entity['keys'][0]
        write('dbt/models/' + name + '.sql', '-- ' + QUALIFICATION + '\n' + SQL[name] + '\n', 'warehouse')
        models.append({'name': name, 'description': entity['grain'], 'columns': [
            {'name': c['name'], 'description': c['description'],
             **({'data_tests': ['unique', 'not_null']} if c['name'] == key else {})}
            for c in entity['columns']]})
    write('dbt/models/schema.yml', yaml.safe_dump({'version': 2, 'models': models}), 'warehouse')
    write('dbt/tests/net_matches_components.sql',
        "SELECT * FROM {{ ref('fct_order_lines') }} WHERE net_amount != gross_amount - refund_amount\n", 'warehouse')

    # Reuse maintained native-file shapes. These remain unvalidated candidates.
    examples = ROOT / 'skills/data-model-accelerator/examples/looker-omni-e2e/target/omni'
    invoice = yaml.safe_load((examples / 'invoices.view').read_text())
    topic = yaml.safe_load((examples / 'billing.topic').read_text())
    relation = yaml.safe_load((examples / 'relationships').read_text())[0]
    for entity in design['entities']:
        name = entity['id']
        view = {key: copy.deepcopy(invoice[key]) for key in ('catalog', 'schema', 'table_name', 'label', 'description')}
        view.update(catalog='synthetic-project', schema='synthetic_analytics', table_name=name,
                    label=name, description=QUALIFICATION, dimensions={})
        for column in entity['columns']:
            dimension = copy.deepcopy(invoice['dimensions']['invoice_id'])
            dimension['sql'] = '`' + column['name'] + '`'
            if column['name'] in entity['keys']:
                dimension.update(primary_key=True, hidden=True)
            view['dimensions'][column['name']] = dimension
        if name == 'fct_order_lines':
            view['measures'] = {}
            for field in ('gross_amount', 'refund_amount', 'net_amount'):
                measure = copy.deepcopy(invoice['measures']['raw_net_cents_sum'])
                measure.update(sql='${' + name + '.' + field + '}', hidden=False)
                measure['filters']['status']['is'] = 'completed'
                view['measures'][field + '_sum'] = measure
        write('omni/' + name + '.view', '# ' + QUALIFICATION + '\n' + yaml.safe_dump(view, sort_keys=False), 'semantic')
    for name, base, joins in [('sales', 'fct_order_lines', ['dim_customers', 'dim_products']),
                               ('refunds', 'fct_refunds', ['fct_order_lines'])]:
        value = copy.deepcopy(topic)
        value.pop('access_filters')  # The public synthetic fixture has no tenant attribute.
        value.update(base_view=base, label='Synthetic ' + name, description=QUALIFICATION,
                     joins={target: {} for target in joins})
        write('omni/' + name + '.topic', yaml.safe_dump(value, sort_keys=False), 'semantic')
    relationships = []
    for edge in design['relationships']:
        value = copy.deepcopy(relation)
        key = edge['from_columns'][0]
        value.update(join_from_view=edge['from'], join_to_view=edge['to'],
                     on_sql='${' + edge['from'] + '.' + key + '} = ${' + edge['to'] + '.' + key + '}')
        relationships.append(value)
    write('omni/relationships', yaml.safe_dump(relationships, sort_keys=False), 'semantic')
    return written


def _review(state, candidate, paths):
    artifacts = [{'id': 'design-narrative', 'path': 'model.md', 'category': 'documentation',
                  'audiences': ['engineer', 'reviewer'], 'sha256': _sha(candidate / 'model.md')}]
    artifacts.extend({'id': 'code-' + str(index), 'path': path, 'category': 'implementation',
        'audiences': ['engineer', 'reviewer'], 'sha256': _sha(candidate / path)} for index, path in enumerate(paths))
    projection = project_review(state['workflow']['design'])
    return {'schema_version': 1, 'title': 'Synthetic BigQuery commerce review', 'description': QUALIFICATION,
        'source_fingerprint': portal.source_fingerprint(state), 'context_sha256': portal.context_fingerprint(state),
        'target': {'framework': 'dbt', 'warehouse': 'bigquery'}, 'artifacts': artifacts,
        'handoff': {'design_artifact_id': 'design-narrative'},
        **{key: projection[key] for key in ('design_binding', 'models', 'relationships', 'assets')},
        'disclosure': synthetic_disclosure([a['id'] for a in artifacts], 'engineer')}


def build_delivery(output_root):
    """Create a fresh retained demo using actual public workflow entry points."""
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    source, run, candidate = root / 'source', root / 'engagement', root / 'candidate'
    source.mkdir(); candidate.mkdir()
    files = {
        'commerce.model.lkml': 'connection: "synthetic_bigquery"\ninclude: "*.view.lkml"\nexplore: sales {}\nexplore: refunds {}\n',
        'sales.view.lkml': '''view: sales {
  derived_table { sql: SELECT l.*, o.status FROM synthetic_raw.lines l
    JOIN synthetic_raw.orders o ON l.order_id = o.order_id ;; }
  dimension: line_id { primary_key: yes type: number sql: ${TABLE}.line_id ;; }
  dimension: status { sql: ${TABLE}.status ;; }
  measure: gross { type: sum sql: ${TABLE}.quantity * ${TABLE}.unit_price ;; filters: [status: "completed"] }
}''',
        'refunds.view.lkml': '''view: refunds {
  sql_table_name: synthetic_raw.refunds ;;
  dimension: refund_id { primary_key: yes type: number sql: ${TABLE}.refund_id ;; }
  dimension: line_id { type: number sql: ${TABLE}.line_id ;; }
  measure: refund_amount { type: sum sql: ${TABLE}.amount ;; }
}''',
    }
    for path, body in files.items():
        (source / path).write_text(body, encoding='utf-8')
    for name, body in SEEDS.items():
        (source / (name + '.csv')).write_text(body, encoding='utf-8')
    source_hashes = {str(p.relative_to(source)): _sha(p) for p in source.iterdir()}
    design = _design()
    catalogue = root / 'synthetic-catalogue.json'
    catalogue.write_text(json.dumps({'objects': {e['id']: {'columns': e['columns']} for e in design['entities']}}))
    answers = {'engagement_type': 'new_model', 'priority_domain': 'Sales and refunds', 'framework': 'dbt',
        'warehouse': 'bigquery', 'semantic_target': 'omni', 'migration_scope': 'model_semantic',
        'input_handling': 'pre_sanitized', 'audience': 'engineer',
        'deliverables': ['documentation', 'dictionary', 'diagrams']}
    state = guided.start_engagement(source, run, answers, catalogue)
    state = guided.stage_action(run, 'import-design', document=design)
    narrative = ('# Synthetic commerce proposal\n\n' + QUALIFICATION + '\n\n'
        'Two facts and two dimensions preserve line and refund grains. Refunds must be summed by line '
        'before joining to order-line amounts. Completed orders total gross 60, refunds 8 and net 52; '
        'customer 10 net is 43 and customer 20 net is 9. Pending order 3 is excluded. '
        'Currency is synthetic USD only; no FX conversion or time-zone behavior is established.\n\n'
        'Every source occurrence remains unresolved in the coverage ledger. Legacy customer ownership '
        'is unassigned. A supplied catalogue is removed before provisional generation. '
        'The disclosure approval is a synthetic packaging fixture, not a human design review.\n\n'
        'The dbt project declares BigQuery sources in synthetic-project.synthetic_raw. The CSV inputs '
        'are supplied separately; loading them, configuring a local BigQuery profile, running dbt compile '
        'and native Omni import are operator work not performed by this fixture.\n')
    (candidate / 'model.md').write_text(narrative)
    review = _review(state, candidate, [])
    design_final = finalizer.finalize_delivery(state, review, candidate, root / 'design-delivery')
    report = parse_looker(files)
    state = guided.stage_action(run, 'record-coverage', document={'schema_version': 1, 'reports': [report],
        'expected_files': [{'source': 'looker', 'path': row['path'], 'sha256': row['sha256']} for row in report['source_files']],
        'requirements': [{'id': 'completed-net', 'description': 'Completed line gross less line refunds', 'domain': 'sales'}],
        'targets': [], 'mappings': []})
    existing = design['existing_models'][0]
    state = guided.stage_action(run, 'record-reuse', document={'schema_version': 1,
        'inventory': [{'existing_id': existing['id'], 'namespace': 'synthetic',
            'native_id': 'model.synthetic.legacy_customers', 'snapshot_sha256': hash_json(existing)}], 'assignments': []})
    state = guided.update_answers(run, {'deliverables': ['documentation', 'dictionary', 'diagrams', 'implementation']}, catalogue=None)

    def proposals(revision, values):
        proposed = copy.deepcopy(design); proposed['revision'] = revision
        return {'schema_version': 1, 'proposals': [{'id': domain, 'design': proposed,
            'shared_rules': [{'id': 'currency-basis', 'dimension': 'currency', 'value': value,
                'model_ids': [model], 'evidence_refs': ['synthetic:' + domain + ':currency']} ]}
            for domain, model, value in zip(('sales', 'refunds'), ('fct_order_lines', 'fct_refunds'), values)]}

    state = guided.stage_action(run, 'reconcile-design', document=proposals(2, ('monthly_fx', 'daily_fx')))
    conflict = workflow_reconciliation.summarize(state)
    canonical_during_conflict = copy.deepcopy(state['workflow']['design'])
    state = guided.stage_action(run, 'reconcile-design', document=proposals(3, ('synthetic_usd_no_fx',) * 2))
    reconciled = workflow_reconciliation.summarize(state)
    scope = [e['id'] for e in design['entities']]
    state = guided.stage_action(run, 'request-draft', entities=scope, document={'schema_version': 1,
        'kind': 'provisional_code_request', 'requester': 'Synthetic operator', 'request_reference': 'synthetic://user/provisional',
        'request_text': 'Generate provisional dbt BigQuery and Omni candidates with the missing catalogue disclosed.',
        'bindings': stages.draft_bindings(state, scope)})
    outputs = _write_code(candidate, design)
    tasks = {'schema_version': 1, 'tasks': [{'id': task, 'stage': stage, 'entity_ids': scope,
        'depends_on': dependencies, 'components': [], 'outputs': outputs[task]}
        for task, stage, dependencies in [('warehouse', 'implementation', []), ('semantic', 'semantic', ['warehouse'])]]}
    state = guided.stage_action(run, 'plan-tasks', artifact_root=candidate, document=tasks)
    claim = {'schema_version': 1, 'work_id': 'warehouse', 'attempt_id': 'warehouse-1',
        'role': 'analytics_engineer', 'scope_ids': scope, 'source_paths': [], 'task_id': 'warehouse'}
    state = guided.stage_action(run, 'claim-work', document=claim)
    state = guided.stage_action(run, 'checkpoint-work', artifact_root=candidate, document={'schema_version': 1,
        'attempt_id': 'warehouse-1', 'status': 'interrupted', 'reason': 'Synthetic interruption before registration', 'outputs': []})
    state = guided.resume_engagement(run)
    state = guided.stage_action(run, 'claim-work', document={**claim, 'attempt_id': 'warehouse-2'})
    resume_action = copy.deepcopy(state['last_work_action'])
    for task in ('warehouse', 'semantic'):
        state = guided.stage_action(run, 'plan-tasks', artifact_root=candidate)
        plan = state['workflow']['last_plan']
        work = next(row for row in plan['tasks'] if row['id'] == task)
        state = guided.stage_action(run, 'record-task', artifact_root=candidate, document={
            'task_id': task, 'run_id': task + '-run', 'plan_sha256': plan['plan_sha256'], 'fingerprint': work['fingerprint'],
            'outputs': stages._output_hashes(candidate, outputs[task]), 'evidence_reference': 'synthetic://files/' + task})
        if task == 'warehouse':
            state = guided.stage_action(run, 'checkpoint-work', artifact_root=candidate, document={'schema_version': 1,
                'attempt_id': 'warehouse-2', 'status': 'outputs_recorded', 'reason': 'Candidate bytes registered', 'outputs': outputs[task]})
    state = guided.stage_action(run, 'claim-work', document={**claim, 'attempt_id': 'warehouse-3'})
    reuse_action = copy.deepcopy(state['last_work_action'])
    review = _review(state, candidate, outputs['warehouse'] + outputs['semantic'])
    (root / 'review.json').write_text(json.dumps(review, indent=2))
    final = finalizer.finalize_delivery(state, review, candidate, root / 'provisional-delivery')
    return {'root': root, 'source': source, 'candidate': candidate, 'run': run, 'state': state,
        'source_hashes': source_hashes, 'design_final': design_final, 'final': final,
        'conflict': conflict, 'canonical_during_conflict': canonical_during_conflict,
        'reconciled': reconciled, 'resume_action': resume_action, 'reuse_action': reuse_action,
        'coverage': mapping_coverage.summarize(state), 'reuse': reuse_coverage.summarize(state), 'outputs': outputs}


@unittest.skipUnless(importlib.util.find_spec('yaml') and importlib.util.find_spec('lkml'), 'Optional YAML/LookML parsers unavailable')
class BigQueryReviewJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.delivery = build_delivery(Path(cls.temp.name) / 'demo')

    def test_design_then_provisional_resume_retains_sources_scope_and_unknowns(self):
        import yaml
        d, state = self.delivery, self.delivery['state']
        self.assertEqual(d['source_hashes'], {str(p.relative_to(d['source'])): _sha(p) for p in d['source'].iterdir()})
        self.assertEqual(d['conflict']['status'], 'conflicts')
        self.assertEqual(d['canonical_during_conflict']['revision'], 1)
        self.assertEqual(d['reconciled']['status'], 'consistent')
        self.assertEqual(workflow_reconciliation.summarize(state)['status'], 'consistent')
        self.assertEqual(state['workflow']['design']['revision'], 3)
        self.assertGreater(d['coverage']['counts']['total'], 10)
        self.assertEqual(d['coverage']['counts']['unresolved'], d['coverage']['counts']['total'])
        self.assertEqual(d['reuse']['counts']['unassigned'], 1)
        self.assertEqual(state['workflow']['approvals'], [])
        self.assertFalse(stages.approved_entities(state))
        self.assertFalse(state['readiness']['execution_authorized'])
        self.assertFalse(state['readiness']['generation_ready'])
        self.assertTrue(state['readiness']['provisional_generation_available'])
        self.assertEqual({r['generation_mode'] for r in state['workflow']['runs']}, {'provisional'})
        self.assertEqual(len(state['workflow']['runs']), 2)
        self.assertEqual(d['resume_action']['action'], 'dispatch')
        self.assertEqual(d['resume_action']['resumes_attempt_id'], 'warehouse-1')
        self.assertEqual(d['reuse_action']['action'], 'reuse')
        semantic_checks = next(c for c in stages.public_view(state)['artifact_checks'] if c['task_id'] == 'semantic')
        self.assertEqual(semantic_checks['status'], 'passed')
        self.assertEqual(semantic_checks['counts']['passed'], len(d['outputs']['semantic']))
        # Independently check the candidate's declared references and columns;
        # neither these assertions nor recorded syntax establish native parity.
        for path in d['outputs']['semantic']:
            body = yaml.safe_load((d['candidate'] / path).read_text())
            self.assertIsInstance(body, list if path.endswith('/relationships') else dict)
            if path.endswith('.topic'):
                self.assertIn(body['base_view'], SQL)
                self.assertTrue(set(body['joins']) <= set(SQL))
            elif path.endswith('.view'):
                self.assertIn(body['table_name'], SQL)
                entity = next(e for e in state['workflow']['design']['entities'] if e['id'] == body['table_name'])
                self.assertEqual(set(body['dimensions']), {c['name'] for c in entity['columns']})
            else:
                self.assertEqual(len(body), 3)
                self.assertTrue(all(r['join_from_view'] in SQL and r['join_to_view'] in SQL for r in body))
        with zipfile.ZipFile(d['design_final']['zip']) as archive:
            self.assertFalse(any(p.startswith('02_Implementation/') for p in archive.namelist()))
        with zipfile.ZipFile(d['final']['zip']) as archive:
            names = archive.namelist()
            self.assertIn('START_HERE.html', names)
            self.assertIn('01_Model/Dictionary/data-dictionary.csv', names)
            self.assertTrue(any(p.endswith('.svg') for p in names))
            models = json.loads(archive.read('01_Model/ERD/model-source.json'))['models']
            self.assertEqual({m['id'] for m in models}, set(SQL))
            for model in models:
                self.assertTrue(any(p.endswith('/' + model['id'] + '.sql') for p in names))
            manifest = json.loads(archive.read('DELIVERY_MANIFEST.json'))
            self.assertFalse(manifest['acceptance_ready'])
            self.assertFalse(manifest['deployment_authorized'])
            self.assertIn(b'Synthetic provisional', archive.read('START_HERE.html'))

    @unittest.skipUnless(importlib.util.find_spec('duckdb'), 'Optional DuckDB unavailable')
    def test_generated_preaggregation_passes_independent_oracle_and_naive_join_fails(self):
        import duckdb
        con = duckdb.connect()
        self.addCleanup(con.close)
        for name in SEEDS:
            path = self.delivery['source'] / (name + '.csv')
            con.execute('CREATE TABLE raw_' + name + ' AS SELECT * FROM read_csv_auto(?)', [str(path)])
        for name in SQL:
            body = (self.delivery['candidate'] / 'dbt/models' / (name + '.sql')).read_text()
            con.execute('CREATE VIEW ' + name + ' AS ' + _render_sql(body))
        rows = con.execute("SELECT customer_id, SUM(gross_amount), SUM(refund_amount), SUM(net_amount) "
                           "FROM fct_order_lines WHERE status = 'completed' GROUP BY customer_id ORDER BY customer_id").fetchall()
        self.assertEqual(rows, [(10, 50, 7, 43), (20, 10, 1, 9)])
        totals = con.execute("SELECT SUM(gross_amount), SUM(refund_amount), SUM(net_amount) "
                             "FROM fct_order_lines WHERE status = 'completed'").fetchone()
        expected = (60, 8, 52)  # Independent fixture acceptance values.
        self.assertEqual(totals, expected)
        bad = con.execute("SELECT SUM(l.quantity*l.unit_price), SUM(COALESCE(r.amount,0)), "
            "SUM(l.quantity*l.unit_price-COALESCE(r.amount,0)) FROM raw_orders o JOIN raw_lines l USING(order_id) "
            "LEFT JOIN raw_refunds r USING(line_id) WHERE o.status = 'completed'").fetchone()
        self.assertEqual(bad, (80, 8, 72))
        with self.assertRaises(AssertionError):
            self.assertEqual(bad, expected)
        self.assertEqual(con.execute('SELECT COUNT(*), COUNT(DISTINCT line_id) FROM fct_order_lines').fetchone(), (4, 4))

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQLGlot unavailable; BigQuery parsing not performed')
    def test_generated_models_and_dbt_test_parse_as_bigquery_without_claiming_compile(self):
        import sqlglot
        paths = list((self.delivery['candidate'] / 'dbt').rglob('*.sql'))
        self.assertEqual(len(paths), len(SQL) + 1)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertTrue(sqlglot.parse(_render_sql(path.read_text()), read='bigquery', error_level='RAISE'))
        self.assertFalse(self.delivery['state']['readiness']['execution_authorized'])


if __name__ == '__main__':
    unittest.main()
