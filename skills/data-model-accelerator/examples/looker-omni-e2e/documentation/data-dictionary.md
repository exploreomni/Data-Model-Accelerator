# Data dictionary — synthetic billing model

**10 models / 79 columns:** 34 bronze, 25 silver and 20 gold. Inventory SHA-256: `a6550a215986a1cb844c0f3f93bf081b4ad8a1e9487275b974fa65a3a0c341a7`. [Machine inventory](model-inventory.json) · [Machine dictionary](data-dictionary.json).

Names are the uppercase physical identifiers produced by unquoted candidate DDL. The source catalogue marks most bronze columns non-null; the bootstrap declares no NOT NULL constraints. Downstream types are SQL-derived and native CTAS nullability/type metadata is unobserved. Logical keys and required values are not enforced constraints. Validation entries below describe required checks, not test passes.

[Bronze](bronze.md) · [Silver](silver.md) · [Gold](gold.md) · [ERD and build flow](model-erd.md)

## DMA_SIM.BRONZE.BILLING_INVOICE_CDC

Raw full after-image invoice change events, preserving source versions, arrivals and replays.

**Grain:** One supplied invoice event occurrence. Entity=(TENANT_ID, INVOICE_ID); version adds SOURCE_SEQ. Exact replays can repeat that tuple, so it is not a unique physical row key.

**Definition:** [target/snowflake/00_bronze.sql](../target/snowflake/00_bronze.sql). **Dependencies:** Synthetic raw input; real replication unknown. **Consumers:** DMA_SIM.SILVER.BILLING_INVOICES, Legacy Looker invoice_chaos derived SQL, retained for comparison.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** input/raw-data.json#/invoice_cdc/*/tenant_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.TENANT_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### INVOICE_ID

Source invoice identifier; unique only with its tenant in current-state models.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** input/raw-data.json#/invoice_cdc/*/invoice_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.INVOICE_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### CUSTOMER_ID

Source customer identifier; include tenant in every association.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Tenant-qualified customer reference/history-key component; not globally unique and not an enforced foreign key.
- **Source:** input/raw-data.json#/invoice_cdc/*/customer_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.CUSTOMER_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### ISSUED_AT

Invoice issue instant; source ISO text means UTC only under the scenario contract.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/invoice_cdc/*/issued_at; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.ISSUED_AT. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify UTC interpretation, Chicago midnight/DST boundaries, date-range endpoints and history match; never use machine timezone or convert business date twice.

### GROSS_CENTS

Invoice gross amount in integer minor units of the row currency.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/invoice_cdc/*/gross_cents; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.GROSS_CENTS. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### DISCOUNT_CENTS

Invoice discount in minor units; raw null means zero in the silver contract.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=true. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=1; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/invoice_cdc/*/discount_cents; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.DISCOUNT_CENTS. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### STATUS

Record status; trim/lowercase normalization occurs in silver, not bronze.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/invoice_cdc/*/status; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.STATUS. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify trim/lowercase and posted populations for ledger and invoice separately; preserve drafts upstream.

### CURRENCY

Source currency code; USD and EUR are separate populations without FX conversion.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/invoice_cdc/*/currency; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.CURRENCY. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Currency code; not an amount or exchange rate.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Validate invoice-ledger agreement, reject mismatches, reconcile USD/EUR separately, no implicit FX or mixed-currency totals.

### SOURCE_SEQ

Authoritative source version order within tenant and business entity.

- **Data Type:** NUMBER(38,0) (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Version-identity component with tenant/business ID; exact repeats allowed, conflicting payloads invalid.
- **Source:** input/raw-data.json#/invoice_cdc/*/source_seq; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.SOURCE_SEQ. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless integer sequence, not time/duration.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Latest source version before deletion; exact replay and arrival-shuffle invariance; reject conflicting same-version payloads rather than accept arrival winner.

### OP

Operation marker; exact DELETE removes a latest selected entity. SQL does not normalize its case.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/invoice_cdc/*/op; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.OP. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Agree connector operation domain; SQL recognizes exact DELETE only. Latest tombstone must not resurrect an older row; no operation normalization exists.

### ARRIVAL_SEQ

Arrival order used as tie-breaker; not the source version or an event timestamp.

- **Data Type:** NUMBER(38,0) (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/invoice_cdc/*/arrival_seq; synthetic catalogue DMA_SIM.BRONZE.BILLING_INVOICE_CDC.ARRIVAL_SEQ. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless integer sequence, not time/duration.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Latest source version before deletion; exact replay and arrival-shuffle invariance; reject conflicting same-version payloads rather than accept arrival winner.

## DMA_SIM.BRONZE.BILLING_PAYMENT_CDC

Raw full after-image payment ledger change events; several entries may belong to one invoice.

**Grain:** One payment event occurrence. Entity=(TENANT_ID, ENTRY_ID); version adds SOURCE_SEQ, with exact replays permitted.

**Definition:** [target/snowflake/00_bronze.sql](../target/snowflake/00_bronze.sql). **Dependencies:** Synthetic raw input; real replication unknown. **Consumers:** DMA_SIM.SILVER.BILLING_PAYMENTS, Legacy Looker invoice_chaos derived SQL, retained for comparison.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** input/raw-data.json#/payment_cdc/*/tenant_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.TENANT_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### ENTRY_ID

Ledger-entry identifier within a tenant; payment and credit namespaces are independent.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** input/raw-data.json#/payment_cdc/*/entry_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.ENTRY_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### INVOICE_ID

Source invoice identifier; unique only with its tenant in current-state models.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** input/raw-data.json#/payment_cdc/*/invoice_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.INVOICE_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### AMOUNT_CENTS

Ledger-entry amount in integer minor units of its stated currency.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/payment_cdc/*/amount_cents; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.AMOUNT_CENTS. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### STATUS

Record status; trim/lowercase normalization occurs in silver, not bronze.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/payment_cdc/*/status; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.STATUS. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify trim/lowercase and posted populations for ledger and invoice separately; preserve drafts upstream.

### CURRENCY

Source currency code; USD and EUR are separate populations without FX conversion.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/payment_cdc/*/currency; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.CURRENCY. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Currency code; not an amount or exchange rate.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Validate invoice-ledger agreement, reject mismatches, reconcile USD/EUR separately, no implicit FX or mixed-currency totals.

### SOURCE_SEQ

Authoritative source version order within tenant and business entity.

- **Data Type:** NUMBER(38,0) (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Version-identity component with tenant/business ID; exact repeats allowed, conflicting payloads invalid.
- **Source:** input/raw-data.json#/payment_cdc/*/source_seq; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.SOURCE_SEQ. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless integer sequence, not time/duration.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Latest source version before deletion; exact replay and arrival-shuffle invariance; reject conflicting same-version payloads rather than accept arrival winner.

### OP

Operation marker; exact DELETE removes a latest selected entity. SQL does not normalize its case.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/payment_cdc/*/op; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.OP. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Agree connector operation domain; SQL recognizes exact DELETE only. Latest tombstone must not resurrect an older row; no operation normalization exists.

### ARRIVAL_SEQ

Arrival order used as tie-breaker; not the source version or an event timestamp.

- **Data Type:** NUMBER(38,0) (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/payment_cdc/*/arrival_seq; synthetic catalogue DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.ARRIVAL_SEQ. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless integer sequence, not time/duration.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Latest source version before deletion; exact replay and arrival-shuffle invariance; reject conflicting same-version payloads rather than accept arrival winner.

## DMA_SIM.BRONZE.BILLING_CREDIT_CDC

Raw full after-image credit ledger change events, independent from the payment ledger.

**Grain:** One credit event occurrence. Entity=(TENANT_ID, ENTRY_ID); version adds SOURCE_SEQ, with exact replays permitted.

**Definition:** [target/snowflake/00_bronze.sql](../target/snowflake/00_bronze.sql). **Dependencies:** Synthetic raw input; real replication unknown. **Consumers:** DMA_SIM.SILVER.BILLING_CREDITS, Legacy Looker invoice_chaos derived SQL, retained for comparison.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** input/raw-data.json#/credit_cdc/*/tenant_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.TENANT_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### ENTRY_ID

Ledger-entry identifier within a tenant; payment and credit namespaces are independent.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** input/raw-data.json#/credit_cdc/*/entry_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.ENTRY_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### INVOICE_ID

Source invoice identifier; unique only with its tenant in current-state models.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** input/raw-data.json#/credit_cdc/*/invoice_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.INVOICE_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### AMOUNT_CENTS

Ledger-entry amount in integer minor units of its stated currency.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/credit_cdc/*/amount_cents; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.AMOUNT_CENTS. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### STATUS

Record status; trim/lowercase normalization occurs in silver, not bronze.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/credit_cdc/*/status; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.STATUS. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify trim/lowercase and posted populations for ledger and invoice separately; preserve drafts upstream.

### CURRENCY

Source currency code; USD and EUR are separate populations without FX conversion.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/credit_cdc/*/currency; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.CURRENCY. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Currency code; not an amount or exchange rate.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Validate invoice-ledger agreement, reject mismatches, reconcile USD/EUR separately, no implicit FX or mixed-currency totals.

### SOURCE_SEQ

Authoritative source version order within tenant and business entity.

- **Data Type:** NUMBER(38,0) (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Version-identity component with tenant/business ID; exact repeats allowed, conflicting payloads invalid.
- **Source:** input/raw-data.json#/credit_cdc/*/source_seq; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.SOURCE_SEQ. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless integer sequence, not time/duration.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Latest source version before deletion; exact replay and arrival-shuffle invariance; reject conflicting same-version payloads rather than accept arrival winner.

### OP

Operation marker; exact DELETE removes a latest selected entity. SQL does not normalize its case.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/credit_cdc/*/op; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.OP. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Agree connector operation domain; SQL recognizes exact DELETE only. Latest tombstone must not resurrect an older row; no operation normalization exists.

### ARRIVAL_SEQ

Arrival order used as tie-breaker; not the source version or an event timestamp.

- **Data Type:** NUMBER(38,0) (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/credit_cdc/*/arrival_seq; synthetic catalogue DMA_SIM.BRONZE.BILLING_CREDIT_CDC.ARRIVAL_SEQ. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless integer sequence, not time/duration.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Latest source version before deletion; exact replay and arrival-shuffle invariance; reject conflicting same-version payloads rather than accept arrival winner.

## DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY

Raw effective-dated customer segment snapshots; exact history replays may occur.

**Grain:** One supplied customer history occurrence. Intended version identity=(TENANT_ID, CUSTOMER_ID, VALID_FROM); exact snapshots may repeat and conflicts/overlaps need validation.

**Definition:** [target/snowflake/00_bronze.sql](../target/snowflake/00_bronze.sql). **Dependencies:** Synthetic raw input; real replication unknown. **Consumers:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY, Legacy Looker invoice_chaos derived SQL, retained for comparison.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** input/raw-data.json#/customer_history/*/tenant_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.TENANT_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### CUSTOMER_ID

Source customer identifier; include tenant in every association.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** Tenant-qualified customer reference/history-key component; not globally unique and not an enforced foreign key.
- **Source:** input/raw-data.json#/customer_history/*/customer_id; synthetic catalogue DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.CUSTOMER_ID. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### VALID_FROM

Inclusive UTC start of a customer history interval.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** History-key component with tenant/customer; null only on gold Unknown member, and uniqueness needs validation.
- **Source:** input/raw-data.json#/customer_history/*/valid_from; synthetic catalogue DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.VALID_FROM. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Strict UTC parse, valid half-open intervals, no conflicting starts/overlap, null-end handling, temporal precision and separate Unknown-member null rules.

### VALID_TO

Exclusive UTC interval end; null means open-ended.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=true. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=3; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/customer_history/*/valid_to; synthetic catalogue DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.VALID_TO. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Strict UTC parse, valid half-open intervals, no conflicting starts/overlap, null-end handling, temporal precision and separate Unknown-member null rules.

### SEGMENT

Historical customer segment; casing/whitespace are passed through unchanged.

- **Data Type:** VARCHAR (synthetic catalogue and bootstrap DDL)
- **Nullability:** Source catalogue nullable=false. Bootstrap DDL has no NOT NULL constraint; catalogue requirements are not physically enforced by this script. Fixture NULL count=0; live schema unobserved.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** input/raw-data.json#/customer_history/*/segment; synthetic catalogue DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.SEGMENT. Real connector/upstream field identity unknown.
- **Transformation:** Preserve raw supplied value. Bootstrap defines tables only; no loading, cleaning, version selection or deletion removal is performed here.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Preserve source values and historical segment; validate Unknown behavior and no invoice fanout.

## DMA_SIM.SILVER.BILLING_INVOICES

Typed, normalized latest retained invoice after version selection and deletion filtering.

**Grain:** At most one retained current invoice per (TENANT_ID, INVOICE_ID), selecting greatest source version before DELETE removal.

**Definition:** [target/snowflake/10_silver_invoice.sql](../target/snowflake/10_silver_invoice.sql). **Dependencies:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC **Consumers:** DMA_SIM.GOLD.DIM_CUSTOMERS, DMA_SIM.GOLD.FCT_INVOICES.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC.TENANT_ID
- **Transformation:** tenant_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### INVOICE_ID

Source invoice identifier; unique only with its tenant in current-state models.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC.INVOICE_ID
- **Transformation:** invoice_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### CUSTOMER_ID

Source customer identifier; include tenant in every association.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified customer reference/history-key component; not globally unique and not an enforced foreign key.
- **Source:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC.CUSTOMER_ID
- **Transformation:** customer_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### ISSUED_AT

Invoice issue instant; source ISO text means UTC only under the scenario contract.

- **Data Type:** TIMESTAMP_NTZ (explicit/inherited cast; native CTAS precision metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC.ISSUED_AT
- **Transformation:** CAST(issued_at AS TIMESTAMPNTZ); ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify UTC interpretation, Chicago midnight/DST boundaries, date-range endpoints and history match; never use machine timezone or convert business date twice.

### GROSS_CENTS

Invoice gross amount in integer minor units of the row currency.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC.GROSS_CENTS
- **Transformation:** CAST(gross_cents AS DECIMAL(38, 0)); ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### DISCOUNT_CENTS

Invoice discount in minor units; raw null means zero in the silver contract.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically non-null through COALESCE(...,0), subject to valid inputs and successful casts. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC.DISCOUNT_CENTS
- **Transformation:** COALESCE(CAST(discount_cents AS DECIMAL(38, 0)), 0); ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### STATUS

Record status; trim/lowercase normalization occurs in silver, not bronze.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC.STATUS
- **Transformation:** LOWER(TRIM(status)); ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify trim/lowercase and posted populations for ledger and invoice separately; preserve drafts upstream.

### CURRENCY

Source currency code; USD and EUR are separate populations without FX conversion.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC.CURRENCY
- **Transformation:** currency; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Currency code; not an amount or exchange rate.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Validate invoice-ledger agreement, reject mismatches, reconcile USD/EUR separately, no implicit FX or mixed-currency totals.

## DMA_SIM.SILVER.BILLING_PAYMENTS

Typed current payment entries, retaining all statuses and currencies until gold aggregation.

**Grain:** At most one retained current payment entry per (TENANT_ID, ENTRY_ID).

**Definition:** [target/snowflake/11_silver_payment.sql](../target/snowflake/11_silver_payment.sql). **Dependencies:** DMA_SIM.BRONZE.BILLING_PAYMENT_CDC **Consumers:** DMA_SIM.GOLD.FCT_INVOICES.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.TENANT_ID
- **Transformation:** tenant_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### ENTRY_ID

Ledger-entry identifier within a tenant; payment and credit namespaces are independent.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.ENTRY_ID
- **Transformation:** entry_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### INVOICE_ID

Source invoice identifier; unique only with its tenant in current-state models.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.INVOICE_ID
- **Transformation:** invoice_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### AMOUNT_CENTS

Ledger-entry amount in integer minor units of its stated currency.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.AMOUNT_CENTS
- **Transformation:** CAST(amount_cents AS DECIMAL(38, 0)); ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### STATUS

Record status; trim/lowercase normalization occurs in silver, not bronze.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.STATUS
- **Transformation:** LOWER(TRIM(status)); ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify trim/lowercase and posted populations for ledger and invoice separately; preserve drafts upstream.

### CURRENCY

Source currency code; USD and EUR are separate populations without FX conversion.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_PAYMENT_CDC.CURRENCY
- **Transformation:** currency; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Currency code; not an amount or exchange rate.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Validate invoice-ledger agreement, reject mismatches, reconcile USD/EUR separately, no implicit FX or mixed-currency totals.

## DMA_SIM.SILVER.BILLING_CREDITS

Typed current credit entries, retaining all statuses and currencies until gold aggregation.

**Grain:** At most one retained current credit entry per (TENANT_ID, ENTRY_ID).

**Definition:** [target/snowflake/12_silver_credit.sql](../target/snowflake/12_silver_credit.sql). **Dependencies:** DMA_SIM.BRONZE.BILLING_CREDIT_CDC **Consumers:** DMA_SIM.GOLD.FCT_INVOICES.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_CREDIT_CDC.TENANT_ID
- **Transformation:** tenant_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### ENTRY_ID

Ledger-entry identifier within a tenant; payment and credit namespaces are independent.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_CREDIT_CDC.ENTRY_ID
- **Transformation:** entry_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### INVOICE_ID

Source invoice identifier; unique only with its tenant in current-state models.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_CREDIT_CDC.INVOICE_ID
- **Transformation:** invoice_id; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### AMOUNT_CENTS

Ledger-entry amount in integer minor units of its stated currency.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_CREDIT_CDC.AMOUNT_CENTS
- **Transformation:** CAST(amount_cents AS DECIMAL(38, 0)); ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### STATUS

Record status; trim/lowercase normalization occurs in silver, not bronze.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_CREDIT_CDC.STATUS
- **Transformation:** LOWER(TRIM(status)); ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify trim/lowercase and posted populations for ledger and invoice separately; preserve drafts upstream.

### CURRENCY

Source currency code; USD and EUR are separate populations without FX conversion.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_CREDIT_CDC.CURRENCY
- **Transformation:** currency; ROW_NUMBER partitions tenant/business ID and orders SOURCE_SEQ DESC, ARRIVAL_SEQ DESC; retain rank=1 then OP <> DELETE. All remaining statuses/currencies/dates retained.
- **Units:** Currency code; not an amount or exchange rate.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Validate invoice-ledger agreement, reject mismatches, reconcile USD/EUR separately, no implicit FX or mixed-currency totals.

## DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY

Typed customer history intervals with exact duplicate projected rows collapsed.

**Grain:** One distinct history row. Intended uniqueness=(TENANT_ID, CUSTOMER_ID, VALID_FROM) and non-overlap are not guaranteed by SELECT DISTINCT.

**Definition:** [target/snowflake/13_silver_customer_history.sql](../target/snowflake/13_silver_customer_history.sql). **Dependencies:** DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY **Consumers:** DMA_SIM.GOLD.DIM_CUSTOMERS.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.TENANT_ID
- **Transformation:** tenant_id; SELECT DISTINCT across all five projected fields collapses exact replays, not conflicting/overlapping history.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### CUSTOMER_ID

Source customer identifier; include tenant in every association.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified customer reference/history-key component; not globally unique and not an enforced foreign key.
- **Source:** DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.CUSTOMER_ID
- **Transformation:** customer_id; SELECT DISTINCT across all five projected fields collapses exact replays, not conflicting/overlapping history.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### VALID_FROM

Inclusive UTC start of a customer history interval.

- **Data Type:** TIMESTAMP_NTZ (explicit/inherited cast; native CTAS precision metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** History-key component with tenant/customer; null only on gold Unknown member, and uniqueness needs validation.
- **Source:** DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.VALID_FROM
- **Transformation:** CAST(valid_from AS TIMESTAMPNTZ); SELECT DISTINCT across all five projected fields collapses exact replays, not conflicting/overlapping history.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Strict UTC parse, valid half-open intervals, no conflicting starts/overlap, null-end handling, temporal precision and separate Unknown-member null rules.

### VALID_TO

Exclusive UTC interval end; null means open-ended.

- **Data Type:** TIMESTAMP_NTZ (explicit/inherited cast; native CTAS precision metadata unobserved)
- **Nullability:** Logically nullable for open-ended history; cast preserves NULL. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.VALID_TO
- **Transformation:** CAST(valid_to AS TIMESTAMPNTZ); SELECT DISTINCT across all five projected fields collapses exact replays, not conflicting/overlapping history.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Strict UTC parse, valid half-open intervals, no conflicting starts/overlap, null-end handling, temporal precision and separate Unknown-member null rules.

### SEGMENT

Historical customer segment; casing/whitespace are passed through unchanged.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY.SEGMENT
- **Transformation:** segment; SELECT DISTINCT across all five projected fields collapses exact replays, not conflicting/overlapping history.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Preserve source values and historical segment; validate Unknown behavior and no invoice fanout.

## DMA_SIM.GOLD.DIM_CUSTOMERS

Historical customer dimension plus one Unknown member per tenant with a current invoice.

**Grain:** One customer history version per (TENANT_ID, CUSTOMER_ID, VALID_FROM), plus one Unknown row per current-invoice tenant. CUSTOMER_KEY is a logical unique surrogate requiring tests.

**Definition:** [target/snowflake/20_gold_dim_customers.sql](../target/snowflake/20_gold_dim_customers.sql). **Dependencies:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY, DMA_SIM.SILVER.BILLING_INVOICES **Consumers:** DMA_SIM.GOLD.FCT_INVOICES, Omni customers.view / customers.segment and relationship.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### CUSTOMER_KEY

Warehouse surrogate for a customer history version or tenant-scoped Unknown member.

- **Data Type:** VARCHAR (MD5 hex key or inherited key; native CTAS length metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Logical primary key plus Omni primary_key declaration. No warehouse PK is declared or enforced by this candidate; validate uniqueness/non-nullness.
- **Source:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY.TENANT_ID/CUSTOMER_ID/VALID_FROM; Unknown branch uses DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID and NULL/literal expressions.
- **Transformation:** MD5(tenant_id || ':' || customer_id || ':' || TO_CHAR(valid_from, 'YYYY-MM-DD HH24:MI:SS')); UNION ALL Unknown branch: MD5(tenant_id || ':__UNKNOWN__') over distinct current-invoice tenants.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic surrogate identifier. MD5 is not a privacy or access-control guarantee; real classification unknown.
- **Validation:** Required validation, not an execution claim: Test non-null/unique PK or FK coverage as applicable; verify delimiter-free IDs, reserved Unknown sentinel, whole-second history encoding and hash/input collisions. No native enforcement proof.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY.TENANT_ID; Unknown branch uses DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID and NULL/literal expressions.
- **Transformation:** tenant_id; UNION ALL Unknown branch: tenant_id over distinct current-invoice tenants.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### CUSTOMER_ID

Source customer identifier; include tenant in every association. Gold Unknown member carries NULL.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically nullable: Unknown branch emits NULL; VALID_TO also permits open-ended history. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified customer reference/history-key component; not globally unique and not an enforced foreign key.
- **Source:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY.CUSTOMER_ID; Unknown branch uses DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID and NULL/literal expressions.
- **Transformation:** customer_id; UNION ALL Unknown branch: CAST(NULL AS VARCHAR) over distinct current-invoice tenants.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### VALID_FROM

Inclusive UTC start of a customer history interval. Gold Unknown member carries NULL.

- **Data Type:** TIMESTAMP_NTZ (explicit/inherited cast; native CTAS precision metadata unobserved)
- **Nullability:** Logically nullable: Unknown branch emits NULL; VALID_TO also permits open-ended history. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** History-key component with tenant/customer; null only on gold Unknown member, and uniqueness needs validation.
- **Source:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY.VALID_FROM; Unknown branch uses DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID and NULL/literal expressions.
- **Transformation:** valid_from; UNION ALL Unknown branch: CAST(NULL AS TIMESTAMPNTZ) over distinct current-invoice tenants.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Strict UTC parse, valid half-open intervals, no conflicting starts/overlap, null-end handling, temporal precision and separate Unknown-member null rules.

### VALID_TO

Exclusive UTC interval end; null means open-ended. Gold Unknown member carries NULL.

- **Data Type:** TIMESTAMP_NTZ (explicit/inherited cast; native CTAS precision metadata unobserved)
- **Nullability:** Logically nullable: Unknown branch emits NULL; VALID_TO also permits open-ended history. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY.VALID_TO; Unknown branch uses DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID and NULL/literal expressions.
- **Transformation:** valid_to; UNION ALL Unknown branch: CAST(NULL AS TIMESTAMPNTZ) over distinct current-invoice tenants.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Strict UTC parse, valid half-open intervals, no conflicting starts/overlap, null-end handling, temporal precision and separate Unknown-member null rules.

### SEGMENT

Historical customer segment; casing/whitespace are passed through unchanged.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY.SEGMENT; Unknown branch uses DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID and NULL/literal expressions.
- **Transformation:** segment; UNION ALL Unknown branch: 'Unknown' over distinct current-invoice tenants.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Preserve source values and historical segment; validate Unknown behavior and no invoice fanout.

## DMA_SIM.GOLD.FCT_INVOICES

Current invoice fact with separately aggregated posted payment/credit amounts, Chicago business date and as-of customer key. Drafts, all currencies and all periods remain available.

**Grain:** One retained current invoice per (TENANT_ID, INVOICE_ID), contingent on no history fanout. INVOICE_KEY is a logical unique surrogate; every amount is invoice-grain.

**Definition:** [target/snowflake/21_gold_fct_invoices.sql](../target/snowflake/21_gold_fct_invoices.sql). **Dependencies:** DMA_SIM.SILVER.BILLING_INVOICES, DMA_SIM.GOLD.DIM_CUSTOMERS, DMA_SIM.SILVER.BILLING_PAYMENTS, DMA_SIM.SILVER.BILLING_CREDITS **Consumers:** Omni invoices.view / billing.topic / report-context.json.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

### TENANT_ID

Tenant identifier used in every business identity, ledger association and access context.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Component of every tenant-scoped identity and of the fact access-filter context; not independently unique.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID
- **Transformation:** i.tenant_id; posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### INVOICE_ID

Source invoice identifier; unique only with its tenant in current-state models.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified business identifier; bronze versions/replays and multiple ledger entries mean it is not independently unique.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.INVOICE_ID
- **Transformation:** i.invoice_id; posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### CUSTOMER_ID

Source customer identifier; include tenant in every association.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Tenant-qualified customer reference/history-key component; not globally unique and not an enforced foreign key.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.CUSTOMER_ID
- **Transformation:** i.customer_id; posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic tenant/business identifier, potentially linkable in production; real privacy classification, masking and grants unknown.
- **Validation:** Required validation, not an execution claim: Validate nonempty ASCII alphanumeric source IDs, tenant-scoped keys/joins, declared-grain uniqueness, orphan policy and persona isolation; gold Unknown CUSTOMER_ID is explicitly nullable.

### ISSUED_AT

Invoice issue instant; source ISO text means UTC only under the scenario contract.

- **Data Type:** TIMESTAMP_NTZ (explicit/inherited cast; native CTAS precision metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.ISSUED_AT
- **Transformation:** i.issued_at; posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** UTC instant under scenario contract; raw ISO text then TIMESTAMP_NTZ without intrinsic timezone. History-key formatting assumes whole-second starts.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify UTC interpretation, Chicago midnight/DST boundaries, date-range endpoints and history match; never use machine timezone or convert business date twice.

### INVOICE_DATE

America/Chicago calendar date of the issue instant, derived once upstream.

- **Data Type:** DATE (explicit cast; native CTAS metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.ISSUED_AT
- **Transformation:** CAST(CONVERT_TIMEZONE('UTC', 'America/Chicago', i.issued_at) AS DATE); posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** America/Chicago business date, not UTC date.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify UTC interpretation, Chicago midnight/DST boundaries, date-range endpoints and history match; never use machine timezone or convert business date twice.

### CURRENCY

Source currency code; USD and EUR are separate populations without FX conversion.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.CURRENCY
- **Transformation:** i.currency; posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Currency code; not an amount or exchange rate.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Validate invoice-ledger agreement, reject mismatches, reconcile USD/EUR separately, no implicit FX or mixed-currency totals.

### STATUS

Record status; trim/lowercase normalization occurs in silver, not bronze.

- **Data Type:** VARCHAR (SQL-inferred; native CTAS length/type metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.STATUS
- **Transformation:** i.status; posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic business/technical metadata; production sensitivity, retention, policy and classification owner unknown.
- **Validation:** Required validation, not an execution claim: Verify trim/lowercase and posted populations for ledger and invoice separately; preserve drafts upstream.

### GROSS_CENTS

Invoice gross amount in integer minor units of the row currency.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.GROSS_CENTS
- **Transformation:** i.gross_cents; posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### DISCOUNT_CENTS

Invoice discount in minor units; raw null means zero in the silver contract.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically non-null through COALESCE(...,0), subject to valid inputs and successful casts. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.DISCOUNT_CENTS
- **Transformation:** i.discount_cents; posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### CREDIT_CENTS

Current posted credit total per tenant/invoice/currency, or zero when absent.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically non-null through COALESCE(...,0), subject to valid inputs and successful casts. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_CREDITS.AMOUNT_CENTS/STATUS/TENANT_ID/INVOICE_ID/CURRENCY via posted grouped CTE
- **Transformation:** COALESCE(c.credit_cents, 0); posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### NET_CENTS

Gross minus discount minus posted credits, calculated exactly once upstream.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.GROSS_CENTS/DISCOUNT_CENTS; DMA_SIM.SILVER.BILLING_CREDITS.AMOUNT_CENTS/STATUS/TENANT_ID/INVOICE_ID/CURRENCY via posted grouped CTE
- **Transformation:** i.gross_cents - i.discount_cents - COALESCE(c.credit_cents, 0); posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### PAID_CENTS

Current posted payment total per tenant/invoice/currency, or zero when absent.

- **Data Type:** NUMBER(38,0) (explicit cast or integer aggregate/arithmetic inference; native CTAS metadata unobserved)
- **Nullability:** Logically non-null through COALESCE(...,0), subject to valid inputs and successful casts. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** No key role declared; not a uniqueness or relationship guarantee.
- **Source:** DMA_SIM.SILVER.BILLING_PAYMENTS.AMOUNT_CENTS/STATUS/TENANT_ID/INVOICE_ID/CURRENCY via posted grouped CTE
- **Transformation:** COALESCE(p.payment_cents, 0); posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Integer minor currency units; text-encoded in bronze. USD/EUR fixture uses 100 per major unit. Never sum mixed currencies or clamp signs.
- **Classification:** Synthetic monetary value; production financial sensitivity, masking and access approval unknown.
- **Validation:** Required validation, not an execution claim: Strict integer text/range, exact amounts, null discount/missing-ledger zero, valid zero/negative values, no fanout/double adjustment or double /100; cast failures must not become silent nulls.

### INVOICE_KEY

Warehouse surrogate for tenant/invoice identity; differs from the source legacy concatenated key.

- **Data Type:** VARCHAR (MD5 hex key or inherited key; native CTAS length metadata unobserved)
- **Nullability:** Logically required for valid input; SQL may propagate invalid input NULLs. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Logical primary key plus Omni primary_key declaration. No warehouse PK is declared or enforced by this candidate; validate uniqueness/non-nullness.
- **Source:** DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID/INVOICE_ID
- **Transformation:** MD5(i.tenant_id || ':' || i.invoice_id); posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic surrogate identifier. MD5 is not a privacy or access-control guarantee; real classification unknown.
- **Validation:** Required validation, not an execution claim: Test non-null/unique PK or FK coverage as applicable; verify delimiter-free IDs, reserved Unknown sentinel, whole-second history encoding and hash/input collisions. No native enforcement proof.

### CUSTOMER_KEY

Warehouse surrogate for a customer history version or tenant-scoped Unknown member.

- **Data Type:** VARCHAR (MD5 hex key or inherited key; native CTAS length metadata unobserved)
- **Nullability:** Logically non-null: matched key or tenant-scoped Unknown fallback, assuming valid tenant. No explicit NOT NULL in CTAS; native physical nullability unverified.
- **Key Role:** Logical FK to DMA_SIM.GOLD.DIM_CUSTOMERS.CUSTOMER_KEY; expected many-to-one after quality checks. No warehouse FK declared.
- **Source:** DMA_SIM.GOLD.DIM_CUSTOMERS.CUSTOMER_KEY/TENANT_ID/CUSTOMER_ID/VALID_FROM/VALID_TO and DMA_SIM.SILVER.BILLING_INVOICES.TENANT_ID/CUSTOMER_ID/ISSUED_AT
- **Transformation:** COALESCE(h.customer_key, MD5(i.tenant_id || ':__UNKNOWN__')); posted payment and credit totals are grouped separately per tenant/invoice/currency. Left joins preserve invoices; history uses inclusive start/exclusive end with NULL end open.
- **Units:** Unitless identifier/category; no numeric aggregation meaning.
- **Classification:** Synthetic surrogate identifier. MD5 is not a privacy or access-control guarantee; real classification unknown.
- **Validation:** Required validation, not an execution claim: Test non-null/unique PK or FK coverage as applicable; verify delimiter-free IDs, reserved Unknown sentinel, whole-second history encoding and hash/input collisions. No native enforcement proof.

## Evidence and operation limits

Synthetic only. Candidate SQL declares no grants, masking or row-access policies. Omni billing.topic uses invoices.tenant_id / user_attribute tenant_id; real assignments and native enforcement are unknown. Hidden fields are not security, and direct SQL access is separate.

Bronze creates schemas/tables IF NOT EXISTS but supplies no ingestion service. Silver/gold use CREATE OR REPLACE full rebuilds. No production scheduler, incremental MERGE, stream/task, cross-table atomic publication, SLA, alerts or recovery procedure is implemented by these files.

Primary references: [Snowflake identifiers](https://docs.snowflake.com/en/sql-reference/identifiers-syntax), [numeric types](https://docs.snowflake.com/en/sql-reference/data-types-numeric), [timestamps](https://docs.snowflake.com/en/sql-reference/data-types-datetime), [constraints](https://docs.snowflake.com/en/sql-reference/constraints-overview), [Omni access filters](https://docs.omni.co/modeling/topics/parameters/access-filters). Standard-table PK/FK declarations would not establish enforcement; these scripts do not declare them.
