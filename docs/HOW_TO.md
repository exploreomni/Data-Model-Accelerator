# How to run a modeling engagement

Use the accelerator with your coding agent to turn source data and reporting logic into a model that an analytics engineer can run and subject-matter experts can review. Start with one business domain, agree on its meaning, build a candidate, and prove the relevant behavior before expanding.

See the [project overview](../README.md) and [capabilities and limits](CAPABILITIES.md) for the current release scope.

You can drive the work through prompts. The agent maintains the technical records and runs the selected helpers; SMEs do not need to edit JSON or learn dbt. The command examples below expose the same local workflow for engineers who want to operate it directly.

## 1. Make the skill available locally

Use an approved checkout or downloaded copy of this repository. The core discovery, review and packaging helpers need **Python 3.9+ on a POSIX host** and use the standard library. Native dbt adapters, vendor tools and optional validation exercises have separate pinned requirements; install only what the selected path needs, in an isolated environment. Do not upgrade an existing project's runtime just to match an example.

From the accelerator repository root:

```sh
python3 --version
python3 skills/data-model-accelerator/scripts/guided_workflow.py --help
```

Your agent can read `skills/data-model-accelerator/SKILL.md` directly. To install it in a host's skill directory, copy the **entire** `skills/data-model-accelerator` folder, including references and scripts. Preserve an existing installation unless you deliberately choose to update it. Do not install only `SKILL.md`.

The [host setup reference](../skills/data-model-accelerator/references/targets-and-hosts.md#host-packaging) lists the documented locations for Codex, Claude Code, Gemini CLI, Cortex Code/CoCo Desktop and Genie Code. Check the selected host/version's discovery and file-execution support. These packaging paths do not establish that every host has been tested, has a warehouse connection, or supports independent subagents. A chat surface without file execution needs an authorized engineering runner for executable checks. Cortex Agents is a separate, currently unqualified packaging route.

Ask the agent to confirm it can load the skill and its relative references before starting customer work. Installing the skill does not grant access to accounts or authorize deployment.

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

> Read and follow `/absolute/accelerator/skills/data-model-accelerator/SKILL.md` for `/absolute/approved/source`. Start with a read-only assessment of the order analytics domain and save this engagement outside that source folder. I am comfortable with dbt, and our order operations and finance SMEs are available. Target dbt on Snowflake with Omni downstream. Interview us in short rounds and retain every answer. Preserve existing working behavior unless we explicitly approve a change. Deliver the model, connected ERDs, complete dictionary, layer documentation, candidate dbt project, tests, Omni files and AI context in one guided engineering ZIP. Identify the independent baseline before implementing changes. Discovery does not authorize executing source code or contacting a warehouse.

Choose these independently: **source formats, agent host, transformation framework, warehouse, semantic engine, and execution scope**. Detecting a dbt or Looker source does not choose the destination. “GCP” needs a specific service, such as BigQuery. Omni is optional. Use the [platform matrix](PLATFORM_MATRIX.md) to distinguish candidate authoring from qualified native execution; Coalesce requires a representative versioned native project contract.

Also select the completion scope: `model_only` for the warehouse model,
`model_semantic` for the model and Omni semantic layer, or `full_dashboard` for
dashboard migration as well. Reuse a choice already supplied. If you choose a
full dashboard migration, topic files alone cannot complete it: tile, filter,
listener, layout, interaction and access evidence remain in scope.

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

This is a business review loop, not a vote among agents. An SME's answer can approve a definition; it does not automatically approve a warehouse deployment. The agent maintains the detailed decision register and model specification separately from the short intake fields. Do not invent an `approve` command or add unsupported answer keys.

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

Supply a scoped, dated raw-layer catalogue through authorized read-only access or a nonsecret operator export. Include the actual namespace, visible tables/columns/types, collection identity and visibility gaps. The agent normalizes and verifies the catalogue, binds proposed inputs to it, and separately profiles keys, nulls, duplicates, join cardinality and unmatched rows.

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py assess \
  --run /absolute/engagement-run \
  --catalogue /absolute/reviewed-catalogue.json
```

Registering catalogue bytes in the workflow is not catalogue validation. The [catalogue contract](../skills/data-model-accelerator/references/raw-catalogue.md) and [provider templates](../skills/data-model-accelerator/references/catalogue-providers.md) supply the separate checks. A CSV header is lexical metadata, not a verified Snowflake type or permission. A simulated raw table must stay labeled as a simulation. Existing ingestion remains in place unless a separately scoped change is requested.

Review a proposal before implementation: entity grains and keys; source-to-target mappings; Bronze/Silver/Gold responsibilities; warehouse versus semantic rules; history and deletion behavior; privacy publication boundaries; and unresolved decisions. A layer name does not require an extra physical copy of every table. Keep header and line measures separate, role-specific joins distinct, and interactive ratios or distinct counts at their intended query grain.

## 5. Build a candidate and validate it independently

Existing authorization remains valid for the same action and environment. The agent should complete already-authorized work without repeated permission requests; a new target or expanded action needs its own scope. Recording a requested execution mode in intake is not itself authorization.

After the proposal and execution scope are clear, ask:

> Implement the reviewed candidate in the agreed isolated output or development checkout. Preserve source identifiers and current project conventions. Have an independent analyst freeze expectations from the approved sources and definitions before inspecting candidate results. Run only the local or development checks already authorized. Report complete coverage, discrepancies and remaining target checks; do not change expected results to make the candidate pass.

For an existing dbt project, expect a focused patch and integration instructions. For a new project, expect models, sources, macros/configuration, tests, a nonsecret profile example and ordered setup commands. Run dbt SQL through dbt; do not paste unresolved `ref()`, `source()` or Jinja into a warehouse editor.

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

Review topic grains, measures, role-specific joins, defaults and field publication. Verify that moving logic upstream does not apply it twice downstream. Resolve environment placeholders before native import. Optional dbt metadata integration is a separate setup task; generated YAML does not establish a live integration.

Supply portable AI context and documented native `ai_context` fields describing accepted definitions, time anchors, unknowns, safe source-bound questions and unsupported interpretations. SMEs should review the language an analyst or agent will use. AI guidance, hidden fields and topic curation do not enforce permissions. Native Omni import/query checks and allowed/denied persona tests remain necessary in the authorized tenant. See [semantic placement](../skills/data-model-accelerator/references/semantic-placement.md) and the generated package's setup guide.

## 7. Open, select and iterate on the guided ZIP

Ask for the package you will actually use:

> Prepare an engineering handoff with the current model, connected diagrams, complete dictionary, layer documentation, runnable implementation and concise validation results. Include prerequisites and exact commands for the extracted folder. Exclude source rows unless explicitly selected and approved. Keep the full technical audit separate. Record the prepared handoff and verify the ZIP before delivery.

An engineering ZIP contains `START_HERE.html`, selected numbered folders and `DELIVERY_MANIFEST.json`. Open the guide offline, review changes/decisions and validation, inspect the connected model, then preview or copy the implementation files. Selectable downloads retain required dependencies. A reviewer ZIP excludes implementation, samples and audit; audit material uses a separate export. Smaller exports do not shrink the required internal model, dictionary or validation coverage.

The agent prepares the review manifest and exact file hashes, then uses:

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py record-handoff \
  --run /absolute/engagement-run \
  --review /absolute/review.json \
  --artifact-root /absolute/candidate-artifacts \
  --audience engineer

python3 skills/data-model-accelerator/scripts/delivery_portal.py package \
  --state /absolute/engagement-run/state.json \
  --review /absolute/review.json \
  --artifacts /absolute/candidate-artifacts \
  --audience engineer \
  --output /absolute/engineering-handoff.zip

python3 skills/data-model-accelerator/scripts/delivery_portal.py verify \
  /absolute/engineering-handoff.zip
```

These commands need the actual prepared review/artifacts; they do not manufacture them. Export must use the same audience and selections as the recorded handoff. The [review-surface reference](../skills/data-model-accelerator/references/review-surface.md) explains category selection and exported paths. Integrity verification proves the packaged bytes and links, not the reported business or execution results.

Return review comments to the same task: identify the rule/model, the reason and the SME's decision. Ask the agent to revise code, model, ERD, dictionary and context together, retain the previous version, rerun affected checks, and issue a new package.

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py resume \
  --run /absolute/engagement-run

python3 skills/data-model-accelerator/scripts/guided_workflow.py status \
  --run /absolute/engagement-run --json
```

`resume` refreshes source/catalogue context and invalidates dependent evidence after drift. `status` reads cached state; add `--refresh` to reassess. Do not edit saved state or replace stale evidence with a new timestamp. A prepared handoff means selected files passed integrity checks, not that the model is approved or deployed.

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
| SME changed a rule or source files changed | Resume, version the decision, update affected model/docs, and rerun dependent evidence. |
| Source scan is partial or the project is too large | Scope a coherent domain or explicitly review scan limits; preserve unexamined dependencies and consumers. |
| The bounded dbt runner rejects packages, hooks or stateful behavior | Preserve the project and use a qualified existing CI/operator route; do not delete functionality to obtain a pass. |
| ZIP export reports a missing link or dependency | Correct paths for the exported numbered folders and register the required files before recording/exporting again. |
| An extracted command cannot find a script or dependency | Use the package's runbook from its stated directory; include the missing helper or document its external prerequisite, then reissue the package. |
| SQLFluff reports source/framework conventions | Correct authored issues first; use only the documented reviewed exception contract and retain raw findings. Never rename source keys or suppress errors merely to obtain a pass. |
| No live warehouse, Omni tenant or deployment runner is configured | Complete the candidate/local work and name the specific remaining target integration; do not claim deployment or security acceptance. |
| Native submission outcome is unknown | Preserve the journal/IDs, observe the existing operation and follow the reconciler/recovery contract; do not blindly resubmit. |
