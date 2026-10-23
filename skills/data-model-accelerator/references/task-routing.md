# Scoped assignments and consolidated reviews

Use this contract for new tracked specialist work. Keep one selected domain and
the existing stage plan, naming contract, approvals and output folder layout.
It adds local coordination; it does not launch agents, select models, sandbox
workers, measure billing, or change release authority. Focused inline work remains
available. Unknown business/physical context is recorded and requested provisional
code can still be generated.

## Assign and resume

1. Inspect the host's active workers and saved `operations` first. Reuse a relevant
   worker. Default to at most two concurrent specialists, not two per discipline.
   Keep the user's configured model and effort; report capacity limits without
   silently changing either. Do not pass the conversation history to every worker.
2. Prepare the normal claim (`schema_version`, `work_id`, `attempt_id`, `role`,
   `scope_ids`, `source_paths`, optional stage `task_id`). Plan stage work with its
   artifact root first. Call
   `guided_workflow.py work-bindings --run RUN --document CLAIM.json` for current pins.
3. Add `assignment` to the claim. Required fields are below. Keep `task_id` stable
   for the same logical task, change `attempt_id` for an actual restart, and revise
   the assignment only when scope, inputs, outputs or acceptance changes.
4. `claim-work` returns `dispatch`, `already_active`, or `reuse`. Only `dispatch`
   reserves new work. Unknown host liveness does not justify another worker;
   confirm it stopped and `checkpoint-work` as `interrupted` before restarting.
5. Build the normal bounded `agent_context.py` packet with the **same assignment**,
   task ID, role, scope and bindings. Retain its disclosure/byte limits. Pass the
   short objective, relevant source excerpts, original acceptance evidence and
   open questions; request additional paths explicitly instead of scanning all repos.
6. Before invoking the host, call `prepare-dispatch` with `attempt_id`, the claim's
   `fingerprint`, the actual `packet_dir` and receipt `packet_sha256`. It checks
   actual bytes/current pins. A reservation or preflight is not execution.
7. Invoke the bounded worker through the real host, then `record-dispatch` with the
   actual host reference and the same packet fields. Keep unobservable model or
   effort values null. Explicit inline fallback needs its reason. The receipt is
   host-reported evidence, not authentication or proof of isolation.
8. Register stage outputs with existing `record-task`, then checkpoint exact
   assigned paths. Retain incomplete files on interruption. Matching hashes reuse
   outputs; changed evidence invalidates affected work. Unrelated completed tasks
   keep their own pins and reviews.

## Assignment version 1

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `task_id`, `domain_id`, `stage`, `role` | Stable ownership; must agree with the claim and selected domain/stage |
| `scope_ids` | Exact assigned entities/assets |
| `objective` | One bounded result |
| `outputs` | Exact relative candidate file paths; match planned stage outputs |
| `acceptance` | Nonempty, checkable conditions from original requirements |
| `input_bindings` | Exact current `work-bindings` result, also used in the packet |
| `dependencies` | Additional named content hashes; include relevant evidence in packet context and current work bindings |
| `unknowns` | Explicit missing context; empty is permitted |
| `authoring_mode` | `provisional` or `reviewed_candidate`; match the stage plan |

Role aliases for Omni modeling and independent QA normalize to existing DMA roles.
An assignment is a scope agreement, not OS-level write containment. Keep candidate
roots separate from sources and engagement state. Legacy claims and packets keep
their existing behavior; the progress view labels missing assignments as untracked.
Do not silently backfill them or discard previous output/review evidence.
Assignment metadata is capped at 64 KiB in addition to the existing full-packet
limit; split overlarge work instead of dropping scope silently.

## Review only affected work

Call `review-work --run RUN --document REQUEST.json --artifact-root CANDIDATES`.
Every request has `attempt_id` and `action`:

| Action | Additional fields and behavior |
| --- | --- |
| `start` | Optional `changes` and `dependency_state` (`known` or `unknown`); pins actual candidate files and selects applicable review disciplines |
| `record` | `result` with `review_id`, `candidate_sha256`, `verdict`, `findings`, `reviewer_reference`, `execution_mode` |
| `status` | Returns pending disciplines or the consolidated decision |
| `correct` | `correction_attempt_id`; reserves a separate correction attempt after all required reviews arrive |
| `revise` | On that correction attempt, after preflight/actual dispatch and edits; opens a review of the new candidate with the correction builder's identity |

Review verdicts: `pass`, `changes`, `unknown`. Each finding has `id`, `severity`
(`blocking` or `warning`), `message`, nonempty `evidence` and `affected_ids`, and
an actionable `acceptance` condition. Findings are deduplicated without erasing
different acceptance conditions. Original evidence, independent expectations and
affected dependencies must reach QA; a builder summary alone is insufficient.

Change categories cover source/model/grain/keys/naming, SQL/joins/filters/history,
semantic/metrics, access, dashboards/Apps and presentation/documentation. SQL
outputs and design/semantic/frontend stages impose minimum review coverage;
unknown dependencies request more context and cannot count as fully reviewed.
This is a conservative selector from declared changes and output paths, not a
general semantic diff engine. One independent worker may cover multiple relevant
disciplines. A presentation-only packaging edit does not trigger a warehouse rebuild.

Collect every applicable review on the same snapshot **before** one correction.
The default is one consolidated correction and one verification pass. Reserve
the correction before editing, preserve the old attempt, record the actual new
worker, revise the snapshot, then register/checkpoint corrected outputs again.
Further changes require explicit human resolution or a newly scoped follow-up;
never silently reset the allowance. Inline/self-review, unknown dependencies and
stale bytes cannot produce `reviews_complete`. Even that result is only a local
host-reported review record, not native validation, business approval or deployment.

## Progress and compatibility

The existing overview contains **Task progress and next actions**, with domain,
task/stage/role, reserved versus active work, recorded files, open-question count,
review status and next action. It is an offline snapshot refreshed by the normal
render/package flow. It does not invent a live worker heartbeat or costs.

The shared `scripts/task_routing.py` is kept byte-identical in DMA and OAA; update
and validate both copies together. No new provider API or dependency is required.
