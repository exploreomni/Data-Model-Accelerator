# Retail model ERD

The physical warehouse denominator is nine objects and 68 columns: four reused raw contracts, four current silver views and one gold fact. The report is downstream and has no warehouse relation. All names below use local validation identities; the Snowflake profile example intentionally changes the target database/schema prefix. [Inventory](model-inventory.json) and [dictionary](data-dictionary.md) enumerate all columns.

## Logical relationships after validation

```mermaid
erDiagram
  CURRENT_ORDER ||--o{ CURRENT_LINE : "same tenant and order"
  CURRENT_LINE ||--o{ CURRENT_FULFILLMENT : "same tenant, order and line"
  CURRENT_LINE ||--o{ CURRENT_RETURN : "same tenant, order and line"
  CURRENT_LINE ||--|| LINE_FACT : "one accepted fact per current line"
  CURRENT_ORDER {
    string TENANT_ID PK
    string ORDER_ID PK
    date ORDER_DATE
    string ORDER_STATUS
  }
  CURRENT_LINE {
    string TENANT_ID PK
    string ORDER_ID PK
    string LINE_ID PK
    string PRODUCT_ID
    decimal LINE_NET_CENTS
  }
  CURRENT_FULFILLMENT {
    string TENANT_ID PK
    string FULFILLMENT_ID PK
    string ORDER_ID FK
    string LINE_ID FK
    decimal QUANTITY
  }
  CURRENT_RETURN {
    string TENANT_ID PK
    string RETURN_ID PK
    string ORDER_ID FK
    string LINE_ID FK
    decimal QUANTITY
    decimal REFUND_CENTS
  }
  LINE_FACT {
    string LINE_KEY PK
    string TENANT_ID
    string ORDER_ID
    string LINE_ID
    decimal ORDERED_QUANTITY
    decimal FULFILLED_QUANTITY
    decimal RETURNED_QUANTITY
    decimal LINE_NET_CENTS
    decimal REFUND_CENTS
    decimal RETAINED_REVENUE_CENTS
  }
```

PK/FK marks denote tested logical key membership, not emitted or enforced database constraints. An order may have no current lines; a current line requires exactly one current order. A line may have zero/many fulfillment and return events; every current event requires one current line. Events are independently identified by tenant/event ID, not by line identity. The full composite reference is tenant/order/line even when an ERD column marker abbreviates it. None of these relationships is inferred from an ingestion arrow.

## Bronze to silver physical transformations

```mermaid
flowchart LR
  BO["DMA_RETAIL.RAW.ORDER_CDC
tenant/order/sequence occurrence"] --> SO["DMA_RETAIL.SILVER.STG_ORDERS
tenant/order current view"]
  BL["DMA_RETAIL.RAW.ORDER_LINE_CDC
tenant/order/line/sequence occurrence"] --> SL["DMA_RETAIL.SILVER.STG_ORDER_LINES
tenant/order/line current view"]
  BF["DMA_RETAIL.RAW.FULFILLMENT_CDC
tenant/fulfillment/sequence occurrence"] --> SF["DMA_RETAIL.SILVER.STG_FULFILLMENTS
tenant/fulfillment current view"]
  BR["DMA_RETAIL.RAW.RETURN_CDC
tenant/return/sequence occurrence"] --> SR["DMA_RETAIL.SILVER.STG_RETURNS
tenant/return current view"]
```

These arrows are source-to-target transformations. Complete captures permit identical repeated occurrences; ambiguous payload ties reject before latest-record normalization. Each view ranks SEQUENCE within its entity key and excludes the winning tombstone afterward. Current-only history has no effective time bounds; date cast and renamed status come from the current order, while discount arithmetic is preserved in current line staging.

## Gold and downstream query

```mermaid
flowchart LR
  O["STG_ORDERS"] -->|"tenant/order; required parent"| G["DMA_RETAIL.GOLD.FCT_ORDER_LINE_FULFILLMENT
one current tenant/order/line; table"]
  L["STG_ORDER_LINES"] -->|"base grain"| G
  F["STG_FULFILLMENTS"] --> FA["SUM quantity by tenant/order/line
query CTE only"]
  R["STG_RETURNS"] --> RA["SUM quantity/refund by tenant/order/line
query CTE only"]
  FA -->|"left join zero/one aggregate"| G
  RA -->|"left join zero/one aggregate"| G
  G --> Q["dbt analysis / proposed Omni contract
validated context, month/product sums, ratio of sums
no enabled warehouse model"]
```

The aggregation CTEs are not extra physical objects. Both joins require equality of TENANT_ID, ORDER_ID and LINE_ID. Missing aggregates default to zero; no parent row is dropped to conceal an orphan. LINE_KEY is tenant|order|line, with alphanumeric inputs making the delimiter safe. Gold retains all current statuses and tenants. Report date/status/product predicates and principal checks occur downstream; no all-time aggregate replaces interactive report semantics.
