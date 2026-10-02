# Blind dbt holdout: retail fulfillment and returns

This is one small, authored synthetic migration challenge, not a customer project or general qualification benchmark. No target SQL or acceptance outputs are supplied in this input folder. All source files, values and metadata were frozen before target implementation. The task is to assess this existing dbt project, retain its correct staging, refactor reusable logic into a warehouse model, and demonstrate correctness through independent evaluation.

## Inputs and evidence

`repo/` is an existing-style dbt project with two correct staging models and one flawed report. `raw-data.json` is a sanitized synthetic full capture with 32 rows across four tables. `contract.json` names exact raw columns, source identities, output interfaces and report defaults. `catalogue/warehouse-catalogue.json` is the normalized scoped Snowflake catalogue; its dated object and column receipts are retained in `catalogue/exports/`. All metadata and source identities are authored; no account was queried. Physical columns allow null, while the logical contract below requires values. No primary/foreign keys are assumed enforced. Connection `retail-source-synthetic`, account `DMA_RETAIL_SYNTHETIC`, database `DMA_RETAIL`, raw schema `RAW`; all identifiers are unquoted uppercase.

Raw metadata and data are intentionally separate evidence. Snapshot and catalogue capture: 2026-09-11T12:00:00Z. The catalogue covers exactly these four objects and 30 columns; operational owners, grants, actual replication tooling, latency and native execution remain unknown. This challenge needs no history beyond the full CDC capture; order and product attributes come from latest current records, not an SCD dimension.

## CDC and integrity policy

Every row has positive integer SEQUENCE and Boolean IS_DELETED. Native date strings are ISO YYYY-MM-DD, with date-only business semantics and no timezone conversion. All values are logically required. IDs contain only ASCII letters/digits; the authored key encoding is tenant|order|line. SEQUENCE is monotonic only within the declared entity key, never globally. Keys: orders=(tenant,order); lines=(tenant,order,line); fulfillments=(tenant,fulfillment); returns=(tenant,return).

Validate the full capture before selecting current rows. Byte-equivalent duplicate business payloads at the same key/sequence are idempotent. Any differing payload at the same key/sequence is an ambiguous correction and MUST fail, including conflicts at an older superseded version. Select the highest SEQUENCE first, then remove tombstones; filtering tombstones before ranking would resurrect deleted lines/events. A later valid correction replaces the old payload. This is a full-snapshot exercise: recomputation is acceptable and incremental merge design is not required.

Every current line must reference a current order in its own tenant. Every current fulfillment/return must reference a current line by all three key components. No orphan may disappear through an inner join. Quantities and unit prices are positive integers, discounts and refunds nonnegative integers; discount cannot exceed quantity*unit price. Fulfillment quantities cannot exceed ordered quantities. Returned quantities cannot exceed fulfilled quantities. Net retained revenue may be negative if valid cumulative refunds exceed the line net; do not clamp it. Numeric values are bounded to signed 64-bit for the local adapter. Violations must fail before outputs are accepted.

## Reusable target contract

Preserve and reference `stg_orders` and `stg_order_lines` wherever practical. Their latest-record ordering and line arithmetic are correct on validated input. The current project lacks the full ambiguity/reference checks above; add them. LINE_NET_CENTS already equals QUANTITY*UNIT_PRICE_CENTS-DISCOUNT_CENTS, where discount is a total line discount. Applying it again is wrong.

Produce `fct_order_line_fulfillment` at one row per tenant/order/line for every current nondeleted line, including pending/cancelled orders. Its exact 13-column interface is in contract.json. Ordered quantity comes from line staging. Sum current fulfillment events and current return events independently at line grain before joining; absent children yield zero. Retained revenue=line net-refund. Preserve tenant/order/line/product identities and current order date/status. This fact must contain no report date, tenant, product or status defaults.

## Observed report behavior and acceptance intent

The legacy report `retail_fulfillment_summary` displays month/product totals but multiplies independent child rows. This defect is intentionally known: inflated legacy results are evidence of the problem, not the acceptance oracle. Preserve requested definitions, identities and report context while correcting the joins.

Report fields: ORDER_MONTH, PRODUCT_ID, ordered/fulfilled/returned quantities, line-net/refund/retained-revenue cents and FULFILLMENT_RATE. Month is the first day of order-date month. Rate is SUM(fulfilled)/SUM(ordered), never an average of line rates. No selected rows means an empty grouped report; a zero denominator returns null. All amounts are USD integer cents with no conversion or formatting scaling.

Defaults originate in dbt vars and source SQL: tenant A, dates [2026-04-01,2026-04-04), status completed, product ALL. The report allows tenants A/B, statuses completed/pending/cancelled, any product string with ALL disabling that predicate, and valid inclusive-start/exclusive-end ISO dates. Reversed dates, unknown tenant/status, unauthorized access or a mismatched persona_tenant must fail. Empty date intervals are valid empty reports. Tenant/persona enforcement is a separate local harness boundary; neither the SQL variable nor this synthetic fixture proves production RLS. A caller-supplied persona must equal the selected tenant; authorized defaults to true only when omitted, and explicit false/null fails.

## Expected delivery interface

Provide dbt candidate files, a short assessment/placement decision, validation tests and evidence that correct staging is reused. Expose an evaluator with `evaluate(raw_data, params)` returning `{"gold": [...], "report": [...]}` in the exact uppercase field interfaces from contract.json. Gold is independent of report params and sorted by (TENANT_ID,ORDER_ID,LINE_ID); report sorted by (ORDER_MONTH,PRODUCT_ID). Dates serialize as YYYY-MM-DD. An invalid input/context must raise a clear error or return an explicit failed status with no accepted outputs. The independent evaluator will test baseline, tenant/product/status/empty contexts, duplicate ingestion, late correction, deletion, orphan references and tied-version conflicts. It is kept outside the target-author input.

Native dbt/Snowflake execution, deployment, security membership and business approval remain distinct gates. Local simulation results cannot establish them. Do not access other case targets, prior expected results, or a private-oracle directory to solve this holdout.
