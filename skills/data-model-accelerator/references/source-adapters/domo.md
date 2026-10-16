# Domo source adapter

Research checked 2026-10-15. Adapter version 1 reads supplied UTF-8 JSON snapshots
only. It makes no network calls, evaluates no formula or script, and never runs a
DataFlow. The implemented subset is a declaration inventory, not a migration,
complete Domo export, tenant qualification or parity evaluation.

## Supported native shapes

| Surface | Accepted shape | Extracted evidence |
| --- | --- | --- |
| Platform DataSet v1 | Detail object containing `id`, `name`, `schema.columns`; or an array of those objects | Native DataSet IDs, ordered columns/types, PDP state and policy/filter/principal declarations |
| Product Beast Mode v1 | Template object containing `id`, `name`, `legacyId`, `expression`, `links`; or search response with `results`, `totalHits`, `hasMore` | Original formula, native/legacy IDs, resource links and their active/visible/valid flags, supplied calculation metadata |
| Magic ETL clipboard | Object with `contentType: "domo/dataflow-actions"` and `data: [...]` | Action IDs/types/configuration, `dependsOn` graph, formula text, input/output DataSet references and native filter declarations |

Platform DataSet fields follow the official [DataSet API](https://www.domo.com/docs/portal/3b1e3a7d5f420-data-set-api)
and [vendor OpenAPI definitions](https://github.com/DomoApps/domo-documentation-hub/blob/main/portal/API-Reference/Domo-APIs/DataSet-API.yaml).
The adapter retains `pdpEnabled`, each policy's `id`, `type`, `name`, `users`,
`groups`, and `filters`, including each predicate's `not`, `operator`, `column`
and `values`. These are source declarations; no policy inheritance, membership,
bypass privilege or effective access is inferred. Standalone PDP responses lack
a DataSet binding and are outside this slice. Metadata list records without
`schema` require their detail response before schema extraction.

The official [Beast Modes API](https://www.domo.com/docs/portal/bff3ab39f7a6b-beast-modes)
documents search and template shapes separately. Search can omit `expression`;
that produces `domo.formula_missing`. `legacyId` remains in the native definition
while `id` is the native identity. Links remain declarations even when inactive
or invalid. `DATA_SOURCE` references bind only to a single supplied matching
DataSet ID; `CARD` references remain unresolved because cards are unsupported.
`functionTemplateDependencies` remain opaque. Beast Mode expressions are labeled
`domo:beast_mode`; the adapter does not assume a MySQL dialect, rewrite formulas,
or infer executable lineage from SQL-looking tokens.

The clipboard contract is **unversioned and provisional**, grounded in authors'
public native clipboard examples, not a formal vendor JSON schema. Mark
Snodgrass's [formula/window example](https://community-forums.domo.com/main/discussion/54352/rolling-30-day-formula-in-magic-etl)
shows the exact `contentType`, `data`, `dependsOn`, `expressions[].expression`,
`expressions[].fieldName`, `LoadFromVault.dataSourceId`, and
`PublishToVault.dataSource.guid` shapes. The author's [lineage example](https://community-forums.domo.com/main/discussion/59611/tracking-datasets-connected-in-other-dataflows/p1)
shows filter, selection, join, union and distinct-action configuration. These are
primary evidence of observed native representation, not release guarantees or
proof of algorithm correctness. Local tests use new synthetic IDs, formulas and
business examples; public or customer datasets are not copied.

Recognized action names are `LoadFromVault`, `PublishToVault`,
`ExpressionEvaluator`, `Filter`, `SelectValues`, `MergeJoin`, `UnionAll`, `Unique`
and `WindowAction`. Recognition preserves declarations and does not translate
their runtime behavior. Filter trees, joins and windows remain structured native
configuration. Unknown action types retain their entire definition and graph
edges with `domo.unknown_action`; arbitrary nested SQL/code is never guessed or
executed. Formula settings and extra fields produce explicit opaque-field gaps.

A clipboard selection does not establish its parent DataFlow ID, version,
schedule, complete action graph or runtime configuration. Those facts remain
unknown rather than being synthesized from the filename. Entire DataFlow API
responses (`actions`, `transforms`, encoded `definition`, and SQL DataFlow
variants), card/query definitions, raw SQL, DomoStats tables, CSV row exports,
and custom normalized envelopes are explicitly unsupported. Add a new format
only with independently reviewed, version-bound native evidence.

## Acquisition and authorization boundaries

Platform APIs use OAuth client credentials, scoped clients and bearer tokens on
`api.domo.com`. Product APIs use an instance access token in
`X-DOMO-Developer-Token` and inherit the user's resource access; their coverage
and privilege model are different. App Framework sessions are a third surface.
The adapter neither requests credentials nor treats success on one API family as
permission to use another. [Official API overview](https://www.domo.com/docs/portal/API-Reference/overview)

A separately authorized exporter would use Platform `GET /v1/datasets/{id}`
with the applicable data scope and resource permissions. The list endpoint is
`GET /v1/datasets`, with `limit` (documented maximum 50) and `offset`; retain every
requested page and reconcile the export scope. An array alone does not prove all
pages were acquired. The DataSet CSV data endpoint supplies rows, not the
transformation definitions required here. [DataSet API reference](https://github.com/DomoApps/domo-documentation-hub/blob/main/portal/API-Reference/Domo-APIs/DataSet-API.yaml)

Beast Mode discovery uses Product `POST /api/query/v1/functions/search` with
limit/offset and returns `totalHits`, `hasMore`, and `degraded`; definition retrieval
uses `GET /api/query/v1/functions/template/{id}`. Search completeness is never
asserted from one response, including when `hasMore` is false. Missing pages and
degraded responses are explicit gaps. Request bodies, pagination boundaries,
export time, instance and authorization evidence belong to the upstream exporter;
this parser cannot reconstruct them. [Beast Modes API reference](https://www.domo.com/docs/portal/bff3ab39f7a6b-beast-modes)

## Preservation, limits and failure behavior

- Original JSON text, file SHA-256, object locations and native definitions remain
  available. Unknown fields are retained and flagged. Names never replace IDs.
- DataSet and Beast Mode references bind by unique native ID across supplied
  files. Duplicate definitions remain separate evidence and make links unresolved.
- Action dependencies bind within one clipboard selection. Duplicate IDs,
  missing targets, malformed dependency lists and cycles produce gaps; graph
  traversal does not execute actions or infer ordering beyond declarations.
- The common loader rejects duplicate JSON keys, non-finite numbers, unsafe
  paths and excessive depth/size. Limits are 8 MiB/file, 32 MiB total, 512 files,
  150,000 JSON values and depth 48. The action reader additionally allows at most
  1,000 actions and 4,000 dependency entries per clipboard file. Exceeding an
  action/edge limit retains raw input and emits `domo.graph_limit`.
- Missing/malformed IDs, column schemas, PDP definitions, formula strings and
  filter shapes remain review gaps. Empty exports cannot prove absent source
  objects. Each supplied file receives parsed/partial/unsupported accounting.
- `export_completeness` stays `not_established`, `native_validation` stays
  `not_run`, and `execution_performed` stays false. Results do not establish
  grain, uniqueness, runtime type coercion, security or business acceptance.

## Open-source research and reuse decision

| Candidate | Verified scope / license | Decision |
| --- | --- | --- |
| [Domo Python SDK / PyDomo](https://github.com/domoinc/domo-python-sdk) | Vendor SDK; repository identifies MIT licensing; DataSet/PDP and other Platform clients | Useful API/permission evidence, but a network client rather than a bounded definition parser. Not imported, vendored or executed. |
| Shared SQLGlot adapter | Repository's existing pinned SQL parser; MIT dependency | Not used for Beast Mode or Magic ETL formulas because source dialect and evaluation context are not established. |

This is original repository code using the common safe JSON loader and Python
standard library. No third-party source or schema is vendored, so no additional
runtime dependency or third-party license bundle is introduced. Future parser or
SDK reuse requires checking the exact version and license before incorporation.

## Verification and remaining work

`tests/test_source_domo.py` independently asserts IDs, ordered columns/types,
PDP predicates/principals, formula bytes, graph edges, DataSet links and explicit
unknowns. It covers malformed/duplicate JSON, malformed declarations, incomplete
search pages, missing formulas, empty exports, unknown actions/fields, duplicate
identities, unresolved references, cycles, bounded graph size, determinism and
non-execution. This qualifies the synthetic structural subset only. Approved
native customer snapshots, complete export reconciliation, card/SQL DataFlow
formats, runtime comparisons and permission tests remain future work.
