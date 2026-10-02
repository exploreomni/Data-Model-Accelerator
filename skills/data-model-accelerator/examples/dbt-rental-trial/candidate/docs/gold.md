# Gold: rental revenue fact

Authority: synthetic `SYNTHETIC-RENTAL-DECISION-001`. `fct_rental_revenue` has exactly one row per live completed `(tenant_id, rental_id)` at the `2026-08-16T00:00:00Z` watermark. It depends on `stg_rentals`, `stg_locations` and `int_eligible_charges`.

Eligible charges aggregate to the composite rental key before joining rentals. The rental/location join also uses `tenant_id + location_id`. This prevents charge or location fanout across versions and tenants. A left join of charge totals preserves completed rentals with no eligible charges; all amounts become decimal zero and the count becomes integer zero. Counts use actual eligible charge IDs. Live locations for all live rentals are a fixture guarantee, verified by a relationship test.

| Output | Definition |
|---|---|
| fee_amount | Sum of eligible rental_fee and damage_fee signed amounts; nonnegative |
| refund_amount | Sum of eligible refund signed amounts; negative or zero |
| net_revenue | fee_amount + refund_amount |
| eligible_charge_count | Count of eligible charge IDs; deposits excluded |

All amounts are cast to `DECIMAL(18,2)` and the count is `BIGINT`; no float or integer division is used. Tenant, rental, location, status, date and currency columns are VARCHAR. All columns are non-null for the fixture. [The dictionary](data-dictionary.md) covers the exact eleven-column contract, composite keys and lineage.

Applicable rules: R-ELIGIBLE, R-ZERO, R-GRAIN, R-TENANT, R-HISTORY and R-SEMANTIC. R-SIGN is applied upstream and retained in the sums. Cancelled, active and deleted rentals have no fact row. Deleted charges and refundable deposits never contribute amounts or counts. Current live location names appear even on older rental dates; there is no historical label, historical status or as-of revenue claim.

The historical source report remains unchanged at `../input/repo/models/legacy_report.sql`. It combined CDC versions, omitted tenant keys, retained tombstones, used obsolete labels, dropped zero-charge rentals, included deposits and added unsigned refund amounts. Those behaviors are corrected under the synthetic accepted decision. `analyses/legacy_report.sql` now references gold and retains the shared report columns. Tenant C / rental R9 is the declared clean compatibility slice; independent validation is the host's responsibility, not a hard-coded SQL exception.

Omni owns tenant authorization/personas, rental-date/status/location report filters, currency presentation and the `sum(net_revenue)` metric. Gold remains at rental grain and contains all tenants. See [the semantic contract](../semantic/omni-contract.md); a query filter cannot prove authentication or RLS enforcement.

Recover by restoring verified raw seeds and rebuilding silver then gold. Schema, composite-grain and tenant/source coverage tests must pass before downstream consumption. Investigation is required if missing live locations would omit a completed rental; never silently fabricate a location label. No deployment, Snowflake execution, production acceptance, GA status or live Omni validation is claimed by this local synthetic trial.
