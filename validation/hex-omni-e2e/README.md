# Hex migration simulation results

September 10,2026. Local validation passed. Three authored Hex projects and one shared component were parsed and replayed into candidate dbt/Snowflake medallion models and selected Omni report definitions. No live Hex project, Snowflake query or Omni tenant was used.

| Evidence | Observed result | What it establishes |
|---|---|---|
| [Integrated replay](final/e2e-report.json) |125/125 checks passed;24 negative controls caught | Supported fixture transformations and expected rejection paths |
| [Source inventory/graph](final/source-graph.json) |3 projects, 1 component, 24 cells, 30 edges; zero static error gaps | Cell-level static extraction for these schema-valid files; 5 native-runtime/chart review gaps remain |
| [Report comparisons](final/report-comparisons.json) |13 scenarios;78 source/target comparisons against independent results | Dates, segment filters, defaults, empty windows, ratios, retained what-if and differing active definitions |
| [Gold rows](final/gold-rows.json) |10 invoice rows and 10 customer-month rows match | Stated grain, exact cents, historical segment and cohort proxy |
| [Metadata context](final/catalogue-verification.json) |4 objects,23 columns,4 resolved bindings | Pinned synthetic catalogue agrees with input/DDL; CSV landing remains explicitly proposed |
| [Model documentation](../../skills/data-model-accelerator/examples/hex-omni-e2e/documentation/README.md) |11 models, 74 columns; ERD, complete dictionary, all three layer guides | Declared documentation agrees with built column inventory |
| [Full regression suite](regression-tests.txt) |214 tests passed | Existing and new helper behavior with pinned optional engines |
| [Core-only suite](core-regression-tests.txt) |106 passed, 108 optional tests skipped onPython 3.9.6 | Core compatibility; skips do not qualify optional engines |
| [Native dbt parser](native-dbt-parse.json) |dbt-core 1.12.4/adapter 1.12.0;7 models, 4 sources, 85 test nodes parsed | Real dbt project/macro/schema/dependency parsing, with a dummy isolated profile and no warehouse connection |
| [Local dbt assertions](final/dbt-assertions.json) |9 singular SQL assertions returned zero violations | Selected authored SQL tests run through the local adapter; not all 85 native test nodes executed |
| [Looker regression](looker-regression-report.json) |59/59 checks;18 negative controls | Existing Looker simulation remains working after the Hex additions |

## Improvements demonstrated during testing

- SQL dataframe conversion could turn exact DECIMAL/HUGEINT totals into floating point. Materialization now preserves integers/Decimal values.
- Nullable pandas adjustment joins could lose large cents before arithmetic, and integer arithmetic could wrap. The reviewed interpreter now preserves exact Python integer values through the join/cast/arithmetic path. Missing adjustment rows map to zero; a present header-only CSV is supported, while absent content remains a gap.
- The local dbt renderer silently stripped unsupported hooks and could collapse duplicate model names. It now rejects unsupported config/hooks, duplicate identities and destinations that differ from the declared model map.
- DuckDB case folding could accept quoted Snowflake names that would not match the physical catalogue. The Snowflake subset now checks quoted table and column identity.
- Independent tests verify missing source cells, wrong component versions, cross-tenant source/target joins, changed formulas and consistent-but-incomplete dictionaries are detected.

[Independent QA](qa-review.md) records observed failures and closures. [The first integrated run](iterations/run1.json) passed before the final regression/precision/namespace hardening; [final evidence](final/e2e-report.json) pins the resulting code and artifacts. Frozen oracle results were authored separately before target or replay implementations were inspected, and remain unchanged.

## Review status

The [versioned review package](../../hex-omni-review-package.json) includes source, catalogue, code, model documentation and test artifacts. [Review gates](review-gates.json) intentionally remain incomplete for native target qualification and human approval. Passing local tests do not resolve the business choice between invoiced and paying customers or authorize deployment.

Native Hex execution and pandas behavior, chart/app interaction, Snowflake compilation/execution and row policies, Omni validation/access, real incremental ingestion, scale/cost, operational ownership and human acceptance remain open. The current context captures all source inputs; it cannot recover historical payment-event timestamps absent from the source. The documented cohort is an invoice-date proxy at the snapshot.

Reproduce with [the Hex guide](../../skills/data-model-accelerator/references/hex-omni-e2e.md). The new repository workflow is defined locally; no remote CI result is claimed for it.
