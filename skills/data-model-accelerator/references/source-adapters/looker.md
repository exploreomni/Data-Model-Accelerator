# Looker source adapter

Research refreshed **2026-10-15**. This is an offline source inventory, not a
Looker compiler, migration qualification, or live connector. Public documentation
uses an evolving `latest` API reference; retain the actual instance/API version
and Git revision with every supplied capture.

## Accepted evidence and output

`source_adapters.looker.parse(files)` accepts a bounded mapping of relative paths
to UTF-8 text. It performs no file reads, authentication, network requests, query
execution, or writes. The shared report records each supplied file's SHA-256,
coverage, object identifiers, expressions, candidate dependencies, and gaps.

- **LookML:** `.model.lkml`, `.view.lkml`, `.explore.lkml`, other `.lkml`
  project files, and the corresponding `.model`/`.view`/`.explore` names.
  Extracts model, view, Explore, dimension, dimension group, measure, parameter,
  filter, join, access grant/filter, and derived-table declarations. Retains
  native properties, names, `${...}` candidates, SQL, Liquid, inheritance lists,
  and refinement declarations. Names are source symbols, not globally unique
  tenant IDs. Report IDs additionally bind the file and declaration location.
- **Dashboard JSON:** the API 4 dashboard shape and existing schema-1
  `looker_dashboard_export` wrapper. Reuses `looker_source.parse_dashboard`
  without modifying it. Keeps dashboard/element/query/filter/layout IDs,
  query fields, pivots, calculations, filter listeners, opaque visualization
  settings, and inherited parser gaps. Full original text remains authoritative.
- **Not interpreted:** native LookML dashboard YAML (`.dashboard`,
  `.dashboard.lkml`, `.dashboard.lookml`), arbitrary JSON, SQL Runner/merged-query
  behavior, effective access, and source completeness.

The API's dashboard and query contracts distinguish filters, filter expressions,
dynamic fields, and opaque visualization/filter UI settings. Capture referenced
queries and Looks, not only IDs. See the official [dashboard API](https://docs.cloud.google.com/looker/docs/reference/looker-api/latest/methods/Dashboard/dashboard)
and [search contract](https://docs.cloud.google.com/looker/docs/reference/looker-api/latest/methods/Dashboard/search_dashboards).

## Acquisition boundary

Acquisition is a separate authorized workflow. API credentials are tied to a
Looker user, and responses inherit that user's visibility. The official SDK
handles client ID/secret authentication and access tokens; credentials must not
be included in source snapshots. [Authentication documentation](https://docs.cloud.google.com/looker/docs/api-auth).

Dashboard search recommends `limit`/`offset`; `page`/`per_page` are **DEPRECATED**.
Record page exhaustion, filters, inaccessible content, capture time and instance,
then reconcile a separate inventory denominator. A successful page or empty
response does not establish completeness. [Search Dashboards](https://docs.cloud.google.com/looker/docs/reference/looker-api/latest/methods/Dashboard/search_dashboards).

Obtain revision-bound LookML from the approved project repository/export. The
documented [Project File API](https://docs.cloud.google.com/looker/docs/reference/looker-api/latest/methods/Project/project_file)
returns file metadata, including an opaque file ID; its response contract is not
a raw LookML source download. Do not treat metadata listings as project contents
or decompose opaque API file IDs into invented paths.

## Interpretation and gaps

Includes resolve only within the supplied mapping. Relative paths, project-root
paths, `*`, `**`, and extension aliases are matched case-sensitively. Each ordered
include is retained. Missing files, imported-project paths and dynamic patterns
produce gaps; a matching file proves only that bytes were supplied. No effective
model assembly is claimed. [Official include syntax](https://docs.cloud.google.com/looker/docs/reference/param-model-include).

`extends` and `+name` refinements remain separate declarations. Looker's
refinement/include precedence and defaults are not evaluated. The official
[extends guide](https://docs.cloud.google.com/looker/docs/reusing-code-with-extends),
[refinement guide](https://docs.cloud.google.com/looker/docs/lookml-refinements),
and [DRY LookML worked example](https://docs.cloud.google.com/looker/docs/best-practices/dry-cookbook-5)
show why a flat union cannot represent every model's effective behavior.

SQL bodies and `${view.field}` substitutions remain native expressions; candidate
references are **unbound**, and a connection name never selects a SQL dialect.
Liquid, templated filters, user attributes, nested/dynamic substitutions, native
derived tables and PDT persistence require version-bound native evidence.
See [SQL substitutions](https://docs.cloud.google.com/looker/docs/sql-and-referring-to-lookml)
and [Liquid reference](https://docs.cloud.google.com/looker/docs/liquid-variable-reference).
Access filters/grants are declaration evidence only; separately verify roles,
model sets, user-attribute assignments and negative access cases.
[Access filter documentation](https://docs.cloud.google.com/looker/docs/reference/param-explore-access-filter).

## Reuse and licensing decisions

| Component | License / decision |
| --- | --- |
| [lkml](https://github.com/joshtemple/lkml) and its [recursive-descent grammar](https://github.com/joshtemple/lkml/blob/master/lkml/parser.py) | MIT; reuse pinned `lkml==1.3.7` for structural parsing. Original source is retained because parsed values normalize formatting. Add depth/token/progress bounds and reject duplicate scalar parameters instead of allowing upstream top-level overwrite. No fork or vendored parser. |
| [Looker SDK codegen / Python SDK](https://github.com/looker-open-source/sdk-codegen) | MIT; candidate for separately authorized API acquisition. Not installed or invoked by this adapter; SDK transport is not a LookML compiler. |
| [node-lookml-parser](https://github.com/fabio-looker/node-lookml-parser) | MIT; evaluated alternative with PEG AST and project assembly. Not added: another runtime and assembly semantics are outside this bounded Python extractor. |
| [pylookml](https://github.com/looker-open-source/pylookml) | MIT; repository archived April 24, 2024. Not added; its manipulation/integration layer is unnecessary for read-only extraction. |

## Verification

Run `python -m unittest discover -s tests -p 'test*looker*.py'` with the pinned
source-adapter dependencies. The new fixtures cover IDs, evidence hashes, source
preservation, candidate lineage, filters, access declarations, includes, repeated
refinements, derived tables, Liquid, duplicate parameters, malformed input,
bounded nesting, shared dashboard queries, and no I/O/execution. Existing
dashboard parser tests remain unchanged. Fixture success establishes local
extraction behavior only; native validation remains `not_run` and export
completeness remains `not_established`.
