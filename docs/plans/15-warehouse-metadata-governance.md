# Warehouse metadata as a deployment deliverable

Status: local implementation and synthetic validation on `atx/warehouse-metadata`, based on `4024569`; not live-qualified. Requirements reviewed and implementation developed 2026-09-30. See the [implementation evidence and remaining gates](../../validation/warehouse-metadata-governance/README.md).

The implemented scope includes dictionary v2, dbt YAML projection, native metadata generation/readback contracts for all six warehouses, linked release simulations, Metadata review/ZIP integration, downstream context and optional new-Snowflake naming previews. Automatic live metadata dispatch is blocked pending an authenticated native drift collector. Governance provisioning, native Coalesce node projection, non-Snowflake renaming and live provider/consumer qualification remain explicit follow-up work; the original acceptance requirements below are retained rather than silently marked complete.

## Outcome and release boundary

Every generated data model delivery includes a versioned metadata contract alongside its code, ERDs, data dictionary, and layer documentation. For selected, supported deployment routes, approved relation and column descriptions become native warehouse metadata as part of the release. Governance tags and authorized RAW comments have explicit deployment phases. Completion requires independently reading the warehouse and comparing it with the approved contract.

The first live qualification target is **dbt Core + Snowflake**, with framework-independent contracts for Coalesce, native SQL, Databricks, BigQuery, Redshift, ClickHouse, and MotherDuck. No live qualification has occurred. Generating their metadata plans does not make those execution routes qualified. Existing naming is preserved during refactoring; new-model naming is a separate selectable convention.

The Cortex blind test motivates this plan. The submitted account reports 27 models, 1,282 model columns, 497 RAW columns, 6,493 tag associations per environment, and zero DEV/PROD differences. Those are **user-reported results**, not receipts independently verified in this review. They are a scale scenario, not universal coverage targets. Direct assignments, inherited associations, and executed statements must be counted separately.

### What changes from the submitted requirements

| Original proposal | Enhanced requirement |
|---|---|
| Documentation default at project root | Valid dbt model configuration, resolved per selected resource; identify overrides and adapter limitations. |
| Dictionary and manifest prove coverage | Reconcile declared documentation with independently enumerated physical columns. |
| Unknown sensitivity becomes INTERNAL | Preserve UNKNOWN and apply a separately approved handling policy. |
| RAW description can come from a same-named column | Require exact source identity and source-level meaning; suggestions cannot become automatic writes. |
| A macro hash permits a tag post-hook | Retain the hook ban; introduce bounded metadata operations within an authorized release. |
| SQL sidecars run with a dbt plan | Add explicit phase orchestration; current dbt and native SQL destinations are distinct. |
| A tag is only informational | Inspect existing policy bindings and propagation; tag changes can affect access. |
| Literal DEV/PROD equality proves correctness | Check each environment against expectations first, then compare normalized logical identities. |
| One naming convention closes the gap | Deliver metadata without renaming; qualify optional naming independently. |
| Snowflake tags generalized to other platforms | Preserve each platform's capabilities, limitations, security semantics, and release stage. |

## Repository gaps at the requirements-review baseline

This table records the pre-implementation baseline at `4024569`; linked files now include the changes. This work did not run customer SQL or verify the reported Cortex deployment.

| Gap | Current evidence | Consequence |
|---|---|---|
| Documentation is packaged but not managed as warehouse state | [documentation contract](../../skills/data-model-accelerator/references/model-documentation.md), [documentation checker](../../skills/data-model-accelerator/scripts/verify_model_documentation.py) | The checker compares supplied inventory and dictionary; it does not establish native comments or discover columns omitted from both. |
| `persist_docs` is not a consistent generation default | [Power BI target example](../../skills/data-model-accelerator/examples/powerbi-omni-e2e/target/dbt/dbt_project.yml), [rental candidate](../../skills/data-model-accelerator/examples/dbt-rental-trial/candidate/dbt_project.yml) | Some examples enable persistence; the rental candidate omits it. |
| Classification and key roles are prose | `COLUMN_FIELDS` and version-1 handling in the documentation checker | No structured sensitivity policy, multi-role key contract, or metadata deployment mapping. |
| Hooks are deliberately rejected | [dbt runner](../../skills/data-model-accelerator/scripts/run_dbt_project.py), [engineering reference](../../skills/data-model-accelerator/references/analytics-engineering.md) | This is a safety boundary to preserve, not simply a missing allowlist entry. |
| Runtime qualification is narrower than the draft | dbt runner and [dbt evidence verifier](../../skills/data-model-accelerator/scripts/verify_dbt_evidence.py) | Current runner pins Core 1.12.4 / manifest v12 and accepts DuckDB or Snowflake; it does not qualify Fusion. |
| A release selects one framework/destination | [deployment coordinator](../../skills/data-model-accelerator/scripts/deployment_workflow.py), [adapters](../../skills/data-model-accelerator/scripts/deployment_adapters.py) | Snowflake SQL requires the native SQL route; the dbt adapter triggers a configured job. Sidecar execution needs new orchestration. |
| SQL artifacts are submitted as single statements | Snowflake adapter uses `MULTI_STATEMENT_COUNT=1` | A multi-statement provisioning file is not an executable unit in the existing runner. |
| Native verification checks shape, not metadata | [physical schema verifier](../../skills/data-model-accelerator/scripts/verify_physical_schema.py) | Comments, tags, visibility, and metadata parity require additional evidence. |
| Platform metadata is discovery-oriented | [platform matrix](../../skills/data-model-accelerator/scripts/platform_matrix.py) | Catalogue query recipes are not metadata-write qualification. |

## Requirements

### R-1 Discovery, ownership, and delivery selection

1. Extend guided intake before dependent generation. Reuse recorded answers; ask only for missing choices: source and target platforms, framework/runtime versions, selected models and environments, metadata owner/reviewer, existing catalogue/glossary, classification taxonomy, tag namespace, RAW ownership, and naming preference.
2. Present descriptions as a default delivery component. Offer governed tags, RAW comment updates, environment comparison, and downstream semantic/AI context as explicit scope choices. Recorded exceptions must identify affected resources, reason, reviewer decision, and follow-up; they must not appear as passed coverage.
3. Distinguish ownership of generated descriptions, existing human-authored metadata, governance definitions, source objects, and semantic definitions. An absent owner is unresolved, not a fabricated assignment.
4. Discover existing comments, tag definitions/values, applicable policies, and metadata privileges read-only. Reading a catalogue or approving a business definition does not authorize metadata writes.
5. Define one authority per field. A customer's catalogue or curated YAML may remain authoritative. Imported definitions retain source, version/hash, and review status; the agent cannot silently replace them with inferred descriptions.

### R-2 Canonical metadata contract and migration

Evolve the dictionary to version 2 and add a versioned deployment metadata manifest. Keep documentation, lineage, classification, and physical destination separate. Do not force RAW into the existing bronze/silver/gold model inventory; associate a source metadata inventory with the catalogue through stable IDs.

| Contract element | Required behavior |
|---|---|
| Identity | Stable model/source/column IDs; dbt unique ID or Coalesce node ID when applicable; ordered namespace components and quoting flags; explicit environment-to-physical mapping. Names alone are not cross-environment identity. |
| Meaning | Model description and grain; column description, type, nullability, units/currency/timezone when applicable, transformation, validation references, and exact lineage references. Preserve technical facts separately from business interpretation. |
| Provenance | Evidence references and content hashes; origin `source_metadata`, `reviewer`, `inferred`, or `generated`; review status `proposed`, `approved`, or `unresolved`; actual reviewer/decision references only when supplied. |
| Sensitivity | `UNKNOWN`, `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, or `RESTRICTED`, with evidence and review status. Keep classification evidence text. Any handling policy for UNKNOWN is a separate field and decision, not a claim that the data is INTERNAL. |
| Keys | `key_roles` array, retaining readable `key_role` text during migration; roles include primary, surrogate primary, foreign, surrogate foreign, crosswalk, and grain component. `NONE` means reviewed absence; `UNKNOWN` means unresolved. Neither can accompany other roles. Record composite-key groups/order and referenced entity/columns separately. |
| Modeling | Layer, resource type, model role, and materialization are orthogonal. Roles cover staging, intermediate, dimension, fact, bridge, aggregate, snapshot, and explicitly unresolved cases. A view may be a fact; a bronze object need not be copied physically. |
| Sources | Preserve a list of source-system IDs. `CONFORMED` must not replace that list; integration/conformance is a separate attribute. |
| Lifecycle | Ownership reference, change/version identity, status, deprecation/replacement references where known, and links to ERD, layer docs, runbook, and semantic consumers. Do not invent retention or freshness commitments. |

Requirements:

- Validate enums, duplicates, references, forbidden combinations, and completeness with a machine-readable schema plus semantic checks. Update all producers, consumers, fixtures, and review-package associations together.
- Version dictionary, model inventory, metadata plan, observation, and acceptance contracts independently. The current shared documentation reader pins both dictionary and inventory to version 1; separate that handling rather than accidentally upgrading every artifact. Normalize the rental qualification dictionary's alternate `id`/`dbt_id`/`type`/`nullable` shape explicitly in `run_refactor_qualification.py`.
- Supply an explicit version-1 migration command/report. Preserve original text and hashes; mark unmappable values unresolved. Do not infer classification or key roles solely from names. Migrate a copy and regenerate derived artifacts for review.
- Old receipts remain historical evidence. They cannot satisfy new metadata release gates without new qualification. Do not rewrite archived evidence to appear current.
- Keep legacy in-flight releases recoverable under their original versioned contract, without adding metadata claims retroactively. Applying the new feature requires a new reviewed plan; do not mutate an active signed plan in place.
- Preserve full descriptions and lineage in the dictionary even when a platform cannot represent them. Native metadata is a projection, not the only copy.
- Record logical key intent, observed validation results, and warehouse enforcement separately. A key-role tag does not create or prove a primary/foreign-key constraint.

### R-3 Deterministic dbt documentation generation

Add `generate_dbt_docs_yml.py` with preview and apply modes, plus a generation manifest recording owned fields and content hashes.

For a new project, emit valid resource configuration (illustrative project name):

```yaml
name: accelerator_project
version: '1.0.0'
config-version: 2
models:
  accelerator_project:
    +persist_docs:
      relation: true
      columns: true
```

`persist_docs` belongs under resource configuration; it is not a standalone project-root key. dbt documents adapter/object limitations and does not implement this setting for sources. Selected seeds and snapshots need their own qualified configuration. See [dbt persistence](https://docs.getdbt.com/reference/resource-configs/persist_docs).

1. Project approved model and column descriptions into the existing YAML location. Create `models/<layer>/_<layer>.yml` only where no existing patch owns that node; never produce duplicate model patches. Include model grain and meaningful units without repeatedly appending them on regeneration.
2. Store accelerator-owned metadata in a namespaced `config.meta.dma` object. Write current `config.meta` syntax, but qualify against pinned engine/adapter versions. The reported Fusion error is a compatibility test case, not evidence that the current Core runner supports Fusion or that every legacy top-level `meta` must be rejected. See [dbt meta](https://docs.getdbt.com/reference/resource-configs/meta).
3. Use a field-aware, three-way merge against the previous generated baseline. Preserve tests, constraints, aliases, Jinja/doc references, unknown keys, comments, anchors, quoting, and human edits. Where safe round-trip preservation is unavailable, produce a patch for review rather than rewriting the file. Conflicting authoritative definitions block apply.
4. Stable inputs yield byte-identical output. Preserve existing file/order conventions; sort newly generated owned records deterministically. A second apply produces no changes.
5. Resolve effective persistence settings per selected node, including folder and node overrides. Preserve existing overrides but report exceptions; one declaration elsewhere in the project does not prove all layers persist documentation.
6. Document every selected logical model, including ephemeral models. Only materialized resources enter native comment coverage; disabled/unselected/package nodes need explicit inventory treatment. Unsupported object types are reported, not silently skipped.
7. Test quoted/mixed-case identifiers and supported table/view/incremental materializations on the selected adapter. Rendering a docs file or compiling a manifest is not proof of warehouse persistence.

### R-4 Independent scope and completeness

1. Before deployment, reconcile the dictionary and selected framework nodes with compiled projection evidence and the reviewed catalogue. After build, enumerate actual physical relations and columns independently. A manifest's declared columns alone cannot establish the full output schema.
2. Compare both directions: missing physical objects/columns, undocumented physical columns, dictionary-only columns, mismatched identities/types, and duplicate mappings. A column omitted from both YAML and dictionary must still be detected when present in the warehouse.
3. Bind inventory to the exact selection, build ID, code/manifest hashes, destination, and observation time. Expansion from `SELECT *`, incremental schema changes, quoted names, nested field paths, and renamed/versioned models require explicit handling.
4. Evaluate description quality separately from presence: empty/placeholder values fail; tautological or unsubstantiated business definitions require review. Nonempty prose is not proof of correctness. Do not reject legitimate prose merely because it contains a substring such as “none.”
5. Publish denominators: selected, expected physical, observed, documented, approved, excluded, and unverified. Zero visible rows, denied access, an incomplete catalogue, or zero selected models cannot yield 100% coverage.
6. Reuse `verify_engagement.physical_denominator` and `verify_physical_schema.reconcile` with an explicit model-plus-source union. The current physical denominator includes sources, while the existing reconciliation consumes a model inventory; splitting RAW documentation must not silently omit those sources or create false missing-object results. Track source/model identity and write authority even when both refer to one physical object.
7. Distinguish documentation scope from execution scope. The current dbt runner is qualified for its full-root build contract, not arbitrary partial selections. Retain that contract in the first implementation, documenting all resources it actually builds; partial execution requires separately qualified selection/dependency handling and complete build evidence. A smaller documentation selection cannot conceal additional build writes.

### R-5 Snowflake tag definitions and application

1. Default to reviewed customer-owned tags in a configurable governance namespace. Check edition/feature availability and discover compatible definitions; avoid a new domain-prefixed taxonomy for every model when shared tags plus a `DOMAIN` value suffice. Never create or alter governance resources during discovery.
2. Propose object tags for layer, model role, domain, source-system reference, grain reference, and sensitivity; column tags for key roles and sensitivity where required by the approved mapping. Keep long grain prose in comments/dictionary, using a stable `GRAIN_ID` if needed. Tag serialization, limits, allowed values, and multi-source/key-role mappings must be explicit and reversible. No silent truncation.
3. Sensitivity rollup must preserve unknowns and known higher classifications. A table cannot receive a lower sensitivity than a known restricted column merely through an override. Declassification requires changed evidence and a separately reviewed policy decision. No classification state claims that masking is enforced.
4. Read existing tag policy bindings and propagation configuration before planning any tag update. Tags can activate existing masking policies; informational tagging is therefore qualified only when its security effects are known. Bound policies or unknown visibility require the appropriate security review before a write. Do not alter policies, propagation, or security grants as a side effect. See [tag-based masking](https://docs.snowflake.com/en/user-guide/tag-based-masking-policies).
5. Provisioning and application use separate declared capabilities. Generate a minimal privilege plan for the exact namespace, objects, tags, role, and environment. Prefer dedicated governance authority for definition/grant changes; the model runner receives no automatic privilege escalation. `CREATE ... IF NOT EXISTS` does not reconcile an incompatible existing definition; detect drift and require a reviewed change.
6. For custom tags, qualify per-tag grants such as `GRANT APPLY ON TAG`; do not synthesize `GRANT APPLY ON ALL TAGS IN SCHEMA`. Check the full privilege requirements for the chosen ownership model. Existing customer grants remain untouched unless separately selected and authorized.
7. **Optional Preview path:** `SNOWFLAKE.TAGS.SENSITIVITY` is officially documented under **Preview Feature — Open**. It differs from `SNOWFLAKE.CORE.PRIVACY_CATEGORY`; its allowed values are administratively changeable. Require explicit Preview acceptance, live discovery, and the documented application-role path, not custom-tag grant syntax. Do not create tags in `SNOWFLAKE.TAGS`. See [Snowflake-provided tags](https://docs.snowflake.com/en/user-guide/object-tagging/snowflake-provided-tags).
8. Optimize within verified platform limits: avoid redundant inherited assignments, batch eligible operations, bound payload sizes/concurrency, and record logical assignments separately from API requests. Snowflake limits tag values to 256 characters; validate before emission. See [tag values](https://docs.snowflake.com/en/user-guide/object-tagging/work).
9. Keep the existing generic hook rejection. The initial implementation uses the metadata deployment phase in R-7. A matching macro hash does not bind helper macros, dispatch, variables, rendered SQL, privileges, or destinations. Any future hook support needs its own complete execution qualification.

### R-6 RAW/source documentation without invented meaning

1. Always include selected sources in the documentation contract and generated `sources.yml`. Writing source comments is separately selectable and separately authorized; dbt documentation persistence does not perform it.
2. Prefer approved source-owner definitions attached to the exact platform/account/database/schema/table/column identity. Otherwise produce a reviewed source-specific definition from evidence. Reusing a bronze description requires proven direct-pass-through meaning; casting, normalization, filtering, deduplication, and unit conversion may make that description incorrect for RAW.
3. Never auto-resolve from a same-named column in another source table. Cross-table similarities may create review suggestions with evidence, never approved text or runnable writes. Unresolved selected source writes block that phase.
4. Preserve existing source comments unless an approved diff supersedes them. A shared/read-only or connector-managed source remains documented locally; do not modify it without source-owner authorization and a supported lifecycle. Record exclusions and coverage gaps explicitly.
5. Emit typed source-comment operations with exact source bindings, existing-value preconditions, and readback. Use object-appropriate DDL, qualified identifiers, and bounded batches; “one statement per table” is an optimization only when supported and within limits.
6. Preserve the distinction between RAW and bronze when bronze reuses source objects. Such comments still cross the source-write authority boundary. Recreated ingestion objects trigger drift and a newly bound reconciliation plan, not blind recurring writes.

### R-7 Authorized multi-phase release

The release must explicitly coordinate **governance readiness → model build/document persistence → target tags and optional RAW comments → metadata readback → downstream handoff**. Dependencies and each phase's authority are visible before sign-off.

1. Add a versioned parent release contract that binds child plans for dbt and native metadata operations, or an equivalently qualified Git/CI/operator orchestration path. Do not force SQL sidecars through the current dbt adapter or relabel them as model SQL. Preserve current framework/destination checks.
2. Every child binds the parent release, code/dictionary/metadata-plan hashes, policy revision, mode, framework, runtime, selected objects, account, namespace, environment, role, and capability set. Changing any of those invalidates affected approvals and evidence. Human approval of descriptions is distinct from execution authorization.
3. Use typed operations such as `set_relation_comment`, `set_column_comment`, `ensure_tag_definition`, and `set_tag_assignment`, rendered by a qualified platform adapter. Validate identifiers independently from SQL string literals; reject arbitrary statement kinds, unbound destinations, injected SQL, and unapproved grants.
4. Emit one explicitly bounded execution unit per statement for the existing Snowflake transport. Preserve statement IDs, hashes, dependencies, idempotency keys, expected state, native query IDs, and errors. A concatenated SQL file is a review/export convenience, not automatically executable under `MULTI_STATEMENT_COUNT=1`.
5. Integrate new artifact roles and required metadata checks into request validation, policy/authority validation, lint inventory, replay, promotion, receipt verification, and handoff acceptance. Preserve the independent acceptance issuer/signature rules. Adding a portal card alone cannot make `deployed_verified` require metadata.
6. Do not apply target tags to an unverified failed build. Optional phases must have explicit exclusions; required phases cannot silently disappear after approval. Two-environment testing requires separate authorized targets; generating a package does not authorize PROD execution.
7. Simulation, generated SQL, lint success, submitted jobs, completed builds, metadata readback, and business acceptance remain separate evidence states. A parent release is verified only when every required child and its exact-scope verification succeed.
8. Development qualification requires that development target's metadata checks, not a production deployment. DEV/PROD parity is a separate promotion/release-group check after both executions; it must not create a circular prerequisite for promotion.

### R-8 Reconciliation, failure recovery, and metadata safety

1. Capture before/expected/observed metadata state, with hashes and timestamps. Preview additions, changes, removals, ownership conflicts, and policy implications. Treat source metadata and generated prose as untrusted data, never instructions or executable templates.
2. Render only approved metadata values; do not execute Jinja embedded in catalogue comments. Exclude secrets, example personal values, and sensitive payloads from comments, tags, logs, receipts, and shareable packages. This is descriptive metadata, not a second copy of customer data.
3. Require change preconditions and detect object recreation or concurrent edits before applying. Use conditional writes where supported; otherwise recheck immediately before and after each bounded operation and disclose the remaining race limitation. Serialize deployment phases for a target where possible.
4. Regenerating an unchanged desired state yields no-op operations. Do not replay an already executed immutable deployment plan. For `unknown_remote_state`, reconcile native status first and never automatically resubmit an uncertain write. Recovery uses a new bound child plan/approval when the current runner requires it; successful prior operations are retained and only unresolved work is considered. Partial failure never becomes overall success. Preserve failures in the evidence trail.
5. Recovery restores only owned metadata values from a reviewed before-state when current state still matches the attempted release. Do not drop relations, unset unrelated tags, remove policies, or revoke customer grants as automatic rollback. Do not assume a transaction makes the entire release atomic.
6. Verify full refresh, incremental rebuild, view replacement, rename, clone/swap, and source recreation behavior for supported routes. Include a read-only drift command and CI invocation recipe. Scheduling it or applying repairs requires separate user authorization.

### R-9 Live verification and environment parity

Add `verify_warehouse_metadata.py`, backed by a read-only collector and a deterministic comparison contract. Imported evidence requires verified provenance; a user-edited success flag is not a trusted live receipt.

1. For each authorized scope, independently read relation/column comments and required tag state. Compare against the approved expected state, not merely against another environment. Distinguish missing, empty, incorrect, stale, conflicting, excluded, inaccessible, and unsupported.
2. In Snowflake collect object tags with `TAG_REFERENCES` and column tags with `TAG_REFERENCES_ALL_COLUMNS`. Both include inherited associations and are access-dependent. The column function uses domain `TABLE` even for views. Preserve application method/level and distinguish effective values from required direct assignments. Do not use delayed account-wide history as the sole immediate gate. See [object tags](https://docs.snowflake.com/en/sql-reference/functions/tag_references) and [column tags](https://docs.snowflake.com/en/sql-reference/functions/tag_references_all_columns).
3. Record observed identity/role, query IDs, visibility checks, scope hash, build/release IDs, observation times, and complete results or their hashed evidence references. An empty result without established visibility is unverified. Retries must be bounded; timeouts remain unresolved.
4. Compare environments only after each passes its own expected-state check. Map stable model/column/tag IDs through approved environment bindings; DEV and PROD database names need not match. Compare expected types, comments, and direct/effective tags under the documented comparison policy. Preserve meaningful punctuation, units, and case; do not normalize away differences.
5. Allow narrowly documented environment differences, such as an environment tag, using explicit expected values. Compare a shared release scope; unrelated objects outside scope are not automatic failures. An environment missing an expected object is a failure, not an ignored intersection.
6. The metadata gate requires zero unexplained discrepancies or unverified resources in the **required authorized scope**. Exempt RAW or unsupported objects remain visible as exclusions, never a claim of whole-estate coverage. Default production policy blocks unresolved sensitivity where classification is required; any exception retains its approved handling and unresolved status.
7. Store immutable evidence under `evidence/metadata/` and require it in release verification. A matching DEV/PROD pair can still be wrong; equal empty comments must fail. One target does not require an invented second environment.

### R-10 Platform and framework capability contract

Extend `platform_matrix.py` with metadata capabilities by **framework + warehouse + adapter/runtime + object type**. Each entry identifies comment read/write support, tag mechanism, limits, privilege needs, policy effects, persistence on replacement, verifier route, vendor stage, and accelerator qualification status. Separate `documented_vendor_capability`, `implemented`, `locally_tested`, and `live_qualified`.

| Route | Candidate native projection | Required qualification boundary |
|---|---|---|
| Snowflake | Relation/column comments; governed custom tags | Initial live test target. Qualify tables, views, incremental rebuilds, inheritance, role visibility, and optional Preview tag mapping. |
| Databricks | Comments; Unity Catalog tags/governed tags | Pin runtime, catalogue/table format and object type; verify privileges and ABAC effects. Tag inheritance is not the same as Snowflake's and column batching differs. [Unity Catalog tags](https://docs.databricks.com/aws/en/database-objects/tags). |
| BigQuery | Table/field descriptions, including nested fields; labels where appropriate | Distinguish labels from security-bearing policy tags. Do not translate sensitivity into access controls automatically. Column data-governance tags are **Preview** in current documentation; treat as a separate opt-in qualification. [Table metadata](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/tables), [column access](https://docs.cloud.google.com/bigquery/docs/column-level-security-intro), [governance tags](https://docs.cloud.google.com/bigquery/docs/tags). |
| Redshift | Native table/column/view comments | Qualify privileges and object exclusions, including external tables/columns and late-binding-view columns. Do not treat AWS resource tags as column classifications. [COMMENT](https://docs.aws.amazon.com/redshift/latest/dg/r_COMMENT.html). |
| ClickHouse | Table and column comments; system-catalogue readback | Pin server version, table engine, and cluster/replica scope; a local comment update is not proof of all-replica consistency. No invented Snowflake-style tag API. [Table comments](https://clickhouse.com/docs/reference/statements/alter/comment), [column comments](https://clickhouse.com/docs/reference/statements/alter/column). |
| MotherDuck | Evaluate DuckDB-compatible comments in the selected remote database | Local DuckDB tests do not establish MotherDuck compatibility. Verify remote identity, extension/server versions, attachment and dependency limitations; unsupported metadata stays in the contract. [DuckDB comments](https://duckdb.org/docs/current/sql/statements/comment_on). |
| Coalesce | Framework projection to node/column documentation plus qualified warehouse operations | Preserve node IDs, templates/packages, storage mappings and human edits. Qualify the selected Coalesce version/export shape and its generated SQL; never assume node documentation becomes native comments. Retain current conditional route and direct-submission restrictions until separately qualified. |

A missing accelerator adapter is `not_implemented`, not evidence that the vendor lacks the feature. Unsupported pairings remain blocked. Non-Snowflake metadata execution and Fusion are subsequent qualification work, not implied by this first release.

### R-11 Optional naming with consistent physical bindings

1. Offer `<TYPE>_<DOMAIN>_<REST>` for new Snowflake models, with a reviewed type map and example preview. It is a convention option, not a universal best practice or a prerequisite for metadata management. Reuse intake decisions instead of applying one pilot's preference to every customer.
2. Refactors preserve existing aliases and custom schema/alias macros. Renames require a consumer impact plan covering dbt refs, direct SQL, grants, scheduled jobs, semantic models, and compatibility strategy. Do not replace an existing `generate_alias_name` macro without a reviewed integration.
3. Resolve identifiers per platform, including quoting, case, length, collisions, reserved words, model versions, and per-environment mapping. Explicit aliases take precedence. Sandbox naming must remain consistent with its actual target contract.
4. Use one reviewed mapping for code, dictionary, ERDs, native metadata operations, and Omni physical bindings. Reconcile it against the compiled manifest and observed relations; a second independently generated name resolver cannot establish agreement.
5. Include naming policy and all metadata scope/taxonomy choices in `guided_workflow._selection` fingerprints and downstream invalidation, not only `QUESTIONS`/`ANSWER_KEYS`. A changed prefix, domain, tag mapping, RAW scope, or classification policy invalidates affected prepared artifacts, checks, approvals, and semantic bindings.

### R-12 Guided review, semantic handoff, and AI context

1. Include a Metadata page in `START_HERE.html` and the final ZIP. Show: what will be documented, existing-to-proposed differences, evidence/review status, write destinations, RAW exclusions, tag policy implications, unresolved decisions, coverage denominators, and phase results. Keep large receipts in optional technical evidence; preserve manifest associations even in reduced exports.
2. Provide a clear sequence: review meanings → resolve decisions → review generated metadata/code → authorize selected target phases → deploy → verify. Existing valid approvals can be reused only for unchanged bound content; avoid repeated approvals for the same action.
3. Generate human-readable dictionary, layer documentation, ERD labels, YAML, and semantic/AI context from the same versioned definitions. Preserve curated semantic descriptions, metric aggregation/time behavior, fanout restrictions, access context, and known unknowns. Do not automatically turn inferred definitions into authoritative AI instructions.
4. Where Omni is selected, bind generated views/topics/context to the actual deployed names and definition version. Include a downstream refresh/import handoff and acceptance checks for representative fields and business questions. Warehouse comments alone do not prove that Omni, Cortex, or another consumer has loaded them or answers correctly.
5. The handoff includes a metadata change summary, scope/mapping manifest, executable phase artifacts, privilege plan, verification evidence, exception register, and reconciliation/recovery runbook. Operators should not need to discover unlinked SQL sidecars after delivery.
6. Keep metadata checks within the existing warehouse-validation lane and preserve the other quality lanes. Post-run evidence belongs in the separate deployment-review export, linked to the frozen original handoff; do not rewrite that handoff to insert new receipts or change its approved hashes.

## Implementation sequence and stop gates

Complete and validate each phase before beginning the next. All paths in the change map refer to `skills/data-model-accelerator/` unless prefixed with `docs/`. Phase results are retained in `validation/warehouse-metadata-governance/progress.json`; live gates remain open.

| Phase | Scope and change map | Exit gate |
|---|---|---|
| 1. Contracts and intake | R-1/R-2/R-4/R-10: dictionary schema/migrator, metadata manifest/schema, `verify_model_documentation.py`, `references/model-documentation.md`, `guided_workflow.py`, framework/platform capability fields | Versioned migration preserves evidence; unresolved classification remains unknown; independent scope and exclusions are testable. |
| 2. dbt projection | R-3: `generate_dbt_docs_yml.py`, generation ownership manifest, project templates, candidate examples, current-version parsing fixtures | Idempotent merge, preserved human content, valid configuration, effective persistence coverage, no duplicate patches, no customer macros executed by static tests. |
| 3. Snowflake metadata planning | R-5/R-6/R-8: `plan_warehouse_metadata.py`, renderer/adapters, privilege diff, source lineage resolver, before/expected state | Fully scoped safe SQL units; no same-name RAW fallback, no unknown downgrade, no hook exception, policy/ownership conflicts block writes. |
| 4. Release integration | R-7: `deployment_workflow.py`, `deployment_authority.py`, `deployment_adapters.py`, lint artifact roles, request/receipt schemas | Child authority, dependency ordering, identity/hash binding, partial failure/retry and promotion/replay gates pass adversarial tests. |
| 5. Readback and delivery | R-9/R-12: `verify_warehouse_metadata.py`, trusted collector/receipt checks, parity mapping, `delivery_portal.py`, review/export associations and runbook | Equal-but-wrong and invisible metadata fail; scoped verified/excluded states visible; ZIP links and evidence integrity pass. |
| 6. Optional naming and live pilot | R-11 plus full integration: alias integration, downstream physical mapping; `docs/CAPABILITIES.md`, `docs/qualification.md`, skill/operator references | Synthetic end-to-end development run followed by separately authorized promotion/parity; native receipts and remaining platform gaps published accurately. |

New tests must integrate with existing documentation, engagement, guided workflow, runner, deployment authority/adapters, quality, portal, and export suites. Preserve the original generic-hook rejection tests. Store implementation evidence in `validation/warehouse-metadata-governance/`; do not label this requirements review as a passing implementation run.

## Required acceptance scenarios

| ID | Scenario | Required result |
|---|---|---|
| A-01 | Version-1 migration, unknown prose, multi-role composite keys | Lossless provenance; unresolved values retained; invalid combinations rejected. |
| A-02 | All selected bronze/silver/gold models, sources, optional seeds/snapshots, ephemeral nodes | Complete logical docs; honest physical scope and adapter exceptions. |
| A-03 | Repeated generation, hand-edited docs, anchors, doc blocks, duplicate patches | No-op for unchanged input; safe preservation; conflicts block apply. |
| A-04 | A physical column absent from both YAML and dictionary; `SELECT *` expansion | Independent physical enumeration detects the omission. |
| A-05 | Per-folder `persist_docs: false`, mixed-case column, view/incremental model | Effective settings and adapter behavior verified; no global-default false pass. |
| A-06 | Same-named unrelated RAW columns or a transformed bronze field | No automatic source description/write; exact semantic evidence or review required. |
| A-07 | UNKNOWN sensitivity or a proposed lower table classification | No invented INTERNAL/PUBLIC; explicit handling and classification gate. |
| A-08 | Existing custom tag with incompatible allowed values, policy binding, or Preview mapping | Drift/security/stage decision required; no unreviewed provisioning or grant change. |
| A-09 | Modified/helper macro, extra hook, injected identifier/value/Jinja comment | Hook rejection preserved; injection does not execute or expand write scope. |
| A-10 | dbt build plus governance/RAW SQL under different authorities | Bound phase execution; no SQL sidecar misrouted through the dbt job API. |
| A-11 | Wrong account/role/schema, changed dictionary, expired approval, replayed receipt | Fail before mutation or acceptance; stale evidence cannot promote. |
| A-12 | Multi-statement export, large column count, long grain/tag value | Valid bounded transport units; unsupported limits fail before execution; no truncation. |
| A-13 | Build failure, partial metadata success, timeout and retry | Required phase fails; completed operations remain recorded; safe idempotent recovery. |
| A-14 | Concurrent human edit, object recreation, full refresh, clone/swap | Drift detected; no blind overwrite; readback requalifies the actual objects. |
| A-15 | DEV and PROD have identical but wrong/empty comments or missing tags | Each fails its expected-state check despite apparent parity. |
| A-16 | Different database/tag namespaces and intended environment labels | Approved logical mapping passes; missing expected objects still fail. |
| A-17 | Restricted collector cannot see objects/tags, empty result, incomplete pagination | Unverified/failed coverage; never 100% or zero-difference success. |
| A-18 | Read-only/shared RAW and unsupported object types | Visible exclusions; no unauthorized writes or whole-estate completeness claim. |
| A-19 | Direct versus inherited/propagated tag values | Correct effective-state and direct-assignment checks; counts do not confuse associations with writes. |
| A-20 | New naming collisions, existing alias macro, model versions, Omni bindings | Preserve current names by default; reject collisions; all generated bindings agree. |
| A-21 | Every framework/warehouse selection, including Coalesce and MotherDuck | Correct versioned capability status; no Snowflake SQL or local-only qualification mislabeled portable. |
| A-22 | Guided package and reduced ZIP; fresh operator walkthrough | Metadata review and run order discoverable; internal links and evidence hashes valid. |
| A-23 | Approved synthetic Snowflake source → dbt layers → metadata → semantic handoff | Native comment/tag readback matches exact expectations, zero unexplained required-scope gaps; downstream acceptance separate. |
| A-24 | Second authorized environment and promotion after a content change | Fresh target-bound evidence required; logical parity verified only for the approved release. |

The scale test should approximate the reported blind run without embedding customer data: at least 27 selected models, 1,282 model columns, and 497 source columns, with representative Unicode, long descriptions, quoted identifiers, and mixed materializations. Set performance budgets from an observed authorized baseline; do not invent a runtime SLA or require a fixed tag-association count.

## Definition of done and non-claims

- **Requirements complete:** review findings, contract, sequence, and acceptance cases are specified; original acceptance obligations are retained above.
- **Implemented:** changed code and targeted/full regression checks pass with recorded versions and no hidden skips in the qualified lane.
- **Live qualified for dbt + Snowflake:** the selected supported object types complete authorized deployment and independently verified metadata readback; source exceptions and Preview choices are explicit.
- **Customer accepted:** designated reviewers approve business meaning and representative downstream behavior. Neither live comments nor documentation coverage alone establishes this.

This work does not automatically deploy customer changes, rename existing relations, introduce masking/row-access policies, grant broad privileges, classify actual values using AI, enable propagation, replace an enterprise catalogue, or certify every platform. Those require their own selected scope, authority, and validation. Metadata improves discoverability and AI grounding; it does not by itself prove business accuracy, prevent fanout, or enforce access controls.
