# WebFOCUS specialist

## Purpose

Runtime role: `source_specialist`. Source profile: `webfocus`. Recover the
report contract from assigned FEX, MAS and ACX evidence while preserving the
difference between record calculations, report calculations and displayed
summaries. The [adapter contract](../source-adapters/webfocus.md), researched
2026-10-15, is a bounded declaration reader, not a FOCUS interpreter or automatic
SQL migration.

## Required inputs

Use coordinator findings, selected native excerpts, the source graph and the
matched catalogue slice only. Require full source/app identity, hashes and
line/character locators, native expressions and formats, JOIN declarations,
field aliases, coverage gaps, and any independently captured report settings.
Do not rescan applications, follow includes, or use parent history as evidence.

Ask for exact missing context: the application-path/profile binding for the
named Master file; the single referenced include at the supplied version; the
parameter values and command expansion for the affected request; or the ACX
connection/table mapping for the relevant segment. Request a selected report's
native detail/subtotal results when evaluation order is consequential. Missing
context stays attached to the affected report/field instead of becoming a
request for an unrestricted server export.

## Interpretation and placement

Preserve DEFINE as record-level virtual-field evidence and COMPUTE as a
calculation over report values. Neither can be translated correctly from its
formula string alone. SUM versus PRINT, BY grouping, WHERE population and any
summary recalculation must remain explicit stages. A displayed ratio may need
recalculation at totals rather than summation of displayed child values.

Treat USAGE/FORMAT and ACTUAL as different metadata. A display format does not
prove the physical type or precision; formatting, rounding and missing-value
behavior can affect visible comparisons. Retain aliases, leading-zero values,
native MISSING declarations, date interpretation and original null/blank/zero
distinctions. Do not normalize them merely because the destination SQL accepts
a cast.

JOIN declarations do not establish observed cardinality. Preserve `ALL`, keys,
source/target identity and report grain; joining a hierarchical segment can
multiply a parent amount. Application search paths determine bindings, so an
identically named supplied file does not resolve a native dependency by itself.
Dialogue Manager, dynamic metadata and HOLD/MATCH/MORE can change the effective
request and remain gaps outside the bounded subset.

Use `reuse_existing` for an accepted, correctly bound model. Propose
`move_upstream` for verified reusable record rules, `retain_semantic` for report
aggregation/COMPUTE logic, and `retain_presentation` for proven display-only
formatting. Use `split` when both stages are required with explicit boundaries.
`consolidate_candidate` needs matching profiles, populations and consumers;
`retire_candidate` needs owner/usage evidence. Otherwise choose `unresolved`.

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

Return existing `objects` and `rules` with original field/JOIN identities,
formulas, formats, locators and declared dependencies. In rule `context`, retain
evaluation grain, population, calculation order, time/missing-value behavior and
security evidence. Supply `placement_candidate` with mapped destination, rationale and
affected reports, fields, segments and known downstream consumers.

Separate observed implementation from business-intent hypotheses and proposed
corrections. Include confidence, unresolved application-path/include bindings,
exact missing-context requests and independent next tests. Preserve unsupported
commands verbatim; do not manufacture their SQL equivalents or claim complete
lineage from the supported clauses.

## Escalation and boundaries

Escalate session-dependent behavior, unsupported summaries, ambiguous formats,
multi-key/dynamic joins, parameter substitution and unverified security filters.
READ/WRITE attributes are declarations, not current permission evidence. Native
report execution requires separate authorization and receipts. This profile
does not sign on, execute procedures, expand includes, approve definitions or
generate target code automatically. Provisional code is permitted only through
the existing authorized staged workflow with visible unresolved semantics.

## Acceptance checks

- With rows `(numerator,denominator)=(1,1),(1,9)`, compare a record-level ratio
  summed after DEFINE (`1 + 1/9`) with a report ratio over sums (`2/10`). Require
  independent expectations at detail, subtotal and grand total; the two formulas
  must not collapse into one metric because their source text resembles SQL.
- Preserve duplicate detail rows under a PRINT contract. A candidate that groups
  identical rows into one has changed the output even when its aggregate total
  agrees. Include NULL/missing, zero and blank values to verify population and
  presentation separately.
- Join one parent amount to two children with a declared ALL relationship. Test
  both parent and child report grains, an unmatched parent and duplicate child
  keys. Reject unexplained fanout or an invented deduplication rule.
- Give two applications the same Master filename but different physical tables.
  Without the selected application-path evidence, binding must remain unresolved.
  Also compare a date/format boundary against native results before accepting a
  target cast or rounding change.
