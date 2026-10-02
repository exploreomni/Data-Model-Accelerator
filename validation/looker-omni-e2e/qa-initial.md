# Independent local E2E review

Reviewed generated Snowflake/Omni artifacts and their local execution/semantic adapters against the frozen independent oracle and `input/scenario.md`. The oracle and raw fixture were not edited. Findings below describe the implementation when probed; subsequent fixes need focused confirmation.

## Actionable findings

1. **P1 — SQL execution can read files outside the fixture.** `scripts/e2e_warehouse.py:175–190` rejects `exp.Anonymous` functions but permits recognized `ReadCSV`/`ReadParquet` nodes and file-literal table references. `execute_models` at lines 193–207 checks only nonempty table catalog names, while `build` at line 222 opens DuckDB with external access enabled. In a temporary copy, adding `target/snowflake/99_external.sql` with `CREATE TABLE DMA_SIM.GOLD.QA_EXTERNAL AS SELECT * FROM READ_CSV('<temporary-file-outside-case.csv>');` succeeded. A query returned the harmless sentinel `qa_only_sentinel` from that outside file. No sensitive file or network endpoint was accessed. Restrict executable relation/function ASTs and disable external access in the DuckDB connection. Apply the guard to bronze creation, target models and source SELECTs, not only one path.

2. **P2 — Source connection identity is omitted from binding validation.** `scripts/e2e_semantics.py:436` accepts the Looker model `connection` key but does not preserve or validate it against the fixture connection. `scripts/e2e_warehouse.py:159–169` binds physical inputs using only catalog/schema/object names. In a temporary copy, changing `synthetic_billing_snowflake` to `different_warehouse_instance` was accepted by both `load_source` and `compile_looker`; all four physical inputs were still reported and SQL was generated. For this fixed scenario, require the declared connection-to-platform-instance mapping and retain it in the source graph. Qualified table names alone cannot distinguish warehouse instances.

## Findings already being addressed by the parent

- Exact full-fixture replay duplicated history, producing 45 projected gold rows instead of 12. `13_silver_customer_history.sql` copied raw history without deduplication. Exact snapshot repetitions should collapse; differing overlapping intervals must remain invalid. The parent independently found this and is fixing it.
- Changing Omni date/currency defaults to August/EUR survived all scenario comparisons because every scenario supplies explicit overrides. The temporary run passed 51/52 checks; its only failure was the separately identified replay bug. This is not evidence of a fully successful mutant run. The parent owns explicit default-context checks and their negative control.

## Verification limits

Probes used the pinned local Python environment and temporary copies. This review did not rerun a broad test suite, inspect live systems, exercise native Snowflake/Omni validation, verify deployed identity provisioning, or prove warehouse security enforcement. Existing local row/grain/history/currency checks remain simulation evidence. No general parser completeness or production approval is claimed.
