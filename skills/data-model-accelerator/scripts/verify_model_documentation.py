"""Check declared ERD/layer/dictionary coverage; prose accuracy needs review.

Called by the review checker with artifact paths already bounded to the bundle.
The inventory is an explicit denominator, not an independently inferred schema.
"""
import hashlib
import json


LAYERS = {"bronze", "silver", "gold"}
COLUMN_FIELDS = {"name", "description", "data_type", "nullability", "key_role",
                 "source", "transformation", "units", "classification", "validation"}


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def verify(package, artifacts, paths):
    errors = []
    association = package.get("model_documentation")
    if not isinstance(association, dict):
        return ["model_documentation must associate the model inventory, dictionary, ERD and all three layers"]

    def artifact(aid, role):
        if (not nonempty(aid) or artifacts.get(aid, {}).get("role") != role or aid not in paths):
            errors.append("Documentation requires a hashed " + role + " artifact: " + str(aid))
            return None
        if role in {"layer_documentation", "erd"} and not paths[aid].read_bytes().strip():
            errors.append("Documentation artifact is empty: " + aid)
        return paths[aid]

    def read(path, kind):
        if path is None:
            return None
        try:
            value = json.loads(path.read_text(), object_pairs_hook=unique_object)
            versions = {1, 2} if kind == 'data_dictionary' else {1}
            if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
                    or value['schema_version'] not in versions or value.get("kind") != kind):
                raise ValueError("Unsupported version for " + kind + '; migrate the dictionary explicitly')
            if kind == 'data_dictionary' and value['schema_version'] == 2:
                from data_dictionary_v2 import validate_dictionary
                errors.extend(validate_dictionary(value))
            return value
        except (OSError, UnicodeError, ValueError) as error:
            errors.append("Cannot read model documentation: " + str(error))
            return None

    ipath = artifact(association.get("inventory_artifact_id"), "model_spec")
    dpath = artifact(association.get("dictionary_artifact_id"), "data_dictionary")
    readable = artifact(association.get("readable_dictionary_artifact_id"), "data_dictionary")
    if readable is not None:
        if readable == dpath:
            errors.append("Readable dictionary must be a separate rendering of the canonical JSON")
        try:
            if not readable.read_text().strip():
                errors.append("Readable dictionary is empty")
        except (OSError, UnicodeError) as error:
            errors.append("Cannot read dictionary rendering: " + str(error))
    inventory = read(ipath, "data_model_inventory")
    dictionary = read(dpath, "data_dictionary")
    if inventory is None or dictionary is None:
        return errors
    if dictionary.get("model_inventory_sha256") != hashlib.sha256(ipath.read_bytes()).hexdigest():
        errors.append("Data dictionary refers to a different model inventory version")

    models, grouped = {}, {layer: set() for layer in LAYERS}
    records = inventory.get("models")
    if not isinstance(records, list) or not records:
        errors.append("Model inventory requires a nonempty model denominator")
        records = []
    for model in records:
        if not isinstance(model, dict) or not nonempty(model.get("model_id")):
            errors.append("Inventory model requires a stable model_id")
            continue
        mid = model["model_id"]
        if mid in models:
            errors.append("Duplicate model inventory entry: " + mid)
            continue
        layer, columns = model.get("layer"), model.get("columns")
        if not isinstance(layer, str) or layer not in LAYERS:
            errors.append("Model has an unknown documentation layer: " + mid)
            continue
        if not nonempty(model.get("physical_name")):
            errors.append("Model requires its qualified physical name: " + mid)
        if (not isinstance(columns, list) or not columns or not all(nonempty(c) for c in columns)
                or len(set(columns)) != len(columns)):
            errors.append("Model requires a unique nonempty column denominator: " + mid)
            continue
        models[mid] = set(columns)
        grouped[layer].add(mid)

    entries = dictionary.get("models")
    if not isinstance(entries, list):
        errors.append("Data dictionary models must be an array")
        entries = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not nonempty(entry.get("model_id")):
            errors.append("Dictionary model requires a model_id")
            continue
        mid = entry["model_id"]
        if mid in seen:
            errors.append("Duplicate dictionary model: " + mid)
        seen.add(mid)
        if not all(nonempty(entry.get(key)) for key in ("description", "grain")):
            errors.append("Dictionary model lacks description or grain: " + mid)
        columns = entry.get("columns")
        if not isinstance(columns, list):
            errors.append("Dictionary columns must be an array: " + mid)
            columns = []
        names = []
        for column in columns:
            if not isinstance(column, dict) or not all(nonempty(column.get(key)) for key in COLUMN_FIELDS):
                errors.append("Dictionary column lacks required definition/lineage/quality fields: " + mid)
            if isinstance(column, dict) and nonempty(column.get("name")):
                names.append(column["name"])
        if len(names) != len(set(names)):
            errors.append("Duplicate dictionary column: " + mid)
        if mid not in models or set(names) != models[mid]:
            errors.append("Dictionary column coverage differs from model inventory: " + mid)
    if seen != set(models):
        errors.append("Dictionary model coverage differs from model inventory")

    layers = association.get("layers")
    if not isinstance(layers, list):
        errors.append("Documentation layers must be an array")
        layers = []
    seen_layers = set()
    for entry in layers:
        if not isinstance(entry, dict) or not isinstance(entry.get("layer"), str) or entry["layer"] not in LAYERS:
            errors.append("Unknown layer documentation association")
            continue
        layer = entry["layer"]
        if layer in seen_layers:
            errors.append("Duplicate layer documentation: " + layer)
        seen_layers.add(layer)
        artifact(entry.get("document_artifact_id"), "layer_documentation")
        artifact(entry.get("erd_artifact_id"), "erd")
        ids = entry.get("model_ids")
        if (not isinstance(ids, list) or not all(nonempty(mid) for mid in ids)
                or len(set(ids)) != len(ids) or set(ids) != grouped[layer]):
            errors.append("Layer documentation coverage differs from model inventory: " + layer)
    if seen_layers != LAYERS:
        errors.append("Documentation must include bronze, silver and gold")
    return errors
