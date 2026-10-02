# Power BI M, DAX and report context to Omni

The native candidate comprises `invoices.view`, `customers.view`, `relationships` and `billing.topic`. [report-context.json](../target/omni/report-context.json) is **nonnative local metadata** selecting outputs, filter bindings, row policies and the disconnected Scenario calculation. It is not a Power BI parser, an Omni workbook, or proof of native visual behavior.

## Source preparation and relationship

Source Invoices and Customers are Import M partitions backed by native Snowflake SQL. Shared CDC/payment/history/adjustment normalization becomes silver and gold. M Net Cents/default and Date.StartOfMonth become gold expressions; the DAX Outstanding Cents calculated column becomes a gold row expression. Source Scenario is disconnected with Multiplier values 1 and 2; it does not become a warehouse fact or customer relationship.

Source `Invoices[Customer History Key]` relates many-to-one to `Customers[Customer History Key]`, active and single-direction. Source measures are homed on Scenario to avoid same-table column/measure name collisions. The candidate uses effective CUSTOMER_KEY plus TENANT_ID in an always-left many-to-one relationship. Report segment grouping/filtering targets `customers.segment`, preserving source dimension propagation. Missing/inactive/ambiguous relationships are unsupported, not guessed.

## Measure mapping

| Source measure on Scenario | Native Omni candidate | Context / BLANK requirement |
|---|---|---|
| Revenue Cents | `invoices.revenue_cents`: SUM invoice net | Current ordinary report filters; empty SUM remains NULL. |
| Paid Cents | `invoices.paid_cents_total`: SUM invoice paid | Current filters; preserve NULL on no values. |
| Outstanding Cents | `invoices.outstanding_cents_total`: SUM invoice outstanding | Signed amounts, current filters, no aggregate COALESCE. |
| Payment Rate | Paid sum / NULLIF(revenue sum,0) | Ratio of sums; zero or BLANK denominator yields NULL. |
| All Segment Revenue Cents | Native LOD SUM with `always_exclude: [customers.segment]`, selective segment filter cancellation, outer MIN | Remove only segment grouping/filter; retain month, date, status and both tenant security scopes. |
| Share All Segments | Revenue / NULLIF(all-segment revenue,0) | Denominator includes nonselected segments; no visible-mark or all-month total. |
| Posted Revenue Cents | SUM net with posted filter and `cancel_query_filter: true` | Replace only ordinary status selection; draft selection can still yield posted value. |
| Posted Intersection Cents | SUM net with posted filter without cancellation | Intersect with ordinary status; draft conflict yields no values/NULL. |
| Scenario Revenue Cents | Local selected-value multiplier presentation contract | Sole selected 1/2, otherwise alternate 1; blank revenue stays blank. Dynamic native control mapping is unverified. |

[Documented] Omni supports measure SQL references/arithmetic and aggregation declarations. The candidate uses uncoalesced sums and NULLIF, but native SQL generation and empty-result behavior require tests. [Official measure SQL](https://docs.omni.co/modeling/measures/parameters/sql), [aggregation types](https://docs.omni.co/modeling/measures/parameters/aggregate-type).

[Documented] Omni selective filter cancellation can replace a query filter with a measure's filter; without cancellation, conflicting measure/query filters intersect. An empty `is` value with cancellation removes a named filter. This supports the declared status replacement/intersection candidates. No tenant field is canceled. [Official cancel_query_filter](https://docs.omni.co/modeling/filters/operators/cancel-query-filter).

[Documented] Measure LOD supports grouping exclusion and selective filter cancellation. The all-segment candidate removes `customers.segment` from the inner grouping and filter, while MIN exposes the contextual sum at the outer query grain. The native join/subquery behavior when selected outer facts are empty remains unverified; local replay evaluates the modified context independently. [Official measure LOD](https://docs.omni.co/modeling/measures/parameters/level-of-detail).

## Report and total behavior

Revenue Trend and Segment Share enumerate month/segment keys having visible selected fact rows. Empty selections give no grouped rows. KPI Totals has no grouping, always returns one row and recomputes each measure in its own context. It must not sum displayed ratios or repeated denominator values. If only the selected segment is empty, all-segment revenue may still be populated; if status is draft, posted replacement may still return posted revenue while posted intersection is blank.

Security is applied independently before ordinary date/segment/status filters and remains active during every measure change. The native topic binds **both** invoice and customer tenant fields to user attribute tenant_id. Local role/persona matching requires TenantA/A or TenantB/B and explicit authorization; this is not actual Power BI role membership or Omni user-attribute provisioning. Native access-filter behavior remains unqualified. [Official topic access filters](https://docs.omni.co/modeling/topics/parameters/access-filters).

Report defaults are date `[2026-01-01,2026-03-01)`, segment ALL, status posted and multipliers [1], subject to native report evidence binding. Tenant A is the synthetic role/persona boundary. Reversed/malformed dates, unsupported statuses, duplicate/unsupported multiplier selections, missing or mismatched roles/personas fail. Empty or multiple valid multiplier selections use SELECTEDVALUE alternate 1.

[Documented] Omni spreadsheet calculations run over query results. For a resolved sole multiplier 2, a candidate expression is `=${invoices.revenue_cents} * 2`. The companion's selection helper is nonnative metadata; no native SELECTEDVALUE function, dynamic control binding or native blank multiplication is asserted. Selection defaults, null behavior and native presentation require qualification. [Official calculations](https://docs.omni.co/analyze-explore/calculations).

## Acceptance boundaries

Model/SQL parsing, local guarded execution and independent expected-output checks establish bounded development evidence only. Power BI Desktop/Analysis Services, PBIX/TMDL, DirectQuery/composite models, M folding/refresh, native PBIR rendering/interactions, native Omni LOD/filter/BLANK/total behavior, Snowflake execution and production grants remain unverified. [Placement decisions](placement-and-decisions.json) and [source crosswalk](source-to-target.json) retain unknown business authority and operational ownership.
