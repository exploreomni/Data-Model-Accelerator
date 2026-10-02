"""Versioned metadata capabilities; native qualification is always destination-specific."""
import copy

RESEARCH_DATE = '2026-09-30'
_PROFILES = {
    'snowflake': {'relation_comments': ['table', 'view'], 'column_comments': ['table', 'view'],
        'tags': 'custom_governed', 'namespace_components': 2,
        'limitations': ['Tag edition/privileges/policy bindings require preflight.', 'SNOWFLAKE.TAGS mappings are Preview Feature — Open and opt-in.'],
        'documentation': ['https://docs.snowflake.com/en/sql-reference/sql/comment', 'https://docs.snowflake.com/en/user-guide/object-tagging/snowflake-provided-tags']},
    'databricks': {'relation_comments': ['table', 'view'], 'column_comments': ['table', 'view'],
        'tags': 'unity_catalog', 'namespace_components': 2,
        'limitations': ['Pin Unity Catalog/runtime and MODIFY or ownership privileges; COMMENT ON COLUMN requires SQL/Runtime 16.1 or later.', 'Table tag inheritance does not automatically document column tags.', 'Column tagging is one column per ALTER operation.'],
        'documentation': ['https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-comment', 'https://docs.databricks.com/aws/en/database-objects/tags']},
    'bigquery': {'relation_comments': ['table', 'view'], 'column_comments': ['table', 'view'],
        'tags': 'external_policy_required', 'namespace_components': 2,
        'limitations': ['Nested field descriptions need a separately qualified schema API path. Top-level table/view columns use ALTER COLUMN SET OPTIONS.', 'Labels are not column policy tags; no automatic security policy mapping.', 'Column data governance tags are Preview and outside the default emitter.'],
        'documentation': ['https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language', 'https://docs.cloud.google.com/bigquery/docs/tags']},
    'redshift': {'relation_comments': ['table', 'view'], 'column_comments': ['table', 'view'],
        'tags': 'dictionary_only', 'namespace_components': 2,
        'limitations': ['Current-database comments only; external objects and late-binding-view columns are excluded.', 'AWS resource tags are not warehouse column metadata.'],
        'documentation': ['https://docs.aws.amazon.com/redshift/latest/dg/r_COMMENT.html']},
    'clickhouse': {'relation_comments': ['table'], 'column_comments': ['table'],
        'tags': 'dictionary_only', 'namespace_components': 1,
        'limitations': ['Pin server/engine and declared cluster scope; local changes do not establish replica parity.', 'View comments are outside this emitter contract.'],
        'documentation': ['https://clickhouse.com/docs/reference/statements/alter/comment', 'https://clickhouse.com/docs/reference/statements/alter/column']},
    'motherduck': {'relation_comments': ['table', 'view'], 'column_comments': ['table'],
        'tags': 'dictionary_only', 'namespace_components': 2,
        'limitations': ['Remote database identity, extension/version and dependency restrictions need qualification.', 'Local DuckDB does not establish MotherDuck execution.'],
        'documentation': ['https://duckdb.org/docs/current/sql/statements/comment_on']},
}


def capabilities(warehouse, framework='native_sql'):
    if warehouse not in _PROFILES or framework not in ('dbt', 'dbt_core', 'dbt_platform', 'coalesce', 'native_sql'):
        raise ValueError('Explicit supported warehouse/framework required')
    value = copy.deepcopy(_PROFILES[warehouse])
    value.update(schema_version=1, warehouse=warehouse, framework=framework,
                 research_date=RESEARCH_DATE, native_qualified=False,
                 qualification='candidate_generation_and_contract_checks_only',
                 supported_pairing=not (framework == 'coalesce' and warehouse not in ('snowflake', 'databricks', 'bigquery')))
    value['implementation'] = {
        'canonical_contract': True, 'comment_sql': True, 'readback_queries': True,
        'tag_assignment_sql': warehouse in ('snowflake', 'databricks'),
        'dbt_properties_projection': framework in ('dbt', 'dbt_core', 'dbt_platform'),
        'coalesce_node_projection': False, 'governance_provisioning': False,
        'authenticated_native_drift_collector': False,
    }
    value['locally_tested'] = ['contract', 'comment_rendering', 'metadata_diff', 'expected_state_readback']
    value['live_qualified'] = False
    value['automatic_live_metadata_dispatch'] = 'blocked_pending_authenticated_native_drift_collector'
    return value
