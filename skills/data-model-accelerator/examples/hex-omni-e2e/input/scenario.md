# Synthetic Hex workbook collection: subscription billing

This case is invented, customer-free and local only. Three Hex projects share a billing domain. It is a test specification, not a human-approved business definition. Native Hex, dbt/Snowflake and Omni execution remain unavailable.

## Source contract

At snapshot 2026-03-02T00:00:00Z, the connection id is `11111111-1111-4111-8111-111111111111`, warehouse Snowflake, account `DMA_HEX_SYNTHETIC`, database `DMA_HEX`, raw schema `RAW`. Tables INVOICE_CDC, PAYMENT_CDC and CUSTOMER_HISTORY have uppercase columns as in raw-data.json. Tenant and business IDs are composite keys. CDC SEQUENCE is a complete per-key source ordering; exact duplicates are idempotent, conflicting records at the same sequence must fail. Highest sequence wins before deletion filtering. Sequences and IS_DELETED are invented fixture metadata, not inferred production facts.

CUSTOMER_HISTORY uses [VALID_FROM, VALID_TO) intervals, null VALID_TO is open ended. Exact identical history replays deduplicate; overlaps, orphans and null keys fail. Classify invoices at INVOICE_DATE, not current customer segment. Data includes A/B customer/invoice ID collisions and a segment transition exactly on February 1.

`repo/adjustments.csv` is an external manual source with one row per tenant/invoice. Negative amounts are credits, positive amounts corrections. Amounts are integer USD cents; CSV adjustments must be governed and independently inventoried before being promoted to a bronze input. Missing/duplicate adjustments, unknown invoice references and missing file content cannot be silently ignored. Missing rows for valid invoices mean zero adjustment. No currency conversion is implied.

## Intended shared transformations

Keep all current nondeleted invoice statuses in silver/gold; reporting selects posted. Deduplicate payments by tenant/payment/sequence, remove latest tombstones, sum by tenant/invoice before joining invoice facts. NET_CENTS = AMOUNT_CENTS + ADJUSTMENT_CENTS; OUTSTANDING_CENTS = NET_CENTS - PAID_CENTS. Preserve negative balances (overpayment); do not clamp to zero. CUSTOMER_KEY must include tenant, customer and validity start. Gold invoice grain is tenant/invoice. Revenue and executive reporting sum net/paid by invoice-date historical segment and month. Payment rate is SUM(PAID_CENTS)/SUM(NET_CENTS), null for zero denominator. Defaults: tenant A, start_date 2026-01-01 inclusive, end_date 2026-03-01 exclusive, segment ALL. Inputs support B, segment filtering, empty windows, reversed windows (reject), unknown tenant (deny), and explicit unauthorised persona (deny). A UI input alone is not production row security.

## Three source projects and deliberate conflict

1. Revenue exploration: warehouse SQL obtains current invoices, aggregated payments and invoice-date customer segment; Python reads adjustments.csv, joins on tenant+invoice with many-to-one validation, fills missing adjustment with zero, computes NET_CENTS and OUTSTANDING_CENTS; dataframe SQL applies runtime report filters and groups revenue by month/segment. Include a parameter-dependent what-if multiplier cell as retained exploration; it must not change shared revenue.
2. Customer retention: SQL defines an active customer as a customer with a posted invoice and NET_CENTS > 0 in the selected invoice-date month. Outputs distinct tenant/customer/month with historical segment. This project labels its measure `active_customers`.
3. Executive performance: imports/uses the shared revenue calculation (component version evidence required where authored); reports net/paid totals and weighted payment rate. It defines `active_customers` as customers with a posted invoice and PAID_CENTS > 0 in the selected month. These two definitions intentionally conflict; preserve separate names `invoiced_active_customers` and `paying_active_customers` in the proposed semantic layer, retain original names/IDs and require human choice before canonical consolidation. Never silently choose one. Component version drift/missing component must be a gap.

## Retention interpretation

For this bounded snapshot, cohort month is the earliest INVOICE_DATE month of a posted invoice having positive current PAID_CENTS. This is explicitly an invoice-based proxy at the capture watermark, not payment-event-time retention or a historical as-of payment balance. No actual payment timestamp is supplied. Gold customer-month model can supply NET_CENTS, PAID_CENTS, HAS_INVOICE (posted net > 0), HAS_PAID_INVOICE (posted paid > 0) and FIRST_PAID_MONTH using this proxy. Segment belongs to the invoice-grain report; one customer changing segment within a month requires a separately chosen allocation policy before a single customer-month segment can be claimed.

## Test expectations and limits

An independent oracle must derive rows/reports from raw-data.json, adjustments.csv and this scenario only, before reading target code. Compare key sets, intermediate grain, dimensional slices and totals. Include two intentional adjustment mistakes whose grand total cancels but segment outputs change. Inject duplicate/omitted sources, unsafe/dynamic Python, missing components, parameter drift, removal of tenant keys, history overlaps, changed source/target logic and replay errors. Catch defects by the intended assertion, not unrelated syntax errors.

The model package must include source graph and cell coverage, catalogue/bindings, target dbt/Snowflake and Omni files, placement/conflict register, ERD, complete dictionary and bronze/silver/gold operating documentation. Native compilation/execution, real permissions, production incremental ingestion, business approval and release remain separate gates.

## Fixture clarification before oracle freeze

Customer-month NET_CENTS/PAID_CENTS sum all current nondeleted invoice statuses; HAS_INVOICE, HAS_PAID_INVOICE and FIRST_PAID_MONTH use posted invoices only. Reports filter posted invoice-grain rows. Fixture CUSTOMER_KEY is TENANT_ID || '|' || CUSTOMER_ID || '|' || VALID_FROM as YYYY-MM-DD; fixture IDs cannot contain pipes. A production key must use an agreed collision-safe encoding.
