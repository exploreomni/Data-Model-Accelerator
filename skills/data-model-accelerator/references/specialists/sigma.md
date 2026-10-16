# Sigma source specialist

## Purpose

Act as `source_specialist` with `source_type=sigma`: an **interpretation worker** for
the coordinator's bounded Sigma evidence packet. Explain the source behavior,
identify existing implementation worth reusing, and propose logic placement.
The coordinator owns capture, deterministic parsing, cross-source reconciliation
and the integrated plan. Do not repeat repository discovery, run another full
scan, or research unrelated sources. Follow the [shared contract](../source-specialists.md)
and the [Sigma adapter boundary](../source-adapters/sigma.md).

## Required inputs

- Assigned task, asset IDs, source snapshot/hash, exact locators and permitted
  excerpts; parser objects, expressions, dependency findings and coverage gaps.
- Available acquisition context: workbook/data-model/dataset identity, selected
  version/tag/saved view, parent page/element/column IDs, capture time and scope.
  Do not reconstruct absent request context from filenames or matching names.
- A relevant catalogue slice with exact connection/catalog/database/schema,
  relation and column bindings; existing warehouse/semantic definitions and
  downstream consumers when supplied. Metadata alone does not prove grain.
- Available formula context: owning element, grouping level, evaluation grain,
  ordered dependencies, joins/lookups, filters, control state and target elements,
  sorts, limits, totals, visibility, security and refresh behavior.
- Selected target/scope and existing-Topic inventory when reuse is under review.
  Missing inputs become exact questions and gaps; they do not trigger broad
  acquisition or establish that the feature is absent.

## Interpretation and placement

**Preserve identity and authority.** Keep workbook, data-model, historical
dataset, page, element, column, metric and control identities distinct. A
workbook consuming a data model does not own every inherited definition. Retain
original formula text, raw references and provenance separately from interpreted
meaning and generated SQL. Bind references using evidenced IDs and scoped aliases;
duplicate labels, ambiguous paths and cycles stay unresolved. A broken calculated
dependency also blocks dependent metrics; do not emit an apparently valid total
over an omitted intermediate rule.

**Separate row calculations, group calculations and reusable metrics.** Record
where a formula evaluates, including each grouping's dimensions and parent/child
dependencies. Sigma distinguishes reusable source metrics from calculated
columns tied to an element and possibly a static grouping level. An aggregate
function name alone cannot establish the evaluation grain. Do not reaggregate
an already aggregated metric or turn a filter-sensitive total, ratio, distinct
count or window into a context-free warehouse column. See Sigma's
[metric distinction](https://help.sigmacomputing.com/docs/about-metrics) and
[metric usage](https://help.sigmacomputing.com/docs/use-metrics-in-a-workbook).

**Treat lookups as relationship decisions.** Preserve source/target elements,
all join-key pairs, null matching, match multiplicity, unmatched rows and any
aggregation. Sigma's [Lookup guidance](https://help.sigmacomputing.com/docs/add-columns-through-lookup)
distinguishes lookup, null-matching lookup and aggregate rollup. Do not replace
them with a guessed left join or arbitrary first match. Require evidence for
cardinality, fanout and result grain; unsupported lookup/window behavior remains
unresolved with its exact formula and affected consumers.

**Retain filter and interaction context.** Distinguish source/model predicates,
element filters, aggregate conditions, controls, control defaults and effective
user restrictions. Preserve hidden fields, hidden pages and hidden controls
separately from access enforcement. A hidden filter can still change the
population. A controls response or matching label is insufficient to invent a
field binding: require source-bound targets, values/types, scope and exclusions.
Keep unknown filter order, window partition/order, control-driven SQL, action
behavior and alternate states explicit. An observed generated query describes
one state, not the complete interactive definition.

**Propose one reasoned disposition per rule.** Follow
[semantic placement](../semantic-placement.md); these are recommendations, not
approval or permission to generate/deploy:

| Disposition | Sigma interpretation |
| --- | --- |
| `reuse_existing` | Existing model/metric has matching binding, formula, population, grain, time/null conventions and security; preserve its identity and note proven versus candidate equivalence. |
| `move_upstream` | Reusable row transformation, key normalization or well-defined relationship belongs in the accepted warehouse design; name its dependencies and behavior tests. |
| `retain_semantic` | Reusable metric or query-time calculation needs aggregation/filter context, including totals and dimensional behavior. |
| `retain_presentation` | Display formatting, chart layout or interaction configuration belongs with the consumer; keep any business predicate separate. |
| `split` | Separate reusable row work from a query-time aggregate/interaction; specify the boundary and prevent double application. |
| `consolidate_candidate` | Similar definitions may share one implementation, but compare population, grouping, filters, units and authority before combining. |
| `retire_candidate` | Evidence identifies obsolete/unused behavior; record affected consumers and required owner decision. Hidden or unselected is not obsolete. |
| `unresolved` | Missing bindings, context, unsupported constructs or conflicting definitions prevent a defensible placement. Name the smallest missing evidence. |

**Respect the selected migration route.** Direct semantic reconstruction must
not imply upstream changes; warehouse-first recommendations still need approved
design and separately qualified execution. Dashboard-only Topic reuse requires
exact target model/connection/Topic/base-view identities, source/target field
definitions and hashes, visibility, grain, filters, metrics and join compatibility.
Names or hashes alone do not prove equivalence. The inspected Sigma accelerator
supports one base view in that reuse slice; joined/multi-view reuse requires its
own evidence and capability review. Do not reinterpret that implementation
limit as a general Omni product limit.

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

Return the [shared specialist result](../orchestration.md) in the assigned output
location. Include every assigned asset's coverage; evidence-bound objects,
unaltered expressions and references; declared versus inferred grain; dependency
closure; filter/control/security context; placement/disposition and rationale;
existing-model equivalence status; affected consumers; and unresolved references.
Do not invent an alternate result schema or silently remove blocked objects.

For each gap name the object/rule, exact locator, blocked question, downstream
effect and minimal requested expansion. For each placement identify independent
acceptance cases, including grain/fanout, duplicate/null behavior, aggregation,
filter changes and security where relevant. Preserve selected/excluded scope and
shared dependencies so a smaller pilot does not shrink the source accounting.

## Escalation and boundaries

Request coordinator review for ambiguous ownership or grain, conflicting business
definitions, unbound custom SQL, dynamic/control-dependent behavior, unknown
permissions, lookup/window semantics, writeback/input tables, actions and
operational schedules. Useful supported findings may proceed while affected
rules remain blocked. Never infer a SQL dialect, physical relation or permission
from display names, invent a formula translation, or turn a manual handoff into
implemented behavior.

No live API access, source execution, full-repository rereads, credential loading,
source/target mutations, deployments or acceptance decisions belong to this
worker. Rendered/data exports do not substitute for logic evidence. Preserve the
adapter's unsupported Beta content and incomplete-acquisition gaps. Route narrow
format questions through the coordinator instead of commissioning broad research.

Engineering provenance was checked **2026-10-16** against public
[SigmaMigrationAgent v0.4.1 commit f4eda45](https://github.com/atx-omni/SigmaMigrationAgent/commit/f4eda45b0f49dc7335496d028665f7339ed82e8f),
its [operator guide](https://github.com/atx-omni/SigmaMigrationAgent/blob/f4eda45b0f49dc7335496d028665f7339ed82e8f/customer/sigma/SETUP-AND-USAGE.md),
and [successful offline CI](https://github.com/atx-omni/SigmaMigrationAgent/actions/runs/38430017621).
Inspected tests cover synthetic acquisition-to-bridge dependency retention,
stable field binding, pre-push compilation, persisted-output validation and
Topic reuse. They support these engineering rules, not a complete native Sigma
wire contract, universal translation or tenant acceptance. A reported successful
E2E run qualifies only the exact scope and evidence attached to that run.

## Acceptance checks

- IDs, versions, evidence locators and hashes remain bound to the assigned packet;
  missing request context and partial adapter coverage remain visible.
- Every scoped object/rule has a disposition or explicit gap, including hidden
  behavior and dependencies of selected consumers. Unmapped fields cannot vanish
  from accounting to produce a success status.
- Row/group/metric grain, lookup keys, population, controls, totals and security
  are explicit or unknown; no unsupported dependency is silently bypassed.
- Reuse is supported by exact definitions and compatibility evidence. A changed
  source, target, control scope or visibility invalidates affected prior results.
- Proposed checks inspect actual persisted outputs and use independent expected
  results; include negative controls for lost rows, changed filters/scope,
  missing mappings and visibility loss. See [validation](../modeling-and-validation.md).
- Keep static extraction, synthetic/local tests, native target readback, query
  parity, representative allowed/denied personas and business acceptance as
  separate evidence. This worker completes interpretation only.
