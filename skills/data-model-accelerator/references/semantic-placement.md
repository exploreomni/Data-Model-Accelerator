# Warehouse versus semantic placement

Placement considers behavior, reuse and operational ownership. Source language and current storage location do not determine the correct destination. Existing dbt/Coalesce/native projects may already contain the right implementation; reuse is a first-class outcome.

| Logic | Typical proposed placement | Evidence or exception that changes it |
| --- | --- | --- |
| CDC ordering, deduplication, soft deletes, durable history | Warehouse ingestion/silver | Actual connector/state contract; never infer unavailable history |
| Stable entity identity, conformed attributes, reusable row calculations | Warehouse silver/gold | Validate grain, tenant scope, types, currencies and row loss |
| Fact/dimension construction and repeated expensive transformations | Warehouse | Preserve point-in-time and many-to-many behavior; measure actual cost/freshness tradeoff |
| Governed aggregations, ratios, distinct counts and business dimensions | Semantic, possibly with warehouse components | Non-additivity and filter context can make preaggregation incorrect |
| Fixed definition reused by many consumers | Warehouse, semantic or split | Choose ownership and execution semantics; avoid independently maintained duplicate formulas |
| Report parameters, interactive ranking, table calculations and visual totals | Semantic/query/presentation as supported | LOD/filter order and evaluation partition must be preserved; unsupported behavior remains unresolved |
| Labels, formatting, colors and layout | Presentation | Formatting that actually changes rounding, classification or totals is a business rule |
| Row/column security, masking and tenant enforcement | Explicit defense across required layers | Preserve effective restrictions and identity mapping; never treat a dashboard filter as sufficient security |
| Unused/obsolete logic | Retire candidate | Usage absence alone is insufficient; validate dependencies and authority before removal |

These are defaults to evaluate, not automatic translations.

## Required placement record

For each rule ID retain observed source behavior and provide disposition, target layer/object, rationale, dependency bindings, grain before/after, filter/time/security semantics, existing model reuse, impacted consumers, proposed/accepted status, decision evidence, test IDs and unresolved questions. Distinguish code simplification, intended behavior change and confirmed equivalence.

For a split rule, specify which component executes exactly once upstream and which is evaluated at query time. Example: warehouse produces tested invoice-level `gross_amount` and `paid_amount`; the semantic layer computes `sum(paid_amount) / nullif(sum(gross_amount), 0)` after the chosen filters. Do not materialize an invoice ratio and later sum or average it without an appropriate contract.

Other source-sensitive cases requiring explicit review:

- DAX measure with modified filter context: a SQL row expression is not an equivalent replacement just because its name matches.
- Tableau LOD or table calculation: capture its level/partition/order and applicable filters before translating.
- LookML derived table plus measure: a persisted table and a query-time measure are separate decisions; inspect joins, symmetric aggregation behavior, access filters and source dialect.
- Hex or Sigma intermediate steps: a visible table may depend on inputs, upstream cells/elements, saved context or controls absent from a code export.
- Existing dbt/Coalesce models: compare logical definitions and downstream contracts before moving BI logic into a competing new model.

## Omni target review

Use Omni when it is the selected semantic target. Current documentation describes views as model objects representing accessible database tables or other view definitions, with fields and metadata; topics curate model objects for exploration. Model generation should bind to the proposed warehouse relations and expose verified dimensions, measures, relationships and topic context. [Views](https://docs.omni.co/modeling/views)

Omni measures aggregate rows and can reference other measures; this supports the concept of defining a filtered or compound metric in the semantic layer where its context is appropriate. Use the actual documented syntax and validate the selected behavior rather than translating by name. [Measures](https://docs.omni.co/modeling/measures)

Preserve user/tenant policies explicitly. Omni documents model/topic data-access controls, including access grants and filters tied to user attributes. Verify the customer's actual identities, exceptions and policy placement and test permitted/denied personas. Model-level guidance does not prove the warehouse's independent access controls. [Data-access control](https://docs.omni.co/modeling/develop/data-access-control)

Official sources checked September 9, 2026. Verify target-specific syntax and release labels when emitting actual files. Generic semantic recommendations do not prove that every DAX, Tableau, Looker, Hex or Sigma behavior has a direct Omni equivalent. Record unsupported mappings and preserve original evidence for a decision.

For another semantic target, apply the same placement contract and read that target's official model/metric/security documentation. Do not insert Omni-specific syntax into a target-neutral model.
