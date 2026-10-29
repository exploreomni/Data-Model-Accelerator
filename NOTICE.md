# Third-party notices and example provenance

The root MIT license covers original Data Model Accelerator material. It does not replace third-party licenses, grant rights to external datasets, or imply vendor endorsement.

## Redistributed schema files

- **Microsoft Power BI/Fabric schemas.** The unchanged dependency closure comes from `microsoft/json-schemas`, commit `f36df424cb31e0634757d015902688c65bf5f8e5`. Retain the [MIT license](skills/data-model-accelerator/scripts/schemas/powerbi/LICENSE.txt) and [per-file provenance](skills/data-model-accelerator/scripts/schemas/powerbi/provenance.json).
- **Tableau document schema.** The unchanged XSD comes from `tableau/tableau-document-schemas`, commit `f4bce1eb55f0c1c010c0ef826cf531528d5910eb`. Retain the [Apache-2.0 license](skills/data-model-accelerator/scripts/schemas/tableau/LICENSE.txt) and [provenance](skills/data-model-accelerator/scripts/schemas/tableau/provenance.json). Its presence does not establish full native workbook validation; the provenance records the unresolved imported schema limitation.
- **Hex schema.** The public publisher endpoint is `https://static.hex.site/hex-file-schema.json`. The original downloaded schema has no embedded license declaration; no redistribution grant is asserted. This public repository does not distribute those schema bytes. Hex's optional bootstrap obtains the pinned schema directly from the publisher and verifies its checksum. See the [source contract](skills/data-model-accelerator/references/hex-source-contract.md) for the current installation and validation boundary.

## Dependencies and synthetic examples

Runtime packages are installed from the pinned requirements and retain their own licenses. Generated dbt manifests may embed dependency macros; when distributing those outputs, retain the applicable dependency licenses and notices. Such execution outputs are not part of the current source tree.

The billing, rental, retail and Omni fixtures are synthetic. Tenant identifiers, monetary values, authority labels, access personas and connection examples are fabricated; they are not customer records or live provider acceptance. JSON schemas, provenance records and checksum pins are retained because the parsers and tests use them.

Historical release packages, external dataset provenance and their accompanying notices remain in Git history. See [qualification and reproduction](docs/qualification.md) for the historical snapshot and current testing boundaries. This repository does not relicense external datasets or grant rights to redistribute separately acquired inputs.

## Training artwork and typography

The training guide includes Cal Sans and IBM Plex fonts under the SIL Open Font License 1.1. Retain the [font licenses and provenance](docs/training/assets/fonts/PROVENANCE.md). The supplied Omni wordmark remains subject to its owner's trademark and artwork rights; the project MIT license does not relicense that mark or imply endorsement. Original teaching illustrations and the unchanged synthetic ERD have [documented provenance](docs/training/MAINTAINING.md#assets-and-provenance).
