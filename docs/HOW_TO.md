# How to run a modeling engagement

Use the accelerator with your coding agent to turn source data and reporting logic into a model that an analytics engineer can run and subject-matter experts can review. Start with one business domain, agree on its meaning, build a candidate, and prove the relevant behavior before expanding.

See the [project overview](../README.md) and [capabilities and limits](CAPABILITIES.md) for the current release scope.

You can drive the work through prompts. The agent maintains the technical records and runs the selected helpers; SMEs do not need to edit JSON or learn dbt. The command examples below expose the same local workflow for engineers who want to operate it directly.

## Start reliably and review what is known

Tell the agent which repositories, warehouse catalogue exports and existing-model
inventories you are supplying. It records each input once, retains your naming
and target choices, then asks which domain to design first. Missing inputs stay
visible. A useful request is:

> Use all supplied sources to design this domain. Preserve our configured model
> settings and naming conventions. Show what the existing code declares, what
> the warehouse catalogue confirms, and what you are proposing. Include sources,
> intermediates and consumers in coverage, with a separate independent review.
> Generate provisional code if I request it before every binding is verified.

In the model review, inspect the separate source-coverage, provenance, independent
review and human-review statuses. A structurally clean ERD alone does not establish
accuracy. Source objects, actual model candidates and external interfaces are
counted separately. Reply to outstanding questions in ordinary language; the
agent records your answer against the relevant model without restarting intake.

Engineers can inspect the selected installation with `check_installation.py
--preflight --selected-skill PATH` and discover supported input shapes through
`operator_contracts.py examples`. The [design reliability guide](../skills/data-model-accelerator/references/design-reliability.md)
documents multi-source inventory, canonical design assembly, provenance and review
commands. These shared contracts work across the supported frameworks and warehouses;
they do not substitute for testing in the selected native environment.

## Explain what replaces your historical tables

For each domain, tell the agent whether it is new, refactoring, or mixed. Reuse
known answers. When comparison is useful, supply available final-table schemas,
existing SQL/dbt models, spreadsheet logic or documented rules and say which
behavior should remain versus be corrected. A useful request is:

> Refactor this domain and explain what happens to each of our old final tables.
> Use the supplied schemas and SQL as historical evidence. Show splits, merges,
> moved semantic logic, unmapped columns and differences before we review the
> design. Do not repeat repository discovery. If context is missing, keep it
> visible and generate provisional code when I request it.

The agent retains the baseline before design, then builds an optional comparison
after the draft. You can also add the comparison to an existing engagement without
starting over. **Compare with existing tables** in the guided review shows both
directions, coverage and outstanding decisions. Selected documentation includes
the same comparison in Markdown and CSV. When a PDF migration plan is requested,
include this exported comparison in that document and verify the rendered pages;
the comparison helper does not itself run a PDF renderer.

Give ordinary-language decisions to preserve, correct, reject, defer or exclude
specific mappings. The host records those against the displayed comparison.
Mapping review does not approve the design, validate data or authorize deployment.
Missing history does not block explicitly requested provisional code.

Engineers can use the [versioned comparison contract](../skills/data-model-accelerator/references/legacy-alignment.md)
with `guided_workflow.py configure-legacy-comparison`, `record-legacy-baseline`,
`record-legacy-alignment` and `review-legacy-alignment`. Each accepts the same
`--run` and `--document` pattern as other stage actions. Use
`legacy_alignment_tools.py summary|candidates|context|validation-cases --run RUN
--domain DOMAIN --output NEW_PRIVATE_JSON` for read-only inspection without a
project-wide rescan. `summary` does not require a domain. For `context`, the
default is 32 KiB; a higher limit requires `--budget-reason` and cannot exceed
64 KiB. Pass a prior inspection receipt with `--previous` to identify unchanged
inputs, then verify the saved work receipt before reusing a completed review.
Oversized context fails with a partition instruction. Use repeated `--record
kind:id` selectors for a deliberate slice; omitted records remain counted and
the slice cannot establish full-domain comparison coverage.
Source evidence must still pass the existing agent-input disclosure checks.

Cost control comes from reusing extraction, explicit mappings and unchanged
results, and sending only unresolved scoped differences to a reviewer. The tool
records local evidence and packet sizes; it does not estimate an account bill.

## Migration planning and ticket templates

Ask for the optional planning stage after a draft design or when revisiting a
reviewed domain. For example:

> Plan the migration for this domain using our retained old-to-new mappings.
> Ask which spreadsheet/document formats and ticket tool we want. Include the
> old dashboard connections, proposed new model/topic destinations, unresolved
> definitions, dependencies, measurable acceptance criteria and cutover/rollback.
> Keep this to editable plans and ticket templates; do not create live tickets.

The agent asks about local Excel/Word, Google Sheets/Docs or both; the selected
ticket platform; existing templates/backlog; and missing priorities, owners or
migration constraints. It reuses answers already recorded. A draft remains
available when context is missing, alongside requested provisional code.

Open **Migration plan** in `START_HERE.html`. Download the inventory for old/new
tables and dashboard destinations, then the narrative plan and selected ticket
pack. Select both documentation and dictionary to include the full planning
inventory; reduced exports explicitly omit it. Files are together in `05_Migration/`. Shared models and split/merge mappings
remain explicit. Unknown lineage is not filled by matching names. Proposed routes
do not establish native topic existence or dashboard parity.

Notes, owners, priorities and dates can be returned to the agent by stable
planning ID. The agent records them against the displayed plan hash and preserves
them on regeneration. Changing business meaning requires the normal definition
and design reviews. Workbook edits are not automatic approval or live ticket sync.

Google-only selection produces native-authoring content for the host connector;
it is explicitly pending until the host creates and verifies the real documents.
If the host lacks access, choose an offered local fallback or retain the pending
request. There is no silent format substitution. Review each platform's import
instructions before importing, especially parent/dependency handling and updates.
Existing ticket updates are proposals, not rows in a create-only import.

Engineering commands and the PM task contract are in
[migration-planning.md](../skills/data-model-accelerator/references/migration-planning.md).
Planning exports do not authorize ticket creation, external sharing, deployment
or retirement. Unchanged domains reuse retained work; planning formatting edits
do not invalidate approved engineering code.

For a dashboard migration, supply business definitions up front using conversation
or the [business-rule template](../skills/data-model-accelerator/assets/business-rules-template.md).
A useful request is: “Read our Periscope Git snapshot, show what you could and could
not extract, and compare the selected dashboards together. Reuse existing models
and propose shared aggregates where the grain and business rules match. Retain our
rule decisions, then compare independent source results with the generated warehouse
and Omni results. Keep missing evidence visible and generate provisional code if I
request it.” The [migration review guide](../skills/data-model-accelerator/references/migration-review.md)
explains the saved rule register, extraction, portfolio recommendations and parity
scorecard. Recorded evidence appears in **Migration review** and its accompanying
Markdown report; old engagements need no forced conversion.

For operators constructing records directly: before importing a canonical design,
use `"model_ids": []` in portfolio assets, then bind their actual entity IDs after
design import. A proposed source-to-model mapping uses `mapping_status: inferred`;
`proposed` is not a mapping status. Portal validation rows use `static`, `local`,
`warehouse`, `semantic`, `business`, or `operational` as their scope. Keep those
separate from the engagement's `model_only`, `model_semantic`, or `full_dashboard`
completion scope. The agent should populate these records from existing answers,
without making SMEs learn the schema.

## 1. Make the skill available locally

Use an approved checkout or downloaded copy of this repository. The core discovery, review and packaging helpers need **Python 3.9+ on a POSIX host** and use the standard library. Native dbt adapters, vendor tools and optional validation exercises have separate pinned requirements; install only what the selected path needs, in an isolated environment. Do not upgrade an existing project's runtime just to match an example.

From the accelerator repository root:

```sh
python3 --version
python3 skills/data-model-accelerator/scripts/guided_workflow.py --help
```

Your agent can read `skills/data-model-accelerator/SKILL.md` directly. To install it in a host's skill directory, copy the **entire** `skills/data-model-accelerator` folder, including references and scripts. Preserve an existing installation unless you deliberately choose to update it. Do not install only `SKILL.md`.

Optionally install the sibling `data-model-design`, `data-model-implement`,
`data-model-semantic`, `data-model-validate`, `data-model-package`, `data-model-migration-plan` and
`data-model-deploy` folders beside it. These are focused entrypoints into the same
workflow. They require the main skill and share its answers, review and evidence;
they do not create separate projects or repeat discovery.

The [host setup reference](../skills/data-model-accelerator/references/targets-and-hosts.md#host-packaging) lists the documented locations for Codex, Claude Code, Gemini CLI, Cortex Code/CoCo Desktop and Genie Code. Check the selected host/version's discovery and file-execution support. These packaging paths do not establish that every host has been tested, has a warehouse connection, or supports independent subagents. A chat surface without file execution needs an authorized engineering runner for executable checks. Cortex Agents is a separate, currently unqualified packaging route.

Ask the agent to confirm it can load the skill and its relative references before starting customer work. Installing the skill does not grant access to accounts or authorize deployment.

The coordinator should load the workflow and give workers only a short task
briefing and relevant evidence. Do not configure every worker to preload the
complete accelerator, all stage skills or a growing run transcript. For Claude
Code, use isolated task delegation rather than conversation-inheriting forks,
while retaining required workspace instructions and permissions. The
[context guide](../skills/data-model-accelerator/references/agent-context.md)
explains bounded packets, targeted evidence requests and delta reviews. Update
the host's installed copy deliberately before testing these changes; updating a
Git checkout alone does not update an already installed skill.

### Identify the installed runtime

Run the diagnostic from the **host-selected installed copy** before beginning a
new engagement. It reports that copy's content fingerprint and, when the skill
is tracked in Git, its exact repository revision and local-change status:

```sh
python3 /absolute/installed/data-model-accelerator/scripts/accelerator_runtime.py
```

To compare with a deliberately selected release or reviewed copy, supply its full
commit SHA, content SHA-256, or both. Obtain the content fingerprint by running the
same diagnostic on the reference copy; use its `runtime_sha256` value:

```sh
python3 /absolute/installed/data-model-accelerator/scripts/accelerator_runtime.py \
  --expected-revision FULL_COMMIT_SHA \
  --expected-fingerprint FULL_CONTENT_SHA256
```

The JSON contains no installation paths, remote URLs or source excerpts. The
fingerprint covers `SKILL.md`, scripts, references, agents and assets using the
same manifest as the existing installation checker; generated bytecode and
excluded dependency directories do not change it. Copied installations retain a
useful fingerprint even without Git. A skill copied into an unrelated repository
does not inherit that repository's revision. Sibling skills and host settings are
outside this fingerprint's scope.

Without an explicit expected reference, freshness is **unknown**, even for a
clean checkout. A match means only that the supplied reference matches; it does
not establish the latest upstream release, which copy the host loaded, or native
validation. A matching revision with local changes remains unknown unless an
expected content fingerprint establishes the comparison. Missing or unsafe
content is reported as unavailable without exposing private paths.

A mismatch is advisory and does not block authoring or provisional drafts.
Preserve local changes, deliberately update the host-installed copy, then
restart or reload the host as its installation workflow requires and recheck
before a new run. The helper performs no network requests, installation, pull,
restart, host configuration change or active-run mutation. Its CLI returns zero
for an available diagnostic, including a mismatch, and two for invalid expected
hashes or unavailable content. Use `check_installation.py --preflight` when you
also need the private path-bearing report of explicitly supplied installations.

### Optional full validation environment

For the complete local regression suite, create a separate Python 3.12 environment and install the pinned development requirements. Hex schema validation also needs an explicit publisher download; it is not bundled or downloaded by the parser:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python skills/data-model-accelerator/scripts/bootstrap_hex_schema.py
python -m pip check
python -m unittest discover -s tests -q
```

For an offline setup, replace the bootstrap line with `python skills/data-model-accelerator/scripts/bootstrap_hex_schema.py --source /absolute/downloaded/hex-file-schema.json`. The copy must match the exact checksum in the [Hex source contract](../skills/data-model-accelerator/references/hex-source-contract.md). The schema stays Git-ignored. A changed publisher response is rejected until its new pin is deliberately reviewed. Missing optional dependencies or schema validation are coverage gaps, not successful tests. This setup does not execute a customer project or qualify a live warehouse.

## 2. Start with a prompt and a bounded scope

Replace the paths and choices in this example with your actual selections:

> Read and follow `/absolute/accelerator/skills/data-model-accelerator/SKILL.md` for `/absolute/approved/source`. Start with a read-only assessment of one domain and save the engagement outside that source folder. Target dbt on Snowflake with Omni downstream. Reuse known answers and interview us only about missing context. Inventory existing warehouse models as well as raw sources. First deliver the entity design, connected ERD, dictionary, layer responsibilities, asset mappings and decisions for review. Iterate before generating code. After the selected design is signed off, assess development effort, implement the warehouse code, then generate Omni files and AI context in a separate stage. Identify independent expectations before implementation. Retain one guided page and our progress between stages.

Choose these independently: **source formats, agent host, transformation framework, warehouse, semantic engine, and execution scope**. Detecting a dbt or Looker source does not choose the destination. “GCP” needs a specific service, such as BigQuery. Omni is optional. Use the [platform matrix](PLATFORM_MATRIX.md) to distinguish candidate authoring from qualified native execution; Coalesce requires a representative versioned native project contract.

For dbt, also choose whether to retain the existing distribution/version or
evaluate an upgrade. The [runtime guide](../skills/data-model-accelerator/references/dbt-runtime.md)
explains Core, full dbt v2 and dbt OSS. A useful instruction is: “Assess this
project for dbt 2.0.8; keep the source unchanged, prepare only the selected
features, and distinguish requested strict analysis from what actually ran.”
The agent records `dbt_runtime` in the existing answers and reuses that contract.
Runtime/setup appears under **Code & files** and **Validation**, and in the ZIP
README. Missing runtime evidence does not stop design or requested draft code.

Also select the completion scope: `model_only` for the warehouse model,
`model_semantic` for the model and Omni semantic layer, or `full_dashboard` for
dashboard migration as well. Reuse a choice already supplied. If you choose a
full dashboard migration, topic files alone cannot complete it: tile, filter,
listener, layout, interaction and access evidence remain in scope.

To receive code before a catalogue or final design review is available, say:

> Generate the requested dbt and Omni files from the evidence available now. Label unresolved physical bindings and business definitions as provisional, list what must be reconciled, and do not execute or deploy them. Keep code that is still missing visible in the progress report.

The agent records that instruction; you do not need to prepare an approval file.
It should generate supported code or clearly identified scaffolds where necessary,
not substitute another design document. File-only lint and structural checks can
still run when their inputs are available; they do not prove warehouse accuracy.
See [provisional generation](../skills/data-model-accelerator/references/provisional-generation.md).
Keep the initial design review concise, then develop code and its documentation
together for one domain before expanding. Full documentation remains part of the
final selected delivery.

Before giving source content to any agent, establish the classification and
approved input boundary with the [sensitive-data guide](../skills/data-model-accelerator/references/sensitive-data.md).
Unknown fields require review; labels such as PII or PHI do not themselves mask
values. The portable staging route supports reviewed, pre-sanitized inputs and
does not establish protected-data isolation on every coding-agent host.

Use an absolute canonical source path and a separate new run folder. The source can be an existing repository or a narrowly scoped folder of raw CSV extracts. Do not point at a home directory or an account's entire export. Keep profiles, credentials and private keys outside the inspected scope. The collector reports excluded, unreadable, oversized and unsupported inputs; an incomplete inventory remains incomplete.

The agent starts the saved workflow from the accelerator root:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py start \
  --repo /absolute/approved/source \
  --run /absolute/engagement-run
```

Open the resulting `START_HERE.html`. The helper reads source files without running or changing their code. It writes `state.json`, retained revisions and an offline guide. It does not generate the complete model on its own; the host agent performs the modeling work through the skill.

The page visibly labels the delivery as a candidate. Under **Check the evidence**,
review the selected scope and each required lane's next action. Local lint,
native model validation, dashboard readback, query parity, access checks, AI
answers and business acceptance answer different questions. An imported pass or
an attractive ERD cannot supply a missing check.

## Include metadata in the delivery

During discovery, select descriptions only, descriptions plus supported governed tags, or documentation only. Confirm metadata ownership, environments, exact RAW source scope, taxonomy and preservation of existing descriptions. Existing names remain the default. Reuse saved answers; a migration interview must still establish behavior and independent benchmarks before generating dependent changes.

Use the [metadata operator guide](../skills/data-model-accelerator/references/warehouse-metadata.md) to produce the v2 dictionary, preview dbt documentation, bind physical objects, and package the metadata plan. In `START_HERE.html`, open **Metadata** to review coverage, existing/proposed descriptions, exclusions, blockers and run order. Both the full engineer package and reduced exports preserve the evidence status. A reduced package cannot turn omitted evidence into a pass.

For deployment, freeze the dictionary and expected configuration with the build artifacts; prepare native metadata changes against a fresh post-build observation. The generated SQL can be handed to an authorized operator/CI process. Automatic live metadata writes are currently blocked until native drift collection is integrated. Verify the resulting warehouse state and separately validate Omni/AI ingestion before accepting the engagement.

## 3. Answer once, then work with the SMEs

The first short interview establishes the engagement type, priority domain, framework, warehouse, semantic target and desired deliverables. Existing selections should be prefilled. Migration and refactor work additionally need trusted output references, behavior to preserve and intentional corrections. The [discovery guide](../skills/data-model-accelerator/references/discovery.md) describes the deeper questions.

| Engagement | Establish before claiming success |
| --- | --- |
| Migration | Versioned source reports and definitions, comparison populations/settings, consumers and behavior that must survive the move |
| Refactor | Existing project contracts and dependencies, independent before/after expectations, intentional changes and release conventions |
| New model from raw data | Profiled grains and relationships, proposed business definitions, source dispositions and evidence for every physical input |
| Blind test | Explicit allowed inputs and separation from existing solutions and independent expected results |

Bring the engineer and SMEs together around concrete examples: one order, one cancellation, one discount, one missing customer and one period boundary. Ask which date, status population, currency, rounding, tenant and access rules apply. Confirm whether apparently similar measures are intentionally different. Preserve the source behavior alongside any proposed correction.

The agent records each consequential decision against the model version:

| Decision record | What to retain |
| --- | --- |
| Question and evidence | The source/report example and ambiguity being resolved |
| Proposed rule | Grain, population, formula, null behavior, time/currency/security implications and affected consumers |
| Actual SME decision | The named decision-maker, attributable decision reference, date and accepted/rejected/deferred status |
| Version and proof | Affected model/rule version, required tests and evidence invalidated by the change |

This is a business review loop, not a vote among agents. The guided page shows
the question, reviewer role, affected entities/assets and stages waiting on the
answer. Enter an answer and rationale, save the response request, and return it
to the agent. It applies the file using `answer-decisions --document PATH` with
the existing run. Stale design revisions and unknown decision IDs are rejected.
**Answer recorded** means the response was retained; scoped design approval is a
separate transition. Ordinary intake fields and model decisions use separate
contracts, so do not add arbitrary decision IDs to `answer --set`.

New answers can be applied without re-entering previous choices:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py answer \
  --run /absolute/engagement-run \
  --set framework=dbt \
  --set warehouse=snowflake \
  --set semantic_target=omni
```

The agent can also apply an answers file exported from the offline page with `--answers /absolute/answers.json`. Saving answers in the browser downloads a request; the agent applies it. The page does not contact an account or grant approval.

If an answer is genuinely unavailable, record it as unknown and identify the affected work. Raw-only modeling can produce a provisional structural candidate when requested; it cannot recreate an absent Excel baseline, currency policy or historical record. When SMEs later supply the missing facts, revise the same engagement and rerun the affected checks. See the [raw-only route](../skills/data-model-accelerator/references/inherited-data-discovery.md).

## 4. Ground the proposal in sources and the warehouse catalogue

Have the agent inventory the approved source scope, retain hashes/native IDs and resolve upstream and downstream dependencies. For a large repository, choose a domain wave with its complete dependency and consumer boundary. Preserve working models, packages, hooks, materializations and CI instead of replacing the project wholesale.

For supported source formats, ask the coordinator to use the [source adapters](../skills/data-model-accelerator/references/source-adapters.md) before interpretation. The coordinator parses the approved snapshot once, keeps the complete evidence locally, and gives each source specialist only its assigned findings. The output includes unchanged expressions, native IDs, dependency candidates and explicit coverage gaps. It does not execute the source or connect to vendor accounts.

Each planned source task now names one version-pinned [specialist profile](../skills/data-model-accelerator/references/source-specialists.md). Give the worker that profile, the relevant parser findings, original expressions and necessary catalogue/dependency slices. The coordinator uses the plan's `source_type` and `specialist_profile.sha256` as `source_type` and `bindings.specialist_profile` in the context request. `agent_context.py` embeds that one profile and counts it within the existing 32 KiB default budget. Do not ask all 17 workers to scan the repo; dispatch only detected, necessary sources and reuse unchanged evidence. Missing context returns a specific request, not another full discovery pass.

For example, with an operator-supplied BigQuery export in a private folder:

```sh
python skills/data-model-accelerator/scripts/run_source_adapter.py --source bigquery --capabilities
python skills/data-model-accelerator/scripts/run_source_adapter.py /absolute/approved-snapshot \
  --source bigquery --output /absolute/existing-private-folder/bigquery-evidence.json
```

The output must be a new file outside the source folder. Exit `2` means the report was written with partial coverage or omissions; open its gaps rather than treating it as a failed run or complete support. For a planned specialist handoff use `plan_specialists.py --require-source-adapters`, then `extract_specialist_task.py` for each supported task and `verify_specialist_results.py` after reconciliation. Use `--source-profile periscope:.` (or the selected source and relative project root) when origin cannot be inferred safely. Parsing, target code generation, linting, and native execution are separate capabilities; consult the [source matrix](CAPABILITIES.md#source-formats) before choosing an export.

Supply a scoped, dated raw-layer catalogue through authorized read-only access or a nonsecret operator export. Include the actual namespace, visible tables/columns/types, collection identity and visibility gaps. The agent normalizes and verifies the catalogue, binds proposed inputs to it, and separately profiles keys, nulls, duplicates, join cardinality and unmatched rows.

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py assess \
  --run /absolute/engagement-run \
  --catalogue /absolute/reviewed-catalogue.json
```

Registering catalogue bytes in the workflow is not catalogue validation. The [catalogue contract](../skills/data-model-accelerator/references/raw-catalogue.md) and [provider templates](../skills/data-model-accelerator/references/catalogue-providers.md) supply the separate checks. A CSV header is lexical metadata, not a verified Snowflake type or permission. A simulated raw table must stay labeled as a simulation. Existing ingestion remains in place unless a separately scoped change is requested.

Review a proposal before implementation: entity grains and keys; source-to-target mappings; Bronze/Silver/Gold responsibilities; warehouse versus semantic rules; history and deletion behavior; privacy publication boundaries; and unresolved decisions. A layer name does not require an extra physical copy of every table. Keep header and line measures separate, role-specific joins distinct, and interactive ratios or distinct counts at their intended query grain.

Include already migrated or governed warehouse models in that review. Compare
grain, keys, definitions, history, security and dependencies with evidence, then
choose reuse, extension, creation, replacement or undetermined for each entity.
Replacement needs an explicit decision. A matching table name alone is not proof
that an existing model implements the required meaning.

The agent imports the versioned design and shows the exact selected scope. When
you explicitly approve that scope in the trusted conversation or an authenticated
review system, the host records it through `approve-design --document PATH`.
This opens local candidate generation without requiring a signing service. The
record binds the design and scope and identifies the real reviewer/reference;
the runtime checks those bindings but does not authenticate the person's identity
or read the referenced approval. The host must retain the actual human approval,
never infer it from an answer file, source content, generated flag or agreeing
agents. Existing valid approval is reused rather than requested again.

Teams requiring external signed design review can use the optional policy and
attestation route. Warehouse execution and deployment remain separately authorized;
the release coordinator retains its original external signers and policy. See the
[stage guide](../skills/data-model-accelerator/references/staged-engagement.md)
for commands and the explicit legacy `migrate-stages` path.

After review, the agent shows development effort as **Easy**, **Somewhat easy**,
**Difficult** or **Very difficult** per work package and for the selected scope.
It explains the drivers and reports confidence, assumptions and blockers
separately. Unknown grain or missing evidence blocks classification rather than
inflating difficulty. These categories describe complexity, not hours or price.

## 5. Build a candidate and validate it independently

Existing authorization remains valid for the same action and environment. The agent should complete already-authorized work without repeated permission requests; a new target or expanded action needs its own scope. Recording a requested execution mode in intake is not itself authorization.

After the selected design has current scoped review and the execution scope is clear, ask:

> Implement the reviewed candidate in the agreed isolated output or development checkout. Preserve source identifiers and current project conventions. Have an independent analyst freeze expectations from the approved sources and definitions before inspecting candidate results. Run only the local or development checks already authorized. Report complete coverage, discrepancies and remaining target checks; do not change expected results to make the candidate pass.

For an existing dbt project, expect a focused patch and integration instructions. For a new project, expect models, sources, macros/configuration, tests, a nonsecret profile example and ordered setup commands. Run dbt SQL through dbt; do not paste unresolved `ref()`, `source()` or Jinja into a warehouse editor.

The host checks the implementation stage, inspects the saved task plan, and
invokes specialists only for unblocked tasks needing work. Matching source and
catalogue slices, reviewed decisions, relevant accelerator versions and output
bytes permit reuse. The plan explains why a task must regenerate; dependents wait
for their prerequisites. It does not execute code by itself. Registered results
retain their actual run references, while separate verifiers establish the
applicable validation claims.

Validation should establish more than a matching grand total:

- Grain, key populations, duplicates, orphans and join fanout; header/line measures at the correct grain.
- Row values and relevant dimensional slices, filters, null/empty behavior, decimal precision and date boundaries.
- Every generated typed projection, including lazy views; history, correction, deletion and replay behavior where applicable.
- Effective access boundaries and deliberately introduced defects that the relevant assertion detects.

Freeze the input, model and environment versions with the evidence. Preserve failed attempts and explain repairs. If an SME intentionally changes a definition, version the definition and independent expectations; do not silently overwrite the old comparison. The [dbt qualification guide](../skills/data-model-accelerator/references/dbt-qualification.md) defines the full-build artifact association. Some real projects exceed the bundled executor's scope and need their existing qualified CI/operator path.

For Looker-to-Omni work, use the [Omni delivery sequence](../skills/data-model-accelerator/references/omni-delivery.md).
Reconcile the source export denominator before generating a reviewed dashboard
mapping. Retain manual steps for unsupported features. Native validation and
draft readback require the exact approved destination; dashboard behavior still
needs separate tests. The implemented writer attaches a draft to an existing
document and does not publish or replace the current published dashboard.

Build AI context only from reviewed definitions with exact gold-column mappings.
The [Omni Modeler](OMNI_MODELER.md) also supports reviewed derivations through
inherited views, topic aliases and bounded query views. It follows filters,
grouping and join dependencies back to actual approved gold inputs; it does not
invent a physical table for a saved query view. Topic field selection and AI
awareness are checked separately from effective access.
Leave ambiguous meanings as questions. Use the [AI context builder and evaluation
contract](../skills/data-model-accelerator/references/omni-ai-context.md) to freeze
persona questions, allowed fields, definitions, clarification and refusal cases.
Imported structured answers are useful comparisons; they do not prove that a
live AI answered correctly. Use the [access contract](../skills/data-model-accelerator/references/access-enforcement.md)
for native state and allowed/denied persona evidence; documentation and tags
alone do not enforce security.

When downloading fewer categories from the browser, the new ZIP verifies the
selected embedded file hashes. It is a new candidate with a newly rendered HTML
page, and its manifest states that no new content scan or disclosure review ran
in the browser. Return that exact ZIP to the agent for scanning and destination
review before sharing or deployment. File-integrity verification alone does not
clear it for release. Follow the [release evidence contract](../skills/data-model-accelerator/references/delivery-release.md)
for version-bound acceptance and separate destination authorization.

Keep four lanes visible: code conventions, project validity, native warehouse validation and data accuracy. [Static lint](LINTING.md) can expose syntax/style problems; it cannot establish native behavior. Local DuckDB success is local evidence. Offline adapter compilation is not a Snowflake account build. Neither proves SME acceptance.

## 6. Review Omni and AI context with the model

When Omni is selected, have the semantic architect use the same versioned Gold contract as the warehouse model. The package should contain native `.view`, `.topic`, `model` and `relationships` files where applicable, plus setup instructions and explicit physical namespace mappings. Keep support scripts and contract JSON distinct from native Omni files.

Invoke the semantic stage separately. Its task dependencies bind the physical
implementation or explicitly verified reused warehouse relations. Semantic-only
work can reuse existing models without generating a redundant warehouse layer.
Changing the reviewed grain or meaning invalidates affected downstream tasks and
their effort assessment; a cosmetic label change preserves material work where
its bindings remain unchanged.

Review topic grains, measures, role-specific joins, defaults and field publication. Verify that moving logic upstream does not apply it twice downstream. Resolve environment placeholders before native import. Optional dbt metadata integration is a separate setup task; generated YAML does not establish a live integration.

Supply portable AI context and documented native `ai_context` fields describing accepted definitions, time anchors, unknowns, safe source-bound questions and unsupported interpretations. SMEs should review the language an analyst or agent will use. AI guidance, hidden fields and topic curation do not enforce permissions. Native Omni import/query checks and allowed/denied persona tests remain necessary in the authorized tenant. See [semantic placement](../skills/data-model-accelerator/references/semantic-placement.md) and the generated package's setup guide.

## 7. Open, select and iterate on the guided ZIP

Ask for the package you will actually use:

> Prepare an engineering handoff with the current model, connected diagrams, complete dictionary, layer documentation, runnable implementation and concise validation results. Include prerequisites and exact commands for the extracted folder. Exclude source rows unless explicitly selected and approved. Keep the full technical audit separate. Record the prepared handoff and verify the ZIP before delivery.

An engineering ZIP contains `START_HERE.html`, selected files and `DELIVERY_MANIFEST.json`. In the simple layout, **Data model** starts with one gold output's upstream pipeline. Read raw/source → staging → intermediate → gold, then click a table for its columns, keys, joins and linked code. Supplemental views retain inputs outside those pipelines. **Detailed joins & relationships** opens the full ERD; joins are separate from transformation dependencies. Semantic views/topics require explicit physical model bindings, never name matching.

**Code & files** contains the selected implementation, and **Validation** retains reported results and gaps. Missing table-to-code mappings stay explicit. Reviewer packages exclude implementation, samples and audit; audit uses a separate export. Smaller exports retain required dependencies and do not reduce internal model, dictionary or validation obligations.

The agent prepares the review manifest and exact file hashes, then uses:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py record-handoff \
  --run /absolute/engagement-run \
  --review /absolute/review.json \
  --artifact-root /absolute/candidate-artifacts \
  --audience engineer

python3 skills/data-model-accelerator/scripts/finalize_delivery.py \
  --state /absolute/engagement-run/state.json \
  --review /absolute/review.json \
  --artifacts /absolute/candidate-artifacts \
  --audience engineer \
  --output /absolute/engineering-delivery-v1 --javascript
```

These commands need the actual prepared review/artifacts; they do not manufacture them. Export must use the same audience and selections as the recorded handoff. The [review-surface reference](../skills/data-model-accelerator/references/review-surface.md) explains category selection and exported paths. Integrity verification proves the packaged bytes and links, not the reported business or execution results.

The finalizer creates `engineering-delivery-v1/handoff.zip` and the matching
`engineering-delivery-v1/handoff/` folder. Open `handoff/START_HERE.html`.
The default `--layout simple` has five sections: `01_Input_Sources/`,
`02_Input_Context_Files/`, **`03_Design_Documents/`**, `04_Code_Generation/` and
`05_Mappings/`. Design contains the narrative, pipeline SVGs and dictionary;
code contains implementation, setup and validation; mappings contains selected
comparisons and migration documents. Original inputs stay at their registered
roots and are not cloned. With documentation selected, each section's guide states
what is included or missing. Use `--layout classic` for the older `01_Model/`,
`02_Implementation/` and `03_Validation/` paths. The command fails if a selected category has no files or
the required design/navigation is missing, and never overwrites an older export.
`--javascript` needs Node for syntax checks; browser review remains separate.
Prepared files or successful specialist tasks alone are not a finished handoff.

Return review comments to the same task: identify the rule/model, the reason and the SME's decision. Ask the agent to revise code, model, ERD, dictionary and context together, retain the previous version, rerun affected checks, and issue a new package.

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py resume \
  --run /absolute/engagement-run

python3 skills/data-model-accelerator/scripts/guided_workflow.py status \
  --run /absolute/engagement-run --json
```

`resume` refreshes source/catalogue context and invalidates dependent evidence after drift. `status` reads cached state; add `--refresh` to reassess. Do not edit saved state or replace stale evidence with a new timestamp. A prepared handoff means selected files passed integrity checks, not that the model is approved or deployed.

Use the asset selector and layer filter, or search for a domain/table name, to
find the entities and decisions relevant to a report or dashboard. Inferred and
unmapped links stay visible. Filters are for
inspection: they neither change the approved execution scope nor remove files
from an export. Select a new scope explicitly and refresh its bindings when you
intend to change the work.

## 8. Choose publication or deployment after review

A usable handoff can stop at review. If you want a PR or development deployment, specify the repository/branch or exact environment and the intended action. The agent should first prepare the concrete diff, affected objects, current evidence, unresolved decisions and recovery plan. Approval must refer to those versions. Publication, merge, development execution and production promotion are different actions.

The optional [deployment coordinator](DEPLOYMENT.md) requires an externally provisioned runner, explicit destinations, protected credentials and trusted signing keys. Its automated path requires externally authenticated model sign-off and deployment approval; independent native preflight and a separate acceptance issuer remain necessary. The toolkit does not supply production keys, authenticate an SME by a typed name, or turn a browser button into authorization.

Follow the [deployment runbook](../skills/data-model-accelerator/references/deployment.md) for exact plan, approval-request, submit, status and acceptance contracts. Native completion first reaches `verification_pending`; only accepted live evidence reaches `deployed_verified`. Simulation stays `simulation_verified`. Without the runner and issuer integrations, deliver the reviewed plan to the organization's existing authorized release process; do not fabricate signatures or claim automated deployment readiness.

The coordinator's PR route checks an existing remote commit and creates a draft PR; it does not create/push a branch or merge it. Its native adapters have local contract tests, not universal live-provider qualification. If submission times out or returns an unknown outcome, inspect the recorded operation and native identifiers before any retry. Cancellation is not rollback; use the separately reviewed recovery procedure.

## Try the saved workflow without customer data

This optional smoke test creates a tiny **synthetic** source and a fresh run under the system temporary directory. Run it from the accelerator repository root. It needs no warehouse, credentials or external packages and does not execute the CSV content:

```sh
DMA_DEMO="$(python3 -c 'import pathlib,tempfile; print(pathlib.Path(tempfile.mkdtemp(prefix="dma-how-to-")).resolve())')"
mkdir -p "$DMA_DEMO/source"
cat > "$DMA_DEMO/source/orders.csv" <<'CSV'
order_id,amount
A1,10.00
A2,20.00
CSV

python3 skills/data-model-accelerator/scripts/guided_workflow.py start \
  --repo "$DMA_DEMO/source" --run "$DMA_DEMO/run" \
  --set engagement_type=new_model \
  --set 'priority_domain=Synthetic order discovery' \
  --set framework=dbt --set warehouse=snowflake \
  --set semantic_target=omni \
  --set 'deliverables=["implementation","documentation","diagrams","dictionary","validation"]' \
  --set execution_mode=assessment_only

python3 skills/data-model-accelerator/scripts/guided_workflow.py answer \
  --run "$DMA_DEMO/run" --set 'priority_domain=Synthetic order discovery, SME review pending'

python3 skills/data-model-accelerator/scripts/guided_workflow.py resume \
  --run "$DMA_DEMO/run"

python3 skills/data-model-accelerator/scripts/guided_workflow.py status \
  --run "$DMA_DEMO/run" --json
```

Open the `START_HERE.html` in the printed run folder. Expect missing-catalogue evidence to remain visible: this tests saved discovery and answer retention, not model generation or native validation. The files remain available for inspection.

## Troubleshooting

| Symptom | Next useful action |
| --- | --- |
| Skill or reference file is missing | Install the whole skill folder and check the selected host's discovery path. |
| Run path is rejected | Use canonical physical paths; place the run outside the source and avoid symlinked ancestors. |
| State says `interview_pending` or `needs_evidence` | Read the specific missing questions/coverage; supply facts or retain the unknown. Do not relabel the state as complete. |
| Answer is saved but code remains blocked | Apply the response, resolve scoped blockers, and have the host record actual explicit human approval of the displayed scope. No signing service is needed for local candidate generation; an answer file is not approval. |
| A previous engagement lacks stage controls | Run `migrate-stages` explicitly; retain its answers and history. Earlier files do not reconstruct missing approvals. |
| A task says `blocked` or `regenerate` | Inspect its reason and dependency plan; complete or re-review affected work. Do not discard the run to force a fresh start. |
| SME changed a rule or source files changed | Resume, version the decision, update affected model/docs, and rerun dependent evidence. |
| Source scan is partial or the project is too large | Scope a coherent domain or explicitly review scan limits; preserve unexamined dependencies and consumers. |
| The bounded dbt runner rejects packages, hooks or stateful behavior | Preserve the project and use a qualified existing CI/operator route; do not delete functionality to obtain a pass. |
| ZIP export reports a missing link or dependency | Correct paths for the exported numbered folders and register the required files before recording/exporting again. |
| An extracted command cannot find a script or dependency | Use the package's runbook from its stated directory; include the missing helper or document its external prerequisite, then reissue the package. |
| SQLFluff reports source/framework conventions | Correct authored issues first; use only the documented reviewed exception contract and retain raw findings. Never rename source keys or suppress errors merely to obtain a pass. |
| No live warehouse, Omni tenant or deployment runner is configured | Complete the candidate/local work and name the specific remaining target integration; do not claim deployment or security acceptance. |
| Native submission outcome is unknown | Preserve the journal/IDs, observe the existing operation and follow the reconciler/recovery contract; do not blindly resubmit. |

## Review a delivered package

Extract the current named ZIP and open `START_HERE.html`. In **Data model**, use **Domain** to group and filter the recorded domains, then choose one gold output and follow its pipeline top to bottom. **All domains** resets the filter; **Unassigned** keeps missing assignments visible. Shared upstream tables stay in each selected pipeline. Click a table for grain, columns, keys, joins and mapped code; use **Back to model** or Escape to close details. **Actual size** and **Expand diagram** preserve readable labels. Use **Detailed joins & relationships** for the ERD and its filters. **Download this pipeline** saves one SVG; **Download all pipelines** saves the current asset-permitted set; with a domain selected, **Download domain pipelines** saves that domain’s visible set. The full delivery package and approval scope remain unchanged.

**Code & files** identifies the selected implementation, setup guide and standalone ERD/dictionary paths. Selecting an indexed file opens its preview immediately. Generated ERDs and dictionaries open visually; **View source** exposes the original text, and downloads retain the original bytes. dbt SQL belongs in its project; native SQL and Coalesce follow their selected integration guides. **Validation** explains reported checks and what remains unverified. A generated file or clean package is not deployment approval.

Use **Request a change** on a table, or **Prepare review feedback**, to download a version-bound correction/question. Return it to the agent with the current package. The agent checks freshness using `review_feedback.py --page /absolute/current/START_HERE.html --responses /absolute/model-review-feedback.json` before reconciling changes into the existing engagement. Feedback is not automatically applied and cannot approve a design or authorize deployment. Existing decision-answer and review workflows remain available.

The numbered sections contain selected deliverables and, when documentation is selected, guides that expose empty sections. Selected diagrams include SVG views and editable model source. In simple layout, the dictionary includes the full supplied column CSV and a compact Markdown table index linking to it; classic layout retains the full Markdown column table. The root README identifies the entrypoint and files. Technical evidence and previous immutable exports stay outside the customer handoff.

## Work through domains one at a time

Ask: “Identify the candidate business domains first. Show me the choices and
shared dependencies, then ask which domain I want to design first.” The
accelerator records your selection, designs that domain, walks you through its
ERD/tables/decisions, and waits for your design approval before generating the
selected warehouse and Omni code. It then asks which domain to tackle next.

The **Domain journey** panel tracks queued, active, paused, completed and stale
work. Its offline picker prepares a request for the agent; it never executes code
or approves a design. Previously completed models and shared dimensions are
reused. Changed shared contracts flag affected domains for another review.

You can still ask for provisional code with incomplete context. It stays marked
provisional; say “pause this domain and work on inventory next” to save progress
without calling it complete. “Completed” means current reviewed candidate code is
recorded, not production acceptance. Validation, packaging and deployment keep
their existing checks. Existing engagements can adopt this flow without losing
their saved work. See the [operator contract](../skills/data-model-accelerator/references/domain-journey.md).
