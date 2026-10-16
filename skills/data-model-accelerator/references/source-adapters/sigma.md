# Sigma source adapter — bounded REST metadata evidence

Research retrieved **2026-10-15** from the primary sources below. The adapter
accepts supplied UTF-8 file contents only. It performs no API authentication,
network acquisition, formula evaluation, SQL execution or workbook mutation.
The supported contract is the documented **REST v2 response body**, not an
invented consolidated workbook interchange format.

## Supported native response shapes

Save authorized, sanitized response bodies as `.json` files under any safe,
repository-relative path. Each file is either one supported resource or the
native `{"entries": [...], "nextPage": null, "total": N}` list envelope.
Arrays of unrelated resources and home-grown `workbooks/pages/elements` wrappers
are unsupported. Evidence keeps the original path, JSON locator and file hash;
resource metadata retains all supplied fields, including unknown fields.

| Supplied endpoint/body | Extracted evidence | Boundary |
| --- | --- | --- |
| [List workbooks](https://help.sigmacomputing.com/reference/list-workbooks), `GET /v2/workbooks`; individual workbook metadata | `workbookId`, name, versions, tags and raw metadata | Metadata does not contain the full workbook behavior |
| [List workbook pages](https://help.sigmacomputing.com/reference/list-workbook-pages), `/v2/workbooks/{workbookId}/pages` | `pageId`, name and `hidden` declaration | Response omits the request's workbook ID; hidden is not an access policy |
| [List elements](https://help.sigmacomputing.com/reference/list-workbook-page-elements), `/v2/workbooks/{workbookId}/pages/{pageId}/elements` | `elementId`, type, column ID declarations, exact documented `vizualizationType` spelling and errors | No implied filter, join, control, action or layout reconstruction |
| [List columns](https://help.sigmacomputing.com/reference/get-element-columns), `/v2/workbooks/{workbookId}/elements/{elementId}/columns` | `columnId`, label, type and exact Sigma `formula` | Formula text is not executed or translated; bracket text is not asserted as resolved lineage |
| [Get element query](https://help.sigmacomputing.com/reference/get-element-query), `/v2/workbooks/{workbookId}/elements/{elementId}/query`; [List SQL queries](https://help.sigmacomputing.com/reference/list-workbook-queries), `/v2/workbooks/{workbookId}/queries` | `elementId`, name, exact `sql`, and native errors | These responses omit SQL dialect and request context; SQL stays `sql:unknown` |
| [Get dataset (Deprecated)](https://help.sigmacomputing.com/reference/get-dataset), `/v2/datasets/{datasetId}` | `datasetId`, metadata and declared migration-to-data-model reference | Dataset metadata is not a SQL/formula export; migration metadata does not prove accepted parity |
| [List grants](https://help.sigmacomputing.com/reference/list-grants), `/v2/grants` | `grantId`, `inodeId`, member/team principal and permission declarations | Effective permissions, inheritance, row/column policies and warehouse access are unverified |
| [Workbook element lineage](https://help.sigmacomputing.com/reference/list-lineage), `/v2/workbooks/{workbookId}/lineage/elements/{elementId}` | Native `dependencies` mapping, `nodeId`, optional `elementId`, and `edges` source/target/type | Retains declared graph only; no physical-table mapping, join semantics or completeness claim |

For lineage, each dependency mapping key must equal its node's `nodeId`. The
native edge points from upstream `source` to downstream `target`; the canonical
dependency points from dependent to prerequisite. Both original endpoint IDs
and the original edge are retained. Missing nodes or unknown edge kinds become
gaps. Element `columns` references and grant `inodeId` targets remain unresolved;
the adapter does not match ambiguous objects merely because IDs or names agree.

Most list entries omit their parent request IDs and selected version. The
adapter deliberately does **not** derive those identities from filenames or
assume that separately supplied page, element, formula and query responses are
from the same workbook/version. Preserve the acquisition receipt separately.
Repeated IDs are retained with gaps, never silently deduplicated or overwritten.
Only direct relationships evidenced inside the native bodies are recorded.

Standalone `.sql` may retain manually supplied dataset/query SQL as **unbound
evidence**. It does not establish native object ownership or dialect. The
documented [dataset query-history UI](https://help.sigmacomputing.com/docs/examine-dataset-queries)
is a separate acquisition surface; this adapter does not invent a dataset SQL
REST endpoint or treat an extra `sql` property in dataset metadata as such an
endpoint. Unknown properties remain raw metadata and produce gaps.

## Acquisition handoff and completeness

An operator must select the organization, principal, workbook scope, published
version/tag/saved view, snapshot time and relevant permissions outside this
parser. Use the appropriate cloud/region API base URL. Sigma's
[API introduction](https://help.sigmacomputing.com/reference/get-started-sigma-api)
describes client credentials, bearer authentication, regional URLs and API
limits. [Get access token](https://help.sigmacomputing.com/reference/post-token?explorer=true)
uses `POST /v2/auth/token` with `grant_type=client_credentials`, client ID and
secret; the documented token validity is one hour. Do not put credentials or
token responses in source snapshots.

Enumerate the intended workbooks and then each required metadata endpoint.
Follow each `nextPage` value through the endpoint's `page` parameter until its
terminal `null`. The documented default page size is 50 and maximum is 1,000.
Retain all pages plus request parameters externally. Query parameter names
differ: page/element lists use `tag`, while the element-query endpoint documents
`tagName`; saved-view requests can use `bookmarkId`. These contexts must not be
silently combined. The workbook-list `skipPermissionCheck` option is admin-only;
ordinary visibility is not organization-wide coverage.

A nonempty `nextPage`, deprecated `hasMore: true`, absent/malformed pagination,
empty entries, or total/count disagreement produces a gap. The parser does not
infer that another file closes a pagination chain. A terminal page alone still
cannot establish complete scope, filtering, permissions or snapshot coherence.
The result always reports `export_completeness: not_established`,
`native_validation: not_run`, and `execution_performed: false`.

The [OAuth override-token limitations](https://help.sigmacomputing.com/reference/use-oauth-override-tokens)
exclude the workbook SQL-query list and element-query endpoints. API request
success therefore cannot be assumed to reproduce a different user's effective
SQL/security context. Grants are declarations; do not substitute them for
representative user tests or warehouse access evidence.

## Current export and lifecycle limitations

**Datasets are Deprecated.** The current dataset reference says that creation
and edits are unavailable starting June 2, 2026. Preserve historical dataset
evidence and migration IDs; do not reinterpret it as a current data model.

**Manage workbooks as code is Beta.** The
[current feature documentation](https://help.sigmacomputing.com/docs/manage-workbooks-as-code)
and [retrieval instructions](https://help.sigmacomputing.com/docs/get-the-code-representation-of-a-workbook)
describe `GET /v2/workbooks/{workbookId}?includeContents=true`, returning
`contents` and `documentVersion`. The retrieval documentation warns that
unsupported features are silently omitted. This first adapter slice retains
`contents` unchanged inside workbook metadata with a
`sigma.beta_contents_unsupported` gap. It does not interpret the Beta schema or
claim round-trip fidelity. The limitation belongs to this implementation as
well as to the export; it is not a claim that Sigma lacks code representation.

CSV/XLSX/PDF/PNG/JSON **data exports are not workbook logic exports**. The API
introduction distinguishes the export/download results from metadata endpoints.
Data rows, calculated outputs and screenshots cannot establish the formulas,
filters, security declarations or complete interactions that produced them.
Unsupported formats receive explicit file coverage and gaps.

## Primary technical research and reuse decisions

| Source/candidate | License or authority | Decision |
| --- | --- | --- |
| [SQLGlot](https://github.com/tobymao/sqlglot), [license](https://github.com/tobymao/sqlglot/blob/main/LICENSE) | MIT | Reuse the existing shared `parse_sql` evidence helper. No dialect is invented from Sigma query syntax, so this slice preserves raw SQL and does not invoke SQLGlot structural parsing. No new dependency or vendored grammar. |
| [Sigma's sqlparser-rs fork](https://github.com/sigmacomputing/sqlparser-rs), [license](https://github.com/sigmacomputing/sqlparser-rs/blob/main/LICENSE.TXT) | Apache-2.0 | Relevant SQL lexer/parser candidate; not a Sigma-formula or complete workbook parser. No Rust runtime added, no code copied. |
| [Sigma Plugin API](https://github.com/sigmacomputing/plugin) | MIT | Client/plugin interaction SDK, not an offline workbook-definition parser. Not reused or executed. |
| [Sigma sample API repository](https://github.com/sigmacomputing/sigma-sample-api) | Vendor-maintained examples; no repository license was visible in the inspected root | Orientation only. No source copied or installed; do not infer reuse permission from public visibility. |
| [Sigma REST API Recipes](https://quickstarts.sigmacomputing.com/guide/developers_api_code_samples/index.html) | Vendor technical guide | The page/element/column traversal recipe supports the acquisition sequence. Console-format recipe output is not substituted for native response JSON. |

The vendor's technical article
[Examine workbook and data model queries](https://help.sigmacomputing.com/docs/examine-workbook-queries)
explains generated optimized queries and session-scoped query history. This
supports preserving observed query text separately from authored formula intent
and full interactive behavior. The guide
[Reference control values as parameters](https://help.sigmacomputing.com/docs/parameters-in-workbooks)
shows that controls can influence formulas and SQL. Missing control state is
therefore an explicit interpretation gap, not an invitation to substitute a
single observed value. Neither article establishes source completeness or
native acceptance from an offline response file.

## Validation scope

The independent synthetic tests cover native IDs and raw metadata, exact
formula/SQL retention, declared column references, grants, dataset migration
references, lineage direction, missing parent context, Beta/unknown metadata,
pagination, duplicate identities, malformed/deep/duplicate-key/non-finite JSON,
unsafe paths, ambiguous shapes, source prompt injection and a no-network/no-code
execution boundary. They run without optional SQL/YAML/network packages.
`registry.validate` checks canonical evidence binding. Passing these tests
qualifies only this bounded offline extraction behavior; source acquisition,
Sigma execution, effective security and customer acceptance remain separate.

## Interpretation and accelerator integration

Pass this adapter's retained findings and gaps to the bounded
[Sigma interpretation specialist](../specialists/sigma.md); do not dispatch a
second capture or full repository scan. Supplemental context must be tied to the
same source identities/version and hashes. It cannot retroactively make an
incomplete native response complete or teach this parser an unsupported schema.

Reusable lessons from the separately maintained Sigma migration accelerator are
source-bound control/field mappings, stable-ID dependency resolution, preserved
hidden behavior, explicit accounting for blocked/excluded objects, exact
existing-Topic compatibility evidence, and validation of reopened output bytes.
Its enriched snapshot, routing decisions and pre-push context are **not** native
REST response formats accepted by this adapter. Its translation and build paths
are not added to this parser by reference.

The specialist records the inspected public revision and offline CI receipt.
Those synthetic/local checks qualify engineering behavior within their tested
scope. They do not establish source export completeness, live Sigma/Omni parity,
effective permissions or business acceptance for a new engagement.
