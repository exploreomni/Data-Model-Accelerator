#!/usr/bin/env python3
"""Read-only raw catalogue and source-binding contract checks; Python 3.9+.

Completeness describes the declared visible scope and selected source references.
It does not authenticate exports, discover omitted sources, or prove warehouse
permissions, keys, business semantics, CDC/replay behavior, or production safety.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_matrix import WAREHOUSES, get_platform


SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PROVIDERS = set(WAREHOUSES)
ORIGINS = {"live_metadata", "provided_export", "synthetic"}
COMPONENTS_REQUIRED = {"objects", "columns"}
METADATA_FIELDS = ("comments", "relationships", "ownership", "security", "replication", "statistics")
TABULAR_TYPES = {"TABLE", "BASE TABLE", "VIEW", "MATERIALIZED VIEW", "EXTERNAL TABLE", "DYNAMIC TABLE", "STREAMING TABLE", "FOREIGN TABLE", "ICEBERG TABLE"}


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def valid_sha(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def selected_file(value):
    path = Path(value).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Selected metadata file must not be a symlink")
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise ValueError("Selected metadata path must be canonical; symlink or redirected ancestor detected")
    if not resolved.is_file():
        raise ValueError("Selected metadata input must be a regular file")
    return resolved


def export_file(root, relative):
    if not nonempty(relative):
        raise ValueError("Extraction artifact_path must be a relative file path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("Extraction artifact path must remain beneath catalogue folder")
    for index in range(1, len(path.parts) + 1):
        if root.joinpath(*path.parts[:index]).is_symlink():
            raise ValueError("Symlink in extraction artifact path")
    result = (root / path).resolve(strict=True)
    result.relative_to(root)
    if not result.is_file():
        raise ValueError("Extraction artifact must be a regular file")
    return result


def read_json(path):
    raw = path.read_bytes()
    data = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError("Metadata input must be a JSON object")
    return data, hashlib.sha256(raw).hexdigest()


def verify(catalogue_path, bindings_path, max_age_hours=24, now=None):
    errors, gaps, limitations = [], [], [
        "Checks only declared visible scope, export integrity, and declared source-reference bindings; not parser completeness or evidence authenticity.",
        "Metadata enrichment does not prove keys, constraints, access enforcement, replication ordering, replay, business correctness, or deployment readiness.",
        "source_snapshot_sha256 is syntax-checked here; its alignment with the selected repository snapshot must be checked by the caller.",
    ]
    report = {"schema_version": 1, "catalogue_context_complete": False, "errors": errors,
              "gaps": gaps, "limitations": limitations, "catalogue_sha256": None,
              "source_snapshot_sha256": None, "origin": None,
              "counts": {"scopes": 0, "extractions": 0, "objects": 0, "columns": 0,
                         "expected_references": 0, "references": 0, "resolved_references": 0}}

    def require(condition, message):
        if not condition:
            errors.append(message)
        return condition

    def array(parent, name, label):
        value = parent.get(name)
        if not isinstance(value, list):
            errors.append(label + "." + name + " must be an array")
            return []
        return value

    def path_tuple(value, label):
        if not require(isinstance(value, list) and bool(value) and all(nonempty(v) for v in value),
                       label + " must be a nonempty array of nonempty path components"):
            return None
        return tuple(value)

    try:
        catalogue_path = selected_file(catalogue_path)
        bindings_path = selected_file(bindings_path)
        require(catalogue_path != bindings_path, "Catalogue and bindings must be distinct files")
        catalogue, report["catalogue_sha256"] = read_json(catalogue_path)
        bindings, _ = read_json(bindings_path)
        report["origin"] = catalogue.get("origin")
        report["source_snapshot_sha256"] = bindings.get("source_snapshot_sha256")
        for label, value, kind in (("catalogue", catalogue, "warehouse_raw_catalogue"),
                                   ("bindings", bindings, "warehouse_catalogue_bindings")):
            require(type(value.get("schema_version")) is int and value["schema_version"] == 1,
                    label + ".schema_version must be integer 1")
            require(value.get("kind") == kind, label + ".kind is invalid")
        provider = catalogue.get("provider")
        if require(isinstance(provider, str) and provider in PROVIDERS, "catalogue.provider is invalid"):
            report["provider"] = provider
            report["provider_context_requirements"] = get_platform(provider)["metadata"]
            limitations.append("Provider identity requirements are guidance, not authenticated identity evidence; preserve native namespace and visibility limits.")
        require(isinstance(report["origin"], str) and report["origin"] in ORIGINS, "catalogue.origin is invalid")
        if report["origin"] == "synthetic":
            limitations.append("Synthetic catalogue fixture; it is not live warehouse evidence.")
        elif report["origin"] == "provided_export":
            limitations.append("Provided export provenance is declared, not independently authenticated by this checker.")
        require(valid_sha(bindings.get("catalogue_sha256")), "bindings.catalogue_sha256 must be lowercase SHA-256")
        require(bindings.get("catalogue_sha256") == report["catalogue_sha256"], "Bindings catalogue hash does not match the selected catalogue")
        require(valid_sha(report["source_snapshot_sha256"]), "bindings.source_snapshot_sha256 must be lowercase SHA-256")

        age_valid = require(type(max_age_hours) in (int, float) and math.isfinite(max_age_hours) and max_age_hours > 0,
                            "max_age_hours must be a finite positive number")
        clock = now if now is not None else datetime.now(timezone.utc)
        clock_valid = require(isinstance(clock, datetime) and clock.tzinfo is not None and clock.utcoffset() is not None,
                              "now must be a timezone-aware datetime")
        captured = catalogue.get("captured_at")
        if require(nonempty(captured), "catalogue.captured_at must be a timezone-aware ISO8601 string"):
            try:
                captured_time = datetime.fromisoformat(captured[:-1] + "+00:00" if captured.endswith("Z") else captured)
                if require(captured_time.tzinfo is not None and captured_time.utcoffset() is not None,
                           "catalogue.captured_at must include a timezone") and clock_valid:
                    age = clock.astimezone(timezone.utc) - captured_time.astimezone(timezone.utc)
                    require(age >= -timedelta(minutes=5), "Catalogue timestamp is more than five minutes in the future")
                    if age_valid and age > timedelta(hours=max_age_hours):
                        gaps.append("Catalogue is stale for the configured max_age_hours")
            except (ValueError, OverflowError):
                errors.append("catalogue.captured_at is not valid ISO8601")

        context = catalogue.get("context")
        if not require(isinstance(context, dict), "catalogue.context must be an object"):
            context = {}
        require(nonempty(context.get("platform_instance")), "context.platform_instance is required")
        require(nonempty(context.get("principal")), "context.principal is required")
        scopes, scope_identities = {}, set()
        declared_scopes = array(context, "scope", "context")
        require(bool(declared_scopes), "At least one explicit visible scope is required, even for an empty schema")
        for item in declared_scopes:
            if not require(isinstance(item, dict), "Each context.scope entry must be an object"):
                continue
            if not require(all(nonempty(item.get(k)) for k in ("scope_id", "catalog", "schema", "location")),
                           "Scope requires scope_id, catalog, schema, and location"):
                continue
            sid = item["scope_id"]
            require(sid not in scopes, "Duplicate scope_id: " + sid)
            identity = (item["catalog"], item["schema"], item["location"])
            require(identity not in scope_identities, "Duplicate declared scope identity: " + sid)
            scope_identities.add(identity)
            scopes[sid] = item
        report["counts"]["scopes"] = len(scopes)

        coverage = catalogue.get("coverage")
        if not require(isinstance(coverage, dict), "catalogue.coverage must be an object"):
            coverage = {}
        coverage_status = coverage.get("status")
        require(coverage_status in ("complete_for_visible_scope", "partial", "unavailable"), "catalogue.coverage.status is invalid")
        if coverage_status != "complete_for_visible_scope":
            gaps.append("Catalogue visibility is not complete for its declared scope")
        declared_gaps = array(coverage, "gaps", "coverage")
        if declared_gaps:
            gaps.append("Catalogue coverage declares " + str(len(declared_gaps)) + " blocking gap(s)")

        extractions = {}
        complete_components = {sid: set() for sid in scopes}
        for item in array(catalogue, "extractions", "catalogue"):
            if not require(isinstance(item, dict), "Each extraction must be an object"):
                continue
            if not require(all(nonempty(item.get(k)) for k in ("extraction_id", "scope_id", "component")),
                           "Extraction requires extraction_id, scope_id, and component"):
                continue
            eid, sid, component = item["extraction_id"], item["scope_id"], item["component"]
            require(eid not in extractions, "Duplicate extraction_id: " + eid)
            require(sid in scopes, "Extraction references missing scope: " + eid)
            status = item.get("status")
            require(status in ("complete", "partial", "failed", "unavailable"), "Invalid extraction status: " + eid)
            require("query_id" in item and (item["query_id"] is None or nonempty(item["query_id"])), "Extraction query_id must be a nonempty string or null: " + eid)
            require(type(item.get("pagination_complete")) is bool, "Extraction pagination_complete must be boolean: " + eid)
            hash_valid = require(valid_sha(item.get("sha256")), "Extraction sha256 must be lowercase SHA-256: " + eid)
            required = component in COMPONENTS_REQUIRED
            if status != "complete" or item.get("pagination_complete") is not True:
                (gaps if required else limitations).append("Extraction is not complete/paginated: " + eid + " (" + component + ")")
            artifact_valid = False
            try:
                artifact = export_file(catalogue_path.parent, item.get("artifact_path"))
                if artifact in (catalogue_path, bindings_path):
                    errors.append("Extraction evidence cannot be the catalogue or bindings file: " + eid)
                elif hash_valid:
                    artifact_valid = require(digest(artifact) == item["sha256"], "Extraction artifact hash mismatch: " + eid)
            except FileNotFoundError:
                (errors if required else limitations).append("Extraction artifact is missing: " + eid)
                if not required:
                    limitations.append("A complete review bundle must still contain the optional extraction's hashed failure/unavailable receipt: " + eid)
            except (OSError, ValueError) as exc:
                errors.append("Invalid extraction artifact " + eid + ": " + str(exc))
            extractions[eid] = dict(item, integrity_verified=artifact_valid)
            if sid in scopes and status == "complete" and item.get("pagination_complete") is True and artifact_valid:
                complete_components[sid].add(component)
        report["counts"]["extractions"] = len(extractions)
        for sid, present in complete_components.items():
            for component in sorted(COMPONENTS_REQUIRED - present):
                gaps.append("Scope " + sid + " lacks a complete hash-verified " + component + " export")

        objects, object_identities = {}, set()
        for item in array(catalogue, "objects", "catalogue"):
            if not require(isinstance(item, dict), "Each catalogue object must be an object"):
                continue
            if not require(nonempty(item.get("object_id")) and nonempty(item.get("scope_id")), "Object requires object_id and scope_id"):
                continue
            oid, sid = item["object_id"], item["scope_id"]
            require(oid not in objects, "Duplicate object_id: " + oid)
            require(sid in scopes, "Object references missing scope: " + oid)
            require(nonempty(item.get("object_type")), "Object object_type is required: " + oid)
            identity = item.get("identity")
            if not require(isinstance(identity, dict) and all(nonempty(identity.get(k)) for k in ("catalog", "schema", "name")),
                           "Object identity requires catalog, schema, and name: " + oid):
                identity = {}
            else:
                key = (identity["catalog"], identity["schema"], identity["name"])
                require(key not in object_identities, "Duplicate physical object identity: " + oid)
                object_identities.add(key)
                if sid in scopes:
                    require(all(identity[k] == scopes[sid][k] for k in ("catalog", "schema")), "Object identity differs from its exact declared scope: " + oid)
            columns = set()
            for column in array(item, "columns", oid):
                if not require(isinstance(column, dict), "Column must be an object: " + oid):
                    continue
                path = path_tuple(column.get("path"), "Column path in " + oid)
                require(nonempty(column.get("data_type")), "Column data_type is required: " + oid)
                require("nullable" in column and (column["nullable"] is None or type(column["nullable"]) is bool), "Column nullable must be boolean or null: " + oid)
                if path is not None:
                    require(path not in columns, "Duplicate column path: " + oid + ": " + repr(path))
                    columns.add(path)
            object_type = item.get("object_type")
            if isinstance(object_type, str) and object_type.upper().replace("_", " ") in TABULAR_TYPES and not columns:
                gaps.append("Table/view object has no declared columns; its schema cannot establish model context: " + oid)
            metadata = item.get("metadata_status")
            if require(isinstance(metadata, dict), "Object metadata_status must be an object: " + oid):
                unknown = []
                for field in METADATA_FIELDS:
                    value = metadata.get(field)
                    require(value in ("observed", "partial", "unknown"), "Invalid/missing metadata_status." + field + ": " + oid)
                    if value in ("partial", "unknown"):
                        unknown.append(field + "=" + value)
                if unknown:
                    limitations.append("Enrichment is not fully observed for " + oid + ": " + ", ".join(unknown))
            evidenced_components = set()
            evidence = array(item, "evidence", oid)
            require(bool(evidence), "Object requires extraction evidence: " + oid)
            for citation in evidence:
                if not require(isinstance(citation, dict) and nonempty(citation.get("extraction_id")) and nonempty(citation.get("locator")),
                               "Object evidence requires extraction_id and locator: " + oid):
                    continue
                extraction = extractions.get(citation["extraction_id"])
                if require(extraction is not None, "Object evidence references missing extraction: " + oid):
                    same_scope = require(extraction["scope_id"] == sid, "Object evidence extraction belongs to a different scope: " + oid)
                    if same_scope and extraction["integrity_verified"] and extraction["status"] == "complete" and extraction["pagination_complete"] is True:
                        evidenced_components.add(extraction["component"])
            for component in sorted(COMPONENTS_REQUIRED - evidenced_components):
                gaps.append("Object " + oid + " lacks complete " + component + " extraction evidence")
            objects[oid] = {"identity": identity, "column_paths": columns, "scope_id": sid}
            report["counts"]["columns"] += len(columns)
        report["counts"]["objects"] = len(objects)

        expected = array(bindings, "expected_reference_ids", "bindings")
        valid_expected = require(bool(expected) and all(nonempty(ref) for ref in expected), "A nonempty expected_reference_ids set is required for complete source binding validation")
        if valid_expected:
            require(len(set(expected)) == len(expected), "Duplicate expected_reference_ids")
        expected_set = set(ref for ref in expected if nonempty(ref))
        references = array(bindings, "references", "bindings")
        require(bool(references), "Nonempty bindings.references are required for complete model-design context")
        report["counts"]["expected_references"] = len(expected_set)
        seen = set()
        for item in references:
            reference_errors_before = len(errors)
            if not require(isinstance(item, dict), "Each binding reference must be an object"):
                continue
            if not require(nonempty(item.get("reference_id")), "Binding requires reference_id"):
                continue
            rid = item["reference_id"]
            require(rid not in seen, "Duplicate reference_id: " + rid)
            require(rid in expected_set, "Undeclared reference_id: " + rid)
            seen.add(rid)
            require(nonempty(item.get("source_reference")), "Binding source_reference is required: " + rid)
            require(nonempty(item.get("evidence")), "Binding evidence explanation is required: " + rid)
            status = item.get("status")
            require(status in ("resolved", "unresolved", "ambiguous"), "Invalid binding status: " + rid)
            namespace = item.get("namespace")
            namespace_valid = require(isinstance(namespace, dict) and all(nonempty(namespace.get(k)) for k in ("platform_instance", "catalog", "schema")),
                                      "Binding namespace requires platform_instance, catalog, and schema: " + rid)
            requested_columns = set()
            for value in array(item, "column_paths", rid):
                path = path_tuple(value, "Binding column path in " + rid)
                if path is not None:
                    require(path not in requested_columns, "Duplicate binding column path: " + rid)
                    requested_columns.add(path)
            if status in ("unresolved", "ambiguous"):
                gaps.append("Source binding is " + status + ": " + rid)
            elif status == "resolved":
                oid = item.get("object_id")
                if not require(nonempty(oid) and oid in objects, "Resolved binding references missing object: " + rid):
                    continue
                obj = objects[oid]
                if not obj["column_paths"]:
                    gaps.append("Resolved consumable object has no declared columns: " + rid)
                if namespace_valid:
                    require(namespace["platform_instance"] == context.get("platform_instance"), "Binding platform_instance does not match catalogue: " + rid)
                    require(all(namespace[k] == obj["identity"].get(k) for k in ("catalog", "schema")), "Binding namespace does not exactly match object identity: " + rid)
                require(requested_columns <= obj["column_paths"], "Resolved binding contains unknown or case-mismatched column paths: " + rid)
                if len(errors) == reference_errors_before and obj["column_paths"]:
                    report["counts"]["resolved_references"] += 1
        for rid in sorted(expected_set - seen):
            errors.append("Expected source reference omitted from bindings: " + rid)
        report["counts"]["references"] = len(seen)
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        errors.append("Invalid catalogue/bindings input: " + str(exc))
    report["catalogue_context_complete"] = not errors and not gaps
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue_path", type=Path)
    parser.add_argument("bindings_path", type=Path)
    parser.add_argument("--max-age-hours", type=float, default=24)
    args = parser.parse_args(argv)
    report = verify(args.catalogue_path, args.bindings_path, args.max_age_hours)
    print(json.dumps(report, indent=2))
    return 0 if report["catalogue_context_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
