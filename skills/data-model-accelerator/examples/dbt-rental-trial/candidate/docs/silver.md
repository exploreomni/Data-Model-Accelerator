# Silver: current state and eligible transactions

Authority is the synthetic accepted decision `SYNTHETIC-RENTAL-DECISION-001`. These are local full-table transformations using native SQL and three typed dbt seeds; no custom macros, external packages, hooks, incremental state or snapshots are used.

| Model | Dependency | Grain / key | Rule placement |
|---|---|---|---|
| stg_rentals | raw_rentals | One live tenant_id + rental_id | R-CDC, R-TENANT, R-HISTORY; retains current cancelled and active rentals |
| stg_charges | raw_charges | One live tenant_id + charge_id | R-CDC, R-TENANT, R-HISTORY; retains non-revenue categories and charges with deleted parents |
| stg_locations | raw_locations | One live tenant_id + location_id | R-CDC, R-TENANT, R-HISTORY; current location labels |
| int_eligible_charges | stg_rentals, stg_charges | One eligible tenant_id + charge_id | R-ELIGIBLE, R-SIGN, R-TENANT; reusable eligible, signed transactions |

All three staging models rank the complete history by `cdc_sequence DESC, updated_at DESC` within the tenant/entity key. Only rank 1 is considered, then `is_deleted = false` is required. Filtering tombstones first would resurrect obsolete rows. Exact duplicate versions are equivalent; conflicting tied payloads are not covered by the fixture. Staging retains the latest CDC metadata for audit and drops the tombstone flag.

The intermediate joins charges to rentals on both `tenant_id` and `rental_id`, also requiring currency equality. The rental must be live and completed. Only rental_fee, damage_fee and refund remain. Refundable deposits are liabilities excluded from revenue and eligible charge count. `source_amount` retains the nonnegative source magnitude; `signed_amount` is exactly its negative for refunds and its positive value for fees. Both are `DECIMAL(18,2)`.

No tenant or report-date selection is hard-coded. The intermediate owns durable billing eligibility, while report-specific date/status/location filters, personas and metric context remain downstream. Visibility of `tenant_id` is not RLS.

This is a current-state snapshot through `2026-08-16T00:00:00Z`, not an as-of model or SCD. Cancelled rentals remain staged but never enter eligible charges or gold. Gold uses current live location labels even for old rental dates. IDs, dates and timestamps remain VARCHAR; CDC sequences are BIGINT. Every output column is non-null for this fixture. [The dictionary](data-dictionary.md) specifies all columns, types, lineage and tenant relationships.

`models/schema.yml` checks all columns for nulls and enforces the five model schemas. `tests/grain.sql` checks complete composite keys. `tests/tenant_integrity.sql` checks same-tenant parents and source keys, permits orphaned staging charges when their rental is deleted, and requires valid completed parents for eligible charges. These checks do not encode withheld expected revenue values.

On failure, stop consumption, investigate the failed key and original source history, correct the allowed input or model through review, then rebuild and rerun checks. Within this exercise the source is immutable, so source corrections are a handoff, not an edit. Recover from the preserved CSVs; do not patch materialized results or infer missing historical versions. Local tests do not establish Snowflake execution or live tenant security.
