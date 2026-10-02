# Tableau to medallion to Omni qualification exercise

This authored, customer-free workbook deliberately reuses the Hex pilot's billing inputs to isolate Tableau behavior. It is a reproducible local replay of supplied source and candidate artifacts, not fresh automatic model generation, native migration execution or production approval.

## Run

Use Python 3.12 with the pinned optional dependencies. From the repository root:

```sh
python3.12 -m venv /tmp/dma-tableau-env
/tmp/dma-tableau-env/bin/python -m pip install -r skills/data-model-accelerator/scripts/requirements-tableau-e2e.txt
/tmp/dma-tableau-env/bin/python -m unittest discover -s tests -v
/tmp/dma-tableau-env/bin/python skills/data-model-accelerator/scripts/run_tableau_omni_e2e.py --output /absolute/new-tableau-run
```

Output must be a new directory outside the example. The runner records failed checks and a final failure report; a prior output is never overwritten. Do not change frozen expected results to make a candidate pass.

## What executes

The [source reader](tableau-source-contract.md) parses actual XML definitions, source IDs, connections, calculated fields, parameters, filters and worksheet marks. A separately scoped TWBX check verifies every packaged member against its plain-file authority without extracting it. A published-data-source mirror is not inferred from a name; this fixture's TDS is an explicit identical definition mirror.

The bounded source interpreter executes the custom SQL through a restricted DuckDB adapter and evaluates supported Tableau expressions through a positive grammar. It never invokes Python eval/exec, source macros, discovered URLs or native Tableau. Shared raw/SQL validation helpers retain the established billing checks. Raw VARCHAR dates use a documented DATE adaptation; native NUMBER(38,0) is bounded to signed-64-bit input values locally. Exact integer/Decimal arithmetic preserves cents; derived Omni ratios use parsed native measure references with Decimal adaptation, while unsupported float magnitudes fail explicitly if they cannot honor the declared absolute tolerance.

The source applies datasource population, worksheet date context, FIXED grouping, ordinary segment filtering, view aggregation and table calculations in order. The target executes six authored dbt SQL models locally, then renders selected native Omni fields and selective LOD filter cancellation independently. A declared presentation companion preserves what-if multiplication and month-partitioned shares. That JSON companion is not a native Omni workbook file; its proposed native spreadsheet expressions still require authoring and live validation.

## Evidence and independent expectations

The [case](../examples/tableau-omni-e2e/input/scenario.md) freezes raw input semantics and reports. A separate oracle was authored and frozen before inspecting target/execution code. Its 16 scenarios cover both tenants, temporal segment changes, date boundaries, zero denominators, empty windows, ordinary segment filters and what-if changes. Eight invalid contexts are denied on both sides. The [test plan](../examples/tableau-omni-e2e/test-plan.json) declares 160 required checks and 29 field identities before the integrated run; 44 checks inject defects or invalid contexts. Full invoice rows and source/target dimensional slices are compared; matching grand totals alone cannot pass.

The catalogue checks four objects and 23 columns against pinned synthetic metadata exports, source SQL identities and candidate raw DDL. ADJUSTMENTS remains a proposed governed CSV landing. This is not a discovered warehouse account inventory or proof of physical access enforcement.

The model delivery includes six dbt models, four raw contracts, nine executable local SQL assertions, an ERD and complete dictionary/layer documentation for 10 models / 64 columns. Native dbt parsing can be captured separately with an isolated dummy profile; parsing establishes syntax/dependencies only, not warehouse compilation or execution.

## Native qualification still required

The pinned official Tableau XSD could not compile because its publisher-supplied file references missing namespace definitions. The reader records the actual failed compilation and leaves official schema validation unavailable; successful XML extraction does not clear it. Tableau Desktop/Server opening, Hyper extracts, relationships/blending, INCLUDE/EXCLUDE LOD, densification, dashboard actions, row policies and native visual behavior remain outside this pilot.

Before release, obtain actual Tableau output and metadata at aligned watermarks, resolve all extraction gaps, validate dbt in the chosen warehouse, validate Omni LOD/pivot/filter/access behavior, profile incremental ingestion and recovery, and obtain business and operating approval. The manifest retains these blockers. See the repository's `validation/tableau-omni-e2e` evidence for the captured run, QA improvements and native parse receipt.

Sources checked September 10, 2026: [Tableau filter/LOD order](https://help.tableau.com/current/pro/desktop/en-us/calculations_calculatedfields_lod_filters.htm), [Tableau official document schemas](https://github.com/tableau/tableau-document-schemas), [Omni selective LOD filters](https://docs.omni.co/modeling/dimensions/parameters/level-of-detail), [Omni calculations and row totals](https://docs.omni.co/analyze-explore/calculations).
