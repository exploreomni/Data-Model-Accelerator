# Downstream report and Omni handoff

Native source ID: `model.retail_quick_reports.retail_fulfillment_summary`. Proposed consumer ID: `analysis.retail_candidate.retail_fulfillment_summary`. The [analysis](../dbt/analyses/retail_fulfillment_summary.sql) produces the exact nine-field report interface. It is not an enabled model and an ordinary dbt build creates no report table/view. [omni-handoff.json](omni-handoff.json) is explicitly target-neutral companion metadata suitable for an Omni author, not native Omni YAML or a deployed workbook.

| Output | Source fact field | Query rule | Type / units / null |
|---|---|---|---|
| ORDER_MONTH | ORDER_DATE | DATE_TRUNC month, cast DATE; grouping dimension | Calendar DATE, month first day; required on returned rows |
| PRODUCT_ID | PRODUCT_ID | Group current product | VARCHAR identifier; required |
| ORDERED_QUANTITY | ORDERED_QUANTITY | SUM | Exact integer item quantity; required |
| FULFILLED_QUANTITY | FULFILLED_QUANTITY | SUM | Exact integer item quantity; required |
| RETURNED_QUANTITY | RETURNED_QUANTITY | SUM | Exact integer item quantity; required |
| LINE_NET_CENTS | LINE_NET_CENTS | SUM; discount already applied | Exact integer USD cents; required |
| REFUND_CENTS | REFUND_CENTS | SUM | Exact integer USD cents; required |
| RETAINED_REVENUE_CENTS | RETAINED_REVENUE_CENTS | SUM, may be negative | Exact integer USD cents; required |
| FULFILLMENT_RATE | FULFILLED_QUANTITY and ORDERED_QUANTITY | Ratio of sums; NULLIF denominator zero | Unrounded unitless numeric, local double; NULL at zero denominator; tolerance 1e-12 |

Apply caller authorization independently from query filters. Select tenant, date window, status and optional product before grouping; recompute sums and the ratio for totals. No visible row means an empty grouped report. No currency scaling, formatting, multi-currency conversion or timezone behavior is supplied. Display labels, sorting and exports are downstream: local comparisons sort ORDER_MONTH then PRODUCT_ID; production presentation remains to be authored and validated.

Default context is tenant A, [2026-04-01,2026-04-04), status completed and product ALL. Report tenant must be A/B; status completed/pending/cancelled. Any string is a product selector, with ALL removing that predicate. Canonical valid ISO dates are required, end exclusive; equal bounds select an empty population, reversed bounds reject. Values are SQL literals with apostrophe escaping, not interpolated raw SQL.

An omitted persona defaults to the selected tenant **only in this synthetic harness** because the README distinguishes a caller-supplied persona. An explicitly supplied null or mismatched persona rejects. `authorized` defaults true only when omitted; explicit false, null or non-Boolean truthy values reject. An explicitly null tenant/date/status/product does not receive an omission default. Production principal/role membership, user attribute binding and row-level enforcement remain unresolved. A caller-controlled persona or SQL WHERE variable must not be exposed as an actual access-policy substitute.

Original source expressions, references and hashes are in [source-graph.json](../source-graph.json); upstream/distributed target edges are in [target-lineage.json](../target-lineage.json). Source staging and definition meanings are preserved, while the known source fanout and the first candidate's context placement are explicitly corrected. No Omni-native syntax or runtime equivalence has been externally verified in this offline task. Native qualification must exercise field SQL, source grain, default/override behavior, empty results, weighted totals and positive/negative personas against the exact accepted warehouse version.
