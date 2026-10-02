# Retail fulfillment candidate

Five reusable dbt warehouse models preserve the two correct source staging files and remove fulfillment/return fanout. The fact keeps every current line, tenant and status; report filtering and the weighted fulfillment rate are a downstream dbt analysis and target-neutral Omni handoff.

This is one synthetic authoring trial. The corrected candidate passed 14 author tests and a complete native local dbt build of five models plus 52 data tests. A separate frozen oracle matched all eight positive contexts/mutations, and five negative contexts failed for their intended reasons. The packaged candidate was then built in a relocated directory and its native baseline matched the independent expected results. See [validation](evidence/native-dbt-validation.json), the [native evidence receipt](evidence/native-build/receipt.json), and the [complete qualification record](../../../../../validation/dbt-flow/README.md). Snowflake, native Omni behavior, business acceptance and production principal binding remain separate, unqualified gates.

An initial candidate incorrectly made the filtered report an enabled dbt view. Numeric checks passed but missed this architecture defect. The [first-pass record](evidence/architecture-finding.json) and archived snapshot preserve it; the final enabled model inventory excludes that report. This trial must not be described as clean on its first pass.

## Run locally

Install the pinned dbt qualification dependencies in a Python 3.12 environment.
From the repository root, run the packaged evaluator and native build in a fresh
output directory:

```sh
python skills/data-model-accelerator/scripts/run_dbt_holdout.py --output /absolute/new/retail-run
```

Python consumers can import `evaluate(raw_data, params)` from [evaluator.py](evaluator.py). It returns exactly `{"gold": [...], "report": [...]}` with uppercase contract fields, sorted natural identities, ISO dates, integer amounts and an unrounded numeric ratio. Invalid data or caller context raises before any output is accepted.

The replay copies this candidate to the output directory before running dbt. The
validator selects the dbt executable beside its Python interpreter, sets the
local database path through `DMA_RETAIL_DB_PATH`, and accepts an explicit
`--verifier` path when the copy is outside the skill. Temporary files and evidence
directories are created as needed. Historical records retain original author
paths; they are provenance, not installation instructions.

[model-map.json](model-map.json) lists the five enabled warehouse models. [semantic/report-map.json](semantic/report-map.json) identifies the analysis and nine report fields. Runtime database, logs, dbt cache/target and authoring scratch files are excluded from the solution inventory. The original native manifest/run-results archived as evidence are included because they prove the recorded execution denominator.

## Review

- [Assessment and first-pass correction](assessment.md), [placement decisions](decisions.json), [original source graph](source-graph.json), [target lineage](target-lineage.json).
- [ERD](documentation/model-erd.md), [canonical inventory](documentation/model-inventory.json), [readable dictionary](documentation/data-dictionary.md), [canonical dictionary](documentation/data-dictionary.json).
- [Bronze](documentation/bronze.md), [silver](documentation/silver.md), [gold](documentation/gold.md) and [operations](runbook.md).
- [Semantic contract](semantic/omni-handoff.json), [report fields and security](semantic/report-contract.md), [test plan](test-plan.json), [review manifest](review-package.json).

No packages or customer macros are executed by the bounded evaluator. Native dbt executes only the inspected candidate. The separate [Snowflake profile example](profiles/snowflake.yml.example) contains no credentials and was not used; source RAW remains DMA_RETAIL.RAW, while proposed target writes use an isolated database and schema prefix. No source or target account was contacted.
