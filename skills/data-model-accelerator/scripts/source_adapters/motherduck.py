"""Offline DuckDB-dialect evidence, without opening DuckDB or MotherDuck."""
from pathlib import PurePosixPath
import re

from .base import Report, read_json
from .sql import parse_sql


CAPABILITY = {
    "formats": ["DuckDB-dialect .sql", "DuckDB catalogue JSON row arrays"],
    "interpretation": "bounded_static_extraction",
    "acquisition": "supplied_exports",
    "limitations": [
        "No SQL, ATTACH, extensions, clients, files or network are executed or opened by this adapter.",
        "Row signatures do not authenticate query provenance, cloud placement or export completeness.",
        "Local DuckDB success is not MotherDuck qualification, permission validation or business acceptance.",
        "Runtime, dynamic SQL, external data and sharing require separately authorized native evidence.",
    ],
}

_NATIVE_BASE = set("database_name database_oid schema_name schema_oid table_name table_oid comment tags internal temporary".split())
_TABLE_KEYS = _NATIVE_BASE | set("has_primary_key estimated_size column_count index_count check_constraint_count sql".split())
_VIEW_KEYS = set("database_name database_oid schema_name schema_oid view_name view_oid comment tags internal temporary column_count sql is_bound".split())
_COLUMN_KEYS = _NATIVE_BASE | set("column_name column_index column_default is_nullable data_type data_type_id character_maximum_length numeric_precision numeric_precision_radix numeric_scale".split())
_CONSTRAINT_KEYS = _NATIVE_BASE | set("constraint_index constraint_type constraint_text expression constraint_column_indexes constraint_column_names constraint_name referenced_table referenced_column_names".split())
_INFO_BASE = set("table_catalog table_schema table_name".split())
_INFO_TABLE_KEYS = _INFO_BASE | set("table_type self_referencing_column_name reference_generation user_defined_type_catalog user_defined_type_schema user_defined_type_name is_insertable_into is_typed commit_action".split())
_INFO_COLUMN_KEYS = _INFO_BASE | set("column_name ordinal_position column_default is_nullable data_type character_maximum_length character_octet_length numeric_precision numeric_precision_radix numeric_scale datetime_precision interval_type interval_precision character_set_catalog character_set_schema character_set_name collation_catalog collation_schema collation_name domain_catalog domain_schema domain_name udt_catalog udt_schema udt_name scope_catalog scope_schema scope_name maximum_cardinality dtd_identifier is_self_referencing is_identity identity_generation identity_start identity_increment identity_maximum identity_minimum identity_cycle is_generated generation_expression is_updatable".split())
_INFO_CONSTRAINT_KEYS = _INFO_BASE | set("constraint_catalog constraint_schema constraint_name constraint_type is_deferrable initially_deferred enforced nulls_distinct".split())
_DATABASE_KEYS = set("database_name database_oid path comment tags internal type readonly".split())


def _string(value):
    return isinstance(value, str) and bool(value.strip())


def _oid(value):
    return value if type(value) is int and value >= 0 else None


def _name(parts):
    # Components, not this display name, are the lossless namespace evidence.
    return ".".join('"' + p.replace('"', '""') + '"' for p in parts if p is not None)


class _Parser:
    def __init__(self, files):
        self.r = Report("motherduck", files)
        self.identities = set()

    def gap(self, path, code, message, loc="$"):
        self.r.gap(path, code, message, locator=loc)

    def unknown(self, path, loc, row, keys):
        if set(row) - keys:
            self.gap(path, "unknown_fields", "Uninterpreted fields retained: " + ", ".join(sorted(set(row) - keys)), loc)
        for key in ("comment", "constraint_name"):
            if row.get(key) is not None and not isinstance(row[key], str):
                self.gap(path, "invalid_metadata", key + " must be a string or null; raw value retained.", loc)
        for key in ("table_oid", "view_oid", "database_oid", "schema_oid"):
            if row.get(key) is not None and _oid(row[key]) is None:
                self.gap(path, "invalid_metadata", key + " must be a non-negative integer or null; raw value retained without a normalized identity.", loc)
        for key in ("internal", "temporary", "has_primary_key"):
            if row.get(key) is not None and type(row[key]) is not bool:
                self.gap(path, "invalid_metadata", key + " must be a boolean or null; raw value retained.", loc)

    def scope(self, path, loc, row, info=False, view=False):
        keys = ("table_catalog", "table_schema", "table_name") if info else (
            "database_name", "schema_name", "view_name" if view else "table_name")
        parts = [row.get(k) if _string(row.get(k)) else None for k in keys]
        if None in parts:
            self.gap(path, "namespace_unresolved", "Missing database, schema or relation identity; filenames and session defaults are not used.", loc)
        return parts

    def register(self, path, loc, kind, parts):
        if None in parts:
            return
        identity = (kind, tuple(parts))
        if identity in self.identities:
            self.gap(path, "duplicate_identity", "Repeated catalogue identity retained separately; snapshot versions are not merged.", loc)
        self.identities.add(identity)

    def risks(self, path, loc, text):
        checks = (
            (r"\b(?:ATTACH|DETACH|INSTALL|LOAD|IMPORT|EXPORT|COPY|PRAGMA|SET|USE)\b", "runtime_command",
             "Session, attachment, extension or data movement command preserved without execution or effects."),
            (r"\b(?:read_\w+|\w*_scan|httpfs|sqlite_scan|postgres_scan|delta_scan|iceberg_scan)\b|(?:https?|s3|gs|azure)://", "external_data",
             "External data or extension access requires explicit resource binding and separately authorized native validation."),
            (r"\b(?:SECRET|motherduck_token|access_token|password|credential_chain|AWS_SECRET_ACCESS_KEY)\b", "credentials_or_secrets",
             "Credential-related declaration detected; source must be sanitized before sharing. Credentials are not resolved."),
            (r"\b(?:query|query_table|EXECUTE|PREPARE|CALL)\b|\{\{|\{%", "dynamic_sql",
             "Dynamic SQL or runtime dispatch preserved; resolved code and dependencies are unverified."),
            (r"\b(?:SHARE|GRANT|REVOKE|md_information_schema|md_run)\b", "shared_permissions",
             "MotherDuck sharing, permissions and execution placement require cloud-specific evidence."),
        )
        for pattern, code, message in checks:
            if re.search(pattern, text, re.I):
                self.gap(path, code, message, loc)

    def sql(self, path, loc, text, owner=None):
        if not _string(text):
            self.gap(path, "invalid_sql", "Expected a non-empty SQL string.", loc)
            return
        parse_sql(self.r, path, text, "duckdb", owner_id=owner, locator=loc)
        self.risks(path, loc, text)
        self.gap(path, "runtime_unverified", "DuckDB dialect parsing does not establish MotherDuck runtime support, cloud placement, effective access or current attachment bindings.", loc)

    def relation(self, path, loc, row, view=False, info=False):
        self.unknown(path, loc, row, _INFO_TABLE_KEYS if info else (_VIEW_KEYS if view else _TABLE_KEYS))
        parts = self.scope(path, loc, row, info, view)
        if parts[2] is None:
            self.gap(path, "invalid_relation", "Relation name must be a non-empty string.", loc)
            return
        if info:
            view = row.get("table_type") == "VIEW"
            if row.get("table_type") not in ("BASE TABLE", "LOCAL TEMPORARY", "VIEW"):
                self.gap(path, "unknown_table_type", "Table type retained without interpretation.", loc)
        self.register(path, loc, "relation", parts)
        oid = self.r.object(path, loc, "view_catalogue_candidate" if view else "table_catalogue_candidate",
                            _name(parts), native_id=_oid(row.get("view_oid" if view else "table_oid")),
                            namespace_components=parts, database=parts[0], schema=parts[1],
                            table=parts[2], comment=row.get("comment"), has_primary_key=row.get("has_primary_key"),
                            raw_metadata=row, provenance="row_signature_only", namespace_verified=False,
                            oid_scope="export_snapshot_only", cloud_placement="unverified")
        if row.get("sql") is not None:
            self.sql(path, loc + ".sql", row["sql"], oid)
        else:
            self.gap(path, "missing_definition", "No native creation SQL supplied; relation structure and view logic are incomplete.", loc)

    def column(self, path, loc, row, info=False):
        self.unknown(path, loc, row, _INFO_COLUMN_KEYS if info else _COLUMN_KEYS)
        parts = self.scope(path, loc, row, info)
        if not _string(row.get("column_name")) or not _string(row.get("data_type")):
            self.gap(path, "invalid_column", "Column name and native data type must be non-empty strings.", loc)
            return
        self.register(path, loc, "column", parts + [row["column_name"]])
        ordinal_key = "ordinal_position" if info else "column_index"
        ordinal = row.get(ordinal_key)
        if ordinal is not None and (type(ordinal) is not int or ordinal < (1 if info else 0)):
            self.gap(path, "invalid_ordinal", "Column ordinal has an invalid type or range; original value retained.", loc)
        nullable = row.get("is_nullable")
        if nullable is not None and (nullable not in ("YES", "NO") if info else type(nullable) is not bool):
            self.gap(path, "invalid_nullability", "Unexpected native nullability value retained without boolean conversion.", loc)
        oid = self.r.object(path, loc, "column_catalogue_candidate", row["column_name"],
                            namespace_components=parts, data_type=row["data_type"],
                            column_default=row.get("column_default"), comment=row.get("comment"),
                            native_ordinal=ordinal, ordinal_field=ordinal_key, is_nullable=nullable,
                            raw_metadata=row, provenance="row_signature_only", namespace_verified=False)
        if None not in parts:
            self.r.dependency(path, loc, oid, _name(parts), kind="candidate_column_of",
                              target_components=parts, resolution="unresolved")
        if row.get("column_default") is not None:
            if isinstance(row["column_default"], str):
                self.r.expression(path, loc + ".column_default", "duckdb", row["column_default"], oid,
                                  interpretation="declared_default")
                self.risks(path, loc + ".column_default", row["column_default"])
            else:
                self.gap(path, "invalid_default", "Default expression must be a string or null.", loc)

    def constraint(self, path, loc, row, info=False):
        self.unknown(path, loc, row, _INFO_CONSTRAINT_KEYS if info else _CONSTRAINT_KEYS)
        parts = self.scope(path, loc, row, info)
        for key in ("constraint_column_names", "referenced_column_names"):
            if row.get(key) is not None and (not isinstance(row[key], list) or not all(_string(v) for v in row[key])):
                self.gap(path, "invalid_constraint", key + " must be an array of non-empty strings.", loc)
        if row.get("constraint_type") not in ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "NOT NULL"):
            self.gap(path, "unknown_constraint_type", "Constraint type retained without interpretation.", loc)
        label = row.get("constraint_name") if _string(row.get("constraint_name")) else _name(parts)
        oid = self.r.object(path, loc, "constraint_catalogue_candidate", label or "Unbound constraint at " + loc,
                            namespace_components=parts, constraint_type=row.get("constraint_type"),
                            source_columns=row.get("constraint_column_names"), raw_metadata=row,
                            enforcement="not_verified", provenance="row_signature_only")
        if None not in parts:
            self.r.dependency(path, loc, oid, _name(parts), kind="candidate_constraint_of",
                              target_components=parts, resolution="unresolved")
        for key in ("constraint_text", "expression"):
            if row.get(key) is not None:
                if isinstance(row[key], str):
                    self.r.expression(path, loc + "." + key, "duckdb", row[key], oid,
                                      interpretation="declared_constraint")
                else:
                    self.gap(path, "invalid_constraint", "Constraint expression must be a string or null.", loc)
        if row.get("constraint_type") == "FOREIGN KEY":
            reference, columns, sources = row.get("referenced_table"), row.get("referenced_column_names"), row.get("constraint_column_names")
            if _string(reference) and isinstance(columns, list) and isinstance(sources, list) and columns and len(columns) == len(sources) and all(_string(v) for v in columns + sources):
                self.r.dependency(path, loc + ".referenced_table", oid, reference,
                                  kind="foreign_key", source_columns=sources, target_columns=columns,
                                  resolution="unresolved", target_namespace="not_supplied", enforcement="not_verified")
                self.gap(path, "foreign_key_namespace_unresolved", "Referenced table name is retained literally; its database/schema are not inferred from the source relation.", loc)
            else:
                self.gap(path, "foreign_key_incomplete", "Foreign key lacks a referenced table and aligned source/target column names.", loc)

    def json(self, path, value):
        if not isinstance(value, list):
            self.gap(path, "unsupported_shape", "Expected a JSON row array exported from a documented catalogue query; no MotherDuck JSON envelope is assumed.")
            self.r.cover(path, "unsupported")
            return
        self.gap(path, "query_provenance_unresolved", "Row signatures cannot verify originating query, source version, filters, principal, snapshot or local/cloud placement.")
        if not value:
            self.gap(path, "empty_export", "Empty result does not establish an empty or complete catalogue.")
        for i, row in enumerate(value):
            loc = "$[%d]" % i
            if not isinstance(row, dict):
                self.gap(path, "invalid_row", "Catalogue rows must be objects.", loc)
                continue
            info = "table_catalog" in row or "table_schema" in row
            if "column_name" in row and "data_type" in row:
                self.column(path, loc, row, info)
            elif "constraint_type" in row:
                self.constraint(path, loc, row, info)
            elif "view_name" in row:
                self.relation(path, loc, row, view=True)
            elif "table_type" in row:
                self.relation(path, loc, row, info=True)
            elif "table_name" in row and ("has_primary_key" in row or "sql" in row):
                self.relation(path, loc, row)
            elif {"database_name", "type", "readonly"} <= row.keys():
                self.unknown(path, loc, row, _DATABASE_KEYS)
                if not _string(row["database_name"]) or not _string(row["type"]) or type(row["readonly"]) is not bool:
                    self.gap(path, "invalid_database", "Database metadata requires name/type strings and a readonly boolean.", loc)
                    continue
                self.r.object(path, loc, "database_catalogue_candidate", row["database_name"], native_id=_oid(row.get("database_oid")),
                              raw_metadata=row, provenance="row_signature_only", cloud_placement="unverified")
                self.gap(path, "attachment_identity_unverified", "Attachment aliases and type do not prove MotherDuck organization, database identity or effective shared permissions.", loc)
            else:
                self.gap(path, "unsupported_row", "No supported catalogue row signature; original source retained.", loc)
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
                parser.gap(path, str(exc), "Malformed or unbounded JSON retained without interpretation.")
                parser.r.cover(path, "unsupported")
                continue
            # Review hints only, never credential resolution or executable paths.
            parser.risks(path, "$json", text)
            parser.json(path, value)
        else:
            parser.gap(path, "unsupported_format", "Only supplied SQL and catalogue JSON row arrays are supported.")
            parser.r.cover(path, "unsupported")
    return parser.r.finish()
