-- MotherDuck metadata STARTER TEMPLATES; checked 2026-09-24, NOT live-validated.
-- Establish an authorized explicit md: database connection BEFORE these queries.
-- No INSTALL, LOAD, ATTACH, USE, or authentication mutations are included.
-- Replace __DATABASE__ and __SCHEMA__ as escaped, allowlisted string literals.
-- Capture authenticated cloud principal, organization/endpoint and extension
-- version from trusted client/service evidence. DuckDB current_user is not proof
-- of MotherDuck cloud identity. Local DuckDB results are simulation only.

-- MD-00: Observed connection defaults and client engine version.
SELECT current_database() AS database_name, current_schema() AS schema_name,
       version() AS duckdb_version, current_timestamp AS collected_at;

-- MD-01: Attachment metadata; an alias/name alone does not prove remote identity.
-- Avoid exporting local filesystem paths or secrets in attachment configuration.
SELECT database_name, database_oid, type, readonly
FROM duckdb_databases()
WHERE database_name = '__DATABASE__'
ORDER BY database_name;

-- MD-02: Tables/views in exactly the selected attached database and schema.
SELECT table_catalog, table_schema, table_name, table_type
FROM information_schema.tables
WHERE table_catalog = '__DATABASE__' AND table_schema = '__SCHEMA__'
ORDER BY table_catalog, table_schema, table_name;

-- MD-03: Native column types and declared null/default metadata.
SELECT table_catalog, table_schema, table_name, column_name, ordinal_position,
       column_default, is_nullable, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_catalog = '__DATABASE__' AND table_schema = '__SCHEMA__'
ORDER BY table_catalog, table_schema, table_name, ordinal_position;

-- MD-04 OPTIONAL: View definitions; retain confidentiality and native version.
SELECT database_name, schema_name, view_name, comment, sql
FROM duckdb_views()
WHERE database_name = '__DATABASE__' AND schema_name = '__SCHEMA__'
ORDER BY database_name, schema_name, view_name;

-- Local/remote placement, grants/shares, cloud feature support and external-file
-- access require separate evidence. Do not infer these from a successful parse.
