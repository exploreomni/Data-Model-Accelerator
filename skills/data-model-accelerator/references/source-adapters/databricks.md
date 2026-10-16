# Databricks source adapter

Research checked **2026-10-15**. This is bounded offline extraction from supplied
exports. It does not connect to Databricks, authenticate, execute SQL, start Spark,
import Python, install an SDK, or qualify native behavior.

## Implemented input boundary

- `.sql` selected explicitly as Databricks: shared SQLGlot structural extraction
  with the `databricks` dialect. Original SQL remains authoritative. Recognized
  procedural/dynamic SQL, `IDENTIFIER(...)`, notebook headers and magic commands
  remain opaque. Session namespace and parameter bindings are unresolved.
- `.json`: the native Unity Catalog **TableInfo** object from Get Table, or the
  native **ListTables** response with `tables` and optional `next_page_token`.
  No adapter-specific vendor envelope is accepted. Arrays, notebook JSON, job
  responses and mixed response envelopes are not inferred as table metadata.
- Other supplied files remain preserved, unsupported and unexecuted. A `.py`
  extension does not establish Databricks provenance. Bundle YAML, jobs,
  pipelines, workspace archives, notebook cells and runtime code need a separate
  bounded implementation; no DBC/ZIP extraction occurs here.

Example native response shape, using synthetic identifiers:

```json
{
  "tables": [{
    "name": "orders",
    "catalog_name": "analytics",
    "schema_name": "sales",
    "full_name": "analytics.sales.orders",
    "table_id": "synthetic-table-id",
    "table_type": "MANAGED",
    "columns": [{"name": "id", "type_text": "bigint", "position": 0, "nullable": false}]
  }]
}
```

Extraction preserves native table ID, explicit catalog/schema/name components,
table type, comments, full type metadata, nullable/ordinal values, properties,
view SQL, constraints, row filters and column masks when supplied. Raw metadata
and original text remain bound to repository-relative path, locator and SHA-256.
Missing namespaces are never filled from filenames or guessed by splitting
`full_name`. Contradictory explicit identity, malformed columns/policies,
duplicate snapshots, unknown fields, missing definitions and pagination become
visible gaps. Constraint and policy references remain unresolved; absent policies
do not establish unrestricted access.

## Documented contracts and acquisition limits

| Primary source | Consequence for extraction |
| --- | --- |
| [Get Table / TableInfo API](https://docs.databricks.com/api/uc-tables/v1/get-table) | Documents native names/IDs, ColumnInfo, view SQL, constraints, filters and masks. Metadata reflects the acquiring principal; `include_browse` can expose selective metadata. Get Table is labeled **GA** in the reviewed reference. |
| [ListTables API](https://docs.databricks.com/api/uc-tables/v1/list-tables) | List Tables is **GA**. It omits `view_dependencies` and `table_constraints`; options can omit columns, properties or usernames. Continue pagination until `next_page_token` is absent, including empty pages with tokens. Access depends on table privileges/ownership and catalog/schema access. Supplied snapshots cannot authenticate the request scope, principal, or page chain. |
| [OAuth service-principal authorization](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-m2m) | An authorized future collector would require workspace identity, OAuth and resource permissions. Credentials are outside this adapter's inputs and it performs no acquisition. |
| [CREATE TABLE language reference](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-table-using) | DDL supports source formats, properties, generated/default expressions, comments, constraints and policy clauses. Key declarations are informational. Parser acceptance proves neither Databricks acceptance nor key integrity. |
| [Notebook import/export](https://docs.databricks.com/aws/en/notebooks/notebook-export-import) | Source exports use notebook markers; generic Python is not sufficient provenance. Notebook formats can include outputs. Review/sanitize exports before supplying them. |
| [Lakeflow pipeline concepts](https://docs.databricks.com/aws/en/ldp/concepts) | Pipelines use SQL and Python and coordinate batch/streaming flows. A static table declaration does not establish orchestration, refresh, checkpoint or runtime behavior. |

The vendor technical article [Feature Deep Dive: Watermarking in Apache Spark
Structured Streaming](https://www.databricks.com/blog/feature-deep-dive-watermarking-apache-spark-structured-streaming)
(2022-08-22) explains why late events, state eviction, stream joins and output mode
must be evaluated together. It informs the explicit runtime gap; it is not a
release-status source or validation of a supplied customer's pipeline.

## Parser research and choice

| Candidate | License and assessment |
| --- | --- |
| [SQLGlot Databricks dialect](https://sqlglot.com/sqlglot/dialects/databricks.html) | [MIT](https://github.com/tobymao/sqlglot/blob/main/LICENSE). Selected through the shared pinned optional parser. Its Databricks dialect derives from Spark; structural extraction remains bounded and parser failures preserve original SQL. |
| [Apache Spark SQL grammar](https://github.com/apache/spark/blob/master/sql/api/src/main/antlr4/org/apache/spark/sql/catalyst/parser/SqlBaseParser.g4) | [Apache-2.0](https://github.com/apache/spark/blob/master/LICENSE). Useful primary grammar reference; adopting it would require parser/build integration and would not establish coverage of Databricks extensions. Not imported or executed. |
| [Databricks Python SDK](https://github.com/databricks/databricks-sdk-py) | [Apache-2.0](https://github.com/databricks/databricks-sdk-py/blob/main/LICENSE). Metadata/API client candidate, not a SQL or notebook semantic parser. Excluded from offline dependencies and acquisition. |

JSON uses the shared bounded standard-library reader with duplicate-key,
nonfinite-number, size, depth and node checks. Missing SQLGlot produces an
explicit gap; JSON metadata still works without optional packages. New fields or
table kinds remain preserved and flagged rather than silently acquiring invented
semantics.

## Verification and remaining boundary

`tests/test_source_databricks.py` uses synthetic native-shaped inputs and checks
identities, source hashes, missing/contradictory namespaces, types/comments,
constraints/policies, malformed input, SQL dependency ownership, pagination,
unsupported code, missing dependencies and registry contract rejection. The
suite can also run with Python `-S` to verify the standard-library-only path;
native SQL parser assertions then skip explicitly.

All results retain `execution_performed: false`, `native_validation: not_run` and
`export_completeness: not_established`. Effective access, actual grain, key
integrity, full lineage, job/pipeline deployment, streaming/late-data behavior and
customer acceptance require separately authorized native evidence.
