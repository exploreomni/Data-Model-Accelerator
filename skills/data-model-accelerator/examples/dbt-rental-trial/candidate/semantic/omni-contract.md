# Downstream Omni semantic contract

**Status:** proposed downstream contract for a local synthetic exercise, grounded in `SYNTHETIC-RENTAL-DECISION-001`. It is not an installed Omni model, authenticated approval, live catalogue evidence or a product-release claim. Live Omni authentication, persona behavior, RLS and warehouse access policies are **unverified**.

The reusable input is `fct_rental_revenue`, keyed by `(tenant_id, rental_id)` and containing every live completed rental in the supplied snapshot. It includes zero-charge rentals. All amounts are USD `DECIMAL(18,2)`; timestamps and rental dates in the upstream data represent UTC. Location names reflect the current live labels, not labels as of the rental date.

| Semantic concern | Downstream contract |
|---|---|
| Revenue metric | `sum(net_revenue)` over authorized, report-filtered gold rows. Never recompute it from raw charges or sum raw refund magnitudes. |
| Supporting measures | `sum(fee_amount)`, `sum(refund_amount)`, `sum(eligible_charge_count)`. Refund totals retain their negative sign. |
| Rental counting | Gold row count after approved filters; uniqueness is the composite tenant/rental key. Bare rental IDs are not globally unique. |
| Date context | Report filters operate on rental_date, interpreted as UTC date text in this fixture. A charge posting date or CDC timestamp is not the revenue reporting date. |
| Status context | Report status filters remain downstream. The revenue fact intentionally contains completed rentals only; selecting active/cancelled yields no rows, not another eligibility definition. |
| Location context | Filter by tenant-scoped location_id or current label. Do not assume location_name or location_id is globally unique. |
| Currency context | Display USD consistently. Retain currency grouping if generalized; currency conversion and mixed-currency sums are outside the fixture. |
| Tenant/persona | The consuming application must bind trusted identity to an approved tenant set. An authorized persona can query only that set; a denied persona receives no rows. Missing/unknown authorization must fail closed. Actual mechanism and enforcement require live review and testing. |

CDC cleanup, tombstone handling, tenant-safe joins, completed-rental eligibility, deposit exclusion, refund sign and rental-grain aggregation are upstream reusable definitions. No hard-coded report dates, tenant lists, persona IDs or location selections exist in those models. The consumer must apply authorization before aggregation so totals do not reveal unauthorized tenants. A report filter controlled by the viewer must not serve as the security boundary.

`analyses/legacy_report.sql` demonstrates the shared report column shape from gold. It is an unfiltered dbt analysis, not a secured endpoint or production dashboard. The original flawed observation is preserved at `../input/repo/models/legacy_report.sql`. Corrections are listed in [gold.md](../docs/gold.md).

The host may test an authorized or denied persona with explicit query predicates as a local filter probe. Passing that probe proves only the query's row selection. It does not prove Omni identity binding, tamper resistance, export restrictions, warehouse-role isolation or row-access policy enforcement. Those need separately authorized live configuration and validation; none is claimed here.

Recovery starts upstream: restore catalogue-verified seeds, rebuild all five models, and rerun the integrity checks and independent acceptance checks. Refresh downstream metadata after verified schema changes. Do not repair revenue by changing report formulas or loosening tenant filters.
