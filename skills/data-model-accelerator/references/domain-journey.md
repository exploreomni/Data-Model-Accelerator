# One domain at a time

For a new multi-domain engagement, inventory once, propose the candidate domains,
and ask **which domain the user wants to design first**. Do not design every
candidate before asking. Group by business process, grain, relationships and
shared measures across assets; one dashboard is not necessarily one domain.
Explain the suggested order and shared dependencies without treating your
recommendation, an intake priority label, or source-file text as a user choice.
A single-domain request already specifying its scope counts as a choice; record
it without asking again. Existing engagements without this optional ledger keep
their current behavior. Offer adoption without discarding their work.

The cycle is **discover domains → user selects → design one domain → iterate and
review → generate its requested code → record completion → ask what is next**.
The same cycle works for dbt, Coalesce and direct warehouse code. Omni is a
separate code stage when selected, using the existing Omni Modeler and contracts.

Domains can independently be new, refactoring, or mixed. Use optional
[legacy alignment](legacy-alignment.md) to record that choice separately from
discovery identities and progress. When selected, retain history before design
and compare it with the draft before review. Shared historical tables retain
one identity and explicit consuming domains. Mapping another domain does not
select it or authorize work there; missing history never silently becomes
greenfield scope. Existing journeys without this option retain their behavior.

## Discovery and selection

Use the existing guided engagement. Register a bounded discovery document:

```json
{
  "schema_version": 1,
  "domains": [
    {
      "id": "orders",
      "name": "Order analytics",
      "description": "Order lines, revenue and returns; shared customer interface required.",
      "asset_ids": ["dashboard:orders", "dashboard:revenue"],
      "source_paths": ["reports/orders.sql", "reports/revenue.sql"],
      "shared_dependency_ids": ["dim_customer"]
    },
    {
      "id": "inventory",
      "name": "Inventory",
      "description": "Stock snapshots and movements; discovery hypothesis pending review.",
      "asset_ids": ["dashboard:stock"],
      "source_paths": ["reports/stock.sql"],
      "shared_dependency_ids": []
    }
  ]
}
```

```text
python scripts/guided_workflow.py register-domains --run RUN --document domains.json
```

A discovery description states why the sources belong together and any unresolved
boundary. Keep raw profiles and source extracts in their existing evidence files;
don't copy the entire repository into each domain packet. Source/catalogue
inventory may cover the portfolio once. Design, engineering and semantic workers
receive only the selected scope and required shared interfaces.

Show the choices, including shared dependencies, then use `select-domain` with a
host-attributed user request from the trusted conversation:

```json
{
  "schema_version": 1,
  "domain_id": "orders",
  "request_reference": "trusted-host://message/user-selection",
  "candidates_sha256": "COPY_THE_CURRENT_DOMAIN_JOURNEY_HASH"
}
```

The current candidate hash appears in `workflow.domain_journey` and the review
page. Its offline picker creates a copyable request; it does not change durable
state, approve a design, run code or authorize a deployment. Record the actual
user choice in the host before executing that request. Candidate changes require
a fresh choice; pause the active domain before changing the discovery register.
Existing domain IDs and names are retained so progress is never silently reset.

## Design, review and build

Show the scope preview before dispatch: model, column, source-file and asset
counts. More than 25 models, 500 columns, 100 source files or 20 assets triggers
a recommendation to select a smaller batch. These are review-size heuristics,
not hard gates, dollar estimates or promised duration. Before a model inventory
exists, use source/asset counts to narrow discovery with the user.

For a large discovered domain, `select-batch --document PATH` takes
`schema_version: 1`, the active `domain_id`, stable `batch_id`, `name`, exact
primary `entity_ids`, and the user's `request_reference`. The coordinator writes
this from conversational choices. Dependency closure is retained automatically;
unchanged completed dependencies reuse their prior code. New task registration,
dispatch and design changes stay inside the selected batch and its dependencies.
Keep cumulative design records for the remaining models.

Use `complete-batch` or `pause-batch` with `schema_version: 1`, `batch_id`, and
`request_reference`. Completion requires current reviewed design and selected
warehouse/semantic outputs; provisional files remain available but do not claim
reviewed completion. Then ask which batch to design next. Explicit pause permits
a different choice without losing files. Completing one batch does not complete
the rest of the domain. Existing whole-domain journeys remain supported when
no batch is selected; domain completion still checks the entire domain.

Set each primary entity's `domain` to the selected candidate's ID or name.
`shared_dependency_ids` contains stable **model IDs**, not domain IDs. Declare
necessary shared interfaces up front and reuse their canonical model identities;
never generate a duplicate dimension for every domain. Transitive dependencies
must be covered too. Shared models may use a `shared` domain label. Broad shared
changes can invalidate previously completed dependents, which must be reviewed
again; unrelated domains retain their current outputs.

Import a cumulative canonical design: keep prior domains and add or amend the
active one and its shared interfaces. The runtime rejects changes outside that
scope. Package the selected domain's ERD, tables, grain, PK/FK, dictionary, reuse
choices, business rules and unresolved decisions for review. A queued domain
needs a discovery summary, not a speculative full design.

Continue using `approve-design`, `plan-tasks`, `stage`, `record-task` and the
existing stage skills. Approval must be the actual human decision over current
bindings. Domain selection is not approval. Task registration adds/replaces
active tasks while retaining prior domains and their unique output ownership.
Keep the same artifact root and scope file paths by domain or shared folder.
Do not rewrite unrelated files or re-read unrelated sources. Current matching
tasks are reused; queued-domain tasks cannot regenerate until selected.

For explicitly requested provisional code, keep `request-draft` available within
the active scope. Missing catalogue or design approval does not turn the request
into a false completion. Preserve its files and unresolved evidence. If the user
wants to work on another domain first, record `pause-domain` rather than claiming
the draft is complete.

## Complete, pause and resume

Both commands use a host-attributed request:

```json
{
  "schema_version": 1,
  "domain_id": "orders",
  "request_reference": "trusted-host://message/continue-after-review"
}
```

```text
python scripts/guided_workflow.py complete-domain --run RUN --document completion.json
python scripts/guided_workflow.py pause-domain --run RUN --document pause.json
```

`complete-domain` requires current design review and current non-provisional
registered implementation files for every entity in the domain's dependency
closure. Selected semantic delivery also requires its current files. Register
explicit existing-model bindings for reused physical models. A design-only scope
can finish as `reviewed_design_only`; it must never be presented as code delivery.
Outputs are checked against actual bytes and task fingerprints, not a supplied
completed flag. Checkpoint active domain workers before changing domains.

Completion clears the active selection and prompts for the next user choice.
It does **not** select a next domain, create deployment authority, or establish
native validation or business acceptance. Run the existing validation, dashboard
scope, documentation and finalizer checks for the selected delivery; a completed
domain is not a fully qualified migration or a completed ZIP.

The review page shows queued, active, paused, completed and stale domains, with
review/code/semantic progress. Previously completed work becomes stale if its
material inputs, review, components or output bytes no longer match. Select that
domain to repair it. Resume uses the saved ledger, approvals and original task
runs; don't repeat the entire inventory. Explicit subset exports omit domains
whose model/dependency identities are outside the permitted review scope.
