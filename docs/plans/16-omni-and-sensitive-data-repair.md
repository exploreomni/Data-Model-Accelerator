# Omni delivery and sensitive-data repair plan

Status: all nine work packages implemented and locally validated on `atx/omni-privacy-repair`; native qualification and release approval remain pending. Prepared 2026-10-05 against public repository commit `7a25a6b14992d1caaecbf9bd490efc97a40e5cb1`. See the [implementation qualification report](../../validation/omni-privacy-repair/README.md) for exact evidence and limits. This is a local implementation revision; no push or merge was performed.

This is a repository engineering plan, not customer acceptance, a compliance assessment, or deployment authorization. Owners below are responsibilities to assign, not named commitments. Implement and locally validate one work package before starting the next. Track live qualification separately: pending native evidence can permit further local engineering, but never dependent live actions. Record actual results and remaining limitations as work proceeds.

## Outcome

An engineer can supply a supported source export and warehouse catalogue, choose the intended deliverables, review the proposed model, and receive a package whose readiness is supported by evidence. The accelerator must preserve source behavior, distinguish proposed business corrections, protect sensitive information throughout processing, and expose incomplete work before handoff or deployment.

The repair covers two connected failures:

- Omni generation and delivery checks do not reliably establish model validity or completion of a dashboard migration.
- Existing classification, credential controls and package selection do not establish PII, PCI or PHI protection across agent inputs, generated code, metadata, AI context, logs and shared deliverables.

The shared controls apply across dbt, Coalesce and native SQL delivery, with explicit qualification for Snowflake, Databricks, BigQuery, Redshift, ClickHouse and MotherDuck. Looker dashboard JSON is the first source adapter to repair. Existing Looker, Hex, Tableau and Power BI exercises remain regression cases, not claims of exhaustive source support.

## Evidence and boundaries

The repository audit and synthetic probes establish the implementation gaps below. The customer repair report motivates additional acceptance cases, but its original export, pre-fix output, native validator results and live comparisons were not available to this audit. Do not describe the reported customer repairs as independently verified. Do not copy customer names, identifiers, source files, URLs or data into public tests.

| ID | Finding | Current implementation reference | Required repair |
|---|---|---|---|
| G01 | Standalone Looker dashboard JSON can route to unknown; selecting a profile does not parse it | [Source planner](../../skills/data-model-accelerator/scripts/plan_specialists.py) | Structural detection, supported export contracts and deterministic extraction |
| G02 | Semantic files receive YAML structure checks, not general Omni contract validation | [Delivery lint](../../skills/data-model-accelerator/scripts/lint_delivery.py) | Reusable Omni checks plus separate native evidence |
| G03 | The E2E compiler is tied to a synthetic domain and one Looker tile | [Bounded compiler](../../skills/data-model-accelerator/scripts/e2e_semantics.py) | Independent, multi-domain and multi-tile qualification |
| G04 | Requested dashboard completeness is not a required handoff dimension | [Review checker](../../skills/data-model-accelerator/scripts/verify_review_package.py), [guided workflow](../../skills/data-model-accelerator/scripts/guided_workflow.py) | Scope-aware completeness and readiness gates |
| G05 | Native Omni validation, rendered dashboard behavior and effective access remain unproven | [Looker exercise](../../skills/data-model-accelerator/scripts/run_looker_omni_e2e.py) | Native model, query, dashboard and persona evidence |
| G06 | Sensitivity levels do not express overlapping PII/PCI/PHI categories or enforced lineage handling | [Dictionary](../../skills/data-model-accelerator/scripts/data_dictionary_v2.py) | Versioned classification and propagation contract |
| G07 | Comments-only metadata can pass without approved sensitivity; downstream metadata exports all columns | [Metadata contract](../../skills/data-model-accelerator/scripts/metadata_contract.py), [handoff](../../skills/data-model-accelerator/scripts/metadata_handoff.py) | Destination-specific metadata and context disclosure policy |
| G08 | Audience/category selection does not scrub content; selected bytes survive ZIP and embedded HTML | [Delivery portal](../../skills/data-model-accelerator/scripts/delivery_portal.py) | Content-aware input/output gates and scanned release manifest |
| G09 | Informational metadata does not configure or prove masking, row restrictions or permissions | [Metadata capabilities](../../skills/data-model-accelerator/scripts/metadata_platforms.py), [metadata release](../../skills/data-model-accelerator/scripts/metadata_release.py) | Separate security policy contract, qualified adapters and effective-access checks |
| G10 | Generic integrity evidence is insufficient for Omni and privacy release decisions | [Release quality](../../skills/data-model-accelerator/scripts/release_quality.py) | Typed evidence with target, scope, provenance and freshness checks |

Confidence is High for these repository gaps. Native customer outcomes remain unverified.

### Product contract corrections to preserve

Official references checked 2026-10-05; refresh and pin their applicable contract when implementing adapters.

- Omni accepts named and Excel-style formats. Do not reject `0.0%` solely because it is not `percent_1`. [Measure formats](https://docs.omni.co/modeling/measures/parameters/format)
- `catalog` can be omitted when the verified connection default resolves the intended object. Require resolved physical identity, not an unconditional parameter. [Catalog](https://docs.omni.co/modeling/views/parameters/catalog)
- New physical fields and inherited/schema-model overrides need different SQL resolution rules. Resolve dependencies before declaring a missing field definition. [Dimension SQL](https://docs.omni.co/modeling/dimensions/parameters/sql)
- Current documentation uses title-case day names such as `Monday`; model/topic dynamic values need separate dependency review. Do not implement a blanket lower-case rule based on reported feedback. [Model week start](https://docs.omni.co/modeling/models/week-start-day), [Dimension week start](https://docs.omni.co/modeling/dimensions/parameters/week-start-day)
- `time` is not in the documented timeframe list. YAML bracket references must be validated in their actual context: an unquoted flow-list reference can be invalid while a block-list reference is valid. [Timeframes](https://docs.omni.co/modeling/dimensions/parameters/timeframes)
- Native model validation supports a branch and returns issue objects. HTTP 200 is not proof of zero errors. [Validate model](https://docs.omni.co/api/models/validate-model)
- Programmatic dashboard migration is documented. The dashboard import API is **Beta** and must be treated as a version-sensitive, explicitly selected dependency. Its payload is not a direct Looker JSON import. [Migration guide](https://docs.omni.co/guides/migrations/looker-to-omni-skill), [Import dashboard](https://docs.omni.co/api/content-migration/import-dashboard)

## Design decisions

1. Extend the existing source graph, dictionary, review and deployment contracts. Add bounded adapters and validators rather than a second orchestration system.
2. Preserve observed behavior, hypothesized intent and approved business meaning separately. A matching SaaS report is a comparison baseline, not proof of the correct business definition.
3. Keep framework, warehouse, semantic engine and delivery scope independent. Framework selection never establishes native warehouse or security qualification.
4. Use machine checks for supported syntax and coverage; use independent analysts and SMEs for interpretation. Prompt instructions alone cannot satisfy gates.
5. Keep offline review useful. Missing live access yields a reviewable candidate with native checks pending, never an invented success.
6. Require separate authorization for destination writes and production promotion. A reviewed model does not authorize new data disclosures, policy changes or dashboard publication.

## Work packages and implementation order

### 1. Scope, evidence states and containment

**Owner role:** orchestrator engineer. **Closes:** G04, G10. **Depends on:** none.

Extend guided intake to record model-only, model-plus-semantic or full-dashboard scope; selected source/target, environment, delivery audience, available exports, approved AI execution boundary, catalogue authority, security reviewer and business reviewer. Reuse prior answers. Missing SMEs remain unresolved rather than assigned by inference.

Define versioned evidence lanes for source coverage, classification, input egress, YAML, Omni static checks, native model validation, warehouse execution, data parity, dashboard creation/behavior, access, AI context, output disclosure and business acceptance. Each lane records `passed`, `failed`, `pending`, `unsupported`, `not_applicable` or `stale`, with scope and evidence. A missing check is never an implicit pass; not-applicable requires an explicit scope basis.

For source inputs containing unknown or restricted content, permit local discovery but hold external agent submission and broad sharing pending the selected handling policy. Add truthful capability wording to README/how-to guidance immediately with this change.

**Acceptance:** semantic-only scope does not require a dashboard; full migration cannot be complete with only a topic. Contradictory, missing or stale evidence cannot produce a ready status. Old packages remain readable but cannot satisfy new lanes without new evidence. Repeating intake preserves recorded selections.

### 2. Classification, lineage and disclosure controls

**Owner role:** privacy/security engineer with data steward review. **Closes:** G06, G07, G08. **Depends on:** 1.

Extend the dictionary through an explicit version migration. Preserve the existing sensitivity level and add multiple data categories, subtypes where required, origin/evidence, review state, handling policy and derived-column lineage. PII, PCI and PHI can overlap. PHI applicability and de-identification cannot be determined from a name match alone. Preserve UNKNOWN explicitly.

Propagate classifications conservatively through joins, aliases, copies, expressions, free text, nested fields and materializations. Hashing, surrogate keys, masking and aggregation do not automatically remove sensitivity. Downgrades require a recorded reviewer decision and supporting tests; unresolved lineage stays unresolved.

Introduce a shared local inspection/policy module before source text is sent to agents and before artifacts leave the approved environment. Apply it to comments, literals, sample rows, workbook exports, SQL, YAML, dictionaries, AI context, logs, temporary files, backups, HTML payloads and ZIP members. Default to metadata-only or synthetic samples. Keep originals in their approved location; do not silently rewrite source meaning. Unsupported encodings/containers and scanner failures block disclosure or require an explicitly reviewed narrower route.

Define allowed temporary storage, restricted access, approved retention and crash-path cleanup/recovery before processing. Cleanup may remove only run-owned working copies, never original evidence. Do not persist unapproved sensitive copies or raw provider/parser diagnostics during failures. Retention periods are policy inputs, not invented defaults presented as customer requirements.

Use pattern checks and optional approved DLP integration as detection signals, not a universal privacy guarantee. No match means not detected, never automatically PUBLIC or safe. Findings contain artifact/field IDs and rule IDs, not matched raw values, nearby snippets, raw parser exceptions, reversible encodings or hashes of individual low-entropy sensitive values. Credentials and sensitive authentication data must not enter prompts, fixtures or ordinary diagnostics. Scan decoded embedded content as well as visible HTML. Bound archive size/depth and reject unsafe paths.

Enforce destination-specific allowlists for metadata descriptions, field names, sample values and AI context. Close the comments-only bypass: metadata mode cannot skip sensitivity/disclosure review. Unknown or restricted resources may remain in a private candidate under approved handling, but cannot be labeled safe for unrestricted export.

Portable libraries protect only the inputs they control. Qualify a launcher/integration boundary for each supported host, with specialist access limited to approved projections through scoped tool/filesystem permissions. Demonstrate that the specialist cannot bypass that boundary to read originals. Direct host reads outside it must be disclosed as unenforced, never presented as protected by a skill prompt. An unenforced host may receive only independently pre-sanitized inputs or approved non-sensitive metadata; protected-data automation is blocked on that host.

**Acceptance:** synthetic PII/PCI/PHI and credential canaries never reach denied prompt/output paths, including decoded HTML and ZIP members. Positive controls allow approved metadata. Tests cover unknown classification, multi-category fields, derivative propagation, comments-only mode, scanner outage, false positives, nested containers, bypass attempts and no raw values in errors. Crash/retry tests verify storage permissions, retention and cleanup without deleting original evidence. Record false-negative limitations. This step does not claim compliance certification.

### 3. Looker JSON intake and source completeness

**Owner role:** source adapter engineer. **Closes:** G01. **Depends on:** 1–2.

Add bounded, versioned Looker API export recognition and a deterministic parser. Preserve source IDs and paths, dashboard/tile/filter/query IDs, query and Look references, fields, calculations, pivots, sorts, limits, filter-listen wiring, text, visualization settings and layout. Inventory both data and text tiles.

Define a canonical dashboard contract shared with later source adapters. Require export provenance/version, pagination completeness and referenced LookML/query dependencies to be reconciled independently against the intake inventory. Handle missing/truncated exports, duplicate/conflicting IDs, merged queries, dynamic fields and unsupported visualization structures explicitly. Never execute source code or follow embedded URLs automatically. Treat source text as data, including prompt-like instructions.

Capture source-side expected IDs/counts, capture time/revision and pagination evidence, or an explicit operator completeness record with its limits. Comparing two inventories derived from the same export is not independent completeness evidence. Without a trustworthy denominator, mark completeness unknown; operator-declared scope remains distinguishable from source-observed coverage.

**Acceptance:** supported standalone JSON routes correctly without a filename hint. Generic JSON does not become Looker by accident. Missing dependencies and unsupported constructs produce field/tile-specific gaps. Removing any expected source tile or filter causes coverage failure. A structurally valid first page of an incomplete export cannot pass completeness. Repeated parsing gives the same contract and hashes. Read-only extraction leaves the source unchanged.

### 4. Omni generation contract and static checker

**Owner role:** semantic engineer; independent QA owns expected results. **Closes:** G02, part of G03. **Depends on:** 1–3.

Create a reusable Omni contract checker and connect it to generation and `lint_delivery.py`. Pin the supported contract and documentation provenance. Check duplicate keys, object shape, parameter placement/types, supported enums, SQL/reference resolution, dependency cycles, topic joins, temporal references, measures and physical namespace bindings. Emit exact artifact/field diagnostics without exposing sensitive expressions.

Generate from the accepted model/placement version and verified catalogue mapping. Distinguish physical fields, derived fields and inherited overrides. Resolve BigQuery project/dataset independently from Snowflake database/schema; preserve quoted identifier case and selected environment. Validate documented custom formats instead of maintaining an overly narrow name allowlist. Unknown constructs become unsupported pending review/native qualification, not silently dropped.

**Acceptance:** unsupported timeframe, invalid week-start, unresolved physical bindings, broken references, invalid YAML and cycles fail. Valid custom formats, inherited definitions, verified default catalog and block-list timeframe references pass their applicable checks. Tests use multiple arbitrary domains, not fixture-specific names. SQL lint remains separate from Omni contract checking.

### 5. Native Omni validation and bounded repair loop

**Owner role:** integration engineer; independent QA verifies receipts. **Closes:** G05, G10. **Depends on:** 4.

Add an authenticated native validation adapter for an explicitly selected model/environment and authorized development branch. Capture the candidate's complete file inventory, base-model/schema dependencies, connection context, branch identity and validation response. Prove the remote candidate matches the reviewed artifacts before accepting the result; hashes alone do not authenticate a run.

Before any development write or query, check the existing destination audience and access policy. Until package 8 qualifies protected-data enforcement, use synthetic data in an isolated destination or a separately verified pre-existing protected environment; never broaden access to enable the test. Later policy work does not retroactively authorize an earlier exposure.

Parse response issues, distinguish errors from warnings, and apply an explicit warning policy. Protect against wrong branch/instance, changed remote content, expired evidence, partial writes, authorization failure, rate limiting and timeouts. Transport code must validate TLS and redact credentials. Retrying reads is distinct from retrying writes; reconcile ambiguous write outcomes before reuse.

Run a bounded generate → static check → authorized branch update → native validation → repair loop. Preserve diagnostics and diff history safely. Repairs that alter meaning or approved scope return to review. A retry limit ends with actionable unresolved errors rather than forced success. Do not automatically delete content based on suggested native fixes.

**Acceptance:** HTTP 200 with an error fails; missing credentials yields pending; wrong target, stale receipts and modified artifacts fail. Offline simulated responses are visibly labeled synthetic. Live qualification requires a real receipt for the exact candidate and native query compilation/execution remains a separate lane. Branch cleanup only affects resources created for this run and requires ownership verification.

### 6. Dashboard construction and reversible delivery

**Owner role:** dashboard engineer. **Closes:** G04, dashboard portion of G05. **Depends on:** 3–5.

Build dashboard candidates from the canonical contract, including data/text tiles, filter wiring, query calculations, formatting and layout. Assess documented APIs and official migration tooling before implementing a new writer. Qualify selected endpoint/authentication requirements and release stage; do not assume all import routes are stable or draft-only.

Generate a complete build specification offline. For an authorized live route, use an isolated reviewed destination, preserve existing drafts/content, track created IDs, read back the result and verify exact tile/filter coverage. If an endpoint publishes immediately, treat it as publication requiring the corresponding authorization and access controls. Never use destructive draft-clearing as a default.

Persist operation identity and reconcile uncertain outcomes to prevent duplicate dashboards. Snapshot affected state and provide a bounded rollback plan. Where a needed feature lacks qualified automation, retain a manual step and explicit incomplete status.

**Acceptance:** the neutral reported-shape fixture accounts for 11 tiles and 3 filters, including 8 data tiles; these counts are a regression case, not a universal requirement. Omitted tiles, changed filter wiring, missing text and duplicate retries are caught. Topic/build-spec existence cannot satisfy dashboard-created or dashboard-tested evidence. Unauthorized writes are rejected.

### 7. Independent data, dashboard and AI-context validation

**Owner role:** validation analyst; SME decides business meaning. **Closes:** G03, behavioral portion of G05. **Depends on:** 3–6.

Freeze expected behavior independently from generated code. Reconcile source results, warehouse results and actual Omni modeled queries at matched data snapshot, timezone, filter parameters and persona. Aggregate equality alone is insufficient: include grain/uniqueness, join fanout, orphan keys, NULL behavior, duplicated records and tenant isolation. Record numeric tolerances and explanations before evaluating differences.

Test every selected tile and important filter combination, date-window boundaries/inclusion of today, daylight-saving/calendar edges, sorting, pivots, table calculations, zero denominators and row-limit truncation. Compare rendered layout and interactions as well as query results. Do not silently widen date filters or limits to make tests agree.

Keep the reported subtraction-based comparison distinct from a similarly named warehouse measure until an SME accepts equivalence or a correction. Preserve intersecting dashboard/tile filters as observed; flag misleading labels. Refresh statements, contacts and links require owner verification. Treat partition/performance optimization as a separate change with its own benchmarks and parity tests.

Generate AI context from approved definitions, gold-field mappings and explicit unresolved decisions. Test representative questions, ambiguous definitions and prohibited sensitive-field requests against the selected persona; do not promote inferred meaning to business authority.

**Acceptance:** each data tile has a source/target comparison or a visible gap. Counterexamples intentionally change date boundaries, NULLs, fanout, populations, limit/sort and tenant identity; the relevant test fails. Test fixtures include matching day totals with differing tile behavior. Live data stays within its approved boundary; exports contain only permitted summaries. AI context cannot assert unresolved definitions as approved.

### 8. Warehouse and Omni access enforcement

**Owner role:** security/platform engineer; authorized security reviewer approves policy. **Closes:** G09 and access portion of G05. **Depends on:** 2, 5–7.

Separate informational classification from effective protection. Define a security policy contract with exact resources, principals/personas, allowed actions, row/column restrictions, masking behavior, metadata visibility, inheritance, intended destination and readback evidence. Compare existing policy before proposing a change. Do not weaken existing controls or treat a semantic field's hidden flag as an access boundary.

Map warehouse permissions and Omni data access separately from folder/document audience, download/share paths and relevant cache/drill behavior. Use positive and negative persona tests, including absent attributes and unexpected group membership. Authorizations and qualified platform support must precede policy writes or publication.

Apply this qualification matrix; entries describe required engineering work, not confirmed platform feature parity:

| Route | Required qualification |
|---|---|
| dbt | Keep metadata projection separate from underlying warehouse policy execution; preserve existing hook restrictions and explicit release phases |
| Coalesce | Verify native node/schema integration and runtime before claiming projection or policy deployment; exported SQL alone is insufficient |
| Snowflake | Inspect exact object/tag/policy bindings and roles; verify effective masking/row access in the target account |
| Databricks | Bind workspace/catalog/runtime and governance scope; verify applicable grants and row/column control behavior |
| BigQuery | Bind data project/dataset/location and identity; distinguish descriptions/labels from enforceable access and masking policies |
| Redshift | Bind cluster/workgroup/database and identity; verify qualified row/column/masking mechanisms independently of resource tags |
| ClickHouse | Bind server version, engine and cluster/replica scope; verify supported privilege and row/column restrictions |
| MotherDuck | Verify remote identity, sharing and supported controls directly; local DuckDB results do not establish remote enforcement |

For each pairing record `documented`, `implemented`, `locally_tested`, `live_qualified` and explicit unsupported functions. Check official platform documentation during implementation. If a requested control has no qualified route, block protected-data deployment and provide an actionable security handoff; never silently reduce protection.

**Acceptance:** permitted personas can perform only approved actions; denied personas cannot obtain protected data through model queries, dashboards, drills or scoped exports. Newly introduced fields do not evade inherited handling. Policy/tag changes invalidate affected access receipts. Native readback and effective tests agree with the approved policy. Each platform remains unqualified until its own evidence exists.

### 9. Packaging, deployment gates and release qualification

**Owner role:** release engineer; independent reviewer signs off. **Closes:** G04, G08, G10; integrates all prior packages. **Depends on:** 1–8.

Update `START_HERE.html`, ZIP manifests and review summaries to show scope, generated deliverables, pending decisions, evidence lanes and exact next actions. Keep a reviewer-friendly route and optional technical evidence without assuming either is safe merely because of its folder name.

Scan the exact final bytes, including embedded assets and archived members. A content change invalidates the corresponding scan and downstream evidence. Prevent a time-of-check/time-of-use substitution by binding release inputs to the frozen manifest and rechecking immediately before submission. Keep diagnostic logs and originals out of share packages unless separately permitted.

Integrate required lanes into the existing deployment coordinator. User review/iteration and explicit destination authorization remain separate from passing automated checks. Do not loosen existing deployment/metadata blockers to complete the demonstration. Policies, model, dashboard and warehouse code need dependency ordering, readback and a recovery plan; partial completion must be reported accurately.

Add contract version migration for legacy dictionaries, review packages and evidence. Preserve old receipts as historical, never relabel them as satisfying stronger gates. Update SKILL.md, orchestration/source contracts, host instructions, README, HOW_TO and CAPABILITIES with exact supported paths and limitations.

**Acceptance:** unvalidated candidate packages are clearly labeled and cannot deploy as accepted migrations. Failed privacy scans prevent sharing. Offline/skipped/unsupported native checks cannot appear passed. Changed source/candidate/target/policy invalidates affected approval. Existing supported flows pass regression tests without acquiring unsupported claims.

## Subagent operating contract

The orchestrator must dispatch or explicitly record unavailable roles; emitting prompts is not proof that a specialist ran. Each role receives only approved inputs and returns structured evidence bound to the same run, scope and artifact version.

| Role | Owns | Cannot self-certify |
|---|---|---|
| Source specialist | Parsed source inventory, behavior and unresolved dependencies | Business approval or target success |
| Warehouse engineer | Model, SQL, lineage, dictionary and ERDs | Independent data accuracy |
| Omni model engineer | Native model files and source/target field mappings | Native acceptance without an observed validator result |
| Dashboard engineer | Tile/filter/layout mapping and authorized construction | Parity based solely on successful creation |
| Validation analyst | Independent comparisons and negative controls | SME meaning or security authorization |
| Security reviewer | Classification, disclosure policy and persona evidence | Compliance certification from a scanner |
| Orchestrator/release reviewer | Coverage, evidence validity, decisions and authorized promotion | Fabricated role execution or missing approvals |

Roles may run sequentially to reduce cost. The implementation author cannot be the sole source of the expected results or business approval. Conflicts remain attached to affected fields/tiles; unrelated work may continue.

## Qualification and release gates

1. **Local engineering gate:** new unit/contract/negative tests pass; supported legacy exercises still pass; generated documentation and model inventories agree; no secrets/customer data in public fixtures.
2. **Blind generation gate:** a fresh agent receives sanitized exports, catalogue and approved intake only. It generates new artifacts rather than replaying a checked-in answer. Independent QA evaluates both success and expected blocking cases. Repeat across distinct domains and record host/model/tool versions.
3. **Native pilot gate:** authorized BigQuery + Omni development pilot covers the reported failure family; a dbt + Snowflake pilot covers the existing primary flow. Capture exact native receipts, tile behavior, effective access and approved disclosure. Additional warehouses/frameworks retain their own qualification status.
4. **Business gate:** SMEs approve definitions and intentional behavior changes, including misleading labels, date interactions and freshness text. An unavailable SME leaves those items open.
5. **Release gate:** independent review, CI, dependency/secret checks, migration/backward-compatibility checks, sanitized evidence, recovery instructions and destination-specific approval. Initial repaired release claims only the paths that passed their gates.

No universal percentage of accuracy or production-readiness claim is derived from test counts. Stop progression on failed local acceptance criteria, document the failing case, repair and rerun the affected checks before moving forward. Local implementation completion permits the next package's engineering work; it does not complete a pending native gate. When native credentials are unavailable, record local results and native validation separately, preserve the pending state, and block corresponding deployment claims.

## Prerequisites and decisions

- General repairs can begin with sanitized fixtures. Exact customer reproduction additionally needs the original export, pre-fix generated files and execution/version context, handled within the approved boundary.
- Live qualification needs scoped source/warehouse/Omni access, a reviewed development destination and personas. Credentials must remain in approved secret storage, not the plan or prompts.
- Before live dashboard construction, select a qualified API route and explicitly accept any Beta dependency. A manual build specification remains an honest fallback, with deployment pending.
- Before protected-data deployment, the customer's authorized owner must approve handling, disclosure destinations and effective-access expectations. Missing review is not permission to assume a policy.
- Performance or partition changes remain independent of parity repairs; require separate approval and benchmark evidence.
- Named owners, delivery dates and effort estimates are unassigned until implementation is scoped. No production writes, repository push or merge is authorized by this planning document.

## Execution ledger

For each package, append the implementation commit, focused tests, independent review, native evidence references where applicable, unresolved gaps and actual completion state. Do not mark an item complete because a later stage was planned.

| Package | Implementation | Local acceptance | Live qualification | State |
|---|---|---|---|---|
| 1. Scope/evidence | Shared evaluator and explicit guided intake implemented | 6 assurance tests and 37 guided workflow tests passed | No native acceptance claimed | Local foundation validated; release integration in package 9 |
| 2. Privacy/disclosure | Classification migration, lineage, staging, metadata and exact-byte package scans implemented | Scanner 19, privacy 15, staging 4, disclosure 5 tests passed; independent bypass retest passed; metadata 93 tests including six-dialect lint passed | Protected host isolation and native policy enforcement unqualified | Locally validated; detectors are bounded, not universal DLP |
| 3. Looker intake | Deterministic API4 extraction and planner/result-verifier integration implemented | 45 specialist regressions, 26 parser tests and 17 independent cases passed; two QA defects repaired | Independent source completeness and native behavior pending | Locally validated |
| 4. Omni static contract | Version-pinned generator, context-aware checker and delivery lint integration implemented | 37 checker tests including 22 independent cases, 14 generator tests and 38 lint tests (3 new Omni integration cases) passed | Native acceptance remains separate | Locally validated |
| 5. Native validation | TLS development adapter, signed preflight, snapshots, recovery journal, separate query modes and bounded reviewed repairs implemented | 28 cases passed, including 22 independent probes; direct input scan and timeout/replay defects repaired | No tenant calls; native qualification pending | Locally validated; operating reference included |
| 6. Dashboard construction | Complete source work list, reviewed native mapping and authorized existing-document branch-draft writer implemented | 39 cases passed, including 25 independent tests and the neutral 11-tile/3-filter shape | Draft API/UI pilot pending; new-document publication and Beta import unqualified | Locally validated; no publication or destructive clearing |
| 7. Independent parity/AI | Source/warehouse/Omni population comparator and privacy-aware gold-field AI context with structured evaluation implemented | 28 parity and 36 AI context tests passed, including independent probes; structural import, dependency and layer gaps repaired | Live AI answers, dashboard behavior, native result provenance and SME approval pending | Locally validated |
| 8. Access enforcement | Exact access-state, nonweakening, persona/readback contracts and shared six-platform capability matrix implemented | 29 security and 32 platform tests passed; independent metadata-visibility gap repaired | Native provisioning remains unsupported; effective access requires independent authentication | Locally validated |
| 9. Packaging/release | Signed evidence gates, exact-byte coordinator checks, guided review integration and operator documentation implemented | 31 signed-release/integration cases, new UI behavior checks and final 1,474-test suite passed with no skips; two fresh domains passed six independent local scenarios; dependency audit and secret scan clear | Native pilots, qualified access collectors, SME acceptance and remote CI pending; pixel-level visual inspection unverified | Locally validated; no production acceptance or release authorization |

The fresh generation exercise also repaired ordinary YAML list handling in the dbt documentation helper, with two additional regression cases. It correctly preserves the subsequent approval blocker for proposed metadata. All nine packages are included in the local implementation revision containing this ledger; focused evidence and remaining gaps are retained in the [qualification report](../../validation/omni-privacy-repair/README.md). No historical receipt was relabeled as satisfying the new gates.
