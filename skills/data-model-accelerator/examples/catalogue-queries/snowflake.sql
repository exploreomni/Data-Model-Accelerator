-- Snowflake metadata STARTER TEMPLATES; documentation checked 2026-09-09.
-- Select and run statements independently after scope/version review.
-- NOT live-validated. No business table scans. No mutation statements.
-- Replace quoted identifier "__DATABASE__" and string literal '__SCHEMA__'
-- using provider-correct escaping and exact stored identifier case.
-- Raw outputs require a collection manifest and canonical normalization.
-- Do not interpret missing rows/definitions as evidence of absent objects/rules.

-- SF-00: Session provenance; record query ID/start/end in the execution envelope.
SELECT CURRENT_ACCOUNT() AS account_locator,
       CURRENT_REGION() AS account_region,
       CURRENT_USER() AS collected_by,
       CURRENT_ROLE() AS active_primary_role,
       CURRENT_TIMESTAMP() AS collected_at;

-- SF-01: Approved schema metadata (not a claim of all account schemas).
SELECT CATALOG_NAME, SCHEMA_NAME, SCHEMA_OWNER, CREATED, LAST_ALTERED, COMMENT
FROM "__DATABASE__".INFORMATION_SCHEMA.SCHEMATA
WHERE SCHEMA_NAME = '__SCHEMA__'
ORDER BY CATALOG_NAME, SCHEMA_NAME;

-- SF-02: Relations; ROW_COUNT/BYTES are metadata statistics, not profiles.
SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, TABLE_OWNER,
       IS_TRANSIENT, ROW_COUNT, BYTES, CREATED, LAST_ALTERED, LAST_DDL, COMMENT
FROM "__DATABASE__".INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME;

-- SF-03: Declared columns. DTD_IDENTIFIER supports optional nested-type exports.
SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION,
       DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, CHARACTER_MAXIMUM_LENGTH,
       NUMERIC_PRECISION, NUMERIC_SCALE, DTD_IDENTIFIER, COMMENT
FROM "__DATABASE__".INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;

-- SF-04: View definition evidence; preserve unavailable/hidden text as unknown.
SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, VIEW_DEFINITION, IS_SECURE,
       CREATED, LAST_ALTERED, COMMENT
FROM "__DATABASE__".INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME;

-- SF-05 OPTIONAL: Declared constraints; does not provide ordered key columns
-- or establish uniqueness/cardinality. Preserve ENFORCED without reinterpretation.
SELECT CONSTRAINT_CATALOG, CONSTRAINT_SCHEMA, CONSTRAINT_NAME,
       TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_TYPE, ENFORCED, COMMENT
FROM "__DATABASE__".INFORMATION_SCHEMA.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = '__SCHEMA__'
ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME;

-- SF-06 OPTIONAL: Referential declarations; referenced constraint may be outside
-- this schema. Keep unresolved dependency identities; do not widen scope silently.
SELECT CONSTRAINT_CATALOG, CONSTRAINT_SCHEMA, CONSTRAINT_NAME,
       UNIQUE_CONSTRAINT_CATALOG, UNIQUE_CONSTRAINT_SCHEMA, UNIQUE_CONSTRAINT_NAME,
       MATCH_OPTION, UPDATE_RULE, DELETE_RULE
FROM "__DATABASE__".INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = '__SCHEMA__'
ORDER BY CONSTRAINT_CATALOG, CONSTRAINT_SCHEMA, CONSTRAINT_NAME;

-- SF-07 OPTIONAL: Structured OBJECT/MAP field declarations, not VARIANT profiling.
-- ROW_IDENTIFIER/DTD_IDENTIFIER are type links, not business keys.
SELECT OBJECT_CATALOG, OBJECT_SCHEMA, OBJECT_NAME, OBJECT_TYPE,
       ROW_IDENTIFIER, FIELD_NAME, ORDINAL_POSITION, DATA_TYPE,
       NUMERIC_PRECISION, NUMERIC_SCALE, DTD_IDENTIFIER
FROM "__DATABASE__".INFORMATION_SCHEMA.FIELDS
WHERE OBJECT_SCHEMA = '__SCHEMA__'
ORDER BY OBJECT_CATALOG, OBJECT_SCHEMA, OBJECT_NAME, ROW_IDENTIFIER, ORDINAL_POSITION;

-- Additional policy/grant/SHOW/account-history/array-element exports are separate
-- optional tasks; these statements do not establish complete governance or CDC.
