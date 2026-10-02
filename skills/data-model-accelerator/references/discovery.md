# Discovery before generation

Start by understanding the engagement and the result the user wants. Use short interview rounds, normally one to three related questions at a time. Reuse the request, previous answers and supplied evidence. The prompts below are a menu, not a form to read aloud in full.

Complete the meaningful choices before generating dependent target models, code, diagrams or delivery exports, and before executing them. A user who already supplied those choices has completed this part of discovery; summarize them and proceed within the existing authorization. Do not add a ceremonial confirmation. Read-only inventory, profiling and evidence collection may continue while an answer is pending.

## Round 1: intent, outcome and audience

- Is this a **migration**, a **refactor** of the existing implementation, a **new model**, or a **blind test**? Reuse an explicit description instead of asking for the label again.
- What business decision, report, domain or failure should the work address? Who will use the result: business reviewers, analysts, analytics engineers, platform operators, or several of these?
- Which outputs are wanted: model documentation, connected SVG diagrams, data dictionary, implementation for the selected target, validation tests/results, optional sample/seed data, or an optional technical audit export? See [delivery-experience.md](delivery-experience.md).

For a blind test, record the permitted evidence boundary and prohibit solution/example contamination. For a new model without existing reports, identify proposed definitions and independently specified expectations. Neither mode inherits a migration baseline or established business approval.

## Round 2: sources and behavior

For migration, establish these before choosing what to translate:

- Exact source projects, repositories/revisions, native artifact IDs, dialects, export formats and available parser coverage. An upstream dbt project describes a source; it does not choose dbt as the target.
- Trusted report or SaaS baseline: report ID/version, extraction time, source watermark, user/persona, population, hidden/default filters, period, timezone, currency, status inclusion, null/empty behavior, history and effective-date rules. Obtain detailed rows when available; totals alone cannot prove attribution.
- Behavior to retain versus intentionally change: formulas, exclusions, manual adjustments, interactions, security and known compromises. Preserve observed behavior and proposed corrections as separate contracts. Identify who can resolve disputed meanings using actual stated authority.
- Downstream consumers, exports, schedules and semantic/report dependencies; what moves, stays, changes, or is proposed for retirement. Establish pilot and cutover scope, compatibility criteria, recovery expectations and any explicitly stated timing. A retirement proposal grants no deletion authority.

Across engagement types, establish the available physical catalogue, schemas and source-value evidence; row grains and tenant/key scope; replication, corrections, deletes and history; and representative permitted/denied security contexts when access testing is in scope. Unknown facts remain unknown. Do not invent source guarantees, owners or a business baseline to fill the questionnaire.

## Round 3: target and execution boundary

Choose these independently, reusing any explicit choices:

| Choice | Resolve before dependent generation or execution |
|---|---|
| Agent host | Actual host/tool surface and available file/delegation capabilities |
| Transformation framework | dbt, qualified Coalesce path, or native SQL; do not infer it from the source project |
| Warehouse | Exact platform and relevant version/runtime; ask whether GCP means BigQuery when ambiguous; DuckDB is a local option when selected |
| Semantic target | Retain the current engine, use Omni, another selected target, or no semantic code in scope |
| Environment | Account/workspace/project, database/schema/dataset, location and source destinations; placeholders are acceptable for an explicitly nonexecuted handoff |
| Mode and authority | Assessment, candidate generation, authorized local/development execution, or deployment handoff; record existing authorization, environment, identity/role, row/date limits, cost ceiling, timeout and external actions |

Clarify whether Cortex/Genie names an agent host or a different product surface when that affects the path. A framework/warehouse combination is a request, not proof that a qualified emitter or runtime is available. Follow [targets-and-hosts.md](targets-and-hosts.md) for the chosen path; state unsupported generation or validation plainly.

Selecting deliverables does not authorize executing their code, publishing a repository, changing a warehouse or retiring a source. Conversely, do not ask for permission again when the user has already authorized the specific action and environment. Resolve missing meaningful choices with the user; do not treat a suggested default, silence or a generated selection file as confirmation.

## Record the outcome and continue useful work

Record confirmed selections, stated authority, unknown facts, unresolved decisions, and which outputs depend on each gap. A lightweight selection record is described in [delivery-experience.md](delivery-experience.md); it is separate from the evidence/authority contracts.

- **Decision missing:** ask the smallest question that changes the result. Hold its dependent deliverables or execution; continue independent read-only work.
- **Fact unavailable:** produce a bounded assessment showing the evidence and gap. Mark affected model branches provisional or blocked; do not fill them with plausible business meaning.
- **Answers already supplied:** proceed within the chosen scope. Do not repeat the interview or turn routine implementation choices into new approvals.
- **Scope changes:** update the selections and affected specification, preserve the previous version, and invalidate affected evidence. Retain still-valid answers and permissions.

## Evidence needed by stage

- **Assessment:** source inventory, parse/coverage status, known outputs and explicit gaps. Code alone can support this stage.
- **Candidate model:** scoped raw catalogue and actual object/column bindings, plus evidenced grains and explicit proposals. Without a catalogue, deliver assessment hypotheses and the collection request rather than claiming a physically grounded model. Missing history cannot be recovered by assertion.
- **Local semantic tests:** representative sanitized/synthetic data, independently specified expectations and stated limits.
- **Target validation:** exact generated revision, target/compiler versions, authorized development scope, source watermarks, actual execution records and applicable access probes.
- **Business approval:** selected definitions, known discrepancies, aligned evidence, exact model/code/docs versions and the actual human decision.

## Why this discovery exists

The motivating problem is report-specific logic added under delivery pressure until output agrees with a SaaS report. That agreement can hide competing definitions, manual corrections, grain problems or security differences. The accelerator should turn the evidence into a reusable model and reviewable change, with explicit consumer impact and decisions that need an authority.

The original request for an assessment, target model, documentation, ERD, code and tests describes one useful full delivery. It is not a mandate to export every artifact for every user. Requested presentation can be small while the internal model documentation and validation denominator stay complete.
