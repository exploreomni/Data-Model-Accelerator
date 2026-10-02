-- ClickHouse metadata STARTER TEMPLATES; checked 2026-09-24, NOT live-validated.
-- Run selected SELECT statements independently. Replace __DATABASE__ with an
-- escaped, allowlisted string literal. Use an authorized metadata-only identity.
-- system.* describes the connected server, not automatically every cluster node.
-- Capture endpoint/cluster, query_id, pagination and errors through the client.
-- ClickHouse has database.table, not database.schema.table. Canonical normalization
-- may use schema="__no_schema__"; retain that explicit mapping, never emit it in SQL.

-- CH-00: Observed session context; host/cluster identity comes from the client.
SELECT currentDatabase() AS database_name, currentUser() AS database_user,
       version() AS server_version, now() AS collected_at;

-- CH-01: Relations and native physical design. Preserve engine separately from
-- canonical object_type; a MergeTree PRIMARY KEY is not a uniqueness guarantee.
SELECT database, name, uuid, engine, is_temporary, partition_key, sorting_key,
       primary_key, sampling_key, comment
FROM system.tables
WHERE database = '__DATABASE__'
ORDER BY database, name;

-- CH-02: Native types/default kinds; do not derive nullability with a naïve regex
-- over Nullable/LowCardinality/Array nesting or collapse unsigned types.
SELECT database, table, name, type, position, default_kind, default_expression,
       comment, is_in_partition_key, is_in_sorting_key, is_in_primary_key,
       is_in_sampling_key, compression_codec
FROM system.columns
WHERE database = '__DATABASE__'
ORDER BY database, table, position;

-- CH-03 OPTIONAL: Definitions can contain confidential paths/settings.
-- Collect only when authorized; engine_full is needed for full engine arguments.
SELECT database, name, create_table_query, engine_full, as_select
FROM system.tables
WHERE database = '__DATABASE__'
ORDER BY database, name;

-- Grants/policies, ON CLUSTER coverage, replicas, materialized-view behavior,
-- TTL/mutations and connector CDC semantics require separate evidence.
