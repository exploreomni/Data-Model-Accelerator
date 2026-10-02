# Hex source extraction contract

Schema acquisition updated 2026-10-02; source-format review recorded 2026-09-10. This is a bounded static adapter plus a synthetic replay fixture, not a Hex connector or native runtime certification.

## Native format and pinned evidence

Hex documents a native YAML project format that preserves logic and app layout while excluding project outputs. Hex recommends this format over Jupyter exports because Jupyter can lose SQL-cell and input behavior. Hex also documents programmatic validation using its public JSON schema and the `*.hex.yaml` filename convention. [Hex import/export documentation](https://learn.hex.tech/docs/explore-data/projects/import-export).

The schema is an optional local dependency, excluded from the public repository and its MIT license. Its publisher URL and schema `$id` are [https://static.hex.site/hex-file-schema.json](https://static.hex.site/hex-file-schema.json). The current pin, retrieved 2026-10-02, is 127,155 bytes with SHA-256 `e0a8d6f4261983194de2230821bcd86604d817301dc054a42665df4eb421bde0`; it declares JSON Schema draft-07 and `schemaVersion: 3`. The schema contains no embedded license declaration; no broader redistribution grant is asserted.

Explicitly acquire this dependency before running Hex schema validation or the full optional test suite. From the repository root:

```sh
python3 skills/data-model-accelerator/scripts/bootstrap_hex_schema.py
```

For offline setup, use an already acquired copy with exactly the pinned bytes:

```sh
python3 skills/data-model-accelerator/scripts/bootstrap_hex_schema.py \
  --source /absolute/downloaded/hex-file-schema.json
```

Both routes verify the checksum before writing the Git-ignored `scripts/schemas/hex-file-schema.v3.json`. The network route uses only the publisher URL and rejects redirects. The URL is mutable: a different response fails closed and requires an explicit reviewed pin update. The parser never downloads schemas automatically, and an absent or changed local schema cannot count as successful native-format validation.

Historical 2026-09-10 qualification records used the earlier 126,750-byte schema with SHA-256 `9bec5a4ec25cddf4703425e25fe4540a04bc36408cf826ee917a5f78c71f6c67`. Those records remain unchanged and do not claim validation against the current pin. Preserve the actual schema hash with every new result.

The schema defines `meta.projectId`, `meta.sourceVersionId`, `meta.hexType`, `meta.codeLanguage`, ordered `cells`, app layout and shared/project assets. Native SQL uses `cellType: SQL`, `config.source`, `resultVariableName`, `dataFrameCell` and `dataConnectionId`. Python is `cellType: CODE` under project `codeLanguage: PYTHON`. An input's name/type/default/options and CHARTV2 settings use the exact schema properties. A component import is `COMPONENT_IMPORT` with `config.component.id` and `.version`. These field claims are grounded in the pinned schema, not invented adapter fields.

A connection asset in the pinned schema exposes its UUID, not account, database, role, warehouse, credentials or permission truth. Fully qualified SQL references supply authored physical names; a synthetic scenario may separately declare a connection binding. Do not label that scenario as native connection metadata.

## API and coverage

`scripts/hex_source.py` exposes `inspect_repo(repo) -> dict`; optional dependencies are PyYAML, jsonschema and SQLGlot. It does not execute SQL/Python, import notebook packages, call a tenant or make network requests.

Returned fields:

- `projects`: project/component IDs, source-version ID, path/hash, ordered scoped cell IDs, native metadata/layout/asset declarations.
- `cells`: stable scoped `projectId/cellId`, native cell ID, order, type, label, source/config, reads/writes, parsed analysis and parse status.
- `edges`: evidence-backed warehouse, file, variable and version-bound component references. The component's source cells remain independently addressable. Import cells expose exported variable names for downstream dependencies; repeated imports/writers remain ambiguous.
- `definitions`: SQL projection and Python assignment expressions with originating project/cell/path. Preserve these expressions and upstream filters when comparing metric definitions; matching names alone do not establish equivalence.
- `assets`, `gaps`, `counts`: file hashes, explicit error/review reasons and coverage counts. `native_runtime_validated` is always false. `static_coverage_complete` means the present input fits this adapter's analyzed subset without error gaps; it is not proof the repository contains every project or dependency.

The reader rejects duplicate YAML keys, aliases/anchors, invalid schema/UUID formats, symlink assets, oversized files and unsupported dynamic SQL templates. Identity fields optional in Hex's schema are still required for complete migration evidence; absence creates a gap and an explicitly unbound placeholder rather than a fabricated UUID. Duplicate project IDs, repeated cell IDs within a project, multiple variable writers, missing producers, cyclic dependencies, missing files/components and mismatched component versions are errors. The same cell label or UUID in distinct projects stays separately scoped.

Supported static content is one SELECT query per SQL cell; Python assignments, constant CSV paths, dataframe merges, fillna, integer casts and arithmetic; static inputs; component references; CHARTV2 dataframe references/settings; basic text. Joins, filters, groupings, CTEs, projections, Python reads/writes and merge validation arguments remain in evidence. Notebook order is retained separately from inferred dependencies. Unsupported native cell types are inventoried with gaps, not dropped. Dynamic imports/calls, branches, external state or column writes, unbound variables and dynamic paths require review. Safe parsing is not execution authorization.

App cell references are checked against the supplied cell set. Chart settings are preserved but not natively rendered or behaviorally validated. Shared filters, generated apps, nested components, dynamic inputs, partial exports, missing environment/security context and native output behavior require additional evidence. Generic YAML or Jupyter files are marked unclassified rather than automatically accepted as native Hex projects. Compare `assets` against an independently captured repository inventory to detect a deleted whole workbook; no directory scan can prove an absent file used to exist.

## Synthetic collection and source replay

`examples/hex-omni-e2e/input/repo/` contains three PROJECT exports—Revenue exploration, Customer retention and Executive performance—and a fourth COMPONENT export, Shared revenue calculation. The validation lane checks all four against the installed pinned schema. This is authored synthetic native-format content; no Hex tenant exported or imported it.

The shared component obtains current invoices using source sequence before deletion filtering, separately aggregates deduplicated payments, performs a tenant-qualified invoice-date history join, then reads the separately inventoried `adjustments.csv`. Python joins on tenant/invoice with `validate="many_to_one"`, fills absent adjustment rows with zero and derives net/outstanding integer cents. SQL and Python retain their source code and cell identities.

Revenue applies parameterized tenant/date/segment filters downstream and separately retains a what-if multiplier. Retention's original `active_customers` means positive-net posted invoices; Executive's original `active_customers` means positive-paid posted invoices. They remain distinct source definitions and require business choice before consolidation. Cohort month is an explicitly synthetic invoice-based proxy using full-capture current payments, calculated before report-window filters. It is not payment-event-time retention.

The local `report-contract.json` is an adapter manifest, explicitly not native Hex YAML. It selects the three stable project IDs, output variables, default inputs and original metric meanings. It does not grant tenant access. Root's separate replay harness may expand only validated component versions and interpret reviewed fixture SQL/Python in a restricted runtime. This adapter supplies evidence, not an unrestricted evaluator. Matching local results cannot prove Hex scheduling, user permissions, dependency reordering, dataframe coercion, chart behavior or published-app acceptance.
