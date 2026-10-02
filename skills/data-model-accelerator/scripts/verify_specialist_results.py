#!/usr/bin/env python3
"""Verify declared specialist extraction coverage and provenance; never execute source code."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


COVERAGE = {"parsed", "partial", "unsupported", "missing", "unreadable"}
PLACEMENTS = {"warehouse", "semantic", "presentation", "split", "unresolved"}


def text_value(value):
    return isinstance(value, str) and bool(value.strip())


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inside(root, relative):
    if not text_value(relative):
        raise ValueError("Expected a relative file path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Path leaves its assigned root: " + relative)
    for index in range(1, len(path.parts) + 1):
        if root.joinpath(*path.parts[:index]).is_symlink():
            raise ValueError("Symlink in evidence path: " + relative)
    full = (root / path).resolve(strict=True)
    full.relative_to(root)
    if not full.is_file():
        raise ValueError("Evidence must be a regular file: " + relative)
    return full


def read_json(path):
    data = json.loads(path.read_text(), object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object: " + path.name)
    return data


def records(parent, key, errors):
    value = parent.get(key)
    if not isinstance(value, list):
        errors.append(key + " must be an array")
        return []
    return value


def verify(plan_path):
    errors, gaps = [], []
    report = {"schema_version": 1, "extraction_complete": False, "tasks_expected": 0,
              "tasks_returned": 0, "assets_expected": 0, "objects_returned": 0,
              "rules_returned": 0, "errors": errors, "gaps": gaps,
              "limitation": "Checks declared extraction/provenance only; does not establish business equivalence, independent execution, placement approval or deployment readiness."}
    try:
        original = Path(plan_path).absolute()
        if original.is_symlink():
            raise ValueError("Dispatch plan must not be a symlink")
        plan_path = original.resolve(strict=True)
        run_root = plan_path.parent
        plan = read_json(plan_path)
        inventory_path = inside(run_root, plan.get("inventory_path"))
        inventory = read_json(inventory_path)
        snapshot = digest(inventory_path)
        if snapshot != plan.get("source_snapshot_sha256"):
            errors.append("Inventory changed after dispatch")
        if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
                or type(inventory.get("schema_version")) is not int or inventory["schema_version"] != 1):
            errors.append("Unsupported plan/inventory schema version")
        if plan.get("status") != "planned":
            gaps.append("Dispatch inventory is incomplete")
        repository = inventory.get("repository", {})
        root_value = repository.get("root") if isinstance(repository, dict) else None
        if not text_value(root_value) or not Path(root_value).is_absolute():
            raise ValueError("Inventory requires repository.root as an absolute path")
        stored_root = Path(root_value)
        if stored_root.is_symlink():
            raise ValueError("Symlink in stored source root")
        repo_root = stored_root.resolve(strict=True)
        if repo_root != stored_root:
            raise ValueError("Stored source root must remain canonical; symlink or redirected ancestor detected")
        assets, assigned = {}, set()
        for asset in records(inventory, "assets", errors):
            if not isinstance(asset, dict) or not text_value(asset.get("asset_id")):
                errors.append("Invalid inventory asset")
                continue
            aid = asset["asset_id"]
            if aid in assets:
                errors.append("Duplicate inventory asset: " + aid)
            assets[aid] = asset
            if asset.get("sha256") is None:
                gaps.append("Source asset has no bounded content hash: " + aid)
                continue
            try:
                current = inside(repo_root, asset.get("path"))
                if type(asset.get("size_bytes")) is int and current.stat().st_size != asset["size_bytes"]:
                    errors.append("Source asset size changed after dispatch: " + aid)
                    continue
                if digest(current) != asset.get("sha256"):
                    errors.append("Source asset changed after dispatch: " + aid)
            except (OSError, ValueError) as exc:
                errors.append("Source asset unavailable " + aid + ": " + str(exc))
        report["assets_expected"] = len(assets)
        inventory_gaps = inventory.get("gaps", [])
        if not isinstance(inventory_gaps, list):
            errors.append("Inventory gaps must be an array")
        elif inventory_gaps:
            gaps.append("Inventory declares " + str(len(inventory_gaps)) + " gap(s)")
        tasks = records(plan, "tasks", errors)
        report["tasks_expected"] = len(tasks)
        if not tasks:
            gaps.append("No source specialist tasks were planned")
        task_ids, result_paths, object_ids, rule_ids = set(), set(), set(), set()
        rule_references = []

        for task in tasks:
            if not isinstance(task, dict) or not text_value(task.get("task_id")):
                errors.append("Invalid task")
                continue
            tid = task["task_id"]
            if tid in task_ids:
                errors.append("Duplicate task id: " + tid)
            task_ids.add(tid)
            task_assets = task.get("asset_ids")
            if not isinstance(task_assets, list) or not task_assets or not all(text_value(x) for x in task_assets):
                errors.append("Task requires nonempty asset_ids: " + tid)
                continue
            allowed = set(task_assets)
            if len(allowed) != len(task_assets):
                errors.append("Duplicate assigned asset in " + tid)
            for aid in allowed - assets.keys():
                errors.append("Assigned asset absent from inventory: " + aid)
            assigned.update(allowed)
            try:
                result_path = inside(run_root, task.get("result_path"))
                if result_path in result_paths or result_path in {plan_path, inventory_path}:
                    raise ValueError("Task result path reused or reserved")
                result_paths.add(result_path)
                result = read_json(result_path)
            except (OSError, ValueError) as exc:
                errors.append("Missing/invalid specialist result " + tid + ": " + str(exc))
                continue
            report["tasks_returned"] += 1
            if type(result.get("schema_version")) is not int or result["schema_version"] != 1 or result.get("task_id") != tid:
                errors.append("Result schema/task mismatch: " + tid)
            if result.get("source_snapshot_sha256") != snapshot:
                errors.append("Stale specialist result: " + tid)
            coverage = {}
            for entry in records(result, "asset_coverage", errors):
                if not isinstance(entry, dict) or not text_value(entry.get("asset_id")):
                    errors.append("Invalid asset coverage in " + tid)
                    continue
                aid = entry["asset_id"]
                status = entry.get("status")
                if aid in coverage:
                    errors.append("Duplicate asset coverage in " + tid + ": " + aid)
                coverage[aid] = status
                if aid not in allowed:
                    errors.append("Coverage outside assignment in " + tid + ": " + aid)
                if not isinstance(status, str) or status not in COVERAGE or not text_value(entry.get("reason")):
                    errors.append("Coverage needs valid status/reason: " + aid)
                if status != "parsed":
                    gaps.append(tid + ": " + aid + " not fully parsed")
                if status == "parsed" and assets.get(aid, {}).get("status") in ("unsupported_binary", "unreadable", "unreadable_limit"):
                    errors.append("Binary/unreadable artifact requires separately inventoried extraction: " + aid)
            for aid in allowed - coverage.keys():
                errors.append("Assigned asset omitted from result " + tid + ": " + aid)

            def evidence_ok(item, label):
                evidence = item.get("evidence")
                if not isinstance(evidence, list) or not evidence:
                    errors.append("Missing source evidence for " + label)
                    return
                for citation in evidence:
                    if (not isinstance(citation, dict) or not text_value(citation.get("asset_id"))
                            or citation["asset_id"] not in allowed or not text_value(citation.get("locator"))):
                        errors.append("Invalid/out-of-scope source citation for " + label)

            local_objects = set()
            for obj in records(result, "objects", errors):
                if not isinstance(obj, dict) or not text_value(obj.get("object_id")):
                    errors.append("Invalid extracted object in " + tid)
                    continue
                oid = obj["object_id"]
                if oid in object_ids:
                    errors.append("Object id collision across results: " + oid)
                object_ids.add(oid)
                local_objects.add(oid)
                if (not all(text_value(obj.get(k)) for k in ("kind", "name")) or "native_id" not in obj
                        or (obj["native_id"] is not None and type(obj["native_id"]) not in (str, int))):
                    errors.append("Object lacks identity metadata: " + oid)
                grain = obj.get("grain")
                if (not isinstance(grain, dict) or grain.get("status") not in ("observed", "inferred", "unknown")
                        or not text_value(grain.get("description"))):
                    errors.append("Object lacks stated grain/uncertainty: " + oid)
                evidence_ok(obj, oid)
            unresolved = records(result, "unresolved_references", errors)
            unresolved_names = set()
            for ref in unresolved:
                if not isinstance(ref, dict) or not text_value(ref.get("reference")) or not text_value(ref.get("reason")):
                    errors.append("Invalid unresolved reference in " + tid)
                else:
                    unresolved_names.add(ref["reference"])
            if unresolved:
                gaps.append(tid + ": unresolved source references")
            result_gaps = records(result, "gaps", errors)
            if result_gaps:
                gaps.append(tid + ": specialist declared " + str(len(result_gaps)) + " gap(s)")
            for rule in records(result, "rules", errors):
                if not isinstance(rule, dict) or not text_value(rule.get("rule_id")):
                    errors.append("Invalid extracted rule in " + tid)
                    continue
                rid = rule["rule_id"]
                if rid in rule_ids:
                    errors.append("Rule id collision across results: " + rid)
                rule_ids.add(rid)
                if not all(text_value(rule.get(k)) for k in ("kind", "language", "expression")):
                    errors.append("Rule lacks original language/expression: " + rid)
                if not isinstance(rule.get("output_object_id"), str) or rule["output_object_id"] not in local_objects:
                    errors.append("Rule output is absent from its result: " + rid)
                context = rule.get("context")
                if (not isinstance(context, dict) or not all(k in context for k in ("evaluation_grain", "filters", "security"))
                        or not text_value(context.get("evaluation_grain"))):
                    errors.append("Rule lacks evaluation context: " + rid)
                placement = rule.get("placement_candidate")
                if (not isinstance(placement, dict) or not isinstance(placement.get("destination"), str)
                        or placement["destination"] not in PLACEMENTS or not text_value(placement.get("rationale"))):
                    errors.append("Rule lacks explicit placement candidate/rationale: " + rid)
                evidence_ok(rule, rid)
                for ref in records(rule, "input_refs", errors):
                    if not isinstance(ref, dict) or not text_value(ref.get("reference")):
                        errors.append("Invalid source reference for " + rid)
                    elif ref.get("status") == "resolved" and text_value(ref.get("object_id")):
                        rule_references.append((rid, ref["object_id"]))
                    elif ref.get("status") == "unresolved" and ref["reference"] in unresolved_names:
                        pass
                    else:
                        errors.append("Reference resolution not evidenced for " + rid)
        for aid in assets.keys() - assigned:
            gaps.append("Inventory asset has no specialist assignment: " + aid)
        for rid, oid in rule_references:
            if oid not in object_ids:
                errors.append("Resolved reference points to nonexistent object: " + rid + " -> " + oid)
        report["objects_returned"] = len(object_ids)
        report["rules_returned"] = len(rule_ids)
        report["source_snapshot_sha256"] = snapshot
    except (OSError, ValueError, TypeError) as exc:
        errors.append("Invalid dispatch/evidence: " + str(exc))
    report["extraction_complete"] = not errors and not gaps
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch_plan", type=Path)
    args = parser.parse_args()
    report = verify(args.dispatch_plan)
    print(json.dumps(report, indent=2))
    return 0 if report["extraction_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
