# Power BI billing migration review package

This synthetic candidate contains six dbt/Snowflake models over four raw contracts: **10 physical models and 64 columns**. It preserves three selected reports through native Omni candidate definitions and an explicitly nonnative local companion. No customer export, deployed model, native visual parity or business approval is claimed.

- [Inventory](model-inventory.json), [canonical dictionary](data-dictionary.json), [readable dictionary](data-dictionary.md) and [documentation index](documentation-index.json) define complete scoped coverage.
- [ERD](model-erd.md), [bronze](bronze.md), [silver](silver.md) and [gold](gold.md) describe grain, history, tenant identity, lineage, refresh and operations.
- [Source crosswalk](source-to-target.json), [placement register](placement-and-decisions.json) and [semantic mapping](semantic-mapping.md) retain source M/DAX and report context.
- [Target map](../target/model-map.json), [dbt project](../target/dbt/README.md) and [report companion](../target/omni/report-context.json) make the candidate executable by the separate bounded test harness.

The key behaviors are measure-specific context and BLANK: all-segment revenue removes only segment; posted revenue replaces status while posted intersection preserves the conflicting status restriction; KPI totals recompute rather than sum displayed subtotals. The disconnected multiplier remains exploratory. These are preserved source definitions, not a claim that a business owner has approved their authority.

Independent comparisons must bind source native identifiers, account/schema/columns and both tenant roles. Local SQL execution and static schema checks do not establish Power BI Desktop/Analysis Services, Snowflake or Omni acceptance. Native import refresh/folding, service role membership, DirectQuery/composite behavior, TMDL/PBIX extraction, visuals and production operations remain outside this bounded replay.
