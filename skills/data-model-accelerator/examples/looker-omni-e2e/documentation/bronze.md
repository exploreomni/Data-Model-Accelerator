# Bronze — retained synthetic source evidence

Four raw tables preserve change events and customer history before business transformation. These are synthetic input contracts, not an implemented SaaS replication service. [Data dictionary](data-dictionary.md) documents every column; [ERD/build flow](model-erd.md) separates model relationships from transport.

`target/snowflake/00_bronze.sql` creates `DMA_SIM` and all three schemas, then uses `CREATE TABLE IF NOT EXISTS`. It does not load data, refresh records, migrate an existing schema, install a connector, create a task, or establish retention. The local simulator loads supplied JSON separately. No source credentials, production account, connector watermark, replication lag, delivery guarantee or source owner is verified.

The fixture has 17 invoice event occurrences, 18 payment events, 9 credit events and 4 customer-history rows, read from `input/raw-data.json`. These counts describe this supplied file, not warehouse metadata or production cardinality. Catalogue and native-shaped exports cover 34 columns with matching names/types. Most are marked non-null in the synthetic catalogue, but bootstrap DDL has no `NOT NULL`: treat source-required values as a logical contract, not a physical guard.

Amounts remain integer cents encoded as strings. Timestamp strings represent UTC instants only under `input/scenario.md`. IDs are nonempty ASCII alphanumeric and tenant-scoped. Raw values, including whitespace/case in status and nullable discount/history end, are preserved. An empty or malformed value is not silently replaced with a plausible business value.

CDC events are full after-images. Entity plus `SOURCE_SEQ` identifies a source version, while exact replays may repeat it. `ARRIVAL_SEQ` is not source order. All events are retained in this exercise; a real connector's history/retention must be investigated separately. Customer history is interval data, not inferred from invoice events.

## Model inventory

### DMA_SIM.BRONZE.BILLING_INVOICE_CDC

Raw full after-image invoice change events, preserving source versions, arrivals and replays.

**Grain:** One supplied invoice event occurrence. Entity=(TENANT_ID, INVOICE_ID); version adds SOURCE_SEQ. Exact replays can repeat that tuple, so it is not a unique physical row key.

**Columns (11):** `TENANT_ID`, `INVOICE_ID`, `CUSTOMER_ID`, `ISSUED_AT`, `GROSS_CENTS`, `DISCOUNT_CENTS`, `STATUS`, `CURRENCY`, `SOURCE_SEQ`, `OP`, `ARRIVAL_SEQ`.

**Definition:** [target/snowflake/00_bronze.sql](../target/snowflake/00_bronze.sql).

**Dependencies:** Synthetic raw JSON and source schema export; real replication unknown. **Consumers:** DMA_SIM.SILVER.BILLING_INVOICES, Legacy Looker invoice_chaos derived SQL, retained for comparison.

**Key contract:** Event/version identity permits exact replays; history identity is logical and requires conflict/overlap checks.

### DMA_SIM.BRONZE.BILLING_PAYMENT_CDC

Raw full after-image payment ledger change events; several entries may belong to one invoice.

**Grain:** One payment event occurrence. Entity=(TENANT_ID, ENTRY_ID); version adds SOURCE_SEQ, with exact replays permitted.

**Columns (9):** `TENANT_ID`, `ENTRY_ID`, `INVOICE_ID`, `AMOUNT_CENTS`, `STATUS`, `CURRENCY`, `SOURCE_SEQ`, `OP`, `ARRIVAL_SEQ`.

**Definition:** [target/snowflake/00_bronze.sql](../target/snowflake/00_bronze.sql).

**Dependencies:** Synthetic raw JSON and source schema export; real replication unknown. **Consumers:** DMA_SIM.SILVER.BILLING_PAYMENTS, Legacy Looker invoice_chaos derived SQL, retained for comparison.

**Key contract:** Event/version identity permits exact replays; history identity is logical and requires conflict/overlap checks.

### DMA_SIM.BRONZE.BILLING_CREDIT_CDC

Raw full after-image credit ledger change events, independent from the payment ledger.

**Grain:** One credit event occurrence. Entity=(TENANT_ID, ENTRY_ID); version adds SOURCE_SEQ, with exact replays permitted.

**Columns (9):** `TENANT_ID`, `ENTRY_ID`, `INVOICE_ID`, `AMOUNT_CENTS`, `STATUS`, `CURRENCY`, `SOURCE_SEQ`, `OP`, `ARRIVAL_SEQ`.

**Definition:** [target/snowflake/00_bronze.sql](../target/snowflake/00_bronze.sql).

**Dependencies:** Synthetic raw JSON and source schema export; real replication unknown. **Consumers:** DMA_SIM.SILVER.BILLING_CREDITS, Legacy Looker invoice_chaos derived SQL, retained for comparison.

**Key contract:** Event/version identity permits exact replays; history identity is logical and requires conflict/overlap checks.

### DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY

Raw effective-dated customer segment snapshots; exact history replays may occur.

**Grain:** One supplied customer history occurrence. Intended version identity=(TENANT_ID, CUSTOMER_ID, VALID_FROM); exact snapshots may repeat and conflicts/overlaps need validation.

**Columns (5):** `TENANT_ID`, `CUSTOMER_ID`, `VALID_FROM`, `VALID_TO`, `SEGMENT`.

**Definition:** [target/snowflake/00_bronze.sql](../target/snowflake/00_bronze.sql).

**Dependencies:** Synthetic raw JSON and source schema export; real replication unknown. **Consumers:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY, Legacy Looker invoice_chaos derived SQL, retained for comparison.

**Key contract:** Event/version identity permits exact replays; history identity is logical and requires conflict/overlap checks.

## Quality, operations and ownership

Required checks: input shape and declared columns; strict identifier/type/null contracts; source-version conflict detection; replay preservation; operation domain; currency agreement; UTC interpretation; history interval validity. Runtime pass/failure evidence belongs in the separately recorded validation run. Source catalogue capture/visibility is synthetic, not proof of a real connection.

**Refresh and recovery:** Bronze creates schemas/tables IF NOT EXISTS but supplies no ingestion service. Silver/gold use CREATE OR REPLACE full rebuilds. No production scheduler, incremental MERGE, stream/task, cross-table atomic publication, SLA, alerts or recovery procedure is implemented by these files.

**Security:** Synthetic only. Candidate SQL declares no grants, masking or row-access policies. Omni billing.topic uses invoices.tenant_id / user_attribute tenant_id; real assignments and native enforcement are unknown. Hidden fields are not security, and direct SQL access is separate.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

**Unknown in production:** source/warehouse access, ingestion lag, retention/deletion requirements, schedules, incremental strategy, concurrency/publication atomicity, volume/cost/SLA, observability, incident owner, rollback and business acceptance. These gaps require concrete evidence and ownership, not inferred defaults.

**Validation boundary:** Documentation was checked against parsed candidate SQL, source catalogue and Omni physical mappings. No Snowflake native execution, deployed constraint introspection or Omni native validation was performed to author this page.
