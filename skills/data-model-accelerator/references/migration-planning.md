# Optional domain migration planning

This stage turns retained evidence into requirements and migration work. It does
not approve a design, prove parity, execute SQL, create live tickets, retire
sources or authorize deployment. Existing engagements and provisional-code paths
remain unchanged when it is absent. Keep source repositories read-only.

## Intake and scope

Reuse existing answers before asking about selected domain, new/refactor/mixed
mode, expected behavior changes, local Excel/Word versus Google Sheets/Docs (or
both), ticket platform, company template/backlog, priorities, supplied owners and
dates, cutover constraints and acceptance responsibilities. Unknowns remain open
questions. Missing catalogue/history never prevents a requested provisional
plan or code artifact. Do not label a draft as an approved migration.

Use the active domain and its declared shared dependencies. Do not generate all
domains or automatically advance. A portfolio summary may show queued progress;
detailed work for another domain requires its selection. Before design, use the
selected bounded inventory and explicitly show missing target structure.

## Responsibilities and inexpensive context

The coordinator owns scope, evidence retention, user decisions and delivery.
The reconciliation specialist owns historical mapping interpretation. The
`migration_project_manager` converts current scoped evidence into work items,
requirements, dependencies, migration waves and an operational plan. The analyst
owns independent expected outcomes. No role can authenticate its own acceptance.

Build source inventories once; reuse `legacy_alignment`, business rules, model
design, supplied consumer inventories and available migration-validation records.
Name matches are suggestions, not lineage. Retain complete table/column/rule and
consumer denominators, including exclusions, unknowns and unsupported behavior.
Observed lineage, proposed bindings, native observations and acceptance are
different states. A supplied topic identifier is not proof that the topic exists.

Claim the PM role with one domain ID and empty `source_paths`; it consumes saved
records, not a new source scan or implementation `task_id`. Use
`migration_plan_tools.py context` to assemble bounded planning content, then apply
the existing `agent_context.py` disclosure/scanning boundary before dispatch.
Preserve host model defaults. Do not load every vendor playbook or parent chat.
Reuse matching outputs; later passes require changed material or named findings.
An unchanged packet proves input equality only, not execution or correctness.
Register the authored plan before checkpointing PM work as `outputs_recorded`.
Completion checks the original input binding and records the retained plan as an
output separately. A plan does not invalidate its own unchanged work; source,
configuration, model, mapping, human-edit or retained-output drift still does.

## Durable operations

The optional `workflow.migration_planning` sidecar uses version 1. Configure with:

```json
{
  "schema_version": 1,
  "domain_id": "commerce",
  "mode": "refactor",
  "output_format": "local",
  "ticket_platform": "jira",
  "request_reference": "trusted-host://user/planning-choice"
}
```

`output_format` is `local`, `google` or `both`; `ticket_platform` is `jira`,
`linear`, `azure_devops`, `monday`, `asana`, `github` or `generic`. Choose based
on the user's answer, not the example. Use the shared locked workflow:

```sh
python scripts/guided_workflow.py configure-migration-planning --run RUN --document choices.json
python scripts/guided_workflow.py record-migration-plan --run RUN --document plan.json
python scripts/guided_workflow.py edit-migration-items --run RUN --document edits.json
python scripts/migration_plan_tools.py summary --run RUN --output inspection.json
python scripts/migration_plan_tools.py context --run RUN --domain commerce --output packet.json
python scripts/migration_plan_tools.py export --run RUN --domain commerce --output NEW_OUTPUT_DIRECTORY
```

Inspection and export outputs stay outside the source and saved run. Existing
files are not overwritten. The guided page/finalizer also packages current
selected planning outputs automatically under `05_Migration/` when documentation
and dictionary are included. These planning files contain column metadata as
well as narrative, so deselecting either category removes the entire planning
payload and its binaries, with an explicit omission notice. CLI exports are working artifacts; use the finalizer for a complete
handoff. Keep generated technical JSON out of the user's primary local bundle.

Use `register_plan`'s strict schema in `scripts/migration_planning.py`. Stable IDs
join work items, mappings, models, consumers, decisions and waves. Historical
target mappings are derived from the alignment contract, not reauthored in a
parallel mapping graph. Optional upstream lineage retains supplied original IDs
and evidence; absent edges remain unknown. Explicit dashboard/chart records name
legacy tables and proposed target model/topic IDs; missing known consumers stay
visible. Targetless retirement/exclusion remains a proposal unless the original
governance contract records actual human acceptance.

A minimal provisional record (replace IDs with the selected domain) is:

```json
{
  "schema_version": 1,
  "domain_id": "commerce",
  "consumers": [],
  "work_items": [],
  "questions": [{"id": "acceptance-owner", "text": "Who will provide the independent acceptance reference?", "model_ids": [], "consumer_ids": []}],
  "narrative": "Draft migration approach. Consumer destinations and acceptance evidence are not yet supplied."
}
```

Empty arrays preserve unknowns; they do not satisfy a request for a complete
migration plan. Add a work item with stable `id`, `title`, `outcome`, `scope`,
`model_ids`, `mapping_ids`, `consumer_ids`, `dependencies`, and
`acceptance_criteria` (`id`, `expected`, `evidence_ref`, optional `evidence_label`).
Use `null` for an unknown evidence reference. Set `operation` to `create`,
`update` or `review`; updates require the supplied `external_id`. Regeneration
requires `expected_plan_sha256` from the current summary. To retain a human
edit, submit `plan_sha256`, `request_reference` and `edits` containing the item
`id` and changed `owner`, `priority`, `due_date` or `notes` through
`edit-migration-items`. No edit field changes acceptance or approval.

## Requirements and migration sequence

Write tickets around verifiable outcomes. Include the business reason, exact
affected IDs, scope/exclusions, dependencies, acceptance criteria and evidence
needed. Functional behavior includes grain, population, filters, nulls, dates,
currency and security where relevant. Operational requirements include refresh,
history/backfill, performance, access, observability, recovery and ownership.
Record unsupported or missing expectations instead of inventing tolerances.

An acceptance criterion states an observable expected result and the evidence
needed to evaluate it. The engineering author cannot supply the sole oracle.
Keep ticket-specific criteria separate from the team's definition of done.
Difficulty uses Easy, Somewhat easy, Difficult or Very difficult, plus confidence
and rationale; it does not estimate hours, price or completion dates.

Group shared-model work once and link dependent consumers. Plan only applicable
waves: definitions and prerequisites, shared foundations, warehouse models,
semantic objects, dashboard reconnection, independent validation, cutover,
monitoring/handover and reviewed retirement. Record readiness conditions,
rollback triggers and recovery responsibilities in the narrative/requirements.
Unknown windows, owners or sign-off stay unassigned. Never declare deployment
readiness from completed document generation or ticket status.

## Export and human review

The workbook opens with the overview, historical model mapping and consumer
destinations. Supporting sheets retain detailed mappings, work items, questions
and waves. The Word document explains the approach and dependencies, includes
the supplied target ERD, and links the stable planning IDs. Neither changes the
canonical design. Empty evidence must be visibly unknown, not a zero-gap pass.

Google-only exports are typed sheet/document content marked pending host creation.
Use available native tools to create editable documents in the selected folder,
then read back IDs, table ranges, record counts, permissions and representative
content. Keep the host's returned URLs and original planning snapshot together.
Creation does not authorize public sharing. For both formats, preserve the same
snapshot and IDs. When native access is unavailable, ask whether to switch to
local; do not fabricate links or silently claim completion. No automatic cloud
sync is provided. Reconcile subsequent cloud edits by stable ID before regenerating.

Generated evidence columns are separate from editable notes/owner/priority/date.
The `edit-migration-items` operation is an attributed planning edit, not approval.
Use optimistic plan-hash binding. Preserve edits across regeneration and retain
notes on removed IDs as archived. Imported sheet/document changes require host
review. Material source/definition changes stale affected plans; cosmetic planning
edits must not invalidate engineering approval. Old exports remain immutable.

## Ticket adapters and sources

The portable runtime generates templates/import files only. Existing ticket IDs
must be supplied before preparing update proposals. Importing the same file twice
is not universally safe. Keep stable accelerator IDs in descriptions and use an
existing backlog export for deduplication. Preserve dependencies that the selected
importer cannot express in a manual follow-up list. Validate the customer's actual
field names, process and required fields before calling an export import-ready.

Selected guidance, verified 2026-10-21; recheck when changing an adapter:

- [Atlassian acceptance criteria](https://www.atlassian.com/work-management/project-management/acceptance-criteria)
  and [definition of done](https://www.atlassian.com/agile/project-management/definition-of-done/):
  outcome-specific criteria and team quality standards serve different purposes.
- [Jira CSV](https://support.atlassian.com/jira-cloud-administration/docs/import-data-from-a-csv-file/):
  parent rows precede children; IDs and custom fields require explicit mapping.
- [Linear templates](https://linear.app/docs/issue-templates) and
  [CLI importer](https://linear.app/docs/cli-importer): use supported issue fields;
  CLI imports do not reproduce all project/comment structures.
- [Azure Boards CSV](https://learn.microsoft.com/en-us/azure/devops/boards/queries/import-work-items-from-csv?view=azure-devops):
  work item types/fields vary by process; parent-child links are supported, other
  link types need separate treatment. Do not invent assignees, states or dates.
- [Monday Excel imports](https://support.monday.com/hc/en-us/articles/360000219209-Import-files-from-Excel):
  only the first tab imports; subitems become ordinary items. Use a dedicated
  import file, not the full review workbook. Board mappings/duplicate behavior matter.
- [Asana CSV](https://help.asana.com/s/article/preparing-data-for-csv-import?language=en_US):
  imports add tasks, not updates. Do not send update proposals through create CSV.
- [GitHub templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository):
  offer Markdown templates, without silently changing the customer's repository.

No API writes, notifications or live ticket import tests are performed by export.
Those require a later explicit request naming the destination and reviewed scope.
