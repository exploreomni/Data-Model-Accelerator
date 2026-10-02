# Semantic contract and source preservation

The native candidate includes three `.view` files, two `.topic` files and the special `relationships` file. [report-context.json](../target/omni/report-context.json) is an explicitly **nonnative** local companion that binds source report roles, selected fields, output aliases, filters and defaults. It is not an Omni workbook/dashboard export. Physical SQL quotes exact uppercase columns; field references point to other modeled fields.

| Source output / original identity | Proposed semantic definition | Warehouse field/grain |
|---|---|---|
| Revenue `revenue_summary`, project `5e760dfd-fdc7-5462-9807-a12f807eebc9`, cell `c7db64be-6671-54f8-8714-2d80116373e6` | `invoice_count`, `revenue_cents`, `paid_cents_total`, `outstanding_cents_total`, `payment_rate` grouped by invoice month/segment | `FCT_INVOICES`; posted measure and report filters; invoice-date historical segment. |
| Retention `active_customer_detail`, project `3b237687-7ceb-5f7d-bec6-047158cb60ef`, cell `06a5206d-c15a-5f3d-b2ad-9116c2f34f33` | Distinct tenant/customer/month/segment/first-paid-month tuples where posted and net > 0 | Invoice fact for population and historical segment; customer-month many-to-one lookup for full-capture first paid month. |
| Retention summary `active_customers`, cell `8473ffd1-e376-5d15-b81f-689c9fa7a4b1` | Proposed `invoiced_active_customers`: distinct tenant/customer keys with a posted positive-net invoice | CASE dimension on invoice fact plus `count_distinct`; not a sum of invoices or flags across months. |
| Executive `executive_summary`, project `8a6acc93-05da-50b1-91a3-c09584f72f7c`, cell `29a72b7c-da5a-5c86-a258-b20fd59e0ef1` | Net/paid sums, weighted rate, and both explicitly named active metrics grouped by invoice month/segment | Invoice fact; original executive `active_customers` is preserved as proposed `paying_active_customers`. |

The shared component is `8c7958a3-573b-5b81-9a0e-02de54bed99d`, pinned version `48181ff3-ae9a-5717-add9-699e64214924`. SQL cell `fb1b0798-bd91-5b31-873c-2736038d7153` supplies current invoice/payment/history logic; Python cell `019ca33f-6110-5123-8c28-0b8fbb312f3f` reads/validates adjustments, merges on tenant/invoice and derives net/outstanding. Each imported copy and component version must be validated; missing or drifted imports remain source-coverage gaps. The [source report contract](../input/repo/report-contract.json) preserves role and variable selection independently.

## Money and metric population

Invoice money measures use filtered hidden sums with `status: posted`. Public wrappers explicitly return zero for empty aggregate populations. `payment_rate` divides aggregate paid by aggregate net with `NULLIF(net,0)`. Net-zero returns null, including empty aggregates; no per-row ratio average, sum of ratios or denominator substitution is introduced. Empty grouped reports have zero groups. Display-only `revenue_usd` divides cents by 100 without moving currency conversion into shared facts.

`invoiced_active_customer_key` is tenant/customer only for posted net-positive invoices; `paying_active_customer_key` uses posted paid-positive invoices. Their `count_distinct` measures preserve customer distinctness within the selected group. A customer appearing in several historical segments can appear in each segment; segment counts are not necessarily additive to an unsegmented distinct total. No canonical field called `active_customers` exists until an explicit human decision.

Customer-month measures are deliberately named `all_status_*_cents`; the monthly table includes drafts. `invoiced_customer_months` and `paying_customer_months` sum binary monthly flags, so across months they count customer-months rather than unique customers. The invoice-grain active metrics retain the source report interpretation. No segment field is exposed on `customer_month.view`.

## Report context, exploration and authorization

Defaults are tenant A, date range `[2026-01-01, 2026-03-01)` and segment `ALL`. Runtime dates filter `invoices.invoice_date`, not first-paid month; the exact-segment filter uses `invoices.segment`. Equal endpoints are a valid empty selection; reversed windows fail. Date/segment defaults are report context, not materialization filters. The what-if multiplier remains in retained Hex exploration and never enters reusable revenue.

`billing.topic` binds `invoices.tenant_id` to user attribute `tenant_id`; `retention.topic` binds `customer_month.tenant_id` to the same attribute. The fixture requires an authorized A/B persona and denies unknown or explicitly unauthorized personas. A UI input alone is not authorization; hidden fields are not authorization either. Real user-attribute provisioning, group membership, warehouse grants/RLS and negative persona tests in Omni remain unverified. Raw SQL can bypass semantic topics and is not evidence of topic enforcement.

The invoice→customer relationship uses customer key plus tenant. The invoice→customer-month relationship uses tenant, customer and invoice month. Both declare many-to-one and require independently tested keys. Native model validation and actual query generation remain open. Candidate syntax follows the [bounded Omni contract](../../../references/looker-omni-contract.md), [official views](https://docs.omni.co/modeling/views), [relationships](https://docs.omni.co/modeling/relationships) and [topic access filters](https://docs.omni.co/modeling/topics/parameters/access-filters); those documents do not establish that this particular candidate has been accepted by Omni.
