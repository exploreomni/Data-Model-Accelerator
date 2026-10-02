# Silver: reusable current-state normalization

Coverage: `DMA_RETAIL.SILVER.STG_ORDERS`, `DMA_RETAIL.SILVER.STG_ORDER_LINES`, `DMA_RETAIL.SILVER.STG_FULFILLMENTS`, `DMA_RETAIL.SILVER.STG_RETURNS` — four views, 25 columns. These are the exact local identities; the unexecuted Snowflake profile uses an isolated target database and schema prefix. Full [column mappings](data-dictionary.md), [code](../model-map.json) and [lineage](../target-lineage.json) share the same inventory.

| View | Grain | Transformation and reason upstream |
|---|---|---|
| STG_ORDERS | One current nondeleted TENANT_ID, ORDER_ID | Reuse original SQL unchanged. Rank entity-local sequence, exclude winning tombstone, cast ORDER_DATE, rename STATUS to ORDER_STATUS and retain tenant-aware ORDER_KEY. Every consumer needs the same current header. |
| STG_ORDER_LINES | One current nondeleted TENANT_ID, ORDER_ID, LINE_ID | Reuse original SQL unchanged. Retain product, quantity, price, total discount and LINE_KEY; compute LINE_NET_CENTS = QUANTITY × UNIT_PRICE_CENTS − DISCOUNT_CENTS once. |
| STG_FULFILLMENTS | One current nondeleted TENANT_ID, FULFILLMENT_ID | Newly factor event normalization out of report logic. Preserve order/line identity and quantity. Do not aggregate yet: event grain remains available. |
| STG_RETURNS | One current nondeleted TENANT_ID, RETURN_ID | Newly factor event normalization out of report logic. Preserve order/line identity, quantity and refund. Refund quantity and money are distinct facts. |

## Ambiguity, deletes and conformance

The complete raw capture is validated before any model output is accepted. Exact duplicate payloads at the same key/sequence are idempotent. The ranking can choose any identical duplicate without changing projected values. A differing tie is rejected, including superseded ties; there is no arbitrary tie-breaker that silently decides business truth. Select highest sequence before applying IS_DELETED, so deleted lines/events cannot resurrect from an earlier version.

Current lines require a current order in their own tenant; current fulfillment and return events require a current line using TENANT_ID, ORDER_ID and LINE_ID. Events whose winning version points to a missing or deleted line reject the capture. No Unknown parent row or orphan-dropping inner join is used. `current_references.sql` tests these logical relationships. Composite keys are tenant scoped; pipe-encoded order/line keys are safe only under the explicitly checked alphanumeric fixture identity domain.

These views preserve current values across every tenant, order status, product and order date. No report filter is introduced. Source ISO calendar dates become DATE only on orders; all amounts are integer USD cents. Valid inputs are logically nonnull. There are no fabricated defaults on missing required inputs, imputed quantities, or additional currency/timezone rules. Null enforcement is via prevalidation and tests, not declared physical constraints.

## History, quality and operations

This is current-state reconstruction from a complete version capture, not SCD2. A later valid header/line correction restates its historical order date, status, product or price; there are no effective-from/effective-to predicates or as-of attribute joins. Late versions are resolved by entity sequence, not arrival time. Both exact replay and tombstone behavior are covered by author mutation fixtures.

Materialization is view to preserve the source project's staging approach and keep normalization reusable; the gold table is rebuilt after raw replacement. Rank/dedup costs scale with the full retained capture. No incremental merge, clustering, partition pruning, schedule or production performance result is claimed. For production, review capture volume and concurrency before selecting materialization or incremental strategy.

Run raw gates before model acceptance; native dbt's dependency graph builds current views before the fact. Model not-null/unique assertions, current-reference checks and line fact coverage supplement source checks. The [test plan](../test-plan.json) connects each behavior to evidence. A dbt failure may leave already built relations and is not an atomic rollback: withhold publishing and rerun from the accepted complete capture after repair. Business/data engineering owner, freshness SLA, access grants, retention and on-call ownership remain unknown; shared recovery and qualification steps are in the [runbook](../runbook.md).
