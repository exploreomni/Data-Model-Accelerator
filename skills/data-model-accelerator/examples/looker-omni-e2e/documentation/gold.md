# Gold — invoice fact and historical customer dimension

Two models publish 20 warehouse columns: `DIM_CUSTOMERS` (6) and `FCT_INVOICES` (14). [Data dictionary](data-dictionary.md) covers each field and [ERD/build flow](model-erd.md) shows the expected many-to-one relationship. Gold is the reusable dataset, not a materialized September/USD executive report.

Build the dimension after silver history and current invoices; build the fact after all four silver models and the dimension. Both SQL files perform full replacements. No cross-model transaction, task orchestration, incremental merge, change propagation schedule, grants, or rollback mechanism is established. Mid-refresh consistency, late corrections, rebuild cost and publication policy require operational design before real deployment.

`DIM_CUSTOMERS` retains all supplied history versions and adds one tenant-scoped Unknown member for each tenant present in silver invoices. Its Unknown `CUSTOMER_ID`, `VALID_FROM` and `VALID_TO` are null; `SEGMENT` is `Unknown`. Existing dimension rows need not have invoices. The fact selects the history version valid at invoice `ISSUED_AT`, then stores its surrogate; an unmatched invoice receives that tenant's Unknown key without being dropped. Omni joins by the preselected key, rather than repeating the temporal join or substituting today's customer segment.

Keys are proposed identifiers, not enforced warehouse PK/FKs. Invoice key is MD5 of tenant, colon and invoice ID. Historical customer key includes tenant, customer ID and `VALID_FROM` formatted to whole seconds; Unknown key uses tenant plus `:__UNKNOWN__`. This relies on fixture alphanumeric, nonempty source identifiers and second-precision history starts. Arbitrary delimiters, subsecond history starts, hash/input collisions and alternate unknown-member conventions need a revised encoding contract and tests. Hashing is not anonymization or security.

Posted payment entries and posted credit entries are grouped independently per tenant/invoice/currency before left-joining invoices. This avoids a payment-by-credit cross product. No payment-time/report-period restriction is applied to current ledger totals. Missing totals become zero. Net cents = gross cents − discount cents − posted credit cents; paid cents = posted payment cents. Zero and negative amounts are preserved. Currency mismatches require validation; equality joins alone can silently leave unmatched ledger rows. Orphan handling and reporting are explicit review decisions, not inferred from a successful join.

Invoice business date is UTC-to-America/Chicago conversion followed by a date cast. All drafts, currencies and dates remain in the fact. Money stays in exact integer minor units; USD and EUR are separate populations and neither is converted into the other.

## Semantic consumers and deliberate boundaries

Omni `invoices.view` maps to the fact; `customers.view` maps to the dimension. The relationship declares `many_to_one` and `always_left` on both `invoices.customer_key = customers.customer_key` and `invoices.tenant_id = customers.tenant_id`, contingent on tested dimension-key uniqueness and fact-key coverage within the same tenant. Both views mark their surrogates as `primary_key`; those declarations do not verify data integrity.

The `billing.topic` adds `invoices.tenant_id` access filtering via user attribute `tenant_id`. No user definitions/assignments, bypass values or live tenant security were validated. Warehouse grants/policies are absent, and hidden dimensions are not access restrictions. Direct SQL access is a separate enforcement path.

Posted invoice count and filtered sums remain semantic. Hidden raw sums feed public COALESCE-to-zero wrappers, then `payment_rate = paid_cents_sum / NULLIF(net_cents_sum,0)`. This is a ratio of sums after query grouping and filters, never an average of row ratios. Empty totals zero is an explicit exercise contract; native Looker empty behavior was not observed. `net_amount_display` divides by 100 once with a generic numeric format/selected-currency label, proposing a correction to the legacy unconditional USD format. The preserved tile still selects cents, not this display measure.

The report context retains the native date expression `2026/09/01 to 2026/09/30`, currency USD default, posted filter, historical-segment grouping/listen mappings, segment sort and limit 500. It is a local simulation contract, not a native published Omni dashboard. Other grouped/date/currency/persona cases are acceptance scenarios, not additional source assets.

## Model inventory

### DMA_SIM.GOLD.DIM_CUSTOMERS

Historical customer dimension plus one Unknown member per tenant with a current invoice.

**Grain:** One customer history version per (TENANT_ID, CUSTOMER_ID, VALID_FROM), plus one Unknown row per current-invoice tenant. CUSTOMER_KEY is a logical unique surrogate requiring tests.

**Columns (6):** `CUSTOMER_KEY`, `TENANT_ID`, `CUSTOMER_ID`, `VALID_FROM`, `VALID_TO`, `SEGMENT`.

**Definition:** [target/snowflake/20_gold_dim_customers.sql](../target/snowflake/20_gold_dim_customers.sql).

**Dependencies:** DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY, DMA_SIM.SILVER.BILLING_INVOICES **Consumers:** DMA_SIM.GOLD.FCT_INVOICES, Omni customers.view / customers.segment and relationship.

**Key contract:** Use the stated tenant-qualified grain and per-column key roles in the dictionary. No primary/foreign-key constraints are declared in these scripts.

### DMA_SIM.GOLD.FCT_INVOICES

Current invoice fact with separately aggregated posted payment/credit amounts, Chicago business date and as-of customer key. Drafts, all currencies and all periods remain available.

**Grain:** One retained current invoice per (TENANT_ID, INVOICE_ID), contingent on no history fanout. INVOICE_KEY is a logical unique surrogate; every amount is invoice-grain.

**Columns (14):** `TENANT_ID`, `INVOICE_ID`, `CUSTOMER_ID`, `ISSUED_AT`, `INVOICE_DATE`, `CURRENCY`, `STATUS`, `GROSS_CENTS`, `DISCOUNT_CENTS`, `CREDIT_CENTS`, `NET_CENTS`, `PAID_CENTS`, `INVOICE_KEY`, `CUSTOMER_KEY`.

**Definition:** [target/snowflake/21_gold_fct_invoices.sql](../target/snowflake/21_gold_fct_invoices.sql).

**Dependencies:** DMA_SIM.SILVER.BILLING_INVOICES, DMA_SIM.GOLD.DIM_CUSTOMERS, DMA_SIM.SILVER.BILLING_PAYMENTS, DMA_SIM.SILVER.BILLING_CREDITS **Consumers:** Omni invoices.view / billing.topic / report-context.json.

**Key contract:** Use the stated tenant-qualified grain and per-column key roles in the dictionary. No primary/foreign-key constraints are declared in these scripts.

## Quality, operations and ownership

Required checks: every invoice row against independently specified expectations; unique/non-null surrogates; fact-to-dimension coverage; no history fanout; tenant boundaries; separate ledger and currency reconciliations; zero/negative/empty totals; Chicago date boundaries; grouped/totals/segment/currency/date personas. Metadata declarations and SQL parsing alone do not prove these checks passed.

**Refresh and recovery:** Bronze creates schemas/tables IF NOT EXISTS but supplies no ingestion service. Silver/gold use CREATE OR REPLACE full rebuilds. No production scheduler, incremental MERGE, stream/task, cross-table atomic publication, SLA, alerts or recovery procedure is implemented by these files.

**Security:** Synthetic only. Candidate SQL declares no grants, masking or row-access policies. Omni billing.topic uses invoices.tenant_id / user_attribute tenant_id; real assignments and native enforcement are unknown. Hidden fields are not security, and direct SQL access is separate.

**Ownership:** Unknown: no real business owner, steward, engineering operator, security approver or on-call owner is supplied. The synthetic scenario is not human business approval.

**Unknown in production:** source/warehouse access, ingestion lag, retention/deletion requirements, schedules, incremental strategy, concurrency/publication atomicity, volume/cost/SLA, observability, incident owner, rollback and business acceptance. These gaps require concrete evidence and ownership, not inferred defaults.

**Validation boundary:** Documentation was checked against parsed candidate SQL, source catalogue and Omni physical mappings. No Snowflake native execution, deployed constraint introspection or Omni native validation was performed to author this page.
