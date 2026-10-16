"""Bounded, offline BigQuery REST/Dataform exports and GoogleSQL extraction."""
from pathlib import PurePosixPath
import re

from .base import Report, read_json
from .sql import parse_sql


CAPABILITY = {
    "formats": ["GoogleSQL .sql", "BigQuery REST v2 Table/Routine JSON",
                "Dataform REST v1 compilationResults.query JSON", "SQLX evidence only"],
    "interpretation": "bounded_static_extraction",
    "acquisition": "supplied_exports",
    "limitations": [
        "No API requests, SQL execution, SQLX/JavaScript compilation, or native validation.",
        "REST list projections, pagination, permissions and export scope can omit objects or definitions.",
        "Dynamic SQL, legacy SQL, non-SQL routines and unknown fields remain unresolved.",
        "Dependency targets and physical metadata require independent catalogue validation.",
    ],
}

_TABLE_KEYS = set("kind etag id selfLink tableReference friendlyName description labels schema "
                  "timePartitioning rangePartitioning clustering requirePartitionFilter numBytes "
                  "numLongTermBytes numRows creationTime expirationTime lastModifiedTime type view "
                  "materializedView materializedViewStatus externalDataConfiguration biglakeConfiguration "
                  "location streamingBuffer encryptionConfiguration snapshotDefinition defaultCollation "
                  "defaultRoundingMode cloneDefinition numTimeTravelPhysicalBytes numTotalLogicalBytes "
                  "numActiveLogicalBytes numLongTermLogicalBytes numTotalPhysicalBytes numActivePhysicalBytes "
                  "numLongTermPhysicalBytes numPartitions maxStaleness tableConstraints resourceTags "
                  "replicas externalCatalogTableOptions partitionDefinition hivePartitioningOptions".split())
_FIELD_KEYS = set("name type mode fields description policyTags maxLength precision scale collation "
                  "defaultValueExpression roundingMode rangeElementType categories foreignTypeDefinition "
                  "dataPolicies".split())
_ROUTINE_KEYS = set("etag routineReference routineType creationTime lastModifiedTime language arguments "
                    "returnType returnTableType importedLibraries definitionBody description determinismLevel "
                    "strictMode remoteFunctionOptions sparkOptions dataGovernanceType pythonOptions "
                    "externalRuntimeOptions buildStatus".split())
_ACTION_KINDS = {"relation", "operations", "assertion", "declaration", "notebook", "dataPreparation"}
_RELATION_KEYS = set("dependencyTargets disabled tags relationDescriptor relationType selectQuery "
                     "preOperations postOperations incrementalTableConfig partitionExpression clusterExpressions "
                     "partitionExpirationDays requirePartitionFilter additionalOptions connection tableFormat "
                     "fileFormat storageUri".split())
_INCREMENTAL_KEYS = set("incrementalSelectQuery refreshDisabled uniqueKeyParts updatePartitionFilter "
                        "incrementalPreOperations incrementalPostOperations".split())


class _Parser:
    def __init__(self, files):
        self.r = Report("bigquery", files)
        self.identities = set()
        self.references = []

    def gap(self, path, code, message, locator):
        self.r.gap(path, code, message, locator=locator)

    def unknown(self, path, locator, value, supported):
        keys = sorted(set(value) - supported)
        if keys:
            self.gap(path, "unknown_fields", "Preserved without interpretation: " + ", ".join(keys), locator)

    def mapping(self, path, locator, value):
        if not isinstance(value, dict):
            self.gap(path, "invalid_metadata", "Expected a JSON object.", locator)
            return None
        return value

    def sequence(self, path, locator, value):
        if not isinstance(value, list):
            self.gap(path, "invalid_metadata", "Expected a JSON array.", locator)
            return []
        return value

    def target(self, path, locator, value, dataform=False, routine=False):
        if value is None:
            self.gap(path, "missing_identity", "Explicit project, dataset and object identifiers are required.", locator)
            return None
        value = self.mapping(path, locator, value)
        if value is None:
            return None
        keys = ("database", "schema", "name") if dataform else (
            "projectId", "datasetId", "routineId" if routine else "tableId")
        self.unknown(path, locator, value, set(keys))
        if not all(isinstance(value.get(k), str) and value[k].strip() for k in keys):
            self.gap(path, "missing_identity", "Explicit project, dataset and object identifiers are required.", locator)
            return None
        return tuple(value[k] for k in keys)

    def register(self, path, locator, target, namespace):
        identity = (namespace, target)
        if identity in self.identities:
            self.gap(path, "duplicate_identity", "Repeated identity within the supplied metadata: " + ".".join(target), locator)
        self.identities.add(identity)

    def dependency(self, path, locator, owner, target, namespace, **details):
        if target is not None:
            self.r.dependency(path, locator, owner, ".".join(target),
                              target_components=list(target), evidence="declared_metadata", **details)
            self.references.append((path, locator, target, namespace))

    def sql(self, path, locator, value, owner, expression_only=False):
        if not isinstance(value, str) or not value.strip():
            self.gap(path, "missing_sql", "A non-empty SQL expression or definition is required.", locator)
            return
        # Retain the exact source even when it cannot be safely interpreted.
        if re.search(r"\bEXECUTE\s+IMMEDIATE\b", value, re.IGNORECASE) or "${" in value or "{{" in value:
            self.r.expression(path, locator, "bigquery", value, object_id=owner)
            self.gap(path, "dynamic_sql_unresolved", "Dynamic SQL or template expansion requires reviewed compiled evidence.", locator)
        elif expression_only:
            self.r.expression(path, locator, "bigquery", value, object_id=owner,
                              interpretation="retained_expression")
        else:
            parse_sql(self.r, path, value, dialect="bigquery", owner_id=owner, locator=locator)

    def fields(self, path, locator, fields, owner, components=(), depth=0):
        if depth > 32:
            self.gap(path, "nesting_limit", "Schema nesting exceeds the bounded extractor limit (32).", locator)
            return
        names = set()
        for index, item in enumerate(self.sequence(path, locator, fields)):
            loc = f"{locator}[{index}]"
            field = self.mapping(path, loc, item)
            if field is None:
                continue
            self.unknown(path, loc, field, _FIELD_KEYS)
            name, dtype = field.get("name"), field.get("type")
            if not isinstance(name, str) or not name.strip() or not isinstance(dtype, str) or not dtype.strip():
                self.gap(path, "invalid_field", "A field requires a non-empty name and type.", loc)
                continue
            if name in names:
                self.gap(path, "duplicate_field", "Repeated sibling field name: " + name, loc)
            names.add(name)
            parts = components + (name,)
            mode = field.get("mode", "NULLABLE")
            if mode not in ("NULLABLE", "REQUIRED", "REPEATED"):
                self.gap(path, "unsupported_field_mode", "Unknown field mode retained.", loc + ".mode")
            field_id = self.r.object(path, loc, "field", ".".join(parts),
                                     native_id=None, parent_id=owner, field_path=list(parts),
                                     data_type=dtype, mode=mode, raw_metadata=field)
            if "defaultValueExpression" in field:
                self.sql(path, loc + ".defaultValueExpression", field["defaultValueExpression"], field_id, True)
            if "fields" in field:
                self.fields(path, loc + ".fields", field["fields"], owner, parts, depth + 1)
            elif dtype.upper() in ("RECORD", "STRUCT"):
                self.gap(path, "missing_nested_fields", "Nested schema fields are absent.", loc)

    def table(self, path, locator, item):
        table = self.mapping(path, locator, item)
        if table is None:
            return
        self.unknown(path, locator, table, _TABLE_KEYS)
        target = self.target(path, locator + ".tableReference", table.get("tableReference"))
        if target is None:
            return
        self.register(path, locator, target, "table")
        oid = self.r.object(path, locator, "table", ".".join(target), native_id=table.get("id") or ".".join(target),
                            project_id=target[0], dataset_id=target[1], table_id=target[2],
                            table_type=table.get("type", "TABLE"), raw_metadata=table,
                            time_partitioning=table.get("timePartitioning"),
                            range_partitioning=table.get("rangePartitioning"), clustering=table.get("clustering"))
        if "schema" in table:
            schema = self.mapping(path, locator + ".schema", table["schema"])
            if schema is not None:
                self.unknown(path, locator + ".schema", schema, {"fields", "foreignTypeInfo"})
                self.fields(path, locator + ".schema.fields", schema.get("fields"), oid)
        else:
            self.gap(path, "missing_schema", "Table schema is absent; list projections do not supply a full schema.", locator)
        for key in ("view", "materializedView"):
            if key in table:
                view = self.mapping(path, locator + "." + key, table[key])
                if view is None:
                    continue
                self.unknown(path, locator + "." + key, view,
                             set("query useLegacySql userDefinedFunctionResources useExplicitColumnNames privacyPolicy "
                                 "enableRefresh refreshIntervalMs lastRefreshTime allowNonIncrementalDefinition".split()))
                if key == "view" and view.get("useLegacySql", True) is not False:
                    if isinstance(view.get("query"), str):
                        self.r.expression(path, locator + ".view.query", "bigquery_legacy", view["query"], object_id=oid)
                    self.gap(path, "legacy_sql_unresolved", "View does not explicitly select GoogleSQL (useLegacySql=false).", locator + ".view")
                else:
                    self.sql(path, locator + "." + key + ".query", view.get("query"), oid)
        if table.get("type") in ("VIEW", "MATERIALIZED_VIEW") and not any(k in table for k in ("view", "materializedView")):
            self.gap(path, "missing_sql", "View definition is absent from the supplied resource.", locator)
        for key in ("snapshotDefinition", "cloneDefinition"):
            if key in table:
                definition = self.mapping(path, locator + "." + key, table[key])
                if definition is not None:
                    loc = locator + "." + key + ".baseTableReference"
                    self.dependency(path, loc, oid, self.target(path, loc, definition.get("baseTableReference")), "table", relation=key)
        if "tableConstraints" in table:
            constraints = self.mapping(path, locator + ".tableConstraints", table["tableConstraints"])
            if constraints is not None:
                self.unknown(path, locator + ".tableConstraints", constraints, {"primaryKey", "foreignKeys"})
                for i, fk in enumerate(self.sequence(path, locator + ".tableConstraints.foreignKeys", constraints.get("foreignKeys", []))):
                    loc = f"{locator}.tableConstraints.foreignKeys[{i}]"
                    fk = self.mapping(path, loc, fk)
                    if fk is not None:
                        self.dependency(path, loc, oid, self.target(path, loc + ".referencedTable", fk.get("referencedTable")), "table", relation="foreign_key", raw_metadata=fk)
        for key in ("externalDataConfiguration", "biglakeConfiguration", "externalCatalogTableOptions", "partitionDefinition"):
            if key in table:
                self.gap(path, "metadata_only", key + " is retained; external storage and specialized behavior are not interpreted.", locator + "." + key)

    def routine(self, path, locator, item):
        routine = self.mapping(path, locator, item)
        if routine is None:
            return
        self.unknown(path, locator, routine, _ROUTINE_KEYS)
        target = self.target(path, locator + ".routineReference", routine.get("routineReference"), routine=True)
        if target is None:
            return
        self.register(path, locator, target, "routine")
        language = routine.get("language", "REMOTE" if "remoteFunctionOptions" in routine else "SQL")
        oid = self.r.object(path, locator, "routine", ".".join(target), native_id=".".join(target),
                            project_id=target[0], dataset_id=target[1], routine_id=target[2],
                            routine_type=routine.get("routineType"), language=language, raw_metadata=routine)
        if not routine.get("routineType"):
            self.gap(path, "missing_routine_type", "Routine type is absent.", locator)
        body = routine.get("definitionBody")
        if language == "SQL":
            self.sql(path, locator + ".definitionBody", body, oid)
        else:
            if isinstance(body, str):
                self.r.expression(path, locator + ".definitionBody", str(language).lower(), body, object_id=oid)
            self.gap(path, "non_sql_routine", "Non-SQL or remote routine behavior is retained without interpretation or execution.", locator)

    def descriptor(self, path, locator, descriptor, owner):
        descriptor = self.mapping(path, locator, descriptor)
        if descriptor is None:
            return
        self.unknown(path, locator, descriptor, {"description", "columns", "bigqueryLabels"})
        for i, col in enumerate(self.sequence(path, locator + ".columns", descriptor.get("columns", []))):
            loc = f"{locator}.columns[{i}]"
            col = self.mapping(path, loc, col)
            if col is None:
                continue
            self.unknown(path, loc, col, {"path", "description", "bigqueryPolicyTags"})
            parts = col.get("path")
            if not isinstance(parts, list) or not parts or not all(isinstance(v, str) and v for v in parts):
                self.gap(path, "invalid_field", "Column descriptor requires an explicit path array.", loc)
                continue
            self.r.object(path, loc, "column_descriptor", ".".join(parts), parent_id=owner,
                          field_path=parts, raw_metadata=col, physical_schema_verified=False)

    def action(self, path, locator, item):
        action = self.mapping(path, locator, item)
        if action is None:
            return
        self.unknown(path, locator, action, _ACTION_KINDS | {"target", "canonicalTarget", "filePath", "internalMetadata"})
        target = self.target(path, locator + ".target", action.get("target"), dataform=True)
        if target is None:
            return
        self.register(path, locator, target, "action")
        kinds = sorted(_ACTION_KINDS & action.keys())
        if len(kinds) != 1:
            self.gap(path, "invalid_action_union", "Exactly one Dataform compiled object is required.", locator)
        kind = kinds[0] if len(kinds) == 1 else "unknown"
        oid = self.r.object(path, locator, "dataform_" + kind, ".".join(target), native_id=".".join(target),
                            project_id=target[0], dataset_id=target[1], action_name=target[2],
                            raw_metadata=action, source_file=action.get("filePath"))
        if "canonicalTarget" in action:
            self.target(path, locator + ".canonicalTarget", action["canonicalTarget"], dataform=True)
        if kind == "unknown":
            return
        body = self.mapping(path, locator + "." + kind, action[kind])
        if body is None:
            return
        loc = locator + "." + kind
        if kind in ("notebook", "dataPreparation"):
            self.gap(path, "unsupported_action", "Dataform " + kind + " is retained without interpreting executable behavior.", loc)
            return
        supported = {
            "relation": _RELATION_KEYS,
            "operations": {"dependencyTargets", "disabled", "tags", "relationDescriptor", "queries", "hasOutput"},
            "assertion": {"dependencyTargets", "disabled", "tags", "relationDescriptor", "selectQuery", "parentAction"},
            "declaration": {"relationDescriptor"},
        }[kind]
        self.unknown(path, loc, body, supported)
        for i, dep in enumerate(self.sequence(path, loc + ".dependencyTargets", body.get("dependencyTargets", []))):
            dep_loc = f"{loc}.dependencyTargets[{i}]"
            self.dependency(path, dep_loc, oid, self.target(path, dep_loc, dep, dataform=True), "action", relation="dataform_dependency")
        if "parentAction" in body:
            dep_loc = loc + ".parentAction"
            self.dependency(path, dep_loc, oid, self.target(path, dep_loc, body["parentAction"], dataform=True), "action", relation="assertion_parent")
        if "relationDescriptor" in body:
            self.descriptor(path, loc + ".relationDescriptor", body["relationDescriptor"], oid)
        if kind in ("relation", "assertion"):
            self.sql(path, loc + ".selectQuery", body.get("selectQuery"), oid)
        for key in ("queries", "preOperations", "postOperations"):
            if key in body:
                for i, sql in enumerate(self.sequence(path, loc + "." + key, body[key])):
                    self.sql(path, f"{loc}.{key}[{i}]", sql, oid)
        if kind == "operations" and "queries" not in body:
            self.gap(path, "missing_sql", "Operation queries are absent.", loc)
        if "partitionExpression" in body:
            self.sql(path, loc + ".partitionExpression", body["partitionExpression"], oid, True)
        for i, value in enumerate(self.sequence(path, loc + ".clusterExpressions", body.get("clusterExpressions", []))):
            self.sql(path, f"{loc}.clusterExpressions[{i}]", value, oid, True)
        if "incrementalTableConfig" in body:
            inc_loc = loc + ".incrementalTableConfig"
            inc = self.mapping(path, inc_loc, body["incrementalTableConfig"])
            if inc is not None:
                self.unknown(path, inc_loc, inc, _INCREMENTAL_KEYS)
                self.sql(path, inc_loc + ".incrementalSelectQuery", inc.get("incrementalSelectQuery"), oid)
                if "updatePartitionFilter" in inc:
                    self.sql(path, inc_loc + ".updatePartitionFilter", inc["updatePartitionFilter"], oid, True)
                for key in ("incrementalPreOperations", "incrementalPostOperations", "uniqueKeyParts"):
                    for i, value in enumerate(self.sequence(path, inc_loc + "." + key, inc.get(key, []))):
                        self.sql(path, f"{inc_loc}.{key}[{i}]", value, oid, key == "uniqueKeyParts")
        elif body.get("relationType") == "INCREMENTAL_TABLE":
            self.gap(path, "missing_incremental_config", "Incremental relation has no incremental definition.", loc)

    def document(self, path, value):
        if isinstance(value, list):
            for i, item in enumerate(value):
                self.resource(path, f"$[{i}]", item)
            if not value:
                self.gap(path, "empty_export", "Empty resource array does not establish inventory coverage.", "$")
            return
        if not isinstance(value, dict):
            self.gap(path, "invalid_metadata", "Expected an export object or resource array.", "$")
            return
        collections = {"tables": self.table, "routines": self.routine, "compilationResultActions": self.action}
        selected = [key for key in collections if key in value]
        if not selected:
            self.resource(path, "$", value)
            return
        self.unknown(path, "$", value, set(collections) | {"kind", "etag", "nextPageToken", "totalItems"})
        self.r.object(path, "$", "export_page", path, raw_metadata={k: v for k, v in value.items() if k not in collections},
                      inventory_scope_verified=False)
        if value.get("nextPageToken"):
            self.gap(path, "pagination_incomplete", "A nextPageToken remains; this export page is not a complete collection.", "$.nextPageToken")
        if "nextPageToken" in value and not isinstance(value["nextPageToken"], str):
            self.gap(path, "invalid_metadata", "nextPageToken must be a string.", "$.nextPageToken")
        for key in selected:
            items = self.sequence(path, "$." + key, value[key])
            if not items:
                self.gap(path, "empty_export", "Empty collection does not establish inventory coverage or permission scope.", "$." + key)
            for i, item in enumerate(items):
                collections[key](path, f"$.{key}[{i}]", item)
        if "tables" in selected and isinstance(value.get("totalItems"), int) and isinstance(value["tables"], list) and value["totalItems"] > len(value["tables"]):
            self.gap(path, "collection_count_mismatch", "totalItems exceeds the number of tables supplied on this page.", "$.totalItems")

    def resource(self, path, locator, value):
        if not isinstance(value, dict):
            self.gap(path, "invalid_metadata", "Expected a resource object.", locator)
        elif "tableReference" in value or value.get("kind") == "bigquery#table":
            self.table(path, locator, value)
        elif "routineReference" in value or "routineType" in value:
            self.routine(path, locator, value)
        elif "target" in value and _ACTION_KINDS & value.keys():
            self.action(path, locator, value)
        else:
            self.gap(path, "unsupported_json_shape", "Expected Table, Routine or compilationResultActions metadata; no identity is inferred from filenames.", locator)


def parse(files):
    """Extract supplied UTF-8 text only; never compile, execute or acquire source."""
    parser = _Parser(files)
    for path, text in sorted(files.items()):
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".sql":
            parser.sql(path, "$", text, None)
            parser.r.cover(path)
        elif suffix in (".sqlx", ".js"):
            parser.r.expression(path, "$", "sqlx" if suffix == ".sqlx" else "javascript", text)
            parser.gap(path, "compilation_required", "Supply a Dataform compilationResults.query response; source compilation is not performed.", "$")
            parser.r.cover(path, status="partial", reason="Compilation required")
        elif suffix == ".json":
            try:
                document = read_json(text)
            except (ValueError, TypeError, RecursionError) as error:
                parser.gap(path, "invalid_json", str(error), "$")
                parser.r.cover(path, status="partial", reason="Invalid JSON export")
                continue
            parser.document(path, document)
            parser.r.cover(path)
        else:
            parser.gap(path, "unsupported_format", "Unsupported BigQuery source format.", "$")
            parser.r.cover(path, status="unsupported", reason="Unsupported source format")
    for path, locator, target, namespace in parser.references:
        if (namespace, target) not in parser.identities:
            parser.gap(path, "unresolved_dependency", "Referenced " + namespace + " is absent from supplied metadata: " + ".".join(target), locator)
    return parser.r.finish()
