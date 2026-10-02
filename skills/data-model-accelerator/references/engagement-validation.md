# Enhanced engagement validation

Use this contract for new dbt refactors after the analytics-engineering workflow.
It composes seven mandatory gates: refactor execution/benchmark, review package,
physical schema, preserved source values, dependency/consumer scope, catalogue
provenance and typed authority. The older helpers remain available for archived
version-1 evidence; their individual passes do not establish this enhanced grade.

## Prepare before engineering

1. Preserve the read-only source project and its `ae_common.snapshot(project)`
   file inventory. This hash is a content snapshot, distinct from a Git commit.
2. Use source specialists to construct the dependency graph, including shared
   macros/configuration and downstream semantic/report consumers. Preserve source
   native IDs and complete report contracts. Resolve cross-file references;
   aliases, ratio denominators, filters, date windows, nulls and query grain must
   come from those consumers, not just the directly selected model.
3. Normalize the raw catalogue and retain the original hashed metadata exports.
   Freeze independently derived expectations and preserved-field case bindings
   before engineering. Protect their digests in the host's run record. A matching
   aggregate or passing dbt test cannot replace source-value conservation checks.
4. Dispatch the engineering plan with exact file ownership. Preserve the actual
   host identities/times and the existing refactor record. The scope checker and
   validation coordinator do not start agents or generate arbitrary target code.

`engagement_scope` JSON requires `schema_version: 1`, `kind: engagement_scope`,
`source_revision`, `nodes`, `selected_nodes`, `exclusions`, and `consumers`:

- Each node: `id`, `kind` (`model`, `source`, `semantic`, `report`, `support`),
  nonempty `paths` relative to the source snapshot, and `depends_on` IDs. Source
  nodes cite their declaration files. Shared YAML paths may appear in several
  nodes. Every dependency must resolve; every node participates in cycle checks.
- Every source file must appear in a node or an exclusion `{path, reason}`.
  Exclusions cannot overlap nodes. Generated/environment directories omitted by
  the snapshot helper remain explicitly outside this denominator.
- Every affected semantic/report consumer needs `{node_id, disposition, reason}`.
  `disposition` is `migrate`, `retire` or `defer`; deferred consumers block a pass.
  Retirement is a declared design decision, never an instruction to delete.
- The checker follows all descendants of selected nodes, then all ancestors of
  that affected graph. This retains a consumer's other shared dependencies.
  File accounting and declared edges are not proof of complete parsing; unresolved
  dynamic SQL, unseen workbooks and external assets remain specialist gaps.

`source_value_contract` JSON requires `schema_version: 1`,
`kind: source_value_contract`, `source_revision`, `catalogue_sha256`,
`baseline_sha256`, and nonempty `preserved_fields`. Each field declares `model_id`,
`model_column`, `case_id`, `case_column`, `source_reference`. Model/column names
must exist in the documentation inventory; cases/columns must exist in the frozen
baseline with zero numeric tolerances. Declare source dimensions, attribution,
costs and other conserved values explicitly. Coverage is limited to these
bindings; transformed fields require their own independent cases.

## Build and collect independent evidence

Use the existing reviewed `run_dbt_project.py --execute` flow. It retains profile,
destination, hook, package and snapshot controls. The enhanced verifier never
executes repository code, SQL or installers and never obtains credentials.

Use `export_results.serialize_rows(description, rows, columns, keys)` for DB-API
results. It requires exact unique column names, full row widths, strict types and
unique nonnull keys. Decimals become strings without quantization; floats retain
only the precision the driver supplied. Dates/times preserve native ISO values
and offsets. Booleans cannot stand in for integers. More than 100,000 rows rejects
the export; partition a larger population into explicitly frozen cases instead
of truncating it. A rejected export remains a failed/missing case in the complete
benchmark, with a separate diagnostic; never reduce the expected denominator.

Collect physical metadata after the completed build, independently of the
dictionary. The optional local adapter is
`capture_duckdb_schema.capture(database_path, native_receipt_path, project_path)`.
It runs fixed information-schema queries with a read-only connection and external
access disabled. It retains unexpected tables in native schemas so documentation
cannot hide them. This adapter supports local DuckDB only. Other warehouses need
an authorized host collector/export; the verifier does not implement connectors.

A `physical_schema_observation` declares version 1, `kind`, `candidate_sha256`,
`origin` (`executed_metadata` or `provided_export`), `validation_scope`
(`local` or `target`), `adapter_type`, UTC `captured_at`, `identifier_policy: exact`,
nonempty `scope`, `native_receipt_sha256`, `invocation_id`, and `relations`.
Each relation contains `physical_name` and a complete nonempty column-name array.
Use exact SQL-quoted three-part names, e.g. `"DB"."Silver"."Orders"`, escaping
embedded double quotes. The denominator includes enabled native materialized
models, seeds, snapshots and declared sources; ephemeral models have no physical
relation. Deduplicate shared physical source/seed identities. These checks cover
names and column presence, not physical types, nullability, prose or permissions.

## Catalogue provenance and decision authority

`catalogue_provenance` requires version 1, `kind: catalogue_provenance`,
`catalogue_sha256`, `capture_method`, `provenance_reference`, and `mappings`.
Capture methods correspond exactly to catalogue origins:

| Capture method | Catalogue origin |
| --- | --- |
| `synthetic_generator` | `synthetic` |
| `operator_export` | `provided_export` |
| `live_connector` | `live_metadata` |

Each mapping contains `catalogue_pointer`, `extraction_id`, `export_pointer`.
Pointers use exact JSON-pointer paths into the normalized catalogue and its hashed
raw JSON export. Map each object's identity (`catalog`, `schema`, `name`) and
`object_type`, plus every column's `path`, `data_type`, `nullable`, exactly once.
For example, `/objects/0/identity/catalog` can map to extraction `objects` at
`/0/table_catalog`. Null, boolean, number and string values remain distinct.
This checks normalized values against retained exports. It cannot authenticate
the collector, discover withheld metadata, or prove a provided export was live.
Non-JSON exports need a separately reviewed normalization adapter; do not invent
pointer matches or label a synthetic catalogue as captured warehouse metadata.

`engagement_authority` requires version 1, `kind: engagement_authority`,
`source_revision`, `candidate_sha256`, `catalogue_sha256`, `baseline_sha256`,
`scope_contract_sha256`, `value_contract_sha256`, `native_source_bindings_sha256`, `purpose`, `decision_state`,
`actor_id`, `review_reference`, `rule_ids`, `decision_ids`.

- `purpose`: `simulation` or `development_validation`. Synthetic catalogues and
  fixture replays require simulation and cannot establish target validation.
- `decision_state`: `proposed`, `simulation_authorized` or
  `human_approval_recorded`. Proposed definitions require a null review reference.
  Other states require a nonempty reference. Simulation cannot claim human model
  approval; development cannot borrow simulation authorization.
- `rule_ids` exactly covers the plan's rules; `decision_ids` exactly covers the
  frozen correctness-case decisions. Empty decision IDs are valid when there are
  no correctness cases. Updating pinned scope/values requires a new authority
  record; never rewrite history to imply earlier review of changed evidence.
- Development validation may test proposed definitions. A human-approval record
  remains a claim until the trusted host authenticates the actual authority and
  reviewed version. Every result explicitly denies promotion authorization.

## Assemble and verify

Keep the existing review package with ERD, readable/canonical dictionary, all
three layer documents, lineage, catalogue/bindings/exports and test evidence.
Its source-inventory artifact must be JSON with `schema_version: 1`,
`kind: engagement_source_inventory`, absolute `project_root`, and the exact
`snapshot` object from `ae_common.snapshot(source_project)`. The review package's
`source_snapshot_sha256` remains the **inventory file hash**, while the plan,
scope and benchmark source revision is the **snapshot content hash**. The enhanced
gate explicitly bridges them; do not replace one hash with the other. This version
supports one normalized catalogue per engagement.

Register exactly one code-role JSON artifact with `kind: engagement_candidate_inventory`,
`schema_version: 1`, absolute candidate `project_root`, and its exact `snapshot`.
Other code artifacts may accompany it. This binds the review package to the tested
candidate instead of accepting an unrelated code attachment.

Create JSON with `schema_version: 1`, `kind: engagement_validation_request`, and
these eight associations, each `{path, sha256}`:

`refactor_record`, `review_package`, `model_inventory`, `physical_observation`,
`value_contract`, `scope_contract`, `authority`, `catalogue_provenance`.

Also include `native_source_bindings`, one entry per enabled native dbt source:
`{source_id, catalogue_object_id, local_remap}`. Each object must be resolved by
the review package's catalogue bindings. Native database/schema/identifier and
observed top-level columns must match its catalogue identity and column paths.
Use `local_remap: null` for a matching identity. For a local-only namespace change,
declare `{relation: [database, schema, identifier], reason}` explicitly; target
validation never permits this remapping. Nested catalogue paths are compared at
their top-level physical column for this check. Pin the whole bindings array with
`ae_common.hash_json` in authority's `native_source_bindings_sha256`; an empty
array is valid only when the native manifest has no enabled sources.

Paths may be absolute or safe relative paths from the request. The model inventory
must be the exact file associated with review-package documentation. Output must
be a new file outside both the source and candidate projects.

```sh
python scripts/verify_engagement.py /absolute/request.json \
  --output /absolute/new-engagement-verification.json
```

The command recomputes the underlying gates; prewritten passing summaries are
insufficient. `enhanced_local_validated` and `enhanced_target_validated` describe
evidence coverage at that scope, not production approval. Failures yield
`incomplete` and a nonzero exit. Malformed/broken associations fail closed before
dependent checks; valid failed gates retain detailed reports. Retain each attempt
in a new output file. Reuse evidence only while all its pins and context remain
valid. Adapter/export corrections without model changes are new evidence attempts,
not fictitious model-repair events in the legacy repair chain.

Require separate target warehouse execution, Omni semantic/security acceptance,
operations and actual human approval before promotion. No passing synthetic run,
recorded actor name or approval string grants those permissions.
