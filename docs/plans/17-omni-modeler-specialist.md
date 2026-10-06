# Dedicated Omni Modeler — research-backed implementation plan

**Status: bounded local implementation complete on `atx/omni-modeler`; native and external-host qualification pending.** Prepared 2026-10-05, America/Chicago, against DMA commit `f705497c4e49b91c01bbd81b0d24bc0774b900f1`. Follow the [qualification record](../../validation/omni-modeler/README.md) for actual completed scope and test results. This extends [plan 16](16-omni-and-sensitive-data-repair.md); its authority, privacy, independent-validation and release controls remain requirements. Responsibilities below are roles, not named commitments or delivery dates.

## Recommendation

Create a first-class **DMA Omni Modeler** role covering models, views, relationships, topics and query views, with explicit capability and qualification records. Compose selected modules from Omni's official agent-skills project with DMA's existing engineering and evidence contracts. Do not create another unversioned modeling manual or assume that an upstream agent prompt establishes runtime support.

The official repository already includes an [Omni Modeler agent](https://github.com/exploreomni/omni-agent-skills/blob/90d523181438a46d59cf976ed9117174d29889da/agents/omni-modeler.md). Research pin: `90d523181438a46d59cf976ed9117174d29889da`, dated 2026-10-01. Its [model explorer](https://github.com/exploreomni/omni-agent-skills/blob/90d523181438a46d59cf976ed9117174d29889da/skills/omni-model-explorer/SKILL.md), [model builder](https://github.com/exploreomni/omni-agent-skills/blob/90d523181438a46d59cf976ed9117174d29889da/skills/omni-model-builder/SKILL.md) and [AI optimizer](https://github.com/exploreomni/omni-agent-skills/blob/90d523181438a46d59cf976ed9117174d29889da/skills/omni-ai-optimizer/SKILL.md) provide a useful starting point. These are implementation guidance; current API documentation and observed target behavior still govern qualification.

**Success means:** an engineer can ask for a new model, migration, refactor, repair or audit; the correct specialist actually runs; changes preserve approved meaning; unsupported features remain visible; and the resulting package explains what was generated, what was tested and what still needs a decision. “All-encompassing” describes ownership and discovery coverage, not an unsupported promise that every Omni feature can be generated or deployed automatically.

## Evidence and present gaps

Research combined current official documentation, the pinned upstream skills, a bounded review of nine Slack threads, and relevant text from seven internal training decks. Internal links, customer examples and private observations are retained outside this public repository. Training recordings and live demonstrations were not reviewed. No tenant validation or warehouse execution was performed for this plan.

| Current DMA finding | Consequence | Planned correction |
|---|---|---|
| [Specialist planner](../../skills/data-model-accelerator/scripts/plan_specialists.py) lists a generic `semantic_architect`; it creates source prompts, not executable target-role evidence | A role name does not prove that an Omni modeler ran | Add an explicit target task contract, host adapter and verifiable results |
| Omni native model files are not a recognized source family in that planner | Existing Omni projects lack a dedicated inventory/refactor route | Recognize native filenames and structural context; distinguish unrelated files and mixed repositories |
| [Static contract](../../skills/data-model-accelerator/scripts/omni_contract.py) and [generator](../../skills/data-model-accelerator/scripts/generate_omni_model.py) support a bounded subset | Physical/inherited views and simple topics do not constitute general Omni modeling | Version capabilities by object, operation, dialect and qualification |
| Native `.query.view` identity, top-level `query:`/`sql:`, composites, advanced selectors and filtered measures are outside that subset | Valid Omni constructs can be rejected before native validation | Separate invalid syntax from valid-but-unsupported constructs; expand with independent examples |
| [AI context projection](../../skills/data-model-accelerator/references/omni-ai-context.md) requires direct approved gold bindings | Legitimate derived/query-view semantics need a safe lineage extension | Trace approved semantic derivations to accepted inputs without weakening disclosure or meaning review |
| The installed local skill differs from this checkout and lacks recent Omni modules | Two operators can receive different behavior from the same request | Report installed version, repository revision and dependency pins at start; verify installation explicitly |

**Confidence: High** in these repository findings and the architectural recommendation. Feature-specific automation remains unqualified until implemented and tested. Prior local regression results are historical evidence for their exact revision, not a new test run or live acceptance.

## Source policy and corrections to encode

Use current official docs/changelog for product contracts and release labels; pinned vendor code for implementation examples; training for teaching patterns; full Slack threads for field observations and regression ideas. Internal evidence cannot override documented behavior silently. When documentation and observed behavior disagree, retain both, narrow the capability and investigate. Absence of a release label does not establish GA.

| Research finding | Rule for the specialist |
|---|---|
| Current documentation supports dbt deferral in non-production environments and partial-build virtual-schema workflows | Inspect the configured environment. Do not repeat older guidance that deferral is unavailable or require cloning every environment. [Environments](https://docs.omni.co/integrations/dbt/environments), [virtual schemas](https://docs.omni.co/integrations/dbt/virtual-schemas) |
| Both modeled-query and SQL query views are documented | Treat them as first-class modeling options with distinct contracts. Saving a query view does not prove materialization or warehouse parity. [Query views](https://docs.omni.co/modeling/query-views) |
| YAML read modes, write modes, shared/workbook scope and branch context are different contracts | Always set modes explicitly; preserve exact file paths and checksums. Current GET documentation defaults to `combined` and limits branch reads to shared/combined. Qualify writes separately. [Get model YAML](https://docs.omni.co/api/models/get-model-yaml) |
| AI selection can be ambiguous and context is constrained | Inspect reachable fields and context projection, evaluate selection/results, and require clarification when necessary. Never promise deterministic routing from prose or hard-code an old universal field-count limit. [AI optimization](https://docs.omni.co/modeling/develop/ai-optimization) |
| Model edits can break existing content; stale branch snapshots can overwrite newer work | Test the affected dependency closure, synchronize before promotion and read back the result. A clean YAML check alone is insufficient. [Git best practices](https://docs.omni.co/integrations/git/best-practices), [Content Validator](https://docs.omni.co/api/content-validator/validate-content) |
| Feature availability and lifecycle differ | [Composite topics](https://docs.omni.co/modeling/composite-topics) are **Beta**; full extension-model Git support is described as **work in progress** in the [extension deployment guide](https://docs.omni.co/guides/deployment/scaled-deployments-shared-model-extensions). [Extension cache scheduling](https://docs.omni.co/modeling/models/cache-policies) is **coming soon**. The [model `skills` parameter](https://docs.omni.co/modeling/models) is **scheduled to be deprecated**. Preserve these limits; do not build new dependencies on prospective or deprecated paths. |

Review upstream rules before adoption. Do not invent primary keys to satisfy a style rule, force `aggregate_type` onto every SQL-derived measure, treat a nonempty result as correctness, or automatically ship because a vendor workflow suggests it. Keep current DMA target authorization, approval, disclosure, checksum and journal requirements authoritative. Resolve historical field reports using their replies; fixed issues become regression tests, not permanent product limitations.

## User journey and decisions

1. **Discover the engagement.** Reuse existing answers; establish new build, migration, refactor, repair or read-only audit. Confirm business questions, audience, critical metrics, source completeness, selected outputs and available SMEs. Unknown meaning remains a decision, not a fabricated definition.
2. **Confirm the working boundary.** Identify repository/version, catalogue authority, framework, warehouse/dialect, Omni model, schema/shared/workbook scope, branch/environment, credential identity and allowed actions. Offline review works without credentials. Do not expose restricted inputs merely to complete discovery.
3. **Explain the proposal.** Show domains/topics, base populations, grain, metric definitions, placement choices, access implications, impact and unresolved questions. Start with one representative domain and independent expected results.
4. **Build and independently test.** Produce the selected candidate files and documentation; run applicable static, native, result, access and AI checks. Separate blockers from warnings and from checks awaiting access.
5. **Review a clear handoff.** `START_HERE.html` presents the model, change rationale, decisions, evidence and next action. After review, the existing deployment coordinator offers only qualified, authorized delivery routes and destinations. Modeling approval does not itself authorize deployment.

The modeler asks targeted questions where the answer changes semantics or access. It should not repeat intake, ask for routine reversible edits already authorized, or block unrelated work while a definition is unresolved. Default to small, reviewable changes rather than bulk replacement of an existing model.

## Role, integration and authority

| Role | Owns | Boundary |
|---|---|---|
| DMA orchestrator | Intake, approved projections, task dispatch, dependency ordering and coverage | Does not invent specialist execution or approve its own missing evidence |
| Source specialist | Source behavior, formulas, identifiers, filters and unresolved source logic | Does not choose business truth or certify target parity |
| Warehouse engineer | Conformed facts/dimensions, SQL, grain tests, catalogue and upstream ownership | Supplies accepted contracts to the modeler; does not independently certify its own outputs |
| **DMA Omni Modeler** (`omni_modeler`) | Effective model inventory, placement recommendations, native candidates, topic/field mapping, query views, AI proposals and change impact | Cannot self-approve meaning, permissions, independent results or production promotion |
| Independent semantic validator / analyst | Expected results, model/query behavior, negative controls, downstream impact and evidence review | Runs separately from authoring; SMEs remain the authority for business definitions |
| Security and release roles | Approved handling, effective-access checks, destination authority and promotion | Existing plan-16 contracts remain in force |

Reuse existing analyst/QA roles rather than creating an agent for every object type. Dispatch `omni_modeler` when Omni is the selected semantic target, when an existing Omni model is being assessed, or when explicitly requested. Keep the general semantic architect for other targets. Actual host execution must return a task receipt; a generated prompt or an upstream Markdown agent file is not proof of dispatch.

**Input contract:** run/task IDs; approved scope; source and catalogue pins; effective/authored model snapshot; dependency graph; definitions and unresolved decisions; placement version; privacy policy; target identity; permitted operations; selected capability/knowledge/adapter versions.

**Output contract:** inventory and dependency graph; proposed change set and original-byte hashes; rationale and source lineage; grain/key/join evidence; target files; source-to-target crosswalk; topic audience and metric definitions; AI-context candidate; validation requests/results; content impact; unresolved/unsupported items; deployment handoff. All outputs bind the same run and exact candidate version. No credentials, hidden provider diagnostics or unapproved samples travel in these records.

## Capability coverage

Every capability records separate states for `documented`, `implemented`, `locally_tested` and `live_qualified`. Track inspect, preserve, generate, statically validate, natively validate and deploy independently. A feature may be preserved safely while generation remains unsupported. Do not collapse these into a single green “supported” label.

| Surface | Required coverage and modeling judgment | Acceptance focus |
|---|---|---|
| Models and scopes | Schema/shared/workbook/branch origin, inheritance, effective overrides, constants, calendars/timezones, includes/routing, SQL preambles, caching and environments | Explain which definition wins; preserve unrelated settings and workbook intent; scope-specific contracts and least-privilege handling of operational settings |
| Physical and inherited views | Catalogue bindings, quoted identifiers, dimensions/measures, schema overrides, multi-extension and topic-scoped variants | Exact physical identity, resolved dependencies, faithful round trip; never generate a key without grain/uniqueness evidence |
| Fields and metrics | SQL/aggregate measures, filtered and distinct measures, formats, timeframes, labels, groups, synonyms, NULL/zero semantics, semi-additivity and period comparisons | Ratio-of-sums versus sum-of-ratios; duplicate keys; empty populations; timezone/fiscal/DST boundaries; no arbitrary default currency |
| Relationships | Global/topic scope, cardinality/direction, optionality, aliases, role-playing dimensions, self joins, temporal joins, bridges and competing paths | Counts/totals at intended grain, orphan preservation, multiple one-to-many branches, current/as-of lookup, overlapping validity intervals and many-to-many allocation |
| Topics | Business/audience scope, base population, reuse versus new topic, curated selectors, topic views/relationships, mandatory/default filters and access settings | Reachable fields, stable identifiers, effective joins, correct filtering stage and downstream dependencies |
| Query views | Native `.query.view`, modeled `query:` and SQL `sql:`, output shape, dependencies, aggregation grain, filters, sort/limit behavior, promotion and schema drift | Query/SQL forms compile and match independent results; no unnoticed truncation, stale fields or unverified physical substitution |
| Composite topics — **Beta** | Component topics, shared dimensions/views, cross-fact measures, field identity and unrelated-record handling; explicit selection and tenant qualification | Unequal grains and missing groups; compare component and combined totals; no forced single wide model |
| Advanced calculations | Level of detail, filter-only/templated filters, table calculations and supported cross-view references | Explicit inner/outer grain and filter stages; preserve per-query behavior instead of blindly hoisting calculations |
| Aggregate awareness | Existing aggregate eligibility, grain/dimension/measure compatibility, freshness and environment references | Observe actual query plan/rewrite and result parity; compare cost/performance without asserting a universal benefit |
| AI readiness | Model/topic/view/field context, descriptions, selection controls, approved values, synonyms, tested sample queries and ambiguity | Persona-specific question suite, selection/results, clarification/refusal and disclosure; no invented business meaning |
| Governance and lifecycle | Grants/access filters versus visibility, dependency impact, schema/dbt sync, leader/follower Git routes, branch drift, freshness/cache policy and recovery | Credential-specific allow/deny tests, exact state/readback, safe partial failure, candidate-specific receipts; cached/uncached and suggestion freshness checks |

This is the target inventory, not a claim that all rows are currently implemented. Rare or newly documented features enter the registry with explicit gaps; they must not be silently removed, rewritten or treated as invalid Omni syntax.

## Placement policy

Choose placement from reuse, grain, security, performance, operational ownership and portability. Reusable cleansing, deduplication, identity conformance and durable fact/dimension construction normally belong in the warehouse. Shared metric definitions, governed exploration and audience-specific context belong in the semantic model when appropriate. Query views are legitimate for reusable semantic composition or aggregation; repeated expensive transformations may justify an upstream implementation. One-off workbook calculations may remain local.

For each rule, record observed source behavior, approved meaning, chosen layer, alternatives and a parity test. Preserve unresolved differences. Do not push every query view upstream, promote every local calculation globally, or build one giant topic merely because tables can join. Keep transformation framework and warehouse selection independent: dbt/Coalesce/native SQL remain existing engineering responsibilities, while the modeler binds the resulting qualified relations.

## Implementation sequence and exit criteria

Implement and validate each package before advancing. A package can complete local engineering while native qualification remains pending; dependent live actions cannot bypass that pending state. Proposed new file names below are design targets, not existing modules.

### 1. Versioned knowledge and capability contract

**Owner:** architecture/semantic maintainer. **Depends on:** none.

- Create a short role reference plus focused modules for scopes, fields, joins/topics, query views, advanced patterns, AI and lifecycle. Load only the modules relevant to the task.
- Add a knowledge manifest with claim/source ID, official URL or private reference, retrieval date, source revision/hash where available, exact release label or `not_stated`, applicable feature/dialect, evidence type, confidence and unresolved conflicts. Keep internal content in an access-controlled optional overlay, never public fixtures or default prompts.
- Pin selected upstream modules and runtime versions; record their purpose and local overrides. Prefer dependency composition. If code/text is copied, retain applicable Apache-2.0 license/attribution notices; do not relabel upstream material as MIT. Verify the distribution approach during implementation.
- Document an ADR for composition, conflict precedence and maintenance ownership. Refresh affected sources when docs/dependencies change or a contract fails; upstream changes require review and regression tests, not automatic trust.

**Exit:** public-only installation can operate; denied internal sources are not exposed; conflicting claims remain visible; a changed pin invalidates affected qualification. No universal “latest docs” claim without a recorded revision/retrieval.

### 2. Real target-role dispatch and reproducible installation

**Owner:** orchestration engineer. **Depends on:** 1.

Extend `plan_specialists.py`, orchestration references, specialist-result verification and guided workflow with `omni_modeler` input/output contracts. Report the active installed skill versus repository version before executing. Distinguish planned, running, completed, failed and unavailable tasks. Preserve non-Omni flows.

Provide host adapters for actual capabilities available in Claude Code, Codex, Gemini, Cortex Code and the specifically selected Genie runtime. A shared skill file is not host qualification. Where delegation is unavailable, a disclosed sequential role with independently prepared validation may be used. Separately, every route without qualified tool/filesystem containment must accept only independently reviewed pre-sanitized inputs or approved non-sensitive metadata; inline execution cannot substitute for containment. Do not claim sandbox isolation from a prompt.

**Exit:** fresh installation triggers the correct role; non-Omni requests do not; missing/stale installations are actionable; a planner-only run cannot claim a completed specialist. Test each host separately and publish unqualified rows honestly.

### 3. Omni inventory, model representation and change safety

**Owner:** semantic adapter engineer. **Depends on:** 2.

Add a deterministic Omni source adapter and typed internal representation. Preserve full native filenames, authored bytes, scope, inherited origin, logical/physical IDs, dependency edges and unresolved references. Read effective and authored state separately; never write merged effective state back as authored overrides. Emit origin-aware minimal changes with explicit deletion intent, leaving inherited defaults inherited. Detect query-view naming correctly. Inventory offloaded/missing schemas through qualified explicit reads; missing from one response does not mean nonexistent.

Round-trip unchanged artifacts without semantic loss; preserve unsupported blocks as opaque source content and prevent edits that depend on unresolved meaning. Extend generation/static checks with scope-aware schemas. Keep diagnostics for malformed YAML, invalid supported syntax, missing dependencies and unsupported features distinct. Version and migrate existing contracts instead of silently reinterpreting old evidence. Reconcile parsed coverage against an authoritative export/API inventory, including pagination and scope; two counts derived from the same incomplete input cannot establish completeness.

**Exit:** mixed repository fixtures route correctly; no-op round trips retain content and a combined-read no-op emits no writes; omitted files never imply deletion; duplicate keys, cycles and conflicting IDs fail. Valid unfamiliar constructs survive inventory without receiving a false validation pass. Existing bounded supported cases remain valid.

### 4. Core views, measures, relationships and topics

**Owner:** Omni model engineer; QA owns expectations. **Depends on:** 3.

Expand `omni_contract.py`, `generate_omni_model.py` and focused reference modules for model settings, inherited/topic overrides, filtered/custom measures, topic selectors, aliases and relationship paths. Derive generation from approved contracts and actual catalogue evidence. Prefer scoped changes over broad global overrides.

**Exit:** independent synthetic fixtures cover duplicate lookup keys, two child fact branches, role-playing dates, missing dimensions, NULL/empty results, ratios, filters, formats and calendars. Add current-versus-as-of dimensions, overlapping validity intervals and many-to-many bridge allocation/deduplication; keep unqualified combinations explicitly unsupported for generation. Prove that deliberately wrong cardinality or population fails; YAML validity alone cannot satisfy data correctness. Do not infer uniqueness from a column name or description.

### 5. Query views and advanced composition

**Owner:** Omni model engineer with warehouse architect review. **Depends on:** 4.

Implement modeled-query and SQL query-view representations, filename validation, output-field resolution and lineage. Integrate them with generation, static checks and native adapter candidates. Capture grouping, filters, sort/limits, nested dependencies, semantic references and environment bindings. Parse SQL conservatively within the approved read-only contract; do not execute source SQL or operational model settings to discover their meaning. Handle workbook-to-shared promotion only through a qualified, authorized route.

Add composite topics, level-of-detail/filter constructs and aggregate-awareness modules as independently gated capabilities. Do not gate basic query-view delivery on every advanced feature. Upgrade AI lineage contracts to cover reviewed semantic derivations over approved warehouse inputs, including query views; maintain existing approved-gold restrictions by default and require an explicit reviewed scope change for other source layers.

**Exit:** valid query views reach the native-validation stage; incomplete output shape remains pending; modeled and SQL forms agree with independently frozen expectations. Composite missing groups, nested filter stages, limited queries, renamed source columns and aggregate compatibility have negative controls. Never treat a saved query as a physical materialization.

### 6. Native lifecycle, impact and access qualification

**Owner:** integration engineer and independent security/QA reviewers. **Depends on:** 4–5 for selected features.

Extend the existing `omni_native.py` contract rather than bypassing it with unrestricted CLI calls. Qualify exact CLI/API versions, endpoint modes, credentials, target model/branch, physical environment, timezone and checksum semantics. Retain the current isolated synthetic-development boundary until a separately reviewed expansion qualifies real-data handling.

For dbt changes, verify the selected environment and completed build, refresh the intended schema, then inspect content impact. Deferral needs explicit environment/physical-resolution evidence, including intentional production fallback for unbuilt relations. Existing physical-to-virtual schema migration is documented as an operation outside branches and needs separate authorization. Do not infer isolation from a branch ID. Separate reference-only content scans, query compilation and query execution in evidence.

Inspect baseline defects and changed dependency closure. Block new failures and affected unresolved baseline failures; an unrelated documented pre-existing issue may remain visible without triggering destructive repair. Read and compare whole-file state before updates, use supported concurrency controls and reconcile ambiguous writes. Never auto-refresh production or merge merely to clear an error.

Honor the configured native/Git leader/follower route; followers are read-only. External Git edits are discouraged by official guidance; validate the supported route before proposing them. Include attached content in the promotion inventory because a model PR can publish that content too. Keep existing repository bypass/protection policy unchanged. Test stale branch promotion, partial writes, permissions, rate limiting, redacted failures and recovery before enabling new operations. A passing Git connection test does not establish functioning webhooks or review enforcement.

**Exit:** exact-candidate native results distinguish HTTP success from model errors; content impact includes relevant dependencies; access tests use actual selected principals and query paths. Offline/simulated/pending evidence never appears live-qualified. Zero rows can be correct; compare against the expected population.

### 7. AI context and independent behavior evaluation

**Owner:** semantic analyst; SMEs approve definitions. **Depends on:** 5–6 for selected paths.

Extend `omni_ai_context.py` with reviewed derived lineage, effective topic reachability and context provenance. Keep guidance concise and evidence-backed. Preserve server-managed `ai_context_patch` rather than authoring its contents; inspect the effective merged context after parent changes. Use closed-value lists only where complete and authorized; do not expose values through examples. Bind tested sample queries to current field identities. Treat AI selection controls separately from security policy.

Freeze questions, expected definitions, fields, results, personas and ambiguity decisions independently from the generated candidate. Evaluate duplicate metric labels, time/currency ambiguity, context truncation, unrelated requests, missing attributes and restricted fields. Put clarification in a coordinator when the selected query tool cannot perform it. Native AI evaluation features remain optional and status-qualified; a portable evaluation contract must still work without them.

**Exit:** field/context drift invalidates affected results; a confident answer using the wrong metric fails; unauthorized disclosure fails; appropriate clarification succeeds. Record repeated trials and applicable provider/settings to expose nondeterminism. Structured offline comparisons remain distinct from observed native AI behavior and business acceptance.

### 8. Guided delivery and fresh-user qualification

**Owner:** delivery engineer and independent pilot operator. **Depends on:** 1–7 for the claimed release scope.

Integrate the candidate into the existing HTML/ZIP workflow. Provide the model/ERD, dictionary, topic and metric catalogue, placement rationale, query-view dependencies, AI context, selected native files, validation summary and deployment instructions. Keep technical evidence optional in navigation, not optional for readiness. Preserve sensitivity scanning of exact output bytes.

Run two independent exercises: (a) a new model from a raw catalogue with missing business context; (b) a messy existing model with workbook overrides, query views and downstream content. Add an SME-assisted iteration to demonstrate that definitions can change without losing source behavior or stale-approval protection. Start native qualification with selected dbt/Snowflake and BigQuery environments; maintain separate rows for Databricks, Redshift, ClickHouse and MotherDuck. Framework coverage and dialect parsing do not imply native Omni qualification.

Update `SKILL.md`, README, HOW_TO, CAPABILITIES, orchestration references and installation checks only to the level proved. Dashboard construction stays with its existing specialist, with stable field/topic mappings and impact handoffs from the modeler; it cannot disappear from a requested full migration.

**Exit:** a fresh operator can identify the starting point, decisions, supported scope and exact next step without conversation history. Generated/native/passed/approved/deployed states stay separate; packaging contains no private research. Record observed runtime, tool calls, retrieval volume and costs where available, with agreed pilot thresholds rather than invented performance promises.

## Qualification corpus and release decision

Maintain independent fixtures at three levels: deterministic contract tests, controlled native integration tests and fresh-operator end-to-end exercises. Include valid advanced examples as well as malformed ones, so the checker cannot improve apparent safety by rejecting every feature. Add holdout domains, different naming conventions and counterexamples unknown to the authoring agent.

Required negative cases include wrong-grain joins, alias collisions, sum-of-ratios drift, filter-stage changes, row-limit truncation, stale schema/branch/context, denied fields through alternate paths, source prompt injection, incomplete inventories and unsupported host containment. Benchmark larger synthetic projects with bounded retrieval, caching keyed to revision and affected dependency analysis; never truncate context silently or expose a broader catalogue just to improve recall.

Release a capability only when its selected operation has reproducible evidence for the exact source/candidate/target/policy/version, independent expected outcomes and a recovery path. Local tests, native validation, data parity, effective access, AI behavior and SME approval are separate gates. Do not claim a percentage of universal modeling accuracy from a small exercise.

**First implementation milestone:** packages 1–3 establish trustworthy knowledge, real specialist dispatch and lossless Omni intake. Packages 4–5 supply the missing modeling breadth. Packages 6–8 establish native confidence and the operator experience. No production or customer sign-off is implied by completing this plan.

## Public reference map for implementation

All sources below were reviewed on 2026-10-05. Recheck affected contracts when implementing and before qualification. A guide or example establishes neither exhaustive API coverage nor tested behavior in the customer's environment.

| Knowledge module | Primary reference set |
|---|---|
| Scope and inheritance | [Modeling layers](https://docs.omni.co/modeling), [model parameters](https://docs.omni.co/modeling/models), [extension deployment](https://docs.omni.co/guides/deployment/scaled-deployments-shared-model-extensions) |
| Topics and joins | [Topics](https://docs.omni.co/modeling/topics), [topic best practices](https://docs.omni.co/modeling/topics/best-practices), [relationships](https://docs.omni.co/modeling/relationships), [role-playing joins](https://docs.omni.co/guides/modeling/join-to-same-table), [composite topics](https://docs.omni.co/modeling/composite-topics) |
| Query views and placement | [Query Views](https://docs.omni.co/modeling/query-views), [view query parameter](https://docs.omni.co/modeling/views/parameters/query), [view SQL parameter](https://docs.omni.co/modeling/views/parameters/sql), [LOD placement alternatives](https://docs.omni.co/guides/patterns/level-of-detail-build-comparison) |
| Metric semantics | [Symmetric aggregates](https://docs.omni.co/analyze-explore/sql/symmetric-aggregates), [single-field filters](https://docs.omni.co/guides/modeling/single-field-filter), [level of detail](https://docs.omni.co/analyze-explore/custom-fields/level-of-detail) |
| Security, AI and freshness | [Data access controls](https://docs.omni.co/modeling/develop/data-access-control), [AI optimization](https://docs.omni.co/modeling/develop/ai-optimization), [answer quality](https://docs.omni.co/guides/ai/improve-ai-answer-quality), [model AI context](https://docs.omni.co/modeling/models/ai-context), [cache policies](https://docs.omni.co/modeling/models/cache-policies) |
| dbt and delivery | [dbt integration](https://docs.omni.co/integrations/dbt), [preview dbt changes](https://docs.omni.co/guides/modeling/preview-dbt-changes), [dbt environments](https://docs.omni.co/integrations/dbt/environments), [virtual schemas](https://docs.omni.co/integrations/dbt/virtual-schemas), [single-instance deployment](https://docs.omni.co/guides/deployment/single-instance-git-dbt) |
| Git and native validation | [Git integration](https://docs.omni.co/integrations/git), [settings](https://docs.omni.co/integrations/git/settings), [follower mode](https://docs.omni.co/integrations/git/follower-mode), [Git best practices](https://docs.omni.co/integrations/git/best-practices), [read YAML](https://docs.omni.co/api/models/get-model-yaml), [Content Validator](https://docs.omni.co/api/content-validator/validate-content) |

Further contract discovery is required for exact serialized advanced constructs, aggregate-awareness combinations, newly selected endpoints and host-specific delegation. Their inclusion in this plan is a research/engineering requirement, not an unsupported claim of qualification.
