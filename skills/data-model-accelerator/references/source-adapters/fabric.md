# Microsoft Fabric source adapter

Research checked **2026-10-15**. This adapter reads approved UTF-8 snapshots
locally. It performs no authentication, API requests, SDK installation, notebook
execution, Spark jobs, SQL execution, model evaluation or deployment. Fabric is
source evidence only; it does not add a warehouse deployment target.

## Implemented native boundary

| Native input | Bounded interpretation |
| --- | --- |
| Git `.platform` v2 | Explicit item type, display name, description and Git logical ID, including nested repositories. The closest ancestor `.platform` owns an item file. Directory suffixes do not establish identity. |
| Get Item Definition response | The exact `{"definition":{"parts":[...]}}` response, with optional `definition.format`. Each part must have `path`, `payload`, and `payloadType: "InlineBase64"`. The decoded `.platform` establishes item identity. |
| `Notebook` | One FabricGitSource `notebook-content.py`, `.sql`, `.scala` or `.r` retained verbatim; or one root-level `.ipynb` with nbformat 4, minor 0–5. Cell IDs, raw metadata, source fragments, and exact joined code are retained. Magics, environment, outputs and code dependencies are not evaluated. |
| `DataPipeline` | `pipeline-content.json` with native `properties.activities`. Top-level activity declarations and exact-name `dependsOn` references; `TridentNotebook` service item/workspace references remain unresolved. Nested flow, connection/dataset binding, scripts and execution semantics are not interpreted. |
| `Lakehouse` | `LakehouseDefinitionV1`: `lakehouse.metadata.json`; optional `shortcuts.metadata.json`, `data-access-roles.json`, `alm.settings.json` version 1.0.1. Shortcut targets and security declarations are retained, not resolved or enforced. |
| `SemanticModel` | Required `definition.pbism`, plus exclusively `definition/**/*.tmdl` or `model.bim`. The existing bounded Power BI reader retains model declarations, M/DAX, relationships and role expressions. Recognized settings versions are 1.0, 4.0 and 5.0; 1.0 requires TMSL. Unknown versions remain gaps. |

Only these four item types have body readers. Other `.platform` item types retain
metadata and raw parts with an unsupported-type gap. In particular, **Warehouse,
SQL endpoint metadata, SQL database projects, Report/PBIR, Dataflow, Spark job
and environment definitions are not semantically parsed here**. Warehouse SQL
stays verbatim; a `.sql` extension in Fabric might instead represent a Spark SQL
notebook. The adapter does not assume every Fabric item supports Get Definition,
select a T-SQL dialect from an arbitrary filename, or run a SQL project build.

[Microsoft's item-definition overview](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/item-definition-overview)
links to separate contracts for supported service item types. Service support
for an item type does not imply this adapter interprets that type. List Items,
Get Item metadata, operation-state responses, bulk export ZIPs, naked `parts`
objects and invented export envelopes remain unsupported. A supplied response
cannot authenticate its original endpoint, caller, request parameters or capture
time.

## Identity and version evidence

The preferred profile follows Microsoft's published
[platformProperties 2.0.0 schema](https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json):

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
  "metadata": {"type": "Lakehouse", "displayName": "Synthetic lakehouse"},
  "config": {"version": "2.0", "logicalId": "11111111-2222-3333-4444-555555555555"}
}
```

The [Git source-format article](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/source-code-format)
also shows a root-level `version: "2.0"` with schema URI
`https://developer.microsoft.com/json-schemas/fabric/platform/platformProperties.json`.
That documented shape is recognized with a visible legacy-profile gap: the URI
could not be retrieved during this research. These two profiles are explicit;
conflicting versions and arbitrary schema URLs are not accepted. This is a
bounded field check, not full JSON Schema validation. V1 `item.metadata.json`
and `item.config.json` are retained as unsupported; their coexistence with
`.platform` blocks body interpretation. The item type is case-sensitive.

`logicalId` is retained as the source-control identity. It is **not** substituted
for the workspace service `itemId`. The same logical ID can exist in different
workspaces. Repeated snapshots retain separate evidence and an ambiguity gap;
no automatic cross-workspace binding occurs. Missing/invalid logical identity
blocks body interpretation. Item directory names and response filenames never
supply omitted names, IDs or workspace identity.

## Provenance, bounds and security

Every original file remains in coverage with its UTF-8 SHA-256. Raw item parts
and original API responses are retained verbatim in the report. Decoded records
point to the original response path/hash and exact part index/payload locator.
Their `decoded_provenance` separately records the native part path and decoded
SHA-256. Decoded files are never written to disk. Imported Power BI objects and
edges are remapped into the Fabric report while preserving their native IDs,
expressions and source locators. Fabric's component fingerprint includes the
Power BI reader, its research note, legacy implementation and pinned schemas
transitively.

Input uses shared limits: 512 files, 8 MiB per file, 32 MiB total, bounded JSON
node/depth counts, duplicate-key rejection, and finite numbers. Decoded bundles
have separate aggregate 512-part / 32-MiB limits across the parse call and the
same per-file limits. Strict canonical padded Base64 and UTF-8 are required;
binary parts, unsupported encodings, oversize parts, duplicate paths, traversal,
absolute paths, URI paths, backslashes, noncanonical paths, case/Unicode
collisions and file/directory collisions reject the entire affected bundle
before interpretation. Unpadded/noncanonical Base64 stays an explicit gap even
if another client could decode it. A bad bundle's original response is retained.

URLs, schema references, native shortcut paths and runtime references are inert
source text. No remote schema or `$ref` is resolved, URL is fetched, source is
imported, template is rendered or nested definition envelope is expanded.
Notebook source and pipeline dynamic expressions remain unexecuted. Native role
or policy declarations do not establish actual access. Snapshots can contain
credentials, personal information, outputs and confidential code: use the
engagement's approved input projection and disclosure controls before sharing.
Raw retention does not sanitize content.

## Acquisition contract and omissions

The reader does not collect evidence, but an independently authorized collector
must preserve these API boundaries:

- [Get Item Definition](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/get-item-definition)
  uses `POST /v1/workspaces/{workspaceId}/items/{itemId}/getDefinition` and optional
  `format`. Despite retrieving a definition, it requires **read and write item
  permissions** and delegated `Item.ReadWrite.All` or the appropriate specific
  `itemType.ReadWrite.All` scope. It omits sensitivity labels. Protected labels
  can block retrieval unless the caller has the relevant label-removal usage
  rights. Do not describe this as a universally read-only permission surface.
- [List Items](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/list-items)
  requires a viewer workspace role and delegated `Workspace.Read.All` or
  `Workspace.ReadWrite.All`. Its `continuationToken`/`continuationUri` represent
  pagination. Capture the complete authorized page chain and intended folder,
  recursion and type scope separately; a supplied list is not complete workspace
  evidence. This adapter deliberately does not interpret item lists as bodies.
- [Long-running operations](https://learn.microsoft.com/en-us/rest/api/fabric/articles/long-running-operation)
  distinguish a `202` acceptance from a final result. Retain `Location`,
  `x-ms-operation-id` and `Retry-After`; inspect operation state and retrieve its
  result after success. A `Succeeded` state object alone is not a definition.
  Respect `429` retry guidance; neither acceptance nor pagination implies export
  completion. This adapter performs no polling.
- [Identity support](https://learn.microsoft.com/en-us/rest/api/fabric/articles/identity-support)
  distinguishes Entra users, service principals and managed identities. The
  service-principal tenant setting and each item API's identity support must be
  checked. Generic API support does not guarantee every item type supports the
  same identity. Credentials and tokens are outside this adapter's contract.

## Item-specific evidence limits

[Notebook definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/notebook-definition)
documents `FabricGitSource` and `ipynb`, with language-specific native source
filenames. The API page uses both `FabricGitSource` and `fabricGitSource` spelling;
these explicit spellings are recognized. Code and historical outputs cannot
establish current execution, successful dependencies, results, access or lineage.

[DataPipeline definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/datapipeline-definition)
documents activity names, types, `typeProperties`, dependencies, policy and
external references. This adapter preserves raw activity metadata, distinguishes
control dependencies from data dependencies, and leaves runtime expressions
unbound. Conditions, parameterized IDs, nested loops, dataset connections and
side effects require source-specific review. A unique supplied activity name
binds only within that item's top-level array.

[Lakehouse definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/lakehouse-definition)
provides settings and shortcut declarations, not a physical table/column
catalogue or data inventory. ALM settings control inclusion of shortcuts and
roles; data-access-role inclusion is disabled by default. Entra member lists are
not supported in these definition APIs/CI/CD. Empty GUIDs have contextual
substitution behavior and remain unresolved. Missing security files cannot prove
unrestricted access. Table schemas, grants, effective membership, shortcut
availability and SQL endpoint behavior require independent catalogue/security
evidence.

[SemanticModel definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/semantic-model-definition)
defines mutually exclusive TMDL/TMSL parts and required `definition.pbism`.
[Power BI semantic-model folders](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset)
explain settings-version constraints and pending/unapplied changes. Only the
bounded model reader is reused here; TOM validity, formula dependencies,
Direct Lake/DirectQuery behavior, refresh, service membership, report interactions
and runtime security remain unqualified. Additional parts, including pending
changes, remain explicit unsupported files rather than silently superseding the
saved model.

For warehouse work, [Microsoft's development/deployment overview](https://learn.microsoft.com/en-us/fabric/data-warehouse/development-deployment)
currently labels this area **preview** and describes SQL database projects,
DacFx, `.dacpac`, Git and deployment workflows. These are distinct contracts;
this adapter neither builds them nor treats source sync as deployed SQL schema.
Capture approved native DDL/catalogue evidence and qualify a separate bounded
warehouse reader before using it for model lineage or physical binding.

## Parser and open-source decision

The implementation uses Python standard-library JSON/Base64 and the repository's
Power BI reader. It does not add an SDK or dependency. The
[Microsoft JSON schemas repository license](https://github.com/microsoft/json-schemas/blob/main/LICENSE)
is MIT; schemas were researched, not copied or downloaded at runtime. Existing
Power BI parser/schema license decisions remain in [powerbi.md](powerbi.md).

Microsoft's [fabric-cicd project](https://github.com/microsoft/fabric-cicd) is a
[MIT-licensed](https://github.com/microsoft/fabric-cicd/blob/main/LICENSE)
deployment library. The official
[CI/CD planning article](https://learn.microsoft.com/en-us/fabric/fundamentals/understand-best-practices-fabric-cicd)
and [local deployment tutorial](https://learn.microsoft.com/en-us/fabric/cicd/tutorial-fabric-cicd-local)
are useful primary implementation context. The library's job is deployment,
not an inert semantic source parser; it is not imported, vendored or invoked.
Documentation and library examples do not establish tenant acceptance.

## Validation evidence

`tests/test_source_fabric.py` uses independent synthetic native fixtures, not
customer exports or native acceptance receipts. Tests cover Git/API identity,
raw code, nested roots, original/decoded provenance, model delegation and
fingerprint invalidation, malformed JSON/parts, unsupported types/versions,
missing parser dependencies, path/case/Unicode collisions, decoding limits,
nonexecution, pipeline references and lakehouse security gaps. The Fabric tests
run without optional packages on Python 3.9; full-repository optional suites
retain their own dependency skips. Passing tests means the bounded extraction
contract held for these fixtures, not that Fabric accepted or executed anything.
