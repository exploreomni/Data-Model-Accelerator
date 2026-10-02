# Hex billing model: conceptual, logical and physical views

This editable diagram set covers all **11 models and 74 columns** through the linked [inventory](model-inventory.json) and [dictionary](data-dictionary.md). Relationship lines below describe proposed logical associations and transformation dependencies; they are not enforced foreign keys. Candidate DDL/CTAS emits no physical PK/FK/NOT NULL constraints. Data-test execution and native acceptance are separate evidence.

## Conceptual and logical grain

The billing domain contains versioned invoices and payments, effective customer classifications, and manual signed invoice corrections. A current invoice combines independently aggregated payments and at most one correction, then acquires exactly one historical customer classification at its invoice date. Monthly customer balances derive from those invoice facts. Repeated source occurrences are not additional business entities.

```mermaid
erDiagram
  CUSTOMER_HISTORY ||--o{ CURRENT_INVOICE : "effective tenant/customer/date match"
  CURRENT_INVOICE ||--o{ CURRENT_PAYMENT : "same tenant and invoice"
  CURRENT_INVOICE ||--o| MANUAL_ADJUSTMENT : "same tenant and invoice"
  CUSTOMER_MONTH ||--|{ CURRENT_INVOICE : "same tenant/customer/invoice month"
  CUSTOMER_HISTORY {
    string tenant_id
    string customer_id
    date valid_from
    date valid_to "exclusive; nullable"
    string segment
  }
  CURRENT_INVOICE {
    string tenant_id
    string invoice_id
    string customer_id
    date invoice_date
    int net_cents
    int paid_cents
    int outstanding_cents
  }
  CURRENT_PAYMENT {
    string tenant_id
    string payment_id
    string invoice_id
    int paid_cents
  }
  MANUAL_ADJUSTMENT {
    string tenant_id
    string invoice_id
    int adjustment_cents
  }
  CUSTOMER_MONTH {
    string tenant_id
    string customer_id
    date invoice_month
    int has_invoice
    int has_paid_invoice
    date first_paid_month "invoice proxy; nullable"
  }
```

The effective join is `invoice.TENANT_ID = history.TENANT_ID AND invoice.CUSTOMER_ID = history.CUSTOMER_ID AND invoice.INVOICE_DATE >= history.VALID_FROM AND (invoice.INVOICE_DATE < history.VALID_TO OR history.VALID_TO IS NULL)`. An unmatched or multiply matched invoice fails validation. No current-segment or Unknown-member fallback is asserted. A customer-month contains at least one current invoice; a dense month spine is outside scope.

## Bronze responsibility / physical source view

```mermaid
flowchart LR
  RAWFILE["input/raw-data.json<br/>Synthetic captured source"] --> RI["DMA_HEX.RAW.INVOICE_CDC<br/>invoice event occurrence"]
  RAWFILE --> RP["DMA_HEX.RAW.PAYMENT_CDC<br/>payment event occurrence"]
  RAWFILE --> RH["DMA_HEX.RAW.CUSTOMER_HISTORY<br/>effective history occurrence"]
  CSV["input/repo/adjustments.csv<br/>Independently inventoried manual source"] -->|"proposed governed landing"| RA["DMA_HEX.RAW.ADJUSTMENTS<br/>tenant/invoice adjustment"]
```

Arrows denote a source/landing mapping, not a demonstrated connector or physical constraint. Invoice/payment version identity adds `SEQUENCE` to the tenant/business key. Exact CDC/history replays remain visible in raw; adjustment duplicates always fail. The four RAW objects fulfill bronze duties without an extra copied layer.

## Silver physical transformation view

```mermaid
flowchart LR
  RI["DMA_HEX.RAW.INVOICE_CDC"] -->|"highest sequence then tombstone; casts/status"| SI["DMA_HEX.SILVER.BILLING_INVOICES<br/>tenant/invoice"]
  RP["DMA_HEX.RAW.PAYMENT_CDC"] -->|"highest sequence then tombstone; casts"| SP["DMA_HEX.SILVER.BILLING_PAYMENTS<br/>tenant/payment"]
  RH["DMA_HEX.RAW.CUSTOMER_HISTORY"] -->|"complete DISTINCT; date casts"| SH["DMA_HEX.SILVER.BILLING_CUSTOMER_HISTORY<br/>tenant/customer/valid-from"]
  RA["DMA_HEX.RAW.ADJUSTMENTS"] -->|"strict signed cents; no deduplication"| SA["DMA_HEX.SILVER.BILLING_ADJUSTMENTS<br/>tenant/invoice"]
```

Source conflicts, invalid identities, duplicate adjustments and overlapping histories must fail before these current-state results are promoted. Every source-to-target column is listed in the dictionary. No status/date/tenant report filter is applied upstream.

## Gold physical relationship and aggregation view

```mermaid
flowchart LR
  SH["DMA_HEX.SILVER.BILLING_CUSTOMER_HISTORY"] --> D["DMA_HEX.GOLD.DIM_CUSTOMERS<br/>key tenant|customer|valid-from"]
  SI["DMA_HEX.SILVER.BILLING_INVOICES"] --> F["DMA_HEX.GOLD.FCT_INVOICES<br/>key tenant|invoice"]
  SP["DMA_HEX.SILVER.BILLING_PAYMENTS"] -->|"SUM per tenant/invoice before join"| F
  SA["DMA_HEX.SILVER.BILLING_ADJUSTMENTS"] -->|"0..1 adjustment; tenant/invoice"| F
  D -->|"exactly one effective tenant/customer/date row"| F
  F -->|"all-status sums; separate posted flags"| M["DMA_HEX.GOLD.FCT_CUSTOMER_MONTH<br/>key tenant|customer|month<br/>no segment"]
  F --> BI["Omni billing topic<br/>invoice-date segment reports"]
  D -->|"customer_key + tenant; many-to-one"| BI
  M -->|"tenant + customer + month; many-to-one"| BI
  M --> RT["Omni retention topic<br/>customer-month proxy"]
```

The Omni relationship from invoices to customer-month is a many-to-one lookup for cohort proxy fields, not a reverse aggregation join. Segment stays on invoice history. `HAS_INVOICE` and `HAS_PAID_INVOICE` are intentionally different; the diagrams do not imply one approved definition of active customer. Cohorts use current paid balances at the captured watermark and do not establish payment-event-time retention.
