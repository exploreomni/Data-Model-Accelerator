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

- **Overview:** outcome, current scope and readiness, material decisions or blockers, and the next action.
- **Design:** the maintained design document and connected model views, with deeper inventory and dictionary links available on demand.
- **Implementation:** the selected patch or native code, integration prerequisites and run instructions, when included for that audience.

Use progressive disclosure for the full inventory, detailed validation, dependency ledgers and technical audit. Keep material failures and blockers visible in Overview; moving evidence behind a detail link must not hide its effect on readiness. These choices organize navigation, not exporter categories or approval scope. Do not expose code in reviewer exports or link to files excluded from a smaller package.

Maintain one current human-readable design document, bound to the canonical design identity and revision. Link its domain/layer detail, complete dictionary and required evidence rather than creating competing executive summaries, model guides or design narratives. Required internal documentation remains complete. Record durable decisions, rationale, evidence and affected scope in the existing canonical design/decision and stage records; chat and rendered pages are projections, not alternative sources of authority.

## Keep two packages distinct

The **user handoff** is the small working package. For a full delivery, use three to five numbered folders with one `START_HERE.html` or `START_HERE.md` at the root. A useful three-folder layout is:

```text
handoff/
  START_HERE.html
  01_Model/           selected model, connected diagrams, docs and dictionary
  02_Implementation/ selected framework project or native SQL and setup guide
  03_Validation/     selected tests, concise results and remaining checks
Technical_Audit/     full versioned review and execution evidence (separate ZIP)
```

Omit unselected artifacts and unnecessary empty folders. A separate fourth folder for explicitly requested sample data can help when it is substantial. Use plain labels, portable relative links and a dependency/run order. The entrypoint states what was generated, which target it is for, what was actually tested, prerequisites, unresolved decisions, and the next concrete action. Link directly to each selected deliverable; do not make the user navigate execution receipts to find the model or code.

The exporter preserves each registered path beneath its category folder. Write Markdown references for that final location; the exporter rejects unresolved or unsafe internal links and requires linked artifacts to remain selected. It does not rewrite bytes after review. Check the resulting extracted folder layout as well as the offline guide. New integrity manifests bind the package to the workflow's `context_sha256`; this digest is an integrity association, not an approval or execution receipt.

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

- One table block per physical object within a view, grouped by layer or coherent domain. Show qualified identity, grain and key columns with PK/FK roles; use stable identities across views.
- Draw lines between the blocks. Show cardinality and optionality, including tenant/effective-time predicates where applicable. Label role-specific joins such as bill-to versus ship-to on distinct edges to the same dimension.
- Distinguish transformation lineage from logical joins and observed/enforced constraints. Use separate views or explicit line styles with a legend; an ingestion arrow must not imply a foreign-key constraint. Mark unresolved/inferred edges truthfully.
- For a dense model, provide a connected overview and coherent layer/domain views with cross-references. Preserve object/relationship coverage across those views. Do not replace the model with disconnected table pairs or repeat a central table once per edge.
- Visually inspect the rendered output at a readable viewing scale. Resolve clipped text, overlapping labels/lines, detached endpoints and unreadable density. Confirm that isolated source objects remain represented, with their status explained.

The diagram and dictionary must describe the same pinned model as the selected code and review evidence. A readable SVG is a presentation result; it does not establish actual constraint enforcement or production acceptance.

## Communicate milestones without multiplying artifacts

Keep chat milestones concise: state the outcome or useful learning, then the next action and any material blocker. Skip routine file inventories and repeated plans. Update canonical records and the same entrypoint when a decision or readiness change needs to persist; do not manufacture a new portal or summary for the update.

The final response gives one primary link to the current entrypoint, the delivered outcome, material limits and the next concrete action. Keep full file lists, validation receipts and optional audit downloads inside the delivery. A later requested export is a versioned snapshot of the same engagement, not a new engagement or a replacement for its durable decisions.

## Reusable implementation

The shared [guided workflow](guided-workflow.md), [platform adapters](platform-adapters.md) and [review renderer/exporter](review-surface.md) implement this presentation path for all selected frameworks and warehouses. Use them instead of cloning a fixture-specific portal. The agent supplies the actual model/code and authoritative evidence through existing contracts.
