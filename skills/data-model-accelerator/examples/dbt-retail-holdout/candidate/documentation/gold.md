# Gold: reusable order-line fulfillment fact

Coverage: `DMA_RETAIL.GOLD.FCT_ORDER_LINE_FULFILLMENT` — one rebuilt table, 13 columns, one row per current nondeleted `(TENANT_ID, ORDER_ID, LINE_ID)`. The [SQL](../dbt/models/gold/fct_order_line_fulfillment.sql), [dictionary](data-dictionary.md) and [ERD](model-erd.md) describe the same fact. No downstream report is an enabled warehouse model.

## Grain and money

Start from current lines and preserve LINE_KEY, tenant/order/line/product, quantity and already discounted LINE_NET_CENTS. The current order supplies date and status through tenant/order equality. Logical orphan checks require the order to exist; the SQL uses a left join so a bad parent is not silently erased. There is no customer/product dimension or bridge because those records were not supplied.

Aggregate current fulfillment events independently by tenant/order/line to one row containing SUM(QUANTITY). Aggregate current return events independently to one row containing SUM(QUANTITY) and SUM(REFUND_CENTS). Join each reduced result to the line using all three identity fields. Each optional child aggregate has zero or one matching row. Missing child aggregates become zero, while parent line measures remain unchanged. Joining the two raw event collections directly would multiply both sides; the fact deliberately prevents that known source defect.

`RETAINED_REVENUE_CENTS = LINE_NET_CENTS − REFUND_CENTS`. Discounts are total line discounts and are already applied once in reusable staging. Valid refunds may exceed line net: negative retained revenue is retained. Fulfilled quantity must not exceed ordered; returned must not exceed fulfilled. Quantity and money are additive across lines in this USD-only fixture. No currency field, conversion, rounded display dollars or timezone assumption is invented.

## Downstream contract

The warehouse fact contains all current tenants, statuses, dates and products. Month grouping, report defaults, access context and ratio are retained downstream in [the dbt analysis](../dbt/analyses/retail_fulfillment_summary.sql) and [semantic handoff](../semantic/omni-handoff.json). The analysis is compiled and queried for acceptance comparison, without creating a report relation. Its nine fields have a separate [semantic dictionary](../semantic/report-contract.md); including them as physical warehouse columns would misstate placement.

Order month is the first day of ORDER_DATE's calendar month. Each requested report quantity/amount is SUM of the corresponding fact field. FULFILLMENT_RATE is SUM(FULFILLED_QUANTITY)/NULLIF(SUM(ORDERED_QUANTITY),0), including totals; it is never a sum/average of displayed rates. An empty selected population returns no grouped rows. A zero denominator yields NULL. The local guard validates tenant A/B and a supplied persona, authorization, allowed status, optional product and half-open dates. None of this establishes warehouse RLS or native Omni access enforcement.

## History and reconciliation

Current header and line corrections restate existing fact rows. Full rebuilds include late event corrections and remove winning tombstones after validating remaining references. No SCD attributes, as-of joins, Unknown members or incremental merge are specified. LINE_KEY is a tested logical identity, not an enforced database primary key.

The final native local full build has five models plus 52 data tests; actual built columns match the nine-object/68-column warehouse inventory. Author tests cover a hand-derived multi-fulfillment/multi-return case, discount-once arithmetic, weighted ratios, tenant collisions, optional children, replay, correction, deletion and invalid references. Negative controls remove a tenant join or double the discount and demonstrate detection. Native versus template execution matches on the frozen baseline, but both execute candidate definitions; independent hidden acceptance is not claimed here.

The first candidate materialized report context and was corrected after parent architecture review; see [assessment](../assessment.md). Numeric passes did not establish correct placement. No production owner approved either schema or metric. A deployment proposal still needs named business/operational ownership, Snowflake execution/performance, native Omni query/total/security validation and acceptance of exact bytes.

## Operations

After the four silver views, build the fact as a complete table, run the full assertions, then reconcile and expose only accepted output. Full-table cost is acceptable for this 32-row synthetic capture, not an estimate for production. No job cadence, freshness or recovery SLA, grants, retention, monitoring owner or cost budget was supplied. Alerting should include input conflict/null/schema failures, orphan and quantity failures, test/skipped-node outcomes and input capture identity; operator delivery is unimplemented. Failed dbt builds can leave partial relations; [runbook](../runbook.md) requires publication gating and reconstruction from an accepted capture rather than claiming atomic rollback.
