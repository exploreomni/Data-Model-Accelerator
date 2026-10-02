# Power BI billing model ERD

The inventory covers **10 physical models and 64 columns**. These editable diagrams show proposed transformations and logical relationships. No arrow asserts enforced foreign keys, native RLS or a demonstrated source loader. [Dictionary](data-dictionary.md) and [inventory](model-inventory.json) are the complete column denominator.

## Logical identities and cardinality

```mermaid
erDiagram
  EFFECTIVE_CUSTOMER ||--o{ INVOICE : "tenant/customer and half-open invoice-date match"
  INVOICE ||--o{ PAYMENT : "tenant/invoice"
  INVOICE ||--o| ADJUSTMENT : "tenant/invoice"
  EFFECTIVE_CUSTOMER {
    string tenant_id
    string customer_id
    date valid_from
    date valid_to "exclusive; null open"
    string customer_key "tenant|customer|start"
    string segment
  }
  INVOICE {
    string tenant_id
    string invoice_id
    string invoice_key "tenant|invoice"
    date invoice_date
    string customer_key
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

An invoice requires exactly one same-tenant effective customer: `invoice_date >= valid_from AND (invoice_date < valid_to OR valid_to IS NULL)`. No match or overlapping matches fail rather than producing Unknown or fanout. Payment and adjustment references must target a current invoice; an invoice may have zero payments or no adjustment. Fixture key components exclude pipes. Natural identities are tenant/invoice, tenant/payment and tenant/customer/valid-from; surrogate strings are convenience encodings, not production collision guarantees.

## Bronze objects

```mermaid
flowchart LR
  SNAP["input/raw-data.json<br/>synthetic capture"] --> RI["DMA_POWERBI.RAW.INVOICE_CDC<br/>invoice version occurrence"]
  SNAP --> RP["DMA_POWERBI.RAW.PAYMENT_CDC<br/>payment version occurrence"]
  SNAP --> RH["DMA_POWERBI.RAW.CUSTOMER_HISTORY<br/>effective history occurrence"]
  CSV["input/repo/adjustments.csv"] -->|"proposed governed landing"| RA["DMA_POWERBI.RAW.ADJUSTMENTS<br/>tenant/invoice correction"]
```

RAW dates are VARCHAR; number precision follows the candidate DDL. CDC/history exact replays may repeat at this boundary. Adjustment duplicate keys are invalid. Ingestion arrows are declarations, not connector evidence.

## Silver objects

```mermaid
flowchart LR
  RI["DMA_POWERBI.RAW.INVOICE_CDC"] -->|"rank by sequence before delete; cast"| SI["DMA_POWERBI.SILVER.BILLING_INVOICES<br/>tenant/invoice"]
  RP["DMA_POWERBI.RAW.PAYMENT_CDC"] -->|"rank before delete; cast"| SP["DMA_POWERBI.SILVER.BILLING_PAYMENTS<br/>tenant/payment"]
  RH["DMA_POWERBI.RAW.CUSTOMER_HISTORY"] -->|"complete DISTINCT; dates"| SH["DMA_POWERBI.SILVER.BILLING_CUSTOMER_HISTORY<br/>tenant/customer/valid-from"]
  RA["DMA_POWERBI.RAW.ADJUSTMENTS"] -->|"strict signed cents; no duplicate collapse"| SA["DMA_POWERBI.SILVER.BILLING_ADJUSTMENTS<br/>tenant/invoice"]
```

Same-version conflicts are rejected before ranking. Report filters, DAX context modifiers and disconnected Scenario selections do not change these current-state grains.

## Gold and downstream query boundaries

```mermaid
flowchart LR
  SH["DMA_POWERBI.SILVER.BILLING_CUSTOMER_HISTORY"] --> D["DMA_POWERBI.GOLD.DIM_CUSTOMERS<br/>tenant/customer/valid-from"]
  SI["DMA_POWERBI.SILVER.BILLING_INVOICES"] --> F["DMA_POWERBI.GOLD.FCT_INVOICES<br/>tenant/invoice"]
  SP["DMA_POWERBI.SILVER.BILLING_PAYMENTS"] -->|"SUM tenant/invoice before join"| F
  SA["DMA_POWERBI.SILVER.BILLING_ADJUSTMENTS"] -->|"optional correction; tenant/invoice"| F
  D -->|"exactly one effective row"| F
  D --> SEC["Both customer and invoice tenant scopes"]
  F --> SEC
  SEC --> BASE["Ordinary date, segment, status context"]
  BASE --> SUMS["Selected sums and ratio"]
  BASE --> ALL["Remove only segment grouping/filter<br/>retain date, month, status, security"]
  BASE --> POST["Replace status with posted OR intersect posted<br/>distinct measures"]
  SUMS --> KPI["Recomputed KPI: one row, BLANK aware"]
  ALL --> KPI
  POST --> KPI
  SUMS --> SCENARIO["Disconnected selection: sole multiplier else 1<br/>downstream presentation"]
```

Only the two gold table boxes are warehouse models. The source Scenario table is disconnected; it contributes no warehouse join. Source Customers Segment propagates through the active many-to-one effective key; target report dimensions likewise use customers.segment. KPI totals independently evaluate altered measure contexts even when selected rows are empty. Native Omni join/subquery/BLANK behavior and actual security enforcement remain unverified.
