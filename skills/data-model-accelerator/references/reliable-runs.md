# Reliable runs, bounded dispatch and interrupted delivery

Use the existing guided engagement for every new run. These additions support
the same design, provisional-authoring, native-validation and release contracts;
they do not introduce another approval system or execute host agents.

## Start and resume

`guided_workflow.py start` records the installed runtime content fingerprint,
selected outputs, source snapshot and interview answers. `resume` retains history
and observes runtime changes. Installed copies without Git still have an exact
content identity. Older states remain readable; missing accounting is **untracked**,
not zero work or a passing check. Never identify an installed release from a
directory name alone.

Before qualifying a release in an agent host, compare the actual installed skill
with the reviewed checkout:

```sh
python scripts/check_installation.py --expected-skill /absolute/checkout/skills/data-model-accelerator \
  --installed-skill /absolute/host/skills/data-model-accelerator
```

This read-only check includes specialist instructions, references, parsers and
review assets. Exit 0 means matching content, 1 reports differences, and 2 means
the comparison could not be performed. It never installs or launches anything.
Use the same check for any separately installed stage skill. Runtime observations
made by older releases may cover scripts only; do not equate their identity scope
with the expanded manifest. A passing local suite is not an actual Claude run.

For intake, the saved field is `migration_scope` for both new models and
migrations: `model_only`, `model_semantic`, or `full_dashboard`. `input_handling`
is one of `metadata_only`, `pre_sanitized`, or `protected_environment`; retain
the actual reviewed input boundary rather than choosing a value to clear a gate.
Translate the user's plain-language choices into these fields.

The coordinator uses supplied source adapters and keeps their full result files.
Do not replace them with a convenience regex parser or a truncated spreadsheet.
Use the [lossless source contract](source-adapters.md) to merge extraction work;
its counts describe supplied evidence, not business or SaaS export completeness.
Workers receive the relevant packet, not the full merged inventory.
Register the coordinator's occurrence mappings and existing-model ownership
using [review-evidence.md](review-evidence.md). Keep the full evidence in the
content-addressed engagement files; give specialists exact relevant slices.

## Reserve work before invoking a specialist

After planning stage tasks, or before read-only source discovery, use:

```sh
python scripts/guided_workflow.py claim-work --run /absolute/engagement \
  --document /absolute/work-request.json
```

The host prepares the request; users do not need to author JSON:

```json
{
  "schema_version": 1,
  "work_id": "extract-orders",
  "attempt_id": "extract-orders-1",
  "role": "source_specialist",
  "scope_ids": ["orders"],
  "source_paths": ["models/orders.sql"]
}
```

Use the roles in [agent-context.md](agent-context.md). For registered stage work,
include `task_id` and use its exact `entity_ids` as `scope_ids`; `source_paths`
can then be empty because the existing plan supplies the dependency bindings.
Stage prerequisites and saved output freshness are rechecked. Non-stage work
needs exact source paths; its hashes are checked without executing source code.
Set optional `source_type` (for example `looker`) to bind source work to its parser,
wrappers, references and installed dependency versions. Omission conservatively
binds all supported adapters. Renaming identical work cannot dispatch it twice.

`dispatch` reserves a slot; the host must still prepare the bounded context packet
and actually invoke its worker. `already_active` means use the existing worker.
`reuse` means retain the matching outputs and original assurance, without another
invocation. None proves host isolation, model identity or correct interpretation.
Keep actual host observations with the existing execution receipt.

The default ceiling is two simultaneous specialists across all roles, including
architects and semantic modelers. A small sequential task can use
`execution_mode: "inline"`; that is not independent review. The ceiling is not a
target. To change it, use `configure-work --document PATH` with
`{"schema_version":1,"max_workers":3,"reason":"Three independent bounded scopes"}`.
The limit is 1–8, and reducing it cannot hide active workers. Do not change the
configured model or reasoning effort to reduce spend without an explicit choice
and a controlled accuracy comparison.

## Checkpoint and continue the smallest incomplete task

```sh
python scripts/guided_workflow.py checkpoint-work --run /absolute/engagement \
  --artifact-root /absolute/candidate --document /absolute/checkpoint-request.json
```

The request has `schema_version: 1`, `attempt_id`, `status` (`interrupted` or
`outputs_recorded`), a concise `reason`, and relative `outputs` paths. Interrupted
work can retain zero or more files. Completed work requires actual retained bytes.
Stage work must first pass `record-task` registration for that exact scope; a
checkpoint cannot bypass it. Checkpoint paths stay outside the source and state.

On a host limit or interruption, checkpoint each affected active attempt once.
Do not restart finished domains or fan out a new batch of all workers. Resume
the same `work_id` with a new `attempt_id`; matching files are reused, and a
matching interrupted attempt is linked. Changed inputs or outputs prevent reuse.
The runtime reserves slots only in this engagement; it cannot stop an agent host
that ignores the protocol or measure other sessions' concurrency.

The review page reports attempts, active/interrupted work, reuse and the runtime
fingerprint. Context receipts retain packet size and expansion evidence. Provider
tokens and dollars require attributable host telemetry; missing cost is unknown.

## One model, several projections

Register domain proposals through `guided_workflow.py reconcile-design` using
[review-evidence.md](review-evidence.md). The coordinator invokes reconciliation
and retains its scoped result. Contradictions return findings without replacing
the canonical design. Compatible shared records deduplicate; unknown meanings
remain unknown. Resolve conflicts in new proposals instead of editing only a
conflict document. The standalone consistency helper is not a substitute for
registering the result in the engagement.

Import the canonical design through `import-design`. It records diagnostic
consistency findings. Use `design_consistency.project_review` to derive the review
model/relationship inventory and dictionary rows; supply artifact links, narrative,
source/context bindings and other review fields through the existing portal
contract. Derive ERDs from that same inventory. Optional relationship
`from_columns`/`to_columns` lists allow exact column checks; SQL predicate strings
are not parsed as proof of bindings. Alternate-key uniqueness remains unverified
until supported by evidence.

An imported design may still have unknown types, business definitions or physical
bindings. Keep those visible and use the existing requested provisional route.
Do not claim design completeness from placeholder rows or a coarse requirement
count. A final selected handoff checks that its actual review content agrees with
the canonical design; a matching declared hash alone is insufficient.

## Validate continuously and deliver even when interrupted

`record-task` checks declared YAML/JSON syntax for every stage, including draft
filenames. Implementation and semantic tasks retain their additional automatic
authoring checks. Missing parsers and unsupported constructs remain explicit.
Build authoring contract bindings with `authoring_quality.bindings(state)`;
do not substitute a new hash of the fingerprint object for the required value.
Syntax success never establishes a supported Omni capability or target validity.
Follow the dedicated Omni Modeler's maintained capability guidance and native
validation path; do not substitute AI instructions for required model filters
or access enforcement. Unsupported generation is distinct from a product being
unable to support the feature.

Final selected deliveries still use `finalize_delivery.py`. Interrupted work
uses the same command with `--checkpoint`, even when only a status page exists.
If registering those files in the saved engagement first, use
`guided_workflow.py record-handoff --checkpoint`; missing catalogue or interview
answers do not block checkpoint registration. It keeps the unresolved readiness
state and never labels the engagement `handoff_prepared`. Ordinary prepared
handoff registration keeps its existing prerequisites.
The checkpoint contains the available selected files, README, integrity manifest
and offline `START_HERE.html`, explicitly labeled incomplete. It lists missing
selected categories without changing the original selection. It does not bypass
file hashes, disclosure checks or frozen-output protection. The ordinary finalizer
continues to reject missing selected deliverables. Checkpoints do not become final
just because their ZIP verifies.

Keep artifact presence, structural consistency, source/catalogue binding, native
execution and human review separate. An unknown catalogue must not suppress
explicitly requested provisional code. A design-only selection must not trigger
unrequested code generation. Finish with one entrypoint and the exact next action.
