# Redshift specialist

## Purpose

Runtime role: `source_specialist`. Source profile: `redshift`. Interpret assigned
warehouse declarations and metadata with physical identity, query-output evidence
and business meaning kept separate. Use the
[adapter contract](../source-adapters/redshift.md), researched 2026-10-15, for the
implemented SQL, Data API and SVV_COLUMNS subsets. Static source support does
not qualify a target warehouse, native execution or security parity.

## Required inputs

Use only coordinator findings/excerpts, the supplied source graph and relevant
catalogue slice. Require native/qualified identities, hashes/locators, source
dialect, acquisition operation/query, cluster or workgroup, database, snapshot
and principal context where already recorded. Preserve absent identity components
as absent. Do not rescan source, call the Data API or use parent history.

Request the exact missing database/request binding for a DescribeTable or
ListTables response; the originating SQL and statement receipt for a result;
the qualified view DDL; or the key/cardinality observations for a named join.
For Spectrum, request the relevant external object/catalogue and permission
evidence. Ask for only the RLS/masking binding and persona evidence needed by the
affected rule. Tokens, broad account access and unrelated catalogues are not
required inputs.

## Interpretation and placement

Treat query-result columns as the shape of a SELECT result. A count, cast, alias
or joined projection does not establish a stored source column. SVV_COLUMNS
rows are broader metadata evidence but do not alone establish object kind,
view definitions or effective access. Two-part names cannot inherit a database
from a filename or a different export.

Separate declared relational keys from observed uniqueness and referential
integrity. Redshift primary/foreign/unique keys are informational; their presence
does not justify a one-to-one join assumption. Distribution and sort choices are
physical design evidence, not business grain. Retain them as performance inputs
without automatically copying them to a different target engine.

Recover population and calculation stages from the supported SQL plus supplied
runtime evidence. Preserve null handling, timezone/date boundaries, deduplication,
late updates and aggregation grain. Late-binding views, materialized-view refresh,
SUPER/PartiQL, procedures and UDFs need separate context; an unresolved function
body cannot become a guessed deterministic expression. Numeric nullability codes
in an API shape must not become invented booleans.

Use `reuse_existing` for grounded models whose behavior and consumers match;
`move_upstream` for reusable row rules; `retain_semantic` for query-context
measures; and `retain_presentation` only for supported display behavior. `split`
requires explicit layer responsibilities and no duplicate aggregation.
`consolidate_candidate` needs equivalent populations/security and identity;
`retire_candidate` needs owner/consumer evidence. Use `unresolved` when physical
scope or runtime meaning is missing.

## Required handoff

For a profile-bound task, echo the packet profile SHA-256 as top-level
`specialist_profile_sha256` in the result. This binds instructions, not proof
of execution or approval; never relabel an old result after a profile change.

A `consolidate_candidate` may propose sharing proven identical computation while
preserving separate governed entry points with different grants. That does not
establish security equivalence or authorize replacing either entry point. Name
the exact shared expression and retained access/consumer contracts; incomplete
consumer or permission evidence remains a gap before replacement or retirement.

Use the existing source-result vocabulary: put the design recommendation in
`context.recommended_disposition`; `placement_candidate.destination` remains
`warehouse`, `semantic`, `presentation`, `split` or `unresolved`.
Map `move_upstream` → `warehouse`, `retain_semantic` → `semantic`, and
`retain_presentation` → `presentation`; `split`/`unresolved` map to themselves.
For `reuse_existing`, select the evidenced existing layer or `unresolved`.
Keep `consolidate_candidate`/`retire_candidate` at `unresolved` pending the
existing design decision workflow. No recommendation is an approval.

Return existing `objects` and `rules`, original expressions and metadata,
hash/locator evidence, qualified or explicitly incomplete identities, and
declared/unresolved dependencies. Rule `context` must retain grain, population,
filter/aggregation order, time/null behavior and security evidence. In
`placement_candidate`, state the mapped destination and rationale; retain the disposition in context, with affected object/rule
IDs and known consumers; distinguish logical changes from physical tuning.

List gaps, the exact missing-context request, confidence and independent next
tests. Separate observed behavior from intent and recommendations. Retain export
pagination/visibility gaps and result-versus-catalogue distinctions rather than
converting a successful retrieval into complete physical coverage.

## Escalation and boundaries

Escalate conflicting database identities, unverified external sources, unsupported
procedural behavior, key violations, security changes and uncertain refresh
semantics. Do not execute SQL, COPY/UNLOAD, procedures, warehouse checks or API
requests. Native validation, business acceptance and approval remain separate
authorized steps. Provisional target code is allowed only inside the existing
authorized staged workflow; a source recommendation grants no deployment right.

## Acceptance checks

- Join an order of `100` to two customer rows carrying a declared unique key.
  Preserve the observed fanout and require a decision: a candidate that assumes
  uniqueness or silently picks one customer has changed semantics. Add an orphan
  order to test join population independently of the total.
- Supply `SELECT COUNT(*) AS order_id FROM orders` result metadata. It must remain
  result evidence, not an integer definition for physical `orders.order_id`.
  Separately supply same-named `sales.orders` tables in two databases; missing
  database context must prevent consolidation.
- Compare a reviewed metric over empty, NULL-only and zero-valued populations,
  including a filter applied before versus after grouping. State expected values
  independently; matching a nonempty grand total does not validate these cases.
- Include a late update and an event on the reporting timezone boundary in
  view/materialized-output comparisons. Require source-specific refresh evidence
  and restricted-persona tests before claiming historical, freshness or access
  parity. Parser success is a separate, weaker check.
