"""Vendor documentation and accelerator qualification are separate assertions."""
import copy

FRAMEWORK_ALIASES = {'native_sql':'native_sql','dbt':'dbt','dbt_core':'dbt','dbt_platform':'dbt','coalesce':'coalesce'}
PLATFORMS = {
    'snowflake': {
        'controls':['object/role grants','row access policies','column masking','tag policy bindings'],
        'sources':['https://docs.snowflake.com/en/user-guide/security-column-intro',
                   'https://docs.snowflake.com/en/sql-reference/functions/policy_references'],
        'requirements':['Exact account, database/schema/object and active role.',
                        'Policy visibility is privilege-scoped; empty readback does not prove no policies.',
                        'Verify account edition and effective policy/tag bindings; metadata comments do not enforce access.'],
        'inspection':['SHOW GRANTS on exact objects and roles; resolve inherited role privileges.',
                      'DESCRIBE MASKING POLICY / ROW ACCESS POLICY and INFORMATION_SCHEMA.POLICY_REFERENCES with sufficient visibility.',
                      'Run positive and denied role queries, then test derived objects and newly introduced columns.']},
    'databricks': {
        'controls':['Unity Catalog grants','table row filters and column masks','governed-tag ABAC'],
        'sources':['https://docs.databricks.com/aws/en/data-governance/unity-catalog/filters-and-masks/',
                   'https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac/requirements'],
        'requirements':['Pin cloud/workspace, metastore, catalog/schema/object, runtime and compute access mode.',
                        'Table controls and ABAC have different runtime and object limitations; qualify the selected route.',
                        'Do not infer enforcement from ungoverned tags, view labels or local Spark results.'],
        'inspection':['Read current grants, complete table policy assignments, UDF definitions and governed tag state.',
                      'Run exact-persona tests using the selected SQL warehouse/runtime; verify missing attributes and conflicting groups.',
                      'Qualify view support and any Beta dependency explicitly rather than treating every object alike.']},
    'bigquery': {
        'controls':['IAM/dataset/table access','row access policies','column policy tags/data policies','data masking'],
        'sources':['https://docs.cloud.google.com/bigquery/docs/row-level-security-intro',
                   'https://docs.cloud.google.com/bigquery/docs/column-data-masking-intro'],
        'requirements':['Pin project, dataset, location, principal and reservation/edition where relevant.',
                        'Policy tags/data policies enforce access; descriptions and ordinary labels do not.',
                        'Data governance tags are Preview; select and qualify them explicitly.'],
        'inspection':['Read table schema policy tags, applicable data policies, row policies and effective IAM.',
                      'Verify complete regional taxonomy/policy scope and inherited principal permissions.',
                      'Disable cached-result reuse for effective persona tests; account for policy propagation.']},
    'redshift': {
        'controls':['role/object grants','row-level security','dynamic data masking'],
        'sources':['https://docs.aws.amazon.com/redshift/latest/dg/r_Database_objects.html',
                   'https://docs.aws.amazon.com/redshift/latest/dg/t_ddm-considerations.html'],
        'requirements':['Pin cluster or serverless workgroup, database, identity and session settings.',
                        'Qualify RLS and masking independently of AWS resource tags.',
                        'Preserve policy priority and role inheritance; row filtering precedes masking.'],
        'inspection':['Read grants, RLS enablement/policy assignments and masking policy assignments/priorities.',
                      'Inspect effective roles including bypass privileges and query/explain metadata visibility.',
                      'Run positive and negative identity tests on base and derived objects, including exports.']},
    'clickhouse': {
        'controls':['users/roles and column grants','row policies','masking policies'],
        'sources':['https://clickhouse.com/docs/reference/statements/create/row-policy',
                   'https://clickhouse.com/docs/reference/statements/create/masking-policy'],
        'requirements':['Pin server version, database, engine, cluster/replica scope and user/active roles.',
                        'Masking-policy support must be qualified on the exact server; uncovered users may see original values.',
                        'A row policy is not a substitute for restrictive column grants or protection of write-capable paths.'],
        'inspection':['Read SHOW GRANTS, roles, system policy inventories and exact policy definitions on every relevant node.',
                      'Verify restrictive/permissive row-policy combinations and complete masking subject coverage.',
                      'Run direct/table-function/distributed and scoped export paths under separate personas.']},
    'motherduck': {
        'controls':['database sharing','preset/custom roles','documented table-level access controls'],
        'sources':['https://motherduck.com/product/pricing/',
                   'https://motherduck.com/docs/key-tasks/sharing-data/sharing-overview'],
        'requirements':['Pin remote organization/database/share, identity, token scope and supported account capabilities.',
                        'Current documentation includes table-level controls; do not assume only database-level access.',
                        'Row/column masking and inheritance remain unqualified in this adapter; never substitute local DuckDB proof.'],
        'inspection':['Inspect remote share audience, database/table entitlements, roles and token restrictions.',
                      'Test actual remote identity and allowed/denied resources, including cross-database and export paths.',
                      'If required row/column controls lack a qualified route, block and obtain a reviewed isolation design.']},
}


def capabilities(warehouse, framework='native_sql'):
    if warehouse not in PLATFORMS or framework not in FRAMEWORK_ALIASES:
        raise ValueError('Unsupported security warehouse/framework')
    normalized = FRAMEWORK_ALIASES[framework]
    vendor = copy.deepcopy(PLATFORMS[warehouse])
    return {'schema_version':1,'warehouse':warehouse,'framework':normalized,'documented':True,
            'implemented':True,'locally_tested':True,'live_qualified':False,
            'implementation_scope':'Offline exact-state contract, nonweakening checks, native readback comparison and persona-evidence comparison only.',
            'native_policy_writes':False,'native_evidence_authenticated':False,
            'unsupported_functions':['automatic policy provisioning','automatic GRANT/REVOKE','tenant qualification from imported JSON',
                                     'automatic policy loosening','protected deployment without authenticated effective tests'],
            'framework_boundary':('Metadata and documentation projection does not execute or qualify warehouse policies.' if normalized=='dbt' else
                                  'Native node/schema/runtime and warehouse policy execution need separate qualification; exported SQL is insufficient.' if normalized=='coalesce' else
                                  'Native SQL delivery does not prove policy execution or effective enforcement.'),
            'vendor_documented_controls':vendor['controls'],'official_sources':vendor['sources'],
            'qualification_requirements':vendor['requirements'],'read_only_inspection_recipe':vendor['inspection']}
