"""Pure, bounded SQL rendering for reviewed warehouse metadata operations.

No I/O, execution, approval, permission inference, or SQL/Jinja interpretation.
One return value is one statement, even when data contains semicolons. Execute
through a native single-statement transport, never a shell, notebook, template,
or naive semicolon splitter. Read results are permission-filtered observations:
empty results cannot establish absence or complete metadata visibility.

Primary contracts checked 2026-09-30 (live destination qualification separate):
https://docs.snowflake.com/en/sql-reference/sql/comment
https://docs.snowflake.com/en/sql-reference/sql/alter-table-column
https://docs.snowflake.com/en/sql-reference/sql/alter-view
https://docs.snowflake.com/en/sql-reference/functions/tag_references
https://docs.snowflake.com/en/sql-reference/functions/tag_references_all_columns
https://docs.snowflake.com/en/sql-reference/data-types-text
https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-comment
https://docs.databricks.com/aws/en/database-objects/tags
https://docs.databricks.com/aws/en/sql/language-manual/data-types/string-type
https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language
https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/lexical
https://docs.cloud.google.com/bigquery/docs/information-schema-column-field-paths
https://docs.aws.amazon.com/redshift/latest/dg/r_COMMENT.html
https://docs.aws.amazon.com/redshift/latest/dg/r_QUOTE_LITERAL.html
https://docs.aws.amazon.com/redshift/latest/dg/c_join_PG.html
https://clickhouse.com/docs/reference/statements/alter/comment
https://clickhouse.com/docs/reference/statements/alter/column
https://clickhouse.com/docs/reference/syntax
https://duckdb.org/docs/current/sql/statements/comment_on
https://duckdb.org/docs/current/sql/meta/duckdb_table_functions
"""

WAREHOUSES = {'snowflake', 'databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck'}


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _string(value, label, maximum=16000):
    _need(type(value) is str and len(value) <= maximum, 'Invalid ' + label)
    _need(not any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value),
          'Unsupported control/Unicode character in ' + label)
    return value


def _identifier(value):
    _string(value, 'identifier', 256)
    _need(bool(value) and value == value.strip() and not any(ord(c) < 32 for c in value), 'Invalid identifier')
    return value


def _quote(warehouse, value):
    value = _identifier(value)
    if warehouse == 'databricks':
        return '`' + value.replace('`', '``') + '`'
    if warehouse == 'bigquery':
        # GoogleSQL supports escaped quoted identifiers, but the pinned static
        # lexer does not model them. Do not claim validation for that subgrammar.
        _need('`' not in value and '\\' not in value, 'BigQuery escaped identifiers require separate native qualification')
        return '`' + value + '`'
    if warehouse == 'clickhouse':
        return '`' + value.replace('\\', '\\\\').replace('`', '\\`') + '`'
    return '"' + value.replace('"', '""') + '"'


def _literal(warehouse, value):
    if value is None:
        return 'NULL'
    value = _string(value, 'metadata text')
    if warehouse == 'motherduck':
        return "'" + value.replace("'", "''") + "'"
    value = value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    value = value.replace("'", "\\'") if warehouse in ('databricks', 'bigquery') else value.replace("'", "''")
    return "'" + value + "'"


def _relation(warehouse, relation):
    _need(warehouse in WAREHOUSES, 'Unsupported warehouse')
    _need(type(relation) is dict and set(relation) == {'namespace', 'name', 'kind'}, 'Exact relation fields required')
    namespace = relation['namespace']
    _need(type(namespace) is list and len(namespace) == (1 if warehouse == 'clickhouse' else 2),
          'Exact native namespace components required')
    for part in namespace + [relation['name']]:
        _identifier(part)
        if warehouse == 'bigquery':
            _need('.' not in part, 'BigQuery namespace/relation components cannot contain path separators')
    _need(relation['kind'] in ('table', 'view'), 'External, ephemeral, late-binding and unqualified object kinds are unsupported')
    _need(warehouse != 'clickhouse' or relation['kind'] == 'table', 'ClickHouse view metadata is outside this renderer contract')
    parts = namespace + [relation['name']]
    if warehouse == 'redshift':
        parts = parts[1:]
    return '.'.join(_quote(warehouse, part) for part in parts)


def _column(warehouse, relation, column):
    if column is None:
        return None
    _need(type(column) is str, 'Nested field paths are unsupported; supply one exact top-level column name')
    _identifier(column)
    if warehouse in ('bigquery', 'clickhouse'):
        _need('.' not in column, 'Nested/dotted fields require a separately qualified route')
    _need(warehouse != 'motherduck' or relation['kind'] == 'table', 'MotherDuck view-column comments are unsupported')
    return _quote(warehouse, column)


def render_comment(warehouse, relation, column_or_None, value_or_None):
    """Render one exact comment set/removal; unsupported removal fails explicitly.

    Databricks COLUMN requires SQL/DBR 16.1+ and standard literal decoding;
    views use COMMENT ON TABLE and schema evolution may later replace comments.
    Redshift requires current_database() == namespace[0] immediately before use.
    ClickHouse is local-replica only; no implicit ON CLUSTER or replica claims.
    None represents exact native absence, never an implicit empty-string rewrite.
    """
    name = _relation(warehouse, relation)
    column = _column(warehouse, relation, column_or_None)
    kind = relation['kind'].upper()
    value = _literal(warehouse, value_or_None)
    if warehouse == 'bigquery':
        if value_or_None is not None and column is not None:
            _need(len(value_or_None) <= 1024, 'BigQuery column description exceeds 1024 characters')
        clause = ' ALTER COLUMN ' + column if column is not None else ''
        return 'ALTER ' + kind + ' ' + name + clause + ' SET OPTIONS (description = ' + value + ');'
    if warehouse == 'clickhouse':
        _need(value_or_None is not None, 'ClickHouse absence is empty text; exact NULL restoration is unsupported')
        clause = 'COMMENT COLUMN ' + column if column is not None else 'MODIFY COMMENT'
        return 'ALTER TABLE ' + name + ' ' + clause + ' ' + value + ';'
    if warehouse == 'snowflake' and value_or_None is None:
        if column is None:
            return 'ALTER ' + kind + ' ' + name + ' UNSET COMMENT;'
        _need(kind == 'TABLE', 'Snowflake view-column exact NULL restoration is unsupported')
        return 'ALTER TABLE ' + name + ' MODIFY COLUMN ' + column + ' UNSET COMMENT;'
    if column is not None:
        target = 'COLUMN ' + name + '.' + column
    else:
        target = ('TABLE' if warehouse == 'databricks' else kind) + ' ' + name
    return 'COMMENT ON ' + target + ' IS ' + value + ';'


def render_tag(warehouse, relation, column_or_None, tag):
    """One custom Snowflake/UC assignment. No creation, removal or policy changes.

    Supplied policy evidence is a contract field, not authenticated approval.
    Native permission, existing assignments, limits, inherited state and policy
    associations must be independently observed before executing this candidate.
    """
    name = _relation(warehouse, relation)
    column = _column(warehouse, relation, column_or_None)
    _need(warehouse in ('snowflake', 'databricks'), 'Governed native tag emission is unsupported for this warehouse')
    _need(type(tag) is dict and set(tag) == {'id', 'name', 'value', 'policy_effects', 'evidence_reference'},
          'Exact tag contract fields required')
    _identifier(tag['id'])
    _need(type(tag['name']) is list and len(tag['name']) == (3 if warehouse == 'snowflake' else 1), 'Exact native tag namespace required')
    for part in tag['name']:
        _identifier(part)
    _string(tag['value'], 'tag value', 256)
    _need(tag['value'].strip() != '', 'Tag value must be explicit and nonempty')
    _need(tag['policy_effects'] == 'none_verified' and type(tag['evidence_reference']) is str and bool(tag['evidence_reference'].strip()),
          'Informational tag assignment requires supplied policy preflight evidence')
    if warehouse == 'snowflake':
        _need(tag['name'][0].upper() != 'SNOWFLAKE', 'Snowflake system/Preview tag assignments require a separately qualified route')
        tag_name = '.'.join(_quote(warehouse, part) for part in tag['name'])
        clause = ' MODIFY COLUMN ' + column if column is not None else ''
        return 'ALTER ' + relation['kind'].upper() + ' ' + name + clause + ' SET TAG ' + tag_name + ' = ' + _literal(warehouse, tag['value']) + ';'
    _need(column is None or relation['kind'] == 'table', 'Databricks view-column tagging is outside this renderer contract')
    _need(not any(c in tag['name'][0] for c in '.,-=/:'), 'Databricks tag key contains a prohibited character')
    _need(tag['value'] == tag['value'].strip(), 'Databricks tag value cannot have leading/trailing spaces')
    clause = ' ALTER COLUMN ' + column if column is not None else ''
    return ('ALTER ' + relation['kind'].upper() + ' ' + name + clause + ' SET TAGS ('
            + _literal(warehouse, tag['name'][0]) + ' = ' + _literal(warehouse, tag['value']) + ');')


def read_queries(warehouse, relation):
    """Enumerate a scoped relation, all actual columns, and supported native tags.

    No desired-column filter or expected-row count is accepted here. The caller
    must establish role visibility, result completeness, target identity, query
    success and freshness separately, and preserve missing/denied/unknown states.
    Query IDs are stable within a relation, not globally unique operation IDs.
    """
    name = _relation(warehouse, relation)
    namespace, table = relation['namespace'], relation['name']
    lit = lambda value: _literal(warehouse, value)
    quote = lambda value: _quote(warehouse, value)
    queries = []

    def add(identity, sql, purpose):
        queries.append({'id': identity, 'sql': sql + ';', 'purpose': purpose})

    if warehouse == 'snowflake':
        database, schema = namespace
        info = quote(database) + '."INFORMATION_SCHEMA".'
        where = 'TABLE_CATALOG = ' + lit(database) + ' AND TABLE_SCHEMA = ' + lit(schema) + ' AND TABLE_NAME = ' + lit(table)
        add('relation', 'SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, CREATED, LAST_DDL, COMMENT FROM ' + info + '"TABLES" WHERE ' + where,
            'Observe relation identity/type/comment and creation/DDL timestamps. These are incarnation candidates, not a qualified immutable object ID; visibility is permission-filtered.')
        add('columns', 'SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, DATA_TYPE, COMMENT FROM '
            + info + '"COLUMNS" WHERE ' + where + ' ORDER BY ORDINAL_POSITION', 'Independently enumerate every visible physical column and comment.')
        add('relation_tags', 'SELECT * FROM TABLE(' + info + 'TAG_REFERENCES(' + lit(name) + ", 'TABLE'))",
            'Observe object tags including inherited/apply-method state; TABLE domain also applies to views; empty is not visibility proof.')
        add('column_tags', 'SELECT * FROM TABLE(' + info + 'TAG_REFERENCES_ALL_COLUMNS(' + lit(name) + ", 'TABLE'))",
            'Observe all visible column tags including inherited/apply-method state; TABLE domain also applies to views.')
    elif warehouse == 'databricks':
        catalog, schema = namespace
        where = 'table_catalog = ' + lit(catalog) + ' AND table_schema = ' + lit(schema) + ' AND table_name = ' + lit(table)
        add('relation', 'SELECT table_catalog, table_schema, table_name, table_type, created, last_altered, comment FROM system.information_schema.tables WHERE ' + where,
            'Observe Unity Catalog relation/comment and creation/change timestamps. Reliable incarnation must be qualified separately; a collector timestamp cannot replace it.')
        add('columns', 'SELECT table_catalog, table_schema, table_name, column_name, ordinal_position, full_data_type, comment FROM '
            + 'system.information_schema.columns WHERE ' + where + ' ORDER BY ordinal_position', 'Independently enumerate every visible top-level column and comment.')
        tags_where = 'catalog_name = ' + lit(catalog) + ' AND schema_name = ' + lit(schema) + ' AND table_name = ' + lit(table)
        add('relation_tags', 'SELECT catalog_name, schema_name, table_name, tag_name, tag_value FROM system.information_schema.table_tags WHERE ' + tags_where,
            'Observe explicit relation tag assignments; this is not an ABAC inheritance or policy evaluation.')
        add('column_tags', 'SELECT catalog_name, schema_name, table_name, column_name, tag_name, tag_value FROM system.information_schema.column_tags WHERE ' + tags_where,
            'Observe explicit tags on all visible columns; object tags do not imply column assignments.')
    elif warehouse == 'bigquery':
        project, dataset = namespace
        info = quote(project) + '.' + quote(dataset) + '.INFORMATION_SCHEMA.'
        where = 'table_catalog = ' + lit(project) + ' AND table_schema = ' + lit(dataset) + ' AND table_name = ' + lit(table)
        add('relation', 'SELECT t.table_catalog, t.table_schema, t.table_name, t.table_type, t.creation_time, o.option_value AS description FROM '
            + info + 'TABLES AS t LEFT JOIN ' + info + 'TABLE_OPTIONS AS o ON t.table_catalog = o.table_catalog '
            + "AND t.table_schema = o.table_schema AND t.table_name = o.table_name AND o.option_name = 'description'"
            + " WHERE t.table_catalog = " + lit(project) + ' AND t.table_schema = ' + lit(dataset) + ' AND t.table_name = ' + lit(table)
            , 'Observe relation, creation-time incarnation candidate and description option; reliable identity qualification and matching dataset location remain required.')
        add('columns', 'SELECT c.table_catalog, c.table_schema, c.table_name, c.column_name, c.ordinal_position, c.data_type, f.description, f.policy_tags, '
            + 'f.field_path AS observed_description_path FROM ' + info + 'COLUMNS AS c LEFT JOIN ' + info
            + 'COLUMN_FIELD_PATHS AS f ON c.table_catalog = f.table_catalog AND c.table_schema = f.table_schema AND c.table_name = f.table_name '
            + 'AND c.column_name = f.column_name AND f.field_path = c.column_name WHERE c.table_catalog = ' + lit(project)
            + ' AND c.table_schema = ' + lit(dataset) + ' AND c.table_name = ' + lit(table) + ' ORDER BY c.ordinal_position',
            'Enumerate all physical columns independently; a missing description path is unknown, not an absent comment.')
        add('nested_fields', 'SELECT table_catalog, table_schema, table_name, column_name, field_path, data_type, description, policy_tags FROM '
            + info + 'COLUMN_FIELD_PATHS WHERE ' + where + ' AND field_path != column_name ORDER BY field_path',
            'Observe nested-field coverage gaps and security policy tags; neither is automatically emitted by this renderer.')
    elif warehouse == 'redshift':
        database, schema = namespace
        add('current_database', 'SELECT current_database() AS database_name, ' + lit(database) + ' AS expected_database_name',
            'Mandatory preflight: current database must exactly equal the bound database before COMMENT execution.')
        joins = ' FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid'
        where = ' WHERE current_database() = ' + lit(database) + ' AND n.nspname = ' + lit(schema) + ' AND c.relname = ' + lit(table)
        add('relation', 'SELECT current_database() AS database_name, n.nspname AS schema_name, c.relname AS table_name, c.oid AS relation_oid, c.relkind, d.description'
            + joins + " LEFT JOIN pg_catalog.pg_description d ON d.objoid = c.oid AND d.objsubid = 0 AND d.classoid = 'pg_catalog.pg_class'::regclass"
            + where, 'Read current-database relation OID and comment without SVV truncation; OID reuse/lifetime requires independent incarnation qualification.')
        add('columns', 'SELECT current_database() AS database_name, n.nspname AS schema_name, c.relname AS table_name, a.attname AS column_name, '
            + 'a.attnum AS ordinal_position, ty.typname AS data_type, a.atttypmod AS type_modifier, a.atttypid AS data_type_id, d.description' + joins
            + ' JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid JOIN pg_catalog.pg_type ty ON ty.oid = a.atttypid'
            + ' LEFT JOIN pg_catalog.pg_description d ON d.objoid = c.oid '
            + "AND d.objsubid = a.attnum AND d.classoid = 'pg_catalog.pg_class'::regclass" + where
            + ' AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum', 'Enumerate all physical columns including uncommented ones; normalize native type name/modifier before comparison; external/late-binding columns excluded from writes.')
    elif warehouse == 'clickhouse':
        database = namespace[0]
        add('relation', 'SELECT database, name AS table_name, uuid, engine, metadata_modification_time, comment FROM system.tables WHERE database = ' + lit(database) + ' AND name = ' + lit(table),
            'Observe local-replica UUID/comment/engine; zero or unsupported UUID is unknown incarnation, and local visibility is not cluster-wide parity.')
        add('columns', 'SELECT database, table AS table_name, name AS column_name, position AS ordinal_position, type AS data_type, comment FROM '
            + 'system.columns WHERE database = ' + lit(database) + ' AND table = ' + lit(table) + ' ORDER BY position',
            'Independently enumerate every local-replica physical column and comment.')
    else:
        database, schema = namespace
        where = 'database_name = ' + lit(database) + ' AND schema_name = ' + lit(schema)
        function = 'duckdb_tables()' if relation['kind'] == 'table' else 'duckdb_views()'
        field = 'table_name' if relation['kind'] == 'table' else 'view_name'
        oid = 'table_oid' if relation['kind'] == 'table' else 'view_oid'
        add('relation', 'SELECT database_name, schema_name, ' + field + ', ' + oid + ', comment FROM ' + function + ' WHERE ' + where + ' AND ' + field + ' = ' + lit(table),
            'Observe attached database/schema/relation and internal OID; OID stability across sessions/restarts and remote MotherDuck identity require independent qualification.')
        add('columns', 'SELECT database_name, schema_name, table_name, column_name, column_index AS ordinal_position, data_type, comment FROM duckdb_columns() WHERE '
            + where + ' AND table_name = ' + lit(table) + ' ORDER BY column_index', 'Independently enumerate all visible columns; view-column writes remain unsupported.')
    return queries
