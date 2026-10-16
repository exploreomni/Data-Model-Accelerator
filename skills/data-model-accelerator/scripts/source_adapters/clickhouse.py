"""Bounded offline ClickHouse SQL and native FORMAT JSON evidence."""
from pathlib import PurePosixPath
import re

from .base import Report, read_json
from .sql import parse_sql


CAPABILITY = {
    "formats": ["ClickHouse .sql", "native FORMAT JSON query responses and catalogue-row candidates"],
    "interpretation": "bounded_static_extraction",
    "acquisition": "supplied_exports",
    "limitations": [
        "No HTTP requests, SQL execution, source imports, native validation or permission checks.",
        "Result meta describes output headers, not the physical schema of a source table.",
        "ORDER BY and PRIMARY KEY do not establish row uniqueness or business grain.",
        "Materialized views, aggregate states, distributed topology and runtime merges need native evidence.",
    ],
}

_TABLE_KEYS = set("database name uuid engine is_temporary data_paths metadata_path "
                  "metadata_modification_time metadata_version dependencies_database dependencies_table "
                  "create_table_query engine_full as_select parameterized_view_parameters partition_key "
                  "sorting_key primary_key sampling_key unique_key skipping_indices_types storage_policy "
                  "total_rows total_bytes total_bytes_uncompressed parts active_parts total_marks "
                  "active_on_fly_data_mutations active_on_fly_alter_mutations active_on_fly_metadata_mutations "
                  "columns_descriptions_cache_size lifetime_rows lifetime_bytes comment has_own_data "
                  "loading_dependencies_database loading_dependencies_table loading_dependent_database "
                  "loading_dependent_table target_database target_table definer".split())
_COLUMN_KEYS = set("database table name type position default_kind default_expression comment "
                   "data_compressed_bytes data_uncompressed_bytes marks_bytes is_in_partition_key "
                   "is_in_sorting_key is_in_primary_key is_in_sampling_key compression_codec "
                   "character_octet_length numeric_precision numeric_precision_radix numeric_scale "
                   "datetime_precision serialization_hint statistics".split())
_DESCRIBE_KEYS = set("name type default_type default_expression comment codec_expression ttl_expression is_subcolumn".split())
_RESPONSE_KEYS = set("meta data rows rows_before_limit_at_least rows_before_aggregation statistics totals extremes exception".split())


class _Parser:
    def __init__(self, files):
        self.r = Report("clickhouse", files)
        self.identities = set()

    def gap(self, path, code, message, loc="$"):
        self.r.gap(path, code, message, locator=loc)

    def unknown(self, path, loc, value, keys):
        if set(value) - keys:
            self.gap(path, "unknown_fields", "Fields retained without interpretation: " +
                     ", ".join(sorted(set(value) - keys)), loc)

    def runtime_gaps(self, path, loc, text):
        checks = (
            (r"MaterializedView|MATERIALIZED\s+VIEW", "materialized_view_runtime",
             "Materialized-view refresh, trigger timing, target population and historical backfill are unverified."),
            (r"(?:Simple)?AggregateFunction\s*\(|AggregatingMergeTree", "aggregate_state_runtime",
             "Aggregate-state merge/finalization and result equivalence require native validation."),
            (r"\bDistributed\b", "distributed_runtime",
             "Distributed engine topology, remote schemas, sharding and delivery state are unverified."),
            (r"\w*MergeTree\b|\bFINAL\b", "merge_runtime",
             "Merge, replacement, collapse, mutation and FINAL behavior are not established by declarations."),
        )
        for pattern, code, message in checks:
            if re.search(pattern, text, re.I):
                self.gap(path, code, message, loc)

    def sql(self, path, loc, text, owner=None):
        if not isinstance(text, str) or not text.strip():
            self.gap(path, "missing_sql", "Expected non-empty SQL text.", loc)
            return
        start = len(self.r.objects)
        parse_sql(self.r, path, text, "clickhouse", owner_id=owner, locator=loc)
        for obj in self.r.objects[start:]:
            obj["details"]["uniqueness"] = "not_established"
            obj["details"]["key_semantics"] = "sorting_or_sparse_index_not_uniqueness"
        self.runtime_gaps(path, loc, text)
        if re.search(r"\b(?:ORDER\s+BY|PRIMARY\s+KEY)\b", text, re.I):
            self.gap(path, "key_not_uniqueness", "Sort and sparse-index declarations do not establish uniqueness or business grain.", loc)

    def register(self, path, loc, kind, identity):
        key = (kind, tuple(identity))
        if key in self.identities:
            self.gap(path, "duplicate_identity", "Repeated metadata identity; versions are not merged.", loc)
        self.identities.add(key)

    def table(self, path, loc, row):
        self.unknown(path, loc, row, _TABLE_KEYS)
        if not all(isinstance(row.get(k), str) and row[k].strip() for k in ("database", "name", "engine")):
            self.gap(path, "invalid_table", "A table row requires explicit database, name and engine; session-scoped temporary identity is unsupported.", loc)
            return
        parts = [row["database"], row["name"]]
        self.register(path, loc, "table", parts)
        native_id = row.get('uuid')
        if native_id is not None and (not isinstance(native_id, str) or not native_id.strip()):
            self.gap(path, 'invalid_identity', 'Supplied UUID must be a nonempty string; invalid value retained only as raw metadata.', loc + '.uuid')
            native_id = None
        oid = self.r.object(path, loc, "table_catalogue_candidate", ".".join(parts), native_id=native_id,
                            database=parts[0], table=parts[1], engine=row["engine"],
                            engine_full=row.get("engine_full"), sorting_key=row.get("sorting_key"),
                            primary_key=row.get("primary_key"), partition_key=row.get("partition_key"),
                            comment=row.get("comment"), uniqueness="not_established", raw_metadata=row,
                            provenance="row_signature_only", namespace_verified=False)
        for key in ("sorting_key", "primary_key", "partition_key", "sampling_key"):
            value = row.get(key)
            if value:
                if isinstance(value, str):
                    self.r.expression(path, loc + "." + key, "clickhouse", value, oid,
                                      interpretation="declared_" + key, uniqueness="not_established")
                else:
                    self.gap(path, "invalid_metadata", "Key expression must be a string.", loc + "." + key)
        if row.get("sorting_key") or row.get("primary_key"):
            self.gap(path, "key_not_uniqueness", "Sort and sparse-index keys do not establish uniqueness or business grain.", loc)
        self.runtime_gaps(path, loc, row["engine"])
        if row.get("create_table_query"):
            self.sql(path, loc + ".create_table_query", row["create_table_query"], oid)
        elif row.get("as_select"):
            self.sql(path, loc + ".as_select", row["as_select"], oid)
        else:
            self.gap(path, "missing_definition", "No creation or view query supplied; catalogue row alone is not a full declaration.", loc)
        if row.get("create_table_query") and row.get("as_select"):
            if isinstance(row["as_select"], str):
                self.r.expression(path, loc + ".as_select", "clickhouse", row["as_select"], oid,
                                  interpretation="preserved_original")
            else:
                self.gap(path, "invalid_metadata", "as_select must be a string.", loc + ".as_select")
        for db_key, table_key, kind in (
            ("loading_dependencies_database", "loading_dependencies_table", "loading_dependency"),
            ("dependencies_database", "dependencies_table", "catalogue_dependent_view"),
        ):
            if db_key not in row and table_key not in row:
                continue
            dbs, names = row.get(db_key), row.get(table_key)
            if not isinstance(dbs, list) or not isinstance(names, list) or len(dbs) != len(names) or not all(
                    isinstance(v, str) and v for v in dbs + names):
                self.gap(path, "invalid_dependency_pair", "Catalogue database/table arrays must be aligned non-empty strings.", loc)
                continue
            for i, (db, name) in enumerate(zip(dbs, names)):
                self.r.dependency(path, f"{loc}.{table_key}[{i}]", oid, db + "." + name,
                                  kind=kind, target_components=[db, name], resolution="unresolved")
        if row.get("target_database") or row.get("target_table"):
            if all(isinstance(row.get(k), str) and row[k] for k in ("target_database", "target_table")):
                self.r.dependency(path, loc + ".target_table", oid,
                                  row["target_database"] + "." + row["target_table"],
                                  kind="materialized_view_target", resolution="unresolved")
            else:
                self.gap(path, "invalid_dependency_pair", "Materialized-view target requires database and table.", loc)

    def column(self, path, loc, row, source, export_id):
        self.unknown(path, loc, row, _COLUMN_KEYS if source == "system.columns" else _DESCRIBE_KEYS)
        parts = [row.get("database"), row.get("table")] if source == "system.columns" else []
        if not all(isinstance(v, str) and v.strip() for v in parts + [row.get("name"), row.get("type")]):
            self.gap(path, "invalid_column", "Column candidate requires string name/type and any supplied database/table identity.", loc)
            return
        self.register(path, loc, "column", (parts or [path]) + [row["name"]])
        kind_key = "default_kind" if source == "system.columns" else "default_type"
        default_kind = row.get(kind_key)
        oid = self.r.object(path, loc, "column_catalogue_candidate", row["name"], parent_id=export_id,
                            database=parts[0] if parts else None, table=parts[1] if parts else None, data_type=row["type"],
                            default_kind=default_kind, comment=row.get("comment"),
                            uniqueness="not_established", raw_metadata=row,
                            provenance="row_signature_only", namespace_verified=False)
        if parts:
            self.r.dependency(path, loc, oid, ".".join(parts), target_components=parts,
                              kind="candidate_column_of", resolution="unresolved")
        else:
            self.gap(path, "describe_namespace_unresolved", "DESCRIBE-shaped rows do not identify a table or distinguish DESCRIBE TABLE from query output.", loc)
        if default_kind not in (None, "", "DEFAULT", "MATERIALIZED", "ALIAS", "EPHEMERAL"):
            self.gap(path, "unknown_default_kind", "Unknown column default kind retained.", loc + "." + kind_key)
        for key in ("default_expression", "ttl_expression", "codec_expression"):
            if row.get(key):
                if isinstance(row[key], str):
                    self.r.expression(path, loc + "." + key, "clickhouse", row[key], oid,
                                      interpretation="declared_expression", default_kind=default_kind)
                else:
                    self.gap(path, "invalid_metadata", "Column expression must be a string.", loc + "." + key)
        if default_kind and not row.get("default_expression"):
            self.gap(path, "missing_expression", "Column default declaration lacks its expression.", loc)
        if row.get("is_in_sorting_key") or row.get("is_in_primary_key"):
            self.gap(path, "key_not_uniqueness", "Index membership is not a uniqueness constraint.", loc)
        self.runtime_gaps(path, loc, row["type"])

    def json(self, path, value):
        if not isinstance(value, dict):
            self.gap(path, "unsupported_shape", "Expected a native FORMAT JSON object.")
            self.r.cover(path, "unsupported")
            return
        response, loc = value, "$"
        if not isinstance(response, dict) or not isinstance(response.get("meta"), list) or not isinstance(response.get("data"), list):
            self.gap(path, "invalid_response", "FORMAT JSON requires meta and data arrays.", loc)
            self.r.cover(path, "unsupported")
            return
        self.unknown(path, loc, response, _RESPONSE_KEYS)
        oid = self.r.object(path, loc, "query_result", path,
                            query_result_schema=response["meta"],
                            response_metadata={k: v for k, v in response.items() if k not in ("meta", "data")},
                            physical_schema_verified=False)
        self.gap(path, "query_provenance_unresolved", "Native FORMAT JSON does not identify its originating query, server, snapshot, namespace or catalogue scope; row signatures are candidates only.", loc)
        for i, header in enumerate(response["meta"]):
            if not isinstance(header, dict) or not all(isinstance(header.get(k), str) and header[k] for k in ("name", "type")):
                self.gap(path, "invalid_header", "Query-result header requires name and type strings.", f"{loc}.meta[{i}]")
            else:
                self.unknown(path, f"{loc}.meta[{i}]", header, {"name", "type"})
        rows = response["data"]
        if type(response.get("rows")) is not int or response["rows"] != len(rows):
            self.gap(path, "row_count_mismatch", "Missing or inconsistent result row count.", loc + ".rows")
        limit_count = response.get("rows_before_limit_at_least")
        if limit_count is not None and (type(limit_count) is not int or limit_count > len(rows)):
            self.gap(path, "limited_result", "Result limit evidence does not establish a complete catalogue.", loc)
        if response.get("exception"):
            self.gap(path, "query_exception", "Response reports an exception; no catalogue rows are interpreted.", loc + ".exception")
            self.r.cover(path, "partial")
            return
        if not rows:
            self.gap(path, "empty_export", "Empty output does not establish an empty source catalogue.", loc + ".data")
        for i, row in enumerate(rows):
            row_loc = f"{loc}.data[{i}]"
            if not isinstance(row, dict):
                self.gap(path, "invalid_row", "FORMAT JSON data rows must be objects.", row_loc)
            elif {"database", "name", "engine"} <= row.keys():
                self.table(path, row_loc, row)
            elif {"database", "table", "name", "type"} <= row.keys():
                self.column(path, row_loc, row, "system.columns", oid)
            elif {"name", "type", "default_type", "default_expression"} <= row.keys():
                self.column(path, row_loc, row, "DESCRIBE", oid)
            else:
                self.gap(path, "uninterpreted_result_row", "Query data retained as source; no supported catalogue signature.", row_loc)
        self.r.cover(path, "parsed")


def parse(files):
    parser = _Parser(files)
    for path, text in sorted(files.items()):
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".sql":
            parser.sql(path, "$sql", text)
        elif suffix == ".json":
            parser.r.expression(path, "$json", "json", text, interpretation="preserved_original")
            try:
                value = read_json(text)
            except ValueError as exc:
                parser.gap(path, str(exc), "Invalid or unbounded JSON; source retained without interpretation.")
                parser.r.cover(path, "unsupported")
                continue
            parser.json(path, value)
        else:
            parser.gap(path, "unsupported_format", "Only SQL and FORMAT JSON snapshots are supported.")
            parser.r.cover(path, "unsupported")
    return parser.r.finish()
