# Maintenance bronze layer
Synthetic proposed specification; no native observations or authenticated approval.

Retain all supplied CSV fields and rows as lexical text. Original landing/replication behavior, null encoding, deletes, CDC ordering, freshness and schema drift are unknown; no ingestion changes are proposed.

## bronze_work_orders
Planned relation: `SYNTHETIC_REVIEW.DMA_MAINTENANCE.BRONZE_WORK_ORDERS`. Grain: One row per work_order_id in the supplied snapshot; no historical uniqueness asserted. Columns: work_order_id, tenant_id, opened_on, labor_cost, status.
See DICTIONARY.md for every column and transformation, ERD.svg/ERD.mmd for connected lineage, implementation/dbt for exact projections, and local-results.json for executed local observations.

## bronze_parts
Planned relation: `SYNTHETIC_REVIEW.DMA_MAINTENANCE.BRONZE_PARTS`. Grain: One row per part_line_id in the supplied snapshot; no historical uniqueness asserted. Columns: part_line_id, work_order_id, quantity, unit_cost.
See DICTIONARY.md for every column and transformation, ERD.svg/ERD.mmd for connected lineage, implementation/dbt for exact projections, and local-results.json for executed local observations.

Materialization: views, full current-snapshot read behavior. Run bronze before silver before gold through dbt dependencies. Refresh and late arrivals follow source requery, with no recoverable source history assumed. Owner, SLA, retention, currency and native access are unresolved. Source correction/replay semantics need operator evidence. Monitor key, null, cast and orphan failures before publication; native fresh-watermark and access checks remain pending. Recovery: retain original source and model hashes, inspect consumer impact, then revert only separately approved candidate views. No production write, rollback command or source retirement is authorized.

Definitions remain proposed. NULL/empty-set aggregation behavior follows ordinary SUM (NULL for empty sets); do not replace missing labor/usage values with zero without review. See DASHBOARD.md for exact source population, dates, sorts, limits and interactive controls.
