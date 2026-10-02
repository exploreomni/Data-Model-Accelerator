# Retail dbt forward-test

This synthetic case starts with an existing dbt report that multiplies fulfillment
and return rows, plus two correct staging models and a four-table raw catalogue.
Its candidate preserves staging, creates a line-grain gold fact, and places report
context in a downstream analysis/Omni handoff.

Input and independent expected values were frozen before a separate agent
completed the candidate. Root review corrected an initial report-placement error;
relocation testing corrected machine-path and missing-directory assumptions.
The final replay passes 15/15 checks, including a native local dbt build of five
models and 52 data tests. It is now a regression fixture, not a new blind test
whenever it runs.

Use the [candidate and documentation](candidate/README.md) and the
[qualification record](../../../../validation/dbt-flow/README.md). The original
source and oracle files preserve their trial provenance, including historical
temporary paths. Execute the packaged runner from the repository root:

```sh
python skills/data-model-accelerator/scripts/run_dbt_holdout.py --output /absolute/new/retail-run
```

The runner uses only the pinned synthetic fixture and executes a relocated copy.
Expected outputs remain unchanged. No native Snowflake/Omni or human approval is
claimed. This input includes an explicit output/behavior contract and establishes
no general automatic compiler capability.
