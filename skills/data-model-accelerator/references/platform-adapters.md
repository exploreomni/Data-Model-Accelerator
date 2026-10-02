# Platform readiness and adapter contract

`scripts/platform_readiness.py` is a read-only compatibility collector. It does not run git, import source code, execute Jinja/macros/hooks, install dependencies, connect to a warehouse, generate target code, or authorize external work. Python 3.9+ standard library is sufficient; the no-follow traversal requires POSIX filesystem support. The single versioned registry is `scripts/platform_matrix.py`; this collector's `ADAPTER_REGISTRY` is a derived compatibility view. All six warehouse choices have dialect, metadata identity, physical-design and check-recipe profiles. Registry entries do not establish live qualification.

The intended operator is an analytics engineer who knows the existing project. Use the collector to assemble prerequisites automatically; ask the operator only for missing facts and meaningful choices. Do not remove packages, hooks, flags, unit tests or stateful behavior just to make the bounded executor accept a customer repository.

## API and CLI

```python
from platform_readiness import assess_repository

result = assess_repository(
    repo_path,
    framework="dbt",          # dbt | coalesce | native_sql | None
    warehouse="snowflake",    # snowflake | databricks | bigquery | redshift | clickhouse | motherduck | gcp | None
    include_paths=["target/manifest.json"],
)
```

```sh
python scripts/platform_readiness.py /absolute/customer-repo \
  --framework dbt --warehouse snowflake \
  --include-path target/manifest.json
```

The CLI prints JSON to stdout and writes no files. Exit 0 means the bounded inventory has no scan gaps, **not** that generation or execution is ready. Exit 2 means retained scan gaps; exit 1 means invalid input or inability to open the root safely. Callers must inspect capabilities, findings and questions. `None` selections permit read-only assessment. `gcp` yields a warehouse question and never silently becomes BigQuery.

Options are `max_files` (5,000), `max_file_bytes` (10 MiB), `max_total_bytes` (64 MiB), `max_entries` (20,000), `max_depth` (40), `include_paths`, and `coalesce_contract`. Limits must be positive integers. No network or adapter dependency is needed. The caller owns persistence; write assessment outputs outside the input repository.

## Stable result schema

- `schema_version: 1`, `kind: platform_readiness`.
- `source_fingerprint`: `algorithm: sha256`, `value`, `scope: bounded_nonsecret_repository`, `complete`. The hash binds inspected relative paths/content hashes, exclusions, gaps, scan limits and explicit includes. It excludes absolute location, timestamps, selections and credential contents. Moving identical inputs is stable; modifying inspected bytes changes it. A partial fingerprint does not bind unseen content. Credential changes deliberately do not alter it; environment identity has a separate authority contract.
- `selection`: independent `framework` and `warehouse`, retaining unresolved/null input.
- `coverage`: `complete`, `scanned_files`, `scanned_bytes`, `limits`, `exclusions`, `gaps`. Each exclusion/gap has `path` and `reason`. Completeness means the selected static inventory bounds, not complete business/column lineage or unseen consumer coverage.
- `detected_sources`: `{type, paths, confidence: static_signal}` entries. Multiple types can coexist. Source detection never chooses the target.
- `raw_csv_inventory`: bounded snapshot headers, exact byte hashes, logical row counts and metadata gaps, with `source_owner` retaining dbt ownership when present. Fields remain lexical text; see [raw CSV contract](raw-csv-source-contract.md). This is not a native warehouse catalogue.
- `findings`: `{id, severity, summary, next_action, paths, blocks}`. Severity is `info`, `warning`, or `blocker`. `blocks` identifies `generation`/`execution` scope. Static regex signals may over-detect comments or empty configuration; the finding requests review, not automatic source rewriting.
- `questions`: `{id, prompt, choices}` for unresolved selections. These are questions, not assumed answers.
- `capabilities.assessment`: status `supported` or `partial`; reason always limits the claim to static inspection.
- `platform_pairing`: the selected matrix route, or null before selection; status is `supported`, `conditional` or `unsupported`, always `native_qualified: false`.
- `capabilities.generation`: `agent_assisted`, `requires_contract`, `unsupported`, or `needs_selection`. `agent_assisted` identifies an authoring route after the separate discovery/model/evidence gates; this collector is not a code generator. Scan blockers still prevent generation even when this authoring route exists.
- `capabilities.execution`: `requires_operator_validation`, `blocked`, or `needs_selection`. This module never returns a qualified execution pass.
- `native_semantics_parsed: false`, `execution_performed: false`.

Known credential/profile paths are excluded before opening or hashing. Error output does not echo source contents. Credentials embedded in otherwise legitimate SQL/configuration cannot be universally identified by filename; nothing returns file contents or resolves environment values. Keep secrets outside project inputs. Symlinks, unreadable paths, changing files and exceeded limits remain explicit gaps. Directory-entry limits bound enumeration as well as bytes. `target`/`dbt_packages` are skipped with dependency-evidence gaps unless explicitly included. An explicit file include does not import its generated siblings. Control, environment and credential exclusions cannot be overridden.

This is not an atomic filesystem snapshot. Re-assess before dependent work and compare the fingerprint; use the existing immutable source/evidence contracts for actual execution. A concurrent change entirely between two observations can only be caught by the host's stronger snapshot controls.

## Platform routes and boundaries

| Selection | Assessment and candidate route | Execution boundary |
|---|---|---|
| dbt Core → all six | Agent-assisted project patch with the chosen adapter, preserving packages, macros, hooks and CI | Exact Core/adapter/runtime compatibility must be qualified; ClickHouse uses dbt-clickhouse, MotherDuck uses a qualified dbt-duckdb/DuckDB/MotherDuck combination |
| dbt platform hosting → Snowflake / Databricks / BigQuery / Redshift | Separate hosting lookup and deployment route; intake still selects `dbt` once | Existing hosted job and runtime must be verified; local adapter availability does not establish hosting |
| dbt platform hosting → ClickHouse / MotherDuck | Unsupported by the current accelerator hosting adapter | ClickHouse documentation says **Private beta**; DuckDB is **CLI only**. No entitlement or MotherDuck hosting contract is inferred |
| native SQL → all six | Agent-assisted dependency-ordered SQL in the explicit dialect | Static lint/transpilation is not native validation; target execution, receipts and independent acceptance remain required |
| Coalesce → Snowflake / Databricks / BigQuery | Conditional; representative native contract required | CLI overview says Snowflake only; newer setup documents Databricks and BigQuery (7.40+). Verify the exact installed CLI/platform contract |
| Coalesce → Redshift / ClickHouse / MotherDuck | Unsupported; generation and execution are blocked | SQL, supplied native IDs or a complete contract cannot override the missing vendor route |

`platform_matrix.get_platform(warehouse)` returns a detached JSON-safe profile. `get_pairing(framework, warehouse)` returns a route; `dbt_core` aliases `dbt`, while `dbt_platform` is a hosting lookup, not an extra interview framework. `WAREHOUSES`, `FRAMEWORKS`, `SQLFLUFF_VERSION` and `adapter_registry()` are shared by intake, catalogue and specialist routing. Unknown products fail closed; `gcp` is not a profile.

Profiles pin SQLFluff **4.3.0** and its exact dialect. MotherDuck uses `duckdb` only as a grammar baseline. Typed check recipes distinguish local syntax, framework configuration/rendering, native planning, connection requirements, cost, side effects and uncovered statements. They are documentation recipes, not automatically executed commands. Native tools and frameworks still require their own pinned versions. See [catalogue providers](catalogue-providers.md) for the selected metadata route.

The existing bounded dbt/Snowflake runner's Core 1.12.4 full-project contract remains unchanged. No new warehouse runtime is installed or qualified by this registry. Source detection uses explicit platform markers or declared specialist profiles; generic SQL, CSV rows and `type: duckdb` alone do not prove a remote MotherDuck source.

`coalesce_contract` is a nonsecret caller-supplied dictionary with:

```json
{
  "warehouse": "snowflake",
  "project_format_version": "operator-confirmed-version",
  "representative_paths": ["coalesce/nodes/example.yml"],
  "node_ids": ["existing-native-node-id"],
  "column_ids": ["existing-native-column-id"],
  "node_types": ["reviewed-native-type"],
  "storage_mappings": {"SOURCE": {"database": "DEV", "schema": "SOURCE"}}
}
```

Representative paths must have been inspected. IDs and mappings are retained by the caller, not copied into readiness output. This completeness check is not a Coalesce schema validator, authenticity proof, or permission to deploy. Native node/type definitions, stable identities, storage mappings, imports and platform compatibility still need their own reviewed evidence.

## Complex dbt prerequisites

The collector surfaces package declarations, project hooks/flags, vars/environment references, dispatched/project macros, introspection, incremental/snapshot behavior, unit-test/function resources, selected/state/deferred CI commands, version requirements and supplied manifest versions. Profiles are deliberately not read, so their templates and selected identity remain an explicit operator-review requirement. Root project macros are not categorically forbidden by the existing executor; their static detection calls for review before any compilation.

Keep assessment available for complex inputs. Do not loosen `run_dbt_project.py` or `verify_dbt_evidence.py` restrictions wholesale. For unsupported execution, preserve the original project and use a reviewed existing CI/operator route. Retain original artifact/query receipts and their limitations; a new UX record does not make those receipts pass the narrower bundled verifier. Stateful models need multi-run history, correction, deletion and recovery evidence independently of an initial build.

## Official platform references

These links were checked live on **2026-09-24**. They describe vendor formats/capabilities, not this accelerator's validation status.

- [dbt project configuration](https://docs.getdbt.com/reference/dbt_project.yml) defines the project file and configurable resource paths, flags, hooks and dispatch. [dbt environment variables](https://docs.getdbt.com/reference/dbt-jinja-functions/env_var) documents environment-dependent configuration. The collector observes references without resolving values.
- [Coalesce Git contents](https://docs.coalesce.io/docs/git-integration/what-gets-committed) documents native nodes, node types, mappings, jobs and project files; current node storage includes YAML and SQL forms. [Nodes and node types](https://docs.coalesce.io/docs/get-started/coalesce-fundamentals/nodes) and [storage locations/mappings](https://docs.coalesce.io/docs/get-started/coalesce-fundamentals/storage-locations-and-storage-mappings) distinguish native behavior from physical environment destinations. SQL files alone do not prove the required native contract.
- [Snowflake CREATE TABLE](https://docs.snowflake.com/en/sql-reference/sql/create-table) documents platform-specific DDL variants. A generated script still needs the selected environment, permissions, data and native validation.
- [Databricks SQL reference](https://docs.databricks.com/aws/en/sql/language-manual/) distinguishes SQL/Runtime syntax and configuration; [bundle settings](https://docs.databricks.com/aws/en/dev-tools/bundles/settings) describes the native bundle configuration used as a source-routing signal.
- [BigQuery overview](https://docs.cloud.google.com/bigquery/docs/introduction) identifies the warehouse product; [datasets](https://docs.cloud.google.com/bigquery/docs/datasets-intro) documents project/dataset identity and location. GCP names a broader platform and is not a sufficient warehouse selection.
- [Dataform compilation configuration](https://docs.cloud.google.com/dataform/docs/configure-compilation) documents the workflow settings and legacy JSON settings used for BigQuery source routing. SQLX and JavaScript are inventoried without compilation or execution.

## Extending the registry

Add a distinct source marker and target contract without conflating them. Document supported native format/version, current emitter/executor status, prerequisites, semantic limitations and primary documentation. Add synthetic tests for mixed sources, ambiguous generic SQL, incomplete scans, unsafe paths, unsupported configuration and drift. Existing qualification gates must continue rejecting unsupported evidence. A new registry entry or passing static test does not qualify a vendor execution path.
