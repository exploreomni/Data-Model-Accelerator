# Synthetic Tableau migration: subscription billing

This deliberately reuses the invented billing records from the Hex pilot to isolate Tableau-specific behavior. No customer data, native Tableau export or production approval is implied. The proposed Snowflake namespace is DMA_TABLEAU, account DMA_TABLEAU_SYNTHETIC, schema RAW, captured at 2026-03-02T00:00:00Z. Input metadata and output evidence must identify this namespace explicitly.

## Raw and shared model contract

INVOICE_CDC, PAYMENT_CDC and CUSTOMER_HISTORY have the exact uppercase columns in raw-data.json. ADJUSTMENTS is the proposed governed landing of repo/adjustments.csv, keyed by tenant/invoice. Amounts are integer USD cents. Composite identities include tenant. Highest source SEQUENCE wins before tombstone filtering. Exact repeated versions are idempotent; conflicting same-sequence versions, null identifiers, missing references and overlapping customer validity intervals fail. Invoice-date customer history uses [VALID_FROM, VALID_TO); a null end means open-ended. Physical raw date columns are VARCHAR, with explicit casts in silver and a DATE adaptation in the local engine.

Deduplicate payments at tenant/payment grain, remove latest tombstones, then aggregate by tenant/invoice before joining invoice facts. Join one adjustment per tenant/invoice. Missing adjustment rows mean zero; missing CSV content, duplicate keys and orphan adjustments are errors. NET_CENTS = AMOUNT_CENTS + ADJUSTMENT_CENTS; OUTSTANDING_CENTS = NET_CENTS - PAID_CENTS. Preserve negative net and overpaid balances. Gold contains all current, nondeleted invoice statuses at tenant/invoice grain. Customer history dimension grain is tenant/customer/valid-from. Keys use tenant|business-id and tenant|customer|valid-from within this synthetic fixture, where components cannot contain pipes. Production needs an agreed collision-safe encoding.

## Tableau source and order of operations

One authored TWB workbook contains three worksheets and one dashboard, backed by an embedded Snowflake custom SQL data source. Its separately authored TDS mirror must have matching SQL and field definitions. A TWBX packages those exact artifacts as a separate packaging test; count the workbook once. No Hyper extract is supplied. Tableau native opening, rendering, server permissions and refresh are unavailable.

The custom SQL normalizes CDC, aggregates payments, applies temporal customer binding and joins the proposed RAW.ADJUSTMENTS landing; it returns amount, nullable adjustment, paid, tenant, invoice, customer, invoice date, status and historical segment. Native row calculations compute net using ZN(adjustment), outstanding, invoice month and parameter predicates. Unsupported or missing source semantics fail or remain explicit gaps; they may not be replaced by expected outputs.

Defaults: tenant=A, start_date=2026-01-01 inclusive, end_date=2026-03-01 exclusive, segment=ALL, multiplier=1. Tenant B, individual segments, bounded date windows and multiplier 2 are supported. Input tenant is constrained to the supplied synthetic persona tenant; unknown/missing tenant, unauthorized persona, malformed/reversed dates and nonfinite multipliers fail. This local persona check does not establish Tableau or Omni security.

For each worksheet, apply datasource population filters (posted status and selected tenant), then the date-window CONTEXT filter, then compute the FIXED calculation, then apply the ordinary segment DIMENSION filter, then aggregate view marks, then compute table calculations. The segment predicate is `segment=ALL OR row.segment=segment`. FIXED customer net is `{ FIXED [Tenant ID], [Customer ID] : SUM([Net Cents]) }`; it respects the date context and tenant/status population but ignores the ordinary segment filter. Worksheet-specific contexts must be preserved.

## Selected worksheets

1. Revenue Trend: group by invoice month and historical segment. Output `month`, `segment`, `revenue_cents` (SUM net), `paid_cents` (SUM paid), `outstanding_cents` (SUM outstanding), `payment_rate` (SUM paid / SUM net; null at zero), and `scenario_revenue_cents` (SUM net times multiplier, retained downstream).
2. Customer Value: group selected marks by customer ID and historical segment. Output `customer_id`, `segment`, `selected_revenue_cents` (SUM selected net), `fixed_customer_revenue_cents` (MIN FIXED customer net). The FIXED value may repeat across segments; summing it across marks would double count. No grand total for this repeated dimension is claimed.
3. Revenue Share: group by invoice month and historical segment. Output `month`, `segment`, `revenue_cents`, `share_of_month` = SUM(net) / WINDOW_SUM(SUM(net)). Address by segment, partition by month, after dimension filters; null at zero denominator. Do not use an all-month denominator or materialize this interactive share in gold. Dashboard filter actions, sorting ties, densification and native visual rendering remain unqualified.

Empty windows produce zero marks (empty lists) for all three sheets. Keep exact integer cents and compare ratios with 1e-12 tolerance. A segment change across January/February makes filtering before FIXED observably wrong; raw multi-payment invoices and A/B identity collisions expose fanout and cross-tenant joins. Original semantics are preserved; a business owner must decide whether context-sensitive customer value and filtered share are desired authoritative definitions.

## Required evidence

An independent oracle derives expected invoice rows and all selected sheet outputs directly from this scenario and frozen raw/CSV inputs, without reading target code or the prior Hex oracle. Cover both tenants, context/date boundaries, segment filters, zero denominators, empty windows and multiplier changes. Inject defects in source formulas, datasource/filter membership, context order, FIXED scope, table-calculation partitioning, joins, source/TDS drift, archive paths and documentation. Require failures for their intended reasons.

Deliver a static source graph with original native names/IDs and hashes; scoped catalogue and bindings; candidate dbt/Snowflake bronze/silver/gold and Omni model; per-rule placement and supported presentation contract; ERD, complete dictionary and all three layer guides; execution traces, negative evidence and explicit review gates. This is a bounded replay of authored artifacts, not a general Tableau compiler, automatic fresh model generation, native deployment or production acceptance.
