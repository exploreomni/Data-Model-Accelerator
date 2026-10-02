# Gold: invoice facts and a customer-month snapshot

Three gold models preserve invoice-level accounting and effective history while separating a customer-month proxy from report-grain measures. The [ERD](model-erd.md), [inventory](model-inventory.json), [dictionary](data-dictionary.md) and [native dbt SQL](../target/dbt/models/gold) describe the same candidate.

| Physical model | Grain / keys | Business purpose |
|---|---|---|
| `DMA_HEX.GOLD.DIM_CUSTOMERS` | `(TENANT_ID, CUSTOMER_ID, VALID_FROM)`; `CUSTOMER_KEY = tenant|customer|YYYY-MM-DD` | Preserve each supplied effective segment interval. No Unknown or current-only collapse. |
| `DMA_HEX.GOLD.FCT_INVOICES` | `(TENANT_ID, INVOICE_ID)`; `INVOICE_KEY = tenant|invoice`; effective `CUSTOMER_KEY` | Reusable all-current-status invoice balances with preaggregated payments, signed adjustments and invoice-date historical segment. |
| `DMA_HEX.GOLD.FCT_CUSTOMER_MONTH` | `(TENANT_ID, CUSTOMER_ID, INVOICE_MONTH)`; `CUSTOMER_MONTH_KEY = tenant|customer|YYYY-MM-DD` | All-current-status monthly balances, two separate posted activity flags, and earliest positive-paid invoice-month proxy. |

## Invoice formula and relationship contract

Payments are summed independently per tenant/invoice before any invoice join. Adjustments are a maximum-one-row tenant/invoice source. The effective customer join includes tenant and customer and uses `INVOICE_DATE >= VALID_FROM AND (INVOICE_DATE < VALID_TO OR VALID_TO IS NULL)`. Exactly one match is required; the left join preserves a visible invalid orphan for a failing assertion instead of silently dropping an invoice. Declared many-to-one cardinalities and Omni primary keys are logical expectations, not proof that the input satisfies them.

`NET_CENTS = AMOUNT_CENTS + COALESCE(ADJUSTMENT_CENTS,0)`. `PAID_CENTS` is the sum of current nondeleted payments, zero when no payment exists. `OUTSTANDING_CENTS = NET_CENTS - PAID_CENTS`, preserving negative overpayments. Values are integer USD cents; formatting divides by 100 exactly once. No FX conversion, report date restriction, tenant-A restriction or what-if multiplier enters a gold formula.

`INVOICE_MONTH` is the first day of the supplied invoice-date month. `SEGMENT` is taken from the effective customer row for that invoice date. Surrogate delimiters are protected by input validation; they do not excuse omission of tenant predicates. Current nondeleted drafts and out-of-report-window invoices remain in the invoice fact.

## Customer-month meaning and the unresolved active metric

Monthly `NET_CENTS`, `PAID_CENTS` and `OUTSTANDING_CENTS` sum **all current invoice statuses**. `HAS_INVOICE` is one only if at least one posted invoice in that tenant/customer/month has positive net cents. `HAS_PAID_INVOICE` is one only if at least one posted invoice has positive current paid cents. The two flags preserve different source definitions. No canonical `active_customers` metric is supplied.

`FIRST_PAID_MONTH` is the earliest invoice month with a posted invoice having positive current paid cents over the full captured invoice population. It is computed before report date/segment filters. A customer with no qualifying invoice has null. This is an invoice-based cohort proxy at capture `2026-03-02T00:00:00Z`, not payment-event-time retention, not the first actual cash receipt, and not a historical as-of payment balance. No payment timestamp exists to support those stronger interpretations.

The monthly table has no segment because a customer can change segment within a month. Invoice/segment reporting stays on the invoice fact. Retention detail selects distinct tenant/customer/month/historical-segment tuples from eligible invoices and joins the customer-month row for `FIRST_PAID_MONTH`. A single segment per customer-month would require a new approved allocation policy. Months with no current invoice have no row; a dense cohort/calendar matrix would be a separately scoped extension.

## Semantic consumers and proof

The [semantic crosswalk](semantic-mapping.md) maps revenue, executive and retention outputs to actual Omni fields. Money measures filter posted invoices and sum before forming `payment_rate = paid_sum / NULLIF(net_sum,0)`. Empty aggregate sums explicitly default to zero; grouped empty populations have no groups. The active metrics remain `invoiced_active_customers` and `paying_active_customers`, with original project names/IDs in the [conflict register](placement-and-conflicts.json).

Validation must compare invoice key sets, payment/adjustment components, effective segment/month slices, customer-month populations, each active flag and the cohort proxy. Total-only reconciliation is insufficient: opposite adjustment mistakes can cancel overall while changing segment reports. Authored tests and the independent local runner provide separate evidence; no native runtime execution or business acceptance is claimed by these documents.

## Operations, access and recovery

Gold uses full table rebuilds in dependency order after validated silver. Changes to captured payments or invoice versions may revise prior monthly balances and `FIRST_PAID_MONTH`; the current-snapshot design deliberately does not preserve historical as-of results. A production watermark/history design is an open decision. Run grains, effective relationships, formula/ledger reconciliation, tenant/persona checks, replay/shuffle invariance and report slices before publishing.

No production task schedule, incremental strategy, SLA, consumer owner, access grant, retention policy or rollback automation is supplied. Operational and business owners are **unknown**. Topics declare tenant attributes, but real attribute assignment, unauthorized-persona enforcement, Snowflake policy behavior and native Omni model validation remain separate gates. On failure, retain the prior accepted models/reports, rebuild from the retained source/CSV snapshot, reconcile, and approve the exact corrected version before a separately authorized cutover.
