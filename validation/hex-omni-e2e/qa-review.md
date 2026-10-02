# Independent Hex migration QA

Reviewed on 2026-09-10. The reviewer authored the independent oracle from only the synthetic scenario, raw records and manual adjustments before inspecting source replay, generated dbt or Omni implementations. Expected files remained frozen during QA. The reviewer then authored `tests/test_hex_execution.py`; root authored and corrected the execution helpers. This is actual independent local execution evidence, not business acceptance.

## Observed result

The current bounded replay matches all 13 frozen report scenarios through both Hex-source interpretation and generated gold models queried through the Omni definitions: 78 source/target report comparisons. All 10 current invoice rows and all 10 customer-month rows match the independent expected fields. Cents and counts require exact integer values; non-null payment ratios use absolute tolerance `1e-12`; null ratios and cohort values must remain null.

The suite accounts for all 24 native cells across three projects and one versioned component. It covers both tenant contexts, January/February and the February boundary, each segment, empty windows, zero revenue, the retained what-if input, five invalid/denied contexts, draft balances, temporal customer keys, source replay/order changes, overpayment, large integer cents and a present empty adjustment export.

Final focused run: **26 tests passed** in Python 3.12 with the optional replay engines. Optional-free system Python correctly skipped all 26 tests rather than claiming engine validation. No blocking correctness finding remains within the reviewed scope. The main migration runner and broader repository suite are root's separate evidence.

## Findings and focused controls

| Finding | Reproduction and observed closure |
| --- | --- |
| Pandas merge rounded integer cents | Adjustment `9007199254740993` originally replayed as `9007199254740992`; a value near signed-64 maximum also wrapped the computed net negative. Root preserved exact integer/object values. Exact-cent and overflow controls now pass. |
| Unsupported dbt behavior was ignored | A `pre_hook` configuration was silently stripped; duplicate model stems were collapsed by a dictionary. Both now reject. A changed model alias also rejects against the declared destination map. |
| Quoted physical table identity lost case | Lowercase quoted catalogue/schema/table names originally bound through DuckDB case folding. These now reject. |
| Quoted physical column identity lost case | `SELECT "amount_cents" FROM DMA_HEX.RAW.INVOICE_CDC` originally returned rows although the declared Snowflake column is `AMOUNT_CENTS`. The final guard rejects this unsupported quoted identity, and the focused regression passes. Dataframe SQL retains its separately declared DuckDB behavior. |
| Empty adjustment export was treated as missing | The scenario permits zero adjustment rows for current invoices. A present empty export now replays with zero adjustments and agrees with the independent oracle. Missing content remains distinct. |

Negative controls also execute intentional tenant-key omissions in source SQL, target fact SQL and an Omni relationship; grain or report assertions detect the resulting fanout. Two opposite adjustment errors preserve the grand total but fail segment-level comparison. Changed ratio logic and removed population filtering fail report checks. Missing report cells/components, altered connection identity, conflicting CDC versions, duplicate adjustment keys, temporal overlaps/orphans and required null values reject.

A harmless temporary CSV cannot be read through either the SQL allowlist or the returned DuckDB connection. Unsupported Python imports, dynamic access and file writes reject; the temporary sentinel remains absent. These controls do not make the fixture interpreter an arbitrary-code sandbox.

## Evidence boundaries

- Source parsing and the reviewed Python/SQL/Omni subset execute locally. Native Hex, dbt compilation, Snowflake, Omni rendering and real security enforcement were unavailable. SQL dialect translation and deliberate exact-integer interpretation are not proof of native pandas dtype behavior or native platform equivalence.
- The synthetic catalogue supplies the declared raw context; it is not a live metadata capture. Catalogue construction/verification has a separate owner and was not independently reimplemented here.
- Parameter authorization and tenant predicates are functional controls in this simulation, not production RLS proof. Native chart behavior, reactive/linear scheduling beyond this fixture, retained exploration UX, incremental ingestion and business approval remain unqualified.
- Static source coverage is only for the captured fixture. Unknown exports, omitted whole projects outside the declared set and arbitrary Hex/Python features are not proven complete.

Frozen SHA-256 values verified after QA:

| Artifact | SHA-256 |
| --- | --- |
| `expected/oracle.py` | `b23efe5ecb5f1a1580471aec1e208e1dd1aada34f07d8984b23a77bccd217d13` |
| `expected/expected_rows.json` | `b49d8b2f1584b75155df3103979ff4d15fcba54214910faea345ceac7469f363` |
| `expected/expected_reports.json` | `7ad6c05417c809b8daa955fadcdb561965fc61cede3b7b77a48b7005fdca3cb6` |

Reproduction: `/private/tmp/dma-e2e-env/bin/python -m unittest discover -s tests -p test_hex_execution.py -v` from the repository root. The final run required no warning suppression.
