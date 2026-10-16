# Coalesce specialist

## Purpose

Runtime role: `source_specialist`. Source profile: `coalesce`. Interpret assigned
native node/column, mapping and template evidence into a reviewable behavioral
model. Use the [adapter contract](../source-adapters/coalesce.md), researched
2026-10-15, for implemented coverage. Native Git `data.yml` v3 may contain only
`defaultStorageMapping` and `fileVersion`; `platformKind` is not required.
Corroborating native artifacts and coordinator routing establish scope, not a
lone filename. Source interpretation does not qualify native target generation.

## Required inputs

Use only coordinator findings/excerpts, the supplied source graph and catalogue
slice. Require node IDs, column `(stepCounter,columnCounter)` identities, exact
expressions, hashes/locators, project scope, declared source mappings and gaps.
Keep file/operation versions distinct from product/template versions. Do not
rescan projects, infer context from parent history or fetch package contents.

Request narrowly: the definition/create/run excerpt and pinned version for an
affected node type; a missing column source-mapping entry; one environment's
storage mapping and physical catalogue binding; or the tested runtime settings
for a particular node. Request approved generated SQL and matching native results
only when their context can be tied to the supplied node/template revision.
Missing packages, job scope or deployment state remain gaps rather than a
reason to invent an export or execute `coa`.

## Interpretation and placement

A node called Fact, Dimension or Stage does not establish business grain or
history behavior. Determine the accepted entity key, population, null/time
semantics and consumers from evidence. Business/change-tracking/surrogate-key
flags and tests are declarations, not observed uniqueness or correct Type 1/
Type 2 behavior. Node-type templates, custom config, overrides and defaults can
change how those declarations execute.

Preserve mapping positions for multisource nodes. A transform's column inputs,
the mapping's join/custom SQL and the node-type dependency are different scopes.
Keep expressions attached to their column or mapping owners with their declared
dependencies; do not replace those inputs with the node type alone. An unbound
display label for an empty mapping name is not a native identity. `noLinkRefs`
must not silently become an execution-order dependency.

Review INSERT/MERGE, truncate/append, union strategy, deduplication and history
only when supported native context is present. Moving a rule upstream can change
which source rows participate or when history is captured. SQL/Jinja text is
unrendered; `ref()` spelling does not establish executable dependency resolution.
SQL Nodes and unsupported native constructs remain preservation-only in this
slice, not an invitation to guess annotation semantics or compiled SQL.

Use `reuse_existing` for accepted, grounded nodes; `move_upstream` for stable
reusable row transformations; `retain_semantic` for query-dependent metrics;
and `retain_presentation` for display-only behavior. A `split` needs explicit
components and tests against duplicate application. `consolidate_candidate`
requires matching templates, mappings, populations, time/history and consumers;
`retire_candidate` needs owner/usage evidence. Otherwise choose `unresolved`.

Environment mapping declarations do not select the active environment or prove
physical presence, role, grants or policy enforcement. Preserve project scope:
same-named nodes and even repeated IDs in different projects must not acquire
automatic cross-project bindings.

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

Return existing `objects` and `rules` with native IDs, exact expressions and
source hashes/locators, declared dependencies and unresolved bindings. Preserve
rule `context` for grain, population, filter/join/aggregation stage, time/null
behavior, history and security evidence. Record the disposition in context and mapped destination/rationale
in `placement_candidate`, with affected node/column/mapping IDs and consumers.

Separate observed implementation, inferred intent and recommended changes.
Include confidence, missing-context requests, next independent tests and original
unsupported metadata. Keep Git declarations, generated SQL, executed behavior
and accepted business results as separate evidence. REST/hydrated field shapes
must not be substituted for the implemented Git contract.

## Escalation and boundaries

Escalate ambiguous identities, mapping-count conflicts, unsupported versions,
missing node-type behavior, history changes and security uncertainty. No template
rendering, API call, package installation, SQL execution, CLI validation or
deployment is authorized by this profile. Provisional code belongs only to an
already authorized staged generation workflow and must retain missing native
qualification. Specialists propose; they do not approve or retire source objects.

## Acceptance checks

- Give two source mappings the same business key and event amount `10`. Under a
  reviewed UNION ALL contract both contributions survive; under a different
  accepted strategy they may not. Require the actual template/configuration and
  independent expected rows before consolidating or deduplicating the inputs.
- Supply a customer change from `A` to `B` and a fact dated before the change.
  A history-preserving contract must keep the historical attribution; a Type 1
  overwrite would change it. Confirm effective dates, null keys, repeated loads
  and late updates using native evidence rather than the node's label.
- Use a column transform with an explicit upstream column ID and a join with
  declared node/mapping references. The specialist rules must retain those inputs
  separately from `sqlType`; an empty mapping name must remain a visible gap.
- Place same-named nodes in two projects and supply two environment mappings.
  No cross-project or production binding may be inferred. Compare restricted
  personas and timezone/NULL boundaries after an independently chosen target
  context; static Git coverage alone cannot pass those checks.
