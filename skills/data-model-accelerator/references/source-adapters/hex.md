# Hex source adapter

Research refreshed **2026-10-15**. This adapter is an offline source inventory,
not a Hex runtime, live connector or migration acceptance result.

## Accepted evidence and output

`source_adapters.hex.parse(files)` accepts the shared bounded mapping of relative
paths to UTF-8 text. It recognizes `.hex.yaml` exports with `schemaVersion: 3`
and reuses `hex_source.inspect_repo` unchanged. A private temporary directory
contains only supplied files; it is removed after inspection. The only other
input read is the installed, checksum-pinned publisher schema. No project code,
SQL, import, notebook kernel, API client or schema download is executed.

The report preserves project/component IDs, source-version IDs, native cell IDs,
project-scoped identities, array order, native configuration, SQL/Python text,
parameter names/defaults/options, chart/app declarations, connection references,
candidate variable/table/file dependencies and versioned component references.
Original YAML remains an expression with a file hash. Each extracted object and
finding refers to its original supplied path and locator. Duplicate native IDs
remain separate evidence objects and produce gaps; no export wins by overwrite.
Dependencies point from a consumer to the referenced producer and retain the
legacy edge kind and native reference.

The publisher's [Hex export guide](https://learn.hex.tech/docs/explore-data/projects/import-export)
describes YAML as project logic and app layout without outputs. Jupyter export
can lose Hex-specific SQL and input behavior, so `.ipynb` is unsupported here.
Supplied CSV and other companion files may provide file-reference evidence;
this adapter does not parse their data or claim their semantic coverage.

## Acquisition boundary

Acquisition requires a separately authorized capture. The documented API uses
bearer authentication. Personal tokens mirror user permissions; workspace tokens
have administrator-managed scopes, including project reads. Keep tokens outside
snapshots and record the workspace, capture time and visibility scope. The
official overview describes cursor pagination: request `limit` up to 100 and
continue with `pagination.after` until it is absent. Retain every response page
and reconcile against an independent inventory, including inaccessible items.
[API overview and token scopes](https://learn.hex.tech/docs/api-integrations/api/overview).

The [API 1.0.0 reference](https://learn.hex.tech/docs/api-integrations/api/reference)
documents `GET /api/v1/projects`, with archived/component/trashed/unlisted
inclusion flags defaulting to false, and `POST /api/v1/projects/export`.
Export accepts `projectId` and a version: `draft` is the default, while `latest`
selects the most recently published app. Preserve the chosen version and
resulting source-version ID; do not mix draft and published captures silently.
Project metadata alone does not contain the exported cell sources.

[Git export](https://learn.hex.tech/docs/explore-data/projects/git-export) is
another capture path for projects and components. It is enabled per project and
exports publishing changes; it is one-way. A repository therefore needs an
independent project/version inventory before anyone claims export completeness.
Connection credentials, live parameter values, source data, runtime outputs,
environment state and effective access require their own evidence; this adapter
does not infer them from configuration or a connection ID.

## Version and interpretation limits

The existing [Hex source contract](../hex-source-contract.md) pins the publisher
schema at `https://static.hex.site/hex-file-schema.json` to SHA-256
`e0a8d6f4261983194de2230821bcd86604d817301dc054a42665df4eb421bde0`,
retrieved on 2026-10-02. Missing or changed schema bytes produce
`hex.schema_unavailable`; setup must use the existing explicit bootstrap.
The adapter never downloads or replaces a schema. Other export versions fail
validation rather than being treated as v3. A schema match is structural
evidence, not vendor runtime validation or a statement about current features.

The reused reader parses dataframe SQL as DuckDB and warehouse SQL as Snowflake.
The latter is an assumption, recorded as `hex.sql_dialect_unverified` for every
warehouse SQL cell. Raw SQL and Jinja parameters are retained. Mutation SQL,
complex templates and unsupported code remain visible failures. Python is parsed
with `ast`; only its bounded dataframe subset contributes candidate analysis.
Dynamic calls, mutations, unsupported languages and missing variable producers
produce gaps. Python files referenced in source are never imported.

Component resolution requires the supplied component ID and exact requested
source version. Missing/version-mismatched/nested components remain gaps.
Even a resolved component has `hex.component_runtime_unverified`. Runtime inputs,
external files, chart selection, app filters and report interactions are not
evaluated. Unknown cell types retain configuration and an unsupported-cell gap.

Array order is retained without being promoted to execution order. Hex's
[execution model](https://learn.hex.tech/docs/explore-data/projects/project-execution/execution-model)
describes a reactive graph. The vendor-authored technical article
[Beyond linear notebooks](https://hex.tech/blog/beyond-linear-notebooks/)
explains direct code analysis and dependency-based recomputation. These support
preserving dependency evidence and explicitly qualifying dynamic state; they do
not make this static subset equivalent to Hex's graph engine. Native runs still
need separately captured project/component versions, parameters, identity,
watermarks, outputs and report-interaction checks.

## Reuse and licensing decisions

| Component | License and decision |
| --- | --- |
| Existing `hex_source.inspect_repo` | Reuse this repository's implementation and pinned schema contract unchanged. The wrapper adds shared evidence binding and explicit capability gaps; no second Hex grammar or execution engine is introduced. |
| [PyYAML](https://github.com/yaml/pyyaml/blob/main/LICENSE) | MIT; reuse pinned `PyYAML==6.0.3`. The shared safe reader rejects duplicate keys, aliases, executable tags and excessive structure before the legacy reader runs. |
| [jsonschema](https://github.com/python-jsonschema/jsonschema/blob/main/COPYING) | MIT; reuse pinned `jsonschema==4.26.0` with the existing Draft 7 schema and UUID format checks. |
| [SQLGlot](https://github.com/tobymao/sqlglot/blob/main/LICENSE) | MIT; reuse pinned `sqlglot==30.18.0` for the legacy bounded SQL analysis. Dialect parsing is candidate evidence, not query execution or proven lineage. |
| [Hex hextoolkit](https://learn.hex.tech/tutorials/connect-to-data/using-the-hextoolkit) | Vendor-documented package usable within Hex projects. No open-source license is established by that documentation; not installed, vendored or invoked. Its runtime access to connections is outside offline extraction. |
| Publisher schema and API specification | The schema has no embedded redistribution license; retain the existing separate-download policy and [repository notice](../../../../NOTICE.md). The API reference labels its specification `UNLICENSED`; no generated client/specification bytes are bundled by this change. |

## Verification

Run `python -m unittest discover -s tests -p 'test_source_hex.py'` and the unchanged
`test_hex_source.py` suite using the pinned parser dependencies and installed
schema. The new tests use fixed expected native IDs, formulas, parameter names,
versions and relation names from the synthetic three-project/component fixture.
They also cover stable hashes/ordering, missing components/files/variables,
duplicate identities, malformed/deep/unsafe YAML, schema drift/absence, missing
dependencies, non-Python code, private temporary cleanup, path collisions and
blocked source execution/network/outside-file access.

Fixture success establishes local extraction behavior only. The report always
retains `native_validation: not_run`, `export_completeness: not_established` and
`execution_performed: false`. Every supplied file is accounted for; unsupported
files and partial project interpretation remain visible.
