# Hex billing model review package

The candidate converts shared invoice, payment, adjustment and historical-customer logic into seven dbt/Snowflake models while retaining separate active-customer meanings. It includes **11 scoped physical models and 74 columns**, counting four reused/proposed raw contracts. All content is synthetic; no native runtime or business approval is implied.

- [Model inventory](model-inventory.json), [readable dictionary](data-dictionary.md), [canonical dictionary](data-dictionary.json) and [documentation index](documentation-index.json) establish the explicit coverage denominator.
- [ERD](model-erd.md) provides conceptual, logical and physical layer views.
- [Bronze](bronze.md), [silver](silver.md) and [gold](gold.md) document grain, lineage, transforms, dependency order, refresh/history, governance, recovery and unknown owners.
- [Semantic mapping](semantic-mapping.md) links original source project/cell IDs to Omni fields and distinguishes report context from reusable facts.
- [Placement/conflict register](placement-and-conflicts.json) records retained exploration, governed CSV landing, the unresolved active-customer choice, cohort-proxy limits and operational gaps.
- [Target model map](../target/model-map.json), [dbt project](../target/dbt/README.md), [raw contracts](../target/snowflake/00_raw_contract.sql) and [Omni report companion](../target/omni/report-context.json) make the proposal reviewable.

The dictionary inventory is parsed from candidate raw DDL and final model projections, with every column linked to source/code and rule context. Coverage alignment does not prove the formulas are right. Independent row-level, dimensional, replay, security and mutation checks supply additional local evidence. The independent expected-output author did not supply these target definitions.

Decisions still requiring human approval include any canonical `active_customers` meaning, source-file governance, production loading/refresh/history behavior, within-month customer-segment allocation, access provisioning and ownership. Native Hex component execution, dbt/Snowflake compile/run, Omni validation and target persona enforcement are separate gates. Keep source and prior consumer artifacts until the exact candidate, results and unresolved decisions are reviewed.
