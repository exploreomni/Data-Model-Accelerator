# Tableau context, native Omni LOD and presentation mapping

The candidate contains two native `.view` files, `billing.topic` and `relationships`. The [report-context companion](../target/omni/report-context.json) is explicitly nonnative local metadata: it selects source worksheets, output aliases, filters, evaluation order and post-query expressions. It is not an Omni workbook or dashboard export and does not imply native rendering parity.

| Tableau worksheet | View marks and output | Proposed placement |
|---|---|---|
| Revenue Trend | Month/segment; SUM net, SUM paid, SUM outstanding, weighted payment rate; aggregated net times multiplier | Invoice facts and semantic sums/ratio; multiplier remains a workbook calculation after mark aggregation. |
| Customer Value | Customer/segment; selected net sum; MIN of the FIXED tenant/customer net | Query-time native Omni LOD dimension with selective segment-filter cancellation, wrapped in MIN for each selected mark. |
| Revenue Share | Month/segment net and share of the selected month's marks | Semantic net sum followed by a presentation calculation, addressing segment and partitioning by month after dimension filters. |

## Explicit filter order

Each selected worksheet applies datasource tenant and posted-status population, then the date-window context, then FIXED, then the ordinary segment dimension filter, then mark aggregation and table calculations. Defaults are tenant A, `[2026-01-01, 2026-03-01)`, segment ALL and multiplier 1. Per-worksheet filter roles remain explicit in the companion; they are not inferred solely from the presence of a predicate.

Date filtering uses `invoices.invoice_date`; segment filtering uses `invoices.segment`. Tenant is bound to the supplied authorized synthetic persona and the modeled tenant access filter. Missing/unknown tenant, persona mismatch or explicit unauthorized state fail in the local contract. UI inputs and hidden fields do not establish Tableau/Omni production security. Empty windows produce no marks; reversed or malformed windows fail. The multiplier must be finite and does not alter gold or FIXED.

## Documented native LOD candidate

The `fixed_customer_revenue_cents` dimension references invoice net cents and defines `level_of_detail.aggregate_type: sum` with `fixed: [tenant_id, customer_id]`. Its filter entry is `segment: {is: '', cancel_query_filter: true}`. This selectively removes only the ordinary segment query filter while preserving other query context. Blanket `cancel_query_filters` is not set. The actual field lives in [invoices.view](../target/omni/invoices.view). Omni documents fixed grouping and selective cancellation as distinct controls. [Official dimension LOD reference](https://docs.omni.co/modeling/dimensions/parameters/level-of-detail)

`fixed_customer_revenue_cents_min` aggregates that dimension using MIN. The companion maps its report alias to `fixed_customer_revenue_cents`. This value repeats across customer/segment marks, so summing it or claiming a grand total would change the source semantics. The declaration is a documented syntax candidate; native LOD query generation, interaction with topic access and actual workbook behavior remain unverified. Do not replace it with a permanently materialized all-time customer total.

Money measures keep posted filters on their underlying sums. `payment_rate` divides selected paid sum by `NULLIF(selected net sum,0)` without per-invoice ratio aggregation. Public aggregate wrappers explicitly default empty sums to zero; selected worksheet queries are grouped, so an empty input still produces zero marks.

## Documented presentation proposal and local contract

For Revenue Share, the local companion computes `revenue_cents / partition_sum(revenue_cents)` over post-filter marks, with partition `month` and addressing field `segment`; zero denominator becomes null. This expression is harness metadata, not a native Omni model expression.

The proposed native worksheet uses month as rows, segment as the pivot, and enables row totals for the revenue measure. Its spreadsheet expression divides `${invoices.revenue_cents}` by `${invoices.revenue_cents:row_total}`, with an IF zero branch returning `1/0`. Omni documents row-total references and explicitly documents `1/0` as a spreadsheet null result; this is not inferred from warehouse SQL division. [Official calculations examples](https://docs.omni.co/analyze-explore/calculations#examples)

The proposed expression is `=IF(${invoices.revenue_cents:row_total} = 0, 1/0, ${invoices.revenue_cents} / ${invoices.revenue_cents:row_total})`. Native workbook construction, pivot filling and filtering must still be tested. All selected segment marks must be available before computing the denominator; row/pivot limits or densification can change the population. No matching sorting/action/visual-total behavior is claimed. Omni documents that calculations can depend on result shape and that pivoted queries do not support calculation pushdown. [Official calculation evaluation behavior](https://docs.omni.co/analyze-explore/calculations#evaluating-calculations-before-or-after-row-limits)

Revenue Trend's local companion expression is `revenue_cents * multiplier`. A documented native spreadsheet counterpart for multiplier 2 is `=${invoices.revenue_cents} * 2`; the general companion contains an explicitly nonnative placeholder for a validated finite numeric literal. It does not invent Omni parameter interpolation or a dynamic control API. Multiplication is a documented spreadsheet operator. [Official supported operators](https://docs.omni.co/analyze-explore/calculations/math-number)

## Relationships and remaining decisions

The invoice→customer join uses effective CUSTOMER_KEY plus TENANT_ID and declares many-to-one; both the key and relationship require data tests. The invoice fact already carries historical segment, and runtime segment filtering targets that invoice field consistently with the LOD cancellation. The topic binds `invoices.tenant_id` to user attribute `tenant_id`; real attribute provisioning, Snowflake grants/RLS and negative personas in native Omni remain separate validation.

The [placement register](placement-and-decisions.json) distinguishes reusable row logic, context-sensitive LOD, selected-mark share and exploration. Original names/IDs are retained in [source-to-target.json](source-to-target.json). A business owner must approve whether these preserved worksheet definitions should become authoritative metrics. Owner, production refresh, grants and release approval remain unknown.
