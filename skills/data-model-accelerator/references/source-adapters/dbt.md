# dbt supplied-source adapter

Research reviewed: **2026-10-15**. Implementation:
[`dbt.py`](../../scripts/source_adapters/dbt.py). Independent synthetic checks:
[`test_source_dbt.py`](../../../../tests/test_source_dbt.py).

## Compatibility contract

This is an offline source reader for approved UTF-8 snapshots. It never imports
or invokes dbt, renders Jinja, executes Python models/macros/hooks/SQL, installs
packages, reads profiles, performs warehouse introspection, or acquires artifacts.
Existing dbt refactor, qualification and evidence-verification workflows are
separate and unchanged.

The separate [runtime workflow](../dbt-runtime.md) adds explicit distribution and
version assessment. For supplied Parquet `target/info_schema/v1` snapshots use
`scripts/dbt_information_schema.py`; the UTF-8 source adapter does not parse binary
Parquet. The coordinator attaches the bounded projection and its gaps to the
assigned dbt task. This avoids repeated full-manifest ingestion and does not
establish native execution or physical key relationships.

The only accepted manifest schema URI is
`https://schemas.getdbt.com/dbt/manifest/v12.json`. The adapter validates bounded
container/identity/dependency shapes, **not the full JSON Schema**. Older versions,
future versions, alternate URLs and custom envelopes retain their exact JSON and
produce gaps. Manifest schema version and engine `metadata.dbt_version` remain
separate values, following the official [manifest contract](https://docs.getdbt.com/reference/artifacts/manifest-json)
and [v12 schema](https://schemas.getdbt.com/dbt/manifest/v12.json). This does not
claim compatibility with every engine behavior that emits a v12 artifact.

| Supplied input | Extracted evidence | Boundary |
| --- | --- | --- |
| Native v12 manifest | Native resource IDs/package namespaces, original paths, configuration and resource metadata, exact raw and compiled code, macro bodies, columns, declared node/macro dependencies | Export provenance and dependency completeness are not authenticated; no compiled-to-current-revision equivalence |
| `nodes`, `sources`, `macros`, `exposures`, `docs`, `groups` | Models, analyses, tests, snapshots, seeds, operations, source relation/freshness properties, macros, consumers and ownership declarations | No execution, physical column verification, freshness result or test-pass claim |
| `disabled` | Native v12 map from ID to arrays of disabled definitions, preserving multiple definitions separately | Disabled nodes do not resolve active dependency edges |
| Metrics, semantic models, saved queries and unit tests | Native metadata and explicitly supplied dependencies | Semantic execution remains an explicit gap |
| `dbt_project.yml` | Project name, resource paths, vars, config/materialization/security declarations, exact hook strings | Config inheritance and environment/target rendering remain unresolved |
| Arbitrarily nested properties `.yml` | Named declarations, source tables, model versions, columns, data tests, contracts, descriptions and original metadata | No IDs invented from names and no implicit property-to-manifest merge |
| `packages.yml`, `dependencies.yml`, `package-lock.yml` | Declared packages, local/Git/tarball locations, revisions and cross-project declarations | No install, download, remote resolution or proof of lockfile authenticity |
| Authored SQL/Jinja and Python | Exact original text/hash; structural SQL only with unambiguous manifest binding and supported adapter evidence | Jinja and Python remain inert; SQL dialect is otherwise unknown |
| CSV | File hash, byte count and explicitly lexical seed-file candidate | No data rows, delimiter, type inference or seed execution |

The current [properties documentation](https://docs.getdbt.com/reference/define-properties)
permits omission of the version fields since dbt v1.5. This slice interprets an
omitted `version`/`config-version` using the v2 structure; explicit fields must be
integer `2`. Quoted, null, boolean and other versions are gaps. The reviewed
native discovery contract uses `.yml`; `.yaml` is preserved but marked unsupported.
[Project configuration](https://docs.getdbt.com/reference/dbt_project.yml) and
[packages](https://docs.getdbt.com/docs/build/packages) are declarations, not
instructions to execute a project.

Every supported JSON/YAML/code file retains original text and SHA-256 evidence;
all files have coverage records. Unsupported files, profiles and CSV retain hashes
without copying credential/data contents into the report. This is not a general
secret scrubber: approved manifests, code and YAML may themselves contain sensitive
values. Input approval and downstream disclosure controls still apply.

## Identity, dependency and revision rules

- Each manifest resource must have an explicit non-empty name/package and an ID
  agreeing with its native map key and resource-type/package prefix. Versioned
  model IDs and test-ID suffixes remain intact. Same short names in different
  packages are not merged.
- Native edges use only supplied `depends_on.nodes`/`depends_on.macros` IDs, with
  locators for the precise array entry. A target resolves only to one active
  definition **in that manifest** and in the correct dependency category. Missing,
  disabled, malformed and ambiguous targets remain unresolved. No dependency is
  inferred from comments, regular expressions, YAML `ref` strings, remote package
  declarations or code filenames. Parent/child/group maps and selectors are retained
  as separate supplied metadata; graph-map consistency is not certified.
- SQL file binding requires one supplied `dbt_project.yml` with matching package,
  a safe exact `original_file_path`, exact raw-code/file text, and a matching
  SHA-256 if that checksum algorithm is declared. Multiple manifests do not get
  ranked by filename or timestamp. Binding establishes same supplied bytes only;
  it does not authenticate a Git revision or export.
- Dialect comes from bound manifest `metadata.adapter_type`, using explicit
  mappings for Snowflake, BigQuery, Redshift, Postgres, DuckDB, Databricks, Spark,
  ClickHouse and SQL Server. A directory name, profile name or SQL resemblance
  never selects a dialect. Missing/unsupported adapter types remain unknown.
- `raw_code`, `compiled_code`, `macro_sql` and documentation blocks are separate
  expressions. Compiled code retains invocation/version context but always has a
  revision/provenance gap. It is not recompiled, structurally substituted for raw
  Jinja or treated as a successful run. Matching raw bytes cannot prove matching
  macros, packages, vars, target, incremental state or environment.

The official [ref reference](https://docs.getdbt.com/reference/dbt-jinja-functions/ref)
describes package/version references and native graph construction. The
[parsing guide](https://docs.getdbt.com/reference/parsing) describes context-sensitive
and partial-parsing limitations. Those are why this adapter consumes native ID
edges instead of guessing a graph from text. Dynamic branches and macro dispatch
remain explicit review gaps even when a supplied manifest has dependencies.

Materializations, incremental/snapshot strategies, unique keys, contracts and
column constraints remain declarations. [Model access](https://docs.getdbt.com/reference/resource-configs/access)
and [warehouse grants](https://docs.getdbt.com/reference/resource-configs/grants)
serve different purposes; both are retained without asserting effective security.
Hooks, SQL headers, policy metadata and Python models require separate native review.

## Acquisition handoff

Use an already approved repository snapshot and an existing artifact from the
intended run. The [manifest documentation](https://docs.getdbt.com/reference/artifacts/manifest-json)
describes local `target/` files and job artifact downloads. Preserve the selected
account/project/environment/job/run/step, exporting principal, Git commit,
invocation, engine and adapter versions, package resolution, vars/target context,
selection and snapshot time in a separate acquisition receipt. Hash the downloaded
bytes and reconcile the resource scope against an independent inventory.

The [Administrative API](https://docs.getdbt.com/docs/dbt-apis/admin-api) is a separate
acquisition surface. [Authentication tokens](https://docs.getdbt.com/docs/dbt-apis/authentication)
distinguish account-scoped PATs for user/development contexts from scoped service
tokens for production integrations. Preserve permissions and account/base-domain
scope; never put a token or credential-bearing `profiles.yml` in the input bundle.
The [API v2 reference](https://docs.getdbt.com/dbt-cloud/api-v2) documents
`Authorization: Token ...` (also `Bearer`) and `limit`/`offset` pagination for list
endpoints, with a maximum `limit` of 100. A first page is not a complete inventory.
Missing permissions, inaccessible runs, empty lists and failed requests are
coverage gaps, not evidence that a project or artifact is absent.

For run artifact list/download behavior, the maintained
[Dagster dbt integration source](https://github.com/dagster-io/dagster/blob/master/python_modules/libraries/dagster-dbt/dagster_dbt/cloud/resources.py)
provides a primary implementation of `GET` run artifact endpoints, including the
optional one-based `step` and last-step default. Pin an explicit run and intended
step during acquisition rather than assuming a last-step artifact represents the
required model build. This reader does not accept API pagination envelopes,
merge pages, follow URLs, trigger jobs, or certify any acquisition receipt.

Generating a missing artifact is a separate execution decision. The official
[`execute` reference](https://docs.getdbt.com/reference/dbt-jinja-functions/execute)
explains that `dbt compile` can run warehouse queries through `run_query` and that
parse-time Jinja still evaluates macros such as logging. This adapter therefore
does not use `dbt parse` or `dbt compile` as an allegedly passive parser fallback.

## Parser research and license boundary

| Candidate | Decision and license evidence |
| --- | --- |
| Python JSON + pinned PyYAML 6.0.3 | Used through shared bounded readers; YAML safe loading rejects aliases, executable tags, duplicate keys and non-JSON primitive values. [PyYAML license](https://github.com/yaml/pyyaml/blob/6.0.3/LICENSE): MIT. |
| Shared SQLGlot 30.18.0 | Used only for explicitly bound, non-templated authored SQL. [License](https://github.com/tobymao/sqlglot/blob/v30.18.0/LICENSE): MIT. A syntax tree is not native execution. |
| dbt-extractor | Reviewed, not installed or invoked. Its [primary implementation notes](https://github.com/dbt-labs/dbt-extractor) document a limited tree-sitter/Jinja static subset and rejection when extraction cannot be certain. [License](https://github.com/dbt-labs/dbt-extractor/blob/main/LICENSE): Apache-2.0. Falling back to rendering would violate this source reader's boundary. |
| dbt Core v1.10.0 | Reviewed only as a versioned engine baseline, not imported. [License at the reviewed tag](https://github.com/dbt-labs/dbt-core/blob/v1.10.0/License.md): Apache-2.0. This statement is not a license claim about every later dbt product/distribution. |

The primary technical article
[The key technologies behind SQL Comprehension](https://docs.getdbt.com/blog/sql-comprehension-technologies)
separates parsing, binding and execution. The implementation adopts that distinction:
source syntax/declarations, supplied native dependency bindings and actual behavior
are separate evidence lanes. The vendor's
[schema-change automation discussion](https://www.getdbt.com/blog/surviving-schema-changes-with-automation)
illustrates Jinja-driven relation discovery and explicit dependency handling; this
reader retains such code and its uncertainty without running discovery macros.

## Validation and remaining qualification

Synthetic tests cover namespace/version IDs, sources/macros/tests/exposures,
disabled definitions, exact CRLF/raw/compiled bytes, hooks/grants, ambiguous/stale
bindings, missing dependency evidence, malformed JSON/YAML, unknown schemas,
version omission, remote-package declarations, inert Python/Jinja, seed/profile
content exclusion and missing optional dependencies. Every result passes the shared
`registry.validate` evidence contract. Parser-specific assertions skip explicitly
when their dependency is absent; dependency-free preservation tests still run.

All results report `export_completeness: not_established`, `native_validation:
not_run` and `execution_performed: false`. Live dbt compilation/execution, engine
schema validation, warehouse behavior, effective access, full inventory closure,
source-to-target equivalence and business acceptance remain separate work.
