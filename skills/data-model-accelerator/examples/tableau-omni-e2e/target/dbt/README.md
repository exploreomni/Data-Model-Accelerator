# Synthetic Tableau billing dbt candidate

This project contains six Snowflake table models over four explicit RAW contracts. It reuses validated current-state transformation patterns but preserves this Tableau fixture's namespace, source provenance and worksheet context. There is no customer-month or all-time customer-revenue model. [model-map.json](../model-map.json) records the exact inventory and dependency order.

The local harness renders a bounded subset of dbt config/ref/source and executes translated SQL. This is not native dbt compilation or Snowflake execution. The orchestrator records any native dbt parse separately; parsing does not validate credentials, generated warehouse statements, permissions or model results.

## Intended execution to qualify separately

1. Inventory and reconcile the raw source and adjustment receipt in `DMA_TABLEAU.RAW`. Raw invoice/history dates remain VARCHAR; silver casts them explicitly. The local adapter's DATE loading is separate from the native type contract.
2. Pin compatible dbt Core/Snowflake adapter versions and configure an isolated target using [profiles.yml.example](profiles.yml.example). No credentials or live connector are supplied. This candidate uses nested data-test arguments documented for Core 1.10.5 and later and limits Core to `<2.0.0`.
3. Parse/compile natively and review the generated manifest and SQL. Run source identity/value, version-conflict, history-overlap and adjustment uniqueness tests before model promotion. Build silver and the dimension; require current-reference and exactly-one temporal-history checks; then build the invoice fact and run all generic/singular assertions.
4. Compare source and target invoice keys and each worksheet over independent context/segment/tenant/multiplier cases. Test deliberate defects, including wrong FIXED filter order and wrong share partition; totals alone are insufficient.
5. Obtain human definition/operating/access approval before a separately authorized deployment or consumer cutover. Retain source artifacts and prior accepted results for rollback.

dbt normally combines target schema and custom schema. The included [schema macro](macros/generate_schema_name.sql) emits literal SILVER/GOLD only for target `fixture` in database `DMA_TABLEAU`; all other targets retain default schema isolation. Do not share this exact fixture namespace among developers. The macro's native behavior must be verified before use. [Official dbt custom schemas](https://docs.getdbt.com/docs/build/custom-schemas)

The [nine singular SQL tests](tests), [source YAML](models/sources.yml) and [model YAML](models/models.yml) assert input consistency, grain, temporal/tenant binding and signed financial reconciliation. They do not enforce database constraints or implement quarantine. [Official dbt data tests](https://docs.getdbt.com/reference/resource-properties/data-tests)

See the complete [bronze](../../documentation/bronze.md), [silver](../../documentation/silver.md), [gold](../../documentation/gold.md), [dictionary](../../documentation/data-dictionary.md), [ERD](../../documentation/model-erd.md) and [semantic/presentation mapping](../../documentation/semantic-mapping.md). Production ingestion, schedule, freshness SLA, owners, permissions, retention and recovery automation remain unspecified.
