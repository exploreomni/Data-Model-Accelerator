"""Bounded Snowflake-to-DuckDB fixture execution; never a warehouse connector.

Source SQL is parsed as LookML and Snowflake SQL. Only this synthetic case's
declared in-memory relations and an explicit expression/function subset are
allowed. External access and extension installation/loading are disabled after
the trusted in-memory attachment. This guards the trusted synthetic regression
harness; it is not a security sandbox for arbitrary customer SQL or Python.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import duckdb
import lkml
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope


RAW = {
    'invoice_cdc': 'BILLING_INVOICE_CDC', 'payment_cdc': 'BILLING_PAYMENT_CDC',
    'credit_cdc': 'BILLING_CREDIT_CDC', 'customer_history': 'BILLING_CUSTOMER_HISTORY',
}
RAW_COLUMNS = {
    'invoice_cdc': ('tenant_id', 'invoice_id', 'customer_id', 'issued_at', 'gross_cents',
                    'discount_cents', 'status', 'currency', 'source_seq', 'op', 'arrival_seq'),
    'payment_cdc': ('tenant_id', 'entry_id', 'invoice_id', 'amount_cents', 'status',
                    'currency', 'source_seq', 'op', 'arrival_seq'),
    'credit_cdc': ('tenant_id', 'entry_id', 'invoice_id', 'amount_cents', 'status',
                   'currency', 'source_seq', 'op', 'arrival_seq'),
    'customer_history': ('tenant_id', 'customer_id', 'valid_from', 'valid_to', 'segment'),
}
FACT_COLUMNS = ['tenant_id', 'invoice_id', 'customer_id', 'issued_at', 'invoice_date',
                'currency', 'status', 'gross_cents', 'discount_cents', 'credit_cents',
                'net_cents', 'paid_cents']
FIXTURE_CONNECTION = 'synthetic_billing_snowflake'
FIXTURE_PLATFORM_INSTANCE = 'synthetic-snowflake-account'
RAW_RELATIONS = {('DMA_SIM', 'BRONZE', name) for name in RAW.values()}
ALLOWED_RELATIONS = RAW_RELATIONS | {
    ('DMA_SIM', 'SILVER', name) for name in (
        'BILLING_INVOICES', 'BILLING_PAYMENTS', 'BILLING_CREDITS', 'BILLING_CUSTOMER_HISTORY')
} | {('DMA_SIM', 'GOLD', name) for name in ('FCT_INVOICES', 'DIM_CUSTOMERS')}
_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class FixtureContractError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_source(repo):
    repo = Path(repo)
    model = lkml.load((repo / 'models/billing.model.lkml').read_text())
    if model.get('connection') != FIXTURE_CONNECTION:
        raise FixtureContractError('Looker connection must match the fixed synthetic_billing_snowflake fixture binding')
    parsed = lkml.load((repo / 'views/invoice_chaos.view.lkml').read_text())
    if len(parsed.get('views', [])) != 1:
        raise FixtureContractError('The bounded case requires exactly one source view')
    view = parsed['views'][0]
    source_sql = view['derived_table']['sql']
    if any(marker in source_sql for marker in ('{%', '${', '{{')):
        raise FixtureContractError('Dynamic derived-table SQL is not supported by this fixture')
    ast = _validated_ast(source_sql, allowed_relations=RAW_RELATIONS)
    if not isinstance(ast, exp.Select):
        raise FixtureContractError('Derived table must be one SELECT')
    refs = sorted({(t.catalog.upper(), t.db.upper(), t.name.upper())
                   for t in ast.find_all(exp.Table) if t.catalog or t.db})
    if not refs or not set(refs) <= RAW_RELATIONS:
        raise FixtureContractError('Source references objects outside the synthetic raw scope')
    ctes = [{'name': c.alias, 'sql': c.this.sql(dialect='snowflake'),
             'dependencies': sorted({t.name for t in c.this.find_all(exp.Table)})}
            for c in ast.args.get('with_', exp.With()).expressions]
    return view, source_sql, {'physical_inputs': refs, 'ctes': ctes,
                              'source_connection': FIXTURE_CONNECTION,
                              'connection_binding': {
                                  'connection': FIXTURE_CONNECTION,
                                  'platform_instance': FIXTURE_PLATFORM_INSTANCE,
                                  'catalog': 'DMA_SIM', 'schema': 'BRONZE',
                                  'evidence': 'Fixed synthetic fixture identity; no live account connection was tested.'},
                              'dimensions': view.get('dimensions', []),
                              'measures': view.get('measures', [])}


def validate_raw(data):
    """Input contract assertions; expected metric computation lives elsewhere."""
    if set(data) != set(RAW):
        raise FixtureContractError('Raw object inventory differs from declared fixture')
    for stream, columns in RAW_COLUMNS.items():
        if not isinstance(data[stream], list) or not data[stream] or any(
                not isinstance(row, dict) or set(row) != set(columns) for row in data[stream]):
            raise FixtureContractError('Raw rows must use the exact nonempty declared column inventory: ' + stream)
    latest = {}
    replay_count = 0
    for stream in ('invoice_cdc', 'payment_cdc', 'credit_cdc'):
        versions, selected = {}, {}
        key_name = 'invoice_id' if stream == 'invoice_cdc' else 'entry_id'
        for row in data[stream]:
            for key in ('tenant_id', key_name, 'invoice_id'):
                if not isinstance(row.get(key), str) or not re.fullmatch(r'[A-Za-z0-9]+', row[key]):
                    raise FixtureContractError('Invalid scoped source identity')
            if type(row.get('source_seq')) is not int or row['source_seq'] < 1:
                raise FixtureContractError('Invalid source ordering')
            if row.get('op') not in ('UPSERT', 'DELETE'):
                raise FixtureContractError('Unknown CDC operation')
            amounts = ('gross_cents', 'discount_cents') if stream == 'invoice_cdc' else ('amount_cents',)
            for field in amounts:
                if field == 'discount_cents' and row[field] is None:
                    continue
                if not isinstance(row[field], str) or not re.fullmatch(r'-?\d+', row[field]):
                    raise FixtureContractError('Amount is not exact integer cents')
            identity = (row['tenant_id'], row[key_name])
            version = (*identity, row['source_seq'])
            payload = {k: v for k, v in row.items() if k != 'arrival_seq'}
            if version in versions and versions[version] != payload:
                raise FixtureContractError('Conflicting payload for the same source version')
            replay_count += version in versions
            versions[version] = payload
            if identity not in selected or row['source_seq'] > selected[identity]['source_seq']:
                selected[identity] = row
        latest[stream] = {k: r for k, r in selected.items() if r['op'] != 'DELETE'}
    invoices = latest['invoice_cdc']
    for stream in ('payment_cdc', 'credit_cdc'):
        for row in latest[stream].values():
            if row['status'].strip().lower() != 'posted':
                continue
            parent = invoices.get((row['tenant_id'], row['invoice_id']))
            if parent is None:
                raise FixtureContractError('Posted ledger has no current scoped invoice')
            if parent['currency'] != row['currency']:
                raise FixtureContractError('Ledger/invoice currency mismatch')
    histories, history_records = {}, set()
    history_replay_count = 0
    for row in data['customer_history']:
        # Deduplicate complete payloads only. A different segment or any other
        # differing field on an overlapping interval remains a conflict.
        record = json.dumps(row, sort_keys=True, separators=(',', ':'))
        if record in history_records:
            history_replay_count += 1
            continue
        history_records.add(record)
        start = datetime.fromisoformat(row['valid_from'])
        end = datetime.fromisoformat(row['valid_to']) if row['valid_to'] else datetime.max
        if start >= end:
            raise FixtureContractError('Invalid history interval')
        histories.setdefault((row['tenant_id'], row['customer_id']), []).append((start, end))
    for intervals in histories.values():
        ordered = sorted(intervals)
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
            raise FixtureContractError('Overlapping customer history')
    return {'raw_rows': {k: len(v) for k, v in data.items()},
            'replayed_versions': replay_count, 'replayed_history_rows': history_replay_count,
            'distinct_history_rows': len(history_records), 'current_invoices': len(invoices)}


def catalogue_context(case, output, source_snapshot):
    """Generate a fresh SYNTHETIC metadata snapshot; never retimestamp a live export."""
    case, output = Path(case), Path(output)
    original = case / 'input/catalogue/warehouse-catalogue.json'
    catalogue = json.loads(original.read_text())
    if catalogue['origin'] != 'synthetic':
        raise FixtureContractError('This simulator only regenerates synthetic catalogue evidence')
    if catalogue.get('provider') != 'snowflake' or catalogue.get('context', {}).get('platform_instance') != FIXTURE_PLATFORM_INSTANCE:
        raise FixtureContractError('Catalogue platform_instance does not match the fixed synthetic Looker connection binding')
    scope = catalogue.get('context', {}).get('scope', [])
    if len(scope) != 1 or (scope[0].get('catalog'), scope[0].get('schema')) != ('DMA_SIM', 'BRONZE'):
        raise FixtureContractError('Catalogue scope must be the fixed DMA_SIM.BRONZE fixture namespace')
    data = json.loads((case / 'input/raw-data.json').read_text())
    _, _, graph = load_source(case / 'input/repo')
    objects = {o['identity']['name']: o for o in catalogue['objects']}
    if set(objects) != set(RAW.values()):
        raise FixtureContractError('Normalized catalogue omits or adds raw objects')
    if any((o['identity'].get('catalog'), o['identity'].get('schema'), o['identity'].get('name')) not in RAW_RELATIONS
           for o in catalogue['objects']):
        raise FixtureContractError('Normalized catalogue object namespace differs from the source connection binding')
    native_objects = json.loads((original.parent / 'exports/objects.json').read_text())['rows']
    native_columns = json.loads((original.parent / 'exports/columns.json').read_text())['rows']
    if {r['TABLE_NAME'] for r in native_objects} != set(objects):
        raise FixtureContractError('Native object export differs from normalized catalogue')
    if any((r.get('TABLE_CATALOG'), r.get('TABLE_SCHEMA'), r.get('TABLE_NAME')) not in RAW_RELATIONS
           for r in native_objects + native_columns):
        raise FixtureContractError('Native metadata namespace differs from the source connection binding')
    for stream, table in RAW.items():
        actual = {k.upper() for k in data[stream][0]}
        columns = {tuple(c['path']): c for c in objects[table]['columns']}
        native = {(r['COLUMN_NAME'],): r for r in native_columns if r['TABLE_NAME'] == table}
        if set(columns) != {(k,) for k in actual} or set(columns) != set(native):
            raise FixtureContractError('Raw rows, native column export and normalized columns disagree')
        for key, column in columns.items():
            row = native[key]
            if row['DATA_TYPE'] != column['data_type'] or (row['IS_NULLABLE'] == 'YES') != column['nullable']:
                raise FixtureContractError('Normalized type/nullability differs from native metadata')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'exports').mkdir(exist_ok=True)
    for extraction in catalogue['extractions']:
        relative = Path(extraction['artifact_path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise FixtureContractError('Metadata export path is unsafe')
        raw = (original.parent / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != extraction['sha256']:
            raise FixtureContractError('Synthetic metadata receipt changed')
        (output / relative).write_bytes(raw)
    catalogue['captured_at'] = datetime.now(timezone.utc).isoformat()
    path = output / 'warehouse-catalogue.json'
    path.write_text(json.dumps(catalogue, indent=2) + '\n')
    references = []
    for catalog, schema, name in graph['physical_inputs']:
        obj = objects[name]
        references.append({'reference_id': '.'.join((catalog, schema, name)),
            'source_reference': '.'.join((catalog, schema, name)), 'status': 'resolved',
            'object_id': obj['object_id'], 'column_paths': [c['path'] for c in obj['columns']],
            'namespace': {'platform_instance': catalogue['context']['platform_instance'],
                          'catalog': catalog, 'schema': schema},
            'evidence': 'Native Snowflake SQL AST physical input; source SELECT stars expanded against verified synthetic raw schema.'})
    bindings = {'schema_version': 1, 'kind': 'warehouse_catalogue_bindings',
                'catalogue_sha256': sha(path), 'source_snapshot_sha256': source_snapshot,
                'expected_reference_ids': [r['reference_id'] for r in references], 'references': references}
    binding_path = output / 'catalogue-bindings.json'
    binding_path.write_text(json.dumps(bindings, indent=2) + '\n')
    return path, binding_path, graph


def _physical_relation(table, allowed_relations):
    if not isinstance(table, exp.Table) or not isinstance(table.this, exp.Identifier):
        raise FixtureContractError('Function/file relations are outside the declared fixture scope')
    parts = (table.args.get('catalog'), table.args.get('db'), table.this)
    if any(not isinstance(part, exp.Identifier) or not _IDENTIFIER.fullmatch(part.name) for part in parts):
        raise FixtureContractError('Physical relations must be fully qualified fixture identifiers, never paths or unqualified tables')
    if any(part.args.get('quoted') and part.name != part.name.upper() for part in parts):
        raise FixtureContractError('Quoted physical relation identifiers must match uppercase Snowflake fixture names')
    identity = tuple(part.name.upper() for part in parts)
    if identity not in allowed_relations:
        raise FixtureContractError('Physical relation is outside the declared fixture scope: ' + '.'.join(identity))


def _create_target(ast):
    """Validate the only DDL forms in this fixture; return its target node."""
    for key, value in ast.args.items():
        if value and key not in {'this', 'kind', 'expression', 'exists', 'replace'}:
            raise FixtureContractError('Unsupported CREATE option: ' + key)
    kind = ast.args.get('kind')
    target = ast.this.this if isinstance(ast.this, exp.Schema) else ast.this
    if not isinstance(target, exp.Table):
        raise FixtureContractError('CREATE requires a declared fixture target')
    if kind == 'DATABASE':
        if target.name != 'DMA_SIM' or target.db or target.catalog or ast.args.get('expression') is not None:
            raise FixtureContractError('CREATE DATABASE target must be the preattached DMA_SIM fixture')
    elif kind == 'SCHEMA':
        if target.catalog != 'DMA_SIM' or target.db not in {'BRONZE', 'SILVER', 'GOLD'} or target.name or ast.args.get('expression') is not None:
            raise FixtureContractError('CREATE SCHEMA target must be DMA_SIM.BRONZE, SILVER, or GOLD')
    elif kind == 'TABLE':
        _physical_relation(target, ALLOWED_RELATIONS)
        query = ast.args.get('expression')
        if query is not None and not isinstance(query, (exp.Select, exp.Union)):
            raise FixtureContractError('CREATE TABLE AS requires a supported SELECT/UNION query')
        if query is None and not isinstance(ast.this, exp.Schema):
            raise FixtureContractError('CREATE TABLE needs explicit fixture columns or a SELECT query')
    else:
        raise FixtureContractError('Only declared fixture DATABASE/SCHEMA/TABLE creation is supported')
    return target


def _validated_ast(sql, *, allowed_relations=ALLOWED_RELATIONS):
    try:
        expressions = sqlglot.parse(sql, read='snowflake', error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as error:
        raise FixtureContractError('Fixture SQL could not be parsed: ' + str(error)) from error
    if len(expressions) != 1 or expressions[0] is None:
        raise FixtureContractError('Execute exactly one parsed fixture statement at a time')
    ast = expressions[0]
    if not isinstance(ast, (exp.Select, exp.Union, exp.Create)):
        raise FixtureContractError('Only reviewed fixture SELECT/CREATE statements are supported')
    # SQLGlot recognizes READ_CSV and other external readers as named AST nodes,
    # not Anonymous functions. An explicit positive subset covers both forms.
    functions = {exp.And, exp.Or, exp.Cast, exp.Coalesce, exp.ConvertTimezone,
                 exp.Lower, exp.MD5, exp.RowNumber, exp.Sum, exp.ToChar, exp.Trim,
                 exp.Count, exp.Nullif, exp.Case, exp.If}
    nodes = functions | {
        exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Neg, exp.DPipe, exp.Alias,
        exp.CTE, exp.Column, exp.ColumnDef, exp.Create, exp.DataType,
        exp.DataTypeParam, exp.Distinct, exp.EQ, exp.NEQ, exp.GT, exp.GTE,
        exp.LT, exp.LTE, exp.From, exp.Group, exp.Having, exp.Identifier,
        exp.Is, exp.Join, exp.Limit, exp.Literal, exp.Boolean, exp.Not,
        exp.Null, exp.Order, exp.Ordered, exp.Paren, exp.Schema, exp.Select,
        exp.Star, exp.Subquery, exp.Table, exp.TableAlias, exp.Union,
        exp.Where, exp.Window, exp.With,
    }
    for node in ast.walk():
        if isinstance(node, exp.Func) and type(node) not in functions:
            raise FixtureContractError('SQL function is outside the fixture subset: ' + type(node).__name__)
        if type(node) not in nodes:
            raise FixtureContractError('SQL construct is outside the fixture subset: ' + type(node).__name__)
        if isinstance(node, exp.Identifier) and not _IDENTIFIER.fullmatch(node.name):
            raise FixtureContractError('Identifier paths and nonfixture identifier syntax are unsupported')
        if isinstance(node, exp.With):
            aliases = [cte.alias for cte in node.expressions]
            if node.args.get('recursive') or len(aliases) != len(set(aliases)):
                raise FixtureContractError('Recursive or duplicate CTE definitions are unsupported')
        if isinstance(node, exp.DataType) and node.this.value not in {'VARCHAR', 'TEXT', 'DECIMAL', 'BIGINT', 'INT', 'DOUBLE', 'TIMESTAMPNTZ', 'DATE'}:
            raise FixtureContractError('Data type is outside the fixture subset: ' + str(node.this))
    create_target = _create_target(ast) if isinstance(ast, exp.Create) else None
    classified = {id(create_target)} if create_target is not None else set()
    try:
        for scope in traverse_scope(ast):
            for table in scope.tables:
                if not isinstance(table.this, exp.Identifier):
                    raise FixtureContractError('Table functions and file relations are not allowed')
            for _, (node, source) in scope.selected_sources.items():
                if isinstance(source, exp.Table):
                    _physical_relation(source, allowed_relations)
                    classified.add(id(source))
                elif isinstance(source, Scope):
                    if isinstance(node, exp.Table):
                        if node.catalog or node.db:
                            raise FixtureContractError('CTE references must be unqualified')
                        classified.add(id(node))
                else:
                    raise FixtureContractError('Unsupported SQL relation binding')
    except FixtureContractError:
        raise
    except Exception as error:
        raise FixtureContractError('Could not resolve fixture relation scope: ' + str(error)) from error
    if any(id(table) not in classified for table in ast.find_all(exp.Table)):
        raise FixtureContractError('A SQL relation was not bound to a declared fixture object or visible CTE')
    return ast


def to_duckdb(sql):
    ast = _validated_ast(sql)
    if isinstance(ast, exp.Create) and ast.args.get('kind') == 'DATABASE':
        raise FixtureContractError('Fixture database attachment is trusted setup, never translated source SQL')
    for node in list(ast.find_all(exp.ToChar)):
        fmt = node.args.get('format')
        if not isinstance(fmt, exp.Literal) or fmt.this != 'YYYY-MM-DD HH24:MI:SS':
            raise FixtureContractError('Unsupported Snowflake timestamp display adapter')
        node.replace(exp.TimeToStr(this=node.this.copy(), format=exp.Literal.string('%Y-%m-%d %H:%M:%S')))
    return ast.sql(dialect='duckdb', unsupported_level=sqlglot.ErrorLevel.RAISE)


def execute_models(connection, target, *, bronze=True):
    for path in sorted(Path(target).glob('*.sql')):
        if not bronze and path.name.startswith('00_'):
            continue
        for ast in sqlglot.parse(path.read_text(), read='snowflake', error_level=sqlglot.ErrorLevel.RAISE):
            ast = _validated_ast(ast.sql(dialect='snowflake'))
            if not isinstance(ast, exp.Create):
                raise FixtureContractError('Warehouse fixture script must contain only CREATE statements')
            if ast.args.get('kind') == 'DATABASE':
                continue
            connection.execute(to_duckdb(ast.sql(dialect='snowflake')))


def add_raw(connection, data):
    for stream, table in RAW.items():
        rows = data[stream]
        fields = RAW_COLUMNS[stream]
        connection.executemany('INSERT INTO DMA_SIM.BRONZE.' + table + ' (' + ','.join(fields) + ') VALUES ('
                               + ','.join('?' for _ in fields) + ')', [[r[k] for k in fields] for r in rows])


def build(case, data=None):
    case = Path(case)
    data = data if data is not None else json.loads((case / 'input/raw-data.json').read_text())
    validate_raw(data)
    # Fixed connection identity is part of the source contract even when a caller
    # uses build() without first requesting catalogue bindings.
    load_source(case / 'input/repo')
    connection = duckdb.connect(':memory:', config={
        'autoinstall_known_extensions': 'false', 'autoload_known_extensions': 'false'})
    connection.execute("ATTACH ':memory:' AS DMA_SIM")
    connection.execute('SET enable_external_access=false')
    try:
        # Create bronze first, then load events, then materialize silver/gold.
        for ast in sqlglot.parse((case / 'target/snowflake/00_bronze.sql').read_text(), read='snowflake'):
            ast = _validated_ast(ast.sql(dialect='snowflake'))
            if not isinstance(ast, exp.Create):
                raise FixtureContractError('Bronze fixture script must contain only CREATE statements')
            if ast.args.get('kind') != 'DATABASE':
                connection.execute(to_duckdb(ast.sql(dialect='snowflake')))
        add_raw(connection, data)
        execute_models(connection, case / 'target/snowflake', bronze=False)
        return connection
    except Exception:
        connection.close()
        raise


def query_rows(connection, sql):
    if not isinstance(_validated_ast(sql), (exp.Select, exp.Union)):
        raise FixtureContractError('The query interface only permits read-only SELECT/UNION statements')
    cursor = connection.execute(to_duckdb(sql))
    return [dict(zip([d[0].lower() for d in cursor.description], row)) for row in cursor.fetchall()]


def fact_rows(connection):
    fields = ','.join('i.' + c for c in FACT_COLUMNS)
    return query_rows(connection, 'SELECT ' + fields + ', c.segment FROM DMA_SIM.GOLD.FCT_INVOICES i '
                      'LEFT JOIN DMA_SIM.GOLD.DIM_CUSTOMERS c ON i.customer_key = c.customer_key '
                      'AND i.tenant_id = c.tenant_id ORDER BY i.tenant_id,i.invoice_id')
