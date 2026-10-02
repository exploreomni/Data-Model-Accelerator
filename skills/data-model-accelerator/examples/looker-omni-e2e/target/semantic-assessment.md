# Semantic architect assessment — synthetic Looker to Omni migration

Status: **candidate artifacts authored; local structure checked; native validation and approval outstanding**. No live tenant, warehouse execution, credentials, expected/oracle files, or target publication used by this specialist. Source extraction finished before reading the two target gold definitions.

## Evidence and outputs

Source snapshot: `6bc16edf65649fc696cf5055a8b2e7ab09dcdc35f75459dcebce64644b79332b`. The assigned Looker specialist result contains 4 parsed assets, 50 objects, 48 rules, 6 unresolved references and 10 explicit gaps. Its structural checker reports no errors while retaining `extraction_complete: false`. Shared synthetic catalogue evidence is recorded separately from repo asset evidence.

Native-format candidate files are `omni/invoices.view`, `omni/customers.view`, `omni/relationships`, and `omni/billing.topic`. They contain 20 dimensions, 7 measures, one many-to-one relationship and one topic tenant access filter. `omni/report-context.json` is the agreed **local simulation interface**, not a native Omni dashboard export or published report. It preserves the original element's fields, fixed posted filter, date/currency defaults, listens, segment sort and 500-row limit.

Physical mappings were checked against `snowflake/21_gold_fct_invoices.sql` and `snowflake/20_gold_dim_customers.sql`: `DMA_SIM.GOLD.FCT_INVOICES` and `DMA_SIM.GOLD.DIM_CUSTOMERS`. Both use unquoted physical names; YAML SQL explicitly quotes uppercase column names. Fact `customer_key` references the historical dimension version selected upstream, including a tenant-scoped Unknown member. No second temporal join is added in Omni.

## Measure and field crosswalk

| Native Looker reference | Candidate Omni reference | Preserved behavior / proposed change |
|---|---|---|
| `invoice_chaos.invoice_count` | `invoices.invoice_count` | Posted filtered count of non-null `invoice_key`; warehouse uniqueness must be tested. Native source count SQL remains unobserved. |
| `invoice_chaos.net_cents_sum` | `invoices.raw_net_cents_sum` → `invoices.net_cents_sum` | Posted sum of upstream net cents; public COALESCE adds explicit empty-total zero. |
| `invoice_chaos.paid_cents_sum` | `invoices.raw_paid_cents_sum` → `invoices.paid_cents_sum` | Posted sum of upstream paid cents; public COALESCE adds explicit empty-total zero. |
| `invoice_chaos.payment_rate` | `invoices.payment_rate` | Ratio of those aggregate sums with NULLIF(net,0), after grouping and filters; two-decimal percent display. |
| `invoice_chaos.net_amount_display` | `invoices.net_amount_display` | One division by100; generic two-decimal number format and explicit selected-currency label replace unconditional USD. Remains absent from the preserved tile. |
| `invoice_chaos.segment` | `customers.segment` | Historical segment via fact's as-of customer_key; not current customer segment. |
| `invoice_chaos.legacy_invoice_key` | `invoices.invoice_key` | Identity intent retained, physical representation changes from colon concatenation to warehouse MD5. Source name/expression remain in lineage; target must pass key tests. |
| `invoice_chaos.tenant_id`, `invoice_id`, `invoice_date`, `currency`, `status`, `net_cents`, `paid_cents` | Corresponding `invoices` dimensions | Tenant, local business ID, Chicago business date, currency, normalized status and integer minor-unit amounts preserved. |

**Proposed behavior change — empty population:** hidden raw filtered sums keep aggregate behavior; public COALESCE wrappers implement the exercise's zero totals. The supplied LookML has no explicit empty-set zero rule. No native generated SQL was inspected, so this is not claimed as proven source equivalence. A zero denominator still yields null payment rate.

**Proposed presentation correction — currency:** the supplied tile selects cents directly. An unused Looker display measure divides net by100 and always labels USD, even when the Currency control selects EUR. The candidate retains cents in the preserved report and exposes the optional display measure with numeric formatting and an explicit label. USD/EUR in this exercise both use100 minor units. Other currency scales, conversion and mixed-currency totals remain outside the contract. No business owner approved this correction.

## Query and access boundaries

`billing.topic` references `invoices`, exposes the `customers` join and declares `access_filters: [{field: invoices.tenant_id, user_attribute: tenant_id}]`. It supplies no bypass values or default persona. Real Omni attribute definitions, values, user/group assignment, connection role and warehouse row policies are unknown. Hidden fields are a presentation property, not security. A local simulator denying unknown personas does not certify native access enforcement.

The report's source IDs remain `exec_collections_legacy` and `legacy_collections_by_segment`; original model `billing`, Explore `invoice_chaos`, title, `looker_grid`, `newspaper`, and `dashboards-next` are preserved in the source result. Target context maps the Explore to `invoices` and segment to `customers.segment`. The source date expression is retained verbatim; the exercise interprets it as September1 inclusive through October1 exclusive. Additional daily, total, segment, currency and date scenarios are acceptance cases, not invented source dashboard assets.

The fact retains drafts, other currencies and out-of-period invoices. Report defaults never filter the reusable table globally. Posted payment/credit aggregation and net arithmetic execute once upstream. Semantic sums retain posted invoice filters; report posted filters apply additionally. The ratio remains query-grain dependent and never becomes a precomputed invoice ratio.

## Source-rule placement crosswalk

Every ID below has the prefix `looker:synthetic_billing_mess:rule:`. This is a proposed disposition against the parent-authored warehouse candidates; it is not approval or independently demonstrated equivalence.

| Rule suffix | Proposed target / review boundary |
|---|---|
| `connection` | Unresolved external connection configuration; scenario binds only the local simulation. |
| `includes` | Omni view/topic file set; source project membership retained in lineage. |
| `access_filter` | omni/billing.topic access_filters; native assignment and warehouse enforcement unverified. |
| `cte:invoice_versions` | snowflake/10_silver_invoice.sql; version conflict validation required. |
| `cte:invoice_current` | snowflake/10_silver_invoice.sql; version conflict validation required. |
| `cte:payment_versions` | snowflake/11_silver_payment.sql; version conflict validation required. |
| `cte:payment_current` | snowflake/11_silver_payment.sql; version conflict validation required. |
| `cte:credit_versions` | snowflake/12_silver_credit.sql; version conflict validation required. |
| `cte:credit_current` | snowflake/12_silver_credit.sql; version conflict validation required. |
| `cte:posted_payments` | snowflake/21_gold_fct_invoices.sql; separate posted ledger aggregation. |
| `cte:posted_credits` | snowflake/21_gold_fct_invoices.sql; separate posted ledger aggregation. |
| `cte:customer_history` | snowflake/13_silver_customer_history.sql and 20_gold_dim_customers.sql; interval integrity required. |
| `derived_sql` | Silver/gold decomposition; invoice grain and historical as-of semantics require reconciliation. |
| `column:tenant_id` | Warehouse gold → invoices.tenant_id. |
| `column:invoice_id` | Warehouse gold → invoices.invoice_id. |
| `column:customer_id` | Warehouse gold → invoices.customer_id. |
| `column:issued_at` | Warehouse gold → invoices.issued_at. |
| `column:invoice_date` | Warehouse gold → invoices.invoice_date. |
| `column:currency` | Warehouse gold → invoices.currency. |
| `column:status` | Warehouse gold → invoices.status. |
| `column:segment` | Warehouse gold → customers.segment via historical key. |
| `column:gross_cents` | Warehouse gold → invoices.gross_cents. |
| `column:discount_cents` | Warehouse gold → invoices.discount_cents. |
| `column:credit_cents` | Warehouse gold → invoices.credit_cents. |
| `column:net_cents` | Warehouse gold → invoices.net_cents. |
| `column:paid_cents` | Warehouse gold → invoices.paid_cents. |
| `column:legacy_invoice_key` | Warehouse gold → invoices.invoice_key; explicit identity representation change. |
| `join:payments` | Silver/gold decomposition; invoice grain and historical as-of semantics require reconciliation. |
| `join:credits` | Silver/gold decomposition; invoice grain and historical as-of semantics require reconciliation. |
| `join:history` | Silver/gold decomposition; invoice grain and historical as-of semantics require reconciliation. |
| `dimension:legacy_invoice_key` | omni/invoices.view invoice_key; hidden/type/identity context retained as applicable. |
| `dimension:tenant_id` | omni/invoices.view tenant_id; hidden/type/identity context retained as applicable. |
| `dimension:invoice_id` | omni/invoices.view invoice_id; hidden/type/identity context retained as applicable. |
| `dimension:invoice_date` | omni/invoices.view invoice_date; hidden/type/identity context retained as applicable. |
| `dimension:currency` | omni/invoices.view currency; hidden/type/identity context retained as applicable. |
| `dimension:status` | omni/invoices.view status; hidden/type/identity context retained as applicable. |
| `dimension:segment` | omni/customers.view segment; hidden/type/identity context retained as applicable. |
| `dimension:net_cents` | omni/invoices.view net_cents; hidden/type/identity context retained as applicable. |
| `dimension:paid_cents` | omni/invoices.view paid_cents; hidden/type/identity context retained as applicable. |
| `measure:invoice_count` | omni/invoices.view invoice_count; query-grain semantics and documented proposed changes apply. |
| `measure:net_cents_sum` | omni/invoices.view net_cents_sum; query-grain semantics and documented proposed changes apply. |
| `measure:paid_cents_sum` | omni/invoices.view paid_cents_sum; query-grain semantics and documented proposed changes apply. |
| `measure:payment_rate` | omni/invoices.view payment_rate; query-grain semantics and documented proposed changes apply. |
| `measure:net_amount_display` | omni/invoices.view net_amount_display; query-grain semantics and documented proposed changes apply. |
| `dashboard_filter:Reporting Date` | omni/report-context.json filters; viewer-adjustable defaults retained. |
| `dashboard_filter:Currency` | omni/report-context.json filters; viewer-adjustable defaults retained. |
| `tile_query` | omni/report-context.json element; mapped selected fields/fixed filter/listens/sort/limit. |
| `tile_listen` | omni/report-context.json element; mapped selected fields/fixed filter/listens/sort/limit. |

## Validation status and remaining evidence

Completed locally: safe parsing of all four Omni YAML documents and the report JSON; exact uppercase physical-column checks against the two gold SELECT projections; resolution of all modeled measure references; structural check of the explicit topic tenant filter. These checks do not run Omni's native validator, model schema discovery, symmetric-aggregation engine, real query compilation, Looker runtime or Snowflake SQL execution.

The separately owned compiler and independent acceptance work must still exercise grouped/totals/empty/zero-net outcomes, persona isolation, all gold rows, replay and arrival order. Source SQL lacks conflict, currency-mismatch and history-overlap rejection; parent-authored warehouse validation must demonstrate those scenario rules. Record results separately rather than retroactively treating this assessment as execution evidence. Native branch/model validation, live modeled query comparisons, identity configuration and business/security acceptance remain open before production use.

Primary syntax references checked September9,2026: [Omni measures](https://docs.omni.co/modeling/measures), [relationships](https://docs.omni.co/modeling/relationships), [access filters](https://docs.omni.co/modeling/topics/parameters/access-filters), [format strings](https://docs.omni.co/modeling/measures/parameters/format), [native model validation](https://docs.omni.co/api/models/validate-model). Omni's [SQL documentation](https://docs.omni.co/analyze-explore/sql) states that raw SQL tabs bypass the model; their results cannot establish topic security.
