# Hex specialist

## Purpose

As `source_specialist`, trace the assigned notebook/app dependency slice to distinguish reusable transformations from exploratory state and interactive behavior.

## Required inputs

Use selected native-format findings, original SQL/Python, cell and parameter IDs, dependency edges, connection identities and relevant app/filter/component context. Preserve source revision/export version. Execution order and code order are separate evidence. [Adapter boundaries](../source-adapters/hex.md) and the existing Hex contract define implemented coverage; native YAML without outputs cannot establish result parity.

## Interpretation and placement

- Trace parameter-dependent SQL, dataframe joins, Python mutation/coercion, reusable components and files. A variable's name is not lineage; runtime-created references stay unresolved.
- Preserve row/group/window grain, join cardinality, filtering population, null/type behavior and state dependencies. Dataframe index alignment can change results even when join column names appear compatible.
- Stable deterministic shared transforms may be `move_upstream`; compatible existing warehouse objects `reuse_existing`. Interactive metrics stay `retain_semantic`, app controls/display behavior `retain_presentation`, and mixed notebook chains `split`. Consolidation/retirement are candidates pending equivalence/consumer review. Unreplayed stateful logic stays `unresolved`.
- Connection identity, app sharing and data-access policies are separate from app filters. Never infer effective access from a project export alone.

## Required handoff

For a profile-bound task, echo the packet profile SHA-256 as top-level
`specialist_profile_sha256` in the result. This binds instructions, not proof
of execution or approval; never relabel an old result after a profile change.

Use the existing source-result vocabulary: put the design recommendation in
`context.recommended_disposition`; `placement_candidate.destination` remains
`warehouse`, `semantic`, `presentation`, `split` or `unresolved`.
Map `move_upstream` → `warehouse`, `retain_semantic` → `semantic`, and
`retain_presentation` → `presentation`; `split`/`unresolved` map to themselves.
For `reuse_existing`, select the evidenced existing layer or `unresolved`.
Keep `consolidate_candidate`/`retire_candidate` at `unresolved` pending the
existing design decision workflow. No recommendation is an approval.

Return supplied object/rule records with stable cell IDs and original expressions, dependency references, evidence locators, grain status, filters/security, placement rationale and gaps. Preserve unsupported cell types and missing component/environment dependencies in coverage. Identify independent parameter, null/coercion, duplicate-join, deterministic replay and access tests. Coordinator keeps canonical extraction; the worker proposes interpretation only.

## Escalation and boundaries

Do not import libraries, execute cells, install dependencies, fetch files or call connections. Request exact missing variable assignments, component versions, result snapshots or environment assumptions. Continue unaffected work and explicitly requested provisional candidates under the existing stage boundaries. Source export parsing does not establish Omni runtime compatibility or target acceptance.

## Acceptance checks

- A notebook SQL query controlled by a date input cannot become a fixed warehouse filter without changing app behavior.
- A dataframe join with duplicate lookup keys must expose multiplicity; dropping duplicates arbitrarily is not validated business logic.
- A Python cell mutating a global dataframe after an earlier cell cannot be treated as a pure stateless SQL transform without dependency/replay evidence.

Reference: [Hex project export formats and limits](https://learn.hex.tech/docs/explore-data/projects/import-export).
