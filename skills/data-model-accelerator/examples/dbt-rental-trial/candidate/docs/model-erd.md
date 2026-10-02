# Rental model relationships and lineage

Authority: **synthetic** `SYNTHETIC-RENTAL-DECISION-001`. This documents the local trial, not a live warehouse or Omni deployment. Keys shown below are composite; no bare entity ID is globally unique. All fields are non-null in the supplied fixture; the complete eight-relation column inventory is in [the dictionary](data-dictionary.md).

```mermaid
erDiagram
    stg_locations ||--o{ stg_rentals : "tenant_id + location_id"
    stg_rentals o|--o{ stg_charges : "tenant_id + rental_id; deleted parent allowed"
    stg_charges ||--o| int_eligible_charges : "tenant_id + charge_id; eligible subset"
    stg_rentals ||--o{ int_eligible_charges : "tenant_id + rental_id; completed and same currency"
    stg_rentals ||--o| fct_rental_revenue : "tenant_id + rental_id; completed subset"
    stg_locations ||--o{ fct_rental_revenue : "tenant_id + location_id; current label"
    fct_rental_revenue ||--o{ int_eligible_charges : "tenant_id + rental_id; aggregate charges first"
    stg_rentals {
        varchar tenant_id PK
        varchar rental_id PK
        varchar location_id FK
        varchar rental_status
        varchar rental_date
        varchar currency
        varchar updated_at
        bigint cdc_sequence
    }
    stg_charges {
        varchar tenant_id PK
        varchar charge_id PK
        varchar rental_id FK
        varchar charge_type
        decimal amount
        varchar currency
        varchar updated_at
        bigint cdc_sequence
    }
    stg_locations {
        varchar tenant_id PK
        varchar location_id PK
        varchar location_name
        varchar updated_at
        bigint cdc_sequence
    }
    int_eligible_charges {
        varchar tenant_id PK
        varchar charge_id PK
        varchar rental_id FK
        varchar charge_type
        varchar currency
        decimal source_amount
        decimal signed_amount
    }
    fct_rental_revenue {
        varchar tenant_id PK
        varchar rental_id PK
        varchar location_id FK
        varchar location_name
        varchar rental_status
        varchar rental_date
        varchar currency
        decimal fee_amount
        decimal refund_amount
        decimal net_revenue
        bigint eligible_charge_count
    }
```

The arrows above express logical relationships, not enforced database foreign keys. In particular, `tenant_id` participates in every marked foreign key even where Mermaid displays the entity ID separately. All `decimal` fields are `DECIMAL(18,2)`.

| Immutable source | Current-state staging | Further dependency |
|---|---|---|
| `ref('raw_rentals')` | `stg_rentals` | `int_eligible_charges`, `fct_rental_revenue` |
| `ref('raw_charges')` | `stg_charges` | `int_eligible_charges` → `fct_rental_revenue` |
| `ref('raw_locations')` | `stg_locations` | `fct_rental_revenue` |

Each raw relation retains replicated CDC events. Staging ranks by descending sequence and timestamp before filtering tombstones. The snapshot watermark is `2026-08-16T00:00:00Z`; current location labels replace older labels even for older rental dates. No SCD/as-of history is implied.

The gold-to-charge relationship describes the analytical grain, not a reverse dbt dependency: the fact depends on intermediate charges aggregated by the composite rental key. Completed rentals may have zero eligible charges and still appear once in gold.

Recover by restoring catalogue-verified raw CSVs and rebuilding all five tables, then rerunning schema, grain and tenant checks. Composite joins do not enforce tenant authentication or RLS; see [the Omni contract](../semantic/omni-contract.md).
