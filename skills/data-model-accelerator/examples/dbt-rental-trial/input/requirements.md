# Synthetic accepted rental billing definitions

Authority: `SYNTHETIC-RENTAL-DECISION-001`, supplied by the independent source
analyst `/root/rental_analyst` for this exercise only. These accepted definitions
are fabricated test authority, not authenticated human approval, customer policy,
financial guidance, production acceptance or a claim of live catalogue access.
The engineer receives this input directory; independent expected exports and
acceptance queries are withheld. Do not read a sibling oracle or candidate output.

## Scope and source bindings

Build exactly five enabled models in dependency order: `stg_rentals`,
`stg_charges`, `stg_locations`, `int_eligible_charges`, `fct_rental_revenue`.
The three raw CSV relations are dbt seeds bound in `catalogue.json`; reference
those exact seed names with `ref`. Preserve all seed bytes and the input source.
Use native SQL compatible with Snowflake and DuckDB, no external packages,
custom macros, hooks, incremental state, snapshots or adapter-specific syntax.
The host supplies an isolated profile named `rental_trial`. Maintain the project
name/profile and explicit seed types in `dbt_project.yml`.

All source rows are at or before the fixed watermark `2026-08-16T00:00:00Z`.
All timestamps and rental dates represent UTC; timestamps are canonical sortable
VARCHAR values, not session-timezone timestamps. Currency is USD throughout.
IDs are strings and local to each tenant. The synthetic source guarantees
non-null keys, nonnegative source charge amounts, supported charge/status values,
and currency equality between a rental and its tenant-matched charges. A charge
may reference a deleted rental; such a charge remains in staging but is not
eligible revenue. Live rentals in this fixture all have live matching locations.

## Accepted rules

- **R-CDC:** Each staging model has one latest live row per entity key: tenant
  plus rental ID, charge ID, or location ID. Order the complete source history by
  descending `cdc_sequence`, then descending `updated_at`. Exact replicated
  versions are equivalent; do not add their values. Conflicting payloads at the
  same sequence/timestamp are outside this fixture. Choose the latest version
  before excluding `is_deleted = true`; never resurrect an older live version.
- **R-TENANT:** Every partition, entity key and relationship includes `tenant_id`.
  Charge-to-rental joins use `(tenant_id, rental_id)` and rental-to-location joins
  use `(tenant_id, location_id)`. IDs repeat across tenants intentionally.
- **R-HISTORY:** This is a current-state snapshot at the supplied watermark, not
  an as-of or slowly changing dimension. Staging retains live cancelled rentals.
  Location labels are the latest live labels, including for older rental dates.
  Do not carry obsolete statuses, source versions or labels into the mart.
- **R-ELIGIBLE:** Only live rentals with `rental_status = 'completed'` enter the
  gold mart. Eligible charges must belong to those rentals in the same tenant
  and currency. Include only `rental_fee`, `damage_fee`, and `refund` charge types.
  `refundable_deposit` is a liability and contributes neither revenue nor the
  eligible charge count. Cancelled, active and deleted rentals contribute no
  gold row and no eligible charges. Deleted charges contribute no revenue.
- **R-SIGN:** Raw `amount` is a nonnegative magnitude. Rental and damage fees
  keep the positive amount. A refund is exactly negative `amount`, even though
  the raw magnitude is positive. Use fixed-precision DECIMAL(18,2), no float or
  integer division. Gold `refund_amount` is negative or zero; `fee_amount` is
  nonnegative. `net_revenue = fee_amount + refund_amount`.
- **R-ZERO:** Completed live rentals with no eligible charges still have exactly
  one gold row with decimal zero for all three amounts and integer zero for
  `eligible_charge_count`. Count actual eligible charge IDs, not outer-join rows.
- **R-GRAIN:** Aggregate eligible charges to `(tenant_id, rental_id)` before or
  equivalently without multiplicative joins to rentals and current locations.
  Gold has exactly one row per live completed rental, with no report aggregation.
- **R-SEMANTIC:** Reusable CDC cleanup, tenant joins, eligibility and signed
  transaction amounts belong upstream. Omni keeps tenant authorization/persona,
  rental-date/status/location report filters, currency presentation and the
  `sum(net_revenue)` metric over gold. No tenant or report-date selection is
  baked into reusable SQL. Gold exposes tenant IDs; this alone is not enforced
  row-level security. A denied-persona acceptance query is a query-filter probe,
  not proof of Omni authentication or warehouse access-policy enforcement.

## Exact model contracts

Column names and types are part of the accepted output contract. All columns are
non-null for this fixture. Staging drops `is_deleted` after tombstone handling and
retains the latest CDC metadata for audit. ID/text/date/timestamp fields below are
VARCHAR, sequences/counts are integers, and monetary fields DECIMAL(18,2).

| Model | Grain/key | Exact output columns, in preferred order |
|---|---|---|
| stg_rentals | tenant_id + rental_id | tenant_id, rental_id, location_id, rental_status, rental_date, currency, updated_at, cdc_sequence |
| stg_charges | tenant_id + charge_id | tenant_id, charge_id, rental_id, charge_type, amount, currency, updated_at, cdc_sequence |
| stg_locations | tenant_id + location_id | tenant_id, location_id, location_name, updated_at, cdc_sequence |
| int_eligible_charges | tenant_id + charge_id | tenant_id, charge_id, rental_id, charge_type, currency, source_amount, signed_amount |
| fct_rental_revenue | tenant_id + rental_id | tenant_id, rental_id, location_id, location_name, rental_status, rental_date, currency, fee_amount, refund_amount, net_revenue, eligible_charge_count |

## Legacy compatibility and changes

`models/legacy_report.sql` is intentionally a flawed historical observation, not
business truth. It combines replicated versions, omits tenant predicates,
retains tombstones, uses obsolete location labels, drops zero-charge rentals,
includes deposits and adds refund magnitudes. Tenant C / rental R9 is a clean
compatibility slice with a unique rental and location, one charge, and no CDC
updates; its shared report columns should continue to match the source report.
Other changes follow `SYNTHETIC-RENTAL-DECISION-001` and are accepted corrections.
Remove the old report from enabled model resources. Write the downstream report
query to `analyses/legacy_report.sql`, referencing gold; document the corrections.

## Tests and documentation

Provide singular tests in `tests/grain.sql` and `tests/tenant_integrity.sql` and
schema descriptions/tests in `models/schema.yml`. Tests must inspect composite
grains and same-tenant relationships, including eligible charge relationships
and gold source keys; do not encode withheld expected amounts. Tests that assume
global ID uniqueness are wrong. A staged charge with a deleted parent is allowed;
an eligible charge with a missing/completed-status/tenant-mismatched parent is not.

Write the five-model ERD, a readable data dictionary plus canonical JSON dictionary,
and bronze/silver/gold documents at the exact owned paths in `model-spec.json`.
Dictionary JSON must enumerate model IDs, grain, keys, columns/types, dependencies,
rule IDs, history and tenant relationships. Bronze documents the three immutable
raw sources; silver covers all three staging models and the intermediate; gold
covers the fact. Include lineage, CDC and semantic placement. Write
`semantic/omni-contract.md` with the downstream metric, filters and persona
contract plus the explicit unverified-live-Omni limitation. No deployment or
production/GA claims follow from this local synthetic exercise.
