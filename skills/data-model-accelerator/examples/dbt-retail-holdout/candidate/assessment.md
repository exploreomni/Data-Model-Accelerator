# Assessment and placement

The supplied retail project has reusable current-state logic and a defective report join. Preserve the existing `stg_orders` and `stg_order_lines` bytes; normalize fulfillment and return events independently; aggregate each child collection to tenant/order/line before joining. This prevents multiplying ordered quantity, discounted line net, fulfillment and refunds. Confidence is high for the supplied synthetic scope, supported by hand-derived fixtures and actual local native dbt execution; general migration behavior is unqualified.

## Evidence and authority

The [source graph](source-graph.json) retains the original model IDs, full dbt/Jinja expressions, hashes and source references. The canonical source inventory covers eight files, three SQL models and four sources. An inline specialist pass was used because this task prohibited nested agents. It is an author pass, not independent source or semantic QA. The four-object, 30-column [catalogue](evidence/catalogue/warehouse-catalogue.json) is a frozen authored Snowflake declaration with scoped receipt exports, not a live account observation. All 15 input-manifest files passed byte/hash checks.

The supplied README and contract explicitly request correction of independent-child fanout. They establish intent for this synthetic trial; they are not a human production approval. Legacy inflated numbers are evidence of the defect and were never used as expected output. Private acceptance outputs, prior targets and root test output were not read.

## Compatibility and correction

| Rule | Observed source | Final disposition |
|---|---|---|
| Current orders | Highest SEQUENCE by tenant/order, then tombstone removal; date cast and ORDER_KEY | Reuse source SQL byte-for-byte; validate ambiguous versions and input before accepting output |
| Current lines | Highest SEQUENCE by tenant/order/line; quantity × price − total discount once | Reuse source SQL byte-for-byte; preserve LINE_NET_CENTS without applying discount again |
| Fulfillments and returns | Raw child joins within report can multiply one another | New silver current-event models and separate line aggregates inside gold; correction required by frozen input |
| Fact population | Report has selected tenant/date/status/product | Fact retains all current lines; selection is retained only in downstream analysis/semantic contract |
| Rate | Fulfilled divided by ordered at selected grouping | Ratio of sums; unrounded, NULL at zero denominator; totals recompute |
| Authorization | Source WHERE is a SQL variable | Local caller-context guard only; production principal membership and Omni access policy remain unresolved |

Missing child rows mean zero quantity/refund; this is a fact-level absence rule. A report with no selected rows returns an empty list, not a fabricated zero row. Refunds may exceed line net and produce negative retained revenue. No currency conversion, timezone conversion, reporting-calendar dimension, product dimension or SCD history is invented: the contract supplies USD cents and current date-only attributes.

## First-pass architecture finding

The author initially emitted the filtered report as an enabled `REPORTS.RETAIL_FULFILLMENT_SUMMARY` view. Although 14 author tests and the earlier six-model/60-test native run passed, a parent architecture review found that an ordinary dbt build would materialize interactive report context upstream. Those tests had covered numerical behavior without proving placement.

Before changes, all 55 existing solution/evidence files were copied and hashed. [architecture-finding.json](evidence/architecture-finding.json) binds the original snapshot archive. The query was then moved into `dbt/analyses/retail_fulfillment_summary.sql`; the report model/YAML schema entry was removed, and the evaluator, native analysis check and documentation were updated. The final native full-build denominator is five models plus 52 tests. An actual catalogue query verified that there is no REPORTS relation. This is a recorded first-pass failure and correction, not an oracle-driven adjustment or a clean-first-pass claim.

## Boundaries and decisions still open

The evaluator rejects the full malformed capture before output; dbt SQL adds ambiguity, null/value, reference, coverage and balance assertions. Direct dbt invocation alone is not the complete input-validation boundary: the supplied raw gate also enforces exact field sets, native Boolean/integer types, alphanumeric identifiers and canonical date strings. No durable quarantine, production scheduling, transactional publish, service principal, access grants, SLA, retention policy or business/operational owner was supplied. These are explicit deployment gates in [decisions.json](decisions.json), not missing columns to fill with assumptions.

The author's native/evaluator comparison tests two execution paths of the same candidate definitions; it does not independently establish business truth. Hand-derived microfixtures and negative controls provide additional local evidence. Independent withheld evaluation belongs to the parent and is not claimed in this package.

## Packaging finding

The author validator pins the provided local dbt executable and skill-verifier path, and the local profile pins the candidate database path. This makes the authored receipt reproducible at the original location but does not establish relocation portability. Parent review identified this after business comparison. The author executable snapshot remains frozen; the parent owns a separately recorded relocation-only patch and replay. No portable-copy pass is claimed in this author package.
