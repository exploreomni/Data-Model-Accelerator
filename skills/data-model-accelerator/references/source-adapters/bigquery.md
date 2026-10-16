# BigQuery supplied-source adapter

Research reviewed: 2026-10-15. Implementation:
[`bigquery.py`](../../scripts/source_adapters/bigquery.py). Contract tests:
[`test_source_bigquery.py`](../../../../tests/test_source_bigquery.py).

## Compatibility and extraction contract

This is bounded static extraction from supplied UTF-8 text. BigQuery is a managed
service without a fixed database-engine version in this contract. The supported
metadata shapes are BigQuery REST **v2** `Table` and `Routine`, and Dataform REST
**v1** `compilationResults.query`. A JSON file may contain a single Table/Routine,
an array of these resources, or response collections named `tables`, `routines`
and `compilationResultActions`. Arbitrary INFORMATION_SCHEMA query-result JSON,
Dataform CLI graph JSON, and BigQuery job results are not interchangeable formats.
Unknown shapes produce gaps; filenames never supply missing identity.

| Supplied input | Extracted evidence | Boundary |
| --- | --- | --- |
| GoogleSQL `.sql` | Shared SQLGlot structural objects, projections, clauses and table references; exact source text | Static syntax is not native validation, physical binding or column-level lineage |
| Table resource JSON | Project/dataset/table identity, opaque native ID, recursive field paths, type/mode, original metadata, defaults, partitioning and clustering | No data profiling, enforced uniqueness or effective security claim |
| View/materialized-view definition | Exact query and structural SQL bound to its metadata owner | Ordinary views must explicitly set `useLegacySql: false`; absent setting is conservatively unresolved |
| Routine resource JSON | Identity, language, arguments and return metadata, exact body; supported SQL body structure | Scalar expressions, scripting, remote and other-language behavior may remain unresolved |
| Dataform query response | Action and canonical targets, source file, declared dependencies, relation/assertion/operation SQL, incremental SQL and options, column descriptions | Declaration metadata is documentation, not verified physical schema |
| SQLX or JavaScript | Original supplied source expression | No compilation; requires separately supplied compiled evidence |

The implementation uses the shared **SQLGlot 30.18.0** dependency pin and the
`bigquery` dialect. The [upstream parser documentation](https://sqlglot.com/)
explicitly distinguishes its lenient parser from database validation. All
expressions and dependencies retain their source path, JSON locator and file
hash. Project and dataset components remain separate metadata as well as qualified
names. Unknown fields are retained in their resource's raw metadata and produce
gaps at the supported object boundaries. Specialized external-table options are
retained with a metadata-only gap.

## Operator acquisition handoff — no network acquisition in this adapter

1. Establish the intended projects, datasets, locations, resource types and
   snapshot time outside the parser. Record the exporting principal and filters;
   do not supply credentials. Provide sanitized, authorized metadata snapshots.
2. Enumerate each dataset using
   [`tables.list`](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/tables/list),
   following every page token. It requires `bigquery.tables.list` and returns a
   partial table projection. Retrieve individual
   [`tables.get`](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/tables/get)
   resources with `bigquery.tables.get` for schemas and definitions; retain any
   field selections or metadata-view settings used during acquisition.
3. Enumerate
   [`routines.list`](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/routines/list)
   pages. Default list fields omit bodies. Retrieve
   [`routines.get`](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/routines/get)
   with `bigquery.routines.get`, or use an explicit list `readMask` that includes
   the required definitions. Retain the request settings. OAuth scopes do not
   by themselves establish IAM access to each resource.
4. For Dataform, supply every page of the same
   [`compilationResults.query`](https://docs.cloud.google.com/dataform/reference/rest/v1/projects.locations.repositories.compilationResults/query)
   result. Permission is `dataform.compilationResults.query`. Preserve compilation
   identity, code revision, overrides, variables and request filters in the
   external acquisition receipt. `filePath` filtering can omit actions even when
   the final page has no token. Compiled targets and canonical targets can differ.

The API does not embed all acquisition context in each response. This adapter
therefore always reports `export_completeness: not_established` and
`native_validation: not_run`. A non-empty `nextPageToken`, empty collection,
missing schema/body, absent declared target, duplicate identity or count mismatch
adds an explicit gap. It does not chase tokens or infer that another supplied
file closes a page chain. Keep separate compilations/snapshots in separate parse
runs: the adapter does not merge conflicting versions. SQL references are
unresolved catalogue evidence even when structural extraction succeeds.

## Primary research and reuse decisions

| Candidate/source | License or authority | Decision |
| --- | --- | --- |
| [SQLGlot](https://github.com/tobymao/sqlglot), [license](https://raw.githubusercontent.com/tobymao/sqlglot/main/LICENSE) | MIT | Reuse the pinned dependency through the shared helper. Do not vendor or rewrite its grammar; preserve dependency notices if redistributed. |
| [GoogleSQL, formerly ZetaSQL](https://github.com/google/googlesql), [license](https://raw.githubusercontent.com/google/googlesql/master/LICENSE) | Apache-2.0 | Candidate for future deeper analysis. Not added: separate native/Bazel integration and catalogue provisioning exceed this offline slice. Upstream states releases can break compatibility and the framework is not an officially supported Google product. |
| [Dataform core](https://github.com/dataform-co/dataform), [license](https://raw.githubusercontent.com/dataform-co/dataform/main/LICENSE) | Apache-2.0 | Do not import or run the compiler on supplied source. Accept the documented API export instead; no compiler code copied. |
| [Google Dataform v1 API definition](https://raw.githubusercontent.com/googleapis/googleapis/master/google/cloud/dataform/v1/dataform.proto) | Google API protobuf, Apache-2.0 | Shape authority for action unions, targets and fields; no generated SDK vendored. |
| [BigQuery Table](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/tables) and [Routine](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/routines) | Official REST v2 definitions | Field and default semantics, rather than source-format guesses. Reference text is paraphrased; no documentation or samples copied. |

Google's primary technical article,
[Transform SQL into SQLX for Dataform](https://cloud.google.com/blog/products/data-analytics/transform-sql-into-sqlx-for-dataform/)
(2023-02-08), demonstrates how SQLX combines configuration, JavaScript helpers
and dependency references. The current
[Dataform overview](https://docs.cloud.google.com/dataform/docs/overview)
describes compilation into SQL and a dependency tree. These support the design
decision to inspect supplied compiled exports instead of guessing SQLX expansion;
neither establishes that an exported compilation executed successfully.

## Explicit unsupported boundaries and verification

No API calls, warehouse jobs, Dataform compilation, JavaScript evaluation,
package hooks, dynamic SQL expansion, secret retrieval or source execution occur.
`EXECUTE IMMEDIATE` and templates remain source evidence with gaps. The dynamic
marker check is deliberately conservative and may flag marker text in a literal
or comment. Routine invocation lineage, script control flow, remote libraries,
row access policies, authorized views, effective IAM, wildcard expansion,
partition pruning and runtime incremental behavior require separate validation.
Dataform notebooks and data-preparation actions remain raw unsupported actions.

The independent synthetic tests exercise known field paths and values, exact
source preservation, SQL lineage, nested/repeated fields, partition/clustering
metadata, incremental Dataform expressions, omitted dependencies, malformed and
duplicate-key JSON, unknown fields and incomplete pagination. Passing them proves
the local bounded extractor behavior, not Google Cloud compatibility across all
features, source completeness, native execution or customer acceptance.
