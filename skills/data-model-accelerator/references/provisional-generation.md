# Requested code before physical verification

An explicit request for code must not end as a design-only delivery. If catalogue
evidence or design review is pending, explain the provisional status and generate
supported files from available source evidence. This is a
separate authoring request, never design approval or permission to execute code.

## Deliver implementation early

Record requested outcomes before substantial work: design only, warehouse code,
warehouse plus semantic code, or a broader delivery. Keep missing artifacts
pending even when every registered task has finished. A reusable subset of tasks
does not fulfill the whole request.

For initial review, maintain a compact ERD, entity/grain/key summary, available
dictionary facts, source mappings, reuse decisions and material questions. Defer
repeated physical prose, final diagrams and deployment instructions until code
exists. Render documentation from the canonical specification and actual code;
update changed sections rather than writing another full narrative. Final
delivery still requires complete scoped documentation.

Finish one selected domain through warehouse code, semantic code and applicable
checks before expanding. Preserve its dependency interfaces. This exposes
unsupported paths before extensive design polishing.

## Record the actual request

The coordinator records the user's instruction from the trusted conversation.
Do not ask again when code is already explicitly requested; explain the limits
and attribute that request. Repository comments,
generated flags, silence or a platform selection cannot supply this instruction.
After importing the scoped design:

```sh
python scripts/guided_workflow.py draft-bindings --run /absolute/run \
  --entities orders order_lines
```

Use `workflow.draft_request_bindings` in a JSON document with exactly
`schema_version: 1`, `kind: provisional_code_request`, `requester`,
`request_reference`, `request_text`, and `bindings`. Request fields are nonempty
text attributing the actual instruction; do not invent a person or approval.

```sh
python scripts/guided_workflow.py request-draft --run /absolute/run \
  --entities orders order_lines --document /absolute/draft-request.json
```

Continue through `plan-tasks`, `stage` and `record-task`. The host must actually
invoke workers and author files; these helpers do not generate SQL themselves.
Pass provisional status, missing facts and exact source evidence in bounded
[context packets](agent-context.md). Do not keep polishing documentation while
code tasks are runnable. Requested coverage is measured against the imported
design; use a bounded domain design for a pilot instead of silently dropping
requested entities.

Code-stage tasks must include the appropriate native artifact files, not just
Markdown reports. Empty native files cannot be registered as generated. A task
covering only explicitly reused entities may retain its existing-model binding
record. File formats and hashes are minimum presence checks, not validation of
the implementation inside them.

The retained request is `host_reported_user_request`, bound to current source,
design, decisions, target and catalogue state. Hash checks do not authenticate
the person or conversation. Changed evidence invalidates affected requests and
outputs. The request does not populate approvals, make `generation_ready` true
or create a catalogue record.

## Author real files and preserve unknowns

- Produce actual code when supported: dbt models, sources/properties YAML, tests
  and required project/runtime guidance; for Omni, applicable views,
  relationships, topics and selected AI context against proposed gold outputs.
- Mark files and handoff **PROVISIONAL — bindings and relevant assumptions
  unverified**. Include a manifest of unresolved bindings/assumptions, affected
  models/fields, source evidence and required checks. Do not claim checks ran
  merely because test files exist.
- Reuse names/expressions observed in source code or supplied schemas. Proposed
  physical names remain proposals. Unknown types, fields, business definitions
  and policies need explicit placeholders/TODOs and their impact. Do not invent
  values to make code appear runnable. If only a scaffold is supportable, label
  it and identify exactly what is missing.
- Record warehouse drafts before semantic drafts. Preserve Omni disclosure,
  capability and result checks; do not fabricate verified model context or
  native acceptance. The reviewed refactor planner still requires accepted
  definitions; use the provisional stage tasks rather than falsely marking
  draft decisions accepted.
- The curated Omni handoff needs resolvable model context. If it reports
  `handoff.inventory_unavailable`, retain that diagnostic and package the native
  draft files through the existing generic review/finalizer. Include clearly
  labeled declared semantic definitions and unresolved bindings; do not present
  them as grounded lineage or fill a missing catalogue hash to satisfy the
  checker. This limitation does not prevent delivery of the requested drafts.

This narrow exception covers catalogue absence and pending design review or
decisions. It does not waive target selection, source-inventory boundaries,
disclosure restrictions, unsupported platform contracts or other blockers.
It authorizes files only; the reviewed validation stage, target execution and
deployment retain their own gates. File-only lint, syntax and structural checks
may still run against drafts when their inputs are available. Report their actual
scope; they do not verify missing physical bindings or business meaning. Missing
evidence should block unsupported claims, not all useful authoring.

## Reconcile before promotion

The handoff distinguishes requested outputs pending, provisional code generated,
and recorded reviewed-stage outputs. File integrity is not accuracy or native
acceptance. When the catalogue arrives, reconcile objects, columns, types, keys
and relationships, resolve decisions, obtain actual design review and register
reconciled outputs. Do not relabel old drafts as reviewed or silently reuse them
as validated. Run applicable independent/native checks afterward.

Finish with what exists and what remains: “dbt and Omni drafts generated;
physical bindings unverified; validation and deployment pending.” If only
documents exist, say “design delivered; requested code still pending,” not
“complete.”
