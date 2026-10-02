# Third-party notices and example provenance

The root MIT license covers original Data Model Accelerator material. It does not replace third-party licenses, grant rights to external datasets, or imply vendor endorsement.

## Redistributed schema files

- **Microsoft Power BI/Fabric schemas.** The unchanged dependency closure comes from `microsoft/json-schemas`, commit `f36df424cb31e0634757d015902688c65bf5f8e5`. Retain the [MIT license](skills/data-model-accelerator/scripts/schemas/powerbi/LICENSE.txt) and [per-file provenance](skills/data-model-accelerator/scripts/schemas/powerbi/provenance.json).
- **Tableau document schema.** The unchanged XSD comes from `tableau/tableau-document-schemas`, commit `f4bce1eb55f0c1c010c0ef826cf531528d5910eb`. Retain the [Apache-2.0 license](skills/data-model-accelerator/scripts/schemas/tableau/LICENSE.txt) and [provenance](skills/data-model-accelerator/scripts/schemas/tableau/provenance.json). Its presence does not establish full native workbook validation; the provenance records the unresolved imported schema limitation.
- **Hex schema.** The public publisher endpoint is `https://static.hex.site/hex-file-schema.json`. The original downloaded schema has no embedded license declaration; no redistribution grant is asserted. This public repository does not distribute those schema bytes. Hex's optional bootstrap obtains the pinned schema directly from the publisher and verifies its checksum. See the [source contract](skills/data-model-accelerator/references/hex-source-contract.md) for the current installation and validation boundary.

## Dependency code inside recorded validation artifacts

Historical native dbt manifests, including compressed evidence archives, contain resolved dbt and dbt-duckdb macro definitions alongside the authored fixture SQL. These dependencies retain their own licenses:

- [dbt-core Apache-2.0 license](licenses/dbt-core-LICENSE.txt)
- [dbt-adapters Apache-2.0 license](licenses/dbt-adapters-LICENSE.txt)
- [dbt-duckdb Apache-2.0 license](licenses/dbt-duckdb-LICENSE.txt)

The unchanged license copies and their distribution versions, source repositories and SHA-256 hashes are recorded in [license provenance](licenses/provenance.json). Original copyright notices inside embedded macro source remain intact. Runtime packages are installed separately from the dependency requirements and retain their own licenses; this notice is not a complete software bill of materials.

## Examples and external seed exercise

The authored billing, rental and retail fixtures are synthetic exercises. Tenant identifiers, monetary values, authority labels, access personas and connection examples are fabricated; they are not customer records or live provider acceptance.

The source-only example delivery uses observations from 15 CSVs at `Data-Engineer-Camp/dbt-dimensional-modelling`, commit `f04d1876137e212e8c133ba75622aeec98bab225`, directory `adventureworks/seeds`. The [input manifest](validation/no-context-release-candidate/input-manifest.json) and the ZIP's source catalogue identify exact paths and hashes. The public package contains generated model code, metadata, documentation and validation results; it excludes the raw source rows and working database. Acquire the external seeds separately and evaluate the upstream terms before redistribution. This repository does not relicense that external dataset.

Historical qualification records preserve observed results and bounded limitations. See [public evidence handling](validation/PUBLICATION.md) for retained local paths and the distinction between historical checks and this publication's checks.
