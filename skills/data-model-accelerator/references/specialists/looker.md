# Looker specialist

## Purpose

As `source_specialist`, preserve the behavior of assigned LookML and dashboard queries while proposing which reusable transformations belong upstream.

## Required inputs

Use selected parser findings and original LookML/SQL/Liquid, view/Explore IDs, dashboard query/tile/filter contracts, include/refinement dependencies, catalogue and existing-model slices. The coordinator runs canonical parsers once and retains full dashboard contracts. Supply independent expected inventory when claiming source completeness. [Adapter](../source-adapters/looker.md) and existing Looker dashboard contracts retain their boundaries.

## Interpretation and placement

- Trace includes, extensions, refinements, imported projects and derived-table/PDT persistence separately from query behavior. Missing imports remain dependencies, not absent business logic.
- Preserve primary-key declarations, join relationship direction, symmetric-aggregate assumptions, measure filters, Liquid parameters, access filters/grants and user-attribute bindings. Declared relationships are not measured cardinality.
- Row-level derived transforms may be `move_upstream`; validated existing definitions may be `reuse_existing`. Measures affected by query grouping, filters or parameters are usually `retain_semantic`; table calculations/drills/display behavior may be `retain_presentation`. Mixed derived/query logic is `split`; uncertain behavior stays `unresolved`. Consolidation/retirement are candidates needing equivalence/consumer review.
- Never translate symmetric-aggregate protection into an unexplained business transformation or assume flattened joins remain safe.

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

Return the supplied object/rule schema with stable native IDs, exact evidence locators, original expressions, dependencies, declared/inferred/unknown grain and filter/security context. Preserve every assigned tile and control in coverage, including text/unsupported tiles. Explain placement with affected consumers and required validation. The coordinator attaches canonical `dashboard_contracts` and source-adapter evidence unchanged; scope declarations alone do not establish source-observed completeness.

## Escalation and boundaries

Do not compile Liquid, execute SQL, fetch dashboards, follow URLs or infer missing attributes. Request exact Explore, field, user-attribute or merged-result evidence. Continue unaffected tasks; use existing provisional-generation and human-approval boundaries. Source interpretation does not certify Omni YAML, query parity or dashboard acceptance.

## Acceptance checks

- Orders joined to order items must not sum order totals at item grain without a proven fanout-safe strategy.
- A user-selected period filter cannot become a permanent warehouse WHERE clause. An access filter must remain an independently enforced security requirement.
- A ratio measure must be recomputed from aggregated numerator/denominator, not averaged from displayed row ratios without evidence.

Reference: [Looker symmetric aggregates](https://cloud.google.com/looker/docs/best-practices/understanding-symmetric-aggregates).
