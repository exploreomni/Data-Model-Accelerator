# Selected deliverables and a usable handoff

Read after [discovery.md](discovery.md) and before target artifact generation. Confirm the missing choices that change the output; reuse choices and execution authority already supplied. This reference controls delivery presentation. The full evidence, authority and documentation requirements in the skill remain in force.

## Record what was requested

Offer understandable selections: model documentation, connected SVG diagrams, data dictionary, selected-path implementation, validation tests/results, optional sample or seed data, and a separate optional technical audit export. Users may select a subset. Record the intended audience, engagement type, framework, warehouse, semantic scope and prerequisites with the selection. A reusable model and its complete internal documentation remain the basis of every export.

A small delivery-selection record can look like this (the durable engagement also records interview and evidence context):

```json
{
  "schema_version": 1,
  "engagement_type": "migration",
  "framework": "dbt",
  "warehouse": "snowflake",
  "semantic_target": "retain_existing",
  "audience": "analytics_engineers",
  "deliverables": ["implementation", "diagrams", "documentation", "dictionary", "validation"],
  "request_only": true,
  "note": "Requested handoff contents; no execution or business approval is asserted."
}
```

The engagement types are `migration`, `refactor`, `new_model`, and `blind_test`; framework choices use `dbt`, `coalesce`, or `native_sql`; guided warehouse choices are `snowflake`, `databricks`, `bigquery`, `redshift`, `clickhouse`, or `motherduck` (`gcp` requires clarification; DuckDB remains a separate local test target). Deliverable IDs are `implementation`, `diagrams`, `documentation`, `dictionary`, `validation`, `sample_data`, and `technical_audit`. Audience and semantic target are optional fields populated from discovery. A blind-test example uses `blind_test`; do not silently carry that label into a migration.

This is a request record, not an evidence/authority contract or a claim that every combination has been qualified. Coalesce follows its native emitter and selected-platform contract; do not relabel it as native SQL to fit an exporter. **The record grants no execution authority and approves no business definitions.** Actual action stays within the user's stated authorization and existing environment/evidence gates. Missing values remain unresolved in discovery instead of being filled from an unrelated source convention.

## Maintain one current entrypoint

Reuse the engagement's existing `START_HERE.html`, or its selected `START_HERE.md` fallback, as the authoritative working entrypoint. Refresh that page through the shared delivery workflow as the work advances. Do not create another portal, overview or summary document at each milestone. If no entrypoint exists, create it once and retain its location.

Offer at most three primary choices, appropriate to the selected stage and audience:

- **Data model:** choose one gold output and read its upstream pipeline from top to bottom. Show full names, brief keys and new/reused status at a readable natural size. Selecting a table opens its columns, joins and exact code links; the detailed ERD remains available separately. Keep the project/target and candidate status visible. Supplemental views retain inputs and interfaces outside the gold pipelines.
- **Code & files:** the selected implementation, supporting configuration/tests, integration guide and file index. Default to a table-linked file; classify an unmapped file as supporting/unmapped rather than guessing which model it implements. Reviewer packages show explicit code omission. File-index selections scroll to the selected preview. Generated SVGs and dictionaries open visually with an original-source toggle; copy and download retain original file text/bytes.
- **Validation:** concise readiness and next actions, with full required evidence and outside-scope checks available on demand. Failed, unsupported or stale evidence remains visible in the opening summary.

Use the same sidebar to reach feedback, dictionary, lineage and supporting details. Table-specific feedback is a request, bound to the exact page/context. Check `review_feedback.py --page /absolute/current/START_HERE.html --responses /absolute/model-review-feedback.json` before the host reconciles corrections into canonical records. Reject stale or unknown-table feedback; never treat a response as design approval or deployment authorization.

Use progressive disclosure for the full inventory, detailed validation, dependency ledgers and technical audit. Keep material failures and blockers visible in the opening review summary; moving evidence behind a detail link must not hide its effect on readiness. These choices organize navigation, not exporter categories or approval scope. Do not expose code in reviewer exports or link to files excluded from a smaller package.

Maintain one current human-readable design document, bound to the canonical design identity and revision. Link its domain/layer detail, complete dictionary and required evidence rather than creating competing executive summaries, model guides or design narratives. Required internal documentation remains complete. Record durable decisions, rationale, evidence and affected scope in the existing canonical design/decision and stage records; chat and rendered pages are projections, not alternative sources of authority.

## Keep two packages distinct

The **user handoff** uses the finalizer's default `--layout simple`: one root `START_HERE.html` (the [review page](review-page.md)) and five sections for the selected files:

```text
Handoff/
  START_HERE.html
  01_Input_Sources/        input inventory and permitted source artifacts
  02_Input_Context_Files/  selected requirements, rules and catalogue context
  03_Design_Documents/     design narrative, gold pipelines and dictionary
  04_Code_Generation/     warehouse/semantic code, setup and validation
  05_Mappings/            historical-to-target mappings and migration documents
Technical_Audit/          separate optional export
```

Original repositories remain at their registered roots; packaging does not clone them. Only explicitly registered, selected and audience-permitted files enter the handoff. When documentation is selected, section guides explain missing or unselected content; an empty section does not establish stage completion. `--layout classic` retains the older `01_Model/`, `02_Implementation/`, `03_Validation/` and optional sample-data paths. A domain review uses its own layout (`01_review/`, `02_dbt/`, `03_omni/`, `04_docs/`); see the [domain review page](domain-review-page.md).

Use plain labels, portable relative links and a dependency/run order. The entrypoint states what was generated, the target, actual checks, prerequisites, unresolved decisions and the next concrete action. Link directly to the selected design and code.

The exporter preserves each registered path beneath its selected section/category folder. An optional type-compatible artifact `section` selects `input_sources`, `input_context`, `design`, `code` or `mappings`; see [review-surface.md](review-surface.md#content-contract). Write Markdown references for that final location; the exporter rejects unresolved or unsafe internal links and requires linked artifacts to remain selected. It does not rewrite bytes after review. Check the resulting extracted folder layout as well as the offline guide. New integrity manifests bind the package to the workflow's `context_sha256`; this digest is an integrity association, not an approval or execution receipt.

Keep prior exports and their manifests immutable. The live entrypoint may be refreshed, while a newly requested export uses a new version and contains its own portable `START_HERE.html` snapshot. Those frozen copies do not become competing working portals. Do not revise an old ZIP, reviewed artifact or evidence receipt to make it appear current.

The **technical audit** retains the complete review package, canonical inventory/dictionary, source/catalogue and code snapshots, lineage, decisions, immutable baselines, actual exports, validation results, execution records and hashes. Preserve each run as a new version. It stays outside the compact handoff and is available as a separate download when requested; `technical_audit` does not add audit files to the working folders. Do not copy sensitive source rows into a broad handoff merely because they exist in the audit; preserve applicable access and data-sharing limits.

Selecting fewer exports never removes mandatory internal ERD, dictionary or bronze/silver/gold documentation, shrinks the source/consumer/model denominator, drops failing tests, or bypasses [review-package](contracts.md), [model-documentation](model-documentation.md) or [engagement-validation](engagement-validation.md) gates. A documentation-only request need not generate executable code; its status remains scoped to the work and checks actually performed.

## Make code usable for the chosen path

Deliver real files in dependency order with prerequisites and environment configuration. Include a short setup/run guide naming the selected runtime/adapter versions, required source objects, namespaces, external dependencies, safe configuration locations and the exact ordered steps. Keep credentials outside the package. Unresolved placeholders must be explicit and prevent claims that execution is ready.

- **dbt:** for existing projects, deliver a focused patch against a pinned source revision, preserving CI, packages, configuration and untouched models, plus integration instructions and pinned dependency/runtime requirements. Preserve sound transformations instead of adding wrapper models merely to create new code. An optional complete reference snapshot can accompany the patch when requested and permitted by the exporter and disclosure rules; it is not the default working deliverable. Retain required macros, hooks, materializations, seeds/snapshots and tests, or identify their exact pinned external acquisition requirements. A reference subset with unresolved dependencies is not a standalone runnable project. For new projects, deliver a complete coherent project, including `dbt_project.yml`, selected models, source declarations, required macros/configuration, documentation and applicable tests. Provide a nonsecret profile template or precise profile setup instructions. State the scoped project command sequence and target, respecting existing execution conventions. `ref`/`source` and Jinja belong in this project; do not tell a user to paste individual dbt model files into a warehouse SQL editor.
- **Native SQL:** deliver numbered files in the selected warehouse dialect, with qualified dependencies, environment setup, implementation, verification and recovery steps as applicable. The SQL intended for an editor must contain no unresolved dbt Jinja or `ref`/`source` calls. Use the actual selected platform's namespace, decimal, timestamp and materialization behavior; a generic SQL folder does not prove portability.
- **Other native formats:** use the separately qualified target contract. SQL alone is not a native Coalesce project, and documentation alone is not a deployed semantic model.
- **Omni:** explicitly register native `.view`, `.topic` and the exact extensionless `relationships` file as implementation artifacts. They ship with their original names and hashes. Deliver real model bodies and native setup/validation instructions; file inclusion alone does not prove successful Omni validation.

Validation summaries are selectable exports; applicable validation requirements still govern any claimed validation status. Do not remove tests or configuration required by a coherent implementation merely because the summary is unselected. Distinguish generated tests, tests actually executed, failed/missing checks and remaining target-specific acceptance. Do not present fixture execution as warehouse or Omni acceptance.

Keep generated, locally checked, natively validated and human-accepted readiness distinct, with the exact scope and evidence for each. A generated file is not an executed model; a local check is not native validation; native success is not business acceptance or deployment authority. Missing, stale or failed evidence remains explicit. Use existing stage and evidence records for these claims rather than inventing a single completion badge.

Reference snapshots follow the same registered-file, size, audience and dependency constraints as other artifacts. Do not nest an archive inside an export, silently drop unsupported files, or strip required runtime/tests to fit a limit. Partition through the existing export workflow or record the external prerequisite and precise coverage gap.

## Sample data is optional; dependencies are not

Include seed rows only when requested and allowed for the intended audience. Identify whether they are supplied, sanitized or synthetic, their source/hash, and the supported load path. Keep seed dependencies explicit in both the code and startup instructions.

When a selected example implementation requires its bundled seeds, explain that dependency and keep those seeds selected with the implementation. Do not allow a checkbox to produce a broken dbt project. For a package that omits seeds, use confirmed existing source relations or document the exact external seed acquisition/load requirement. Do not leave broken `ref` dependencies, silently replace supplied rows with invented examples, or claim a self-contained runnable package. If the user needs a self-contained local demonstration, confirm whether approved supplied/sanitized data or explicitly synthetic fixtures should be included.

## Render connected SVGs

When selected, ship actual SVG files plus editable diagram sources. Use the model inventory and reviewed relationships from [model-documentation.md](model-documentation.md), with these presentation requirements:

- Default to one upstream pipeline per concrete gold model. Read raw/source → staging/preparation → intermediate → gold from top to bottom; preserve actual dependencies even when they skip a stage or reuse another gold model. Retain isolated inputs and unresolved interfaces in labeled supplemental views.
- Group pipeline choices by recorded domain and expose an All domains filter. Use the gold output's membership rather than its ancestors' domains; preserve cross-domain dependencies in each view. Keep Unassigned and shared/multiple-domain groups explicit. Domain filtering is navigation only, separate from the active-domain workflow and full package scope.
- Use fixed-size readable cards with full names, brief supplied PK/FK or declared-key labels, and new/reused status. Keep the full dictionary and edge details outside the main diagram. Large pipelines scroll instead of shrinking all labels; explicitly flag cycles without dropping their edges or inventing execution order.
- Transformation arrows come only from recorded lineage or `depends_on`. Keep logical joins, roles, predicates and cardinality in the detailed ERD/table inspector. A join never creates an inferred transformation dependency or proves an enforced constraint.
- Add semantic views and topics only from explicit warehouse-model and view-membership bindings. Do not infer physical mappings from matching names or treat a semantic placement as native verification.
- Inspect the actual rendered output for clipped text, overlaps, detached endpoints and density. Confirm complete supplied model coverage across primary and supplemental views.

The diagram and dictionary must describe the same pinned model as the selected code and review evidence. A readable SVG is a presentation result; it does not establish actual constraint enforcement or production acceptance.

## Communicate milestones without multiplying artifacts

Keep chat milestones concise: state the outcome or useful learning, then the next action and any material blocker. Skip routine file inventories and repeated plans. Update canonical records and the same entrypoint when a decision or readiness change needs to persist; do not manufacture a new portal or summary for the update.

The final response gives one primary link to the current entrypoint, the delivered outcome, material limits and the next concrete action. Keep full file lists, validation receipts and optional audit downloads inside the delivery. A later requested export is a versioned snapshot of the same engagement, not a new engagement or a replacement for its durable decisions.

## Reusable implementation

The shared [guided workflow](guided-workflow.md), [platform adapters](platform-adapters.md) and [review renderer/exporter](review-surface.md) implement this presentation path for all selected frameworks and warehouses. Use them instead of cloning a fixture-specific portal. The agent supplies the actual model/code and authoritative evidence through existing contracts.

## First-use acceptance

The recipient receives one named current ZIP and one extracted handoff location. Keep work files, screenshots, superseded immutable exports and technical audit outside it; never overwrite frozen exports to clean the view. The generated root README is an extraction/file index, not another design narrative. Selected dictionaries ship all supplied columns in CSV; simple layout adds a compact Markdown table index linking that CSV. Classic layout retains the full Markdown column table. Selected diagrams ship as SVG views plus editable model source. Generated projections are identified separately from immutable registered files in the manifest, and must match the selected inventory. Screen filters do not change the canonical model or approval scope. Diagram downloads state whether they contain the current pipeline/view or the complete permitted set; the selected handoff retains its declared scope.

Before handoff, run page/package integrity, JavaScript syntax and stub-DOM checks, then inspect the actual extracted HTML in a browser. Check initial context, all scoped tables, responsive inspector/back behavior, table-to-code mapping, download/copy, first-click navigation, feedback freshness and code/readiness omissions. Test smaller exports and legacy packages as well. A fresh reviewer must complete open → model → table → code → readiness → feedback without chat history. Report browser limitations honestly and retain the observations outside the customer package. Synthetic usability exercises cannot establish native or business validation.

Use the [finalizer](review-surface.md#finalize-the-selected-handoff) for the final
selected delivery. It checks actual files and creates the ZIP plus extracted
handoff together. The coordinator must not substitute a source clone, candidate
folder, status-only page or `handoff_prepared` message for that result. Explain that
`03_Design_Documents/` is the simple layout's design folder (`01_Model/` in classic layout). Missing outputs require repair or an explicit
incomplete status, not another full model run or a silent reduced selection.
# Early checks and large deliveries

Use `delivery_preflight.py --run-dir <engagement> --review <review.json> --artifacts <candidate>`
before assembling the final export. It reports selected formats, audience, sizes,
catalogue availability and missing disclosure context without changing draft authority.
The finalizer includes this report and separate artifact-delivery, native-validation,
business-approval and deployment states in its receipt. An explicit scoped draft
request allows prepared provisional files; `--checkpoint` means genuinely incomplete work.

Simple-layout deliveries with more than 100 models or 200 selected files use one
root Start Here with domain/output navigation and bounded offline table, code and
pipeline pages in `03_Design_Documents/Review/`. The original code stays in
`04_Code_Generation/`; pages only display it. Excel/Word/PDF and mappings have direct
links in Migration plan. Small and classic deliveries retain their existing renderer.

The maintained large-package route scans each exact member within the document
limit, then verifies every member, path and hash in the assembled container. It
does not raise the generic incoming-archive scanner limits. There is no clean-scan
override: unsupported rich content or unresolved disclosure still prevents export.
Raster figures are not OCR-verified; retain their documented coverage limitations.
