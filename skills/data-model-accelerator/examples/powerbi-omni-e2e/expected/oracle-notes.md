# Independent Power BI expectation contract

Authored and executed on 2026-09-11 by the independent oracle/QA agent. Before freeze, the agent used only this case's `input/scenario.md`, `input/raw-data.json` and `input/repo/adjustments.csv`. It did not inspect the new source, target, parser/runtime, or any prior pilot's oracle/expected files. Reuse of invented billing records is intentional; the Power BI report expectations were independently derived from this scenario. The coordinating agent confirmed the local role/persona default interpretation. Expectations were not shared with the source or target authoring agents.

This oracle is standard-library Python business logic, with no SQL/DAX translation or target imports. It is synthetic validation evidence, not business approval or native Power BI execution.

## Input provenance

The declared source context is account `DMA_POWERBI_SYNTHETIC`, catalogue `DMA_POWERBI`, raw schema `RAW`, at snapshot `2026-03-02T00:00:00Z`.

| Input | SHA-256 |
| --- | --- |
| `input/scenario.md` | `22bf742a262cca14cdab43e8c0b4bd87f89a24139f5834583289869a04e5b291` |
| `input/raw-data.json` | `d28ffee6457c1d8ebcde1d5e756f10771ec42b4d76c844e582cd1c981ce94d9c` |
| `input/repo/adjustments.csv` | `43b062327e2ff07db032b1b2ceb7c31f4aa6b1c69b2ac801bb18baf3b284ba6e` |

## API and serialization

`calculate(raw, adjustments, params=None)` returns `invoices`, `revenue_trend`, `segment_share` and `kpi_totals`. Adjustment input is complete CSV text or a list of records with the exact uppercase fields, never a path. Present header-only CSV/empty records mean zero adjustments; missing content, duplicate keys and orphans reject. Inputs are not mutated.

The full gold invoice list has 10 rows, sorted by tenant/invoice, with these 14 fields: `tenant_id`, `invoice_id`, `invoice_key`, `customer_id`, `customer_key`, `invoice_date`, `invoice_month`, `status`, `segment`, `amount_cents`, `adjustment_cents`, `net_cents`, `paid_cents`, `outstanding_cents`. It includes all current nondeleted statuses and remains independent of report parameters. This full-model validation output is not a role-filtered result served to a user. Segment comes from the exact invoice-date customer version. Dates are canonical date strings; raw inputs do not supply timestamps requiring timezone conversion. No extra status normalization is assumed.

Grouped visuals sort by month then historical segment and enumerate only visible selected fact keys. KPI Totals always contains exactly one row, even when grouped outputs are empty. Each report uses the scenario's exact output keys.

Cents are exact Python integers. JSON null represents BLANK, distinctly from zero. Ratios use Decimal precision 60 and serialize as strings; comparison permits absolute error at most `1e-12`. Neither division by zero nor a blank numerator/denominator produces a numeric ratio. Multipliers must be a unique subset of integer `[1,2]`; booleans and floats are rejected. Exactly one selection supplies its scalar; none or multiple selections use alternate 1. Scenario cents remain exact integers or BLANK.

Report JSON uses `scenarios: [{name, parameters, outputs}]` and `invalid_scenarios: [{name, parameters, expected_error_code}]`. Errors use `OracleContractError.code`. Omitted parameters use report defaults. Choosing tenant B alone selects invented TenantB/B role/persona; explicit null, unknown or mismatched role/persona/tenant rejects. This is a synthetic harness binding, not service membership or RLS enforcement. Segment accepts a string, with ALL removing the ordinary segment predicate; an unknown or empty string may produce no selected facts.

## Context semantics and independent checks

The frozen set contains **22 valid scenarios, 16 rejected contexts, 10 full fact rows and 88 report rows**. It covers both tenants/segments, date boundaries, zero and empty results, unknown segment, draft contexts, SELECTEDVALUE selections, recalculated totals and separate status replacement/intersection behavior.

Before generating the JSON files, an independent temporary verification script executed **243 assertions**. It checked every full fact's keys, date, historical segment, status and money components against raw-derived explicit anchors; every valid scenario's KPI fields, row counts and Fraction-derived ratios; default grouped marks/denominators; repeated-denominator versus total behavior; replay/order invariance; all rejected contexts; CDC conflict, history overlap/orphan, null identity, missing/duplicate/orphan adjustment handling; empty adjustments; negative balances; and integers beyond binary floating-point precision. No candidate outputs informed those checks.

Consequential anchors:

- Default A: revenue 39,000, paid 22,000, outstanding 17,000 cents. KPI payment rate is `22/39`, recalculated from totals. The default visual repeats month denominators whose sum is 78,000, while the correct KPI all-segment denominator is 39,000.
- Selecting SMB: revenue 27,000 and all-segment denominator 39,000; KPI share is `9/13`. January/February mark shares remain `4/5` and `1/2`, because REMOVEFILTERS clears segment but preserves each mark's month.
- Draft A: ordinary revenue is 6,000, Posted Revenue replaces status and returns 39,000, while Posted Intersection is BLANK.
- Draft A with SMB has no selected facts. Its ordinary totals are BLANK, all-segment revenue is 6,000, Posted Revenue is 27,000, and Posted Intersection remains BLANK. Draft B similarly has no ordinary facts but Posted Revenue is 50,500.
- An unknown segment produces empty grouped visuals and BLANK ordinary KPI measures, but all-segment revenue remains 39,000. A truly empty date window makes every KPI measure BLANK. The February 20 zero-net invoice instead produces numeric zero amounts and BLANK ratios.
- Selection `[2]` doubles scenario revenue to 78,000 without changing other measures. `[]`, `[1,2]` and reversed selection `[2,1]` use alternate 1.
- A/I8's latest tombstone removes it; A/I6 remains a draft gold invoice; A/I4 binds the February 1 Enterprise history version. Tenant collisions never combine identities.

Native M, DAX, relationship propagation, modeled roles, PBIR rendering, metadata authenticity and candidate implementations are subsequent QA subjects. PBIX/TMDL, native Desktop/Analysis Services, Snowflake/Omni execution, refresh/folding, production security and operational acceptance remain unqualified. Run `oracle.py --generate` only before freeze; subsequent QA must preserve these expected artifacts.
