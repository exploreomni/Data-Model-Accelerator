# Targeted specialist context

The coordinator owns intake, inventory, cross-domain reconciliation and stage
gates. Workers own one bounded question or artifact. Install the complete shared
runtime, but do not load the entire workflow into every worker's context.

## Dispatch once, supply only what the task needs

1. Inventory and extract each source scope once. Prefer deterministic parsers and
   saved structured results over repeatedly asking models to reread the same
   files. Assign shared assets one extraction owner; other tasks consume its
   verified findings and relevant original evidence. The source planner groups
   by project/type; it does not automatically compute semantic dependency slices.
2. Check saved stage tasks before dispatch. Reuse verified results only under the
   existing scope, input, component and output freshness rules. Do not retag an
   old result with a new inventory hash. Reuse the running worker for the same
   task; a slow response is not a reason to launch a duplicate.
3. For a new task, request a fresh worker context without the parent transcript
   when the host supports it. Send a concise coordinator briefing, selected
   evidence and just the required reference sections. Do not send global
   inventory, full working memory, all platform guides or prior tool logs.
   Keep trusted host instructions; do not disable security rules to reduce size.
4. Default to at most two concurrent extraction workers. Do small tasks in the
   coordinator when delegation adds no value; independent acceptance still needs
   a separate reviewer. No nested delegation unless the coordinator explicitly
   assigns a distinct workstream. Preserve the configured model choice.
5. Give each task an artifact contract and stop condition. Return the artifact
   path/hash plus a short handoff with covered IDs, findings, gaps and requested
   context. Persist results once; do not echo large artifacts into chat.

| Worker | Relevant input | Exclude by default |
| --- | --- | --- |
| Source extractor | Assigned assets, native syntax guidance, result contract, necessary dependencies | Target implementation manuals and unrelated source layers |
| Catalogue collector | Selected physical identities and provider metadata contract | BI workbooks and implementation drafts |
| Warehouse architect | Scoped source graph, catalogue slice, reuse evidence, accepted decisions, modeling conventions | Whole repository and full prior drafts |
| Engineer | Reviewed scoped design, exact owned files, upstream interfaces, selected framework contract | Unrelated domains and analyst-owned expected values |
| Semantic / Omni modeler | Reviewed gold bindings, measure/filter/security contracts, relevant capability modules | Raw/staging implementation unless needed to resolve lineage |
| Analyst / independent reviewer | Original relevant expressions and report contracts, independent expectations, candidate diff, affected dependency/documentation slices | Author's conclusions as the sole oracle or all previous conversations |
| Documenter | Current model specification, scoped dictionary/ERD/code associations, unresolved definitions | Repeated source discovery and re-authoring business definitions |

These are routing defaults, not permission to omit required dependencies or
security/history/population context. The coordinator retains a complete coverage
ledger across tasks. Full deterministic coverage and release checks still run.

## Prepare a packet

Use `scripts/agent_context.py` before delegated work. It calls the existing
`prepare_agent_input.py` disclosure/scanning boundary, selects explicit line
ranges from pinned UTF-8 evidence and scans the generated briefing too. Original
files are processed locally and temporary copies removed; only selected text
enters `TASK.md`. It does not infer classification or summarize automatically.
The coordinator writes the summary from verified evidence. This is not a new
business-result schema, privacy boundary, execution runner or approval engine.

```sh
python scripts/agent_context.py --root /absolute/approved-evidence \
  --request /absolute/context-request.json --output /absolute/new-task-packet
```

The request is JSON:

- `schema_version: 1`, `kind: agent_context_request`, unique `task_id`, `mode:
  initial` and a `role` from the table's runtime names: `source_specialist`,
  `catalogue_specialist`, `warehouse_architect`, `analytics_engineer`,
  `semantic_modeler`, `validation_analyst`, `independent_reviewer` or
  `documentation_specialist`.
- For a planned source task with `specialist_profile`, add `source_type` and
  `bindings.specialist_profile` using that plan's profile SHA-256. The builder
  loads only the matching installed profile, verifies the pin, scans it with
  the rest of the packet, and includes its bytes within the same budget. A
  changed profile requires review/rebinding of the affected task, not silent
  reuse. Other source types and legacy requests can continue without this
  optional extension. The receipt records profile metadata, not all profiles.
- Legacy logical role names `semantic_architect`, `independent_qa` and
  `omni_modeler` are accepted aliases for context roles `semantic_modeler`,
  `independent_reviewer` and `semantic_modeler`, respectively. The packet and
  receipt preserve `requested_role` when an alias is used. This does not replace
  the dedicated Omni workflow or establish an actual host invocation.
- `bindings`: named SHA-256 pins for the applicable source, catalogue, design,
  decisions and instruction/component versions. These are supplied associations,
  not authenticated approvals or a replacement for the saved stage checks.
- `brief`: exactly `objective`, `scope_ids`, `summary`, `decisions`, `unknowns`,
  `constraints`, `output_contract`, `stop_conditions`. Objective, summary and
  output contract are text; the rest are arrays of text. Scope, constraints and
  stop conditions are nonempty. State known facts, inferences and accepted
  decisions separately in the summary; cite evidence IDs and human decision
  references. Include exact allowed output paths and applicable stage boundaries.
- `evidence`: 1–32 entries, each with `id`, relative `path`, whole-file `sha256`,
  `classification`, `purpose`, and `ranges` such as `[[12, 36], [80, 96]]`.
  Ranges are inclusive, ordered, disjoint, one-based lines; at most 64 excerpts.
  Preserve complete expressions and their dependencies. For minified JSON or
  structured records, prepare a bounded normalized projection with original
  IDs/pointers and hashes first; do not invent line-based semantic slicing.
- `policy` and whole-packet `classification`: the existing reviewed agent-input
  disclosure contract from [sensitive-data.md](sensitive-data.md). Include the
  summary, evidence, metadata and output path context in disclosure review.
  Do not label private evidence PUBLIC to pass a scan. All selected original
  files must pass their own classifications even when only an excerpt is sent.

Default maximum: **32 KiB for the complete packet**, including evidence and
instructions; the summary itself is capped at **8 KiB**. These are engineering
defaults, not token or billing limits. `max_packet_bytes` may lower the limit or
raise it to 64 KiB with a nonempty `budget_reason`. Overflow is rejected, never
silently truncated. Split coherent tasks or select tighter evidence before
raising a limit. The helper checks integrity, not semantic completeness.

Send `TASK.md` once through the actual host dispatcher. Keep
`CONTEXT_RECEIPT.json` in the private audit with the packet hash, source pins,
selected lines and byte counts. Record that reference beside the actual host
agent/run ID and execution mode. A prepared packet does not prove invocation,
fresh context, host containment, review independence or native validation.
The host may add mandatory instructions, tool definitions and later results;
those are outside this packet's byte limit.

Source capture and semantic extraction are separate. The coordinator verifies
whole-file hashes and runs authorized deterministic native parsers against the
approved staged sources before dispatch. The worker verifies excerpt hashes and
interprets only selected findings; it cannot recompute a whole-file hash from an
excerpt. `file_coverage` reports how many lines are included and whether all text
is present, never whether semantic extraction succeeded. A worker given only one
of two objects must report partial file coverage unless separately verified
complete extraction evidence accounts for the remainder. For Looker, the
coordinator retains and attaches the complete canonical parser contract when
reconciling results; missing parser output remains a gap. File pointers and
parser instructions do not implicitly grant workers access outside the packet.

## Ask for a dependency, not another repository scan

A worker missing evidence returns the exact object/path/locator, its reason and
the blocked finding. The coordinator resolves that request against the catalogue
and shared graph, applies disclosure checks, then supplies only the needed slice.
Record the expansion and new packet hash. An absent field in a packet is not
proof it is absent from the source. Keep unknowns unresolved and continue
unaffected work. Allow reviewers to challenge a summary with original evidence;
do not require them to accept the coordinator's interpretation.

## Bound design and review loops

Default to one design draft, one independent review and one targeted correction
review per scoped design revision. Repair the affected entities in the canonical
design instead of writing a second full design. The correction includes changed
IDs, before/after hashes, impact/dependency closure, relevant source excerpts and
all still-open findings. Do not reopen resolved, unchanged findings for style.
If a substantive issue persists, stop that loop and state the missing evidence
or human decision; continue unrelated work. Material new facts or newly approved
scope may justify another cycle, with an explicit reason and prior findings
retained. Renaming a task or re-spawning a worker does not reset the allowance.

For a follow-up packet use `mode: delta` and `delta` with exactly
`previous_packet_sha256`, `changed_ids`, `open_findings`, `reason`. At least one
changed ID or open finding is required. The helper records these supplied links;
it does not authenticate the previous run, calculate impact closure or approve
reuse. Use the existing saved-task freshness checks for that decision.

Keep extraction's one contract-correction limit and engineering's existing
repair-event limits. Design review is not a replacement for independent analyst
baselines, target-native validation, security tests or complete documentation
coverage. Delta review must include newly affected consumers and dependencies.

## Host and usage boundaries

For Claude Code, use a regular isolated subagent for a new bounded task, not a
conversation-inheriting fork. Avoid preloading the full accelerator and every
stage skill into each worker: Claude Code injects listed skills in full at
startup. Supply the selected instructions in the briefing instead, while
preserving required workspace instructions and tool permissions. Check the
actual installed host's startup configuration before claiming this is effective.
See [Claude Code subagents](https://code.claude.com/docs/en/sub-agents).

Apply the same pattern through the actual available Codex, Gemini, Cortex or
Genie dispatcher. If fresh task context is unavailable, disclose that limit and
use a bounded inline pass when appropriate; it is not independent QA. No
portable helper can force another host's context inheritance or billing behavior.

Track operational evidence: task count, attempts, packet bytes, expansions,
reused results and remaining findings. Provider tokens, cache reads and dollars
belong to the host's telemetry; account-period changes cannot establish one
run's charge. Use [Claude Code cost diagnostics](https://code.claude.com/docs/en/costs)
for host attribution. Do not add guessed cost dashboards or promise a savings
percentage from packet size. Development effort remains a separate model-build
complexity assessment.
