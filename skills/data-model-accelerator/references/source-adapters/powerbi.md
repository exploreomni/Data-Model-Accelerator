# Power BI source adapter

Research checked 2026-10-15. This is an offline, bounded inventory of supplied
UTF-8 files, not a Power BI execution engine or a complete TOM implementation.
It preserves source hashes, locations, native metadata and raw expressions.

## Accepted formats and versions

| Input | Implemented boundary |
| --- | --- |
| PBIP project | Existing `powerbi_source.inspect_repo` profile: one PBIP entrypoint, one report pointer, confined local `byPath` semantic model, TMSL `model.bim`. |
| TMSL `*.bim` | Database metadata object containing `name`, integer `compatibilityLevel >= 1200`, and `model`. This is extraction, not validation of every property against TOM. TMSL commands are not run. |
| Enhanced PBIR | Existing profile retains report/page/visual/filter definitions, ordered projections and candidate references. Report content version `2.0.0`; tableEx projection subset. Unsupported behavior stays a gap. |
| TMDL `*.tmdl` | Documented declaration subset: database, model, table, column, measure, partition, relationship, role, tablePermission and named expression; model ordering refs for table/role/expression. Always partial coverage. |
| PBIX, PBIR-Legacy, opaque binaries | Unsupported; export an approved text snapshot with the source application first. |

The legacy validator reuses the repository's Microsoft schema bundle pinned to
`microsoft/json-schemas` commit `f36df424cb31e0634757d015902688c65bf5f8e5`
(bundle checked 2026-09-11). Exact schema roots are PBIP properties `1.0.0`,
semantic-model definition properties `1.0.0`, report definition properties
`2.0.0`, report `3.3.0`, page `2.1.0`, visual container `2.9.0`, pages metadata
`1.1.0`, and version metadata `1.0.0`. See
[`provenance.json`](../../scripts/schemas/powerbi/provenance.json) for URLs and
hashes. A newer schema is a coverage gap; no schema is invented or fetched at
runtime. Microsoft documents schema versions in each PBIR file's `$schema` URI.
[Microsoft report format documentation](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report)

## What extraction preserves

TMSL extraction keeps tables, columns, measures, partitions, named expressions,
relationships, roles and table permissions. Native metadata stays attached,
including lineage tags, hidden flags, relationship direction/activity, RLS text
and column permissions. M/DAX expressions and SQL query partitions are retained
without evaluation. JSON line arrays are joined with newlines; the original
native array remains available. Relationship endpoints and permission table
references resolve only against the same supplied model scope.

TMDL uses tab or four-space structural indentation. It supports quoted names,
doubled quote escapes, property scalars, single-line and indented expressions,
and triple-backtick expression blocks. Expression payload whitespace and the
original TMDL expression slice are retained, rather than reconstructed as a
TOM-normalized expression. Relationships use qualified column names. Unknown
fragments receive explicit gaps; malformed declarations retain the entire file
as an unparsed object. No defaults, inferred role membership, expression
dependency resolution or complete partial-declaration merge is claimed.
[Microsoft's TMDL syntax and examples](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview)

Model extraction proceeds even when the report binding fails, so an unsupported
remote report reference cannot silently erase local model security evidence.
Legacy lexical DAX edges remain **candidates**, with canonical consumer IDs;
they do not establish complete or semantically resolved lineage. Native report
behavior, dynamic format strings, calculation groups, perspectives, hierarchy
semantics, refresh/folding, object-level security enforcement and unsupported
TMDL fragments require separate review and native validation.

## Acquisition contract and missing evidence

Acquire text using Power BI Desktop Save as Project, an authorized TOM/XMLA
export, or an authorized Fabric definition export. Supply model and report
definitions together with the extraction date, workspace/item IDs, chosen
format, permissions and exclusion manifest. Fabric semantic definitions use
TMDL by default or explicit TMSL, not both simultaneously. Preserve the original
parts before decoding approved `InlineBase64` payloads into the file mapping;
the adapter does not unwrap API responses or request remote URLs.
[Microsoft semantic definition format](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/semantic-model-definition)

The Fabric v1 semantic-model `getDefinition` operation requires model read/write
permission and delegated `SemanticModel.ReadWrite.All` or `Item.ReadWrite.All`.
It supports TMDL/TMSL and long-running operations. Sensitivity labels are omitted
and encrypted labels block export. Report `getDefinition` similarly requires
report read/write permission with `Report.ReadWrite.All` or `Item.ReadWrite.All`;
it also omits sensitivity labels and may return an asynchronous operation.
Complete the documented operation polling and preserve any errors/omissions.
[Semantic-model API](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/get-semantic-model-definition),
[report API](https://learn.microsoft.com/en-us/rest/api/fabric/report/items/get-report-definition)

Workspace item discovery is paginated. Fabric v1 `List Items` requires a Viewer
workspace role with `Workspace.Read.All` or `Workspace.ReadWrite.All`; follow all
`continuationToken`/`continuationUri` pages in the authorized scope. A visible
item list is not proof that every definition could be exported. This adapter
does not paginate or assess permissions. Remote `byConnection` models, gateway
bindings, credentials, tenant role assignments and effective security require
separate evidence; they are never inferred from report files.
[List Items API](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/list-items)

## Reuse assessment

| Candidate | Evidence and decision |
| --- | --- |
| Existing repository parser | **Reused** for pinned-schema validation and PBIP/PBIR report inventory. Its source files remain unchanged. The caller stages approved inert text in a temporary directory; no source scripts, hooks or URLs run. |
| Microsoft TOM `TmdlSerializer` | Preferred full-fidelity TMDL parser/serializer when a separately reviewed .NET SDK integration is added. `DeserializeDatabaseFromFolder` creates the TOM database representation. No SDK dependency/version is installed or claimed by this Python subset. [Official API workflow](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview) |
| Microsoft `powerquery-parser` | MIT-licensed TypeScript lexer/parser, useful for future M AST extraction; a parser is not M execution. Not installed here: adding a Node bridge solely for syntax would not supply connector, folding or native runtime validation. [Maintainer repository and license](https://github.com/microsoft/powerquery-parser) |
| `pbi-tools` | Maintainer repository identifies AGPL-3.0 and a .NET/Power BI extraction toolchain. Consider only as a separately approved operator extraction tool; no code vendored, linked, copied or installed into this MIT repository. [Repository](https://github.com/pbi-tools/pbi-tools) |
| Tabular Editor 2 | Core repository license is MIT, with additional third-party licenses; do not confuse it with the separate Tabular Editor 3 product. Useful operator/TOM ecosystem tooling, not a runtime dependency here. No source copied. [Maintainer repository](https://github.com/TabularEditor/TabularEditor) |

## Verification and limits

`tests/test_source_powerbi.py` uses independently authored synthetic TMSL/TMDL
metadata based on the official syntax examples, plus the existing synthetic PBIP
case for regression compatibility. Tests cover raw M/DAX/RLS, relationship
directions, cross-file references, malformed input, missing and duplicate
identities, unsupported grammar, source non-execution, remote references,
path confinement and canonical report validation. The legacy tests remain
unchanged. No customer source or third-party fixtures were copied.

The common input limits apply; the legacy PBIP profile additionally has bounds
of 200 files, 2,000,000 bytes per file and 10,000,000 bytes total. Its narrower
limit produces an explicit gap. Full folder coverage, valid JSON schemas and
passing local tests do not establish export completeness, refresh success,
security equivalence, native behavior or customer acceptance.
