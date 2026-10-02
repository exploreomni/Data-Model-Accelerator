# Independent billing oracle

Only `input/raw-data.json` and `input/scenario.md` supplied the business evidence.
No legacy LookML, generated SQL, semantic YAML, migration runner, or target result
was inspected. This is independently specified synthetic expected data, not
business approval or live warehouse/security evidence.

- Raw-data SHA-256: `f345f387c7df7c65d480878dd92c7cab4cfc8454a58843621271c9c9e8388d48`
- Scenario SHA-256: `cef44718d15b689c7a6c6ec15492e3de72503c2eecfc9181fd80fe76bf5602c7`
- 12 invoice arithmetic controls, nine report scenarios, and exact-fraction total-rate controls passed.
- Replay, changed arrival order, source-conflict/currency/history negatives, and three denied personas passed.

## API and output

`recompute(data)` accepts the raw JSON dictionary and returns all 12 current
invoice dictionaries, including the draft, EUR invoice and August dates. It
does not create or assume a target surrogate key. Rows sort lexically by
`(tenant_id, invoice_id)`; identifiers and currency case are preserved. Status is
trimmed/lowercased. `issued_at` is canonical UTC ISO8601 ending in Z;
`invoice_date` is its America/Chicago calendar date.

`report(data, tenant, currency, start_date, end_date, group_by=None, segment=None,
zero_net_only=False)` returns a list of dictionaries. Each has grouping fields,
`invoice_count`, `net_cents`, `paid_cents` and `payment_rate`. Date bounds are
inclusive start/exclusive end. `group_by` accepts a list of invoice identity,
customer, date, tenant, currency, status or segment field names. Results sort
lexically by the requested grouping tuple. A total has one row even when empty;
an empty grouped query has no groups. Missing/unknown tenant persona raises
PermissionError; only A and B are admitted in this local simulator.

Amounts/counts compare exactly as integers. Rates are Decimal at 50
significant digits, exported as strings to avoid binary-float loss; null rates
remain JSON null. Exact Fraction controls independently verify report arithmetic.
When comparing a target floating ratio, use absolute tolerance no larger than
`1e-12`; never apply that tolerance to cents/counts/identity. Money display is
`Decimal(cents) / Decimal(100)` and is separate from all aggregation.

`expected_rows.json` is the complete invoice list. `expected_reports.json` contains
`scenarios`, each with its scenario_id, explicit parameters and expected rows.
The callable recompute/report functions also support independently recomputing
mutated raw input; baseline fixture constants are checked only by main().

## Explicit contract decisions and limits

The unspecified empty-date scenario uses the literal empty half-open interval
`[2026-09-01, 2026-09-01)`. Segment and daily breakdowns are two report scenarios.
No ambiguity affects the supplied numeric results.

Every CDC version is checked for conflicting payloads before latest-version
selection; only arrival_seq is excluded from that payload. DELETE is processed
after version selection. Payments and credits are independently aggregated from
their current posted entries. Currency is validated for those contributing
entries against the latest invoice state, including a retained invoice tombstone.
No posted orphan ledger exists in the supplied data; if a mutation introduces an
unknown invoice reference, the oracle raises an explicit contract error because
orphan treatment is unspecified. It does not invent conversion or allocation.

Customer history is tenant-scoped, start-inclusive/end-exclusive and evaluated
at the UTC issued_at instant; missing history yields Unknown. The oracle rejects
overlapping intervals for a tenant/customer, including duplicate intervals.
Discount null becomes zero; amounts are not clamped. Invoice source sequence,
currency, report date, status and persona are kept as separate concerns.

Local persona rejection is only a functional simulator check. It does not
establish warehouse row-access policy, Omni access enforcement, or production
readiness. No source SQL, macros, external systems or deployment were executed.
