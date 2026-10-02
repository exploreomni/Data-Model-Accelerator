-- Redshift metadata STARTER TEMPLATES; checked 2026-09-24, NOT live-validated.
-- Run selected SELECT statements independently in the authorized database.
-- Replace __DATABASE__ and __SCHEMA__ as escaped, allowlisted string literals.
-- Capture AWS account, region, cluster/workgroup and Data API statement IDs
-- from the authorized client; SQL session identity alone does not prove IAM.
-- No business rows are scanned and no metadata/permission repair is performed.

-- RS-00: Observed session context, not proof of the requested IAM identity.
SELECT current_database() AS database_name, current_schema() AS schema_name,
       current_user AS database_user, version() AS server_version,
       current_timestamp AS collected_at;

-- RS-01: Relations visible through SVV_ALL_TABLES, including external tables.
-- Visibility differs by principal. AWS recommends SHOW TABLES for discovery
-- across evolving datashare/external contexts; collect that separately if needed.
SELECT database_name, schema_name, table_name, table_type, remarks
FROM svv_all_tables
WHERE database_name = '__DATABASE__' AND schema_name = '__SCHEMA__'
ORDER BY database_name, schema_name, table_name;

-- RS-02: Visible native/external columns. Retain native type spelling and scale.
-- SHOW COLUMNS is the separate current AWS discovery recommendation.
SELECT database_name, schema_name, table_name, column_name, ordinal_position,
       column_default, is_nullable, data_type, character_maximum_length,
       numeric_precision, numeric_scale, remarks
FROM svv_all_columns
WHERE database_name = '__DATABASE__' AND schema_name = '__SCHEMA__'
ORDER BY database_name, schema_name, table_name, ordinal_position;

-- RS-03 OPTIONAL: Declared constraints for the connected database only.
-- PK/FK/UNIQUE declarations are informational, not independent grain tests.
SELECT constraint_catalog, constraint_schema, constraint_name,
       table_catalog, table_schema, table_name, constraint_type
FROM information_schema.table_constraints
WHERE table_catalog = '__DATABASE__' AND table_schema = '__SCHEMA__'
ORDER BY table_catalog, table_schema, table_name, constraint_name;

-- Distribution/sort/encoding, SUPER shape, policies, datashare context,
-- physical IDs and replication contracts require separately scoped evidence.
