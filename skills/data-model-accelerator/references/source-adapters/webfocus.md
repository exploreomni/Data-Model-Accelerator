# WebFOCUS source adapter

Research checked: 2026-10-15. Qualification: bounded offline declaration extraction;
no WebFOCUS runtime, live tenant, effective-access or migration-parity qualification.
Input must be an approved, sanitized UTF-8 snapshot. The adapter does not collect
credentials, call APIs, load files named by source, execute procedures, or translate
WebFOCUS expressions into SQL.

## Implemented contract

`source_adapters.webfocus.parse(files)` accepts repository-relative paths, including
nested projects, and returns the shared `Report.finish()` evidence contract. Full
native text, file hashes and precise line/character locators are retained. Declared
names, JOIN IDs, field aliases/formats and native expressions remain identifiable;
identical filenames in different directories remain separate objects.

| Supplied source | Extracted subset | Boundaries |
| --- | --- | --- |
| `.fex` | Literal `TABLE FILE` and `DEFINE FILE` blocks; `SUM`/`PRINT` field lists; single-field `BY`; original `WHERE`; one-line `DEFINE`/`COMPUTE name[/format] = expression;`; single-key `JOIN key IN source TO [ALL] key IN target AS name` | One command per physical line, except inline SUM/PRINT/BY/WHERE/COMPUTE clauses. No formula evaluation or column-lineage inference. |
| `.mas` | Dollar-terminated FILENAME/SUFFIX, SEGMENT or SEGNAME/SEGTYPE, FIELDNAME or FIELD, ALIAS, USAGE or FORMAT, ACTUAL, MISSING and selected descriptive attributes | Attributes retain their original values. PARENT, DATASET and ACCESS references are unresolved declarations. Defaults, validity and runtime enforcement are not inferred. |
| `.acx` | Dollar-terminated SEGNAME, TABLENAME, CONNECTION, KEYS, READ and WRITE attributes | Native physical table/connection references are retained. These do not establish access, uniqueness, credentials or a working connection. |

Every supported file carries a runtime-context gap. Application search paths,
profiles, session settings and effective security are absent from ordinary source
snapshots. Dependencies remain `unresolved` even when another supplied file has a
matching basename: the server's application-path resolution is not reproduced.

Unrecognized files receive unsupported coverage. Unknown commands/attributes,
malformed quoting/declarations, missing END/dollar terminators, duplicate metadata
names, amper variables, Dialogue Manager, includes, SQL passthrough and session or
execution commands receive explicit gaps. Literal include names are dependencies
only; included sources are never loaded. Multiline expressions, aliases/display
modifiers, joins outside the single-key form, MATCH/MORE/HOLD, charts, styling,
security filters, stored procedures and dynamic metadata remain opaque.

Bounds are shared file/byte/path limits plus 800 interpretation units across all
files, 20,000 physical FEX lines per file, 32,768 characters per unit, 64 inline
clauses, 32 metadata attributes and 128 projected fields. Over-limit input retains
original source and an explicit gap. No omitted portion is promoted to parsed
coverage. This is not a complete FOCUS grammar or interpreter.

## Language evidence and technical reading

- [Developing Your Report Request, WebFOCUS 9.3.5](https://docs.tibco.com/pub/wf-wf/9.3.5/doc/html/910-crlang/creating_reports_overview63.htm)
  documents TABLE/END, JOIN, DEFINE and SUM/BY/COMPUTE in a report. Its distinction
  between record-level virtual fields and calculations over report values motivates
  retaining DEFINE and COMPUTE as different stages; the adapter does not reproduce
  either evaluation engine.
- [Creating a Numeric Expression](https://docs.tibco.com/appstudio/905/doc/html/topic/reporting/CreatingReportswithWFLanguage/source/exp83.htm)
  provides native DEFINE/COMPUTE expression syntax. Original formulas and formats
  are retained, including constructs the extractor cannot interpret.
- [Sequential Data Source Formats, WebFOCUS 9.3.4](https://docs.tibco.com/pub/wf-wf/9.3.4/doc/html/describing-data-lang/vsam62.htm)
  explains file, segment and field declarations, including USAGE and ACTUAL.
- [Parameterizing Master and Access File Values, WebFOCUS 9.3.4](https://docs.tibco.com/pub/wf-wf/9.3.4/doc/html/describing-data-lang/dif59.htm)
  illustrates dynamic metadata, including multipart TABLENAME values. This is why
  amper variables block static binding. The indexed official documentation was
  available during research; direct retrieval of this page failed.
- [Customizing a Procedure With Variables, WebFOCUS 9.3.6](https://docs.tibco.com/pub/wf-wf/9.3.6/doc/html/en-us/dev-reporting-apps/dm52.htm)
  explains Dialogue Manager substitution and command-stack execution. Parsing a
  literal file cannot establish the resulting procedure or runtime environment.
- [Manipulating Summary Values With Prefix Operators, WebFOCUS 9.3.8](https://docs.tibco.com/pub/wf-wf/9.3.8/doc/html/en-us/910-crlang/tot74.htm)
  describes recalculation at summary levels. Totals and RECOMPUTE remain gaps;
  recognizing SUM is not evidence of equivalent SQL aggregation.

These vendor-authored technical articles are primary interpretation references,
not evidence that this adapter implements every documented construct.

## Acquisition research only

No acquisition client is implemented. An authorized operator must supply source
and an independent export inventory/version/scope record.

1. **Authentication:** the vendor's [sign-on reference](https://webfocusinfocenter.informationbuilders.com/wfappent/TL4s/TL_ebi/source/02REST_WS12.htm)
   documents POST `/ibi_apps/rs/ibfs` with `IBIRS_action=signOn`, and session-cookie
   continuity for later calls. SAML/CAS may redirect before authentication; version
   and deployment configuration affect this behavior. A future connector must
   validate application response codes as well as HTTP success and protect all
   cookies/tokens. This historical reference does not establish a tenant's current
   authentication contract.
2. **Inventory:** [Listing Files Within an Application, 9.3.3](https://docs.tibco.com/pub/wf-wf/9.3.3/doc/html/embedded-bi-user/03REST_WS21.htm)
   documents GET `/ibi_apps/rs/ibfs/EDA/{node}/{app}?IBIRS_action=get`, XML child
   entries and FEX/MAS/ACX extensions. Inventory is not source content. Preserve
   server node, application, full path and source-returned identifiers externally.
3. **Repository source/export:** the official [repository REST reference](https://webfocusinfocenter.informationbuilders.com/wfappent/TLs/TL_ebi/source/02REST_WS16.htm)
   describes folder/content listing and `getContent` for FEX and URL text. Its
   `cmExport` operation invokes a pre-existing change-management scenario. That
   scenario's scope must be independently checked; report output and export success
   do not establish complete definitions. The FEX/URL endpoint is not evidence of
   a general MAS/ACX download API. This adapter does not unpack scenario archives.
4. **Pagination/completeness:** the reviewed list examples use XML children and
   declared sizes. A general cursor/page contract was not verified in the reviewed
   endpoints. Do not invent pagination parameters or treat one response, an empty
   result, permission-filtered content, or a scenario as a complete estate. Future
   acquisition needs version-specific traversal/paging documentation, bounded
   recursion, visible-versus-expected inventory reconciliation and omission checks.
5. **Execution:** the vendor's [Running a Report Within an Application](https://webfocusinfocenter.informationbuilders.com/wfappent/TL4s/TL_ebi/source/03REST_WS23.htm)
   is an execution API. It is outside source acquisition and this adapter; a report
   result does not reconstruct original logic or prove native migration parity.

## Open-source candidates and licensing

| Candidate | Evidence and license | Decision |
| --- | --- | --- |
| [WebFOCUS VS Code extension](https://marketplace.visualstudio.com/items?itemName=pvparuchuri.WebFOCUS) | Author's listing describes FEX/MAS/ACX highlighting and snippets. Its linked repository could not be retrieved and its source license was not verified. | Useful vocabulary reference only. No code copied; highlighting is not a semantic parser. |
| [Lark](https://github.com/lark-parser/lark) | Maintainer repository identifies a Python parsing toolkit and MIT license. | Candidate for a future grammar with explicit version pin and qualification corpus; no complete WebFOCUS grammar established by this research. Not a dependency here. |
| [pyparsing](https://github.com/pyparsing/pyparsing) | Maintainer repository documents a parser toolkit under MIT. | Alternative for grammar growth, not a verified WebFOCUS interpreter. Not a dependency here. |

The implementation uses Python's standard library, with no vendored third-party
parser code. No complete maintained open-source WebFOCUS semantic parser was
verified in this bounded research pass; that is a research limitation, not a claim
that none exists.

## Verification and next qualification

`tests/test_source_webfocus.py` uses synthetic, independently stated structural
expectations for FEX stages/keys, Master/Access attributes, nested identities,
exact source retention, malformed/orphan fragments, dynamic/unknown constructs,
limits and the shared registry contract. Offline tests establish extraction
behavior only. Before migration use, obtain versioned native exports plus profiles,
application-path bindings, include closure, effective security, parameter values,
report settings and native comparison results. Business behavior, data accuracy and
customer acceptance remain separately reviewable evidence.
