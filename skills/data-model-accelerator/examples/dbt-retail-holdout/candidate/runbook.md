# Local operations and promotion boundaries

Use the isolated candidate paths only. Raw input is frozen and read-only. There are no hooks, external packages, seeds, incremental models, snapshots or native Omni mutations in the reviewed candidate. Local DuckDB external access and extension auto-install/auto-load are disabled; this is a trusted synthetic harness, not a sandbox for arbitrary customer SQL or macros.

## Reproduce

1. Inspect [contract](contract.json), [input integrity](evidence/input-integrity.json), source graph, catalogue bindings, all candidate SQL/macros/configuration and the profile. The local loader validates the full synthetic capture before writing typed raw relations. Preserve raw and solution hashes for the run.
2. Use `scripts/run_dbt_holdout.py --output /absolute/new/retail-run` from the skill directory, with the pinned qualification dependencies. It creates an isolated copy and invokes its `validate_local.py`. That helper deletes/recreates **only** the copy's `candidate/runtime/DMA_RETAIL.duckdb`, loads the validated capture, snapshots the reviewed dbt project, then runs a separate native parse and complete unselected `dbt build --no-partial-parse --target local`. The profile lives outside the dbt project at `candidate/profiles/profiles.yml`; the helper supplies `DMA_RETAIL_DB_PATH` for the copied database.
3. Retain the original preflight manifest, full-build manifest/run-results, exit status, execution timestamps, stdout/logs and file snapshot. [receipt.json](evidence/native-build/receipt.json) associates these exact files; the read-only skill verifier checks chronology, denominator, checksums and all success/pass statuses. It does not authenticate the executing principal or establish business truth.
4. Compile the downstream analysis separately, query it without creating a warehouse relation, and compare native gold/report results with the template evaluator. Check no REPORTS relation exists and actual model columns match the canonical inventory. Run `test_evaluator.py` for hand-derived and mutation cases. Verify review-package integrity before using the evidence.

Direct API: `evaluate(raw_data, params)` in [evaluator.py](evaluator.py). It validates before accepting output, executes the five actual candidate SQL definitions in local memory, tests their references/balances/coverage, and runs the downstream analysis with safe context. It never reads the withheld oracle or executes source-repository macros. Dates and identifiers are normalized only within the declared contract. Numeric inputs are signed-64-bit; local DECIMAL(38,0) arithmetic avoids floating-point money within its precision limits. Huge aggregate overflow is not a qualified production workload.

The native full build includes five models and 52 tests. dbt SQL reinforces a subset of the complete Python input gate; direct dbt against arbitrary raw state must not be presented as equivalent acceptance. Caller parameters have local synthetic authorization semantics, not principal authentication. The Snowflake profile example requires operator-provided environment values and an isolated `DMA_RETAIL_CANDIDATE` database with schema prefix, was not used here, and is not a granted deployment route.

## Failure and recovery

Fail the acceptance run on invalid input, malformed context, ambiguity, orphan, quantity bounds, schema/grain divergence, nonzero tests, warnings/skips/missing full-build nodes or evidence drift. Do not expose the resulting relations to consumers. The local evaluator closes its in-memory database on failure and returns no accepted outputs. Native dbt may have built earlier nodes before a later failure; it does not atomically roll them back or revoke grants.

The local recovery path is to repair the known input/implementation cause under review, then rebuild from the last accepted complete raw capture in a new isolated database and re-run the full evidence sequence. Preserve failed snapshots/evidence instead of refreshing hashes to conceal drift. Production would need an approved publication/swap strategy, previous accepted version and capture retention, rollback procedure and responsible operator; none is implemented or approved by this trial.

## Ownership and qualification

| Gate | Evidence here | Required authority or next evidence |
|---|---|---|
| Synthetic source/catalogue identity | Frozen hashes and scoped authored receipts | Live/operator-exported Snowflake catalogue and connection identity for target work |
| Native local execution | dbt 1.12.4 / DuckDB 1.5.5 full build and analysis, no selected build | Native Snowflake compile/build, types and execution evidence |
| Business behavior | Author microfixtures, negative controls, native/evaluator parity and independent frozen-oracle comparison | Actual business acceptance remains open; no approval claimed |
| Security | Local parameter rejection and tenant-aware joins | Trusted principal membership, grants, native Omni policies and negative persona evidence |
| Operations | Full-rebuild local recovery described | Named owners, SLA/freshness, alerting, retention/backups, performance/cost and publication design |
| Omni | Target-neutral fields/filters/ratio mapping | Native authored model and consumer behavior qualification |

The source capture has 32 rows and establishes no scale, latency or cost expectation. Current-state reconstruction intentionally restates corrected historical attributes; as-of/SCD or incremental support needs a new contract. All operational/business owners are unknown because none was supplied. Pending production gates block deployment, not preparation of this bounded local candidate for review.

Portability finding: the author validator and local profile currently use the explicitly supplied absolute environment/helper/database paths. Run the commands at this original candidate location. A relocated delivery needs a separately reviewed runtime/profile path patch and new replay evidence; the parent owns that packaging change. The author native receipt remains bound to the original paths and bytes.
