# Modeling and validation decisions

## Placement is a decision, not a code cleanup rule

| Concern | Candidate destination | Evidence needed |
| --- | --- | --- |
| Landing and replay | Existing replication plus bronze contracts | Keys, ordering, delete signals, schema drift, retention, access and recovery |
| Canonical record identity | Silver/current-state entities | Tenant scope, deduplication policy, source precedence, merge handling |
| Conformance and history | Silver and shared dimensions | Effective-time policy, point-in-time joins, overlapping validity checks |
| Reusable business events | Gold facts at explicit grain | Event identity, measures, relationship cardinalities, correction policy |
| Shared business definitions | Gold or governed semantic layer | Owner-approved population/formula, reuse, aggregation behavior |
| Interactive metrics | Semantic/query layer where appropriate | Filter context, distinct counts, ratios, windows, drill and subtotal behavior |
| Formatting | Report/presentation layer | Display-only transformations distinguished from business rules |

Medallion is a data-refinement pattern, not a requirement to manufacture three physical tables per source. Silver may combine sources; gold can expose detailed facts and dimensions as well as useful aggregates. Choose materialization based on freshness, usage, volume, cost, and operational capacity. [Databricks medallion guidance](https://docs.databricks.com/aws/en/lakehouse/medallion)

For dbt, staging, intermediate transformations, and business marts provide a useful project organization. Do not equate folder names with proven architecture quality or confuse this layout with the organizational concept of data mesh. [dbt project structure](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview)

## Model specification

For every model state the grain in a complete sentence; natural/composite keys; surrogate-key construction when needed; nullable attributes; source and target types; units; freshness; owner status; retention; and security classification. For every relationship state both sides' keys, cardinality, optionality, temporal predicate, tenant boundary, unmatched-row behavior, and any allocation rule. A join on a business ID is insufficient if that ID is not globally unique.

Do not silently choose latest-row wins without a trustworthy ordering and tie policy. A delete can supersede a prior valid row. Ingestion time and business effective time serve different purposes. If replication only preserves current state, historical reconstruction may be impossible. Record that gap instead of manufacturing snapshots.

For numeric transformations preserve decimal precision, units, currency policy, null semantics, signs, rounding stage, and zero denominators. Avoid sum-of-ratios, average-of-averages, and summing distinct counts without a valid aggregation contract. Different definitions can remain intentional variants.

An ERD must agree with the specification and generated code. Show composite tenant keys, one-to-many and optional joins, and temporal relationships in notes. Provide conceptual entities, logical grain/relationships, and physical target names; these can be views of one specification rather than three redundant documents.

The ERD, complete data dictionary and bronze/silver/gold documentation are required deliverables under [model-documentation.md](model-documentation.md). Validate every scoped object and column against the source catalogue and generated/reused models. Separate physical constraints from logical expectations and local test observations; document each layer's transformations, dependencies, refresh/history behavior, governance, ownership and recovery. Keep downstream semantic definitions linked to their gold fields. Update the inventory, dictionary, diagrams and narrative together when code or definitions change.

## Test matrix

Every mandatory test has an identifier, category, case/population, independent expectation, observed result, input/code hashes, environment, scope, and evidence location. A required check with no result is a gap. A negative-control test passes only when the intended defect is detected by the relevant assertion; a syntax error or unrelated failure is not a successful detection.

Evaluate every generated typed projection, including columns in lazy views and
derived calendar attributes. A successful build or row count can leave unused
expressions unevaluated. Track checked and unchecked columns; test malformed
timestamps, decimal overflow and normalized identifier collisions. Treat lexical
versus typed key equivalence, empty strings versus nulls and date versus timestamp
changes as explicit decisions, including downstream semantic joins. For missing
SMEs or legacy outputs, use the bounded [new-model route](inherited-data-discovery.md).

| Category | Required probes when relevant | What a pass establishes |
| --- | --- | --- |
| `source_contract` | Types, nullability, keys, CDC operation/order, delete handling, schema changes | Inputs match the stated assumptions within the tested population |
| `grain` | Composite-key uniqueness; duplicated and null keys; orphan rows | Stated model grain is supported |
| `fanout` | Join multiplicity distribution and per-key additive measures before/after each join | No unapproved expansion or loss of measures |
| `logic` | Status, date, null/empty, exclusion, currency and rounding cases | Intended rule behavior on these cases |
| `reconciliation` | Missing/extra keys, per-key measures, dimensional slices, totals, zero/empty populations | Agreement for aligned source/report context |
| `history` | Validity boundaries, overlapping history, as-of joins, revised classifications | Stated point-in-time policy is applied |
| `replay` | Insert/update/delete, duplicates, out-of-order arrival, restart; incremental vs rebuild | Deterministic convergence under the tested connector contract |
| `security` | Cross-tenant ID collision; permitted/denied roles; masked columns, aggregates, exports | Only tested access behavior, not blanket security certification |
| `negative_controls` | Intentionally remove tenant join, duplicate dimension row, or alter status filter | Checks detect the targeted defect and do not silently bless incorrect output |
| `target_compile` | Exact target dialect, framework and dependency versions, materialization/hooks | Generated project compiles/plans in that target context |
| `target_execution` | Scoped dev run, representative volumes, grants/policies, incremental update | The tested target actually executed the artifacts |
| `operations` | Dependencies, run order, freshness, timeout/cost, restart and rollback | A bounded operational path is demonstrated |

Record performance evidence at representative volume; tiny fixtures prove neither cost nor scale. Record sample method, row/date ranges, filtered population, source/report watermarks, and what was excluded. Do not extrapolate perfect sample results into 100% production correctness. Tolerances are explicit per measure and unit; default exact comparison for keys/counts and decimal amounts where exactness is meaningful. Do not widen tolerances to make a mismatch disappear.

## Two distinct comparison tracks

1. Compatibility: reproduce the observed report on aligned inputs, settings and identity.
2. Correctness: verify the accepted business definition, including intentionally corrected behavior.

Keep a discrepancy register when these differ. Characterizing a bug does not approve retaining it, and a cleaner formula does not approve changing business results. Expected outputs should come from controlled exports or independently reasoned fixtures and business review. Do not generate expected values by running the candidate and copying its output.

## Development execution and release

Static inspection and local fixture execution precede target qualification. A SQL SELECT or compilation step can invoke functions, macros or hooks with side effects; do not treat it as safe solely by its leading keyword. Inspect execution paths, dependencies and connection configuration. Apply development-only destination allowlists, least-privilege roles, limits and timeouts outside the language-model prompt where the host supports them.

Run target tests only inside the authorized scope. No fixture test substitutes for real warehouse row/column access enforcement. No compile result substitutes for execution. No development result substitutes for business approval or operational acceptance.

Before promotion, show the full candidate with exact version/hashes, closed decisions, ERD/docs, complete relevant tests, consumer impact, authorized destination, and rollback/recovery procedure. Retention changes, destructive history rewrites, cutover and decommissioning need their own explicit decisions. On ambiguous execution, inspect the target before retrying.
