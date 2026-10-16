# MotherDuck / DuckDB supplied-source adapter

Research reviewed: 2026-10-15. Implementation:
[`motherduck.py`](../../scripts/source_adapters/motherduck.py). Independent tests:
[`test_source_motherduck.py`](../../../../tests/test_source_motherduck.py).

## Supported contract

This first slice parses supplied UTF-8 snapshots using shared SQLGlot 30.18.0's
`duckdb` dialect. It never connects to a database, imports a DuckDB driver,
executes SQL or source programs, opens referenced files, installs extensions,
attaches databases or accesses the network. DuckDB local compatibility is not
MotherDuck native qualification.

| Input | Extraction | Explicit boundary |
| --- | --- | --- |
| `.sql` | Original SQL, supported relation/column declarations, types/default clauses/declared keys, query expressions and unresolved reads | Runtime syntax, session/search path, external resources and cloud placement remain unverified |
| `duckdb_tables()` JSON row array | Namespace, table OID, comment, declared primary-key indicator, raw metadata and creation SQL when supplied | OIDs are snapshot evidence, not durable cross-export IDs; no observed uniqueness or grain |
| `duckdb_columns()` row array | Namespace, name, native type, native ordinal, default expression, comment, nullability and raw metadata | Native `column_index` is retained without converting it to information-schema ordinal semantics |
| `duckdb_views()` row array | Namespace, view OID, comment and creation SQL; scoped SQL reads retain attached database components | Attachment aliases do not authenticate their remote destinations |
| `duckdb_constraints()` row array | Constraint type/text, column names, raw metadata; aligned foreign-key source/target names | Referenced table names remain literal and unresolved; target database/schema are not inferred |
| `information_schema.tables`, `.columns`, `.table_constraints` row arrays | Documented table types, column declarations and constraint metadata | No view SQL or foreign-key target inferred from incomplete constraint metadata |
| `duckdb_databases()` row array | Attachment name/OID/type/readonly evidence and raw metadata | Does not establish cloud identity, organization or effective shared permissions |

DuckDB documents the [native metadata function fields](https://duckdb.org/docs/current/sql/meta/duckdb_table_functions)
and [information-schema views](https://duckdb.org/docs/current/sql/meta/information_schema).
Use their exact lower-case result-column names. Arrays are query-result exports,
not a vendor modeling-project format. The parser deliberately does not invent a
MotherDuck JSON envelope. Signature matches are catalogue **candidates**; an
arbitrary query can emit identical names, so provenance remains unverified.

Missing namespace components remain null. Paths, basenames, current database and
`main` are never used to fill them. Duplicate identities are retained separately
and flagged; pages/snapshots are not merged. Unknown fields and malformed values
remain visible in gaps and original source evidence. All inputs keep hashes and
nested repository-relative locators. JSON is bounded to 8 MiB per file, 32 MiB per
run, 512 files, 150,000 nodes and depth 48 by the shared contract; these are parser
limits, not MotherDuck service quotas.

## Acquisition handoff and current API boundary

Acquisition is an independently authorized operator activity. Record the source
organization, principal, database and attachment identities, DuckDB/MotherDuck
versions, exact metadata queries, filters and snapshot time. Keep secrets and
private attachment paths out of supplied snapshots. Missing/filtered/empty
metadata is a coverage gap, not proof that no object exists.

The current [connection guide](https://motherduck.com/docs/key-tasks/authenticating-and-connecting-to-motherduck/connecting-to-motherduck)
documents DuckDB SDK/CLI connections using `md:<database>` and a separate Postgres
endpoint. The token may be provided through configuration or the
`motherduck_token` environment variable; do not embed token values in evidence.
The [connection parameter reference](https://motherduck.com/docs/sql-reference/connection-string-parameters)
distinguishes default workspace attachment from `attach_mode=single`. The latter
requires an explicit database and scopes the session. `saas_mode=true` limits
local filesystem, extension and configuration access; it is not a completeness
or authorization attestation. Retain the actual connection mode used.

The [Admin REST API reference](https://motherduck.com/docs/sql-reference/rest-api/motherduck-rest-api/)
labels the API **Preview** and describes user/token and Duckling administration;
admin methods require appropriate Read/Write admin-token authorization. Its
[official readable reference](https://motherduck.com/docs/sql-reference/rest-api/llms-full.txt)
was available during research, while the HTML endpoint was not readable through
the research tool. No public complete modeling export or general SQL-execution
endpoint was established from that Admin REST contract. This is a bounded
research finding, not a claim that MotherDuck lacks query APIs: SQL clients and
the [official MCP interface](https://motherduck.com/docs/llms.txt) are distinct
query surfaces. Neither is invoked by this adapter. A general Admin API request
quota was not established from the reviewed reference; verify live quotas and
permission scope before implementing acquisition.

Export explicit metadata SELECT results as JSON arrays using a separately
authorized client serializer, or DuckDB's
[COPY JSON `ARRAY` option](https://duckdb.org/docs/current/sql/statements/copy#json-options).
DuckDB's [default JSON export](https://duckdb.org/docs/current/data/json/writing_json)
is newline-delimited; NDJSON, CSV, Parquet and binary `.duckdb` files are not
accepted by this slice. Supply native creation SQL separately where needed.
The existing [metadata query starter](../../examples/catalogue-queries/motherduck.sql)
is an operator reference, not proof that any query has run.

## Review gaps and reuse decisions

External table functions, URI/file references, credential declarations, dynamic
query calls, ATTACH/extension/session commands and sharing/permissions receive
conservative review hints. These textual checks can overflag comments and are
not a credential scanner or security boundary. The boundary is that no source
code executes. Original source is retained, so sanitization must happen before
ingestion. Macros, functions, policies, `md_information_schema` sharing history,
data movement, local/remote execution and effective access require separate
native evidence. Every result retains `execution_performed: false`,
`native_validation: not_run` and `export_completeness: not_established`.

| Candidate / primary source | License / authority | Decision |
| --- | --- | --- |
| [SQLGlot](https://github.com/tobymao/sqlglot), [license](https://raw.githubusercontent.com/tobymao/sqlglot/main/LICENSE) | MIT | Reuse the existing pinned parser; preserve notices on redistribution; no new dependency |
| [DuckDB](https://github.com/duckdb/duckdb), [license](https://raw.githubusercontent.com/duckdb/duckdb/main/LICENSE) | MIT | Useful separately authorized acquisition/runtime tool, not imported or vendored here; local execution cannot qualify MotherDuck |
| [MotherDuck local MCP server](https://github.com/motherduckdb/mcp-server-motherduck), [license](https://raw.githubusercontent.com/motherduckdb/mcp-server-motherduck/main/LICENSE) | MIT | Potential acquisition integration; rejected as an offline parsing dependency because it executes queries. Preserve applicable notices if later reused |
| [MotherDuck metadata/API engineering update](https://motherduck.com/blog/data-warehouse-feature-roundup-dec-2024/) | Vendor technical article, 2024-12-21 | Explains `MD_INFORMATION_SCHEMA`, shares and administrative API context; historical article does not establish current release or complete model coverage |
| [MotherDuck's DuckDB/dbt engineering walkthrough](https://motherduck.com/blog/duckdb-dbt-e2e-data-engineering-project-part-2/) | Vendor technical article | Demonstrates macros, hooks, credentials and export behavior that must remain outside this offline parser |

The independent tests cover native and information-schema shapes, quoted
namespaces, types/defaults/comments/keys, cross-database view reads, missing
scope, malformed/unknown JSON and metadata, duplicate identities, unsafe runtime
statements, optional SQL parser absence and registry validation. Passing these
tests establishes bounded extraction only. Native compatibility, permission
validation, full export coverage and customer acceptance remain unqualified.
