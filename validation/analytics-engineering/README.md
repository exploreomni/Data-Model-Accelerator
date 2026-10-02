# Paired analytics engineering qualification

Observed on 2026-09-23. **Local implementation and bounded synthetic trial pass.**
Live Snowflake, Omni, customer/model-owner approval, production security and
alternate-host qualification remain open.

## Results

| Check | Observed result |
| --- | --- |
| Repository suite, Python 3.12 with full optional environment | 556 passed, no skips |
| Python 3.9 core environment | 256 executed successfully; 300 optional checks skipped |
| Original legacy report | Native local build; clean compatibility slice matched independent oracle |
| Refactored native candidate | 5 models, 3 seeds, 67 dbt data tests passed |
| Independent benchmark | 8 of 8 cases, complete keys and values |
| Model documentation | 8 relations and 63 columns matched native inventory/types and observed null contracts |
| Model inventory/integration | All five planned models mapped to enabled native models; 18 file changes assigned to their owner |
| Negative controls | Fanout, missing tenant, wrong amount and missing dictionary column detected |

The wrong-amount variant passed all dbt data tests while failing three independent
benchmark cases. This directly demonstrates why model tests and independent
accuracy validation are both needed. Fanout and missing-tenant variants failed
both native tests and the benchmark. The dictionary mutation failed column
coverage without changing the accepted candidate.

## Actual agent authoring, separate from replay

The host dispatched `/root/rental_analyst` to author synthetic sources, accepted
fixture definitions and eight independent oracle cases. The baseline was frozen
before dispatching `/root/rental_engineer`. The engineer received the source
repository, catalogue and accepted contracts; the oracle and acceptance queries
were withheld by instructions. Shared filesystem access was not OS-sandboxed.
These are observed Codex collaboration task identities, not cryptographic proof
of isolation or general agent reliability.

The engineer produced five models, tests, the downstream analysis, an ERD,
readable/canonical dictionaries, bronze/silver/gold documents and an Omni semantic
contract. Its own initial version-constraint syntax error was corrected before
its successful build. The coordinator then ran a separate native build and the
analyst-authored queries. The analyst reviewed all eight actual exports, the
source/target hashes, SQL and documentation independently. No benchmark-driven
candidate repair or baseline/tolerance change was needed.

The host integration gate initially rejected a coordinator timestamp rounded to
whole seconds, 136 milliseconds before the frozen baseline. The original failed
record remains in the archive. A separate corrected record uses the exact freeze
time as a conservative lower bound established by sequential freeze-then-dispatch
operations. Its observation semantics and correction are recorded explicitly;
no code, expectations, event, tolerance or verification rule was changed. Times
are observation bounds, not estimates of active effort.

[Host result](host-result.json), [independent analyst review](analyst-review.json)
and [replay result](replay-result.json) preserve those distinctions. The replay
copies an archived candidate and uses `fixture_replay`; it dispatches no agents.
CI now performs that replay under `PYTHONOPTIMIZE=1` after the existing dbt
qualification exercises.

The first Ubuntu CI run exposed a portability problem in five process-double
tests: `/bin/echo` traverses a system symlink on Ubuntu, which the execution
boundary correctly rejects. The test fixture now supplies its own regular file;
the production symlink protection remains unchanged. All 13 execution-boundary
tests pass locally with the portable fixture.

## Retained evidence

- `rental-host-trial.tar.gz`: original source/plan/baseline, legacy and candidate
  native artifacts, query/export receipts, analyst review, host observations,
  initial rejected integration record, timestamp correction and passing record.
- `rental-replay.tar.gz`: fresh local replay plus original failed native/benchmark
  artifacts for deliberate model defects and the dictionary mutation.
- The matching `*-archive.json` files enumerate archived byte hashes. Synthetic
  profiles and database files are excluded; receipts retain original paths and
  timestamps. Replay from the repository creates associations for a new machine.
- `test-results.json`: observed environment, counts and scope.

The fixture's complete source/oracle/query/candidate inventory is pinned in
`examples/dbt-rental-trial/fixture-pins.json`. Replay verifies it before execution
and rechecks during execution. It also rejects symlinks and unsafe output paths.

## Scope and gaps

The fixture exercises current-state CDC cleanup, tenant-colliding keys,
replication duplicates, rental/charge tombstones, deposits, refunds, cancelled
rentals, zero-charge rentals, current location labels and a clean compatibility
slice. Surviving damage fees, current active rentals, location tombstones and
same-sequence/different-timestamp CDC ties were not independently exercised.
The inspected SQL expresses these branches, but inspection is not execution.

All amounts and authority labels are fabricated test data. The denied-persona
case is an explicit filter/empty-result probe; it does not establish authenticated
Omni identities, tenant grants or warehouse RLS. Multi-currency conversion,
conflicting equal-version payloads, source null anomalies, historical/as-of logic,
customer-scale performance and recovery on a live target remain outside this
trial. Use the customer pilot to qualify those relevant to the real domain.
