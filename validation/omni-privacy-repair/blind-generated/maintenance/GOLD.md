# Maintenance gold layer
Synthetic proposed specification; no native observations or authenticated approval.

Publish reusable row-grain facts. Aggregate parts by work_order_id before the left join; absence of parts yields zero, and labor remains once per work order. Keep status, opened_on and tenant_id for query-time filters.

## gold_work_orders
Planned relation: `SYNTHETIC_REVIEW.DMA_MAINTENANCE.GOLD_WORK_ORDERS`. Grain: One row per work_order_id. Columns: work_order_id, tenant_id, opened_on, labor_cost, status, parts_cost, work_cost.
See DICTIONARY.md for every column and transformation, ERD.svg/ERD.mmd for connected lineage, implementation/dbt for exact projections, and local-results.json for executed local observations.

Materialization: views, full current-snapshot read behavior. Run bronze before silver before gold through dbt dependencies. Refresh and late arrivals follow source requery, with no recoverable source history assumed. Owner, SLA, retention, currency and native access are unresolved. Source correction/replay semantics need operator evidence. Monitor key, null, cast and orphan failures before publication; native fresh-watermark and access checks remain pending. Recovery: retain original source and model hashes, inspect consumer impact, then revert only separately approved candidate views. No production write, rollback command or source retirement is authorized.

Definitions remain proposed. NULL/empty-set aggregation behavior follows ordinary SUM (NULL for empty sets); do not replace missing labor/usage values with zero without review. See DASHBOARD.md for exact source population, dates, sorts, limits and interactive controls.
