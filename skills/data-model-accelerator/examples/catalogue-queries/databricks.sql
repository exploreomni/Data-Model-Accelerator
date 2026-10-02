-- Databricks Unity Catalog metadata STARTER TEMPLATES; checked 2026-09-09.
-- Run chosen statements independently after cloud/runtime/permission review.
-- NOT live-validated. No business table scans. No mutation statements.
-- Replace identifier `__CATALOG__` and exact stored schema literal '__SCHEMA__'.
-- Most catalog/schema identifier values in information_schema are lowercase.
-- Record workspace, metastore, endpoint, principal, statement ID and chunk status
-- in the execution envelope. Unity Catalog does not inventory hive_metastore here.

-- DB-00: Session provenance; account/workspace/metastore IDs need external context.
SELECT current_user() AS collected_by,
       current_catalog() AS session_catalog,
       current_schema() AS session_schema,
       current_timestamp() AS collected_at;

-- DB-01: Approved schema metadata.
SELECT CATALOG_NAME, SCHEMA_NAME, SCHEMA_OWNER, COMMENT, CREATED, LAST_ALTERED
FROM `__CATALOG__`.information_schema.schemata
WHERE SCHEMA_NAME = '__SCHEMA__'
ORDER BY CATALOG_NAME, SCHEMA_NAME;

-- DB-02: Relation kinds include documented managed/external shallow clones.
-- STORAGE_PATH is confidential location metadata, not a replication source contract.
SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, TABLE_OWNER,
       DATA_SOURCE_FORMAT, STORAGE_PATH, COMMENT, CREATED, LAST_ALTERED
FROM `__CATALOG__`.information_schema.tables
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME;

-- DB-03: Preserve FULL_DATA_TYPE for nested types. This does not fully enumerate
-- nested field nullability/comments. COLUMN_DEFAULT is reserved/always NULL here;
-- its NULL value must not be normalized into a confirmed absence of a default.
SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION,
       DATA_TYPE, FULL_DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
       NUMERIC_PRECISION, NUMERIC_SCALE, PARTITION_INDEX, COMMENT
FROM `__CATALOG__`.information_schema.columns
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;

-- DB-04: Nonowners can receive NULL VIEW_DEFINITION. Preserve that visibility gap.
SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, VIEW_DEFINITION
FROM `__CATALOG__`.information_schema.views
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME;

-- DB-05 OPTIONAL: AWS docs label TABLE_CONSTRAINTS Public Preview;
-- Databricks SQL / Runtime 11.3 LTS+ and Unity Catalog. Verify selected surface.
-- ENFORCED reports declarations, not independently tested uniqueness/fanout.
SELECT CONSTRAINT_CATALOG, CONSTRAINT_SCHEMA, CONSTRAINT_NAME,
       TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_TYPE, ENFORCED, COMMENT
FROM `__CATALOG__`.information_schema.table_constraints
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME;

-- DB-06 OPTIONAL: AWS docs label KEY_COLUMN_USAGE Public Preview.
-- Keep ordinal positions; referenced parent constraints may remain outside scope.
SELECT CONSTRAINT_CATALOG, CONSTRAINT_SCHEMA, CONSTRAINT_NAME,
       TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME,
       ORDINAL_POSITION, POSITION_IN_UNIQUE_CONSTRAINT
FROM `__CATALOG__`.information_schema.key_column_usage
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION;

-- Nested DESCRIBE AS JSON, policies/grants, lineage/history, and pipeline metadata
-- are separate optional exports. No LIMIT is used as a substitute for completeness.
-- Reconcile every API result chunk and fail completeness if truncated=true.
