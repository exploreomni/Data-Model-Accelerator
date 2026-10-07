# Power BI to warehouse and Omni qualification exercise

This authored billing example tests PBIP/TMSL/enhanced-PBIR source artifacts through a bounded local Power Query M/DAX interpreter, candidate dbt/Snowflake models, and an independent Omni definition renderer. Read [powerbi-source-contract.md](powerbi-source-contract.md) for supported native formats, pinned Microsoft schemas and source limitations. The [scenario](../examples/powerbi-omni-e2e/input/scenario.md) is the predeclared behavioral contract, not a customer-approved business definition.

## Reproduce

Use Python 3.12 and an isolated environment. From the repository root:

```sh
python3.12 -m venv /tmp/dma-powerbi-env
/tmp/dma-powerbi-env/bin/python -m pip install -r skills/data-model-accelerator/scripts/requirements-powerbi-e2e.txt
/tmp/dma-powerbi-env/bin/python -m unittest discover -s tests -v
/tmp/dma-powerbi-env/bin/python skills/data-model-accelerator/scripts/run_powerbi_omni_e2e.py --output /absolute/new-powerbi-run
```

Output must be a new directory outside the case. An existing output cannot be overwritten. No warehouse credentials are used. The interpreter denies external access, dynamic imports, source hooks, unreviewed SQL functions and native connector execution. It is a fixture validator, not a sandbox for arbitrary customer programs.

## Source to target boundary

The three source tables are Invoices, effective-dated Customers, and a disconnected Scenario selector. Two Import partitions use Snowflake native SQL for CDC, payment preaggregation, temporal keys and adjustments. Subsequent M columns and a DAX calculated column compute reusable net, month and outstanding values. Four raw contracts, four silver models and two gold models place these transformations upstream. Historical segment still propagates through the tested many-to-one customer relationship.

Nine source measures are homed on Scenario to avoid native same-table column/measure name collisions. Eight corresponding native Omni measure candidates plus a local presentation rule retain query-time behavior. `SUM` over no rows remains BLANK/NULL; `DIVIDE` does not silently turn a missing or zero denominator into zero. KPI totals recompute at their own grain. `REMOVEFILTERS` clears only segment context, `CALCULATE` can replace status, and `KEEPFILTERS` intersects it. The disconnected multiplier remains downstream; joining its two rows to invoices would cause fanout.

The independent source interpreter consumes the actual M/DAX expressions and native model/report mappings. The target renderer consumes actual Omni dimensions, aggregates, filtered measures, LOD scopes, relationships and topic access filters. It issues separate aggregate queries for modified contexts, so a KPI can return posted revenue even when an ordinary draft selection has no facts. Native Omni behavior for that outer-empty case still needs qualification. The report companion's controls/presentation metadata are explicitly local, not a native Omni workbook export.

## Evidence and arithmetic

The frozen oracle was authored from the scenario, raw snapshot and CSV without inspecting source, target or runtime code. Source and target agents worked independently in parallel; oracle hashes were frozen before either implementation was compared with its results. No expected result was regenerated during repair.

The registered integrated denominator is 212 checks: 22 valid scenarios produce 132 source/target visual comparisons; 16 invalid contexts are denied by both paths; 29 additional negative controls exercise source, target and data failures. Three visuals cover revenue trend, segment share and ungrouped KPI totals. The final evidence retains full invoice rows, source projection, native identities, generated local SQL, raw-catalogue bindings, nine executed singular dbt assertions and documentation coverage.

Source physical dates are VARCHAR with explicit DATE adaptation; source model dateTime fields are restricted to ISO dates in this case. Raw integer values fit signed 64-bit source columns. Aggregate cents stay exact Python integers/Decimals; derived ratios use parsed expressions and 50-digit Decimal division with 1e-12 comparison tolerance. The SQL guard accepts SQLGlot's `TO_CHAR`/`TimeToStr` date normalization only for the reviewed ISO format. This is not a claim of universal Snowflake NUMBER(38,0), M numeric, DAX currency or timestamp equivalence.

The catalogue is a scoped synthetic Snowflake export: four objects and 23 columns, account/namespace-bound to the two actual M native queries. CSV adjustments are a proposed governed landing. No live Snowflake, Databricks or BigQuery metadata was retrieved. General provider guidance remains in [catalogue-providers.md](catalogue-providers.md).

## Delivered model and qualification gates

[Model documentation](../examples/powerbi-omni-e2e/documentation/README.md) supplies the ERD, dictionary, complete bronze/silver/gold guides, rule placements, source crosswalk and unresolved decisions for 10 models and 64 columns. The runner writes fresh evidence to its selected output directory. See [qualification and reproduction](../../../docs/qualification.md); [fixture pins](../examples/powerbi-omni-e2e/fixture-pins.json) protect reviewed execution inputs without claiming execution or approval.

Passing official JSON schemas establishes those file contracts only. Native Power BI Desktop/TOM/Analysis Services, M/DAX execution, service role memberships, refresh/folding, Snowflake execution, Omni LOD/filter/control behavior, performance, recovery and business approval remain separate gates. PBIX, TMDL, remote semantic models, DirectQuery/composite models, inactive/bidirectional/many-to-many relationships, bookmarks, visual interactions, time intelligence and paginated reports remain explicit unsupported or review paths. Do not extrapolate this fixture to complete Power BI migration support.
