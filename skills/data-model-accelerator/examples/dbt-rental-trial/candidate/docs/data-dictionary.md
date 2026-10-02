# Rental billing data dictionary

Canonical companion: [data-dictionary.json](data-dictionary.json). All eight relations and every column are listed below. Authority is **synthetic** `SYNTHETIC-RENTAL-DECISION-001`; this is not customer policy, live catalogue evidence or production acceptance.

Watermark: `2026-08-16T00:00:00Z`. UTC dates and timestamps are canonical sortable VARCHAR values. All columns are non-null under the fixture contract. Monetary values are USD `DECIMAL(18,2)`; sequences and counts are `BIGINT`. No floating-point arithmetic is used.

Every key is tenant-scoped. Tenant IDs and correct joins prevent analytical mixing but do not enforce tenant authorization. All tables are fully rebuilt; no incremental history or SCD is provided.

## raw_rentals (bronze)

replicated CDC event for (tenant_id, rental_id); multiple versions and exact replay duplicates are allowed

**Key:** tenant_id, rental_id. **Unique:** no; repeated source events are allowed. **Dependencies:** immutable CSV only. **Rules:** R-CDC, R-TENANT, R-HISTORY.

Immutable replicated CDC history through 2026-08-16T00:00:00Z; multiple versions, tombstones and exact replay duplicates retained. Entity keys are not unique event keys.

| Column | Type | Nullable | Meaning / lineage |
|---|---|---|---|
| tenant_id | VARCHAR | No | Tenant boundary; required in every key, partition and relationship. Exposing it does not enforce authorization. Lineage: immutable seeds/raw_rentals.csv:tenant_id. |
| rental_id | VARCHAR | No | Rental identifier local to a tenant. Lineage: immutable seeds/raw_rentals.csv:rental_id. |
| location_id | VARCHAR | No | Location identifier local to a tenant. Lineage: immutable seeds/raw_rentals.csv:location_id. |
| rental_status | VARCHAR | No | Current source status; completed is required for revenue eligibility. Lineage: immutable seeds/raw_rentals.csv:rental_status. |
| rental_date | VARCHAR | No | UTC rental date represented as a canonical VARCHAR; used for downstream reporting filters. Lineage: immutable seeds/raw_rentals.csv:rental_date. |
| currency | VARCHAR | No | Currency code; USD in this fixture. Eligible charge and rental currencies must agree. Lineage: immutable seeds/raw_rentals.csv:currency. |
| updated_at | VARCHAR | No | Canonical sortable UTC timestamp VARCHAR; secondary descending CDC ordering field. Lineage: immutable seeds/raw_rentals.csv:updated_at. |
| cdc_sequence | BIGINT | No | Integer CDC sequence; primary descending CDC ordering field. Lineage: immutable seeds/raw_rentals.csv:cdc_sequence. |
| is_deleted | BOOLEAN | No | Source tombstone flag; evaluate only after selecting the latest entity version. Lineage: immutable seeds/raw_rentals.csv:is_deleted. |

**Tenant relationships:**
- `(tenant_id, location_id)` → `raw_locations(tenant_id, location_id)`. Logical source relationship only; resolve latest live versions before analytical joins. Deleted rental parents may remain referenced by charges..

**Recovery:** Restore the original CSV bytes and verify the catalogue SHA-256 before reseeding and rebuilding downstream tables.

## raw_charges (bronze)

replicated CDC event for (tenant_id, charge_id); multiple versions and exact replay duplicates are allowed

**Key:** tenant_id, charge_id. **Unique:** no; repeated source events are allowed. **Dependencies:** immutable CSV only. **Rules:** R-CDC, R-TENANT, R-HISTORY.

Immutable replicated CDC history through 2026-08-16T00:00:00Z; multiple versions, tombstones and exact replay duplicates retained. Entity keys are not unique event keys.

| Column | Type | Nullable | Meaning / lineage |
|---|---|---|---|
| tenant_id | VARCHAR | No | Tenant boundary; required in every key, partition and relationship. Exposing it does not enforce authorization. Lineage: immutable seeds/raw_charges.csv:tenant_id. |
| charge_id | VARCHAR | No | Charge identifier local to a tenant. Lineage: immutable seeds/raw_charges.csv:charge_id. |
| rental_id | VARCHAR | No | Rental identifier local to a tenant. Lineage: immutable seeds/raw_charges.csv:rental_id. |
| charge_type | VARCHAR | No | Source category: rental_fee, damage_fee, refund or refundable_deposit. Deposits are excluded from eligible revenue. Lineage: immutable seeds/raw_charges.csv:charge_type. |
| amount | DECIMAL(18,2) | No | Nonnegative source magnitude in USD with fixed decimal precision; refunds are not signed at source. Lineage: immutable seeds/raw_charges.csv:amount. |
| currency | VARCHAR | No | Currency code; USD in this fixture. Eligible charge and rental currencies must agree. Lineage: immutable seeds/raw_charges.csv:currency. |
| updated_at | VARCHAR | No | Canonical sortable UTC timestamp VARCHAR; secondary descending CDC ordering field. Lineage: immutable seeds/raw_charges.csv:updated_at. |
| cdc_sequence | BIGINT | No | Integer CDC sequence; primary descending CDC ordering field. Lineage: immutable seeds/raw_charges.csv:cdc_sequence. |
| is_deleted | BOOLEAN | No | Source tombstone flag; evaluate only after selecting the latest entity version. Lineage: immutable seeds/raw_charges.csv:is_deleted. |

**Tenant relationships:**
- `(tenant_id, rental_id)` → `raw_rentals(tenant_id, rental_id)`. Logical source relationship only; resolve latest live versions before analytical joins. Deleted rental parents may remain referenced by charges..

**Recovery:** Restore the original CSV bytes and verify the catalogue SHA-256 before reseeding and rebuilding downstream tables.

## raw_locations (bronze)

replicated CDC event for (tenant_id, location_id); multiple versions and exact replay duplicates are allowed

**Key:** tenant_id, location_id. **Unique:** no; repeated source events are allowed. **Dependencies:** immutable CSV only. **Rules:** R-CDC, R-TENANT, R-HISTORY.

Immutable replicated CDC history through 2026-08-16T00:00:00Z; multiple versions, tombstones and exact replay duplicates retained. Entity keys are not unique event keys.

| Column | Type | Nullable | Meaning / lineage |
|---|---|---|---|
| tenant_id | VARCHAR | No | Tenant boundary; required in every key, partition and relationship. Exposing it does not enforce authorization. Lineage: immutable seeds/raw_locations.csv:tenant_id. |
| location_id | VARCHAR | No | Location identifier local to a tenant. Lineage: immutable seeds/raw_locations.csv:location_id. |
| location_name | VARCHAR | No | Current live location label; not the historical label at rental time. Lineage: immutable seeds/raw_locations.csv:location_name. |
| updated_at | VARCHAR | No | Canonical sortable UTC timestamp VARCHAR; secondary descending CDC ordering field. Lineage: immutable seeds/raw_locations.csv:updated_at. |
| cdc_sequence | BIGINT | No | Integer CDC sequence; primary descending CDC ordering field. Lineage: immutable seeds/raw_locations.csv:cdc_sequence. |
| is_deleted | BOOLEAN | No | Source tombstone flag; evaluate only after selecting the latest entity version. Lineage: immutable seeds/raw_locations.csv:is_deleted. |

**Tenant relationships:**
- No parent relationship; entity key remains tenant-scoped.

**Recovery:** Restore the original CSV bytes and verify the catalogue SHA-256 before reseeding and rebuilding downstream tables.

## stg_rentals (silver)

One latest live row per (tenant_id, rental_id).

**Key:** tenant_id, rental_id. **Unique:** yes. **Dependencies:** seed.rental_trial.raw_rentals. **Rules:** R-CDC, R-TENANT, R-HISTORY.

Latest live current-state snapshot at the fixed watermark; rank all versions by cdc_sequence DESC, updated_at DESC, then exclude tombstones. Exact duplicate versions are equivalent. CDC metadata retained; is_deleted removed. No as-of history or SCD.

| Column | Type | Nullable | Meaning / lineage |
|---|---|---|---|
| tenant_id | VARCHAR | No | Tenant boundary; required in every key, partition and relationship. Exposing it does not enforce authorization. Lineage: raw_rentals.tenant_id, latest entity version before tombstone exclusion. |
| rental_id | VARCHAR | No | Rental identifier local to a tenant. Lineage: raw_rentals.rental_id, latest entity version before tombstone exclusion. |
| location_id | VARCHAR | No | Location identifier local to a tenant. Lineage: raw_rentals.location_id, latest entity version before tombstone exclusion. |
| rental_status | VARCHAR | No | Current source status; completed is required for revenue eligibility. Lineage: raw_rentals.rental_status, latest entity version before tombstone exclusion. |
| rental_date | VARCHAR | No | UTC rental date represented as a canonical VARCHAR; used for downstream reporting filters. Lineage: raw_rentals.rental_date, latest entity version before tombstone exclusion. |
| currency | VARCHAR | No | Currency code; USD in this fixture. Eligible charge and rental currencies must agree. Lineage: raw_rentals.currency, latest entity version before tombstone exclusion. |
| updated_at | VARCHAR | No | Canonical sortable UTC timestamp VARCHAR; secondary descending CDC ordering field. Lineage: raw_rentals.updated_at, latest entity version before tombstone exclusion. |
| cdc_sequence | BIGINT | No | Integer CDC sequence; primary descending CDC ordering field. Lineage: raw_rentals.cdc_sequence, latest entity version before tombstone exclusion. |

**Tenant relationships:**
- `(tenant_id, location_id)` → `stg_locations(tenant_id, location_id)`. tests/tenant_integrity.sql; live parent location is a fixture guarantee.

**Recovery:** Rebuild from immutable seeds after correcting the source/logic; rerun schema, grain and tenant integrity tests before consuming results. No incremental state, rollback ledger or production deployment is supplied.

## stg_charges (silver)

One latest live row per (tenant_id, charge_id).

**Key:** tenant_id, charge_id. **Unique:** yes. **Dependencies:** seed.rental_trial.raw_charges. **Rules:** R-CDC, R-TENANT, R-HISTORY.

Latest live current-state snapshot at the fixed watermark; rank all versions by cdc_sequence DESC, updated_at DESC, then exclude tombstones. Exact duplicate versions are equivalent. CDC metadata retained; is_deleted removed. No as-of history or SCD.

| Column | Type | Nullable | Meaning / lineage |
|---|---|---|---|
| tenant_id | VARCHAR | No | Tenant boundary; required in every key, partition and relationship. Exposing it does not enforce authorization. Lineage: raw_charges.tenant_id, latest entity version before tombstone exclusion. |
| charge_id | VARCHAR | No | Charge identifier local to a tenant. Lineage: raw_charges.charge_id, latest entity version before tombstone exclusion. |
| rental_id | VARCHAR | No | Rental identifier local to a tenant. Lineage: raw_charges.rental_id, latest entity version before tombstone exclusion. |
| charge_type | VARCHAR | No | Source category: rental_fee, damage_fee, refund or refundable_deposit. Deposits are excluded from eligible revenue. Lineage: raw_charges.charge_type, latest entity version before tombstone exclusion. |
| amount | DECIMAL(18,2) | No | Nonnegative source magnitude in USD with fixed decimal precision; refunds are not signed at source. Lineage: raw_charges.amount, latest entity version before tombstone exclusion. |
| currency | VARCHAR | No | Currency code; USD in this fixture. Eligible charge and rental currencies must agree. Lineage: raw_charges.currency, latest entity version before tombstone exclusion. |
| updated_at | VARCHAR | No | Canonical sortable UTC timestamp VARCHAR; secondary descending CDC ordering field. Lineage: raw_charges.updated_at, latest entity version before tombstone exclusion. |
| cdc_sequence | BIGINT | No | Integer CDC sequence; primary descending CDC ordering field. Lineage: raw_charges.cdc_sequence, latest entity version before tombstone exclusion. |

**Tenant relationships:**
- `(tenant_id, rental_id)` → `stg_rentals(tenant_id, rental_id)`. No mandatory live-parent test at staging: deleted rental parents are allowed.

**Recovery:** Rebuild from immutable seeds after correcting the source/logic; rerun schema, grain and tenant integrity tests before consuming results. No incremental state, rollback ledger or production deployment is supplied.

## stg_locations (silver)

One latest live row per (tenant_id, location_id).

**Key:** tenant_id, location_id. **Unique:** yes. **Dependencies:** seed.rental_trial.raw_locations. **Rules:** R-CDC, R-TENANT, R-HISTORY.

Latest live current-state snapshot at the fixed watermark; rank all versions by cdc_sequence DESC, updated_at DESC, then exclude tombstones. Exact duplicate versions are equivalent. CDC metadata retained; is_deleted removed. No as-of history or SCD.

| Column | Type | Nullable | Meaning / lineage |
|---|---|---|---|
| tenant_id | VARCHAR | No | Tenant boundary; required in every key, partition and relationship. Exposing it does not enforce authorization. Lineage: raw_locations.tenant_id, latest entity version before tombstone exclusion. |
| location_id | VARCHAR | No | Location identifier local to a tenant. Lineage: raw_locations.location_id, latest entity version before tombstone exclusion. |
| location_name | VARCHAR | No | Current live location label; not the historical label at rental time. Lineage: raw_locations.location_name, latest entity version before tombstone exclusion. |
| updated_at | VARCHAR | No | Canonical sortable UTC timestamp VARCHAR; secondary descending CDC ordering field. Lineage: raw_locations.updated_at, latest entity version before tombstone exclusion. |
| cdc_sequence | BIGINT | No | Integer CDC sequence; primary descending CDC ordering field. Lineage: raw_locations.cdc_sequence, latest entity version before tombstone exclusion. |

**Tenant relationships:**
- No parent relationship; entity key remains tenant-scoped.

**Recovery:** Rebuild from immutable seeds after correcting the source/logic; rerun schema, grain and tenant integrity tests before consuming results. No incremental state, rollback ledger or production deployment is supplied.

## int_eligible_charges (silver)

One current eligible charge per (tenant_id, charge_id), belonging to a completed live same-tenant rental.

**Key:** tenant_id, charge_id. **Unique:** yes. **Dependencies:** stg_rentals, stg_charges. **Rules:** R-ELIGIBLE, R-SIGN, R-TENANT.

Current live eligible charges only; no independent history or CDC metadata. Refund signs and deposit exclusion reflect synthetic accepted rules.

| Column | Type | Nullable | Meaning / lineage |
|---|---|---|---|
| tenant_id | VARCHAR | No | Tenant boundary; required in every key, partition and relationship. Exposing it does not enforce authorization. Lineage: stg_charges.tenant_id; same-tenant/currency completed stg_rentals required. |
| charge_id | VARCHAR | No | Charge identifier local to a tenant. Lineage: stg_charges.charge_id; same-tenant/currency completed stg_rentals required. |
| rental_id | VARCHAR | No | Rental identifier local to a tenant. Lineage: stg_charges.rental_id; same-tenant/currency completed stg_rentals required. |
| charge_type | VARCHAR | No | Source category: rental_fee, damage_fee, refund or refundable_deposit. Deposits are excluded from eligible revenue. Lineage: stg_charges.charge_type; same-tenant/currency completed stg_rentals required. |
| currency | VARCHAR | No | Currency code; USD in this fixture. Eligible charge and rental currencies must agree. Lineage: stg_charges.currency; same-tenant/currency completed stg_rentals required. |
| source_amount | DECIMAL(18,2) | No | Unmodified nonnegative magnitude from the current live source charge. Lineage: stg_charges.amount. |
| signed_amount | DECIMAL(18,2) | No | Source amount for rental/damage fees, negative source amount for refunds; deposits are absent. Lineage: stg_charges.amount; refund sign applied. |

**Tenant relationships:**
- `(tenant_id, charge_id)` → `stg_charges(tenant_id, charge_id)`. tests/tenant_integrity.sql.
- `(tenant_id, rental_id)` → `stg_rentals(tenant_id, rental_id)`. SQL join and tests/tenant_integrity.sql.

**Recovery:** Rebuild from immutable seeds after correcting the source/logic; rerun schema, grain and tenant integrity tests before consuming results. No incremental state, rollback ledger or production deployment is supplied.

## fct_rental_revenue (gold)

Exactly one row per completed live rental (tenant_id, rental_id), before downstream report aggregation.

**Key:** tenant_id, rental_id. **Unique:** yes. **Dependencies:** stg_rentals, stg_locations, int_eligible_charges. **Rules:** R-ELIGIBLE, R-ZERO, R-GRAIN, R-TENANT, R-HISTORY, R-SEMANTIC.

Current-state rental snapshot using current live locations, including for older rental dates. No historical label/status preservation or as-of reconstruction. Completed live rentals without charges remain as zero-valued rows.

| Column | Type | Nullable | Meaning / lineage |
|---|---|---|---|
| tenant_id | VARCHAR | No | Tenant boundary; required in every key, partition and relationship. Exposing it does not enforce authorization. Lineage: stg_rentals.tenant_id; completed live rentals only. |
| rental_id | VARCHAR | No | Rental identifier local to a tenant. Lineage: stg_rentals.rental_id; completed live rentals only. |
| location_id | VARCHAR | No | Location identifier local to a tenant. Lineage: stg_rentals.location_id; completed live rentals only. |
| location_name | VARCHAR | No | Current live location label; not the historical label at rental time. Lineage: stg_locations.location_name joined on tenant_id + location_id; current label. |
| rental_status | VARCHAR | No | Current source status; completed is required for revenue eligibility. Lineage: stg_rentals.rental_status; completed live rentals only. |
| rental_date | VARCHAR | No | UTC rental date represented as a canonical VARCHAR; used for downstream reporting filters. Lineage: stg_rentals.rental_date; completed live rentals only. |
| currency | VARCHAR | No | Currency code; USD in this fixture. Eligible charge and rental currencies must agree. Lineage: stg_rentals.currency; completed live rentals only. |
| fee_amount | DECIMAL(18,2) | No | Sum of eligible rental and damage fees for this rental, decimal zero when none. Lineage: sum(int_eligible_charges.signed_amount) for rental_fee/damage_fee per tenant_id + rental_id; zero if none. |
| refund_amount | DECIMAL(18,2) | No | Sum of signed eligible refunds for this rental; negative or decimal zero. Lineage: sum(int_eligible_charges.signed_amount) for refund per tenant_id + rental_id; zero if none. |
| net_revenue | DECIMAL(18,2) | No | fee_amount + refund_amount, fixed DECIMAL(18,2); downstream revenue metric sums this field. Lineage: fee_amount + refund_amount. |
| eligible_charge_count | BIGINT | No | Count of actual eligible charge IDs at rental grain, integer zero when none; deposits are excluded. Lineage: count(int_eligible_charges.charge_id) per tenant_id + rental_id; zero if none. |

**Tenant relationships:**
- `(tenant_id, rental_id)` → `stg_rentals(tenant_id, rental_id)`. tests/tenant_integrity.sql checks source keys and complete coverage.
- `(tenant_id, location_id)` → `stg_locations(tenant_id, location_id)`. SQL join and tests/tenant_integrity.sql.
- `(tenant_id, rental_id)` → `int_eligible_charges(tenant_id, rental_id)`. Charges aggregate to this composite rental key before the left join.

**Recovery:** Rebuild from immutable seeds after correcting the source/logic; rerun schema, grain and tenant integrity tests before consuming results. No incremental state, rollback ledger or production deployment is supplied.
