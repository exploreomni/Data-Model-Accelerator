# Warehouse metadata delivery

The accelerator now treats warehouse metadata as a reviewed, versioned release component. Use the same dictionary for dbt properties, warehouse comments, the review page and downstream context. Keep metadata presence, correct business meaning, authenticated live execution and consumer acceptance distinct.

## Interview once, then preserve the decisions

Reuse discovery answers. Record `metadata_policy` through `guided_workflow.py answer` before generating dependent artifacts: mode (`comments`, `comments_and_tags`, `documentation_only`), environments, owner, taxonomy, tag namespace, RAW selection/source IDs, decision reference and unknown handling. Descriptions are the default proposed delivery; the user chooses any exception. `naming_policy` defaults to preserving existing names; alternatives require a supplied domain and decision reference. Changing these structured answers invalidates dependent evidence. Legacy engagements remain readable without retroactive metadata claims.

RAW descriptions require a separate source owner decision and exact `source_refs` for the catalogue object, physical column path and catalogue hash. A matching column name, cleaned model description or transformed output is not a RAW definition. `UNKNOWN` is a real classification state; the generator never turns it into INTERNAL. Classifications/key roles do not enforce warehouse permissions or constraints.

## Shared definitions and dbt projection

1. Produce dictionary v2 using `schemas/data-dictionary-v2.schema.json` and `data_dictionary_v2.validate_dictionary`. Keep `models` and `sources` separate; every source needs `source_id`, a distinct column ID and `source_inventory_sha256`. Record real review/evidence references; inference remains proposed or unresolved.
2. For legacy documents, run `scripts/migrate_data_dictionary.py --input OLD.json --output NEW.json`. It preserves original text and provenance in a new file. Historical receipts stay historical.
3. For dbt, follow [dbt-metadata-generation.md](dbt-metadata-generation.md): preview, review, then apply to a separate copy. Use the ownership manifest on regeneration. All selected layers/resources need bindings; seeds/snapshots are explicit and sources receive documentation without `persist_docs`. Human edits, duplicate patches, unsupported YAML or ambiguous versions block apply. Existing overrides are retained and reported.
4. Compile only in the authorized runtime. Check full enabled build scope with `metadata_observation.bind_dbt_manifest`, including source/seed/snapshot relations; a narrow docs selection cannot hide build writes. Native persistence requires subsequent warehouse evidence.

Before the build handoff is frozen, include the v2 dictionary and a JSON `metadata_configuration_template` produced by `metadata_release.configuration_template(configuration)`. The template fixes every configuration field except the future candidate hash. After freezing, derive that hash with `candidate_binding(build_plan)`. Both child planning and full-build acceptance require the original dictionary and template to match; changing scope, dispositions, classifications or physical bindings requires a newly reviewed build handoff.

## Bind the physical warehouse

Create a `metadata_configuration` JSON with these exact top-level keys:

| Key | Meaning |
|---|---|
| `schema_version`, `kind` | `1`, `metadata_configuration` |
| `framework`, `warehouse`, `environment` | Explicit reviewed selections, independent of agent host |
| `target` | `{id, identity}`; automated phases use `metadata_release.target_binding(destination_id, validated_runner_target)` |
| `candidate_sha256` | Exact candidate binding; automated phases use `metadata_release.candidate_binding(completed_build_plan)` |
| `catalogue_sha256` | Reviewed RAW catalogue file hash |
| `metadata_policy` | Same structured selection recorded during discovery |
| `resources` | Every dictionary model/source has an explicit binding/disposition |

Each resource has `resource_id`, `resource_type` (`model` or `source`), `layer`, `relation` (`namespace` components, exact `name`, `kind`), `disposition`, `reason`, `columns` (dictionary-name → physical-name map), `source_write_decision`, `tags` and `column_tags`. Dispositions are `required`, `documented_only`, `excluded`, or `ephemeral`; non-required resources need a reason and remain visible. Physical collisions are refused; aliases are never inferred or renamed. Identifiers retain exact case and are quoted by the selected renderer.

Governed assignments use `{id, name, value, policy_effects, evidence_reference}`. `name` is a fully qualified Snowflake custom-tag path or one Unity Catalog key. Reserved logical IDs `sensitivity` and `key_roles` must match the canonical definitions; a table sensitivity cannot be lower than a classified column. The approved policy/governance evidence must establish `none_verified` effects for this informational route. Bound or unknown security effects, missing definitions and incompatible allowed values block execution. Governance owners provision or change definitions separately; this release does not create tags, issue grants, change masking/ABAC, or enable propagation.

Generate the contract with `scripts/metadata_contract.py --dictionary DICTIONARY.json --configuration CONFIG.json --output CONTRACT.json`. A contract can represent unresolved work and will list blockers. It grants no deployment authority.

## Observe, plan and review

Collect metadata read-only with the queries from `metadata_sql.read_queries(warehouse, relation)`. Each query enumerates all visible columns, including undocumented ones. Capture native query IDs/results, exact destination/principal, reliable object incarnation/version, complete pagination, visibility and governance definitions. Do not fill these fields from the dictionary or invent an object version from the collection time. Type names/modifiers need an exact adapter mapping. An inaccessible or empty catalogue is not complete coverage.

Normalize the export to `warehouse_metadata_observation` using `metadata_observation.py` (see `tests/test_warehouse_metadata_plan.py::observation` for the **synthetic-only** shape). It includes contract/candidate/scope hashes, target, build release ID, timezone-aware observation time, collection provenance, independently enumerated resources and governance. `seal` binds bytes; it does not authenticate them. External collectors/operators must establish and later sign provenance. Imported booleans alone never prove live validity.

After the framework build, prepare the metadata difference against the actual built objects:

```sh
python skills/data-model-accelerator/scripts/plan_warehouse_metadata.py \
  --dictionary DICTIONARY.json --configuration CONFIG.json \
  --observation BEFORE.json --output /absolute/new/metadata-package
```

The package contains `metadata-plan.json`, before/after values, unchanged assignments, scoped privilege requirements, governance requests, read queries and separate `target_metadata/` and `source_metadata/` SQL units. Each file is exactly one native statement. Do not concatenate or split by semicolon. Blocked plans retain candidate SQL in their JSON preview but export no runnable SQL files. Missing/new objects require a post-build observation. One logical tag association is not one API request; direct and inherited associations have separate counts.

Lint every exported SQL unit using the selected warehouse dialect and complete file/hash inventory. Exact quoted identifiers can trigger `RF06`; full description literals can trigger `LT05`. Review these findings and, only where needed, declare an exact-file convention exception with its reason under the existing [lint contract](linting.md). No exception is emitted automatically and raw findings stay visible. Parser, coverage, data and runtime errors cannot be waived. Metadata SQL files retain a terminal newline and their exact planned hashes.

## Reviewed execution through the existing runner

Use the [deployment contract](deployment.md). Prepare a **new linked metadata handoff** after the build, preserving the original build engagement and frozen artifacts. Keep the same source, catalogue, framework, runtime and discovery choices. Register the metadata plan as documentation and each selected SQL unit as implementation in the new handoff. The candidate binding pins the completed build's entire original handoff and immutable commit.

Provision a native SQL destination in the trusted runner policy for the selected warehouse. The framework destination and native destination must declare the same `physical_destination`, an exact nonsecret account/workspace identity established by the runner administrator. A dbt or Coalesce service URL does not identify its warehouse connection. The complete policy is hash-bound to both plans; native endpoint fields are also compared where available. Its exact default namespace is the default boundary. An optional `metadata_namespaces` list can authorize additional explicit namespaces such as bronze/silver/gold/RAW and a custom-tag schema; it is never a wildcard. Credentials remain outside artifacts.

**Current execution boundary:** linked metadata phases are implemented and tested in simulation. Automatic **live** metadata dispatch is blocked because an authenticated native collector that rechecks current state immediately before writes is not implemented. The reviewed SQL/operator or independently governed CI handoff is available; generated queries and imported observations are not a substitute for that collector. Do not remove this block by setting evidence flags or reusing a generic native-SQL route under a dbt review. Native warehouse qualification, collector integration and authority review are remaining work.

Add this field to the ordinary deployment request:

```json
{
  "metadata_phase": {
    "plan_artifact": "metadata/metadata-plan.json",
    "parent_operation_id": "EXACT_COMPLETED_BUILD_OPERATION_ID",
    "phase": "target_metadata"
  }
}
```

Use `source_metadata` in a separately authorized source phase. Select the plan with role `documentation`, followed by that phase's generated SQL files with role `model_sql` in their exact plan order. Extra SQL, altered SQL, wrong destinations and incomplete parent builds are refused. Metadata is routed to the native SQL endpoint, never through a dbt job API. A no-op phase needs readback instead of a write submission.

The existing external model sign-off and deployment approval must cover this exact handoff and plan. The signed approval's `claims.metadata_preflight` must bind the metadata plan, contract, before observation, parent plan, candidate and parent operation; verify full physical build scope, permissions and policy effects; and include an active exclusive change-window reference/expiry. The baseline must postdate completed build execution. See `metadata_release.verify_preflight` for the executable simulation contract. `check_preconditions(plan, current_observation, completed=operation_ids)` provides deterministic drift detection for an external operator/collector; the coordinator cannot presently collect that fresh observation itself. Warehouse DDL is not a universal atomic compare-and-swap. Expiry, recreation or a concurrent edit requires renewed investigation/replanning, not blind overwrite.

The runner records each operation before dispatch. Partial failure/timeout retains its native IDs and successful predecessors. Observe/reconcile existing IDs; never resubmit unknown outcomes. Restore only the recorded previous values after a new drift check and explicit recovery approval. Some platforms cannot restore exact NULL metadata for every object kind; the renderer refuses those cases rather than converting absence to empty text. Rebuild/full-refresh/clone/swap invalidates the previous incarnation and readback.

## Readback, parity and downstream acceptance

Run `scripts/verify_warehouse_metadata.py --contract CONTRACT.json --observation AFTER.json --release-id BUILD_RELEASE_ID --output REPORT.json`. Optional `--phase target_metadata|source_metadata` evaluates that write phase while retaining full physical coverage checks. It detects missing/extra columns, incorrect comments, missing direct tags, unknown policy state and visibility gaps. It reuses the existing physical schema verifier over a model-plus-source union.

`compare_environments` requires fresh observations, a common candidate hash and each environment to pass its own expected-state check first, then compares logical resource/column/tag IDs. Different physical database/tag namespaces are allowed through the reviewed bindings. Different candidate hashes need a separately qualified release mapping and currently fail. Environmental tag differences require explicit reasons/review references; sensitivity and key-role differences cannot be excused this way. Equal empty or wrong descriptions fail before parity. This result is metadata-only comparison, explicitly not signed release parity or promotion authority.

For metadata-phase acceptance, the independent signer's claims include the actual `metadata_observation`; required metadata checks bind the recomputed report's `verification_sha256`. The observation must follow completed execution, match the build release and remain fresh. Simulation observations cannot satisfy live acceptance. The full build's metadata gate also requires its reviewed v2 dictionary in the frozen handoff and full-build scope evidence. Generic passed flags cannot replace this comparison.

Generate a downstream binding/context handoff with `metadata_handoff.py --contract CONTRACT.json --observation AFTER.json --output /absolute/new/semantic-metadata`. It includes `metadata-semantic-handoff.json` and `AI_CONTEXT.md`, retaining unknowns and exact names. The semantic specialist must preserve curated Omni formulas, aggregation, security and topic grain, resolve conflicts, refresh/import the actual tenant and validate representative questions. Warehouse comments alone do not prove that Omni or an AI consumer loaded or interpreted them.

Register `review.metadata = {plan_artifact_id, sha256}` in the guided review. The Metadata page derives its content from the pinned plan and remains in the ZIP. Excluded technical evidence stays explicitly omitted, not passed. Export post-run evidence through the separate deployment review; never insert receipts into a frozen original handoff.

## Optional naming preview

`metadata_naming.preview_naming(warehouse, resources, policy=None, type_map=..., occupied_relations=...)` returns a deterministic candidate map. The default preserves exact resolved names across all six platforms. Existing objects and explicit aliases always win; custom alias/schema macros are never edited. New Snowflake table/view candidates can use `type_domain` with a supplied, reviewed role-to-prefix map and literal stems. Unknown roles, collisions and names exceeding 255 characters block the preview; names are never silently truncated. `layer_domain` and non-Snowflake renaming remain unsupported by this preview.

Carry one reviewed map into code, dictionary, diagrams, native metadata and semantic bindings, then reconcile it with the compiled manifest and actual warehouse names. A preview does not establish live uniqueness or deployment permission. See `tests/test_metadata_naming.py` for synthetic input examples.

## Platform boundaries

| Warehouse | Generated native metadata | Qualification boundary |
|---|---|---|
| Snowflake | Table/view and column comments; custom informational tag assignments | Exact privileges, edition, policies, inheritance and object-incarnation qualification. System/Preview tags are blocked. |
| Databricks | Table/view comments and top-level column comments; UC table/view tags and table-column tags | Unity Catalog; column comments need SQL/Runtime 16.1+. View-column tags are not emitted. Signed native preflight and Statement Execution API receipts required. |
| BigQuery | Table/view descriptions and top-level column descriptions | Nested fields, security policy tags and Preview governance tags need separate qualified paths. Dataset location and complete field metadata matter. |
| Redshift | Current-database table/view and column comments | Owner privileges; external/late-binding objects excluded. AWS resource tags are not column metadata. |
| ClickHouse | Table/column comments | Selected server/engine/replica only. No automatic cluster propagation or governed tag API. |
| MotherDuck | Table/view comments and table-column comments | Remote database/version/dependency qualification; local DuckDB tests are not MotherDuck acceptance. |

dbt uses generated properties plus these native metadata phases where selected. Coalesce uses the shared dictionary/physical binding contract and qualified warehouse operations; node documentation/export generation remains conditional on its actual versioned project. The existing direct live Coalesce submission restriction remains. SQL sidecars must never be called native Coalesce node artifacts. All live platform qualification is destination-specific; static/local test success is not a production certification.

Official capability references: [dbt persistence](https://docs.getdbt.com/reference/resource-configs/persist_docs), [dbt meta](https://docs.getdbt.com/reference/resource-configs/meta), [Snowflake comments](https://docs.snowflake.com/en/sql-reference/sql/comment), [Snowflake tag policy effects](https://docs.snowflake.com/en/user-guide/tag-based-masking-policies), [Databricks comments](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-comment), [Unity Catalog tags](https://docs.databricks.com/aws/en/database-objects/tags), [BigQuery metadata DDL](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language), [Redshift comments](https://docs.aws.amazon.com/redshift/latest/dg/r_COMMENT.html), [ClickHouse table comments](https://clickhouse.com/docs/reference/statements/alter/comment), [ClickHouse column comments](https://clickhouse.com/docs/reference/statements/alter/column), [DuckDB comment semantics](https://duckdb.org/docs/current/sql/statements/comment_on). These document vendor behavior; local tests do not establish live support for a customer destination.
