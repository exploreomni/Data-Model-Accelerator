# Platform capability matrix

The accelerator has six selectable warehouse profiles. A profile supplies routing, metadata templates, SQLFluff dialect and validation recipes; it does **not** establish live-provider qualification. `skills/data-model-accelerator/scripts/platform_matrix.py` is the shared source for intake, readiness, catalogue providers, specialist source types and hosted deployment compatibility.

| Warehouse | SQLFluff 4.3.0 dialect | dbt Core candidate | dbt platform route | Coalesce candidate |
|---|---|---|---|---|
| Snowflake | `snowflake` | Conditional adapter/runtime | Conditional hosted job/runtime | Conditional native contract |
| Databricks | `databricks` | Conditional adapter/runtime | Conditional hosted job/runtime | Conditional native contract |
| BigQuery | `bigquery` | Conditional adapter/runtime | Conditional hosted job/runtime | Conditional native contract |
| Redshift | `redshift` | Conditional adapter/runtime | Conditional hosted job/runtime | Unsupported |
| ClickHouse | `clickhouse` | Conditional dbt-clickhouse/server | Unsupported by this adapter; docs say **Private beta** | Unsupported |
| MotherDuck | `duckdb` | Conditional dbt-duckdb/client/extension | Unsupported; DuckDB docs specify **CLI only** | Unsupported |

Native SQL candidate authoring is available for all six. Intake keeps `dbt`, `coalesce`, `native_sql` separate from the warehouse; it does not ask the engineer to select a hosting product as a transformation framework. GCP remains unresolved until BigQuery or another explicit product is confirmed. Existing projects retain their qualified runtimes. No automatic upgrade or installation is implied.

The hosted matrix follows current [dbt adapter lifecycle documentation](https://docs.getdbt.com/docs/supported-data-platforms); local adapter availability does not establish a hosted connection. Coalesce remains conditional because its [CLI overview](https://docs.coalesce.io/docs/coa/version-733-and-above) states Snowflake-only support while newer [setup guidance](https://docs.coalesce.io/docs/coalesce-ai/local-development/setup-guide) documents Databricks and BigQuery (7.40+). Supplying native IDs or a storage mapping does not override an unsupported route. These source labels were checked September 24, 2026.

## Metadata delivery matrix

The versioned `metadata_platforms.py` profiles distinguish implemented projections, local contract tests and live qualification. All rows share dictionary v2, explicit physical bindings, read queries, difference planning, expected-state verification and guided review. dbt property generation applies to a selected supported dbt project; adapter-specific persistence still requires native qualification.

| Warehouse | Generated comments | Generated tag assignments | Remaining scope limits |
|---|---|---|---|
| Snowflake | Table/view and columns | Existing informational custom tags | Preview/system tags and security-bound tags blocked |
| Databricks | Table/view and top-level columns | Unity Catalog object/table-column tags | Column comments need SQL/Runtime 16.1+; view-column tags excluded |
| BigQuery | Table/view and top-level columns | No default tag emitter | Nested fields, security policy tags and Preview governance tags require separate paths |
| Redshift | Current-database table/view and columns | Dictionary only | External and late-binding objects excluded |
| ClickHouse | Table and columns | Dictionary only | Local selected engine/replica; no inferred cluster propagation |
| MotherDuck | Table/view and table columns | Dictionary only | Remote identity/version/dependency qualification; local DuckDB tests only |

Native metadata dispatch is simulated locally; automatic live dispatch is blocked pending an authenticated drift collector. Coalesce shares the metadata contract on its existing conditional pairings, but native node-documentation projection is not implemented. Unsupported Coalesce pairings remain unsupported. [Metadata operator guide and official capability sources](../skills/data-model-accelerator/references/warehouse-metadata.md).

## Validation boundaries

| Surface | Recipe | What remains unproved |
|---|---|---|
| All six | SQLFluff 4.3.0 with the explicit dialect and complete file/hash coverage | Vendor grammar coverage, references, native types, access and data accuracy; MotherDuck cloud extensions exceed the DuckDB baseline |
| Snowflake | `EXPLAIN USING JSON <eligible_statement>` | Unsupported DDL/scripting and execution behavior; compilation consumes Cloud Services resources |
| Databricks | `EXPLAIN FORMATTED <query>`; selected bundle `validate` | All SQL/job behavior; connected compute and configuration identity still require review |
| BigQuery | `bq ... query --use_legacy_sql=false --dry_run <query>` | Complete scripts: DDL stops after the first DDL; CALL bodies, dynamic SQL and control flow limit coverage |
| Redshift | `EXPLAIN <eligible_statement>` | Arbitrary DDL, distribution/sort design, actual data behavior; planning needs authorized compute |
| ClickHouse | `clickhouse-format --quiet --multiquery` with the script on stdin; connected `EXPLAIN PLAN` | Syntax check is not semantic lint. Engine/reference/cluster behavior remains separate; EXPLAIN ANALYZE executes |
| MotherDuck | `EXPLAIN` in an explicit `md:DATABASE` connection | Local DuckDB is not proof of remote identity or cloud features; EXPLAIN ANALYZE executes |

Each machine profile includes exact recipe placeholders, connection requirements, cost, side effects, uncovered cases and its official source. Recipes are never executed by the matrix or static readiness collector. Use the [authorized deployment runner](DEPLOYMENT.md) for separately approved connected checks; a generic plan/compile command is not a safe sandbox for arbitrary project code.

Official contracts: [SQLFluff dialects](https://docs.sqlfluff.com/en/stable/reference/dialects.html), [Snowflake EXPLAIN](https://docs.snowflake.com/en/sql-reference/sql/explain), [Databricks EXPLAIN](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-qry-explain), [BigQuery dry-run limits](https://cloud.google.com/bigquery/docs/multi-statement-queries#dry-run_a_multi-statement_query), [Redshift EXPLAIN](https://docs.aws.amazon.com/redshift/latest/dg/r_EXPLAIN.html), [ClickHouse syntax utility](https://clickhouse.com/docs/concepts/features/tools-and-utilities/clickhouse-format), [MotherDuck planning](https://motherduck.com/docs/key-tasks/query-performance).

## Metadata and framework checks

Use only the selected [catalogue provider template](../skills/data-model-accelerator/references/catalogue-providers.md). Templates read system metadata, retain explicit namespace and identity requirements, and are not live-validated collectors. ClickHouse's canonical schema marker is never a native schema; MotherDuck attachment identity must distinguish remote data from local DuckDB. Preserve engine/type details, visibility gaps and original exports before normalization.

`dbt parse` checks project structure without native query validation; it does not produce compiled SQL. `dbt compile` and SQLFluff's dbt templater can execute reviewed macros and issue warehouse queries. Qualify the exact Core/adapter/templater combination and capture rendered hooks, tests and materializations. Native `dbt lint` is **Available in v2**, has its own runtime/dialect limits and uses symbolic or stubbed template rendering; it does not make SQLFluff's v1 dbt templater v2-compatible. [dbt parse](https://docs.getdbt.com/reference/commands/parse), [dbt compile](https://docs.getdbt.com/reference/commands/compile), [native lint](https://docs.getdbt.com/reference/commands/lint)

`coa validate` checks native YAML/graph configuration. Capture the Create/Run SQL from the qualified dry-run preview and lint it separately; a preview does not validate the entire cloud deployment. No separate `coa lint` command is claimed. [Coalesce commands](https://docs.coalesce.io/docs/coa/version-733-and-above/coa-commands)

Run the bounded registry/readiness tests with `python3 -m unittest discover -s tests -p 'test_platform*.py'`. Tests cover shared selections, unsupported pairs, synthetic catalogue contexts and recipe boundaries. A passing local test is not a native deployment, business approval or security acceptance.
