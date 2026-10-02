#!/usr/bin/env python3
"""Replay one reviewed synthetic Looker -> Snowflake -> Omni migration locally.

Requires the pinned optional E2E dependencies. No network, credentials, vendor
APIs or warehouse connections. This replays generated artifacts; it does not
claim a general LookML/Omni compiler or a fresh autonomous migration each run.
"""
import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import sqlglot
from sqlglot import exp
import yaml

from e2e_warehouse import (RAW, FixtureContractError, add_raw, build, catalogue_context,
                           execute_models, fact_rows, load_source, query_rows, sha,
                           to_duckdb, validate_raw)
from e2e_semantics import (compile_looker, compile_omni, describe_looker,
                           describe_omni, SemanticCompileError)
from verify_catalogue import verify as verify_catalogue


def normalized(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(item) for item in value]
    return value


def assert_rows(actual, expected):
    actual = normalized(actual)
    if len(actual) != len(expected):
        raise AssertionError('Row count differs: ' + str(len(actual)) + ' vs ' + str(len(expected)))
    for index, (got, want) in enumerate(zip(actual, expected)):
        if set(got) != set(want):
            raise AssertionError('Columns differ at row ' + str(index))
        for field, value in want.items():
            if field == 'payment_rate' and value is not None and got[field] is not None:
                if abs(Decimal(str(got[field])) - Decimal(str(value))) > Decimal('0.000000000001'):
                    raise AssertionError('Ratio mismatch at row ' + str(index))
            elif got[field] != value:
                raise AssertionError(field + ' differs at row ' + str(index) + ': ' + str(got[field]) + ' vs ' + str(value))


def write_json(path, value):
    Path(path).write_text(json.dumps(normalized(value), indent=2, default=str) + '\n')


def load_test_plan(case):
    """Require a predeclared denominator and frozen independent oracle inputs."""
    plan = json.loads((case / 'test-plan.json').read_text())
    required = plan['required_test_ids']
    if not required or len(required) != len(set(required)):
        raise ValueError('Test plan must predeclare unique required test IDs')
    pinned = {'expected/expected_rows.json', 'expected/expected_reports.json',
              'expected/oracle.py', 'input/scenario.md', 'input/raw-data.json'}
    if set(plan['frozen_input_hashes']) != pinned:
        raise ValueError('The independent oracle and scenario must all be pinned')
    for name, digest in plan['frozen_input_hashes'].items():
        if sha(case / name) != digest:
            raise ValueError('Frozen oracle/scenario changed: ' + name)
    scenarios = json.loads((case / 'expected/expected_reports.json').read_text())['scenarios']
    if [s['scenario_id'] for s in scenarios] != plan['scenario_ids']:
        raise ValueError('Executed scenarios differ from predeclared scenario inventory')
    return plan


def coverage_complete(required, checks):
    actual = [item['id'] for item in checks]
    if len(actual) != len(set(actual)) or set(actual) != set(required):
        raise ValueError('Required coverage differs from executed checks; missing=' +
                         str(sorted(set(required) - set(actual))) + '; extra=' +
                         str(sorted(set(actual) - set(required))))
    return bool(checks) and all(item['status'] == 'pass' for item in checks)


def report_contract(description):
    """Compare report behavior independently of renamed source/target views."""
    def field(name):
        if name == 'invoice_chaos.segment':
            return 'customers.segment'
        return name.replace('invoice_chaos.', 'invoices.')
    report = description['report_context']
    element = report['element']
    return {'defaults': description['runtime_defaults'],
            'fields': [field(f) for f in element['fields']],
            'filters': {field(f): v for f, v in element['filters'].items()},
            'controls': {c['name']: field(c['field']) for c in report['filters']},
            'listen': {k: field(v) for k, v in element['listen'].items()},
            'sorts': [field(f) for f in element['sorts']], 'limit': element['limit']}


def assert_contract(actual, expected):
    if actual != expected:
        raise AssertionError('Dashboard fields, filters, controls, defaults, ordering or limit changed')


def run(case, output):
    case, output = Path(case).resolve(), Path(output).resolve()
    if output == case or case in output.parents:
        raise ValueError('Use a new output directory outside the immutable case')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be new or empty')
    output.mkdir(parents=True, exist_ok=True)
    checks, boundaries, queries, assertions = [], [], [], []
    report = {'schema_version': 1, 'origin': 'synthetic_local_e2e', 'simulation_passed': False,
              'checks': checks, 'boundaries': boundaries, 'failures': [],
              'native_snowflake_execution': 'unavailable', 'native_looker_execution': 'unavailable',
              'native_omni_validation_execution': 'unavailable', 'production_approved': False,
              'implementation_hashes': {name: sha(Path(__file__).with_name(name)) for name in
                  ('run_looker_omni_e2e.py', 'e2e_warehouse.py', 'e2e_semantics.py',
                   'plan_specialists.py', 'verify_catalogue.py')},
              'dependencies': {p: importlib.metadata.version(p) for p in ('duckdb', 'sqlglot', 'lkml', 'PyYAML')}}

    def check(cid, category, function):
        try:
            detail = function()
            checks.append({'id': cid, 'category': category, 'status': 'pass', 'scope': 'local', 'detail': detail})
        except Exception as error:
            checks.append({'id': cid, 'category': category, 'status': 'fail', 'scope': 'local',
                           'error': type(error).__name__ + ': ' + str(error)})

    connection = None
    try:
        plan = load_test_plan(case)
        report['test_plan_sha256'] = sha(case / 'test-plan.json')
        report['required_test_ids'] = plan['required_test_ids']
        raw = json.loads((case / 'input/raw-data.json').read_text())
        expected_rows = json.loads((case / 'expected/expected_rows.json').read_text())
        scenarios = json.loads((case / 'expected/expected_reports.json').read_text())['scenarios']
        if not expected_rows or not scenarios:
            raise ValueError('Independent expectations cannot be empty')
        baseline = scenarios[0]
        planner = Path(__file__).with_name('plan_specialists.py')
        dispatched = subprocess.run([sys.executable, str(planner), str(case / 'input/repo'),
            '--output', str(output / 'source-plan'), '--no-git'], capture_output=True, text=True)
        if dispatched.returncode != 0:
            raise ValueError('Source inventory incomplete: ' + dispatched.stdout + dispatched.stderr)
        snapshot = sha(output / 'source-plan/inventory.json')
        catalogue_path, bindings_path, graph = catalogue_context(case, output / 'catalogue', snapshot)
        context = verify_catalogue(catalogue_path, bindings_path)
        write_json(output / 'catalogue-verification.json', context)
        if not context['catalogue_context_complete']:
            raise ValueError('Raw catalogue/bindings are incomplete')
        check('catalogue-physical-input-coverage', 'source_contract', lambda: {
            'physical_inputs': len(graph['physical_inputs']), 'columns': context['counts']['columns'],
            'source_snapshot_sha256': snapshot, 'catalogue_sha256': context['catalogue_sha256']})
        write_json(output / 'source-graph.json', graph)
        check('raw-cdc-types-currency-history-contract', 'source_contract', lambda: validate_raw(raw))
        connection = build(case, raw)
        source_view, source_sql, _ = load_source(case / 'input/repo')
        check('gold-rows-independent-oracle', 'logic', lambda: assert_rows(fact_rows(connection), expected_rows))
        source_rows = query_rows(connection, 'SELECT ' + ','.join(expected_rows[0])
                                 + ' FROM (' + source_sql + ') source_rows ORDER BY tenant_id,invoice_id')
        check('legacy-derived-rows-independent-oracle', 'reconciliation', lambda: assert_rows(source_rows, expected_rows))

        def scalar_zero(sql):
            assertions.append(sql)
            value = query_rows(connection, sql)[0]['violations']
            if value != 0:
                raise AssertionError(str(value) + ' violations')
            return {'violations': 0}

        check('fact-grain-and-key', 'grain', lambda: scalar_zero('''SELECT COUNT(*) AS violations FROM
          (SELECT tenant_id,invoice_id FROM DMA_SIM.GOLD.FCT_INVOICES GROUP BY tenant_id,invoice_id HAVING COUNT(*) <> 1
           UNION ALL SELECT tenant_id,invoice_id FROM DMA_SIM.GOLD.FCT_INVOICES WHERE invoice_key IS NULL
           UNION ALL SELECT invoice_key,invoice_key FROM DMA_SIM.GOLD.FCT_INVOICES GROUP BY invoice_key HAVING COUNT(*) <> 1)'''))
        check('dimension-key-unique', 'grain', lambda: scalar_zero('''SELECT COUNT(*) AS violations FROM
          (SELECT customer_key FROM DMA_SIM.GOLD.DIM_CUSTOMERS GROUP BY customer_key HAVING COUNT(*) <> 1 OR customer_key IS NULL)'''))
        check('fact-dimension-exactly-one-match', 'fanout', lambda: scalar_zero('''SELECT COUNT(*) AS violations FROM
          (SELECT i.invoice_key FROM DMA_SIM.GOLD.FCT_INVOICES i LEFT JOIN DMA_SIM.GOLD.DIM_CUSTOMERS c
           ON i.customer_key=c.customer_key AND i.tenant_id=c.tenant_id GROUP BY i.invoice_key HAVING COUNT(c.customer_key) <> 1)'''))
        check('tenant-dimension-isolation', 'security', lambda: scalar_zero('''SELECT COUNT(*) AS violations
          FROM DMA_SIM.GOLD.FCT_INVOICES i JOIN DMA_SIM.GOLD.DIM_CUSTOMERS c ON i.customer_key=c.customer_key
          WHERE i.tenant_id <> c.tenant_id'''))
        check('effective-customer-history', 'history', lambda: scalar_zero('''SELECT COUNT(*) AS violations
          FROM DMA_SIM.GOLD.FCT_INVOICES i JOIN DMA_SIM.GOLD.DIM_CUSTOMERS c ON i.customer_key=c.customer_key
          WHERE c.customer_id IS NOT NULL AND NOT (i.issued_at >= c.valid_from AND (i.issued_at < c.valid_to OR c.valid_to IS NULL))'''))
        check('retain-nonreport-populations', 'logic', lambda: scalar_zero('''SELECT CASE WHEN
          (SELECT COUNT(*) FROM DMA_SIM.GOLD.FCT_INVOICES WHERE status='draft')=1 AND
          (SELECT COUNT(*) FROM DMA_SIM.GOLD.FCT_INVOICES WHERE currency='EUR')=1 AND
          (SELECT COUNT(*) FROM DMA_SIM.GOLD.FCT_INVOICES WHERE invoice_date < '2026-09-01')=2
          THEN 0 ELSE 1 END AS violations'''))
        def preserved_report():
            for describe, location in [(describe_looker, case / 'input/repo'),
                                       (describe_omni, case / 'target/omni')]:
                assert_contract(report_contract(describe(location)), plan['report_contract'])
        check('report-fields-controls-and-defaults-preserved', 'report_context', preserved_report)
        default_expected = next(s['rows'] for s in scenarios
                                if s['scenario_id'] == 'a_usd_september_by_segment')
        for name, compiler, location in [('omni', compile_omni, case / 'target/omni'),
                                         ('looker', compile_looker, case / 'input/repo')]:
            check(name + '-dashboard-defaults-executed', 'report_context', lambda c=compiler,l=location:
                  assert_rows(query_rows(connection, c(l, {'tenant': 'A', 'group_by': ['segment']})), default_expected))
        results = []
        for scenario in scenarios:
            sid, params, expected = scenario['scenario_id'], scenario['parameters'], scenario['rows']
            source_query = compile_looker(case / 'input/repo', params)
            target_query = compile_omni(case / 'target/omni', params)
            queries.append({'scenario_id': sid, 'source_sql': source_query, 'omni_sql': target_query})
            source_result, target_result = query_rows(connection, source_query), query_rows(connection, target_query)
            results.append({'scenario_id': sid, 'source': source_result, 'target': target_result, 'expected': expected})
            check('omni-' + sid, 'reconciliation', lambda a=target_result, b=expected: assert_rows(a, b))
            if expected == [{'invoice_count': 0, 'net_cents': 0, 'paid_cents': 0, 'payment_rate': None}]:
                source_empty = [{'invoice_count': 0, 'net_cents': None, 'paid_cents': None, 'payment_rate': None}]
                check('source-empty-sql-boundary-recorded', 'logic', lambda: assert_rows(source_result, source_empty))
                boundaries.append({'id': 'empty-total-policy', 'observed': 'Offline direct SQL aggregate expansion returns NULL sums for empty population.',
                    'proposed': 'Omni compound wrappers explicitly return zero totals under the synthetic scenario contract.',
                    'native_looker_behavior': 'unverified', 'business_approval': False})
            else:
                check('legacy-' + sid, 'reconciliation', lambda a=source_result, b=expected: assert_rows(a, b))
        check('omni-measure-filters-without-dashboard', 'logic', lambda: assert_rows(query_rows(connection,
            compile_omni(case / 'target/omni', baseline['parameters'], apply_dashboard_filters=False)), baseline['rows']))
        check('looker-measure-filters-without-dashboard', 'logic', lambda: assert_rows(query_rows(connection,
            compile_looker(case / 'input/repo', baseline['parameters'], apply_dashboard_filters=False)), baseline['rows']))

        def denied(compiler, location, tenant):
            params = dict(baseline['parameters'], tenant=tenant)
            try:
                compiler(location, params)
            except SemanticCompileError as error:
                return {'denied': True, 'reason': str(error), 'scope': 'local policy simulation only'}
            raise AssertionError('Invalid persona unexpectedly produced SQL')

        for tenant in (None, '', 'unknown'):
            for name, compiler, location in [('omni', compile_omni, case / 'target/omni'), ('looker', compile_looker, case / 'input/repo')]:
                check(name + '-deny-persona-' + repr(tenant), 'security', lambda c=compiler,l=location,t=tenant: denied(c,l,t))

        def replay():
            add_raw(connection, raw)
            execute_models(connection, case / 'target/snowflake', bronze=False)
            assert_rows(fact_rows(connection), expected_rows)
            return {'raw_events_loaded_twice': True, 'same_gold_rows': True, 'mode': 'full model rebuild, not incremental MERGE'}
        check('replay-preserves-gold', 'replay', replay)
        def reordered():
            shuffled = {k: list(reversed(v)) for k, v in raw.items()}
            conn = build(case, shuffled)
            try:
                assert_rows(fact_rows(conn), expected_rows)
            finally:
                conn.close()
        check('arrival-order-does-not-select-source-version', 'replay', reordered)

        def bad_input(label, change):
            mutated = deepcopy(raw)
            change(mutated)
            try:
                validate_raw(mutated)
            except FixtureContractError as error:
                return {'mutation': label, 'caught': True, 'reason': str(error)}
            raise AssertionError('Invalid source contract accepted')
        check('reject-conflicting-version', 'negative_controls', lambda: bad_input('conflicting CDC payload',
            lambda d: d['invoice_cdc'].append(dict(d['invoice_cdc'][0], gross_cents='99999', arrival_seq=1000))))
        check('reject-currency-mismatch', 'negative_controls', lambda: bad_input('cross currency ledger',
            lambda d: d['payment_cdc'].append(dict(d['payment_cdc'][0], entry_id='PX', currency='EUR'))))
        check('reject-overlapping-history', 'negative_controls', lambda: bad_input('overlapping history',
            lambda d: d['customer_history'].append(dict(d['customer_history'][0], valid_to=None))))
        check('reject-invalid-amount', 'negative_controls', lambda: bad_input('non numeric cents',
            lambda d: d['invoice_cdc'][0].update(gross_cents='not-money')))

        def mutation(label, change, *, report_query=False, direct=False, schema=False, dashboard=False):
            with tempfile.TemporaryDirectory(prefix='dma-mutant-') as directory:
                mutant = Path(directory).resolve()
                shutil.copytree(case / 'input', mutant / 'input')
                shutil.copytree(case / 'target', mutant / 'target')
                change(mutant)
                conn = None
                try:
                    if schema:
                        catalogue_context(mutant, mutant / 'verification', snapshot)
                    elif dashboard:
                        assert_contract(report_contract(describe_omni(mutant / 'target/omni')), plan['report_contract'])
                    else:
                        conn = build(mutant)
                        got = query_rows(conn, compile_omni(mutant / 'target/omni', baseline['parameters'],
                            apply_dashboard_filters=not direct)) if report_query else fact_rows(conn)
                        assert_rows(got, baseline['rows'] if report_query else expected_rows)
                except (AssertionError, FixtureContractError, SemanticCompileError) as error:
                    return {'mutation': label, 'caught': True, 'reason': str(error)}
                finally:
                    if conn is not None:
                        conn.close()
                raise AssertionError('Deliberately wrong candidate survived')

        def rewrite_sql(root, name, transform):
            path = root / 'target/snowflake' / name
            ast = sqlglot.parse_one(path.read_text(), read='snowflake')
            if not transform(ast):
                raise RuntimeError('Mutation did not find its intended expression')
            path.write_text(ast.sql(dialect='snowflake', pretty=True) + ';\n')
        def remove_predicate(ast, predicate):
            found = False
            for node in list(ast.walk()):
                if predicate(node):
                    node.replace(exp.true()); found = True
            return found
        check('kill-missing-tenant-join', 'negative_controls', lambda: mutation('missing payment tenant join',
            lambda r: rewrite_sql(r, '21_gold_fct_invoices.sql', lambda a: remove_predicate(a,
                lambda n: isinstance(n, exp.EQ) and n.sql().lower() == 'i.tenant_id = p.tenant_id'))))
        check('kill-missing-temporal-join', 'negative_controls', lambda: mutation('missing temporal relationship',
            lambda r: rewrite_sql(r, '21_gold_fct_invoices.sql', lambda a: remove_predicate(a,
                lambda n: isinstance(n, (exp.GTE, exp.LT)) and 'h.valid_' in n.sql().lower()))))
        def double_credit(ast):
            for alias in ast.find_all(exp.Alias):
                if alias.alias == 'net_cents':
                    alias.set('this', exp.Sub(this=alias.this.copy(), expression=sqlglot.parse_one('COALESCE(c.credit_cents,0)',read='snowflake')))
                    return True
            return False
        check('kill-double-credit', 'negative_controls', lambda: mutation('credit subtracted twice',
            lambda r: rewrite_sql(r, '21_gold_fct_invoices.sql', double_credit)))
        def arrival_first(ast):
            for order in ast.find_all(exp.Order):
                order.set('expressions', list(reversed(order.expressions))); return True
            return False
        check('kill-arrival-order-cdc', 'negative_controls', lambda: mutation('arrival replaces source order',
            lambda r: rewrite_sql(r, '10_silver_invoice.sql', arrival_first)))
        def early_delete(ast):
            for cte in ast.find_all(exp.CTE):
                if cte.alias == 'payment_versions':
                    cte.this.set('where', exp.Where(this=sqlglot.parse_one("op <> 'DELETE'",read='snowflake'))); return True
            return False
        check('kill-early-delete-filter', 'negative_controls', lambda: mutation('deletes filtered before version ranking',
            lambda r: rewrite_sql(r, '11_silver_payment.sql', early_delete)))
        def edit_yaml(root, filename, edit):
            path = root / 'target/omni' / filename
            value = yaml.safe_load(path.read_text()); edit(value); path.write_text(yaml.safe_dump(value, sort_keys=False))
        check('kill-sum-of-row-ratios', 'negative_controls', lambda: mutation('sum of row ratios',
            lambda r: edit_yaml(r, 'invoices.view', lambda v: v['measures']['payment_rate'].update(
                sql='${invoices.paid_cents} / NULLIF(${invoices.net_cents},0)', aggregate_type='sum')), report_query=True))
        def remove_net_filter(v):
            names = [k for k,m in v['measures'].items() if m.get('aggregate_type') == 'sum' and 'net_cents' in m.get('sql','')]
            if len(names) != 1: raise RuntimeError('Expected one posted-net raw measure')
            v['measures'][names[0]].pop('filters')
        check('kill-lost-measure-filter', 'negative_controls', lambda: mutation('measure filter lost outside dashboard',
            lambda r: edit_yaml(r, 'invoices.view', remove_net_filter), report_query=True, direct=True))
        check('kill-omitted-access-policy', 'negative_controls', lambda: mutation('topic access filter removed',
            lambda r: edit_yaml(r, 'billing.topic', lambda v: v.pop('access_filters')), report_query=True))
        check('kill-quoted-lowercase-physical-column', 'negative_controls', lambda: mutation('quoted physical column changes case',
            lambda r: edit_yaml(r, 'invoices.view', lambda v: v['dimensions']['tenant_id'].update(sql='"tenant_id"')), report_query=True))
        def omit_column(root):
            path = root / 'input/catalogue/warehouse-catalogue.json'; value = json.loads(path.read_text())
            value['objects'][0]['columns'].pop(); write_json(path, value)
        check('kill-catalogue-normalization-omission', 'negative_controls', lambda: mutation('normalized catalogue omits raw column', omit_column, schema=True))
        def change_connection(root):
            path = root / 'input/repo/models/billing.model.lkml'
            path.write_text(path.read_text().replace('synthetic_billing_snowflake', 'different_warehouse_instance'))
        check('kill-connection-binding', 'negative_controls', lambda: mutation('Looker connection points at a different warehouse instance',
            change_connection, schema=True))
        def edit_report(root, edit):
            path = root / 'target/omni/report-context.json'
            value = json.loads(path.read_text()); edit(value); write_json(path, value)
        check('kill-dashboard-default-currency', 'negative_controls', lambda: mutation('USD default silently becomes EUR',
            lambda r: edit_report(r, lambda v: v['filters'][1].update(default_value='EUR')), dashboard=True))
        check('kill-dashboard-default-dates', 'negative_controls', lambda: mutation('September default silently becomes August',
            lambda r: edit_report(r, lambda v: v['filters'][0].update(default_value='2026/08/01 to 2026/08/31')), dashboard=True))
        check('kill-dashboard-missing-measure', 'negative_controls', lambda: mutation('paid measure omitted from report',
            lambda r: edit_report(r, lambda v: v['element']['fields'].remove('invoices.paid_cents_sum')), dashboard=True))

        report['raw_counts'] = {k: len(v) for k,v in raw.items()}
        report['source_counts'] = {'assets': 4, 'ctes': len(graph['ctes']), 'dimensions':len(source_view['dimensions']),
                                   'measures': len(source_view['measures']), 'physical_inputs':len(graph['physical_inputs'])}
        report['target_counts'] = {'facts': connection.execute('SELECT COUNT(*) FROM DMA_SIM.GOLD.FCT_INVOICES').fetchone()[0],
                                   'dimension_rows': connection.execute('SELECT COUNT(*) FROM DMA_SIM.GOLD.DIM_CUSTOMERS').fetchone()[0],
                                   'report_scenarios':len(scenarios),
                                   'report_result_rows':sum(len(s['rows']) for s in scenarios)}
        write_json(output / 'report-comparisons.json', results)
        write_json(output / 'rendered-queries.json', queries)
        (output / 'executed-assertions.sql').write_text(
            '-- Synthetic Snowflake-dialect assertions executed locally through DuckDB.\n'
            '-- Each statement must return violations = 0. Native execution remains unverified.\n\n' +
            ';\n\n'.join(assertions) + ';\n')
        write_json(output / 'gold-rows.json', fact_rows(connection))
        report['artifact_hashes'] = {str(p.relative_to(case)):sha(p) for folder in ('input','target','expected')
                                   for p in (case/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        report['dialect_adapter'] = 'Snowflake SQLGlot -> DuckDB, strict unsupported errors; one explicit TO_CHAR timestamp format -> STRFTIME adapter.'
        boundaries.extend([
            {'id':'native-runtimes', 'detail':'No native Snowflake/Looker/Omni compilation, execution, roles or tenant validation.'},
            {'id':'code-replay', 'detail':'Regression replay parses source and emitted target artifacts; original multi-agent design/extraction is separately archived, not rerun by this command.'},
            {'id':'source-evidence', 'detail':'Source specialist retained runtime and binding gaps; integrated synthetic catalogue binding is separate evidence.'},
            {'id':'security', 'detail':'Local policy generation and tenant-key checks do not prove warehouse RLS or Omni runtime enforcement.'},
            {'id':'refresh', 'detail':'Rebuild/replay simulation is not a deployed incremental/CDC ingestion service.'},
            {'id':'presentation', 'detail':'Fixed-USD display corrected to selected-currency numeric display as a proposal; no rendered dashboard or native formatting parity.'},
        ])
        report['simulation_passed'] = coverage_complete(plan['required_test_ids'], checks)
    except Exception as error:
        report['failures'].append(type(error).__name__ + ': ' + str(error))
    finally:
        if connection is not None:
            connection.close()
        report['summary'] = {'executed':len(checks),'passed':sum(c['status']=='pass' for c in checks),
                             'failed':sum(c['status']=='fail' for c in checks),
                             'negative_controls_caught':sum(c['category']=='negative_controls' and c['status']=='pass' for c in checks)}
        write_json(output / 'e2e-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path(__file__).resolve().parents[1]/'examples/looker-omni-e2e')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.case, args.output)
    print(json.dumps({'simulation_passed':report['simulation_passed'], **report['summary'],
                      'failures':report['failures'], 'report':str(args.output.resolve()/'e2e-report.json')},indent=2))
    return 0 if report['simulation_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
