# Power BI billing Snowflake candidate

Six full-table models transform four explicit RAW contracts into normalized current state and invoice/customer gold. [model-map.json](../model-map.json) contains exact dependency order, physical aliases and test phases. The proposed database is DMA_POWERBI; source account DMA_POWERBI_SYNTHETIC is synthetic.

`dbt_project.yml` targets the Snowflake adapter and the supplied example profile contains environment-variable placeholders only. The schema macro uses exact SILVER/GOLD only for the isolated fixture target/database; other targets retain default schema isolation. [dbt custom schema behavior](https://docs.getdbt.com/docs/build/custom-schemas).

Run the four source singular assertions before building, then the five relational assertions after their dependencies exist. Generic model/source tests are additional declarations. [dbt data test documentation](https://docs.getdbt.com/reference/resource-properties/data-tests). No native parse or execution claim is made by this artifact author; the separate orchestrator records evidence against the final artifact bytes.

Current-state normalization, M row net/month and DAX calculated-column outstanding are reusable warehouse logic. CALCULATE/REMOVEFILTERS/KEEPFILTERS measures, ratio totals and disconnected multiplier selection remain downstream. All statuses are retained in gold. Source dates remain VARCHAR at RAW and become DATE in silver; no source loader, incremental job, grants, enforced key constraints or approved production workflow is supplied.

For data grain, exact columns, refresh/recovery and unknown owners, use the [complete documentation](../../documentation/README.md).
