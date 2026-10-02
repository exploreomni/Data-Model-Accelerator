# Evidence and output contracts

Use these records to make an assessment reproducible and its decisions reviewable. JSON is preferred for machine-consumed records; concise Markdown explains decisions. Do not multiply artifacts that merely repeat the same content.

## Input snapshot and coverage

Record repository identity without embedded credentials, selected revision, dirty state, selected paths, original asset IDs, file SHA-256 values, formats/dialects, and bounded read errors. Record observed/parsed/unresolved/unsupported asset counts against the selected inventory. Include missing referenced assets as gaps. Hash the serialized snapshot file and retain it as a review artifact.

For external evidence record source ID, extraction context, timestamp/timezone, source watermark and where a sanitized export is stored. Keep secret values and unnecessary sensitive rows out of the review bundle. Approved warehouse-only evidence may be represented by a bounded local receipt with an access-controlled reference and observed outcome; a reference without inspected evidence is not a pass.

Raw-layer catalogue context is required in addition to the repository inventory. Follow [raw-catalogue.md](raw-catalogue.md). Retain one normalized catalogue per provider/environment, its native metadata exports/collection receipts, and bindings from every selected physical input to exact catalogue objects/columns. Catalogue hashes remain separate from the repository snapshot; each binding file carries both. Missing/stale/incomplete catalogue context permits assessment but cannot pass model review completeness.

## Canonical model and lineage records

- Entity/model: stable ID; grain; composite/natural keys; attributes/types/units; source provenance; layer; materialization rationale; current/history policy; security; freshness; ownership status.
- Edge: source/target IDs and columns; join predicate; cardinalities; optionality; tenant/temporal conditions; unmapped references; evidence locations.
- Transformation: stable rule ID; original code location/hash; observed behavior; proposed expression and destination; dependencies/affected consumers; rationale; hypothesis/accepted status; confidence and gaps.
- Metric/report contract: population, dimensions, measures, aggregations, parameters/filters and order, totals, time/currency conventions, persona, export settings, watermark and independent expectation.
- Decision: competing alternatives, evidence, impacted rules/models, owner if stated, status, actual decision reference. An agent recommendation is not an accepted business decision.

Version the specification and render documentation, source-to-target mapping and ERD from the same version. If manually authored, explicitly verify agreement in review. Follow [model-documentation.md](model-documentation.md): an ERD, a complete table/column data dictionary, and documentation for bronze, silver and gold are mandatory model deliverables. Include reused and externally managed in-scope objects; missing evidence stays explicit.

## Specialist extraction and placement

For existing-project runs, use [orchestration.md](orchestration.md) for `inventory.json`, `dispatch-plan.json`, per-task extraction results and actual runtime records. Retain their hashes and the output of `verify_specialist_results.py`. A dispatch plan is pending work; neither task creation nor a returned file establishes completed parsing. Unsupported, partial, missing and stale source evidence stays visible.

The integrated lineage artifact includes the normalized source graph, original native-ID crosswalk and unresolved cross-project bindings. The model specification includes a placement plan keyed by rule ID, the warehouse and semantic architects' recommendations, disagreements, chosen dispositions and expected tests. Semantic emission targets Omni only when selected; otherwise preserve a target-neutral or explicitly chosen target contract.

Use `source_inventory` only for the single canonical inventory referenced by `source_snapshot_sha256`. Include dispatch and specialist results as separately hashed `lineage` artifacts, verification as `test_evidence`, and scope findings as `assessment`. Review scope must exclude unresolved source domains explicitly or keep them as blockers; do not omit a failing specialist from the denominator. `verify_review_package.py` does not replace specialist-result verification or independent semantic QA.

For specialist runs, set `specialist_dispatch_artifact_id` in the review manifest to the dispatch plan's `lineage` artifact ID. Preserve its relative inventory/result paths inside the review bundle and list those files individually as hashed artifacts. The review checker invokes specialist verification, checks their snapshot against the review inventory, and rejects incomplete or unhashed handoffs. Included specialist dispatch/results require that association even if the manifest field is removed. The source root must remain the canonical path recorded by the planner; a symlink replacement requires a new authorized snapshot. Omit the dispatch field only when no specialist dispatch was used, such as a standalone synthetic validation exercise. These checks do not authenticate the evidence or detect deliberate fabrication/removal of an entire evidence trail. Approval remains a separate human decision.

## Required review artifacts

| Role | Content |
| --- | --- |
| `source_inventory` | Selected source revision, file/asset hashes and coverage gaps |
| `warehouse_catalogue` | Scoped physical object/column catalogue, collection identity/time, visibility and enrichment coverage |
| `catalogue_bindings` | Complete selected physical-input reference set, exact namespaces/columns and catalogue/repository hashes |
| `catalogue_evidence` | Native metadata exports and collection receipts, individually hashed |
| `assessment` | Findings, business impact, consolidation candidates and unresolved evidence |
| `model_spec` | Conceptual/logical/physical model and report contracts |
| `erd` | Relationship diagram with grain, keys and temporal notes |
| `data_dictionary` | Canonical JSON and readable table/column definitions, types, null/key policies, lineage, units, classification and validation references |
| `layer_documentation` | Complete bronze, silver and gold model and operational contracts, with explicit model coverage and gaps |
| `lineage` | Original-to-target rules/columns and affected consumers |
| `decisions` | Preserved/corrected behavior, authority and pending decisions |
| `code` | Actual generated target artifacts; include every executable file and dependency/configuration file influencing execution |
| `test_plan` | Expected test inventory, independent oracles, categories, scope, tolerances and sampling |
| `test_evidence` | Executed results and diagnostics; retain failed cases |
| `runbook` | Development scope, deploy sequence, operational ownership, cutover and rollback |

## Review manifest v1

Write `review-package.json` at the bundle root with these fields:

```json
{
  "schema_version": 1,
  "source_snapshot_sha256": "64 lowercase hexadecimal characters",
  "warehouse_catalogues": [
    {"catalogue_artifact_id": "raw-catalogue", "bindings_artifact_id": "raw-bindings", "max_age_hours": 24}
  ],
  "target": {
    "framework": "selected framework",
    "warehouse": "selected warehouse",
    "versions": "actual versions or unverified for local review",
    "environment": "actual scoped environment or local-only"
  },
  "artifacts": [
    {"id": "inventory", "role": "source_inventory", "path": "evidence/source-inventory.json", "sha256": "64 lowercase hexadecimal characters"}
  ],
  "required_test_ids": ["grain-primary-key"],
  "tests": [
    {"id": "grain-primary-key", "category": "grain", "scope": "local", "status": "pass", "artifact_id": "test-results"}
  ],
  "not_applicable": [],
  "unresolved_blockers": []
}
```

This illustrates the shape and intentionally does not constitute a complete/passable package. Use actual hashes and include all roles, required test IDs and results. Enumerate artifacts individually with paths relative to the bundle root. Every referenced evidence file must be included and hashed. Paths must stay within the bundle; symlinks and self-references are rejected. Include all executable/configuration dependencies; the checker cannot discover omitted dependencies for you.

`source_snapshot_sha256` must match the sole `source_inventory` artifact. Accepted `scope`: `local` or `target`; `status`: `pass`, `fail`, `skipped`, `unavailable`. Categories are defined in [modeling-and-validation.md](modeling-and-validation.md). Local review requires source_contract, grain, fanout, logic, reconciliation, security, history, replay and negative_controls. Target review additionally requires target_compile, target_execution and operations, with target-scoped evidence for every applicable category.

`warehouse_catalogues` is a required nonempty array for both local and target review. Each entry points to distinct hashed `warehouse_catalogue` and `catalogue_bindings` artifacts and records the accepted positive `max_age_hours`. Include every native export referenced by the catalogue as `catalogue_evidence`, preserving relative paths beneath its directory. The checker invokes `verify_catalogue.py` and rechecks raw export hashes, age, scope/column bindings and alignment with the repository snapshot. Removing the catalogue association is an error. A synthetic catalogue is permissible for a local exercise only and is rejected for target review. Other test categories and human authority remain independently required.

`model_documentation` is also required at both review stages. It associates a hashed JSON model inventory (`model_spec`), the canonical JSON `data_dictionary`, a separately associated readable dictionary, and exactly one entry for each bronze/silver/gold layer with `document_artifact_id`, `erd_artifact_id` and complete `model_ids`. See [the precise coverage schema](model-documentation.md#machine-readable-coverage-contract). The dictionary pins the inventory hash and covers every declared model/column. The checker rejects missing layers, wrong artifact roles, duplicate/omitted definitions and stale inventory bindings. Independent QA must still establish the actual inventory and verify the readable ERD/dictionary/layer content; the helper does not infer schema or judge prose truth. The abbreviated manifest above is incomplete without this association.

If `history` or `replay` is truly inapplicable, supply a `not_applicable` entry with `category`, `rationale`, and an `artifact_id` pointing to a human decision in a `decisions` artifact. Do not use this mechanism to waive absent evidence or known risk. Other categories require a real assertion, which can establish that there are no joins, no sensitive fields, or no additional transformations when that is the evidenced situation.

Required tests come from the accepted model/consumer inventory and test plan. Keep that denominator explicit; do not remove failing tests or whole assets to produce a green run. Record unknown/omitted scope in `unresolved_blockers`. Decisions still pending block completeness when they affect the proposed models; unrelated deferred domains can be explicitly outside the selected scope.

Check the package:

```sh
python3 scripts/verify_review_package.py /absolute/bundle/review-package.json --stage local
python3 scripts/verify_review_package.py /absolute/bundle/review-package.json --stage target
```

The command reads files only, returns nonzero on incomplete/invalid evidence, and never deploys or grants approval. It verifies structure, file integrity, category coverage and declared results. It does not execute tests, establish evidence authenticity, confirm business truth, verify human identity, or discover dishonest omissions. Real acceptance requires review of the evidence and independent target observations.

## Human approval and execution receipt

Keep approval outside agent-generated test claims: actual approving user/authority; decision reference; scope; source snapshot hash; model/code/docs/test-plan hashes; test-run/environment identity; approved intentional discrepancies; time; and explicitly authorized action. For a release, additionally bind the exact framework/dialect/dependency versions and destination. Never turn a generated manifest, boolean, copied message, or unsigned local file into authority.

Any approved deployment handoff includes those records and a receipt after execution: attempt identifier, returned object/run IDs, actual target identity, checksums or target definition readback, verification results, and partial/unknown failure status. The bundled checker stops at review completeness; deployment enforcement belongs in the authorized platform/CI controls.
