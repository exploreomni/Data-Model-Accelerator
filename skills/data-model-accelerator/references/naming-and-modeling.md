# Naming and modeling contract for the Snowflake simulation

Primary sources checked **2026-09-09**. This is a proposed convention for the synthetic `DMA_SIM` example, not a Snowflake requirement or phData certification. Apply it to new example objects; assess real repositories against their existing conventions before recommending renames.

## What comes from each source

**Documented Snowflake behavior:** unquoted identifiers resolve to uppercase; double-quoted identifiers preserve case and require corresponding references. Identifiers have a 255-character maximum. Lowercase SQL source text such as `invoice_id` therefore creates `INVOICE_ID` when unquoted. Avoid quoted lowercase names merely to make an editor look consistent. Preserve exact case for existing quoted objects and record the full database/schema/object identity. [Identifier requirements](https://docs.snowflake.com/en/sql-reference/identifiers-syntax)

**phData recommendation:** agree on naming standards and separate raw, staging, and transformed responsibilities. Its standardization article discusses databases or schemas as possible separation boundaries and recommends underscore-separated names. This supports consistent layers, not a vendor mandate for the exact words `BRONZE`, `SILVER`, `GOLD`, `FCT_`, or `DIM_`. [phData: Snowflake standardization](https://www.phdata.io/blog/how-to-combat-the-lack-of-standardization-in-snowflake/)

**phData modeling guidance:** choose models for the intended analytical purpose. Its modeling article discusses star schemas and conformed dimensions for consistent analytics. Our invoice fact/customer dimension is an application of that guidance; a vault or fully denormalized table is not a universal prerequisite. [phData: choosing a data model](https://www.phdata.io/blog/how-to-model-and-choose-the-right-data-model/)

## Chosen example namespaces and responsibilities

| Layer | Proposed physical examples | Contract |
|---|---|---|
| Bronze | `DMA_SIM.BRONZE.BILLING_INVOICE_CDC`, `BILLING_PAYMENT_CDC`, `BILLING_CREDIT_CDC`, `BILLING_CUSTOMER_HISTORY` | Preserve supplied change events and history, including source-specific identifiers and version/arrival order. |
| Silver | `DMA_SIM.SILVER.BILLING_INVOICES`, `BILLING_PAYMENTS`, `BILLING_CREDITS`, `BILLING_CUSTOMER_HISTORY` | Clean types, normalize statuses, select latest source versions before tombstone removal, and retain customer effective intervals. |
| Gold | `DMA_SIM.GOLD.FCT_INVOICES`, `DIM_CUSTOMERS` | Publish an invoice-grain fact linked to historical customer versions, plus a tenant-scoped Unknown customer member. |
| Semantic | Omni `invoices`, `customers`, and `billing` topic | Define reusable measures, ratios, exploration relationships, descriptions, and persona-dependent access filters. |

These are example names, not a complete required object inventory. Existing `RAW`, `STAGING`, `MARTS`, source databases, dbt aliases, or Coalesce locations can implement the same responsibilities. Prefer an explicit mapping over renaming working namespaces. A rename recommendation must identify affected consumers, compatibility aliases, migration order, owner approval, and rollback. Source-specific bronze names prevent collisions when several applications have an `invoices` table; separate source schemas are an equally valid established convention.

Bronze preservation does not mean every replication connector retains every historical version. The exercise explicitly supplies retained full after-images ordered by `source_seq`; `arrival_seq` is arrival order only. Replayed identical versions must not change results, and conflicting payloads for one version require rejection. Real connector behavior needs separate evidence. Synthetic JSON records are fixtures, not proof of deployed ingestion.

## Grain, keys, and boundaries

State grain before writing a join: one current invoice per `(tenant_id, invoice_id)`; payment and credit entries each have `(tenant_id, entry_id)` grain. `DIM_CUSTOMERS` uses an SCD2-style history grain `(tenant_id, customer_id, valid_from)`, with one additional Unknown member per tenant. Retain natural identifiers with `_id` and warehouse surrogates with `_key`; these suffixes do not establish uniqueness.

The bounded fixture uses MD5 of colon-separated tenant/invoice identifiers for `invoice_key`; `customer_key` includes tenant/customer and `valid_from` formatted to whole seconds. Unknown keys use tenant plus `:__UNKNOWN__`. This encoding depends on the fixture's nonempty ASCII alphanumeric identifiers and second-precision history starts. Hashing does not remove delimiter, precision or collision risks. Real inputs require an explicit encoding contract, full required timestamp precision, collision checks and stable null/sentinel handling.

Test non-null/unique keys, natural composite uniqueness, foreign-key coverage and non-overlapping history. The fact selects the customer version effective at invoice `issued_at`, with inclusive start/exclusive end and null end open-ended. Missing history maps to Unknown without dropping the invoice. Do not replace historical segment with the current segment.

Pre-aggregate current posted payments and credits separately to tenant/invoice/currency grain before joining the invoice fact. Joining individual ledger rows repeats invoice amounts. Missing ledger totals become zero; mismatched currencies require rejection. Cleaning, deduplication and net arithmetic belong upstream. Keep posted invoice filters, query-grain sums and ratios downstream; the paid/net ratio is a ratio of sums, not an average of invoice ratios.

For standard Snowflake tables, declared primary, foreign, and unique keys are not enforcement evidence. Hybrid tables have different enforcement rules. The example requires data tests regardless of metadata declarations. [Snowflake constraints](https://docs.snowflake.com/en/sql-reference/constraints-overview)

## Columns, money, and time

Use snake_case in SQL source and semantic field names, with explicit physical mapping where Snowflake stores uppercase. Choose descriptive business names; retain raw names in bronze and document every silver rename. Reserve `is_` for actual booleans and separate event timestamps from load timestamps.

The fixture contains **USD and EUR separately**. Bronze amounts are integer cents encoded as text; silver casts to `NUMBER(38,0)`, and gold retains exact integer `gross_cents`, `discount_cents`, `credit_cents`, `net_cents` and `paid_cents`. Net equals gross minus discount minus posted credits; null discount is zero. No warehouse `_usd` conversion columns are implied. Snowflake fixed-point types support explicit precision/scale; floating point can introduce rounding error. [Numeric types](https://docs.snowflake.com/en/sql-reference/data-types-numeric)

The report selects one currency. Both fixture currencies use 100 minor units per major unit; an optional semantic display measure divides by 100 exactly once and uses generic numeric formatting with an explicit selected-currency label. This corrects the legacy unconditional USD format as a proposal. Never aggregate mixed currencies or invent exchange rates. Preserve zero/negative amounts; keep the rate unrounded until presentation and use `NULLIF(denominator, 0)`. Explicit empty-total zeros are a scenario contract, not verified native Looker behavior.

Use explicit timestamp types and documented meaning. This exercise preserves the existing `issued_at`, `valid_from` and `valid_to` names: supplied ISO strings represent UTC instants and are cast to `TIMESTAMP_NTZ`. NTZ itself carries no timezone semantics. A new `_at_utc` suffix may clarify future models, but renaming existing columns is not required. Snowflake LTZ operations use session timezone; TZ retains an offset rather than the original IANA zone. [Date/time types](https://docs.snowflake.com/en/sql-reference/data-types-datetime)

The reporting timezone is `America/Chicago`; derive `invoice_date` with explicit UTC-to-Chicago conversion before truncating to date. Retain drafts, all currencies and all periods in gold; the September/USD/posted defaults remain report or semantic filters. Test midnight boundaries, daylight-saving transitions, missing offsets and timestamp precision. Never let the local machine's timezone decide the contract.

## Physical design and acceptance

Choose tables, views, refresh cadence, incremental keys, and late-arriving-data handling from workload and operational ownership. Do not add clustering to every gold model: Snowflake explicitly describes clustering as a performance/cost tradeoff that is unsuitable for some tables. [Clustering guidance](https://docs.snowflake.com/en/user-guide/tables-clustering-keys)

Acceptance requires grain/key checks, no-fanout reconciliation, null/amount behavior, persona isolation and comparisons at several groupings. The [Looker-to-Omni exercise](looker-omni-e2e.md) parses source/target artifacts and simulates their bounded SQL subset in DuckDB. Its results are local development evidence; Snowflake execution, native Omni validation, access configuration and business-owner acceptance remain separate gates.
