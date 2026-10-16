# Coalesce supplied-source adapter

Research reviewed: **2026-10-15**. Implementation:
[`coalesce.py`](../../scripts/source_adapters/coalesce.py). Independent tests:
[`test_source_coalesce.py`](../../../../tests/test_source_coalesce.py).

## Supported contract

This is offline inventory of supplied Coalesce **Git** artifacts. It does not
call the API or CLI, execute SQL, render Jinja, load packages, resolve credentials,
or alter any existing generation/deployment workflow. Source support does not
qualify native generation, migration parity, deployment, security or acceptance.

| Input | Bounded extraction | Explicit boundary |
| --- | --- | --- |
| Node YAML `fileVersion: 1`, `operation.version: 1` | Native node ID/name, raw operation/config, column IDs/types/nullability/keys, source mappings, exact decoded SQL strings | Types, defaults, tests, history, materialization and overrides are declarations |
| NodeType/Environment/Macro YAML `fileVersion: 1` | Native ID/name, definition/macro text; environment-specific database/schema mappings | Templates are unrendered; mappings do not authenticate actual physical objects or roles |
| `data.yml` v3; `locations.yml` v1 | Project configuration, default storage mapping, declared location names | Git configuration does not establish workspace identity, revision or current environment |
| SQL Nodes `.sql`; templates `.sql.j2`/`.j2` | Exact source and file hashes | No annotation identity, SQL dialect, template/ref binding or runtime claims |
| API JSON, hydrated metadata, legacy/custom envelopes, Jobs/Subgraphs/Packages | Unsupported-file accounting; original YAML remains evidence | No invented common export envelope or inferred job/package semantics |

The [official Git contract](https://docs.coalesce.io/docs/git-integration/what-gets-committed)
separates these files. Node columns use
`columnReference.{columnCounter,stepCounter}` and
`sourceColumnReferences[].columnReferences[]`. The adapter preserves those IDs
without translating them into REST field names. Unknown versions are not
interpreted. New/unknown fields remain raw evidence with gaps.

The vendor's [versioned reference repository](https://github.com/coalesceio/Iceberg-tables/tree/64385ce64d75f81e53628acb059e0731f438f104)
corroborates the contract: its `data.yml` has only `defaultStorageMapping` and
`fileVersion: 3`; it has no required `platformKind`. Its NodeType files use
`definition.yml` alongside `create.sql.j2` and `run.sql.j2`. These artifacts were
inspected as format evidence; no templates or vendor fixtures were copied.

## Identity, lineage and security boundaries

Nested repository paths remain exact. Node IDs, column `(stepCounter,
columnCounter)` pairs, named `(locationName,nodeName)` references and node-type
IDs bind only to a unique supplied target in the same native project directory.
Absent/duplicate targets remain unresolved. Column-source positions are retained;
inconsistent source-mapping counts are flagged rather than repaired. Alias IDs,
declared dependencies and `noLinkRefs` stay separate evidence types. The parser
does not manufacture dependencies from Jinja `ref()` text or short names.
Column transforms belong to their column objects; mapping joins and custom SQL
belong to their source-mapping objects, preserving the declared input references
through the specialist handoff. Blank or malformed mapping names receive explicit
unbound display labels and gaps, with original values retained as evidence.

Every object/expression/dependency has a source locator and SHA-256. Whole YAML
text preserves original spelling while decoded expression strings preserve the
actual value. Security-related config and SQL receive conservative review hints;
custom fields may carry additional security semantics. These hints neither scan
all secrets nor prove enforcement. Supply already approved, sanitized snapshots.
Roles, grants, policies, credentials, active environments and warehouse access
need independent evidence.

Shared limits are 512 files, 8 MiB/file, 32 MiB/run, 150,000 structured values and
depth 48. These are local parser limits, not vendor quotas. YAML aliases, anchors,
duplicate keys and unsafe constructors are rejected. Missing PyYAML retains raw
evidence with an explicit dependency gap. Every result keeps
`execution_performed: false`, `native_validation: not_run` and
`export_completeness: not_established`.

## Acquisition handoff: API is a different contract

Acquisition requires a separately authorized operator. Record organization,
region/base URL, project/workspace or environment ID, collecting principal,
snapshot time, Git commit/dirty state, product version and exact export scope.
Keep tokens and connection secrets outside evidence. Reconcile a separately
captured source inventory; a folder scan cannot establish complete SaaS scope.

The Transform API uses [Bearer authentication and deployment-specific base URLs](https://docs.coalesce.io/docs/api/authentication).
Catalog GraphQL and Quality APIs are distinct surfaces. Use the correct endpoint
and permissions; this adapter consumes neither. The native
[Set Node contract](https://docs.coalesce.io/docs/api/coalesce/set-workspace-node)
uses `metadata.columns[].sources[].columnReferences` with `nodeID`/`columnID`,
which must not be passed off as the Git `stepCounter`/`columnCounter` schema.

[List Environment Nodes](https://docs.coalesce.io/docs/api/coalesce/get-nodes)
documents `detail=false` by default, `limit` 1–500 (default 100), and
`skipParsing=true`, which omits parsed transform data even with `detail=true`.
[Workspace node listing](https://docs.coalesce.io/docs/api/coalesce/get-workspace-nodes)
is workspace-scoped. Preserve endpoint-specific options and omissions.
[Pagination](https://docs.coalesce.io/docs/api/query-parameters)
uses the response `next` value as `startingFrom` with the same `orderBy`; a null
`next` terminates the traversal. Retain every page and reconcile totals/IDs.
Exhausted pagination does not establish authorization visibility or hidden-object
coverage. General request-rate quotas were not established in the reviewed
reference; verify them before building acquisition. No API collector or pagination
completeness assertion is implemented here.

## Research and reuse decisions

| Primary source / candidate | Authority or license | Decision |
| --- | --- | --- |
| [Getting the Most Out of Node Types](https://coalesce.io/product-technology/getting-the-most-out-of-node-types/) | Vendor technical article, 2023-10-12 | Explains configurable SQL/YAML/Jinja patterns; historical guidance does not establish today's release status or behavior of a supplied custom type |
| [DataOps Best Practices with Git and Coalesce](https://docs.coalesce.io/docs/guides/dataops-and-git-best-practices) | Vendor technical guide | Supports preserving configuration, branches and deployment context; neither version control nor a successful parse proves deployment |
| [Current Node Types](https://docs.coalesce.io/docs/build-your-pipeline/v2-node-types) | Official current reference | YAML/mapping-grid and SQL/annotation authoring coexist; SQL Nodes intentionally remain preservation-only in this slice |
| [PyYAML](https://github.com/yaml/pyyaml), [license](https://raw.githubusercontent.com/yaml/pyyaml/main/LICENSE) | MIT | Reuse pinned 6.0.3 through the shared bounded loader; no new runtime dependency; preserve notices on redistribution |
| [SQLGlot](https://github.com/tobymao/sqlglot), [license](https://raw.githubusercontent.com/tobymao/sqlglot/main/LICENSE) | MIT | Existing optional parser is not used to guess a dialect or interpret incomplete Coalesce SQL fragments |
| [Coalesce SAP package](https://github.com/coalesceio/sap) | Apache-2.0 | Potential separately reviewed native reference; not a general parser and not imported/vendored; retain license/NOTICE obligations if later reused |
| [Iceberg package source](https://github.com/coalesceio/Iceberg-tables/tree/64385ce64d75f81e53628acb059e0731f438f104) | Vendor-owned public repository; no root LICENSE in inspected tree | Format evidence only; public visibility is not permission to copy its implementation |

Tests use synthetic fixtures with independent expected identities, expressions,
hashes, mapping scopes and dependency targets. They also cover duplicate IDs,
malformed shapes, unknown versions/envelopes, security declarations, unsafe YAML,
template preservation and optional-parser absence. Passing tests qualifies this
bounded extraction contract only. Existing Coalesce target-generation and
deployment gates remain separate.
