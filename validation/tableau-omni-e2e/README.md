# Tableau migration simulation results

September 10, 2026. The local migration simulation passed. One authored Tableau workbook and its TDS/TWBX artifacts were parsed and replayed into candidate dbt/Snowflake medallion models and selected Omni definitions. The billing records deliberately reuse the Hex pilot's synthetic domain to isolate Tableau behavior. No live Tableau project, Snowflake query or Omni tenant was used.

| Evidence | Result | Scope |
|---|---|---|
| [Integrated replay](final/e2e-report.json) |160/160 checks;44 negative controls | Supported transformations and intended rejections; denominator frozen before the first integrated run |
| [Source graph](final/source-graph.json) |1 workbook,1 datasource,3 sheets,1 dashboard,29 fields,15 calculations,5 parameters | Original identities, formulas, defaults, worksheet context and dependencies; native runtime gaps retained |
| [Packaged workbook](../../skills/data-model-accelerator/examples/tableau-omni-e2e/input/packages/billing.twbx) |3 byte-matching members | TWB/TDS/CSV compared with plain-file authority; no extraction or duplicate workbook counting |
| [Report comparisons](final/report-comparisons.json) |16 scenarios;96 source/target sheet comparisons | Independent results for date/segment context, FIXED, partitioned shares, empty/zero cases and multiplier changes |
| [Gold rows](final/gold-rows.json) |10 full invoice rows | Invoice grain, tenant/history keys, exact cents, signed balances and all current statuses |
| [Catalogue](final/catalogue-verification.json) |4 objects,23 columns,4 bindings | Pinned synthetic metadata, raw DDL and source SQL; ADJUSTMENTS is a proposed CSV landing |
| [Model documentation](../../skills/data-model-accelerator/examples/tableau-omni-e2e/documentation/README.md) |10 models,64 columns | ERD, complete dictionary and bronze/silver/gold guides agree with built schema |
| [dbt assertions](final/dbt-assertions.json) |9 SQL assertions returned zero violations | Authored singular assertions executed through the local adapter |
| [Native dbt parser](native-dbt-parse.json) |6 models,4 sources,73 test nodes parsed | dbt-core1.12.4/adapter1.12.0 with isolated dummy profile; no warehouse connection, compile or run |
| [Independent QA](qa-review.md) |31 focused tests passed | Independently authored oracle, source/target fidelity and adversarial changes |
| [Full suite](regression-tests.txt) |310 tests passed | Pinned optional-engine regression across the repository |
| [Core suite](core-regression-tests.txt) |106 passed,204 optional tests skipped | Python3.9 compatibility; skipped optional tests do not qualify those engines |
| [Hex regression](hex-regression-report.json) |125/125 checks;24 negative controls | Existing Hex pilot remains working |
| [Looker regression](looker-regression-report.json) |59/59 checks;18 negative controls | Existing Looker pilot remains working |

## Improvements from testing

- Native context flags and Boolean filter memberships now reject ambiguous or contradictory values.
- The target rejects companion metadata that contradicts its supported worksheet context order or presentation stage.
- Exact-cent totals remain integers/Decimals. Derived Omni ratios now use their parsed native numerator/denominator and exact selected inputs; the large-ratio regression no longer loses precision in DuckDB division. Unsupported floating-point precision is an explicit failure.
- Source replay verifies current source asset paths and hashes, rejecting a cached graph after file changes.
- Native parameter domains are enforced during replay. Final review found that the authored segment list contradicted the predeclared free-text/unknown-segment test contract; the synthetic workbook was corrected to an `any` string parameter and its package/crosswalk were rebound. Frozen raw inputs and independent expected results were unchanged. List and range mutations now have explicit regression coverage.
- Catalogue binding checks the actual parsed connection/account/namespace and proposed CSV evidence, preventing same-named tables in another account from appearing qualified.
- Independent documentation tests remove a column from both inventory and dictionary, rebind the dictionary hash, and still catch the omission against actual built columns.

The [first integrated run](iterations/run1/e2e-report.json) and [pre-domain-check run](iterations/run2/e2e-report.json) preserve earlier scoped receipts. Subsequent parser precision, hash-binding, parameter-domain and regression closures are reflected in [final evidence](final/e2e-report.json). Earlier local success did not establish native parameter-domain fidelity. Frozen expectations were not regenerated during testing.

## Review status

The [review manifest](../../tableau-omni-review-package.json) binds source, catalogue, implementation, target, documentation and test evidence. [Review gates](review-gates.json) deliberately retain native execution and human-approval blockers.

Tableau's pinned official XSD was attempted with lxml and could not compile: the publisher file references missing namespace definitions. The graph preserves the actual error under `official_schema_validation`. Successful XML extraction and local replay do not establish schema acceptance or native Tableau opening.

Native Tableau/Hyper/rendering, Snowflake compile/execution and access policies, Omni LOD/pivot/filter/security behavior, incremental ingestion, recovery, performance/cost, operational ownership and business approval remain unqualified. FIXED customer value is context-sensitive and repeated across marks; no additive grand total is claimed. The report companion contains local presentation metadata plus proposed documented native expressions, not an exported Omni workbook.

Reproduce using the [Tableau exercise guide](../../skills/data-model-accelerator/references/tableau-omni-e2e.md). The review branch's automated runs are revision-specific GitHub evidence, separate from these captured local receipts.
