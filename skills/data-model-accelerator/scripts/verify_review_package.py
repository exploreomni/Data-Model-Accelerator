#!/usr/bin/env python3
"""Check declared review evidence and artifact integrity; never approve or deploy."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys


ROLES = {
    "source_inventory", "assessment", "model_spec", "erd", "lineage",
    "decisions", "code", "test_plan", "test_evidence", "runbook",
    "data_dictionary", "layer_documentation",
}
CATALOGUE_ROLES = {"warehouse_catalogue", "catalogue_bindings", "catalogue_evidence"}
LOCAL_CATEGORIES = {
    "source_contract", "grain", "fanout", "logic", "reconciliation",
    "security", "history", "replay", "negative_controls",
}
TARGET_CATEGORIES = {"target_compile", "target_execution", "operations"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def verify(manifest_path, stage="local"):
    errors = []
    manifest_path = Path(manifest_path).absolute()
    if stage not in {"local", "target"}:
        return ["Unknown review stage"]
    if manifest_path.is_symlink():
        return ["Manifest must not be a symlink"]
    root = manifest_path.parent.resolve()
    try:
        package = json.loads(manifest_path.read_text(), object_pairs_hook=unique_object)
    except (OSError, ValueError) as exc:
        return ["Cannot read manifest: " + str(exc)]
    if not isinstance(package, dict):
        return ["Manifest must be a JSON object"]
    if type(package.get("schema_version")) is not int or package["schema_version"] != 1:
        errors.append("schema_version must be integer 1")
    target = package.get("target")
    if not isinstance(target, dict):
        errors.append("Missing target context")
    else:
        for field in ("framework", "warehouse", "versions", "environment"):
            if not nonempty(target.get(field)):
                errors.append("Missing target." + field)
            elif stage == "target" and any(
                marker in target[field].lower()
                for marker in ("unverified", "unknown", "local-only", "tbd")
            ):
                errors.append("Unqualified target." + field)

    artifacts = package.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return errors + ["artifacts must be a nonempty array"]
    by_id, paths, roles, artifact_paths = {}, set(), set(), {}
    detected_dispatch_ids, specialist_evidence = set(), False
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            errors.append("Invalid artifact at index " + str(index))
            continue
        aid = artifact.get("id")
        if not nonempty(aid):
            errors.append("Artifact requires an id")
            continue
        if aid in by_id:
            errors.append("Duplicate artifact id: " + aid)
            continue
        by_id[aid] = artifact
        role = artifact.get("role")
        if not isinstance(role, str) or role not in ROLES | CATALOGUE_ROLES:
            errors.append("Unknown artifact role for " + aid)
        else:
            roles.add(role)
        relative = artifact.get("path")
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            errors.append("Invalid SHA-256 for " + aid)
        if not nonempty(relative):
            errors.append("Missing path for " + aid)
            continue
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            errors.append("Artifact path must remain within bundle: " + aid)
            continue
        absolute = root / path
        if any((root.joinpath(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1)):
            errors.append("Artifact symlink is not allowed: " + aid)
            continue
        try:
            resolved = absolute.resolve(strict=True)
            resolved.relative_to(root)
            if resolved == manifest_path.resolve() or resolved in paths:
                errors.append("Self-reference or duplicate artifact path: " + aid)
                continue
            paths.add(resolved)
            content = resolved.read_bytes()
            artifact_paths[aid] = resolved
            actual = hashlib.sha256(content).hexdigest()
            if actual != digest:
                errors.append("Artifact changed or hash incorrect: " + aid)
            try:
                body = json.loads(content, object_pairs_hook=unique_object)
            except (UnicodeError, ValueError):
                body = None
            if isinstance(body, dict):
                if {"inventory_path", "tasks", "source_snapshot_sha256"} <= body.keys():
                    detected_dispatch_ids.add(aid)
                    specialist_evidence = True
                if {"asset_coverage", "task_id", "source_snapshot_sha256"} <= body.keys():
                    specialist_evidence = True
        except (OSError, ValueError) as exc:
            errors.append("Cannot read artifact " + aid + ": " + str(exc))
    for role in sorted(ROLES - roles):
        errors.append("Missing artifact role: " + role)
    inventories = [a for a in by_id.values() if a.get("role") == "source_inventory"]
    if len(inventories) != 1:
        errors.append("Exactly one source_inventory artifact is required")
    elif inventories[0].get("sha256") != package.get("source_snapshot_sha256"):
        errors.append("Source snapshot does not match inventory hash")

    helper_path = Path(__file__).resolve().with_name("verify_model_documentation.py")
    spec = importlib.util.spec_from_file_location("dma_documentation_checker", helper_path)
    documentation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(documentation)
    errors.extend(documentation.verify(package, by_id, artifact_paths))

    catalogue_entries = package.get("warehouse_catalogues")
    if not isinstance(catalogue_entries, list) or not catalogue_entries:
        errors.append("warehouse_catalogues must include raw-layer metadata and source bindings")
        catalogue_entries = []
    used_catalogues, used_bindings = set(), set()
    for entry in catalogue_entries:
        if not isinstance(entry, dict):
            errors.append("Invalid warehouse catalogue entry")
            continue
        cid, bid = entry.get("catalogue_artifact_id"), entry.get("bindings_artifact_id")
        if (not nonempty(cid) or not nonempty(bid)
                or by_id.get(cid, {}).get("role") != "warehouse_catalogue"
                or by_id.get(bid, {}).get("role") != "catalogue_bindings"
                or cid not in artifact_paths or bid not in artifact_paths):
            errors.append("Warehouse catalogue requires hashed catalogue and binding artifacts")
            continue
        if cid in used_catalogues or bid in used_bindings:
            errors.append("Duplicate warehouse catalogue/binding association")
        used_catalogues.add(cid)
        used_bindings.add(bid)
        try:
            helper_path = Path(__file__).resolve().with_name("verify_catalogue.py")
            spec = importlib.util.spec_from_file_location("dma_catalogue_checker", helper_path)
            helper = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(helper)
            catalogue_path, bindings_path = artifact_paths[cid], artifact_paths[bid]
            catalogue = json.loads(catalogue_path.read_text(), object_pairs_hook=unique_object)
            evidence_paths = {artifact_paths[aid] for aid, artifact in by_id.items()
                              if artifact.get("role") == "catalogue_evidence" and aid in artifact_paths}
            for extraction in catalogue["extractions"]:
                if extraction.get("artifact_path") is None and extraction.get("status") in {"failed", "unavailable"}:
                    continue
                relative = Path(extraction["artifact_path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Catalogue evidence leaves its root")
                evidence_path = (catalogue_path.parent / relative).resolve(strict=True)
                if evidence_path not in evidence_paths:
                    errors.append("Catalogue raw metadata exports must be hashed catalogue_evidence artifacts")
            report = helper.verify(catalogue_path, bindings_path, max_age_hours=entry.get("max_age_hours"))
            if not report["catalogue_context_complete"]:
                errors.append("Warehouse catalogue context is incomplete: " + str(len(report["errors"]))
                              + " error(s), " + str(len(report["gaps"])) + " gap(s)")
            if report.get("catalogue_sha256") != by_id[cid]["sha256"]:
                errors.append("Catalogue snapshot differs from review artifact")
            if report.get("source_snapshot_sha256") != package.get("source_snapshot_sha256"):
                errors.append("Catalogue bindings refer to a different repository snapshot")
            if stage == "target" and report.get("origin") == "synthetic":
                errors.append("Synthetic catalogue cannot establish target validation")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append("Cannot verify warehouse catalogue: " + str(exc))
    for aid, artifact in by_id.items():
        if artifact.get("role") == "warehouse_catalogue" and aid not in used_catalogues:
            errors.append("Unassociated warehouse catalogue artifact: " + aid)
        if artifact.get("role") == "catalogue_bindings" and aid not in used_bindings:
            errors.append("Unassociated catalogue binding artifact: " + aid)

    required = package.get("required_test_ids")
    if not isinstance(required, list) or not required or not all(nonempty(x) for x in required):
        errors.append("required_test_ids must be a nonempty string array")
        required = []
    if len(set(required)) != len(required):
        errors.append("Duplicate required test id")
    tests = package.get("tests")
    if not isinstance(tests, list):
        errors.append("tests must be an array")
        tests = []
    test_ids, covered = set(), set()
    for test in tests:
        if not isinstance(test, dict) or not nonempty(test.get("id")):
            errors.append("Each test requires an id")
            continue
        tid = test["id"]
        if tid in test_ids:
            errors.append("Duplicate test id: " + tid)
        test_ids.add(tid)
        if tid not in required:
            errors.append("Test missing from declared test inventory: " + tid)
        category = test.get("category")
        if not isinstance(category, str) or category not in LOCAL_CATEGORIES | TARGET_CATEGORIES:
            errors.append("Unknown category for " + tid)
        evidence = test.get("artifact_id")
        if not isinstance(evidence, str) or by_id.get(evidence, {}).get("role") != "test_evidence":
            errors.append("Missing test_evidence artifact for " + tid)
        if test.get("scope") not in ("local", "target"):
            errors.append("Invalid scope for " + tid)
        if test.get("status") != "pass":
            errors.append("Test is not passed: " + tid)
        if (test.get("status") == "pass" and isinstance(category, str)
                and test.get("scope") in (("local", "target") if stage == "local" else ("target",))):
            covered.add(category)
    for tid in sorted(set(required) - test_ids):
        errors.append("Required test result missing: " + tid)
    exemptions = package.get("not_applicable", [])
    if not isinstance(exemptions, list):
        errors.append("not_applicable must be an array")
        exemptions = []
    exempted = set()
    for exemption in exemptions:
        if not isinstance(exemption, dict):
            errors.append("Invalid not_applicable record")
            continue
        category = exemption.get("category")
        evidence = exemption.get("artifact_id")
        if (category not in ("history", "replay") or not nonempty(exemption.get("rationale"))
                or not isinstance(evidence, str) or by_id.get(evidence, {}).get("role") != "decisions"):
            errors.append("Invalid not_applicable decision")
        elif category in exempted or category in covered:
            errors.append("Duplicate or contradictory not_applicable category: " + category)
        else:
            exempted.add(category)
    needed = LOCAL_CATEGORIES | (TARGET_CATEGORIES if stage == "target" else set())
    for category in sorted(needed - covered - exempted):
        errors.append("Missing " + stage + " passing category: " + category)
    blockers = package.get("unresolved_blockers")
    if not isinstance(blockers, list):
        errors.append("unresolved_blockers must be an array")
    elif blockers:
        errors.append("Unresolved blockers remain: " + str(len(blockers)))
    dispatch_id = package.get("specialist_dispatch_artifact_id")
    if specialist_evidence and dispatch_id is None:
        errors.append("Specialist dispatch association is required for included specialist evidence")
    if detected_dispatch_ids and (not isinstance(dispatch_id, str) or detected_dispatch_ids != {dispatch_id}):
        errors.append("Specialist dispatch association must identify the single included dispatch plan")
    if dispatch_id is not None:
        if not isinstance(dispatch_id, str) or by_id.get(dispatch_id, {}).get("role") != "lineage":
            errors.append("Specialist dispatch must reference a hashed lineage artifact")
        else:
            try:
                helper_path = Path(__file__).resolve().with_name("verify_specialist_results.py")
                spec = importlib.util.spec_from_file_location("dma_specialist_checker", helper_path)
                helper = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(helper)
                dispatch_path = helper.inside(root, by_id[dispatch_id]["path"])
                dispatch = helper.read_json(dispatch_path)
                evidence_paths = [helper.inside(dispatch_path.parent, dispatch["inventory_path"])]
                evidence_paths.extend(helper.inside(dispatch_path.parent, task["result_path"]) for task in dispatch["tasks"])
                if any(path not in paths for path in evidence_paths):
                    errors.append("Specialist inventory/results must all be included as hashed review artifacts")
                extraction = helper.verify(dispatch_path)
                if not extraction["extraction_complete"]:
                    errors.append("Specialist extraction is incomplete: " + str(len(extraction["errors"])) + " error(s), " + str(len(extraction["gaps"])) + " gap(s)")
                if extraction.get("source_snapshot_sha256") != package.get("source_snapshot_sha256"):
                    errors.append("Specialist source snapshot differs from review package")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                errors.append("Cannot verify specialist handoff: " + str(exc))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--stage", choices=("local", "target"), default="local")
    args = parser.parse_args()
    errors = verify(args.manifest, args.stage)
    print(json.dumps({
        "stage": args.stage,
        "evidence_complete_for_review": not errors,
        "errors": errors,
        "limitation": "Checks declared evidence integrity/completeness only; does not approve or deploy.",
    }, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
