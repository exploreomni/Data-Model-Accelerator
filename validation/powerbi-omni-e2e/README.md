# Power BI migration simulation results

September 11, 2026. The authored Power BI migration pilot passes its local simulation. One PBIP/TMSL/enhanced-PBIR project is parsed into candidate dbt/Snowflake medallion models and Omni definitions. The scenario deliberately reuses invented billing data to isolate Power BI behavior. No customer export, live warehouse or BI tenant was used.

| Evidence | Result | Scope |
|---|---|---|
| [Integrated replay](final/e2e-report.json) | 212 checks; 61 negative/denied controls | Fixed denominator; actual supported expressions and intended rejection reasons |
| [Source graph](final/source-graph.json) | 12 assets, 3 tables, 20 columns, 9 measures, 3 M partitions, 1 relationship, 2 roles, 3 visuals, 5 filters, 48 edges | Native identities, mappings, expressions, filters and current hashes |
| Official Microsoft JSON schemas | 10 project/report files pass | Offline pinned 12-file schema closure; excludes native TOM/M/DAX acceptance |
| [Report comparisons](final/report-comparisons.json) | 22 scenarios; 132 source/target visual comparisons | Ratios, selective filter removal, status replacement/intersection, BLANK, totals and disconnected selections |
| [Gold rows](final/gold-rows.json) | 10 full invoice rows | Tenant/invoice grain, historical keys, exact cents and all current statuses |
| [Catalogue](final/catalogue-verification.json) | 4 objects, 23 columns, 4 bindings | Synthetic account/namespace metadata bound to actual M SQL; CSV landing remains proposed |
| [Model documentation](../../skills/data-model-accelerator/examples/powerbi-omni-e2e/documentation/README.md) | 10 models, 64 columns | ERD, complete dictionary and bronze/silver/gold documentation match built schema |
| [SQL assertions](final/dbt-assertions.json) | 9 assertions executed locally | Grain, history, source quality and balance violations checked |
| [Native dbt parser](native-dbt-parse.json) | 6 models, 4 sources, 73 test nodes parsed | Native dbt-core 1.12.4/Snowflake adapter 1.12.0; dummy isolated profile, no warehouse connection |
| [Full regression suite](regression-tests.txt) | 396 tests passed | Pinned optional engines across all four pilots |
| [Core regression suite](core-regression-tests.txt) | 106 passed, 290 optional tests skipped | Python 3.9 compatibility; skips do not qualify optional engines |
| [Independent QA](qa-review.md) | See focused findings and closure | Oracle authored separately from both implementations; adversarial review |
| Prior pilots | [Looker](looker-regression-report.json), [Hex](hex-regression-report.json), [Tableau](tableau-regression-report.json) | Regression of their unchanged source/target contracts |

## Improvements and observed limits

The initial integrated run caught four cases where the parser correctly rejected unsupported relationships/storage modes but surfaced a generic error. The replay now checks those contracts first and preserves a specific reason. One orphan-payment control changed only a superseded CDC version; correcting all versions of that payment made the intended current-state defect observable. These were diagnostic/test-control corrections, not changes to business expectations. [Initial failures](iterations/run1/e2e-report.json) and the [next passing run](iterations/run2/e2e-report.json) remain recorded.

Independent QA exposed a metadata-consistency gap: the target renderer could accept companion descriptions that contradicted implemented parameter or measure context. The renderer now rejects conflicting parameter, security, BLANK and measure-context contracts. Actual native measure SQL and filter declarations still drive the target calculations.

The source SQL guard also handles SQLGlot's typed-date `TimeToStr` normalization for the reviewed ISO format. Source columns remain typed; monetary aggregates and ratios use exact inputs rather than floating-point approximations. Changed source graphs, unsafe M functions, unsupported DAX, unbound references, incomplete tenant keys, unsupported relationships, wrong-account catalogue bindings and output overwrites fail visibly.

Raw/scenario/CSV and independent expected-result hashes stayed frozen. Source and target authors worked independently in parallel; the oracle was frozen before implementation comparisons. The [final evidence](final/e2e-report.json) captures the final implementation hashes; earlier receipts describe earlier revisions only.

## Review status

The [review manifest](../../powerbi-omni-review-package.json) binds exact source, catalogue, runtime, target, documentation and test artifacts. [Review gates](review-gates.json) retain native execution and human approval blockers. The [runbook](runbook.md) separates local validation from qualification and cutover.

The native-source boundary remains material: Microsoft JSON schema acceptance does not prove Desktop/TOM opening, M/DAX execution, model refresh/folding, RLS service membership or visual behavior. The one-row ungrouped KPI is a predeclared local contract; native `tableEx` empty-result cardinality is not established. Native Omni outer-empty LOD/filtered measures, disconnected control mapping, NULL presentation, Snowflake security/execution, incremental ingestion, recovery, cost/performance and business acceptance remain unverified. No production deployment or approval is claimed.

Reproduce with the [Power BI exercise guide](../../skills/data-model-accelerator/references/powerbi-omni-e2e.md). GitHub workflow outcomes are revision-specific evidence separate from these captured local receipts.
