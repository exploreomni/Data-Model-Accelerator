# Development effort after design review

Use `scripts/development_effort.py` after reviewing the entity design and selected
delivery scope. It classifies implementation difficulty from declared factors and
evidence references. It does not predict duration, staffing, price or productivity,
collect provider telemetry, execute a project, or authenticate an approver.

## Categories

| Category | Anchor |
| --- | --- |
| **Easy** | Bounded work using established patterns, clear definitions and dependencies, and understood acceptance criteria. |
| **Somewhat easy** | Several connected changes within supported patterns; limited shared dependencies and coordination; understood validation and recovery. |
| **Difficult** | Material changes to shared models, history, joins, access rules or downstream contracts; substantial reconciliation or regression validation. |
| **Very difficult** | Broad architectural changes, tightly coupled domains, novel implementation paths, or complex migration and recovery requirements. |

Unknown is not Very difficult. Unknown factors or absent supporting evidence
yield `blocked` assessment status, no category, low confidence and
`needs_discovery` readiness. External prerequisites such as waiting for access
instead produce `blocked` readiness while preserving the known category and
confidence. Declare unknown technical behavior as an unknown factor, not merely
as an external blocker. Pending review or declared assumptions yield a provisional category and
medium confidence. Reviewed, fully supported declarations yield `assessed` and
high confidence. Confidence describes the completeness of supplied declarations,
not a statistically calibrated prediction or proof that their contents are true.

Every package and overall result has independent `readiness`: `ready`, `blocked`,
`needs_discovery` or `review_pending`. Review pending does not make a known change
technically harder. A documented assumption can make its assessment provisional
without making execution readiness blocked; record an actual prerequisite in
`blockers` when work cannot proceed.

## Request contract

The standard-library API is `assess_effort(request)`. Pass a JSON-safe object with
exactly these fields:

- `schema_version: 1`, `kind: development_effort_request`.
- `bindings`: `design_revision`, `design_material_sha256`, `scope_sha256`,
  `route_sha256`. Compute `scope_sha256` with this module's `digest(scope)`.
- `review`: `status` (`reviewed` or `pending`) and `reference`. Reviewed requires
  the actual review reference; pending requires null. The orchestrating host must
  establish that the review applies to the current design and selected scope.
- `scope`: `stages` and `excluded_stages`. Partition `implementation`, `semantic`,
  `validation`, `packaging`, `deployment`, `cutover` explicitly. Cutover is a
  subset of deployment effort and requires deployment in scope; it is not a
  separate execution runner. Every included stage needs at least one package.
- `evidence`: distinct `{id, sha256}` records identifying governed, nonsecret
  evidence. A registered hash establishes a binding, not semantic truth.
- `packages`: bounded work packages with distinct stable `id`, included `stage`,
  `depends_on` package IDs, nonempty `material_inputs` mapping stable input IDs
  to SHA-256 values, `factors`, `blockers` and `assumptions`. Optional `model_ids`
  identifies the affected entities. The caller must resolve model IDs against
  the reviewed model inventory. Package dependencies must resolve and be acyclic.

Each package supplies all seven factors: `transformation`, `data_behavior`,
`dependencies`, `platform`, `validation`, `security`, `operations`. Each factor
has exactly `level`, `rationale`, `evidence_ids`. Levels are `easy`,
`somewhat_easy`, `difficult`, `very_difficult`, `unknown`, `not_applicable`.
All evidence IDs must resolve. Explain why a factor is not applicable and cite
its scope evidence; it must not become a shortcut for missing investigation.
Every package needs at least one applicable, assessed factor. Reuse a small,
relevant reviewed contract as evidence for several factors where it genuinely
supports them; do not create artificial evidence records to satisfy the schema.

The helper rejects unsupported fields, invalid IDs, unresolved references,
duplicate IDs, dependency cycles and inconsistent scope. Store sensitive source
content outside this contract; use its governed references instead. No field for
duration, monetary amount or usage instrumentation is accepted.

## Assessment and roll-up

The result includes the original request, its digest, the exact design and route
bindings, per-package category/status/readiness/confidence/reasons, and an overall result.
The original request permits deterministic integrity verification on refresh;
keep this technical record in the governed engagement folder. Show the category,
key drivers, assumptions, blockers, scope and exclusions in the user review.

Package difficulty is the highest applicable factor or prerequisite difficulty.
Readiness blockers and provisional prerequisites propagate. The overall category
is the highest material package difficulty, never an average; unknown complexity
in any package prevents a complete overall category. Known work waiting for an
external prerequisite retains its rating. Package count is shown separately so that
many simple changes cannot conceal their scope behind an Easy label. Assess
integration work explicitly as a package rather than applying an unexplained
numeric uplift. Validation and operational work belong in scope when required.

## Refresh after a design change

`refresh_effort(previous_assessment, current_request)` verifies the prior record
by reproducing its deterministic assessment, validates current bindings, and
returns freshness per package. It performs no execution and no silent reassessment.

- Changed material input hashes, factor declarations, evidence or dependencies
  mark that package and its dependent closure stale.
- Changed scope or deployment route invalidates all affected-run ratings
  conservatively. Changed design material without mapped package impact also
  invalidates the whole assessment rather than guessing what changed.
- An unchanged material design with a cosmetic revision preserves the ratings,
  displays the current binding, and retains their original binding as provenance.
- Current design review pending prevents reuse as a current reviewed assessment.
- Stale and new packages have no current category. Review their factors before
  calling `assess_effort` again; an old factor level is not evidence about new
  grain, history, security behavior or platform constraints.
- Unchanged work retains readiness as well as difficulty. Material staleness
  requires discovery/reassessment; a review-only hold remains `review_pending`
  unless a known external prerequisite also blocks the work.

The host must construct material fingerprints from actual semantics and required
dependencies. Excluding a meaningful change as “cosmetic” would defeat freshness
checks; this helper cannot infer meaning from an opaque hash. Neither an assessed
rating nor a current freshness result grants model, execution or deployment approval.
