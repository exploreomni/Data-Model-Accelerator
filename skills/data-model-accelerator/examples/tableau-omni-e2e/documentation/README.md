# Tableau billing migration review package

The candidate preserves the three selected Tableau worksheets with six reusable dbt/Snowflake models, a native Omni model, and an explicit local presentation contract. It covers **10 physical models and 64 columns**, including four raw contracts. All data and source assets are authored synthetic fixtures; no native Tableau opening, Omni model acceptance, production deployment or business approval is implied.

- [Inventory](model-inventory.json), [canonical dictionary](data-dictionary.json), [readable dictionary](data-dictionary.md) and [documentation index](documentation-index.json) establish complete declared coverage.
- [ERD](model-erd.md), [bronze](bronze.md), [silver](silver.md) and [gold](gold.md) document physical responsibilities, grain, keys, lineage, refresh, governance and recovery.
- [Source crosswalk](source-to-target.json), [placement register](placement-and-decisions.json) and [semantic/presentation contract](semantic-mapping.md) preserve original names and order of operations.
- [Target map](../target/model-map.json), [dbt project](../target/dbt/README.md) and [report companion](../target/omni/report-context.json) make implementation and output selection reviewable.

The crucial distinction is context: the customer FIXED calculation preserves tenant, posted status and date-window context but ignores only the ordinary segment filter. Customer values may repeat across marks and are summarized by MIN within a mark. Revenue share is calculated over filtered marks, partitioned by month and addressed by segment. Neither calculation becomes an all-time warehouse column.

Independent local comparisons and negative controls must prove source interpretation and target behavior separately. Inventory/dictionary agreement alone cannot establish semantic correctness. Native Tableau rendering/actions/densification, Snowflake execution, Omni LOD behavior and production persona permissions remain separate gates. Any native dbt parse evidence is recorded by the orchestrator and does not establish warehouse execution.
