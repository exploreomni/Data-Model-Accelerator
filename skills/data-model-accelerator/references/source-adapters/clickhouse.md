# ClickHouse supplied-source adapter

Research reviewed: **2026-10-15**. Implementation:
[`clickhouse.py`](../../scripts/source_adapters/clickhouse.py). Independent tests:
[`test_source_clickhouse.py`](../../../../tests/test_source_clickhouse.py).

## Supported evidence and qualification

This first slice accepts supplied UTF-8 `.sql` and native `FORMAT JSON` response
bodies. It never contacts ClickHouse, runs SQL, imports source projects or follows
URLs. It uses the shared **SQLGlot 30.18.0** pin with the
[`clickhouse` dialect](https://sqlglot.com/sqlglot/dialects/clickhouse.html).
Compatibility is a tested syntax subset, not a qualified server-version range.
Record the actual ClickHouse version separately when acquiring source evidence.

| Native input | Retained/extracted evidence | Qualification boundary |
| --- | --- | --- |
| SQL DDL, views and queries | Exact SQL; supported declarations, column types/default/materialized/alias/comment clauses, engine and sort/partition properties, structural projections and unresolved table reads | No native compilation, physical binding, actual grain or complete lineage claim |
| `FORMAT JSON` response | Exact original JSON, output `meta`, row counts, statistics and other response metadata | `meta` describes query-result headers, never source-table columns |
| Rows matching `system.tables` fields | `table_catalogue_candidate`, database/name/UUID, engine, keys, comment, original row, supplied definition SQL and labeled dependency candidates | Shape recognition does not authenticate the originating query, namespace, snapshot or server |
| Rows matching `system.columns` fields | `column_catalogue_candidate`, database/table/name/type, defaults, comments, original metadata, unresolved `candidate_column_of` | Key membership is metadata evidence, not enforced uniqueness |
| DESCRIBE-shaped rows | Unbound column candidates with defaults, codec, TTL and subcolumn metadata | No table identity is inferred from paths or headers; DESCRIBE can also describe query output |

Native JSON uses `meta`, `data`, `rows` and optional statistics/limit/totals fields.
It does **not** identify the original SQL or physical source. Consequently every
JSON result has `query_provenance_unresolved`; candidate names never become
verified physical bindings automatically. No custom envelope is required or
presented as a vendor export. Supply qualified DDL and independent acquisition
context for later review. See the official
[JSON format](https://clickhouse.com/docs/reference/formats/JSON/JSON).

Recognized row signatures are `database/name/engine` for table candidates,
`database/table/name/type` for column candidates, and
`name/type/default_type/default_expression` for unbound DESCRIBE candidates.
Rows lacking those signatures remain original query evidence. An arbitrary query
can return these names, which is why candidates always carry
`provenance: row_signature_only` and `namespace_verified: false`.

The official [system.tables contract](https://clickhouse.com/docs/reference/system-tables/tables)
defines engine, creation query, sort/primary/partition keys and paired dependency
arrays. The adapter labels `dependencies_*` as `catalogue_dependent_view`, not
upstream SELECT reads; loading prerequisites and materialized-view destinations
have separate kinds. All targets remain unresolved. Detached tables are omitted
from that system table, and temporary-table visibility is session-specific;
empty-database temporary identities remain unsupported.

The [system.columns contract](https://clickhouse.com/docs/reference/system-tables/columns)
provides typed column metadata, default kinds and key-membership flags.
[DESCRIBE TABLE](https://clickhouse.com/docs/reference/statements/describe-table)
uses `default_type` instead of `default_kind` and may expose subcolumns. It also
supports describing SELECT output. The adapter preserves nested names verbatim,
without treating every dot as a separately established physical column hierarchy.

## Acquisition handoff — operator work, not implemented network behavior

Use an authorized principal and retain version, endpoint identity, database,
query text, selected fields, filters, settings, roles and snapshot time in the
external acquisition record. Exclude credentials from supplied files. Export
approved `system.tables` and `system.columns` selections with `FORMAT JSON`,
qualified creation statements and, where needed, DESCRIBE output. Separate
different snapshots rather than silently combining conflicting versions.

The official [HTTP interface documentation](https://raw.githubusercontent.com/ClickHouse/clickhouse-docs/main/docs/integrations/interfaces/http.md)
describes GET read-only queries and POST query bodies. Authentication supports
Basic authentication or `X-ClickHouse-User`/`X-ClickHouse-Key`; URL credentials are
discouraged because they can be logged. Database and query settings affect
interpretation. The interface streams output: HTTP 200 alone does not establish
success, because errors can appear later in the body. Preserve and inspect the
complete response; buffering with `wait_end_of_query` has documented caveats.
The adapter rejects malformed JSON and treats a supplied exception as a gap,
without extracting candidate rows from that response.

This SQL-result protocol is not a token-paginated catalogue listing. If an
operator splits exports with SQL limits, retain the exact boundaries and all
results. [LIMIT documentation](https://clickhouse.com/docs/reference/statements/select/limit)
warns that results without ORDER BY can vary, and settings may impose limits.
Recommendation: use explicit stable ordering and non-overlapping bounds against
one controlled snapshot, then independently reconcile scope and counts. The
adapter does not fetch later chunks or infer completeness from a matching row
count; a `rows_before_limit_at_least` value above supplied rows produces a gap.
That field is a lower estimate, so its absence or equality is not proof of full
coverage. Empty results, duplicate identities and missing/inconsistent counts
also remain explicit gaps.

## Semantics deliberately left unresolved

- ORDER BY and PRIMARY KEY are sort/sparse-index evidence. They never establish
  row uniqueness or business grain. The official
  [MergeTree reference](https://clickhouse.com/docs/reference/engines/table-engines/mergetree-family/mergetree)
  supplies the storage-engine semantics; this adapter does no data profiling.
- Materialized-view declarations do not prove trigger/refresh state, historical
  population, backfill, target freshness or acceptance. AggregateFunction and
  SimpleAggregateFunction types do not prove state/finalized-result equivalence.
- MergeTree-family declarations and FINAL require runtime review for merging,
  replacement, collapsing, mutations and data visibility. Conservative marker
  checks may also flag those words in comments or literals.
- The [Distributed engine](https://clickhouse.com/docs/reference/engines/table-engines/special/distributed)
  depends on cluster topology and remote tables. Engine strings are preserved;
  this slice does not invent remote bindings or validate delivery/shard behavior.
- Table functions, dynamic or templated SQL, macros, dictionaries, permissions,
  row policies, encryption, external storage, effective security and unsupported
  syntax require separate evidence. SQLGlot support is not ClickHouse validation.

## Primary research and parser reuse

| Source/candidate | Authority/license | Decision |
| --- | --- | --- |
| [SQLGlot](https://github.com/tobymao/sqlglot), [license](https://raw.githubusercontent.com/tobymao/sqlglot/main/LICENSE) | MIT | Reuse the existing pinned parser through the shared helper; no copied grammar or additional dependency. Retain upstream notices if redistributed. |
| [ClickHouse native parsers](https://github.com/ClickHouse/ClickHouse/tree/master/src/Parsers), [license](https://raw.githubusercontent.com/ClickHouse/ClickHouse/master/LICENSE) | Apache-2.0 | Native C++ grammar is an authority/candidate for future version-specific qualification. Not embedded, built or executed in this offline slice. No upstream code copied. |
| [Using Materialized Views in ClickHouse](https://clickhouse.com/blog/using-materialized-views-in-clickhouse) | Primary vendor technical article | Insert-trigger and joined-source examples justify separate target/backfill/runtime evidence; examples do not prove behavior of a supplied customer snapshot. |
| [A simple guide to ClickHouse query optimization: part 1](https://clickhouse.com/blog/a-simple-guide-to-clickhouse-query-optimization-part-1) | Primary vendor technical article | Explains sparse indexes and lack of primary-key uniqueness enforcement, supporting the explicit uniqueness gap. |

## Verification and output status

The tests assert independent identities, retained expressions, metadata-versus-
query-header separation, unbound DESCRIBE scope, CTE-aware references, key
semantics, runtime gaps, invalid/unknown shapes, duplicate JSON keys, incomplete
results, dependency-array mismatches, safe nested paths and the shared registry
contract. SQL tests skip only when SQLGlot is absent; a separate test verifies
that an absent parser produces an explicit gap.

Shared limits bound file count, bytes, structure and nesting. Every accepted file
is accounted for with a checksum and supported/partial/unsupported coverage.
All outputs retain `execution_performed: false`, `native_validation: not_run` and
`export_completeness: not_established`. Passing synthetic offline checks proves
extractor behavior only, not native compatibility, export completeness,
production readiness or customer acceptance.
