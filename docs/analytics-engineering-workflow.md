# Analytics engineering and independent validation

This extension turns the existing assessment/placement workflow into bounded
implementation work with an independently frozen benchmark. It implements nine
sequentially planned components. It does not certify arbitrary projects, host
platforms, Snowflake accounts or Omni tenants.

## Completed implementation stages

| Plan | Component | Review boundary |
| --- | --- | --- |
| [1](plans/01-refactoring-planner.md) | Model dependencies, domain tasks, exact ownership | Accepted model specification and catalogue associations |
| [2](plans/02-independent-baseline.md) | Analyst-authored expected exports and context | Freeze before engineering; preserve protected baseline digest |
| [3](plans/03-snowflake-execution.md) | Reviewed project copy and native dbt receipt | Explicit development profile, destination allowlist and execution authority |
| [4](plans/04-benchmark-engine.md) | Full case/key/value comparison | Compatibility and approved corrections remain separate |
| [5](plans/05-coordination-gates.md) | Role separation, stale evidence and repair history | Actual host execution records and externally pinned event head |
| [6](plans/06-agent-qualification.md) | Independent authoring trial, local replay and negative controls | Synthetic evidence only; target acceptance remains separate |
| [7](plans/07-independent-evidence-hardening.md) | Typed exports, conserved source values and physical column coverage | Independently pinned expectations and observed metadata |
| [8](plans/08-reusable-engagement-workflow.md) | Composite validation, complete declared scope and downstream consumers | Recomputed gates; native invocation and snapshot bindings |
| [9](plans/09-authority-and-catalogue-provenance.md) | Typed authority and normalized catalogue/export reconciliation | Simulation, provisional development and recorded approval remain distinct |

Read the [operator contract](../skills/data-model-accelerator/references/analytics-engineering.md)
for exact JSON fields, command examples, handoffs and limitations. The source
specialists remain read-only extractors. The warehouse/semantic architects choose
the accepted design. Engineering implements declared files; the independent
analyst owns expected results and discrepancy decisions.

## Start a customer pilot

Supply the reviewed dbt/LookML repository, its current raw catalogue and source
provenance, a scoped domain and priority report contracts, accepted definitions,
and an authorized Snowflake development profile with role/warehouse and permitted
database/schema destinations. Keep credentials outside the project. Supply the
Omni development connection/model context and personas separately for downstream
acceptance. Do not invent access or select a production target automatically.

First freeze representative row-level and metric expectations using the source
snapshot, catalogue, report context and source query receipts. Preserve accepted
corrections separately. Then dispatch engineering through the actual host's tools,
build the integrated candidate, obtain independent output exports and recompute
the benchmark. Preserve discrepancies and at most three automatic repairs before
architect review. Revalidate after any source, rule, code or expected-context change.

Required delivery artifacts remain the ERD, canonical and readable dictionaries,
bronze/silver/gold documentation, source-to-target rule mapping, warehouse code,
semantic placement, tests, discrepancy history and reviewable execution evidence.
The new integration verifier does not replace the existing review-package and
fresh-catalogue gates or human approval.

For new existing-project refactoring engagements, use the [enhanced operator contract](../skills/data-model-accelerator/references/engagement-validation.md)
and `verify_engagement.py` to run these gates together. It checks the complete
declared dependency/consumer graph, preserved source values and physical columns,
and reconciles normalized catalogue fields against retained exports. It consumes
the existing reviewed build receipts and never executes an arbitrary repository.
Metadata capture currently has a local DuckDB adapter; other warehouse collectors
and actual approval authentication remain host responsibilities.

## Qualified scope

- Core comparison/planning/association helpers: Python 3.9+, standard library.
- Reviewed execution: pinned dbt-core 1.12.4 evidence; external PyYAML/profile and
  selected adapter required. Native replay uses the pinned local DuckDB environment.
- Full root-project builds only. External packages, operation/pre/post hooks,
  unit-test resources, functions, YAML snapshots, profile templates and ambient
  dbt option overrides fail explicitly until qualified.
- Repair event append uses POSIX file locking (macOS/Linux); it is not a distributed
  event service. Hashes and supplied agent names do not authenticate execution.
- Project inventory and evidence readers are bounded. Large exports should be
  partitioned into explicit cases; do not silently sample or omit cases.
- No customer-scale, Snowflake, Omni, alternate-host or production acceptance is
  implied by the synthetic tests. The repository skill remains portable guidance;
  each host must supply and qualify its real delegation/execution controls.

## Replay the independent fixture

With the existing native qualification dependencies installed:

```sh
python skills/data-model-accelerator/scripts/run_refactor_qualification.py \
  --output /absolute/new-rental-replay --dbt /absolute/environment/bin/dbt
```

The command executes only the bundled rental fixture, copies its archived
candidate and labels execution `fixture_replay`. It does not start new agents.
It freezes the fixture baseline, builds real dbt models, queries the local database,
compares every frozen case, verifies integration and executes deliberately broken
model variants. The [original host authoring record](../validation/analytics-engineering/README.md)
is maintained separately from these repeated local results. The first trial
passed all eight benchmark cases and verified documentation for eight relations
and 63 columns; its report preserves observed failures and remaining coverage gaps.
