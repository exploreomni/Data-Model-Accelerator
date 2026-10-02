# Independent review of the provisional candidate

**Outcome: all implemented local source-derived checks pass. Confidence: High for this pinned CSV snapshot and local simulation.** This is not native Snowflake/Omni qualification, legacy Excel agreement, business acceptance or access-control enforcement.

The analyst froze expected results from the raw CSVs before reading any candidate artifact. The original frozen artifacts remain unchanged. Candidate field names were then mapped to the independently defined entity roles and values. The analysis did not derive its expected monetary results from candidate SQL.

| Evidence lane | Coverage | Result |
|---|---|---|
| Raw input scope | 15 CSVs, 120 columns, 54,068 rows | Complete for supplied files |
| Bronze preservation | 15 relations and every source cell | Exact lexical preservation |
| Silver preservation | 15 relations and every source cell | Exact normalized preservation, with the timestamp erratum below |
| Source retention comparisons | 692,214 cell comparisons across Bronze and Silver | Zero normalized mismatches; no missing/extra/duplicate source keys |
| Gold row values | Six entity/relationship roles, 216,289 mapped cells | Zero mismatches |
| Gold dimension population | All source rows in five source-backed dimensions, including unused dimensions; 78,654 mapped cells | Zero mismatches |
| Payment-type dimension | Complete distinct source card-type population | Pass |
| Aggregates | 13 order/line slice groups: all, month, status, online, territory, customer, product, category and discount as applicable | Exact Decimal agreement |
| Role-specific geography | Every order through separate billing and shipping paths | Exact agreement |
| Reason analysis | Distinct source order IDs and matched-header order IDs for all reasons | Exact agreement; orphan bridge links remain visible |
| Projection execution | All 43 models/393 columns plus 15 raw relations/120 columns, all rows fetched | 58/58 relations and 513/513 columns evaluate |
| Published fields | All nine Gold relation surfaces against explicit allowlists | Pass; no denied raw card/person/address fields |
| Negative controls | Five defects injected into actual candidate relations in isolated memory | 5/5 intended assertions detect their defect |
| Actual Omni YAML replay | 15 measures across 52 cases, 11 joins, 3 topic grains, 99 dimensions and 8 grouped queries | All pass in the bounded local interpreter |
| Semantic negative controls | Wrong measure field, removed DISTINCT, and wrong date-role predicate in actual YAML definitions | 3/3 intended defects detected |

The Gold row-value and additional dimension-cell denominators overlap; they must not be added and described as unique-field coverage. Every Gold entity key population is covered, but this is not a claim that every possible business rule has a trusted definition.

The five negative controls duplicate a referenced product dimension row, fan out actual line facts through the reason bridge, change one actual order amount by exactly 0.01, exclude an actual orphan detail row from a Bronze clone, and expose an actual source-linked credit-card ID in a published order query. The checks report the expected grain, amount, missing-key or publication-field failure. No syntax failure is counted as defect detection. Original raw files and the candidate database were not mutated.

## Actual semantic definitions and final rerun

The actual native Omni YAML files are hashed and parsed with SQLGlot using Snowflake syntax, then replayed against the final candidate database in DuckDB. The supported subset is explicit: direct quoted dimensions; recursive count, distinct count, sum and ratio/NULLIF measures; forward many-to-one left equality joins; and topics without hidden filters or join overrides. Unsupported behavior fails rather than being guessed. All/empty/date/orphan cases preserve NULL and distinct-count behavior, while every join is checked by source identity and expected target key. Monetary comparisons remain exact Decimal; only the floating ratio uses an explicit 1e-12 absolute tolerance. Its numerator and denominator are independently checked exactly.

This is bounded local semantic replay, **not native Omni compilation, query planning, runtime, permissions or AI-answer validation**. All original native files remain unchanged. The final physical and semantic checks were rerun against the modeler’s final database after nonsemantic style/metadata corrections. Both passing runs remain available: first-run receipts under `prior-pass-01/`, current final receipts at this directory’s root. The original oracle freeze and input hashes remain unchanged.

## Source findings retained by the candidate

- 41 order lines reference missing headers. The candidate retains all 5,716 line IDs.
- 46 reason links reference 23 missing headers. The candidate retains all 1,710 bridge pairs.
- Each address role has 69 missing references; nullable joined attributes and source IDs remain separate.
- 17,719 customer-to-person references are unmatched. All 19,820 customer IDs remain represented.
- Fifteen source subtotals differ from unrounded proposed line arithmetic by at most 0.00005. Both values remain visible.
- All-line derived net is 12,641,672.212954; header subtotal is 12,527,981.9927. These have different populations and rounding behavior and must not be forced into equality.
- The many-valued reason bridge inflates measures when naively joined. The separate fact populations and semantic boundaries need to remain intact.
- `NA` is preserved as a source country code. CSV blanks and padded text are handled explicitly.

## Normalization erratum

The original oracle ran on system Python, whose timestamp parser rejected the valid source value `2014-02-08 10:03:55.51` for product ID 940. That made its inferred type for the whole `modifieddate` column text. Comparing the candidate's correctly typed timestamp against that text classification initially produced 504 apparent mismatches.

The initial comparison report, original oracle and frozen expectations are retained. A narrowly scoped, source-hash-verified erratum normalizes variable fractional-second widths without rounding or introducing a timezone. That resolves the comparison without a candidate change. The error and correction are fully recorded in `candidate-comparison-initial.json`, `timestamp-normalization-erratum.json` and its reproducible script.

## Qualification limits

Currency, status/cancellation definitions, metric ownership, timezones, fiscal policy, CDC/deletion/history, refresh guarantees, real warehouse objects/constraints, operational ownership and actual user-role enforcement remain unknown. Matching these CSVs cannot establish those facts. Omitting sensitive fields from Gold is a surface control; native denied-role tests must still verify access to raw, Bronze and Silver. There is no legacy workbook baseline.

## Evidence and replay

- `benchmark-freeze.json`, `input-hashes.json`, `expected-results.json`, `expectation-contract.json` and `source-row-fingerprints.json`: original immutable oracle.
- `supplemental-freeze.json` and `supplemental-expected-results.json`: geography, calendar and other source-derived expectations, also frozen before candidate inspection.
- `candidate-comparison.json`, `candidate-probes.json`, `dimension-comparison.json` and `omni-local-replay.json`: final results.
- `independent-validation-receipt.json`: database, oracle and script hashes plus environment and scope.
- `oracle.py`, `supplemental_oracle.py`, `timestamp_normalization_erratum.py`, `compare_candidate.py`, `probe_candidate.py`, `compare_dimensions.py` and `replay_omni.py`: reproducible checks.

Candidate DB SHA-256: `eebbd3a657f05074da1210d4c844780ed62ebb5effe4878ee6812b1ee3859008`.

Frozen expected-results SHA-256: `ac68064f50972e7ce1be750bb1327ef1ab1f7f5abec4bf8465077e0a8a576ab4`.

The local database copies contain restricted raw values and must not be included in a distributable package.
