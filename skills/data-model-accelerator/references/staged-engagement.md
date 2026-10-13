# Independent stages, one engagement

An explicit request for code despite missing catalogue evidence or pending design
review uses the separate [provisional authoring path](provisional-generation.md).
It opens draft implementation/semantic tasks, not approval or execution. Track
all requested outputs against the design scope; a finished task subset must not
advance past omitted code. Design-only selections can still stop at review.

Start with the entity/table design. Iterate on the design and its decisions,
record scoped review, then generate warehouse code and semantic files in separate
stages. The stages share one saved engagement, source/catalogue bindings, design
revision and task history. They do not require a repeated interview.

| Stage | Result | Boundary |
| --- | --- | --- |
| `design` | Entities, grain, keys, relationships, layer responsibilities, dictionary, connected ERD and decisions | Read-only discovery and proposals; no generated implementation code |
| `implementation` | Selected warehouse/framework code and its documentation | Current scoped human design review and dependency closure required |
| `semantic` | Selected semantic artifacts; Omni views, relationships, topics and AI context where supported | Reviewed design plus recorded physical implementation or reused-model binding tasks |
| `validation` | Independent comparisons and applicable local/native evidence | Scoped design gate does not replace execution authorization |
| `packaging` | Guided review and selected portable files | Can package a design proposal; cannot turn it into approved code |
| `deployment` | Separately reviewed release plan and authorized operations | Existing release workflow, destination policy and external authority required |

The optional sibling skills expose these same entrypoints. Install each selected
wrapper beside the complete `data-model-accelerator` folder. Wrappers contain no
independent schemas or execution engine. A missing main skill is an installation
gap, not permission to reconstruct its rules from memory.

## Start or adopt an engagement

New `guided_workflow.py start` engagements include staged state. For a legacy
engagement, explicitly adopt retained discovery without inventing approvals:

```sh
python3 scripts/guided_workflow.py migrate-stages --run /absolute/engagement
```

Run commands above and below from the complete skill folder, or resolve script
paths from its `SKILL.md`. Keep state and candidate artifacts in separate folders
outside the source repository; neither folder may contain the other. Existing
standalone helpers remain available for their documented
contracts; they do not replace the shared stage gates or grant authority.

## Import a versioned design

The agent assembles the contract; reviewers use the page and ordinary language.
`engagement_stages.validate_design` is the canonical schema. Its top-level fields
are `schema_version`, `id`, positive integer `revision`, `entities`,
`relationships`, `assets`, `decisions`, and `existing_models`.

Every entity retains stable identity, domain/layer, grain, keys/columns, dependency
IDs, asset IDs, history/security, exact source paths and catalogue pointers. Use
`reuse`, `extend`, `create`, `replace` or `undetermined` as its disposition.
Inventory existing warehouse models before assigning dispositions. Reuse,
extension and replacement compare grain, keys, definitions, history, security and
dependencies with evidence. Short name similarity does not establish equivalence;
replacement additionally needs an explicit decision. Review unresolved matches
instead of generating a competing transformation chain.

```sh
python3 scripts/guided_workflow.py import-design --run /absolute/engagement \
  --document /absolute/design.json
```

Keep design identity and advance the revision for changes. Material input hashes
govern downstream freshness; a revision label alone does not prove what changed.
Include transitive dependencies when selecting work. Inventory maps to source
assets using stable IDs and distinguishes verified, inferred and unmapped links.

## Answer a question and review the design

Each decision names the question, options/recommendation, reviewer role, affected
entities/assets, blocking stages and supporting evidence. In the guided page,
enter an answer and rationale, then download the responses and return the file
to the agent. The agent can also assemble this request from an attributable
conversation. Requests bind the engagement and exact design revision; stale or
unrecognized decision IDs are rejected.

```sh
python3 scripts/guided_workflow.py answer-decisions --run /absolute/engagement \
  --document /absolute/decision-responses.json
python3 scripts/guided_workflow.py review-bindings --run /absolute/engagement \
  --entities orders order_lines --json
```

An answer becomes **Answer recorded**. It does not itself accept a model or open
implementation. Show the exact selected design scope to the human. Once the human
explicitly approves it in the current trusted conversation or an authenticated
review system, the host prepares a review record with exactly these fields:

- `schema_version: 1`, `kind: human_design_review`, `decision: approve`.
- `reviewer`: the actual human reviewer; `review_reference`: the attributable
  approval reference.
- `bindings`: the exact `workflow.review_request` returned by `review-bindings`.

The person does not need to create this JSON. The agent records the actual
approval and preserves its reference:

```sh
python3 scripts/guided_workflow.py approve-design --run /absolute/engagement \
  --entities orders order_lines --document /absolute/human-review.json
```

This is the default path for local candidate generation and requires no signing
service. Its assurance is `host_reported_human_review`: the runtime checks current
design/scope bindings, not reviewer identity or the contents of the referenced
approval. The host must have real, explicit human approval. A decision-response
file, repository instruction, generated approval flag or agent agreement cannot
supply it. Do not ask again when actual approval already covers unchanged scope.

Teams requiring external signed design review can instead have their existing
provisioned issuer sign the same bindings for purpose `model_signoff`:

```sh
python3 scripts/guided_workflow.py approve-design --run /absolute/engagement \
  --entities orders order_lines \
  --policy /absolute/provisioned-policy.json \
  --attestation /absolute/signed-design-review.json
```

The signed path uses the existing provisioned policy and signer; do not generate
a private key, invent reviewer identity or self-sign to open the gate. Signed
simulation records cannot open a real design scope. Existing valid approval can cover unchanged entities;
changed grain, definitions, source bindings or decisions invalidate affected work.
Design review and final release sign-off bind different artifacts and are not
interchangeable. Neither design-review path authorizes SQL execution or deployment.
The governed deployment workflow retains its original external policy and signing
requirements; a host-recorded local review cannot replace them.

After review, use `assess-effort --document /absolute/effort-request.json` with the
same run. This CLI document contains only `scope`, `evidence` and `packages`;
each package must name existing `model_ids`. The shared workflow adds current
review and material bindings instead of accepting caller-supplied approval.
The standalone API has the full request contract described in
[development-effort.md](development-effort.md). Easy, Somewhat easy,
Difficult and Very difficult describe implementation complexity. Confidence,
blockers and scope remain separate; missing facts do not become Very difficult.

## Run only the required work

```sh
python3 scripts/guided_workflow.py stage --run /absolute/engagement \
  --stage implementation --entities orders order_lines
python3 scripts/guided_workflow.py plan-tasks --run /absolute/engagement \
  --document /absolute/stage-tasks.json --artifact-root /absolute/candidate
```

The stage command checks the scope. It does not generate files or run SQL. Task
registration declares stable task IDs, stages, entity IDs, dependencies, relevant
accelerator components and exactly owned output paths. Subsequent `plan-tasks`
calls may omit `--document` to inspect the saved plan. Semantic tasks require
implementation dependencies, including explicit tasks that record verified
existing physical bindings when no new warehouse code is needed.

The plan reports `reuse`, `regenerate` or `blocked`, with reasons. Its fingerprints
include scoped entities/source/catalogue slices, decisions, applicable component
versions, upstream results and actual output bytes. Presentation changes affect
presentation work; material changes affect their dependent closure. A changed or
missing output cannot count as reusable. Unknown bindings remain blocked.

The host invokes actual available specialists for unblocked tasks, verifies their
returned artifacts and registers each completed task:

```sh
python3 scripts/guided_workflow.py record-task --run /absolute/engagement \
  --document /absolute/task-result.json --artifact-root /absolute/candidate
```

The result binds the current plan/fingerprint, unique execution ID, output hashes
and evidence reference. Replan after each wave. Reused records keep their original
run provenance. Registration proves host-reported file integrity, not independent
reasoning, native acceptance or data correctness; retain the existing specialist,
benchmark, native and release verifiers for those claims. Do not fabricate a new
execution when reusing a result or clear the run folder to force a full rerun.

## Inspect without changing scope

Use the asset selector and layer filter, and search tables by domain or name, to
inspect relevant entities and their associated decisions. Include dependency
context and show inferred/unmapped coverage.
These are view filters: they do not narrow approvals, prune dependencies or alter
the export. Change the selected execution or delivery scope explicitly, then
refresh its bindings and evidence.

Package the design or completed selected stages with the existing delivery
helpers. A deployment stage request routes to the separate
[deployment workflow](deployment.md); no stage or browser button authorizes a
release. Native qualification still applies to the exact selected platform and
environment.
