# Guided multiplatform delivery implementation plan

## Outcome

Give a new operator one reusable journey from an existing repository to an inspectable, selected handoff. Keep agent host, source formats, transformation framework, warehouse and semantic engine independent. This change implements local guidance, readiness, resumable workflow state and portable delivery; it does not claim newly qualified cloud execution or a universal code compiler.

## Task 1 — Platform readiness (implement and test first)

Create a declarative adapter registry and bounded read-only compatibility collector for dbt, Coalesce, Snowflake SQL, Databricks and BigQuery. Report findings with evidence paths, coverage and remedies; distinguish assessment, agent-assisted generation and existing qualified execution. Never execute input code or resolve credentials. Test mixed projects, incomplete scans and incompatible configuration.

## Task 2 — Guided engagement state

Create one CLI with start, answer, assess, status and resume actions. Persist discovery answers, source/catalogue/target identity, decisions and version-bound evidence. Missing migration intent blocks dependent generation; existing answers persist. Drift invalidates dependent claims. Never promote an operator assertion into verified execution or approval. Test interruption, changed inputs and stage boundaries.

## Task 3 — Reusable review and export

Render an offline review page from engagement data: next action, readiness, before/after change table, decision queue, layered model, dictionary, script navigation and evidence detail. Export physically separate reviewer/engineering/audit packages with selected artifacts, relative paths and a hash manifest. Reject unsafe paths and stale bytes. Derive statuses from records, never fixture counts. Test selection, portability, escaping and package omissions.

## Task 4 — Integrate and qualify

Update skill routing and one operator start guide; document adapter extension contracts and current support levels. Exercise every supported target choice and failure/resume path in synthetic projects. Run existing core regressions, independent forward testing and browser QA. Produce a portable preview and implementation handoff. Native vendor execution remains explicitly untested without an authorized target.

## Shared implementation contract

- `platform_readiness.py`: `assess_repository(repo, framework, warehouse, **options) -> dict`; result includes schema_version, source fingerprint, coverage, findings, detected sources and independent assessment/generation/execution status. Details are owned by that module and documented in its tests.
- `guided_workflow.py`: local engagement lifecycle and CLI; JSON-safe durable state with schema_version, engagement_id, answers, inputs, readiness, evidence, history, status and next_actions. Source repository is read-only. Renderer accepts this state as data.
- `delivery_portal.py`: presentation and export; optional review content JSON supplies model inventory, changes, dictionary, validation cases and explicitly classified artifact records. No discovered file is shared by default.
- Existing verifiers remain authority for their qualified lanes. New UX records summarize, not replace, those gates. All external execution/publication stays outside these helpers.

Parallel work is limited to the independent readiness and state modules; dependent integration and qualification follow completed implementations.
