# Guided engagement lifecycle

Use [`guided_workflow.py`](../scripts/guided_workflow.py) to start once, answer a short round of questions, and resume later with the same discovery record. It inventories the supplied repository without importing, running, or modifying its code. The repository may describe a different platform from the requested target. A dbt source does not select dbt as the target, and GCP does not select BigQuery.

This helper requires Python 3.9+ and a POSIX host with file locking and no-follow filesystem support. It uses the standard library and the sibling [platform readiness collector](platform-adapters.md). It does not contact a warehouse or resolve credentials.

## One local start path

From the accelerator checkout, run:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py start \
  --repo /absolute/path/to/read-only-source \
  --run /absolute/path/to/engagement-run
```

The run folder must be outside the input repository. It starts a saved interview and writes `START_HERE.html` through the offline renderer. `init` is an alias for `start`. Existing source contents remain unchanged. Symlink paths are rejected; use the canonical physical path. For an existing engagement, use `resume` rather than starting over.

The next round contains at most three unanswered questions. Supply only new or corrected answers; existing answers are retained:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py answer \
  --run /absolute/path/to/engagement-run \
  --set engagement_type=migration \
  --set 'priority_domain=Order analytics' \
  --set framework=dbt
```

`--set KEY=VALUE` accepts a JSON value or a plain string. Quote arrays and spaces in the shell. An exported intake answers object can be supplied with `--answers /absolute/path/to/answers.json` instead. These inputs record requests and facts supplied by the operator; they confer no execution, deployment, or business approval.

```json
{
  "engagement_type": "migration",
  "priority_domain": "Order analytics",
  "framework": "dbt",
  "warehouse": "snowflake",
  "semantic_target": "retain_existing",
  "deliverables": ["implementation", "diagrams", "dictionary", "validation"],
  "trusted_outputs": ["Report 42, revision 3; documented order-date filter"],
  "retained_behavior": ["Preserve report population, currency basis, access filters and date rules"],
  "corrected_behavior": [],
  "host": "Local Codex session",
  "environment": "Isolated development workspace",
  "execution_mode": "candidate_only"
}
```

The example is a request shape, not a verified business contract. Replace it with answers actually supplied for the engagement; never use it to fill missing meaning. The host and execution environment are separate from the transformation framework, warehouse, and semantic target.

After supplying a nonsecret physical catalogue, reassess or resume:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py assess \
  --run /absolute/path/to/engagement-run \
  --catalogue /absolute/path/to/physical-catalogue.json

python3 skills/data-model-accelerator/scripts/guided_workflow.py resume \
  --run /absolute/path/to/engagement-run

python3 skills/data-model-accelerator/scripts/guided_workflow.py status \
  --run /absolute/path/to/engagement-run --json
```

`status` checks saved-state integrity and returns the cached state. `status --refresh`, `assess`, and `resume` reread the bounded source inventory, catalogue and registered receipts, then save a new revision. Every command normally refreshes the offline page; `--no-render` skips that presentation step. A renderer failure leaves the committed state intact and reports the problem. The page is a local review surface, not a server and not a warehouse connection.

## Interview contract

| Field | Accepted answer |
| --- | --- |
| `engagement_type` | `migration`, `refactor`, `new_model`, or `blind_test` |
| `priority_domain` | The first business domain, report, or decision |
| `framework` | `dbt`, `coalesce`, or `native_sql` |
| `warehouse` | `snowflake`, `databricks`, `bigquery`, `redshift`, `clickhouse`, or `motherduck`; `gcp` remains an unresolved answer |
| `semantic_target` | A named engine, `retain_existing`, or explicit `none` |
| `deliverables` | Selected IDs: `implementation`, `diagrams`, `documentation`, `dictionary`, `validation`, `sample_data`, `technical_audit` |
| `trusted_outputs` | Migration/refactor: nonsecret versioned report or output references and comparison scope |
| `retained_behavior` | Migration/refactor: behavior that must remain compatible |
| `corrected_behavior` | Migration/refactor: intentional changes; `[]` explicitly means no requested corrections |
| `host`, `environment`, `execution_mode`, `audience` | Optional operator context; never credentials or approvals |

`execution_mode` accepts `assessment_only`, `candidate_only`, `local_validation_requested`, or `target_validation_requested`. Every value is a request, and `readiness.execution_authorized` remains false. A missing mode is represented as `candidate_only` in runtime context; it does not permit execution.

Unknown answers such as `null`, `unknown`, or `tbd` remain in the record and remain unanswered for dependent work. Do not repeatedly ask known questions or seek permission already granted in the conversation. Resolve meaningful ambiguity with the operator. Missing answers never prevent a bounded static assessment. In migration and refactor work, complete the broader [discovery contract](discovery.md), including populations and filters, currency, history, security, consumers and cutover scope, before treating a short answer as a usable business contract.

## Readiness and authority

| State | Meaning |
| --- | --- |
| `interview_pending` | Meaningful discovery answers are missing; static review remains available |
| `needs_evidence` | Coverage, catalogue, or a generation-scoped platform finding needs attention |
| `assessment_ready` | The interview is complete, but the target generation contract is unresolved |
| `candidate_preparation_ready` | Interview, bounded coverage, available catalogue bytes and conditional platform prerequisites permit preparing candidate work |
| `handoff_prepared` | The context-bound review and selected artifact bytes passed handoff integrity checks; review, native validation and approval remain separate |

`readiness.generation_ready` is the bounded prerequisite flag used by the renderer. It requires an available catalogue, complete bounded source coverage, completed required answers, an `agent_assisted` platform capability, and no generation-scoped blocker. Execution-only findings remain visible without preventing candidate preparation. Selecting only documentation does not remove missing facts; the static assessment and its bounded findings can still be reviewed.

A catalogue hash proves captured bytes only. This helper does not run `verify_catalogue`, validate normalized physical bindings, freeze an independent baseline, verify a model, approve a change, or qualify native execution. Those existing gates retain authority. Do not relabel `candidate_preparation_ready` as an approved model or a completed migration. A report that claims “passed” or “approved” stays an unverified receipt here.

Coalesce needs the representative native contract described in [platform adapters](platform-adapters.md). Pass a nonsecret JSON options object with `--readiness-options PATH` on `start`, `answer`, or `assess`; it is retained for resume. Supported options come from the collector: bounded scan limits, `include_paths` for explicitly selected generated evidence, and `coalesce_contract`. A supplied contract only supports conditional agent-assisted preparation; it does not establish native import or execution support. Scan-limit gaps remain visible and cannot be promoted to complete coverage.

## Record a prepared handoff

After building the review manifest and selected files, record them before export:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py record-handoff \
  --run /absolute/path/to/engagement-run \
  --review /absolute/path/to/review.json \
  --artifact-root /absolute/path/to/candidate \
  --audience engineer
```

The helper refreshes inputs, validates the review's context binding, checks the
selected file hashes, dependencies and portable links, then records
`assurance: file_integrity_only`. The next action becomes reviewing the prepared
handoff and outstanding gates. It never trusts claimed test passes or approvals.
Export using the resulting state and the same review, audience and selection;
recording files before the ZIP avoids a circular package checksum. `--include`
accepts selected category IDs; by default it uses recorded deliverable choices.

`resume`, `assess` and `status --refresh` recheck the pinned review and selected
files. Source, catalogue, target, runtime or discovery drift, changed delivery
choices, or changed/missing selected files invalidate the handoff. Unselected
files are outside that handoff's byte checks. A newly recorded handoff supersedes
the previous current one without deleting its history. A generic external JSON
receipt claiming `prepared_handoff` or `passed` cannot advance this state.

## Durable state and drift

The run directory contains `state.json`, immutable numbered `revisions/*.json`, a cooperating-writer lock, and the offline page. State has `schema_version`, `kind`, `engagement_id`, `revision`, timestamps, `answers`, `inputs`, `readiness`, `evidence`, `history`, `status`, `next_actions`, and `state_sha256`. The digest and exact revision match detect accidental alteration; they are not cryptographic authentication of an operator or report.

`inputs` separates these dependencies:

- `source`: canonical repository path and the full bounded source fingerprint object. The same object is exposed as top-level `source_fingerprint` for review binding.
- `catalogue`: path, SHA-256 and availability, or `null`. A previously supplied file that disappears is retained as an unavailable gap.
- `target`: framework, warehouse, semantic target and their canonical digest.
- `runtime`: host, environment, execution request and their canonical digest.
- `discovery`: digest of mode, priority domain, trusted outputs and retained/corrected behavior.

Source fingerprinting is defined by the collector: inspected nonsecret content, relative paths, coverage and scan settings are pinned. It does not prove the contents of excluded paths. Changing credentials excluded by the collector does not expose or hash their values.

Evidence stores only the dependency pins it actually uses. On refresh, changed pins mark the affected current records `stale`, with the time and changed dependency names. Unrelated evidence remains current, and prior records and history remain present. Registered JSON receipts also become stale when their captured bytes change or disappear. `current` means the captured bindings still match; it never means the receipt is verified. Delivery selection affects what is exported, not the complete internal review denominator.

The active state keeps the latest complete assessment at `readiness.platform`. Each new static evidence record stores its `result_sha256`, compact coverage counts and capability statuses, finding counts, and a `result_ref` pointing to `revisions/NNNNNN.json` at JSON pointer `/readiness/platform`. The referenced immutable revision retains the complete assessment for that event. Repeated assessments therefore add compact summaries and history entries to active state rather than additional full inventories. Existing evidence records containing a full `result` remain readable and are preserved unchanged; this update does not silently compact or delete legacy evidence. Immutable revision storage still grows with each saved full snapshot and is not pruned by this helper.

Writes use a same-directory temporary file, `fsync`, an exclusive numbered revision, then atomic replacement of `state.json`. Concurrent cooperating writers fail with a retry message. An interrupted update leaves the previously committed state usable; a durable orphan revision is preserved and never silently adopted over a committed state. If the first start was interrupted after writing its revision, `resume` explicitly recovers that revision and records the recovery. If initial assessment failed before a revision existed, retry `start` in the folder containing only the workflow lock. No recovery deletes source files or prior revisions.

JSON inputs and state are bounded to 16 MiB, reject duplicate keys and nonfinite numbers, and reject symlink paths. Do not put credentials in answers, catalogues, options or receipts. Known credential paths are rejected before reading, and credential-like fields or values are rejected before persistence. This is an input boundary, not a complete secret scanner; source repositories and allowed nonsecret files should already be prepared for review.

## Callable API

Import the module from its scripts directory. All functions below return the full JSON-safe state; they never return a success claim for native execution.

```python
start_engagement(repo, run_dir, answers=None, catalogue=None,
                 engagement_id=None, readiness_options=None)
update_answers(run_dir, answers, *, catalogue=UNSET, readiness_options=None)
assess_engagement(run_dir, *, catalogue=UNSET, readiness_options=None)
load_engagement(run_dir)
status_engagement(run_dir, refresh=False)
resume_engagement(run_dir)
record_evidence(run_dir, path, kind,
                depends_on=('source', 'catalogue', 'target', 'discovery'))
record_handoff(run_dir, review_path, artifact_root, audience=None, include=None)
```

`UNSET` preserves the current catalogue; explicitly passing `None` removes its binding and blocks candidate preparation until a replacement is supplied. `record_evidence` accepts a bounded nonsecret JSON receipt, preserves only its path/hash, uses the declared dependency subset, and sets `assurance: recorded_unverified`. Static assessments use `assurance: static_read_only`. Neither function trusts asserted approvals or invents validation outcomes.

For export freshness, call `assess_engagement` before binding review content to `source_fingerprint` and the canonical hash of `inputs`. An unchanged assessment increments the audit revision but leaves those input pins unchanged. The [delivery renderer](../scripts/delivery_portal.py) handles selected artifacts and package checks separately. APIs do not render automatically; the CLI performs the late renderer call after committing state.
