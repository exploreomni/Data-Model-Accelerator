# Independent expected results — synthetic Hex migration

Frozen September 10, 2026, before inspecting this case's target, parser, notebook exports or migration runner. The expected-data author was the actual delegated agent `/root/refactor_failure_modes`, acting as an independent business-oracle author. Only these three case inputs were read for expectations:

| Input | SHA-256 |
| --- | --- |
| `input/scenario.md` | `747540943b00d1c8ddfb4fcabc90c609c494522c25d8d5a6a2c816b2e465873e` |
| `input/raw-data.json` | `d28ffee6457c1d8ebcde1d5e756f10771ec42b4d76c844e582cd1c981ce94d9c` |
| `input/repo/adjustments.csv` | `43b062327e2ff07db032b1b2ceb7c31f4aa6b1c69b2ac801bb18baf3b284ba6e` |

The parent clarified the customer-month population and customer-key encoding before freeze and appended those exact choices to the scenario. This is a synthetic test contract, not customer or human business approval. No candidate implementation was used as an oracle, no notebook was executed, and no live system or credential was accessed.

## API and files

`oracle.calculate(raw, adjustments, params=None)` returns a dictionary with:

- `invoices`: every current nondeleted invoice, including the draft and March record; one row per tenant/invoice, sorted by those keys. Customer identity includes its tenant and historical validity start.
- `customer_months`: all current invoices grouped by tenant/customer/month, sorted by those keys. There is deliberately no segment on this model.
- `revenue`: selected posted invoices grouped by month and invoice-date historical segment; invoice count, net/paid/outstanding cents, and weighted payment rate.
- `retention`: distinct tenant/customer/month/segment rows having a selected posted invoice with positive net cents, plus `first_paid_month`. Sorted by tenant/customer/month/segment. A month can contain more than one segment for a customer; no single-segment allocation policy is invented.
- `executive`: selected posted invoices grouped by month/segment, with net/paid cents, weighted payment rate and separate `invoiced_active_customers` and `paying_active_customers` counts. These counts use the two conflicting source definitions; they are not renamed into one canonical active-customer metric.

`adjustments` is CSV text or a list of dictionaries using the four uppercase CSV field names. It is never interpreted as a filesystem path. Passing no source (`None`), a missing header, duplicate tenant/invoice keys, or unknown current invoice references raises `OracleContractError`. A present, valid header with zero rows is distinguishable from missing content; omitted adjustments for valid invoices are zero as specified.

Parameters are `tenant`, `start_date`, `end_date`, `segment`, and `authorized`. Omitted values use A, January 1 inclusive to March 1 exclusive, ALL, and the authorized local persona. Explicit `tenant=None`, unsupported tenants, and `authorized=False` fail. Authorization here is an explicit simulation input, not a warehouse or Omni security assertion. Exact segment names filter rows; an absent segment value in the data yields empty reports. Invalid dates and reversed windows fail. Equal date endpoints are an empty window. Optional `what_if_multiplier` must be finite but has no effect on shared rows or reports.

`expected_rows.json` holds the two full gold row sets. `expected_reports.json` holds 13 valid scenarios and five error scenarios; valid scenarios include defaults A, tenant B, January, February, the February 1 boundary, SMB and Enterprise for both tenants, two empty windows, a zero-revenue window, and the retained what-if multiplier. There are **10 invoice rows, 10 customer-month rows and 69 report rows** across the 13 valid scenarios. All grouped empty reports are `[]`; the zero-revenue invoice remains a report row with zero amounts and null rate.

All field names are lowercase. Dates and month starts are ISO strings. Cents/counts are exact integers; activity flags are booleans. Ratios are `Decimal` at 50-digit precision in memory and decimal strings in JSON; null ratios remain JSON null. Compare keys, dates, flags, cents and counts exactly. Use at most **1e-12 absolute tolerance** when comparing a target's floating-point ratios. Sorting is deterministic for convenience; key-based reconciliation must still detect duplicates, missing keys and extra keys. No tolerance may mask a missing row, changed population or incorrect count.

## Business interpretation

CDC selects maximum source sequence within each tenant/business key before applying tombstones. Full duplicate records are replay; any differing payload at the same sequence fails, including a conflicting older version. Payment amounts are summed independently at tenant/invoice grain before joining facts. Missing payment totals are zero. Current payment and adjustment references must point to retained invoices; references to deleted invoices are treated as orphan current references in this bounded oracle.

History exact replays deduplicate. Null keys, invalid or overlapping intervals, and invoices without exactly one history match fail. Invoice dates use calendar-date comparisons with inclusive start and exclusive end. `customer_key` is `tenant|customer|valid_from`, using the scenario's no-pipes identifier assumption. A/C1 is SMB in January and Enterprise exactly from February 1.

Net cents equal amount plus signed adjustment; outstanding cents equal net minus paid without clamping. No payment status, currency conversion, payment-event timestamp, or retention percentage is invented. Invoice status is compared exactly to `posted`; this scenario does not prescribe additional status normalization.

Customer-month net and paid amounts sum **all current statuses**. Its two activity flags are existential tests over individual posted invoices, not tests of a possibly cancelling month-level sum. `first_paid_month` is the earliest posted invoice-date month with positive current paid cents across the complete snapshot, before report filtering. It is an invoice-based cohort proxy at the stated watermark, not historical payment-event retention. The draft-only A/C3 February row remains with 6,000 net cents, both activity flags false and no first-paid month.

## Independent verification and controls

Executed `oracle.py` with `/private/tmp/dma-e2e-env/bin/python` (Python 3.12). The self-checks compare every invoice's monetary values, segment and month to hand-reconciled literal controls; compare every customer-month amount/activity/cohort tuple to separate literal controls; verify historical keys; and compare grouped payment rates to exact `Fraction` arithmetic.

Manual report controls:

| Tenant/month/segment | Invoice count | Net cents | Paid cents | Invoiced active | Paying active |
| --- | ---: | ---: | ---: | ---: | ---: |
| A / January / Enterprise | 1 | 5,000 | 0 | 1 | 0 |
| A / January / SMB | 2 | 20,000 | 14,000 | 2 | 2 |
| A / February / Enterprise | 1 | 7,000 | 7,000 | 1 | 1 |
| A / February / SMB | 2 | 7,000 | 1,000 | 1 | 1 |

A's default totals are 39,000 net and 22,000 paid cents, weighted rate 22/39. B's are 50,500 net and 35,000 paid cents. The default retention detail has five rows. Shared outputs remain identical under an altered what-if multiplier and under reversed input order plus full CDC/history replay.

Negative source probes reject conflicting CDC versions, differing overlapping histories, null keys, duplicated adjustments, absent adjustment content and orphan adjustment references. All five invalid report contexts are rejected with their expected error category. An extra payment proves negative outstanding balances are preserved. Two adjustment errors (+100 on an SMB invoice and -100 on an Enterprise invoice) leave A's total unchanged but change row and segment outputs, proving totals alone are insufficient.

Frozen artifact hashes:

| Artifact | SHA-256 |
| --- | --- |
| `oracle.py` | `b23efe5ecb5f1a1580471aec1e208e1dd1aada34f07d8984b23a77bccd217d13` |
| `expected_rows.json` | `b49d8b2f1584b75155df3103979ff4d15fcba54214910faea345ceac7469f363` |
| `expected_reports.json` | `7ad6c05417c809b8daa955fadcdb561965fc61cede3b7b77a48b7005fdca3cb6` |

The self-checks validate this independent calculation on the synthetic contract. They do not establish Hex extraction completeness, candidate equivalence, native runtime behavior, tenant enforcement, production incremental ingestion, component/version provenance, or business acceptance. Those require separate evidence. After this freeze, use the callable oracle for approved mutation checks without rewriting these expected files to match a target.
