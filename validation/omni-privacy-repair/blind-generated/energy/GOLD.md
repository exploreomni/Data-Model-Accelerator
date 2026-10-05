# Energy gold layer
Synthetic proposed specification; no native observations or authenticated approval.

Publish reusable row-grain facts. Left join the unique meter lookup to reading facts. Keep all dates and zones. Sum kWh at query time; do not materialize the dashboard date or north selection into the model.

## gold_readings
Planned relation: `synthetic-review.dma_energy.gold_readings`. Grain: One row per reading_id. Columns: reading_id, meter_id, recorded_on, kwh, zone.
See DICTIONARY.md for every column and transformation, ERD.svg/ERD.mmd for connected lineage, implementation/dbt for exact projections, and local-results.json for executed local observations.

Materialization: views, full current-snapshot read behavior. Run bronze before silver before gold through dbt dependencies. Refresh and late arrivals follow source requery, with no recoverable source history assumed. Owner, SLA, retention, currency and native access are unresolved. Source correction/replay semantics need operator evidence. Monitor key, null, cast and orphan failures before publication; native fresh-watermark and access checks remain pending. Recovery: retain original source and model hashes, inspect consumer impact, then revert only separately approved candidate views. No production write, rollback command or source retirement is authorized.

Definitions remain proposed. NULL/empty-set aggregation behavior follows ordinary SUM (NULL for empty sets); do not replace missing labor/usage values with zero without review. See DASHBOARD.md for exact source population, dates, sorts, limits and interactive controls.
