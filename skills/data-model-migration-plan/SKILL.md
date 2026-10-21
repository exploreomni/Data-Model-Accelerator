---
name: data-model-migration-plan
description: Turn an existing Data Model Accelerator domain design and historical alignment into an editable migration inventory, migration plan and ticket templates. Use for migration planning and requirements, not live ticket creation or deployment.
---

# Plan the migration

Use the same saved engagement and sibling runtime at
[data-model-accelerator](../data-model-accelerator/SKILL.md). Coordinators follow
[migration-planning.md](../data-model-accelerator/references/migration-planning.md).
Workers receive only the selected domain packet and relevant export guidance;
do not recursively load the full accelerator or rediscover the repository.

Reuse known intake answers. Ask which domain to plan, whether it is new,
refactoring or mixed, preferred local Excel/Word or Google Sheets/Docs formats,
ticket platform and existing company template/backlog. Retain unknown owners,
dates and decisions without inventing them. Generate a draft from the available
design and mappings; missing planning context does not block requested
provisional code. Domain selection and mapping acceptance are not design approval.

Use `migration_project_manager` for a bounded planning task. Reconciliation owns
mapping evidence; the PM explains dependencies and writes testable requirements,
work items, migration waves, cutover/rollback and unresolved questions. Keep
independent validation with the analyst. Project tickets are not accelerator
execution tasks. Preserve splits, merges, shared objects and unmapped consumers.

Register the plan through the guided workflow, then export from its current
public snapshot. Use one source for workbook, document and ticket descriptions.
Record user edits by stable item ID with the current plan hash; never silently
replace human notes during regeneration. Review imported edits before changing
definitions, approval or evidence. Do not repeatedly import ticket files: inspect
existing tickets and the adapter's update limitations first.

For Google selections, use the host's available authorized native Sheets/Docs
connector with the typed export payload, preserve IDs and verify the returned
documents. Do not report pending payloads as created cloud documents. If no
connector is available, explain the gap and offer a local format; changing the
selection requires a user choice. A local file does not satisfy a Google-only
request. The portable runtime itself makes no network calls.

Finalize selected artifacts through the existing delivery finalizer. Include
the Migration plan navigation and requested files. Reviewable templates and
import files are the endpoint: live ticket creation, external sharing, source
retirement and deployment need separate explicit requests.
