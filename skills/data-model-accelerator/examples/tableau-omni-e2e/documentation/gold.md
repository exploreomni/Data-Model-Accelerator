# Gold invoice facts, with interactive calculations kept downstream

Two gold tables serve the selected worksheets. No customer-month aggregate or all-time customer-value table is included: neither is needed by the selected source semantics. The [ERD](model-erd.md), [model map](../target/model-map.json) and [dictionary](data-dictionary.md) describe the exact physical proposal.

| Physical model | Grain and keys | Purpose |
|---|---|---|
| `DMA_TABLEAU.GOLD.DIM_CUSTOMERS` | Tenant/customer/valid-from; CUSTOMER_KEY = tenant\|customer\|YYYY-MM-DD | Effective customer segment history, with original intervals. |
| `DMA_TABLEAU.GOLD.FCT_INVOICES` | Tenant/invoice; INVOICE_KEY = tenant\|invoice, effective CUSTOMER_KEY | All current nondeleted invoice balances, independently aggregated payments, signed corrections and invoice-date historical segment. |

## Grain and accounting

Payments aggregate per tenant/invoice before joining the invoice fact. Adjustments join on tenant/invoice at maximum-one-row grain. The customer join includes tenant/customer, `INVOICE_DATE >= VALID_FROM`, and exclusive/null-ended VALID_TO. Each invoice must have exactly one effective row. A left join leaves an invalid orphan visible to a failing test; it does not silently omit the invoice. Physical primary/foreign/non-null constraints are not emitted by these CTAS models.

`NET_CENTS = AMOUNT_CENTS + COALESCE(ADJUSTMENT_CENTS,0)`. `PAID_CENTS` is the scoped current-payment total, zero if absent. `OUTSTANDING_CENTS = NET_CENTS - PAID_CENTS`, preserving negative balances and overpayments. All amounts remain integer USD cents. Display divides by 100 exactly once; no FX or zero-clamping is proposed. The scenario multiplier never changes shared net revenue.

Invoice month is the first day of the supplied invoice-date month. Segment belongs to the history row effective on each invoice date, not the customer's current segment. Source IDs cannot contain pipes in this fixture; production key encoding needs explicit design. All current statuses and dates remain in the fact, including drafts and out-of-window invoices.

## Worksheet contracts that cannot become static facts

Revenue Trend selects the posted/tenant/date/segment population and groups by month and historical segment. Revenue, paid and outstanding are sums; payment rate divides aggregate paid by aggregate net and returns null when net is zero. Its scenario revenue multiplies the aggregated mark by the validated runtime multiplier.

Customer Value first filters datasource tenant/status and the date-window context, computes FIXED tenant/customer SUM(net), then applies the ordinary segment filter and aggregates displayed customer/segment marks. The FIXED value can repeat in several marks; MIN preserves the mark value without double counting. No grand total over repeated FIXED values is asserted. Materializing an all-time customer total would lose the source date-context behavior.

Revenue Share divides each filtered month/segment mark by the sum of the remaining marks in that same month. Segment is the addressing dimension and month the partition. The denominator changes after ordinary segment filtering; an all-month or pre-segment denominator is wrong for this contract. Zero denominators produce null and an empty window produces no marks. Sorting ties, densification, filter actions and native visual totals remain unqualified.

The [native Omni LOD and presentation mapping](semantic-mapping.md) records the selective segment cancellation and explicit post-query partition. Business owners must decide whether these source definitions are appropriate authoritative metrics; preservation is not endorsement.

## Refresh, validation and operations

Full rebuild order is validated raw → four silver tables → customer dimension → invoice fact. Source changes can restate prior facts; no historical as-of snapshot service or incremental policy is implemented. Monitor keys, tenant joins, temporal matches, signs, payment reconciliation, replay invariance, and selected worksheet context/partition behavior. Opposing adjustment mistakes can cancel overall, so reconcile segment/month/customer slices as well as totals.

The local harness and independent oracle provide separately recorded evidence. Native Snowflake execution, Omni model validation/LOD evaluation, Tableau workbook opening/rendering and production personas remain unverified here. Native dbt parsing, when recorded, does not establish those gates.

No production run schedule, SLA, grants, retention period, named operating owner, consumer approval or automated rollback is supplied. Preserve source artifacts and the prior accepted outputs until the exact candidate and dimensional results are reviewed. Rebuild from retained validated source/CSV receipts after correction; do not patch isolated gold values. Cutover and decommissioning require separate authorization.
