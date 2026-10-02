# Independent Tableau expectation contract

Authored and executed on 2026-09-10 by the independent oracle/QA agent. Before freezing these files, the agent read only `input/scenario.md`, `input/raw-data.json` and `input/repo/adjustments.csv` for expected behavior. It did not inspect the Tableau source, parser, target, execution runner, prior Hex oracle or prior Hex expected outputs. This is a standard-library business-logic reference, not SQL execution or business approval.

## Frozen input provenance

All input evidence is synthetic. The selected platform instance is `DMA_TABLEAU_SYNTHETIC`, catalogue `DMA_TABLEAU`, raw schema `RAW`, at the supplied snapshot `2026-03-02T00:00:00Z`.

| Input | SHA-256 |
| --- | --- |
| `input/scenario.md` | `e897f8c89794d2c8f58db53464da25e8ccbc7441dad838ad9036de75416b6f84` |
| `input/raw-data.json` | `d28ffee6457c1d8ebcde1d5e756f10771ec42b4d76c844e582cd1c981ce94d9c` |
| `input/repo/adjustments.csv` | `43b062327e2ff07db032b1b2ceb7c31f4aa6b1c69b2ac801bb18baf3b284ba6e` |

## API and row contract

`calculate(raw, adjustments, params=None)` returns `invoices`, `revenue_trend`, `customer_value`, and `revenue_share`. `adjustments` is either complete CSV text or a list of dictionaries with the declared uppercase fields; it is never an executable path. A present header-only CSV or an empty list means zero adjustment rows. Missing content is an error. Inputs are not mutated.

Invoice fields are `tenant_id`, `invoice_id`, `invoice_key`, `customer_id`, `customer_key`, `invoice_date`, `invoice_month`, `status`, `segment`, `amount_cents`, `adjustment_cents`, `net_cents`, `paid_cents`, and `outstanding_cents`. The complete fact contains all 10 current nondeleted invoices, including draft and out-of-report-window records. It is independent of report parameters and sorted by tenant/invoice. Dates are canonical `YYYY-MM-DD`; the raw contract contains dates, not timestamps requiring a timezone conversion. Status is preserved as supplied; no extra normalization rule is assumed.

Reports use exactly the output fields declared in the scenario. Revenue Trend and Revenue Share sort by month then segment. Customer Value sorts by customer ID then segment. This deterministic comparison order is not a claim of native Tableau tie sorting, densification or layout behavior. Empty windows produce empty arrays, not invented zero marks.

Amounts and counts use exact Python integers. Ratios use Decimal with 50 digits of precision and serialize as strings; comparison permits absolute ratio error at most `1e-12`. Null is required when a denominator is zero. The scenario multiplier uses exact decimal arithmetic; integral results serialize as integer cents. A finite fractional multiplier could produce fractional scenario cents, retained as Decimal rather than silently rounded; the frozen multiplier scenarios are 1 and 2.

Parameter defaults are A, January 1 inclusive through March 1 exclusive, segment ALL, multiplier 1. Selecting A or B uses that tenant's invented fixture persona by default; an explicit `persona_tenant` mismatch fails. This interpretation was confirmed with the coordinating agent before freeze. `authorized=False`, unknown or explicit null tenant, malformed/reversed dates and nonfinite multipliers fail with `OracleContractError.code`. An unknown nonempty segment produces no marks. These are synthetic functional controls, not production authorization.

## Independent arithmetic and semantic checks

The frozen outputs contain 16 valid parameter scenarios, 8 rejected contexts, 10 full invoice rows and 78 report marks across the valid scenarios. Coverage includes both tenants, both segments, January, February, the February 1 history boundary, equal bounds, a later empty window, a zero-revenue day, multiplier 2, paired date-and-segment contexts and an unknown segment.

Before generation, an independent temporary verification script executed 84 assertions: every fact's identity/key, date, historical segment, status and amount components; all default Customer Value marks; all default revenue/share marks against hand-derived sums and Fraction ratios; tenant totals; context/segment combinations; null denominators; multiplier isolation; replay/order invariance; all eight context errors; CDC conflict, history overlap/orphan rejection; and empty adjustment records. These assertions used explicit raw-derived anchors rather than target code.

Consequential anchors:

- Default A has revenue 39,000 cents and paid 22,000 cents. January shares are Enterprise `1/5`, SMB `4/5`; February shares are `1/2` each.
- A/C1's default FIXED customer value is 18,000 cents. Its Enterprise mark selects 7,000 and its SMB mark 11,000, but both retain FIXED 18,000. The repeated values are not additive across marks.
- Selecting SMB preserves A/C1 FIXED 18,000, while each selected month's share becomes 1. Restricting the date context to January changes A/C1 FIXED to 11,000; February Enterprise context changes it to 7,000.
- Default B has revenue 50,500 cents and paid 35,000 cents. Tenant collisions do not combine identities.
- A/I6 remains a draft gold invoice for 6,000 cents, but does not enter datasource-posted report populations. A/I8's latest tombstone removes it. A/I4 binds the February 1 Enterprise customer version. A/I7's zero-net day has null rate and share.

No Tableau rendering, native order-of-operations execution, TDS/TWB equivalence, warehouse/Omni compilation, live catalogue access or production security was used to create this oracle. Those are subsequent independent QA and qualification boundaries. The source's FIXED and WINDOW_SUM definitions remain subject to a business owner's decision before becoming authoritative definitions.
