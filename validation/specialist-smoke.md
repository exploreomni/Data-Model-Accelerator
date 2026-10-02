# Mixed dbt and Looker specialist exercise

Executed September 9, 2026, in the current Codex task. Inputs were six deliberately synthetic files under [examples/mixed-projects](../skills/data-model-accelerator/examples/mixed-projects). No customer files, source rows, credentials or warehouse connection were used.

The planner identified one dbt project and one Looker project, assigned all six files, and reported zero inventory gaps. The orchestrator then invoked two actual native subagents, each restricted to its three assigned files. The planner alone did not perform that dispatch.

| Source | Actual task | Assets interpreted | Objects | Rules | Unresolved references | Declared gaps |
| --- | --- | --- | --- | --- | --- | --- |
| dbt | `dbt-ae1fd358c761` | 3 | 3 | 5 | 2 | 5 |
| Looker | `looker-d9065d6da185` | 3 | 11 | 11 | 8 | 8 |

The [handoff verifier report](specialist-smoke/verification-report.json) contains zero structural errors. It returns `extraction_complete: false` and exit code 1 because required bindings and other evidence remain missing. Both executions returned; their extraction state is recorded as `partial`. A successful task return is not complete source coverage or a validated business model.

## What the specialists preserved

| Source behavior observed | Proposed placement implication | Evidence still needed |
| --- | --- | --- |
| dbt already computes `gross_cents - coalesce(credit_cents, 0)` at the source row grain | Consider reusing the existing warehouse rule; avoid applying the credit again downstream | Actual grain, numeric types, credit meaning, source completeness and accepted expectations |
| Looker measures sum net and paid values with a measure-scoped `posted` filter | Preserve governed query-time aggregations; the filter does not justify removing other rows from the shared warehouse model | Accepted population, additional query filters and relation bindings |
| Looker computes paid sum divided by net sum with a protected zero denominator | Preserve ratio-of-sums behavior at the selected query grouping | Decimal division, nulls, totals and alternate grouping tests on the chosen target |
| Looker declares a tenant user-attribute access filter | Carry the explicit access contract into semantic and warehouse security design | Identity mapping, grants, exceptional access and permitted/denied persona tests |
| dbt and Looker both reference an invoice-reporting name | Keep the cross-project relation match as a candidate | Connection, database/schema/alias and physical column evidence; a name match is insufficient |

These are an orchestrator synthesis of the returned source findings, not an approved placement plan. Existing upstream work is an input to reuse or improve; source BI definitions are evidence of behavior, not automatic business authority.

## Audit evidence

- [Inventory](specialist-smoke/inventory.json) and [dispatch plan](specialist-smoke/dispatch-plan.json).
- [Actual execution state and output hashes](specialist-smoke/run-state.json).
- [dbt specialist result](specialist-smoke/results/dbt-ae1fd358c761.json).
- [Looker specialist result](specialist-smoke/results/looker-d9065d6da185.json).

These files are a historical audit snapshot. Absolute source/work-folder paths record this execution; generate a new plan to reproduce the exercise in another checkout. Runtime task prompts stayed in the temporary work folder. Archived JSON declarations establish neither authenticated authorship nor approval.

The six files were interpreted by coding agents, without executing repository SQL or invoking dbt/Looker native compilers. Detection and routing for the other six vendors have fixture regression coverage; their native extraction behavior has not been qualified on representative real projects. The fixture lacks a selected target, live data, dashboard query context and user-attribute configuration. Warehouse/semantic architect orchestration and independent full-model QA are specified by the skill; this exercise executed the two source-specialist tasks only.
