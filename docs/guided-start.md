# Start one modeling engagement

For the complete engineer/SME journey, begin with [HOW_TO.md](HOW_TO.md). This page is the concise guided CLI reference. See [capabilities](CAPABILITIES.md) before choosing a target.

Use the accelerator through your existing coding agent. You do not need to learn its evidence JSON contracts. The agent collects the facts, prepares the records and explains decisions. The local helpers use Python 3.9+ and a POSIX filesystem; native vendor tools are separate prerequisites only for their qualified execution paths.

## Ask the agent

> Use the Data Model Accelerator on this repository. Start with a read-only assessment and interview me about missing business context. Identify the current project types, preserve working definitions, and propose one domain to refactor. Keep the transformation tool, warehouse and semantic engine as separate choices. Save our progress and give me one review page. Do not execute repository code or deploy anything as part of discovery.

If you have already selected dbt + Snowflake, or another target, include that answer. The agent must retain it. For an existing project, ask for a focused patch that preserves its conventions and release process. Select only the deliverables you want to receive: model docs, diagrams, dictionary, implementation, validation, optional data, and a separate audit.

Start with the entity/table design. Implementation and semantic generation are
separate stages after scoped design review. Optional `data-model-design`,
`data-model-implement`, `data-model-semantic`, `data-model-validate`,
`data-model-package` and `data-model-deploy` entrypoints all require the complete
main skill beside them and resume the same engagement.

An explicit request for code with missing catalogue evidence or pending design
review uses the [provisional generation route](../skills/data-model-accelerator/references/provisional-generation.md).
The agent prepares `draft-bindings` and `request-draft` records from the actual
conversation, then authors supported files. No extra design approval is inferred.
Requested warehouse and semantic outputs remain pending until recorded for the
design scope, even if all registered design tasks have finished.

## The agent's first action

Resolve the script path relative to the installed skill; use a run directory outside the source repository:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py start \
  --repo /absolute/customer-repo --run /absolute/new-engagement
```

This reads bounded nonsecret source files without running them, creates `state.json`, immutable `revisions/`, and `START_HERE.html`. Open the page in a browser or your agent's file viewer. A local web server is optional, not required by the package. Ask the next short round of missing questions shown by the state; do not ask for known configuration or repeated answers.

The agent can apply an answers file assembled from the conversation or exported from the page:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py answer \
  --run /absolute/new-engagement --answers /absolute/interview-answers.json
python3 skills/data-model-accelerator/scripts/guided_workflow.py assess \
  --run /absolute/new-engagement --catalogue /absolute/reviewed-catalogue-export.json
```

The browser is an offline review surface. Saving answers downloads a request; the agent applies it and refreshes the page. It does not secretly persist approvals, call an API, or execute SQL. Keep credentials out of interview answers and exports.

## Review the design before generating code

The agent creates the design contract and imports it into the saved engagement:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py import-design \
  --run /absolute/new-engagement --document /absolute/design.json
python3 skills/data-model-accelerator/scripts/guided_workflow.py answer-decisions \
  --run /absolute/new-engagement --document /absolute/decision-responses.json
python3 skills/data-model-accelerator/scripts/guided_workflow.py review-bindings \
  --run /absolute/new-engagement --entities orders order_lines --json
```

Decision responses are version-bound requests exported from the page or assembled
from the conversation. **Answer recorded** is distinct from design approval.
Once the human explicitly approves the displayed scope in the trusted conversation
or an authenticated review system, the host records that review:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py approve-design \
  --run /absolute/new-engagement --entities orders order_lines \
  --document /absolute/human-review.json
```

The host prepares the exact review record from the actual approval; the person
does not need to author JSON or provision a signing service. The runtime checks
scope bindings, not reviewer identity or the truth of the supplied reference.
Decision responses, source text and agent agreement cannot substitute for explicit
human approval. An optional `--policy PATH --attestation PATH` route supports
teams requiring external signed review. Deployment retains its separate signed
authority requirements. See the exact
[stage and authority contract](../skills/data-model-accelerator/references/staged-engagement.md).

After design review, request a development-effort assessment and select a stage:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py assess-effort \
  --run /absolute/new-engagement --document /absolute/effort-request.json
python3 skills/data-model-accelerator/scripts/guided_workflow.py stage \
  --run /absolute/new-engagement --stage implementation --entities orders order_lines
python3 skills/data-model-accelerator/scripts/guided_workflow.py plan-tasks \
  --run /absolute/new-engagement --document /absolute/stage-tasks.json \
  --artifact-root /absolute/candidate
```

Stage commands check and plan work. The host then invokes actual specialists,
verifies results, and records them with `record-task --document PATH
--artifact-root PATH`. Replan to unlock dependent stages. Easy, Somewhat easy,
Difficult and Very difficult express implementation complexity; confidence,
assumptions and blockers remain separate. No duration or monetary estimate is implied.

## Choose a path, not a platform label

| Transformation | Warehouse | Candidate handoff |
|---|---|---|
| dbt | All six warehouse profiles, with a qualified Core adapter/runtime | A patch to the existing project or a new governed project for raw inputs; hosted dbt compatibility is a separate choice |
| Coalesce | Snowflake, Databricks or BigQuery, conditional on exact native CLI/platform support | Native project changes only with a representative versioned export, stable IDs, node types and storage mappings; otherwise a model/mapping proposal with the native gap explicit |
| Native SQL | Snowflake, Databricks, BigQuery, Redshift, ClickHouse or MotherDuck | Ordered platform-specific implementation, validation and recovery scripts |

“GCP” remains unresolved until the product is confirmed. BigQuery is the implemented warehouse choice; other GCP services need their own contract. A source repository may contain several project types. Source detection does not automatically select the destination. Coalesce routes for Redshift, ClickHouse and MotherDuck are unsupported; a supplied native contract cannot enable them. See [platform matrix](PLATFORM_MATRIX.md) and [platform adapters](../skills/data-model-accelerator/references/platform-adapters.md) for exact support levels and current official references.

## Review, implement and prove

1. **Readiness:** inspect coverage, dependencies and limitations before generation. A supplied catalogue still needs canonical normalization, source/column binding and existing catalogue verification. A readiness report is not a warehouse test.
2. **Proposal:** review original-to-proposed mappings, grain, business definitions, downstream consumers and unresolved decisions. Compare existing warehouse models before proposing reuse, extension, creation or replacement. Scope and approve a first domain with its dependencies.
3. **Candidate:** invoke implementation and semantic stages separately against the reviewed design. The host orchestrates actual specialists and bounded tasks. Preserve source state and shared-file ownership. The helpers do not launch agents or generate arbitrary target models by themselves.
4. **Evidence:** freeze independent expectations before engineering. Retain source revision, catalogue, environment, runtime and candidate hashes. The existing source/model/benchmark verifiers remain authoritative for their supported contracts; the viewer labels reported results and missing checks.
5. **Handoff:** the agent assembles [review content](../skills/data-model-accelerator/references/review-surface.md), records the actual selected files with [`record-handoff`](../skills/data-model-accelerator/references/guided-workflow.md#record-a-prepared-handoff), and creates physically separate reviewer, engineer or audit packages. The guide advances to reviewing the prepared output. Package integrity is portable; it does not make an older absolute-path frozen benchmark portable or authenticate target execution.

The bundled dbt executor has a narrower full-project contract than many customer repositories. Packages, profile templates, runtime flags, selected/state/deferred builds and history may require separate qualification. Preserve the customer's configuration; do not remove functionality merely to satisfy a limited runner. Coalesce and native warehouse candidates require their own authorized import/compiler/runtime checks. Native execution, business approval and deployment must remain separate, visible states.

## Resume without starting over

For raw tables or CSV snapshots with no former team, SME or Excel baseline, use
the [provisional new-model route](../skills/data-model-accelerator/references/inherited-data-discovery.md).
It supports candidate generation and source-derived structural checks while
keeping unknown business meaning visible. It does not invent legacy parity,
warehouse metadata or business approval.

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py resume \
  --run /absolute/new-engagement
```

Resume refreshes the current source/catalogue context, preserves answers and earlier revisions, and marks dependent records stale after drift. It does not cancel warehouse queries, roll back created tables, or recover a partially deployed platform. Those operations require the selected environment's reviewed runbook.

For registered staged tasks, run `plan-tasks` with the artifact root to see
`reuse`, `regenerate` and `blocked` decisions. Relevant component versions, source
and catalogue slices, material design decisions, parent results and output bytes
control reuse. Legacy engagements require explicit `migrate-stages --run PATH`;
their saved answers are preserved without creating missing approval or execution
records. Asset filters help navigate the design but do not change export scope.

For large projects, work in domain waves with explicit dependency/consumer closure. Increase inventory limits only after reviewing the reported gaps, or provide selected artifacts under `readiness-options`; never treat a truncated inventory as complete. The review tables are searchable and paginated; diagrams preserve the declared model inventory and relationships. Export each coherent domain separately when package limits are reached, preserving cross-domain dependencies and coverage.

## Before customer sign-off

Run a representative project through discovery, a real mismatch, interrupted/resumed work, source drift and reviewer export. Then obtain separately authorized native target and consumer evidence. Local fixtures and a polished page do not establish customer acceptance. The first customer pilot should expose its actual compatibility and validation gaps before a delivery commitment is made.
