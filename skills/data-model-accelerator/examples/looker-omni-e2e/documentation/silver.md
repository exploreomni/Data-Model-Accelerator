# Silver — typed current entities and effective history

Four silver models separate reusable cleanup from report filters. [Data dictionary](data-dictionary.md) covers all 25 columns. Each SQL file uses `CREATE OR REPLACE TABLE ... AS SELECT`: this is a candidate full rebuild, not a production incremental job or an atomic pipeline.

Build these after the four bronze inputs are loaded and their contracts validated. The invoice, payment and credit models rank by `SOURCE_SEQ DESC, ARRIVAL_SEQ DESC` within tenant/business entity, choose rank 1, then remove exact `DELETE`. Filtering tombstones before ranking would resurrect older live records. Conflicting payloads for one source version must be rejected by validation; the SQL alone uses arrival tie-breaking and does not reject them. Exact replay and shuffled arrival should leave valid current state unchanged.

Amounts are explicitly cast to fixed-point integers. Invoice null discounts become zero; statuses are trimmed and lowercased. Currency and operation strings are not normalized. Invalid numeric/timestamp casts fail rather than being silently accepted; a production error/quarantine workflow is not supplied. Casts to `TIMESTAMP_NTZ` rely on the synthetic UTC input contract, not an intrinsic timezone stored by that type.

Keep drafts, non-posted ledger entries, all currencies and all invoice dates. Posted ledger totals belong in gold; posted invoice and report defaults remain downstream. Technical source sequence, arrival and operation columns are not projected to silver. Their lineage remains in retained bronze; a production audit/watermark strategy is an ownership gap.

Customer history preserves half-open intervals: inclusive `VALID_FROM`, exclusive `VALID_TO`, null end open. `SELECT DISTINCT` removes only exact duplicate projected history rows. It neither resolves conflicting intervals nor proves unique `(TENANT_ID,CUSTOMER_ID,VALID_FROM)` keys. Missing history must remain distinguishable from a malformed or overlapping history record.

## Model inventory

### DMA_SIM.SILVER.BILLING_INVOICES

Typed, normalized latest retained invoice after version selection and deletion filtering.

**Grain:** At most one retained current invoice per (TENANT_ID, INVOICE_ID), selecting greatest source version before DELETE removal.

**Columns (8):** `TENANT_ID`, `INVOICE_ID`, `CUSTOMER_ID`, `ISSUED_AT`, `GROSS_CENTS`, `DISCOUNT_CENTS`, `STATUS`, `CURRENCY`.

**Definition:** [target/snowflake/10_silver_invoice.sql](../target/snowflake/10_silver_invoice.sql).

**Dependencies:** DMA_SIM.BRONZE.BILLING_INVOICE_CDC **Consumers:** DMA_SIM.GOLD.DIM_CUSTOMERS, DMA_SIM.GOLD.FCT_INVOICES.

**Key contract:** Use the stated tenant-qualified grain and per-column key roles in the dictionary. No primary/foreign-key constraints are declared in these scripts.

### DMA_SIM.SILVER.BILLING_PAYMENTS

Typed current payment entries, retaining all statuses and currencies until gold aggregation.

**Grain:** At most one retained current payment entry per (TENANT_ID, ENTRY_ID).

**Columns (6):** `TENANT_ID`, `ENTRY_ID`, `INVOICE_ID`, `AMOUNT_CENTS`, `STATUS`, `CURRENCY`.

**Definition:** [target/snowflake/11_silver_payment.sql](../target/snowflake/11_silver_payment.sql).

**Dependencies:** DMA_SIM.BRONZE.BILLING_PAYMENT_CDC **Consumers:** DMA_SIM.GOLD.FCT_INVOICES.

**Key contract:** Use the stated tenant-qualified grain and per-column key roles in the dictionary. No primary/foreign-key constraints are declared in these scripts.

### DMA_SIM.SILVER.BILLING_CREDITS

Typed current credit entries, retaining all statuses and currencies until gold aggregation.

**Grain:** At most one retained current credit entry per (TENANT_ID, ENTRY_ID).

**Columns (6):** `TENANT_ID`, `ENTRY_ID`, `INVOICE_ID`, `AMOUNT_CENTS`, `STATUS`, `CURRENCY`.

**Definition:** [target/snowflake/12_silver_credit.sql](../target/snowflake/12_silver_credit.sql).

**Dependencies:** DMA_SIM.BRONZE.BILLING_CREDIT_CDC **Consumers:** DMA_SIM.GOLD.FCT_INVOICES.

**Key contract:** Use the stated tenant-qualified grain and per-column key roles in the dictionary. No primary/foreign-key constraints are declared in these scripts.

### DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY

Typed customer history intervals with exact duplicate projected rows collapsed.

**Grain:** One distinct history row. Intended uniqueness=(TENANT_ID, CUSTOMER_ID, VALID_FROM) and non-overlap are not guaranteed by SELECT DISTINCT.

**Columns (5):** `TENANT_ID`, `CUSTOMER_ID`, `VALID_FROM`, `VALID_TO`, `SEGMENT`.

**Definition:** [target/snowflake/13_silver_customer_history.sql](../target/snowflake/13_silver_customer_history.sql).

**Dependencies:** DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY **Consumers:** DMA_SIM.GOLD.DIM_CUSTOMERS.

**Key contract:** Use the stated tenant-qualified grain and per-column key roles in the dictionary. No primary/foreign-key constraints are declared in these scripts.

## Quality, operations and ownership

Required checks: current-state natural-key uniqueness; greatest-version/tombstone order; strict casts; null discount zero; normalized status; exact replay and arrival-shuffle invariance; conflicting version rejection; history no-overlap and valid endpoints. These candidate SELECT statements do not implement every preflight check by themselves. Validate source inputs before trusting downstream grain.

**Refresh and recovery:** Bronze creates schemas/tables IF NOT EXISTS but supplies no ingestion service. Silver/gold use CREATE OR REPLACE full rebuilds. No production scheduler, incremental MERGE, stream/task, cross-table atomic publication, SLA, alerts or recovery procedure is implemented by these files.

**Security:** Synthetic only. Candidate SQL declares no grants, masking or row-access policies. Omni billing.topic uses invoices.tenant_id / user_attribute tenant_id; real assignments and native enforcement are unknown. Hidden fields are not security, and direct SQL access is separate.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

**Unknown in production:** source/warehouse access, ingestion lag, retention/deletion requirements, schedules, incremental strategy, concurrency/publication atomicity, volume/cost/SLA, observability, incident owner, rollback and business acceptance. These gaps require concrete evidence and ownership, not inferred defaults.

**Validation boundary:** Documentation was checked against parsed candidate SQL, source catalogue and Omni physical mappings. No Snowflake native execution, deployed constraint introspection or Omni native validation was performed to author this page.
