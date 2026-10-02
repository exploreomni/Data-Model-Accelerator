# Synthetic Hex billing dbt candidate

This project proposes seven Snowflake table models over four explicitly inventoried raw contracts. It contains native dbt project/model/source/test syntax; it has not been compiled or run by native dbt or Snowflake. The local harness renders a bounded subset of `config`, `ref` and `source` and executes translated SQL in memory. That evidence does not validate the adapter, macros, generated grants or production deployment.

The [model map](../model-map.json) defines every logical name, physical relation, column and run dependency. `DMA_HEX.RAW` supplies bronze responsibilities; a second bronze copy is unnecessary. `RAW.ADJUSTMENTS` is a proposed governed landing of the separately inventoried [CSV](../../input/repo/adjustments.csv), not an assumed native warehouse source or an automatic filesystem read.

## Native setup to validate separately

1. Select and pin compatible dbt Core and Snowflake adapter versions. This candidate uses `data_tests` with nested `arguments`, documented for dbt 1.10.5 and later; the project limits Core to `<2.0.0`. No package installation or native version acceptance is asserted.
2. Review an isolated Snowflake destination and identity. Configure credentials outside this package using [profiles.yml.example](profiles.yml.example). The synthetic source binding is account `DMA_HEX_SYNTHETIC`, database `DMA_HEX`, connection ID `11111111-1111-4111-8111-111111111111`; the example has no credential values.
3. Land and reconcile the four raw contracts before transformation. Validate source file receipts, exact columns/types, CDC ties, null/delimiter keys, adjustments uniqueness and effective-history nonoverlap. Missing CSV content is an error; missing adjustment rows for otherwise valid invoices mean zero.
4. Parse/compile with native dbt and inspect the complete generated manifest and Snowflake SQL. Run the four source-only singular tests listed in [model-map.json](../model-map.json) before building silver. Build silver and the dimension; require orphan/history checks before exposing invoice facts. Build gold; run all generic and singular tests plus independently specified report comparisons.
5. Obtain business, operational and access approval before any consumer cutover. Keep prior models/reports available for rollback. No deployment, source replacement or decommissioning is authorized by this fixture.

## Namespace behavior

dbt normally appends a custom model schema to the target schema. The included [schema macro](macros/generate_schema_name.sql) emits literal `SILVER`/`GOLD` only when the target is named `fixture` and its database is exactly `DMA_HEX`; other targets retain dbt's default namespace isolation. Do not reuse the shared fixture destination for multiple developers. Rebind the semantic model and catalogue when using a distinct destination. This macro has not been natively executed. [dbt custom-schema documentation](https://docs.getdbt.com/docs/build/custom-schemas)

## Assertions and evidence

The [test SQL](tests) includes invalid source identities, conflicting CDC versions, overlapping history, duplicate adjustments, orphan references, grain, effective customer binding, signed balance formulas and payment reconciliation. [Model properties](models/models.yml) and [source properties](models/sources.yml) also declare null, unique, accepted-value and relationship tests. Tests report violations; they do not create enforced constraints or implement a quarantine service. Independent source-versus-target slices and deliberate mutations remain the stronger check against a self-consistent wrong formula. [dbt data-test documentation](https://docs.getdbt.com/reference/resource-properties/data-tests)

Read the [bronze](../../documentation/bronze.md), [silver](../../documentation/silver.md), [gold](../../documentation/gold.md), [semantic mapping](../../documentation/semantic-mapping.md), [dictionary](../../documentation/data-dictionary.md) and [ERD](../../documentation/model-erd.md) together. Fixed SQL/model artifacts replay the authored candidate; they do not constitute a general Hex transpiler or a new autonomous migration on every run.
