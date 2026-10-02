# Bounded raw CSV source contract

This reader supports raw-only discovery without inventing a modeled source project. It is a metadata collector, not a source-system catalogue, profiler of business meanings, code generator or execution adapter.

`raw_csv_source.inspect_csv(data: bytes)` consumes bytes already read under the caller's safe filesystem and byte limits. It performs no filesystem access, network request, import of source content, formula evaluation or writes. The supported format is comma-delimited UTF-8 (optional BOM) with one required header record. Quoted delimiters and multiline fields use Python's strict CSV parser. Dialect detection and legacy encodings are not guessed.

Output contains:

- `sha256` and `size_bytes` for the exact selected file bytes, including BOM/newline representation.
- `columns`: original header `name`, one-based `position`, and `data_type: text`. No numeric/date/Boolean or warehouse types are inferred from cell appearance; identifiers such as padded codes remain uninterpreted.
- `row_count`: exact count of logical data records only after EOF; `null` when parsing or a record bound prevents a complete count. `records_observed` is a bounded partial count, never a substitute for `row_count`.
- `metadata_complete` and stable `gaps` codes. Duplicate exact headers and case/whitespace-normalized collisions are separate gaps; header spellings are not repaired. Ragged rows are counted as logical records but do not produce a complete tabular metadata verdict. Blank records are not silently discarded.
- `native_types_verified: false`, `source_platform: unknown`, `grain: unknown`, and the explicit lexical-text/null-semantics caveat.

No source row values, examples, minima/maxima, value-derived types, formula bodies or parser exception strings enter the output. Column names remain untrusted source metadata. Empty strings are not assigned SQL NULL meaning by this inventory.

The default metadata bounds are 1,000,000 data records, 2,048 header columns and 131,072 characters per field. The CSV runtime's own field-size guard is not changed; if it is more restrictive, that is an explicit parser/runtime-field-limit gap. A complete byte hash does not imply complete CSV parsing. Existing file-count, file-byte, total-byte, traversal, secret and symlink policies apply before this helper is called. Their limits are not automatically raised for CSVs.

`plan_specialists.py` adds an asset's `raw_csv` metadata when bytes were read, and routes otherwise-unassigned `.csv` files to the `raw_csv` specialist. Existing native project/explicit profile ownership takes precedence; in particular, a dbt-owned seed remains dbt-owned. A size-limited file can still have the format routing clue while retaining a null hash and an unreadable status. Symlinks are excluded, never followed.

`platform_readiness.py` adds `raw_csv_inventory` records with `path` and `source_owner`. Readable CSV metadata is identical to the shared reader's output. Observed CSV paths that could not be read retain `metadata_complete: false`, null hash/size/count, empty columns and the scanner's gap codes. CSV cell contents are never examined for vendor/configuration fingerprints. The repository's selected target framework/warehouse is unaffected.

`metadata_complete: true` is scoped to the selected CSV structure only. It does not assert source completeness, original warehouse schema, live platform identity, true/enforced keys, lineage, business metric definitions, historical report/Excel parity, privacy authorization or native execution. Any of those requires independent evidence and its existing review gate. The specialist's returned coverage must describe this bounded metadata scope rather than claiming full native semantics were parsed.
