# Snowflake supplied-source adapter

Research reviewed: **2026-10-15**. Implementation:
[`snowflake.py`](../../scripts/source_adapters/snowflake.py). Independent synthetic
checks: [`test_source_snowflake.py`](../../../../tests/test_source_snowflake.py).

## Compatibility and bounded contract

This adapter reads authorized UTF-8 snapshots offline. It does not contact
Snowflake, execute SQL, load credentials, invoke Snowflake CLI, or execute project
code. Snowflake is a managed service; this contract pins the SQL API **v2** response
shape and **SQLGlot 30.18.0** `snowflake` dialect, not a Snowflake engine release.

| Input | Extracted evidence | Explicit boundary |
| --- | --- | --- |
| `.sql`, including supplied GET_DDL text | Exact SQL, structural table/view declarations, columns, declared keys, projections, clauses and unresolved references through the shared SQL parser | No execution, schema qualification from session defaults, physical column lineage, or semantic equivalence claim |
| SQL API `ResultSet` JSON | Native `statementHandle`, result metadata, result columns, row locators and declared/supplied row counts | A query result column is not a physical catalogue column; status and provenance are supplied, not authenticated |
| CLI JSON/JSON_EXT row arrays for `INFORMATION_SCHEMA.COLUMNS` | Database/schema/table/column components, type, nullability, ordinal, comment, exact default expression and original row metadata | Requires uppercase documented keys and explicit full identity; precision, scale and ancillary metadata are retained in `raw_metadata` |
| `INFORMATION_SCHEMA.TABLES` rows | Qualified relation identity, type, comment and original metadata | A view row does not contain the SQL body; no view dependency is invented |
| `SHOW COLUMNS` rows | Stored case-sensitive names, JSON type details, nullability, comments, default and virtual-column expressions | Accepts CLI JSON string or JSON_EXT object for `data_type`; dimensions/facts/metrics in semantic views are outside this slice |
| `SHOW PRIMARY KEYS` rows | Table, constraint, column and key ordering | Declaration only; does not assert uniqueness or enforcement |
| `INFORMATION_SCHEMA.POLICY_REFERENCES` rows | Policy identity/kind/status and a declared association to an explicitly qualified TABLE/VIEW | Bodies, grant closure, tag propagation and effective user access remain unverified; other target domains remain unresolved |

The two supported JSON containers are actual documented formats: the SQL API
response object and Snowflake CLI's unwrapped array of row objects. There is no
invented `tables`/`columns` wrapper. A row must match a supported metadata signature;
renamed projection fields, arbitrary query rows, incomplete identity, data-only
partition files and custom envelopes produce explicit gaps. File paths never
supply missing database/schema identity. Stored identifier components are retained
and independently quoted to avoid collisions involving dots, quotes or case.
Native object IDs are not fabricated from qualified names. The SQL API statement
handle is the only native ID supplied by these implemented contracts.

Every SQL/JSON source retains its exact text and SHA-256 evidence. Nested
repository-relative paths and locators are preserved. Original metadata rows
retain ancillary properties without implying their behavior has been modeled.
All runs report `export_completeness: not_established`, `native_validation:
not_run`, and `execution_performed: false`.

## Acquisition handoff and omissions

Acquisition is a separate authorized workflow. Preserve the account, exporting
principal/role, database, query or SHOW scope, filters, snapshot time and acquisition
receipt outside these snapshots. Do not include secrets in supplied source files.
The official [authentication guide](https://docs.snowflake.com/en/developer-guide/sql-api/authenticating)
documents OAuth, key-pair JWT and workload identity federation; the
[API reference](https://docs.snowflake.com/en/developer-guide/sql-api/reference)
also defines the programmatic-access-token header type. Authentication does not
establish visibility into every object.

The [SQL API response guide](https://docs.snowflake.com/en/developer-guide/sql-api/handling-responses)
describes `rowType`, string/null `jsonv2` cells and `partitionInfo`. Retrieve every
partition using the native statement handle and partition parameter during
separately authorized acquisition. Additional partition bodies may be gzip data
without sufficient metadata for this standalone reader. This slice deliberately
does not bind data-only partitions to adjacent files, follow URLs, merge partition
chains, or infer that repeated handles close an export. Multiple declared
partitions and count mismatches remain gaps. Multi-statement summary responses
require the individual statement results.

[Snowflake CLI `snow sql`](https://docs.snowflake.com/en/developer-guide/snowflake-cli/command-reference/sql-commands/sql)
documents JSON as row arrays and JSON_EXT's handling of nested objects. The reader
accepts only supplied output; it never processes CLI templates, connection
configuration, a `snowflake.yml` deployment bundle, or embedded executable code.
These inputs are accounted for as unsupported files.

Catalogue/security limits that need independent reconciliation:

- [SHOW COLUMNS](https://docs.snowflake.com/en/sql-reference/sql/show-columns)
  visibility depends on role privileges and the result is limited to 10,000
  records. Record the selected scope; an apparently complete JSON array is not
  proof that all account columns were exported.
- [COLUMNS](https://docs.snowflake.com/en/sql-reference/info-schema/columns) and
  [TABLES](https://docs.snowflake.com/en/sql-reference/info-schema/tables) are
  database-scoped catalogue views. Their rows supply declarations, not observed
  grain, data quality, current row access behavior or an account-wide denominator.
- [SHOW PRIMARY KEYS](https://docs.snowflake.com/en/sql-reference/sql/show-primary-keys)
  distinguishes unenforced standard-table primary keys from enforced hybrid-table
  primary keys. This adapter conservatively labels enforcement unverified.
- [POLICY_REFERENCES](https://docs.snowflake.com/en/sql-reference/functions/policy_references)
  is privilege-filtered. Its status, target columns and tag fields are retained;
  a policy association or ACTIVE status is not a persona access test.
- [GET_DDL](https://docs.snowflake.com/en/sql-reference/functions/get_ddl) is a
  reconstruction API with object/privilege-specific behavior, not an authenticated
  copy of original authored SQL. Preserve export settings and independently check
  definitions, grants and security coverage. Security clauses or unknown markers
  in supplied text are explicitly flagged by this adapter.

Dynamic SQL, procedures/UDFs, scripting blocks and templates are retained as
source units without runtime-read claims. The precheck is intentionally
conservative and can also flag such words inside comments/literals. Statements
outside the shared TABLE/VIEW/query subset remain gaps. Tasks, streams, Snowpark,
external functions, integrations, grants, full policies, dynamic/semantic tables
and deployment orchestration need their own versioned contracts. No lack of a
security attachment in a snapshot means an object is unrestricted.

## Primary research and reuse decision

| Candidate | License / authority | Decision |
| --- | --- | --- |
| [SQLGlot](https://github.com/tobymao/sqlglot), [license](https://raw.githubusercontent.com/tobymao/sqlglot/main/LICENSE), [dialect implementation](https://github.com/tobymao/sqlglot/blob/main/sqlglot/dialects/snowflake.py) | MIT; upstream parser | Reuse the existing pinned dependency through `parse_sql`; no grammar copied or forked. Preserve upstream notices if redistributed. |
| [SQLFluff dialect documentation](https://docs.sqlfluff.com/en/stable/reference/dialects/), [license](https://raw.githubusercontent.com/sqlfluff/sqlfluff/main/LICENSE.md) | MIT; upstream project | A Snowflake-aware parser/linter alternative. Not added: another parser adds dependency and AST normalization work without native validation. |
| [SQLGlot contributor technical guide](https://github.com/tobymao/sqlglot/blob/main/posts/onboarding.md) | Upstream primary technical article | Explains dialect-specific identifier normalization and catalogue-dependent qualification. Supports keeping physical binding unresolved without a matching schema. |
| [SQL API introduction](https://docs.snowflake.com/en/developer-guide/sql-api/intro) and [response handling guide](https://docs.snowflake.com/en/developer-guide/sql-api/handling-responses) | Vendor primary technical guides | Contract authority for acquisition limits, query result metadata and partitions; no network client or sample implementation copied. |

The local tests cover SQL syntax/dependencies, metadata and policy fidelity,
case-sensitive identities, nested paths/hashes, malformed JSON/shape/types,
duplicates, partial partitions, unsupported envelopes, missing optional parser,
non-execution and registry-contract validity. Passing them establishes this
bounded offline slice only. Native Snowflake compilation, complete export scope,
effective security and business acceptance remain separate validation lanes.
