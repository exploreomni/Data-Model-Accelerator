# Independent Power BI local replay QA

Result: **32 focused tests passed; no remaining blocker found within the declared local pilot.** Confidence: High for this bounded synthetic evidence. Native Power BI, Snowflake and Omni execution, warehouse RLS enforcement and human migration acceptance remain unverified.

The independent oracle author reviewed and tested the source parser, positive M/DAX interpreters, generated dbt/Snowflake model and Omni local renderer after freezing expectations. This agent authored the oracle and this QA suite, but did not author or modify those implementations. Expected behavior was derived only from the scenario, raw JSON and adjustment CSV; no target or prior-pilot oracle informed the expected values. All four frozen oracle hashes remained unchanged. Mutations used disposable local synthetic copies; no customer code, live connector or warehouse was executed.

## Observed evidence

- `tests/test_powerbi_execution.py`: 32 tests passed using `/private/tmp/dma-e2e-env/bin/python`. The same file imports cleanly under system Python 3.9 and skips all 32 when optional engines are absent; these skips are not validation passes.
- All 22 frozen parameter scenarios matched actual source replay and local target rendering: **132 visual comparisons**, with row order, keys, NULL/BLANK and exact cents checked. Ratios use absolute Decimal tolerance `1e-12`.
- All 10 complete gold invoice facts matched the independent expected rows. The source comparison covers its 13-field crosswalk and preserves its distinct nullable raw adjustment evidence. Execution traces cover 20 native columns, nine actual DAX measures and three actual M partitions. Ten source JSON artifacts validated against pinned schemas; this is separate from native runtime execution.
- All 16 invalid contexts were rejected by both source and target paths. No/multiple multiplier selections use one; a sole selection of two doubles only the scenario presentation measure.
- Empty filtered results keep one KPI row with BLANK values. An actual zero invoice remains zero. Draft/SMB can have BLANK ordinary revenue, a 6,000-cent all-segment draft denominator and 27,000-cent status-replacing posted revenue simultaneously. Posted intersection remains BLANK. Default repeated mark denominators sum to 78,000 cents while the independently recomputed KPI denominator is 39,000 cents.
- Deliberate changes to actual M null handling, DAX calculated columns, status replacement/intersection, removal of segment context and multiplier alternate produced observable wrong answers and failed oracle comparisons. Removing the source payment tenant join triggered the invoice fanout guard; removing it in target SQL produced extra fact rows caught by the row/grain comparison.
- Inactive, many-to-many and bidirectional relationship changes; missing/altered role predicates; extra report/visual filters; stale source hashes; tenant-removing LOD; aggregate BLANK coercion; changed total policies; unsupported M/DAX and cyclic measures all failed visibly.
- Duplicate/reordered history and CDC replay preserved complete facts. Conflicting same-version CDC, overlapping history, current orphan payments and undeclared raw fields were rejected. Header-only adjustments preserved zero target adjustments and source nullable behavior. Large signed-64 payment amounts retained exact cents and negative outstanding balance; repeating payment ratios remained within tolerance against independent raw recomputation.
- Harmless temporary CSV reads were rejected both through the SQL guard and directly through the returned DuckDB connection. Unsupported M file/web calls and a changed Snowflake account invoked no query callback. The sentinel stayed unchanged.

## Review finding and closure

Code review found that the Omni companion's parameter, full security and per-measure context contracts were not initially checked against execution. The root implementation added strict checks. Five focused regression mutations now reject a changed multiplier alternate, omitted security table, removal of security instead of segment, replacement/intersection contradiction and omitted preserved context. The underlying native candidate measures still drive arithmetic and filter behavior independently. No expectation was changed for this closure.

Reviewed implementation SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `powerbi_execution.py` | `94e5e863e3dcd679da12364f3be6fc9ef0afe9a661c84d6d2ca53632af2d4688` |
| `powerbi_languages.py` | `b554fa23d68b1aa4ebd21c71e2062ad54a14bb644e5c96fc6765ba85a0c84af6` |
| `powerbi_source.py` | `46362f15b00348099d7a2468e2e4d0afedd76f68f441bd79c0e12411fb30cc56` |

## Limits

This qualifies only the authored three-table, nine-measure, three-visual Power BI subset and the supplied parameter matrix. It does not establish general M/DAX/PBIR support, live refresh semantics, native relationship/RLS enforcement, native Omni empty-context behavior, performance or production readiness. Target fanout is caught by validation; generating a local model alone is not a grain proof. The source parser and execution layer intentionally reject unsupported constructs. The standalone regression suite does not rerun or claim the root integrated runner, native dbt parse, documentation or catalogue acceptance evidence; those have separate receipts.
