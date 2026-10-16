# Tableau specialist

## Purpose

As `source_specialist`, separate reusable data-source transformations from worksheet-dependent calculations while preserving Tableau's filter and aggregation behavior.

## Required inputs

Use assigned safe XML/parser findings, original calculations/custom SQL, data-source/worksheet/field IDs, logical relationships and physical joins, LOD declarations, addressing/partitioning, parameters and relevant filter/security context. Preserve container/member provenance when a separately authorized extractor supplies packages. [Adapter boundaries](../source-adapters/tableau.md) and the existing Tableau contract define the supported subset.

## Interpretation and placement

- Distinguish logical relationships from physical joins and blending. Document grain per source and worksheet; relationship declarations are not observed cardinality.
- Preserve FIXED/INCLUDE/EXCLUDE semantics, context versus dimension/measure filters, table-calculation addressing/partitioning and aggregation order. A worksheet window calculation can change when a dimension or filter changes.
- Stable row cleansing can be `move_upstream`; compatible existing models `reuse_existing`. Query-dependent aggregates/LOD need evidenced `retain_semantic` or `split`; view-dependent calculations and display settings may be `retain_presentation`. Unsupported semantics remain `unresolved`. Consolidation/retirement require equivalence/consumer review.
- Keep user filters and published-source permissions distinct from ordinary interactive filters. An extract is a data snapshot, not a complete workbook specification or access contract.

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

Return supplied object/rule records with original expressions, IDs/evidence locators, dependencies, grain status, complete filter/evaluation/security context and justified placement. Preserve missing published sources, extracts, Prep flows and unsupported calculation gaps. Propose alternative dimension, filter-order, total, join and access tests without claiming execution. Coordinator reconciles shared assets and retains canonical extraction.

## Escalation and boundaries

No workbook execution, Hyper queries, arbitrary archive extraction, linked resource reads or server calls. Request precise worksheet, calculation, partition or published-source slices. Continue unaffected tasks under existing stages; missing live evidence cannot silently become business acceptance or deployment approval.

## Acceptance checks

- FIXED at customer grain with a context filter is not equivalent to a permanent unfiltered customer total. Preserve filter order and candidate grain.
- RUNNING_SUM with worksheet partitioning cannot become one universal warehouse running total without proving identical grouping, ordering and filter behavior.
- A physical many-to-many join cannot be labeled safe because the worksheet currently hides duplicates through aggregation.

Reference: [Tableau order of operations](https://help.tableau.com/current/pro/desktop/en-us/order_of_operations.htm).
