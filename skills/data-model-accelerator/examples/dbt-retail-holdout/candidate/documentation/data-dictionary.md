# Retail fulfillment dictionary

All 9 scoped warehouse objects and 68 columns; 30 raw columns come from the supplied catalogue. Local dbt output projections were checked independently against the model map. The [canonical JSON](data-dictionary.json) pins inventory bytes and contains classification, lineage and validation for every column. Physical nullability and constraints do not establish logical input acceptance.

## DMA_RETAIL.RAW.ORDER_CDC

Version occurrence at tenant/order/sequence; exact duplicate payloads permitted.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [input/catalogue/warehouse-catalogue.json](../../input/catalogue/warehouse-catalogue.json)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | input/raw-data.json#/tables/ORDER_CDC/*/TENANT_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | input/raw-data.json#/tables/ORDER_CDC/*/ORDER_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_DATE | Current order header calendar date, no timezone conversion. VARCHAR | input/raw-data.json#/tables/ORDER_CDC/*/ORDER_DATE; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Calendar date; no timezone conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| STATUS | Supplied current-status category; no report default is applied in staging. VARCHAR | input/raw-data.json#/tables/ORDER_CDC/*/STATUS; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| SEQUENCE | Positive version order within the declared entity key only. NUMBER(38,0) | input/raw-data.json#/tables/ORDER_CDC/*/SEQUENCE; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| IS_DELETED | Tombstone applied only after selecting highest version. BOOLEAN | input/raw-data.json#/tables/ORDER_CDC/*/IS_DELETED; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).

## DMA_RETAIL.RAW.ORDER_LINE_CDC

Version occurrence at tenant/order/line/sequence.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [input/catalogue/warehouse-catalogue.json](../../input/catalogue/warehouse-catalogue.json)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | input/raw-data.json#/tables/ORDER_LINE_CDC/*/TENANT_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | input/raw-data.json#/tables/ORDER_LINE_CDC/*/ORDER_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_ID | Line identity scoped to tenant/order. VARCHAR | input/raw-data.json#/tables/ORDER_LINE_CDC/*/LINE_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| PRODUCT_ID | Current order-line product identity, without a separately supplied product dimension. VARCHAR | input/raw-data.json#/tables/ORDER_LINE_CDC/*/PRODUCT_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| QUANTITY | Positive entity quantity; interpreted at the source model grain. NUMBER(38,0) | input/raw-data.json#/tables/ORDER_LINE_CDC/*/QUANTITY; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| UNIT_PRICE_CENTS | Positive unit price in USD cents. NUMBER(38,0) | input/raw-data.json#/tables/ORDER_LINE_CDC/*/UNIT_PRICE_CENTS; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| DISCOUNT_CENTS | Total line discount, subtracted once from quantity times unit price. NUMBER(38,0) | input/raw-data.json#/tables/ORDER_LINE_CDC/*/DISCOUNT_CENTS; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| SEQUENCE | Positive version order within the declared entity key only. NUMBER(38,0) | input/raw-data.json#/tables/ORDER_LINE_CDC/*/SEQUENCE; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| IS_DELETED | Tombstone applied only after selecting highest version. BOOLEAN | input/raw-data.json#/tables/ORDER_LINE_CDC/*/IS_DELETED; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).

## DMA_RETAIL.RAW.FULFILLMENT_CDC

Version occurrence at tenant/fulfillment/sequence.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [input/catalogue/warehouse-catalogue.json](../../input/catalogue/warehouse-catalogue.json)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | input/raw-data.json#/tables/FULFILLMENT_CDC/*/TENANT_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| FULFILLMENT_ID | Fulfillment event identity scoped to tenant. VARCHAR | input/raw-data.json#/tables/FULFILLMENT_CDC/*/FULFILLMENT_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | input/raw-data.json#/tables/FULFILLMENT_CDC/*/ORDER_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_ID | Line identity scoped to tenant/order. VARCHAR | input/raw-data.json#/tables/FULFILLMENT_CDC/*/LINE_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| QUANTITY | Positive entity quantity; interpreted at the source model grain. NUMBER(38,0) | input/raw-data.json#/tables/FULFILLMENT_CDC/*/QUANTITY; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| SEQUENCE | Positive version order within the declared entity key only. NUMBER(38,0) | input/raw-data.json#/tables/FULFILLMENT_CDC/*/SEQUENCE; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| IS_DELETED | Tombstone applied only after selecting highest version. BOOLEAN | input/raw-data.json#/tables/FULFILLMENT_CDC/*/IS_DELETED; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).

## DMA_RETAIL.RAW.RETURN_CDC

Version occurrence at tenant/return/sequence.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [input/catalogue/warehouse-catalogue.json](../../input/catalogue/warehouse-catalogue.json)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | input/raw-data.json#/tables/RETURN_CDC/*/TENANT_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| RETURN_ID | Return event identity scoped to tenant. VARCHAR | input/raw-data.json#/tables/RETURN_CDC/*/RETURN_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | input/raw-data.json#/tables/RETURN_CDC/*/ORDER_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_ID | Line identity scoped to tenant/order. VARCHAR | input/raw-data.json#/tables/RETURN_CDC/*/LINE_ID; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| QUANTITY | Positive entity quantity; interpreted at the source model grain. NUMBER(38,0) | input/raw-data.json#/tables/RETURN_CDC/*/QUANTITY; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| REFUND_CENTS | Nonnegative return-event refund; line fact sums current events; absent children zero. NUMBER(38,0) | input/raw-data.json#/tables/RETURN_CDC/*/REFUND_CENTS; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| SEQUENCE | Positive version order within the declared entity key only. NUMBER(38,0) | input/raw-data.json#/tables/RETURN_CDC/*/SEQUENCE; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| IS_DELETED | Tombstone applied only after selecting highest version. BOOLEAN | input/raw-data.json#/tables/RETURN_CDC/*/IS_DELETED; input/catalogue/warehouse-catalogue.json Preserve complete captured row; raw catalogue permits null physically, logical validation requires values. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).

## DMA_RETAIL.SILVER.STG_ORDERS

One current nondeleted tenant/order.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [dbt/models/staging/stg_orders.sql](../dbt/models/staging/stg_orders.sql)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | DMA_RETAIL.RAW.ORDER_CDC.TENANT_ID; dbt/models/staging/stg_orders.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | DMA_RETAIL.RAW.ORDER_CDC.ORDER_ID; dbt/models/staging/stg_orders.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_DATE | Current order header calendar date, no timezone conversion. DATE | DMA_RETAIL.RAW.ORDER_CDC.ORDER_DATE; dbt/models/staging/stg_orders.sql Latest sequence within entity before tombstone; preserve current value. CAST VARCHAR to DATE. | Calendar date; no timezone conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_STATUS | Current order status renamed from raw STATUS. VARCHAR | DMA_RETAIL.RAW.ORDER_CDC.STATUS; dbt/models/staging/stg_orders.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_KEY | tenant&#124;order encoding at current order grain. VARCHAR | DMA_RETAIL.RAW.ORDER_CDC.{TENANT_ID,ORDER_ID}; dbt/models/staging/stg_orders.sql Reuse tenant-aware pipe concatenation; validate alphanumeric input IDs. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).

## DMA_RETAIL.SILVER.STG_ORDER_LINES

One current nondeleted tenant/order/line.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [dbt/models/staging/stg_order_lines.sql](../dbt/models/staging/stg_order_lines.sql)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | DMA_RETAIL.RAW.ORDER_LINE_CDC.TENANT_ID; dbt/models/staging/stg_order_lines.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | DMA_RETAIL.RAW.ORDER_LINE_CDC.ORDER_ID; dbt/models/staging/stg_order_lines.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_ID | Line identity scoped to tenant/order. VARCHAR | DMA_RETAIL.RAW.ORDER_LINE_CDC.LINE_ID; dbt/models/staging/stg_order_lines.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| PRODUCT_ID | Current order-line product identity, without a separately supplied product dimension. VARCHAR | DMA_RETAIL.RAW.ORDER_LINE_CDC.PRODUCT_ID; dbt/models/staging/stg_order_lines.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| QUANTITY | Positive entity quantity; interpreted at the source model grain. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.RAW.ORDER_LINE_CDC.QUANTITY; dbt/models/staging/stg_order_lines.sql Latest sequence within entity before tombstone; preserve current value. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| UNIT_PRICE_CENTS | Positive unit price in USD cents. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.RAW.ORDER_LINE_CDC.UNIT_PRICE_CENTS; dbt/models/staging/stg_order_lines.sql Latest sequence within entity before tombstone; preserve current value. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| DISCOUNT_CENTS | Total line discount, subtracted once from quantity times unit price. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.RAW.ORDER_LINE_CDC.DISCOUNT_CENTS; dbt/models/staging/stg_order_lines.sql Latest sequence within entity before tombstone; preserve current value. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_NET_CENTS | Ordered quantity times unit price less the total line discount exactly once. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.RAW.ORDER_LINE_CDC.{QUANTITY,UNIT_PRICE_CENTS,DISCOUNT_CENTS}; dbt/models/staging/stg_order_lines.sql Reuse source staging QUANTITY * UNIT_PRICE_CENTS - DISCOUNT_CENTS without modification. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_KEY | tenant&#124;order&#124;line encoding; ASCII alphanumeric components make delimiter safe in this fixture. VARCHAR | DMA_RETAIL.RAW.ORDER_LINE_CDC.{TENANT_ID,ORDER_ID,LINE_ID}; dbt/models/staging/stg_order_lines.sql Reuse tenant-aware pipe concatenation; validate alphanumeric input IDs. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).

## DMA_RETAIL.SILVER.STG_FULFILLMENTS

One current nondeleted tenant/fulfillment.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [dbt/models/staging/stg_fulfillments.sql](../dbt/models/staging/stg_fulfillments.sql)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | DMA_RETAIL.RAW.FULFILLMENT_CDC.TENANT_ID; dbt/models/staging/stg_fulfillments.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| FULFILLMENT_ID | Fulfillment event identity scoped to tenant. VARCHAR | DMA_RETAIL.RAW.FULFILLMENT_CDC.FULFILLMENT_ID; dbt/models/staging/stg_fulfillments.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | DMA_RETAIL.RAW.FULFILLMENT_CDC.ORDER_ID; dbt/models/staging/stg_fulfillments.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_ID | Line identity scoped to tenant/order. VARCHAR | DMA_RETAIL.RAW.FULFILLMENT_CDC.LINE_ID; dbt/models/staging/stg_fulfillments.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| QUANTITY | Positive entity quantity; interpreted at the source model grain. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.RAW.FULFILLMENT_CDC.QUANTITY; dbt/models/staging/stg_fulfillments.sql Latest sequence within entity before tombstone; preserve current value. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).

## DMA_RETAIL.SILVER.STG_RETURNS

One current nondeleted tenant/return.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [dbt/models/staging/stg_returns.sql](../dbt/models/staging/stg_returns.sql)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | DMA_RETAIL.RAW.RETURN_CDC.TENANT_ID; dbt/models/staging/stg_returns.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| RETURN_ID | Return event identity scoped to tenant. VARCHAR | DMA_RETAIL.RAW.RETURN_CDC.RETURN_ID; dbt/models/staging/stg_returns.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | DMA_RETAIL.RAW.RETURN_CDC.ORDER_ID; dbt/models/staging/stg_returns.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_ID | Line identity scoped to tenant/order. VARCHAR | DMA_RETAIL.RAW.RETURN_CDC.LINE_ID; dbt/models/staging/stg_returns.sql Latest sequence within entity before tombstone; preserve current value. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| QUANTITY | Positive entity quantity; interpreted at the source model grain. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.RAW.RETURN_CDC.QUANTITY; dbt/models/staging/stg_returns.sql Latest sequence within entity before tombstone; preserve current value. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| REFUND_CENTS | Nonnegative return-event refund; line fact sums current events; absent children zero. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.RAW.RETURN_CDC.REFUND_CENTS; dbt/models/staging/stg_returns.sql Latest sequence within entity before tombstone; preserve current value. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).

## DMA_RETAIL.GOLD.FCT_ORDER_LINE_FULFILLMENT

One current nondeleted tenant/order/line across all statuses, dates and tenants.

Owner: Unknown; no operational or business approver supplied.

Code/evidence: [dbt/models/gold/fct_order_line_fulfillment.sql](../dbt/models/gold/fct_order_line_fulfillment.sql)

| Column | Definition / type | Source and rule | Units / null policy |
|---|---|---|---|
| LINE_KEY | tenant&#124;order&#124;line encoding; ASCII alphanumeric components make delimiter safe in this fixture. VARCHAR | DMA_RETAIL.SILVER.STG_ORDER_LINES.LINE_KEY; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| TENANT_ID | Tenant scope; part of every business identity and join. VARCHAR | DMA_RETAIL.SILVER.STG_ORDER_LINES.TENANT_ID; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_ID | Order identity scoped to tenant. VARCHAR | DMA_RETAIL.SILVER.STG_ORDER_LINES.ORDER_ID; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_ID | Line identity scoped to tenant/order. VARCHAR | DMA_RETAIL.SILVER.STG_ORDER_LINES.LINE_ID; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| PRODUCT_ID | Current order-line product identity, without a separately supplied product dimension. VARCHAR | DMA_RETAIL.SILVER.STG_ORDER_LINES.PRODUCT_ID; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_DATE | Current order header calendar date, no timezone conversion. DATE | DMA_RETAIL.SILVER.STG_ORDERS.ORDER_DATE; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | Calendar date; no timezone conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDER_STATUS | Current order status renamed from raw STATUS. VARCHAR | DMA_RETAIL.SILVER.STG_ORDERS.ORDER_STATUS; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | Identifier/category/version/boolean as defined; no currency aggregation Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| ORDERED_QUANTITY | Current line quantity preserved without multiplying child rows. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.SILVER.STG_ORDER_LINES.QUANTITY; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| FULFILLED_QUANTITY | Sum of current fulfillment event quantity by tenant/order/line; absent events zero. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.SILVER.STG_FULFILLMENTS.QUANTITY; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. SUM current events separately at line grain before joining; COALESCE absent children to 0. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| RETURNED_QUANTITY | Sum of current return event quantity by tenant/order/line; absent events zero. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.SILVER.STG_RETURNS.QUANTITY; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. SUM current events separately at line grain before joining; COALESCE absent children to 0. | Item count Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| LINE_NET_CENTS | Ordered quantity times unit price less the total line discount exactly once. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.SILVER.STG_ORDER_LINES.LINE_NET_CENTS; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. Preserve parent value; orphan checks must pass before acceptance. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| REFUND_CENTS | Nonnegative return-event refund; line fact sums current events; absent children zero. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.SILVER.STG_RETURNS.REFUND_CENTS; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. SUM current events separately at line grain before joining; COALESCE absent children to 0. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |
| RETAINED_REVENUE_CENTS | Line net less summed refunds; negative retained revenue remains negative. DECIMAL(38,0); exact integer cents or quantities | DMA_RETAIL.SILVER.STG_ORDER_LINES.LINE_NET_CENTS and STG_RETURNS.REFUND_CENTS; dbt/models/gold/fct_order_line_fulfillment.sql Tenant/order/line-safe joins. LINE_NET_CENTS - COALESCE(sum current refunds,0), no clamp. | USD integer cents; no conversion Physically nullable; logically required on accepted rows. No enforced NOT NULL assertion from metadata. |

All identities are tenant scoped. Classification: synthetic; production access/retention unverified. Validation: [fresh replay and author-test instructions](../README.md#run-locally).
