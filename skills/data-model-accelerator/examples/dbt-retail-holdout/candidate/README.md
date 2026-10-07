# Retail fulfillment candidate

Five reusable dbt warehouse models preserve the two correct source staging files and remove fulfillment/return fanout. The fact keeps every current line, tenant and status; report filtering and the weighted fulfillment rate are a downstream dbt analysis and target-neutral Omni handoff.

This candidate came from one synthetic authoring trial and is now a regression fixture. It includes 14 author tests and a native local dbt build of five models plus 52 data tests. The replay compares eight positive contexts/mutations and five negative contexts against separately frozen expectations, then checks relocated native output and report placement. Generate fresh results using the commands below; captured reports are retained in Git history rather than shipped here. See the [qualification guidance](../../../../../docs/qualification.md). Snowflake, native Omni behavior, business acceptance and production principal binding remain separate, unqualified gates.

An initial candidate incorrectly made the filtered report an enabled dbt view. Numeric checks passed but missed this architecture defect. That finding and its captured snapshot remain in Git history; the current enabled model inventory excludes the report. This trial must not be described as clean on its first pass.

## Run locally

Install the pinned dbt qualification dependencies in a Python 3.12 environment.
From the repository root, run the packaged evaluator and native build in a fresh
output directory:

```sh
python skills/data-model-accelerator/scripts/run_dbt_holdout.py --output /absolute/new/retail-run
```

Run the author tests through discovery so their direct-script output writer does
not add evidence files to the frozen source fixture:

```sh
python -m unittest discover -s skills/data-model-accelerator/examples/dbt-retail-holdout/candidate -p test_evaluator.py -v
```

Python consumers can import `evaluate(raw_data, params)` from [evaluator.py](evaluator.py). It returns exactly `{"gold": [...], "report": [...]}` with uppercase contract fields, sorted natural identities, ISO dates, integer amounts and an unrounded numeric ratio. Invalid data or caller context raises before any output is accepted.

The replay copies this candidate to the output directory before running dbt. The
validator selects the dbt executable beside its Python interpreter, sets the
local database path through `DMA_RETAIL_DB_PATH`, and accepts an explicit
`--verifier` path when the copy is outside the skill. Temporary files and evidence
directories are created as needed. Historical records retain original author
paths; they are provenance, not installation instructions.

[model-map.json](model-map.json) lists the five enabled warehouse models. [semantic/report-map.json](semantic/report-map.json) identifies the analysis and nine report fields. The [fixture inventory](../holdout-pins.json) binds the current package. Runtime database, logs, dbt cache/target, native manifests and receipts are created in the fresh output copy; they are not shipped as current execution evidence.

## Review

- [Assessment and first-pass correction](assessment.md), [placement decisions](decisions.json), [original source graph](source-graph.json), [target lineage](target-lineage.json).
- [ERD](documentation/model-erd.md), [canonical inventory](documentation/model-inventory.json), [readable dictionary](documentation/data-dictionary.md), [canonical dictionary](documentation/data-dictionary.json).
- [Bronze](documentation/bronze.md), [silver](documentation/silver.md), [gold](documentation/gold.md) and [operations](runbook.md).
- [Semantic contract](semantic/omni-handoff.json), [report fields and security](semantic/report-contract.md), [test plan](test-plan.json), [synthetic input catalogue](../input/catalogue/warehouse-catalogue.json).

No packages or customer macros are executed by the bounded evaluator. Native dbt executes only the inspected candidate. The separate [Snowflake profile example](profiles/snowflake.yml.example) contains no credentials and was not used; source RAW remains DMA_RETAIL.RAW, while proposed target writes use an isolated database and schema prefix. No source or target account was contacted.
