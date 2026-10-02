# Paired analytics engineering and validation

Use this workflow after source specialists and the warehouse/semantic architects
have established the scoped model specification. This adds implementation and
independent acceptance work to the existing extraction workflow; it does not
replace source discovery, catalogue verification or the model review package.

For existing-project refactoring engagements, finish with the mandatory composite gate in
[engagement-validation.md](engagement-validation.md). It adds physical metadata,
explicit preserved-source-value cases, dependency/consumer coverage, catalogue
export mappings and typed authority. The contracts below remain version 1 for
archived evidence; a passing refactor-run record alone is not enhanced validation.

For raw-only new builds without a trusted prior model or report, use
[inherited-data-discovery.md](inherited-data-discovery.md). Do not fabricate the
original-project or legacy-baseline evidence required by the refactor contract.

## Analytics engineering agent

Inputs: a versioned model specification, source graph and catalogue bindings,
the original project snapshot, a domain task, and the agreed target environment.
Read the dbt specialist guidance for resource paths, macros and materializations.

Own only the task's declared files. Preserve sound existing models. Implement
staging, intermediate transformations and marts in dependency order, with
explicit grain, keys, history and source-to-target rule mappings. The warehouse
architect owns design decisions; the engineer must report ambiguity rather than
invent a business definition. Shared dimensions/macros have one task owner.

Return the patch or isolated working-tree path, before/after file hashes, model
and rule IDs, dependencies, tests, documentation changes and unresolved issues.
Update the ERD/dictionary/layer documentation for changed models at the same
version. Supply unit/data tests, but never replace independent expected values
with outputs from the candidate. Do not edit the analyst's frozen evidence.

## Validation analyst agent

Begin before implementation with source evidence, priority report contracts,
fresh catalogue context and accepted business definitions. Freeze the expected
case population and values independently of the implementation. Capture report
filters, identity/persona, time zone, currency, data watermark and provenance.

Own acceptance queries and benchmark evidence. Keep observed compatibility and
accepted corrections in separate cases; name the human decision reference for
corrections. An old report is an observation, not unquestioned business truth.
Compare complete keys/values where feasible and label sampled coverage explicitly.
Exercise empty/null cases, join multiplicity, changed records and denied personas.
Evaluate every generated projection, including casts and derived calendar columns
in lazy views; build success and row counts can leave invalid expressions
unexecuted. Report column coverage, normalization collisions, decimal overflow
and malformed date/time controls separately from grain and total checks.

Return discrepancies with exact case/model/rule IDs and evidence. Never weaken
tolerances or remove cases to bless an implementation. Native warehouse and Omni
behavior require their own observations. A benchmark pass does not approve
deployment. This role specializes independent QA; existing documentation and
source-coverage checks still apply.

## Coordinate implementation

Use `scripts/plan_refactor.py` for explicit domain ownership and dependency waves.
Dispatch its tasks through the host's real agent tools and record returned agent
and run IDs. The planner emits instructions, not executed-agent evidence.

Run each dependency wave to completion before dependent work. Workers may read
shared contracts but cannot independently redefine them. Integrate patches into
one candidate, then check the whole project's dependency graph and file changes.
Parallelism is optional; inline execution must be labeled and is not independent
agent validation. File ownership in a plan is a review control, not a filesystem
sandbox; use separate worktrees or host-enforced write scopes for concurrent work.

### Refactor specification

Supply JSON with `schema_version: 1`, the actual `catalogue_sha256`, a `models`
array, `external_dependencies` and `shared_paths`. Each model declares `id`,
`domain`, `layer` (`staging`, `intermediate` or `marts`), its SQL `path`,
`depends_on` IDs, `rule_ids`, and `decision_status: accepted`. Use `owned_paths`
for additional model-owned files; assign shared YAML, macros and documentation
once through `shared_paths` (path to domain). External IDs represent explicitly
resolved inputs from the source graph, not permission to invent missing sources.

The accepted decision label records a supplied design choice; it is not proof of
human approval. The existing review package still binds catalogue exports,
source lineage and decision evidence. The plan captures the source project's
files separately from the specification and catalogue hashes.

```sh
python scripts/plan_refactor.py --project /absolute/reviewed-dbt-project \
  --spec /absolute/reviewed-model-spec.json --output /absolute/new-plan
```

The output must be outside the source project. Provide the plan and generated
task prompts to the actual host dispatcher. Keep the analyst's baseline outside
engineer worktrees and retain the original source snapshot for integration checks.

Keep bronze/silver/gold documentation categories while mapping existing raw,
staging/intermediate and mart namespaces explicitly. Folder renames alone do not
establish a model. Preserve downstream semantic definitions in the joint
placement plan rather than materializing every report filter upstream.

## Freeze the independent baseline

Before engineering begins, the analyst prepares a JSON contract with
`schema_version: 1`, `analyst_id`, `source_revision`, `catalogue_sha256` and a
nonempty `cases` array. Each case declares its unique `id`, `category`
(`compatibility` or `correctness`), exact result `columns`, nonempty composite
`keys`, and `context` including `timezone`, `watermark` and `principal`. Include
currency and report filters in context when relevant; candidate context must
match. Empty expected populations are valid cases and must stay in the denominator.

Each column declares `type` (`string`, `integer`, `decimal` or `boolean`) and
`nullable`. Numeric columns may declare nonnegative decimal-string
`abs_tolerance` and `rel_tolerance`; the default is exact equality. Export decimal
values as strings to avoid binary floating-point rounding. Keys cannot be null
or duplicated. Every row must contain exactly the declared columns.

`expected` identifies an independent JSON export (`{"rows": [...]}`) using
`path`, its byte `sha256` and a source `query_id`. A correctness case additionally
requires `decision: {id, approved_by, reason}` explaining the accepted correction.
Keep those decisions and original query evidence reviewable. A supplied person
name does not authenticate approval.

```sh
python scripts/freeze_benchmark.py --contract /absolute/analyst-contract.json \
  --output /absolute/new-baseline.json
python scripts/freeze_benchmark.py --verify /absolute/new-baseline.json
```

The frozen file embeds expected rows and pins the original exports. Verification
rechecks both. Preserve exports with the bundle; changing a pinned file invalidates
it. The digest detects changes relative to the recorded baseline, not malicious
replacement of the entire evidence chain. Keep the frozen digest in the host's
protected run record before dispatching engineering. The program cannot determine
whether a person secretly copied expectations from candidate output; independence
also requires separate ownership and review of source provenance.

## Execute a reviewed project

Use `run_dbt_project.py` only after reviewing the complete project, macros and
SQL for the selected environment. It copies the exact pinned project files,
parses with an explicit profile/target, checks supported resources and physical
write destinations, then performs a complete build. It preserves stdout, stderr,
preflight/build artifacts and the typed native receipt, including failed runs.

The request JSON declares `schema_version: 1`, `project_sha256` from
`ae_common.snapshot(candidate)["sha256"]`, `adapter_type` (`snowflake` or local `duckdb`), `profile`,
`target`, external absolute `profiles_dir`, `timeout_seconds`,
`allowed_destinations: [{database, schema}]`, and `expected_profile`. For Snowflake,
that last object requires exact literal `account`, `role` and `warehouse`; for
DuckDB it requires the exact literal `path`. Template expressions in these
selected profile settings are not qualified. Keep credentials in external
profiles; do not include them in requests or the review package.

```sh
python scripts/run_dbt_project.py --project /absolute/reviewed-candidate \
  --request /absolute/development-request.json --output /absolute/new-build \
  --dbt /absolute/qualified-environment/bin/dbt --execute
```

`--execute` is deliberate because this command runs project code and writes to
the selected database. Use a least-privilege development role restricted by the
warehouse administrator. The allowlist prevents unintended declared placement;
it cannot sandbox arbitrary SQL, macros, materializations or a compromised dbt
installation. Profiles and environment are execution inputs and need trusted host
controls. Parse also evaluates project code. Approval of a plan is not automatic
authorization to execute against a customer account.

The qualified evidence format remains dbt-core 1.12.4, manifest/v12 and
run-results/v6. External package resources, hooks, unit-test resources, functions
and YAML snapshots require separate qualification and are rejected. The runner
does not install packages, upgrade a project, translate dialects or silently
omit unsupported nodes. A Snowflake request is an execution path, not evidence
that a Snowflake account has been tested. Successful local DuckDB evidence stays
`local`; use the retained native receipt and business benchmark together.

Ambient `DBT_*` option overrides and nonempty project `flags` are rejected before
execution so they cannot enable unreviewed test-failure writes or select a partial
build. Reviewed macro inputs under `DBT_ENV_CUSTOM_ENV_*`/`DBT_ENV_SECRET_*` remain
host-controlled inputs; anonymous-usage settings are controlled by the runner.

## Benchmark the candidate

The analyst captures separate query exports using the frozen case contexts.
Supply an actual-results JSON with `schema_version: 1`, the protected
`baseline_sha256`, current `candidate_sha256`, independent `analyst_id`, and
`cases: [{id, context, result: {path, sha256, query_id}}]`. Each result export uses
`{"rows": [...]}` with the frozen column types. Preserve actual warehouse query
IDs and query text in the run evidence; this helper compares exports and does not
execute or authenticate their queries.

```sh
python scripts/benchmark_results.py --baseline /absolute/frozen-baseline.json \
  --actual /absolute/candidate-results.json --project /absolute/candidate \
  --output /absolute/new-benchmark.json
```

The report separates compatibility and approved-correction results. All frozen
cases remain in the denominator, including missing cases and expected-empty
access tests. It compares complete composite keys and every declared value;
duplicate keys, extra/missing rows, null/type/schema changes and context changes
fail. Numeric tolerances use `max(absolute, relative * abs(expected))`; key values
are exact. Detailed differences are capped at 100 per case while counts cover
all differences. Protect reports that contain sensitive values.

Define acceptance queries for staging/intermediate invariants as well as mart
metrics and downstream Omni behavior. A total-only case cannot prove row-level
accuracy or security. Express personas, dates, filters, currency and empty
populations explicitly. Passing these exports does not test a live Omni model;
that requires actual queries from the selected Omni development environment.

## Integrate, repair and verify the run

For this coordinated path, freeze `source_revision` as the plan's
`source_snapshot.sha256`; retain the Git commit reference separately in source
provenance. This binds the expected behavior to the exact reviewed working tree,
including uncommitted files. The catalogue digest must also match the plan.

The host creates a run record with `schema_version: 1`, `execution_mode`
(`host_subagent`, or explicitly `fixture_replay` for archived synthetic replay),
absolute `candidate_project`, `tasks`, `analyst`, `events_head`, `event_evidence`,
and these byte-hash receipts: `plan`, `specification`, `baseline`, `actual`,
`benchmark`, `native`, `events`. Each receipt is `{path, sha256}`; relative paths
resolve from the run record. `event_evidence` is the complete list of distinct
receipts referenced by the event log.

Each executed task supplies its planned `task_id`, observed `host`, `agent_id`,
`run_id`, `started_at`, `finished_at`, and `files`. Every changed file records
`{path, before_sha256, after_sha256}`; use null for addition/deletion. Unchanged
files need no entry. The `analyst` supplies the same execution identity/time
fields without `task_id` or `files`. Preserve timezone-aware timestamp precision;
whole-second truncation can incorrectly place a dispatch before a baseline freeze.
Document observation bounds when the host does not expose exact execution times.
Capture actual host results; never synthesize
agent execution from generated task prompts. One engineering agent may handle
sequential tasks, but the analyst must have a separate identity and run.

Use `repair_events.append_event` to append analyst validation and engineering
repair receipts. Supply the externally retained `expected_head` each time and
persist the returned `event_sha256` in the protected host record. Events include
`kind`, `candidate_sha256`, `evidence_sha256`, UTC `at`, `actor_id`, `task_id` and
`case_ids`. Validation uses null task ID, failed case IDs on failure, and an empty
list on success. Repairs name their owner task and change the candidate hash.
The allowed sequence is validation failure → repair → validation, with at most
three repairs. A pass closes that run; new code starts a new validation run.

Keep every failed benchmark. Repair evidence is a JSON record with
`kind: repair_change`, `candidate_sha256`, `task_id` and nonempty `changed_paths`
owned by that task. Preserve the actual patch alongside it. On unresolved
ambiguity or the third failed repair, hand the discrepancies to the architect;
do not weaken tests, broaden tolerances, rewrite the baseline or erase failures.

```sh
python scripts/verify_refactor_run.py /absolute/run-record.json \
  --output /absolute/new-run-verification.json
```

The verifier recomputes the plan and benchmark, checks current native evidence,
complete task/file/case coverage, role separation, dependency timing and retained
repair history. A later code edit invalidates earlier evidence. Hash chains and
identity strings need trusted host storage; they are not signatures or an access
control system. File differences cannot expose writes that were later reverted.

Keep the existing fresh catalogue, ERD/dictionary/layer-documentation review,
security checks and human model approval as separate release gates. Native
Snowflake validation and actual Omni queries must be observed before target
sign-off. None of these helpers merges, deploys or cuts over production.
