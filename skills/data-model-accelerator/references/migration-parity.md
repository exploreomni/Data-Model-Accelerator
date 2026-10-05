# Independent migration comparisons

The validation analyst freezes a comparison plan and source baseline independently of the generated code. `migration_parity.py` compares private captures; it never queries a system or emits row values. Its `locally_consistent` result cannot authenticate a source run, warehouse run, Omni query, rendered browser session or human approval.

```sh
python scripts/migration_parity.py --plan reviewed-plan.json \
  --baseline frozen-source-observations.json --warehouse warehouse-observations.json \
  --omni modeled-omni-observations.json --output new-private-parity-report.json
```

Use exact snapshots, timezone, parameter values, persona and executed query versions across systems. Preserve the source behavior as observed, including a 90-day tile filter intersecting a 30-day dashboard filter, the inclusion or exclusion of today, daylight-saving boundaries, NULL versus zero, pivots, sorting and a 500-row limit. Freeze meaningful boundary cases; do not widen a date filter or remove a limit to obtain a passing comparison. Record proposed business corrections separately and have the SME approve the new baseline before changing it. Partitioning/performance changes need their own benchmark and parity run.

The version-1 `migration_parity_plan` contains:

- `migration_scope`, the six delivery `bindings`, and the whole `baseline_sha256`.
- `inventory` with explicit `data_tiles`, `text_tiles` and `filter_ids`; every selected data tile needs a case. Full-dashboard scope also needs an interaction case for every tile and filter.
- `scenario_requirements`, mapping every data tile to the scenarios the analyst requires, including `baseline`. Add date boundaries, NULL/zero, fanout, orphan keys, tenant isolation, sort/limit truncation and relevant filter combinations; this explicit denominator is not automatically exhaustive.
- `cases`, each with opaque `id`, `kind: data|interaction`, `subject_kind: tile|filter`, `subject_id`, `scenario` and a common `context` of `snapshot_sha256`, `timezone`, `parameters_sha256`, `persona_sha256`.
- For data cases: `queries` mapping source/warehouse/omni to their exact query hashes; canonical `columns` with number/string/boolean/date types; `grain`; `ordered`; `allow_null_grain`; `truncated`; `tolerances`; and `expected_metrics`. Empty grain permits a single aggregate row. Numeric tolerances name the field and give nonnegative `absolute`, `relative` and a reviewable `reason`; omitted tolerances mean exact numeric comparison.
- Required metric counts: `duplicate_keys`, `orphan_keys`, `tenant_violations`, `join_input_rows`, `join_output_rows`. Duplicate keys and tenant violations must be zero. Capture actual join populations before aggregation: equal totals can conceal fanout. A legitimate expansion needs its exact reviewed expected counts.
- A `review` with `status: approved`, `reference`, and `plan_sha256` over the plan with `review` omitted. This records a frozen decision; it does not authenticate the reviewer.

Each `migration_observations` capture has version 1, `origin: source|warehouse|omni`, an explicit `provenance`, `independent_of_candidate`, `reference`, and `cases` keyed by case ID. Provenance is `source_observed`, `operator_defined`, `synthetic` or `native_observed`; these are declarations until authenticated by a separately controlled observer. The source capture must be complete and independent. Never populate it by rerunning the candidate or copying target results.

For a data observation, include `context` plus its executed `query_sha256`, canonical `rows`, observed `metrics` and `truncated`. Normalize source/target column names using the reviewed field mapping before capture; never silently coerce NULLs, dates or strings. For an interaction observation, include `context` and `value`, a structured record of the observed layout, formatting, filters and interaction outcome. Freeze the source record first and independently collect the Omni record from its rendered dashboard. A fabricated DOM/interaction record has no native authority. Query equality cannot replace this lane.

Missing target cases are pending; unexpected cases, stale plans/baselines, changed execution context, nonunique grain, schema/type mismatch, differing populations, row order, invariants or interactions fail. Output contains opaque case indices, counts, issue codes and whole-artifact hashes. It contains no row values, raw provider errors, free-text answers or per-value sensitive hashes.

Keep raw captures in the approved private environment with owner-only permissions and the reviewed retention policy. Export only permitted summaries. Attach the comparison report and the authenticated observer's exact-version attestation to the delivery evidence. See [AI-context validation](omni-ai-context.md) for separate question/persona tests and [sensitive input handling](sensitive-data.md) for processing boundaries.
