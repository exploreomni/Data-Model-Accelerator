# Tableau supplied-source adapter

Research reviewed: 2026-10-15. Implementation:
[`tableau.py`](../../scripts/source_adapters/tableau.py). Contract tests:
[`test_source_tableau.py`](../../../../tests/test_source_tableau.py).

## Supported boundary and reuse

The adapter accepts approved, credential-free UTF-8 `.twb` and `.tds` text through
the common files mapping. It reuses the existing
[`tableau_source.inspect_repo`](../../scripts/tableau_source.py), including its
XML credential rejection, Snowflake custom-SQL analysis, embedded field mapping,
filters, parameter defaults, worksheet scope, mirror consistency and gaps. Safe
copies are staged in a temporary directory and removed afterward. Existing
Tableau catalogue/replay workflows are unchanged. No SQL, Tableau calculation,
script, connection, network acquisition or source code is executed.

The independently authored fixture uses document version **26.1**. Other versions
retain declarations with an `unqualified_version` gap; this is not a claim of
compatibility across Tableau releases. The existing pinned official
[2026.1 workbook schema](https://github.com/tableau/tableau-document-schemas/blob/main/schemas/2026_1/twb_2026.1.0.xsd)
is attempted separately by the legacy inspector. Its missing publisher namespace
dependency remains an explicit unavailable-schema result. XML parsing, XSD
validation and native application validation remain distinct. The
[REST XML schema](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_concepts_schema.htm)
describes REST request/response envelopes, not TWB semantics. See the existing
[Tableau source contract](../tableau-source-contract.md) for pinned schema provenance.

| Evidence | Normalization and remaining boundary |
| --- | --- |
| Workbooks, data sources, fields, sheets, dashboards | Preserve native IDs/names and legacy scoped IDs; all objects carry file hash and locator. Names are not authenticated server LUIDs. |
| Columns and calculations | Preserve local/remote column mapping, datatype, role, exact formulas and legacy reference edges. References are declared evidence, not a full Tableau expression compiler. |
| Parameters and filters | Preserve defaults, domains, raw members, filter XML and known datasource/context/dimension stages. The legacy analyzer only resolves categorical Boolean member filters; other shapes retain gaps. |
| Custom SQL and relations | Retain exact XML-decoded SQL and relation trees. Existing Snowflake structural analysis is retained. Table references remain unresolved physical dependencies; joins/unions and unknown relations are not replayed. |
| LOD and table calculations | Retain formulas and authored `table-calc` addressing. Legacy partitioning derived from remaining view dimensions is explicitly labeled inference. Marker detection is conservative and may match literals/comments. |
| TDS files | Preserve fields, calculations, filters, relations and declared repository identity. A matched file is a consistency mirror; an unmatched file remains unbound declaration evidence, never a new workbook or automatically resolved published source. |
| Original XML | Retain exact supplied text for accepted safe files; the declaration-subset gap prevents unmodeled XML from being represented as complete extraction. |

Common dependencies point **from the consumer to its referenced input**; legacy
edges are reversed during normalization. Legacy reference tokens that cannot be
bound remain unresolved. `publishedsource`, `sqlproxy`, datasource URLs and
embedded repository references produce explicit published-source gaps, even when
a similarly named TDS exists. Logical `object-graph`/relationship declarations,
multiple worksheet data sources and blending markers remain unresolved. No
cardinality, key uniqueness, effective security or source completeness is inferred.

The adapter rejects DTDs/entities, NUL/non-UTF-8 declarations, wrong roots,
credential-bearing XML, case/Unicode path collisions and unsafe paths. It retains
hash-only gap evidence for rejected XML. XML is limited to 2,000,000 bytes, 5,000
nodes and depth 16 before recursive legacy helpers run; shared aggregate file
limits also apply. SQLGlot incidental logging is suppressed during legacy parsing
so rejected SQL does not escape through logs. These checks supplement the existing
sensitive-data intake policy; they are not a general-purpose secret detector.

## Acquisition handoff — no acquisition is performed by this adapter

1. Record site/server, Tableau/API versions, exporting principal, snapshot time,
   content/revision IDs, filters, requested inventory and acquisition failures.
   Enumerate authorized content using REST collection endpoints and follow all
   `pageNumber`/`pageSize` responses until their `totalAvailable` is accounted for.
   Pagination is endpoint-specific; do not treat one page as a complete inventory.
   [REST pagination](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_concepts_paging.htm).
2. Download authorized workbook definitions using
   [Download Workbook](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_workbooks_and_views.htm#download_workbook).
   The endpoint returns TWB/TWBX and supports `includeExtract=False`; non-admin
   users require `ExportXml`. Published data source acquisition is separate:
   [Download Data Source](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_data_sources.htm#download_data_source)
   returns TDSX, requires `ExportXml` for non-admins, and supports extract omission.
   JWT scopes are method/version-specific and do not replace content permissions.
   Do not fetch encrypted keychains or provide credentials to the adapter.
3. Keep archive/member hashes and an independently reconciled expected inventory.
   Supply safely inventoried TWB/TDS text. TWBX/TDSX are ZIP packages, and extracts
   contain data rather than a complete workbook definition; this adapter does not
   unpack packages or open Hyper/TDE. Prep TFL/TFLX files require another profile.
   [Official file types](https://help.tableau.com/current/pro/desktop/en-us/environ_filesandfolders.htm).
4. Use authorized Metadata API evidence, when available, to corroborate published
   identities and upstream lineage. The API indexes published content, not
   underlying raw data. Its visibility follows content/asset permissions, and
   inaccessible results may be obfuscated or filtered. Record permission mode and
   coverage gaps; empty results do not establish absence.
   [Metadata overview](https://help.tableau.com/current/api/metadata_api/en-us/),
   [permissions](https://help.tableau.com/current/api/metadata_api/en-us/docs/meta_api_permissions.html).
5. For Metadata API acquisition, page the relevant `Connection` fields using
   `first`, `after`, `pageInfo.endCursor` and `hasNextPage`; preserve errors and
   query limits. A selected field set is only a projection of metadata. The model
   documents custom-SQL support limits and that workbook upstream lineage can omit
   databases whose fields are unused by sheets. Metadata API JSON is corroborating
   acquisition evidence, not a currently parsed input format here.
   [Pagination examples](https://help.tableau.com/current/api/metadata_api/en-us/docs/meta_api_examples.html#pagination),
   [metadata model and omissions](https://help.tableau.com/current/api/metadata_api/en-us/docs/meta_api_model.html).

Extract omission is intentional data minimization, not proof of complete behavior.
Preserve separate evidence for published dependencies, policies, credentials
handling, refresh settings, Prep transformations, actions, stories and extensions.
All results retain `export_completeness: not_established`,
`native_validation: not_run` and `execution_performed: false`.

## Primary research and reuse decisions

| Candidate/source | License or authority | Decision |
| --- | --- | --- |
| [Tableau Document API Python](https://github.com/tableau/document-api-python), [license](https://raw.githubusercontent.com/tableau/document-api-python/master/LICENSE) | MIT; upstream explicitly describes its API as unsupported | Reviewed current upstream documentation. Do not add a dependency or copy implementation: its connection/field editing focus does not qualify complete relationships, blending or runtime semantics. Reuse our bounded parser and its existing native sample provenance. |
| [Document API documentation](https://tableau.github.io/document-api-python/) and [installation](https://tableau.github.io/document-api-python/docs/) | Tableau-owned OSS documentation | Historical format coverage reaches roughly Tableau 9.x; current docs test Python 3.10+. Neither statement expands this adapter's tested 26.1 fixture boundary. No Document API runtime is invoked. |
| [Tableau document schemas](https://github.com/tableau/tableau-document-schemas) | Official schema baseline; repository includes Apache-2.0 provenance | Preserve existing pin and separate unavailable-schema evidence. Do not weaken or replace the schema to make XML pass. |
| [Relationships: Data modeling in Tableau](https://www.tableau.com/blog/relationships-tableau-data-model) | Tableau engineering/product article, 2020-05-11 | Relationships select contextual joins and aggregation from the view; declarations alone cannot be translated to one fixed physical join. |
| [Relationships: Asking questions across multiple related tables](https://www.tableau.com/blog/relationships-asking-questions-across-multiple-related-tables) | Tableau technical article, 2020-06-12 | Cross-table calculations and LOD interactions justify unresolved semantic gaps and per-view validation. |
| [Order of operations](https://help.tableau.com/current/pro/desktop/en-us/order_of_operations.htm) | Official product documentation | Context, dimension, LOD and table-calculation order are separate; retaining a formula or filter does not prove equivalent population or totals. |

Native validation still requires a compatible Tableau environment, authorized
published-source bindings, representative views, filters and parameters, and
comparison evidence for totals, grain, security and interaction behavior. The
synthetic tests verify local evidence normalization and failure boundaries only.
