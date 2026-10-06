# Independent Omni Modeler qualification corpus

Prepared 2026-10-05 for plan 17. This directory contains newly invented inputs and independently calculated expected results. No customer source, training example data, earlier delivery, or generator output was used as an expected baseline. The small native YAML inputs were written by hand. The local vendor reference supplied only syntax shapes for query-field mappings, SQL view references, filter operator objects and topic-scoped extended views.

This is a **data-only test contract**, not a production implementation or native qualification. No network calls, deployment, credentials, installed-skill edits or approvals were used. All bindings, identifiers and review claims are synthetic. `context.json` conforms to the existing `omni_model_context` API; its catalogue and column evidence are explicitly synthetic fixture hashes. Never describe them as observed tenant schemas.

## Entry points and fixture contract

- `corpus.json` defines tables, grains, nulls, arithmetic and business semantics.
- `cases.json` selects inputs and expected results for 13 cases. Its `files` keys are native basenames and values are relative storage paths. Read those bytes into a plain `dict[str, str]`, then use the existing `check_model(files, context)` API. For example, `source/auth_noop_orders.view` must be passed as `orders.view`.
- `data/` contains actual CSV rows, including three isolated mutation files. An append or replacement applies to a fresh copy of the baseline. Never apply variants cumulatively unless a test explicitly says so.
- `expected/` contains hand-calculated order rows, query rows, integer totals, exact rational values, counterfactual results and source-scope expectations. JSON pointers in the case contract address these objects.
- `authorization_scenarios.json` supplies concrete synthetic intents, targets, claims and expected zero-call outcomes. The later driver should materialize the current request/policy schemas in temporary directories. There is no credential or operational approval artifact here.
- `FROZEN_SHA256.json` binds every corpus file except itself. Hashes prove integrity of the prepared fixture, not approval or independence by themselves. Amend expected results only with a separately reviewed explanation; do not regenerate them from implementation output.

All money is integer cents. Blank CSV cells are SQL NULL. JSON rational objects contain an exact numerator and denominator; they are not rounded decimal comparisons. A zero denominator produces NULL. Dates are ISO dates without timestamp conversion. Result-row order matters only where the expectation states an explicit sort; compare keyed rows otherwise.

## Why the rows are uneven

Six orders have six lines and four return events. One line has two separately priced returns; another order has two lines; a paid order has no lines; two different lines have equal amounts. Ordinary joined sums, `SUM(DISTINCT amount)`, dropping empty orders, and reconstructing refunds from quantities each produce an observable error. Baseline paid gross is **7,000**, paid refunds **5,400**, and paid net **1,600**. Their aggregate refund ratio is **27/35**, distinct from both the sum and average of per-order ratios.

The same three synthetic parties occupy buyer and seller roles. Buyer paid amounts are Amber 6,500 / Teal 500 / Indigo 0; seller amounts are Amber 0 / Teal 2,500 / Indigo 4,500. Collapsing either role onto the other cannot pass.

The customer-history lookup uses half-open date intervals. An order exactly at the change date belongs to the new segment. Current-segment and as-of totals intentionally differ. Appending the overlapping history row creates two matches for one order; that must block temporal qualification instead of choosing a winner or silently multiplying money. A static relationship declaration alone cannot discover this row-level defect.

The filtered-measure fixture queries total and paid values together. All shipping remains 1,050 while paid shipping is 350 and their ratio is 1/3. Applying the paid condition to the entire query would erase the control population. `order_lines.paid_gross_cents` also uses a qualified filter reference to a joined view, separate from the same-view bare filter reference.

## Later executable test sequence

1. Verify all frozen hashes and load CSVs into an in-memory SQLite or DuckDB database. Check declared keys and foreign keys. Keep numeric and date semantics explicit.
2. Calculate line totals grouped by order. Independently join return events to line identities and group refunds by order. Left-join those two aggregates to orders, then attach buyer, seller and temporal lookups. Compare every output row with `expected/orders.csv`, not just grand totals.
3. Check all metric populations, grouped role totals, temporal segments and ratios. Confirm the deliberately wrong totals in `wrong_answer_sentinels` differ from the accepted answer. These sentinels diagnose common errors; they are not acceptable alternative results.
4. Apply the extra-return and price-change variants separately. Re-run the same calculations. Extra returns change refund measures without changing gross sales, counts or shipping. The price change changes sales without changing refunds. This prevents a memorized baseline total from passing.
5. Check source inventory and typed IR independently of generation: native `.query.view` identity; query-field mapping output names; SQL view dependencies; unknown-node preservation; alias scope; authored versus effective origin. Use `expected/source_semantics.json` as the semantic oracle rather than an implementation-specific object dump.
6. Use the authored YAML inputs as inputs to supported static checks. `orders_by_customer` groups orders by customer; its five expected outputs are in a literal CSV. `returns_by_order` groups return events by order and has three rows. Executing an independently expressed local SQL oracle does not prove Omni compiles either native form. Query/SQL generation must remain unsupported until its support is implemented and tested.
7. Mutate the query output mapping to remove an alias while retaining the dimension. Demand an unresolved-output result; do not bind it to an invented physical column. Test limit/sort behavior as an explicit adapter operation once its API exists. The top-one customer result must be marked incomplete, and its 450 shipping amount must not be promoted to the full-population 1,050.
8. Run isolated unknown-key, templated-SQL and duplicate-key variants. A valid-but-unsupported construct must remain preserved and explicitly unsupported; duplicate YAML keys are invalid. No-op exports must match source bytes, including comments. Ordinary diagnostic output must not include the synthetic opaque marker.
9. For scope handling, a no-op returns the corresponding authored bytes unchanged. The requested label replacement emits only the authored presentation override shown in `expected/authored_label_patch.view`. Do not emit inherited tables, fields or measures. A listed explicit file deletion belongs in the proposed diff; an omitted inherited definition is not a deletion. Deletion has no native authority in this corpus.
10. Finally, run authorization no-ops with a recording transport and valid unrelated preconditions. Check calls and remote bytes, not only a returned status. Missing approval, a self-declared synthetic approval, a stale candidate attestation, an unpermitted destination and production target must never mutate remote state. The fixture's instance string is an offline schema input; it must never be contacted. Test-only issuer material, if required, is created in memory and discarded.

The first executable driver should be a new independent test module after the foundation API is complete. Do not modify existing tests to accommodate the fixture. Supported capability assertions may tighten as implementation arrives; none should silently change unsupported into native-verified. A native API receipt, effective security test, business acceptance and deployment approval remain distinct future evidence lanes.

## Preparation checks actually run

Using the repository-adjacent guided-delivery virtual environment's Python, an inline, independent SQLite calculation checked **34 assertion groups** over the hand-written expected rows/totals, role partitions, measure-local populations, two independent counterfactuals and overlap matches. It wrote no expected files. Outcome: passed. Runtime: Python **3.12.14**, SQLite **3.53.1**.

A separate read-only call to `omni_contract.check_model` used the two `source/auth_noop_orders.*` files mapped to `orders.view` and `orders.topic`, with `context.json`. Contract: `omni-static-v1-2026-10-05`. Outcome: **passed**, no findings, `native_verified: false`, `security_verified: false`. This verifies the authorization baseline reaches beyond static input rejection; it does not run the authorization scenarios yet.

The preparation commands were Python heredoc invocations from the repository root: one imported `csv`, `sqlite3`, `json` and `Fraction` to compare independently expressed SQL results with literal expectations; the other imported `omni_contract` and invoked the unchanged public checker. No generator was used. The freeze step only computed file hashes and validated JSON/path references.

Remaining gaps: executable integration with the new inventory/IR/role-task APIs; extended static behavior; authentication no-op execution with the recording transport; query-sort/limit adapter syntax; and every native or tenant qualification. The source relationship's many-to-one label is a hypothesis qualified only by baseline rows; the overlap variant intentionally falsifies it. There is no claim of complete Omni modeling coverage.
