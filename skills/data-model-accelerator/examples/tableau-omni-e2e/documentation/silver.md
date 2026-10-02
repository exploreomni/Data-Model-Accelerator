# Silver current state and effective history

Four table models normalize facts shared by all three worksheets. Their [SQL](../target/dbt/models/silver) contains source rules, not runtime Tableau filters or presentation calculations. Complete column lineage is in the [dictionary](data-dictionary.md).

| Physical model | Grain and source | Reusable transformation |
|---|---|---|
| `DMA_TABLEAU.SILVER.BILLING_INVOICES` | One current tenant/invoice from `RAW.INVOICE_CDC` | Highest SEQUENCE before tombstone filtering; strict date and integer casts; lower/trim status; retain selected SOURCE_SEQUENCE and all current statuses. |
| `DMA_TABLEAU.SILVER.BILLING_PAYMENTS` | One current tenant/payment from `RAW.PAYMENT_CDC` | Highest SEQUENCE before tombstone filtering; strict paid-cents cast; preserve tenant/invoice reference and selected SOURCE_SEQUENCE. |
| `DMA_TABLEAU.SILVER.BILLING_CUSTOMER_HISTORY` | One distinct effective tenant/customer/valid-from row from `RAW.CUSTOMER_HISTORY` | Whole-record DISTINCT collapses exact replay, then date casts; retain historical segment and exclusive/open end. |
| `DMA_TABLEAU.SILVER.BILLING_ADJUSTMENTS` | One correction per tenant/invoice from `RAW.ADJUSTMENTS` | Strict signed-cents cast and retained reason; no summing or deduplication of duplicate adjustment keys. |

## Rules, keys and failure behavior

Conflicting same-sequence payloads must fail before ROW_NUMBER selects a current version; an arbitrary winner is not conflict resolution. Exact identical CDC payloads are safe ties. Removing tombstones before selecting the latest version would resurrect deleted entities and must be detected. Invalid casts must fail rather than becoming silent null/default values. No TRY_CAST or quarantine service is provided.

Tenant belongs to every business identity, payment/adjustment association and history join. Current payments and adjustments require a current invoice in that tenant. Customer validity intervals are date-based `[VALID_FROM, VALID_TO)`; a null end is open-ended. An invoice on February 1 belongs to a new interval beginning that day. Exact complete history replays collapse, while distinct overlapping records fail. Missing history is a contract error, not an Unknown-member proposal or an inner-join deletion.

These rules move upstream because every consumer needs one consistent current-state interpretation. Posted status, selected tenant, date context, ordinary segment filter, FIXED aggregation, share partition and multiplier remain downstream. Silver does not select tenant A or a report window.

## Dependency order and assertions

Run source identity/value, version-conflict, history-overlap and adjustment-uniqueness assertions before silver. Build four silver models and the customer dimension; require current-reference and exactly-one temporal-history checks before gold exposure. The [nine singular data tests](../target/dbt/tests) and column tests in [model/source YAML](../target/dbt/models/models.yml) are executable assertions, not enforced DDL constraints or proof of native execution.

## Operations, ownership and recovery

All six transformed models use full table rebuilds; no incremental merge or ingestion schedule is implemented. Later source sequences can revise prior invoice dates and values. Exact CDC/history replay and source-order shuffling must preserve valid current results. Adjustments are a separately governed snapshot with a stricter duplicate-key rule.

Monitor current grains, null keys, cast failures, orphan references, effective-history coverage and version conflicts. Production run timing, freshness SLA, alert destination, access/masking, retention and ownership are unknown. No grants, row policies or real customer classifications are supplied.

Retain the prior accepted outputs while rebuilding from an unchanged validated snapshot or an explicitly versioned correction. Reconcile key sets and payment/adjustment components before releasing reports. No destructive source cleanup, production cutover or automated recovery is authorized. Operational owner and business approver remain **unknown**.
