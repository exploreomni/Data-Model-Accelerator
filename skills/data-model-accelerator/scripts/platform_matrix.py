"""Versioned, non-executing platform capabilities; Python 3.9 standard library.

A route is a candidate-authoring/check recipe, never provider qualification.
No imports of vendor runtimes, credential resolution, I/O, or execution occurs.
Intake keeps framework and warehouse separate; dbt_platform is a hosting lookup.
"""
import copy
from typing import Any, Dict, List, Literal, TypedDict

MATRIX_VERSION = 1
RESEARCH_DATE = '2026-09-24'
SQLFLUFF_VERSION = '4.3.0'
WAREHOUSES = ('snowflake', 'databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck')
FRAMEWORKS = ('dbt', 'coalesce', 'native_sql')
DBT_PLATFORM_WAREHOUSES = ('snowflake', 'databricks', 'bigquery', 'redshift')
COALESCE_WAREHOUSES = ('snowflake', 'databricks', 'bigquery')


class CheckRecipe(TypedDict):
    id: str
    kind: str
    recipe: List[str]
    connection_required: bool
    cost: str
    side_effects: str
    coverage_gaps: List[str]
    documentation: str
    status: str
    runtime_constraint: str


class StaticLint(TypedDict):
    tool: Literal['sqlfluff']
    version: str
    dialect: str
    version_policy: str
    coverage_gaps: List[str]
    documentation: str


class Pairing(TypedDict):
    framework: str
    warehouse: str
    status: Literal['supported', 'conditional', 'unsupported']
    reason: str
    native_qualified: bool
    requirements: List[str]
    checks: List[CheckRecipe]
    documentation: List[str]


def _check(identity, kind, recipe, connection, cost, effects, gaps, docs,
           runtime='Pin and verify the selected native client/server capability.') -> CheckRecipe:
    return {'id': identity, 'kind': kind, 'recipe': recipe, 'connection_required': connection,
            'cost': cost, 'side_effects': effects, 'coverage_gaps': gaps,
            'documentation': docs, 'status': 'recipe_only', 'runtime_constraint': runtime}


_DBT_DOC = 'https://docs.getdbt.com/docs/supported-data-platforms'
_COA_DOC = 'https://docs.coalesce.io/docs/coa/version-733-and-above/coa-commands'
_COA_SETUP = 'https://docs.coalesce.io/docs/coalesce-ai/local-development/setup-guide'
_SQLFLUFF_DOC = 'https://docs.sqlfluff.com/en/stable/reference/dialects.html'

# Every profile has explicit identity and validation limits. Recipes contain
# reviewed placeholders, not executable descriptors or permission to connect.
_PROFILES = {
    'snowflake': {
        'label': 'Snowflake', 'dialect': 'snowflake',
        'requirements': ['account', 'role', 'warehouse', 'database', 'schema'],
        'identity': ['account', 'region', 'principal', 'active_roles', 'database', 'schema', 'query_id'],
        'source_markers': ['snowflake.yml', 'snowflake.yaml', 'snowflake connection type'],
        'namespace': 'database.schema.object; preserve quoted identifier case',
        'physical_design': ['table kind and constraint enforcement', 'clustering and warehouse sizing', 'VARIANT versus structured types'],
        'metadata_docs': ['https://docs.snowflake.com/en/sql-reference/info-schema'],
        'native_checks': [_check('snowflake_explain', 'native_plan', ['EXPLAIN USING JSON <eligible_statement>'], True,
            'Cloud Services compilation resources; no statement execution.', 'Compilation against the selected role and namespace.',
            ['Unsupported DDL and scripting need development execution.', 'No business/data or effective-access acceptance.'],
            'https://docs.snowflake.com/en/sql-reference/sql/explain')],
    },
    'databricks': {
        'label': 'Databricks', 'dialect': 'databricks',
        'requirements': ['workspace', 'runtime_or_sql_warehouse', 'catalog', 'schema'],
        'identity': ['workspace', 'metastore', 'principal', 'catalog', 'schema', 'runtime_or_sql_warehouse', 'statement_id'],
        'source_markers': ['databricks.yml bundle', 'databricks.yaml bundle', 'databricks connection type'],
        'namespace': 'catalog.schema.object; distinguish Unity Catalog from hive_metastore',
        'physical_design': ['Delta and table format', 'partitioning/clustering and runtime features', 'catalog grants and storage locations'],
        'metadata_docs': ['https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-information-schema'],
        'native_checks': [
            _check('databricks_explain', 'native_plan', ['EXPLAIN FORMATTED <eligible_query>'], True,
                'Requires a running authorized SQL warehouse or compute runtime.', 'Analyzes a query against the selected catalogue.',
                ['Does not execute or validate all DDL, jobs or data behavior.'],
                'https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-qry-explain'),
            _check('databricks_bundle_validate', 'framework_config', ['databricks', 'bundle', 'validate', '-t', '<target>', '--output', 'json'], True,
                'May contact the workspace; no transformation run is requested.', 'Validates bundle configuration and target resolution.',
                ['Does not validate every SQL statement or execute a job.'],
                'https://docs.databricks.com/aws/en/dev-tools/cli/bundle-commands'),
        ],
    },
    'bigquery': {
        'label': 'Google Cloud BigQuery', 'dialect': 'bigquery',
        'requirements': ['project', 'dataset', 'location', 'job_identity'],
        'identity': ['billing_project', 'principal', 'data_project', 'dataset', 'location', 'job_id'],
        'source_markers': ['dataform.json', 'workflow_settings.yaml', 'bigquery connection type'],
        'namespace': 'project.dataset.object; execute metadata jobs in the matching location',
        'physical_design': ['partition filters and clustering', 'nested/repeated fields', 'unenforced declared primary/foreign keys'],
        'metadata_docs': ['https://cloud.google.com/bigquery/docs/information-schema-intro'],
        'native_checks': [_check('bigquery_dry_run', 'native_dry_run',
            ['bq', '--project_id=<project>', '--location=<location>', 'query', '--use_legacy_sql=false', '--dry_run', '<query>'], True,
            'Dry runs do not use query slots or incur query charges; separate metadata queries can be billed.', 'Validation only for covered statement classes.',
            ['Multi-statement DDL stops after the first DDL.', 'CALL bodies, dynamic SQL and control flow limit coverage.'],
            'https://cloud.google.com/bigquery/docs/multi-statement-queries#dry-run_a_multi-statement_query')],
    },
    'redshift': {
        'label': 'Amazon Redshift', 'dialect': 'redshift',
        'requirements': ['region', 'cluster_or_workgroup', 'database', 'schema', 'principal'],
        'identity': ['aws_account', 'region', 'cluster_or_workgroup', 'principal', 'database', 'schema', 'statement_id'],
        'source_markers': ['redshift connection type'],
        'namespace': 'database.schema.object; preserve case configuration and datashare/external scope',
        'physical_design': ['DISTSTYLE/DISTKEY', 'SORTKEY and encoding', 'SUPER and external schemas', 'informational primary/foreign keys'],
        'metadata_docs': ['https://docs.aws.amazon.com/redshift/latest/dg/r_SVV_ALL_TABLES.html',
                          'https://docs.aws.amazon.com/redshift/latest/dg/r_SVV_ALL_COLUMNS.html'],
        'native_checks': [_check('redshift_explain', 'native_plan', ['EXPLAIN <eligible_statement>'], True,
            'Requires an authorized running cluster/workgroup; planning resources are not guaranteed free.', 'Plans eligible statements without executing them.',
            ['Selected query/DML and CTAS coverage; not arbitrary DDL.', 'Physical design and constraint declarations do not prove data behavior.'],
            'https://docs.aws.amazon.com/redshift/latest/dg/r_EXPLAIN.html')],
    },
    'clickhouse': {
        'label': 'ClickHouse', 'dialect': 'clickhouse',
        'requirements': ['endpoint', 'database', 'principal', 'server_version', 'cluster_scope'],
        'identity': ['endpoint', 'principal', 'database', 'server_version', 'cluster_scope', 'query_id'],
        'source_markers': ['clickhouse connection type'],
        'namespace': 'database.object; canonical schema __no_schema__ is a normalization marker, never a native namespace',
        'physical_design': ['engine and engine parameters', 'ORDER BY versus PRIMARY KEY', 'partition/TTL and replication', 'Nullable/LowCardinality and mutation behavior'],
        'metadata_docs': ['https://clickhouse.com/docs/reference/system-tables/tables',
                          'https://clickhouse.com/docs/reference/system-tables/columns'],
        'native_checks': [
            _check('clickhouse_format_syntax', 'native_syntax', ['clickhouse-format', '--quiet', '--multiquery'], False,
                'Local CPU only.', 'Read the complete reviewed script on stdin. Quiet mode checks syntax; ordinary formatting is not semantic lint.',
                ['No reference, type, engine or permission resolution.', 'Pin the client version to the selected server grammar.'],
                'https://clickhouse.com/docs/concepts/features/tools-and-utilities/clickhouse-format'),
            _check('clickhouse_explain', 'native_plan', ['EXPLAIN PLAN <eligible_query>'], True,
                'Server analysis consumes resources and may consult remote table metadata.', 'Connected planning only; never substitute EXPLAIN ANALYZE.',
                ['No universal DDL validation.', 'EXPLAIN ANALYZE executes the query; separate authorization is required.'],
                'https://clickhouse.com/docs/sql-reference/statements/explain'),
        ],
    },
    'motherduck': {
        'label': 'MotherDuck', 'dialect': 'duckdb',
        'requirements': ['organization_or_endpoint', 'database', 'schema', 'principal', 'duckdb_version', 'motherduck_extension_version'],
        'identity': ['organization_or_endpoint', 'authenticated_principal', 'database', 'schema', 'attachment_type', 'duckdb_version', 'motherduck_extension_version'],
        'source_markers': ['explicit motherduck connection type; duckdb alone is not MotherDuck'],
        'namespace': 'attached_database.schema.object; distinguish md: remote database from local DuckDB',
        'physical_design': ['remote/local attachments and execution placement', 'DuckDB/MotherDuck version compatibility', 'extension and external-file behavior'],
        'metadata_docs': ['https://duckdb.org/docs/current/sql/meta/information_schema',
                          'https://duckdb.org/docs/lts/sql/meta/duckdb_table_functions'],
        'native_checks': [_check('motherduck_explain', 'native_plan', ['duckdb', 'md:<database>', '-c', 'EXPLAIN <eligible_query>'], True,
            'Authorized cloud connection and planning resources; external metadata may be accessed.', 'Plans in the selected MotherDuck connection, without EXPLAIN ANALYZE.',
            ['Local DuckDB alone does not establish remote identity or extension support.', 'EXPLAIN ANALYZE executes the query.'],
            'https://motherduck.com/docs/key-tasks/query-performance')],
    },
}


def get_platform(warehouse: str) -> Dict[str, Any]:
    """Return a detached JSON-safe profile; unknown/GCP selections fail closed."""
    if not isinstance(warehouse, str) or warehouse not in _PROFILES:
        raise ValueError('Choose an explicit supported warehouse product')
    profile = copy.deepcopy(_PROFILES[warehouse])
    profile.update(schema_version=MATRIX_VERSION, warehouse=warehouse, research_date=RESEARCH_DATE,
                   native_qualified=False, execution='requires_operator_validation')
    lint: StaticLint = {'tool': 'sqlfluff', 'version': SQLFLUFF_VERSION, 'dialect': profile['dialect'],
        'version_policy': 'Exact pinned version; qualify the selected templater, adapter and runtime separately.',
        'coverage_gaps': ['Linter grammar is not complete vendor grammar.', 'No native references, data correctness or access acceptance.'] +
                         (['MotherDuck cloud extensions are outside the DuckDB dialect baseline.'] if warehouse == 'motherduck' else []),
        'documentation': _SQLFLUFF_DOC}
    profile['static_lint'] = lint
    profile['metadata'] = {'template': 'examples/catalogue-queries/' + warehouse + '.sql',
        'identity_fields': profile.pop('identity'), 'namespace_mapping': profile.pop('namespace'),
        'requirements': profile['requirements'][:], 'documentation': profile.pop('metadata_docs'),
        'qualification': 'read_only_starter_template_not_live_validated'}
    from metadata_platforms import capabilities
    profile['metadata_delivery'] = capabilities(warehouse)
    from security_capabilities import capabilities as security_capabilities
    profile['access_enforcement'] = security_capabilities(warehouse)
    return profile


def get_pairing(framework: str, warehouse: str) -> Pairing:
    """dbt is Core authoring; dbt_platform is hosting compatibility, not intake."""
    get_platform(warehouse)
    if not isinstance(framework, str) or framework not in (*FRAMEWORKS, 'dbt_core', 'dbt_platform'):
        raise ValueError('Unsupported transformation framework or hosting route')
    framework = 'dbt' if framework == 'dbt_core' else framework
    result = {'framework': framework, 'warehouse': warehouse, 'status': 'conditional', 'native_qualified': False,
              'reason': '', 'requirements': [], 'checks': [], 'documentation': []}
    from security_capabilities import capabilities as security_capabilities
    result['access_enforcement'] = security_capabilities(warehouse, framework)
    if framework == 'native_sql':
        result.update(status='supported', reason='Candidate SQL authoring and native validation recipes exist; no live qualification.',
                      requirements=['Reviewed dialect-specific SQL and target identity'], checks=get_platform(warehouse)['native_checks'])
    elif framework in ('dbt', 'dbt_platform'):
        result['documentation'] = [_DBT_DOC]
        result['requirements'] = ['Exact dbt runtime and warehouse adapter versions', 'Reviewed packages/macros/hooks', 'Native target and independent acceptance evidence']
        if framework == 'dbt_platform' and warehouse not in DBT_PLATFORM_WAREHOUSES:
            reason = ('ClickHouse is documented Private beta; this hosted adapter has no qualified entitlement/runtime contract.'
                      if warehouse == 'clickhouse' else 'DuckDB is documented CLI only; MotherDuck hosting is not established.')
            result.update(status='unsupported', reason=reason)
            return result
        result['reason'] = ('Hosted route limited to the four verified hosting warehouses; the existing job/runtime still needs qualification.'
                            if framework == 'dbt_platform' else 'Core route requires the selected warehouse adapter/runtime; a local adapter does not imply hosted support.')
        if warehouse == 'clickhouse':
            result['documentation'].append('https://github.com/ClickHouse/dbt-clickhouse')
            result['requirements'].append('Qualify dbt-clickhouse materializations and server compatibility; do not assume Core feature parity.')
        if warehouse == 'motherduck':
            result['documentation'].extend(['https://motherduck.com/glossary/motherduck/', 'https://motherduck.com/community-and-open-source/'])
            result['requirements'].append('Qualify dbt-duckdb, DuckDB and MotherDuck extension together with explicit md: destination.')
        result['checks'] = [
            _check('dbt_parse', 'framework_config', ['dbt', 'parse', '--project-dir', '<project>', '--profiles-dir', '<profiles>', '--target', '<target>'], False,
                'Local CPU/filesystem.', 'Parses project structure and writes artifacts; dependencies must already be provisioned.',
                ['Does not produce compiled SQL or validate native references.', 'Repository code and packages still require review.'],
                'https://docs.getdbt.com/reference/commands/parse'),
            _check('dbt_compile', 'framework_render', ['dbt', 'compile', '--project-dir', '<project>', '--profiles-dir', '<profiles>', '--target', '<target>'], True,
                'Macros can query the warehouse and incur compute cost.', 'Macro/run_query code may execute DDL/DML; authorize the exact project before rendering.',
                ['Compiled SQL does not cover actual build behavior.', 'Record hooks, tests and materializations in the coverage inventory.'],
                'https://docs.getdbt.com/reference/commands/compile'),
        ]
        if warehouse != 'clickhouse':
            result['checks'].append(_check('dbt_v2_lint_optional', 'framework_lint',
                ['dbt', 'lint', '--config', '<reviewed-config>', '--format', 'json'], False,
                'Local CPU only; no warehouse connection.', 'Uses bounded symbolic/stub template rendering; no automatic fixes.',
                ['Not identical to SQLFluff results.', 'Rendered variants/placeholders leave explicit coverage gaps.',
                 'DuckDB lint does not establish MotherDuck remote feature support.'],
                'https://docs.getdbt.com/reference/commands/lint',
                runtime='Available in v2; verify exact runtime/dialect capability. Never apply the v1 dbt templater to an arbitrary v2 runtime.'))
    else:
        result['documentation'] = [_COA_DOC, _COA_SETUP, 'https://docs.coalesce.io/docs/coa/version-733-and-above']
        if warehouse not in COALESCE_WAREHOUSES:
            result.update(status='unsupported', reason='No verified Coalesce native contract for this warehouse; supplying SQL or IDs cannot enable the route.')
            return result
        result['reason'] = 'Requires representative native contract and installed-version/platform verification; overview and setup documentation differ.'
        result['requirements'] = ['Native project format/version, node/column IDs, node types and storage mappings',
                                  'Verify exact CLI/platform support: overview says Snowflake only; setup also documents Databricks and BigQuery (7.40+).']
        result['checks'] = [_check('coa_validate', 'framework_config', ['coa', 'validate', '--dir', '<project>', '--workspace', '<workspace>'], False,
            'Local validation; selected native runtime/configuration still must be reviewed.', 'Validates native YAML/graph; no separate coa lint contract is claimed.',
            ['Capture and lint emitted Create/Run SQL separately.', 'Dry-run preview is not complete cloud-plan or native execution validation.'], _COA_DOC)]
        for command in ('create', 'run'):
            result['checks'].append(_check('coa_' + command + '_preview', 'framework_render',
                ['coa', command, '--dir', '<project>', '--workspace', '<workspace>', '--include', '<selector>', '--dry-run', '--verbose'], True,
                'Selected version/profile can consult native metadata; review its connection behavior.',
                'Previews generated DDL/DML instead of executing it; retain node-to-SQL lineage.',
                ['Generated SQL still requires dialect lint and native validation.', 'Not a full cloud deployment-plan acceptance.'],
                _COA_DOC, runtime='Qualify the exact installed CLI/platform contract; BigQuery local development requires 7.40+.'))

    return copy.deepcopy(result)


def adapter_registry() -> Dict[str, Any]:
    """Compatibility view for the source-readiness collector, derived here."""
    frameworks = {
        'dbt': {'generation': 'agent_assisted', 'artifact_contract': 'Reviewed dbt Core project patch; preserve packages, macros, hooks and CI; hosting is a separate compatibility decision.'},
        'coalesce': {'generation': 'requires_contract', 'artifact_contract': 'Versioned representative native project, node and column IDs, node types, storage mappings; only documented warehouse routes.'},
        'native_sql': {'generation': 'agent_assisted', 'artifact_contract': 'Dependency-ordered scripts in the explicitly selected warehouse dialect.'},
    }
    sources = {
        'raw_csv': {'assessment': 'bounded_metadata', 'markers': ['.csv outside a dbt project; snapshot metadata, not native warehouse identity']},
        'dbt': {'assessment': 'static_signals', 'markers': ['dbt_project.yml', 'manifest.json']},
        'coalesce': {'assessment': 'static_signals', 'markers': ['data.yml with native Nodes/locations.yml', 'coalesce.yml']},
        'generic_sql': {'assessment': 'static_signals', 'markers': ['.sql or .sqlx; dialect unresolved without explicit evidence']},
    }
    for name in WAREHOUSES:
        sources[name] = {'assessment': 'static_signals', 'markers': get_platform(name)['source_markers']}
    return {'frameworks': frameworks, 'warehouses': {name: get_platform(name) for name in WAREHOUSES}, 'sources': sources}
