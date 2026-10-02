# Synthetic SaaS invoice validation case

This is a **local SQLite demonstrator**, built from invented companies, invoices,
and expected outputs. `expected_saas_export.json` is a hand-authored stand-in for
an independently obtained SaaS export, not a real export. No customer data,
credentials, network access, or input-repository SQL is involved.

## Business story and explicit choices

Two tenants, A and B, reuse invoice and customer identifiers. A/C1 is Aster Labs;
B/C1 is Birch Media. Aster changes from Startup to Enterprise on February 1,
2026. The report must retain the segment effective on the invoice's business
date. January 31 is Startup; February 1 is Enterprise. A late invoice dated
January 30 must also remain Startup.

The report contains **current posted invoices**, one row per tenant and invoice.
Amounts are integer USD cents in this single-currency case. Payment rate is
`sum(paid_cents) / sum(gross_cents)` after every report filter. It is not the
average or sum of row ratios. A zero denominator, including an empty population,
produces null; counts and amounts for an empty population are zero. A zero-value
posted invoice still contributes one invoice to the count.

The synthetic source is an append-only delivery log of full after-image CDC
events. `(tenant_id, invoice_id, source_sequence)` identifies a source version;
the highest source sequence wins. Exact replay is allowed, while two different
payloads at the same source sequence must block validation. A tombstone removes
the latest invoice state. Arrival order is not source ordering.

These are **fixture assumptions**, not conclusions an accelerator may infer
from arbitrary repositories. The fixture uses date-only business dates and
complete, non-overlapping customer history. It assumes reliable source sequences
and stable event IDs. It does not establish the correct historical, CDC, or
reporting policy for a real customer.

## Independent expected outcomes

Expected rows, groups, and filtered totals were specified separately in
`expected_saas_export.json`; the harness does not generate them from candidate
SQL. The final row-level expectations are:

| Tenant/invoice | Segment at invoice date | Gross cents | Paid cents | Explanation |
|---|---|---:|---:|---|
| A/I100 | Startup | 10,000 | 6,000 | Corrected source version survives duplicate and late older deliveries |
| A/I101 | Enterprise | 30,000 | 30,000 | February 1 boundary |
| A/I103 | SMB | 5,000 | 1,000 | Draft becomes posted in the second batch |
| A/I105 | SMB | 0 | 0 | Null row ratio; invoice count retained |
| A/I106 | Startup | 40,000 | 10,000 | January 30 event arrives in the second batch |
| A/I107 | Enterprise | 15,000 | 7,500 | Another February 1 boundary record |
| B/I100 | Enterprise | 50,000 | 25,000 | Same invoice and customer IDs as tenant A, different facts and identity |
| B/I104 | Startup | 10,000 | 5,000 | Correction survives an older delivery arriving afterward |

A/I102 originally contributes 20,000 gross and 10,000 paid cents. Its later
tombstone removes it. Batch-one validation also proves that draft A/I103 is
excluded before its status change.

The final all-tenant totals are 8 invoices, 160,000 gross cents, 84,500 paid
cents, and a 0.528125 payment rate. Tenant A's Startup filter selects two rows:
50,000 gross cents, 16,000 paid cents, and a 0.32 payment rate. Averaging those
rows' 0.60 and 0.25 ratios would incorrectly yield 0.425.

## What the harness proves locally

`candidate.sql` defines a latest-source-version view and an effective-dated,
tenant-keyed invoice fact view. `report_rows.sql` defines posted-only row output
with tenant, segment, month, and invoice filters. The harness aggregates that
filtered population and compares it with the independent expected fixtures.

The 23 registered checks cover input contracts, conflicting source versions,
exact duplicate deliveries, history overlap, initial and final row outputs,
composite grain, exactly one temporal dimension match for each current invoice,
grouped outputs, seven filter scenarios, weighted ratios,
functional tenant isolation, effective-date boundaries, late arrivals, deletes,
replay, and full rebuild equivalence. Completion requires the exact registered
check sequence; missing checks or unexpected mismatches produce a failed report
and a nonzero CLI exit.

Five deliberate SQL mutations must be rejected:

1. Removing historical join boundaries creates fanout and duplicate invoice keys.
2. Removing the tenant join key exposes another tenant's customer attributes,
   even when the report filters on the invoice tenant.
3. Dropping the segment filter still passes the unfiltered row export but fails
   filtered totals and population expectations.
4. Selecting the latest delivery instead of the latest source sequence loses a
   correction when an older event arrives late.
5. Removing tombstones before ranking resurrects a deleted invoice.

`legacy.sql` intentionally contains the last two CDC mistakes and uses the
current customer segment for historical invoices. It passes a narrow tenant B
January gross/paid smoke report, while wider row-level evidence catches its
defects. A single matching dashboard total is therefore inadequate in this case.

## Run from the repository root

```sh
python3 skills/data-model-accelerator/scripts/validate_example.py --output /tmp/data-model-accelerator-example.json
python3 -m unittest discover -s tests -p 'test_validate_example.py' -v
```

The script also resolves its bundled examples correctly when launched from
another working directory. Its only CLI option besides help is an optional
local JSON output path. There is no option to execute supplied repository SQL.

## Evidence boundary and remaining work

Replay and rebuild checks cover append-only ingestion into an in-memory SQLite
log with views that recompute the result. They **do not** validate an incremental
MERGE implementation, a deployed ingestion connector, watermark recovery,
schema evolution, incomplete after images, or concurrent production loads.

Tenant filtering and join assertions are **functional isolation probes only**.
They do not implement or prove warehouse authorization, row access policies,
masking, service-account isolation, or resistance to arbitrary user queries.

Snowflake, Databricks, BigQuery, dbt, and Coalesce compilation and execution,
real source lineage and exports, real CDC and history semantics, warehouse RLS,
performance, cost, observability, reconciliation tolerances, and production
acceptance remain unverified. Production use needs independent source evidence
and the appropriate platform checks and human decisions; a passing example does
not grant deployment approval.
