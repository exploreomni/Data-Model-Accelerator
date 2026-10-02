# Task 8: Reusable engagement validation and dependency scope

Status: complete; local verification passed.

## Scope

Compose the existing native execution, independent refactor-run verification, catalogue/documentation review and new value/physical gates through one repository-independent validation entry point. Preserve existing version-1 fixture contracts and clearly label their older coverage. Do not execute unreviewed repository code or introduce warehouse credentials into this coordinator.

## Implementation

- Add a hashed, normalized scope contract with a complete declared repository file denominator, dependency graph, selected nodes, shared dependencies and downstream consumer dispositions. Compute both the affected downstream graph and all upstream dependencies needed by those consumers. Fail unresolved IDs, cycles, missing files and omitted consumer decisions. Explicitly distinguish declared graph coverage from parser completeness.
- Add an engagement request that pins the refactor record, review package, model inventory, independent physical observation, source-value contract and scope contract. Recompute every gate, cross-check source/catalogue/candidate identities, require the same documentation inventory, and retain failure details. A passing old run record alone cannot pass the enhanced workflow.
- Keep native execution behind the existing reviewed `run_dbt_project.py --execute` adapter; the new entry point accepts its receipts and never runs SQL or source hooks. Result exporters use Task 7's shared typed serializer.
- Add generic synthetic regressions for renamed domains, shared dependencies, downstream semantic/report consumers, missing gates, drift and passing-native/failed-independent evidence. No private exercise materials.

## Verification and sequence

Complete focused scope and engagement checks before Task 9. The final integration will exercise a native public synthetic dbt build and the enhanced workflow, including negative controls. Target warehouse and Omni acceptance remain separate. Task 9 adds typed authority/provenance before this entry point is recommended for new engagements.

Result: 46 focused checks passed (16 scope, 12 composite engagement, 7 real DuckDB metadata, 11 replay-boundary/export checks). Composite tests use explicitly synthetic native receipts; metadata tests query real temporary DuckDB databases. The public rental native replay separately passed 8 benchmark cases and physical metadata reconciliation for 8 relations/63 columns. Fanout, missing-tenant and incorrect-amount controls failed their independent benchmarks as intended; incorrect amount still passed native tests. Strict serialization initially interrupted the duplicate-key control; failed exports now retain diagnostics and remain failed cases in the unchanged full benchmark denominator.
