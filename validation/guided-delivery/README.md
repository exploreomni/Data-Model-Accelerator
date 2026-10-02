# Guided multiplatform delivery qualification

Local implementation checks completed 2026-09-24. This is qualification of the shared discovery/readiness/review/export workflow, not production, customer or native warehouse acceptance.

## Results

| Check | Result | Scope |
|---|---|---|
| Full regression suite | 748 passed, no skips | Python 3.12.14 in the existing optional-dependency environment; no packages installed for this change |
| Dependency-free core lane | 748 discovered; 441 passed, 307 optional-dependency skips | Python 3.9; the full environment above covers the skipped cases |
| Delivery-specific behavior | 35 passed | Native Omni names, portable links/dependencies, context/legacy integrity, SVG safety, distinct role routing and dense diagram partition coverage |
| Durable workflow behavior | 35 passed | Short interviews, recovery, source/context/file drift, prepared handoff, authority isolation, concurrency and raw-only discovery-to-package integration |
| Platform readiness | 20 passed | Bounded inventory, raw CSV ownership/gaps, independent source/target choices, GCP ambiguity and Coalesce native contract |
| Raw CSV parser / specialist planner | 5 / 25 passed | Metadata-only output, quoted records, malformed inputs and bounds, source ownership and conservative routing |
| Independent code review | No remaining actionable findings in reviewed scope | Reproduced and rechecked malformed-SVG resume defect; 85 focused tests across raw discovery and workflow |
| Synthetic target-route exercise | 9 routes observed | dbt/native SQL across Snowflake, Databricks, BigQuery; Coalesce selections correctly retain missing-native-contract gaps |
| Browser walkthrough | Passed observed cases | Earlier interview/export walkthrough; current Chrome checks cover prepared state, status-only guidance, parallel roles, skip/self edges, visible predicates and linked-file deselection guard |
| Skill structure / JavaScript syntax / whitespace | Passed | Structural and syntax checks only |

Focused suites and the independent review's 85 tests are subsets of the 748 and must not be added as extra tests. The 9 route checks establish status/routing behavior, not vendor support for every combination. Coalesce platform/import compatibility remains an explicit contract requirement.

## Fixes driven by independent review

SVG processing instructions and namespaced external bases now reject, including UTF-16 bypass attempts. Reviewer exports reject known implementation extensions even when mislabeled as documentation. Self-referencing edges remain inside the canvas, and direct bronze-to-gold edges route around intermediate table blocks. Large diagrams retain every object across bounded views and preserve cross-view edge counts plus the full relationship ledger.

The active engagement no longer repeats full inventory payloads in every evidence record. A >1 MiB readiness fixture across six resumes grew by less than 2.5 KiB per action beyond the current inventory, while historical full results remained pinned to immutable revisions. Snapshot disk storage still grows; this is not an unbounded-scale or warehouse performance claim.

The trial-driven revision adds raw CSV metadata/routing without inventing a dbt
source project, a provisional missing-SME playbook, and prepared-handoff file
checks. Changed review hashes short-circuit stale handoff reuse; malformed SVG
produces a handled validation error. Raw-only structural tests, local execution,
native target evidence and human approval remain separate. Projection coverage,
publication allowlists and comparison denominators are explicit engineering
guidance; this release does not add an arbitrary SQL executor or business oracle.

## Browser evidence boundaries

The browser export removed deselected implementation and validation payloads and produced a ZIP accepted by the portable manifest verifier. Interview answers downloaded from the new-user screen were applied through the CLI; the next round preserved those answers. Direct change-to-code navigation opened the intended SQL. The copy control offers a selection fallback when clipboard access is unavailable; native clipboard bytes and all browser families were not qualified.

Those export/interview observations belong to the earlier guided iteration. The
current visual regression used synthetic mixed-layer, self, skip and parallel
bill-to/ship-to relationships in Chrome. It checked readable blocks and the full
predicate/cardinality/role ledger, prepared-set versus subset wording, and the
linked-file deselection guard. The current Python replay verified both engineer
and reviewer ZIPs and prepared-state resume; the browser download was not repeated
in this final visual pass.

The preview uses synthetic models and explicitly pending warehouse/semantic cases. Its illustrative SQL is not a complete deployable dbt project. No customer repository or native Snowflake, Databricks, BigQuery, Coalesce or Omni environment was executed. No repository publication, deployment, business approval or production sign-off is implied.

## Reproduce

```sh
python -m unittest discover -s tests -v
python skills/data-model-accelerator/scripts/run_guided_delivery_demo.py --output /absolute/new-demo-folder
python skills/data-model-accelerator/scripts/delivery_portal.py verify /absolute/new-demo-folder/engineer-example.zip
```

The dependency-free environment intentionally skips optional parser/runtime tests; install/use the repository's pinned optional test environment only within the authorized scope to reproduce the full lane. Start from the [operator guide](../../docs/guided-start.md) for actual engagements. Native qualification must be re-established against the selected project's versions, source context, independent baseline and target identity.
