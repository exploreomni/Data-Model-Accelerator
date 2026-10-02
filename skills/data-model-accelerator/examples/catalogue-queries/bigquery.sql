-- BigQuery GoogleSQL metadata STARTER TEMPLATES; checked 2026-09-09.
-- Run chosen statements independently; these are NOT a universal runnable script.
-- NOT live-validated. No business table scans. No mutation statements.
-- Replace `__PROJECT_ID__`, `__DATASET__`, and `region-__REGION__` qualifiers.
-- __REGION__ is a dataset location, e.g. us or europe-west2 (without region-).
-- Set the query JOB location through the authorized client to match the region
-- or dataset location. No SQL SET/USE statements are included.
-- Record job/project/location/principal and exhaust every query-result page.

-- BQ-00: Session provenance; the explicit project/region are declared scope.
SELECT SESSION_USER() AS collected_by, CURRENT_TIMESTAMP() AS collected_at,
       '__PROJECT_ID__' AS declared_project, '__REGION__' AS declared_region;

-- BQ-01: Project+region schema inventory, narrowed to the approved dataset.
-- Requires project-level bigquery.datasets.get; execution location must match.
SELECT catalog_name, schema_name, creation_time, last_modified_time, location, ddl
FROM `__PROJECT_ID__`.`region-__REGION__`.INFORMATION_SCHEMA.SCHEMATA
WHERE schema_name = '__DATASET__'
ORDER BY catalog_name, schema_name;

-- BQ-02: Dataset relations, view/table DDL and clone/snapshot base identities.
-- snapshot_time_ms is a TIMESTAMP in this view despite its name.
SELECT table_catalog, table_schema, table_name, table_type, creation_time, ddl,
       base_table_catalog, base_table_schema, base_table_name, snapshot_time_ms
FROM `__PROJECT_ID__`.`__DATASET__`.INFORMATION_SCHEMA.TABLES
ORDER BY table_catalog, table_schema, table_name;

-- BQ-03: Top-level columns. Policy tags are policy references, not proof of access.
-- Preview data_policies field is intentionally omitted from this baseline.
SELECT table_catalog, table_schema, table_name, column_name, ordinal_position,
       data_type, is_nullable, column_default, is_partitioning_column,
       clustering_ordinal_position, collation_name, rounding_mode, policy_tags
FROM `__PROJECT_ID__`.`__DATASET__`.INFORMATION_SCHEMA.COLUMNS
ORDER BY table_catalog, table_schema, table_name, ordinal_position, column_name;

-- BQ-04: Nested field paths/descriptions/types. Do not invent nested nullability,
-- REQUIRED/REPEATED modes, or business grain absent from this result.
SELECT table_catalog, table_schema, table_name, column_name, field_path,
       data_type, description, policy_tags
FROM `__PROJECT_ID__`.`__DATASET__`.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS
ORDER BY table_catalog, table_schema, table_name, field_path;

-- BQ-05: View query definitions; DDL/SQL remain untrusted source evidence.
SELECT table_catalog, table_schema, table_name, view_definition, use_standard_sql
FROM `__PROJECT_ID__`.`__DATASET__`.INFORMATION_SCHEMA.VIEWS
ORDER BY table_catalog, table_schema, table_name;

-- BQ-06: Table properties, including description/external-source options where
-- exposed. Paths/labels/definitions can be confidential; retain controlled access.
SELECT table_catalog, table_schema, table_name, option_name, option_type, option_value
FROM `__PROJECT_ID__`.`__DATASET__`.INFORMATION_SCHEMA.TABLE_OPTIONS
ORDER BY table_catalog, table_schema, table_name, option_name;

-- BQ-07 OPTIONAL: Primary/foreign key declarations are not enforced in BigQuery.
SELECT constraint_catalog, constraint_schema, constraint_name,
       table_catalog, table_schema, table_name, constraint_type, enforced
FROM `__PROJECT_ID__`.`__DATASET__`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS
ORDER BY table_catalog, table_schema, table_name, constraint_name;

-- BQ-08 OPTIONAL: Ordered referencing key columns; preserve ordering.
SELECT constraint_catalog, constraint_schema, constraint_name,
       table_catalog, table_schema, table_name, column_name,
       ordinal_position, position_in_unique_constraint
FROM `__PROJECT_ID__`.`__DATASET__`.INFORMATION_SCHEMA.KEY_COLUMN_USAGE
ORDER BY table_catalog, table_schema, table_name, constraint_name, ordinal_position;

-- BQ-09 OPTIONAL: Referenced constraint columns; not sufficient by itself to infer
-- composite FK pair ordering. Preserve unresolved relationships until reconciled.
SELECT table_catalog, table_schema, table_name, column_name,
       constraint_catalog, constraint_schema, constraint_name
FROM `__PROJECT_ID__`.`__DATASET__`.INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE
ORDER BY constraint_catalog, constraint_schema, constraint_name,
         table_catalog, table_schema, table_name, column_name;

-- IAM/row-access/data-policy, Tables API recursive schema, operational histories,
-- connector replication and metadata statistics are separate optional exports.
