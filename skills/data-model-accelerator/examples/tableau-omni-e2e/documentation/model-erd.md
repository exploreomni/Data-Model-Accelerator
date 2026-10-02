# Tableau billing model: conceptual and physical layer views

These editable diagrams cover all **10 physical models**. The [inventory](model-inventory.json) and [dictionary](data-dictionary.md) enumerate all **64 columns**. Arrows represent proposed logical relationships or transformations, never proof of physically enforced keys or production ingestion. Candidate DDL and CTAS emit no enforced PK/FK/NOT NULL constraints.

## Conceptual and logical model

```mermaid
erDiagram
  CUSTOMER_HISTORY ||--o{ INVOICE : "tenant/customer and invoice-date interval"
  INVOICE ||--o{ PAYMENT : "same tenant and invoice"
  INVOICE ||--o| ADJUSTMENT : "same tenant and invoice"
  CUSTOMER_HISTORY {
    string tenant_id
    string customer_id
    date valid_from
    date valid_to "exclusive, nullable"
    string segment
  }
  INVOICE {
    string tenant_id
    string invoice_id
    date invoice_date
    int net_cents
    int paid_cents
    int outstanding_cents
  }
  PAYMENT {
    string tenant_id
    string payment_id
    string invoice_id
    int paid_cents
  }
  ADJUSTMENT {
    string tenant_id
    string invoice_id
    int adjustment_cents
  }
```

Current invoice identity is tenant/invoice; current payment identity is tenant/payment. Every current payment/adjustment must reference a current invoice in the same tenant. An invoice requires exactly one historical customer match at `invoice_date >= valid_from AND (invoice_date < valid_to OR valid_to IS NULL)` within the same tenant/customer. A missing or overlapping match fails rather than introducing an Unknown member.

## Bronze physical responsibilities

```mermaid
flowchart LR
  CAPTURE["input/raw-data.json<br/>invented capture"] --> RI["DMA_TABLEAU.RAW.INVOICE_CDC<br/>versioned event occurrences"]
  CAPTURE --> RP["DMA_TABLEAU.RAW.PAYMENT_CDC<br/>versioned event occurrences"]
  CAPTURE --> RH["DMA_TABLEAU.RAW.CUSTOMER_HISTORY<br/>history occurrences"]
  CSV["input/repo/adjustments.csv<br/>separate source receipt"] -->|"proposed governed landing"| RA["DMA_TABLEAU.RAW.ADJUSTMENTS<br/>tenant/invoice correction"]
```

The arrows are a source contract, not a demonstrated connector. RAW implements bronze without another copied layer. Dates are physically VARCHAR at the declared raw boundary. CDC/history allow exact replay; adjustment duplicate keys are errors.

## Silver physical transformations

```mermaid
flowchart LR
  RI["DMA_TABLEAU.RAW.INVOICE_CDC"] -->|"highest sequence then tombstone; casts/status"| SI["DMA_TABLEAU.SILVER.BILLING_INVOICES<br/>tenant/invoice"]
  RP["DMA_TABLEAU.RAW.PAYMENT_CDC"] -->|"highest sequence then tombstone; casts"| SP["DMA_TABLEAU.SILVER.BILLING_PAYMENTS<br/>tenant/payment"]
  RH["DMA_TABLEAU.RAW.CUSTOMER_HISTORY"] -->|"complete DISTINCT; date casts"| SH["DMA_TABLEAU.SILVER.BILLING_CUSTOMER_HISTORY<br/>tenant/customer/valid-from"]
  RA["DMA_TABLEAU.RAW.ADJUSTMENTS"] -->|"strict signed cents; no duplicate collapse"| SA["DMA_TABLEAU.SILVER.BILLING_ADJUSTMENTS<br/>tenant/invoice"]
```

Source conflicts, missing keys, invalid dates and overlap fail before model promotion. Current source grain remains independent of worksheet filters, FIXED scope, share partition and multiplier.

## Gold physical and query-time dependencies

```mermaid
flowchart LR
  SH["DMA_TABLEAU.SILVER.BILLING_CUSTOMER_HISTORY"] --> D["DMA_TABLEAU.GOLD.DIM_CUSTOMERS<br/>tenant|customer|valid-from"]
  SI["DMA_TABLEAU.SILVER.BILLING_INVOICES"] --> F["DMA_TABLEAU.GOLD.FCT_INVOICES<br/>tenant|invoice"]
  SP["DMA_TABLEAU.SILVER.BILLING_PAYMENTS"] -->|"SUM per tenant/invoice before join"| F
  SA["DMA_TABLEAU.SILVER.BILLING_ADJUSTMENTS"] -->|"0..1 correction; tenant/invoice"| F
  D -->|"exactly one tenant/customer/date match"| F
  F --> CONTEXT["Query tenant + posted + date context"]
  CONTEXT --> LOD["FIXED tenant/customer SUM net<br/>query-time, no segment filter"]
  CONTEXT --> MARKS["Segment filter then view marks"]
  LOD -->|"MIN of repeated value per mark"| MARKS
  MARKS --> SHARE["Share: partition month/address segment<br/>after selected-mark aggregation"]
  MARKS --> WHATIF["Scenario revenue: mark net × multiplier"]
```

Only DIM_CUSTOMERS and FCT_INVOICES are gold physical tables. The query-time boxes deliberately are not warehouse models. The customer FIXED calculation retains context and does not become an all-time materialized total. Share and scenario multiplier are presentation behavior. Segment-sensitive customer value, grand totals, limits, densification, actions and native rendering require separate qualification.
