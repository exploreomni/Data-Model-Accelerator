# New models when business context is missing

Use this route when the operator has raw tables or CSV extracts, but no usable
existing model, former team, SME, or trusted Excel/report baseline. It supports a
provisional engineering handoff, not a reconstructed business approval.

## Interview once, preserve unknowns

Prefill choices already supplied: source scope, first domain, target framework,
warehouse, semantic engine, deliverables and allowed environment. Ask unresolved
questions in short rounds. Record missing SMEs, workbooks, definitions and policies
as unavailable; do not repeatedly ask an unanswerable question or fabricate an
approver. Unknown meaning permits bounded profiling, structural proposals and
explicitly requested candidate generation, with uncertainty visible.

Use `engagement_type: new_model` for a new build. If an existing report or dbt
project is actually being migrated, retain its migration/refactor classification
and unresolved compatibility baseline; do not change modes to bypass it. The
short interview records scope, not full model acceptance.

## Establish what is observed

- Inventory selected sources read-only. Use the `raw_csv` specialist and its
  bounded metadata contract in [source-specialists.md](source-specialists.md)
  for CSV-only inputs. Preserve file hashes, original headers and record counts.
  CSV text is not a native warehouse type. Label pretend Snowflake tables as a
  simulation and map each table to its exact source file.
- Obtain the warehouse catalogue for a real deployment. CSV metadata establishes
  no physical cloud objects, permissions, replication or refresh guarantees.
- Profile keys, nulls, duplicates, join coverage and cardinality. Retain
  source-qualified column IDs and explicit source-to-model mappings. Familiar
  names alone do not prove role, grain, history or business meaning.
- Separate `observed`, `inferred`, `proposed` and `unknown` findings. Declare every
  source table and column retained, omitted with a reason, or unresolved. Compare
  designs by entity role, grain, key population and source-qualified field
  meaning; valid designs can have different names and layer counts.

## Separate retention from publication

Preserve raw fidelity according to the agreed retention policy. Broad staging
retention does not imply publication in gold or the semantic model. Use an
explicit publication allowlist and review sensitive fields such as names,
contact details and addresses. Hiding a field or exposing only count measures
does not establish access protection. Test the actual target access boundary.

Propose facts, dimensions and relationships with explicit grain, join keys,
cardinality and roles. Keep billing and shipping relationships distinct. Do not
use arbitrary deduplication, fabricated history or filter changes to match an
unexplained total. Missing CDC/order/history signals remain gaps. Financial
measures, status interpretations, calendars and currency conversions remain
proposed until supported and approved.

## Independent engineering checks

The analyst derives expectations from pinned raw data and documented source
rules before examining candidate output. The engineer implements the separately
versioned proposal. Preserve discrepancies and repairs. Check:

- Source/output key populations, duplicates, orphans and join fanout.
- **Every generated cast/projection**, including lazy views. Successful builds
  and `count(*)` can leave unused expressions unevaluated. Query each typed
  expression and derived calendar column, reporting the object/column denominator
  and any unexecuted expression.
- Invalid dates/timestamps, boundary values, blank versus null, timezone/date
  grain, decimal precision, overflow and rounding.
- Pin the analyst's normalization runtime as well as the source bytes. Preserve
  lexical tokens such as country code `NA`; a parser's default missing-value
  vocabulary is not a source null policy. If the frozen oracle has a parsing
  defect, retain its original expectations and first failure, record a narrow
  source-verified erratum, and rerun without changing the candidate to match the
  faulty parser.
- Identifier normalization collisions such as `01` versus `1`; warehouse joins
  and semantic relationships must use the same lexical or typed key rules.
- Negative controls that fail the assertion for the introduced defect. An
  unrelated syntax/build error does not demonstrate detection.
- Clean replay and repeat builds where replacement/incremental behavior matters.
  Separate local simulation, native target execution and semantic query evidence.
- Replay the actual generated semantic definitions where a bounded interpreter
  supports them, including empty/filter cases, distinct counts, each date/address
  role and full topic join grain. A join can preserve row counts while using the
  wrong role key. Unsupported expressions remain gaps; successful local replay
  does not establish native Omni behavior or live AI response accuracy.

Without legacy output, these are **structural and source-derived checks**, not
measured Excel/report compatibility or business accuracy. Never manufacture a
source dbt project, legacy baseline, approval record or complete refactor receipt
to satisfy `verify_engagement.py`. Its eight-gate refactor grade retains its
prerequisites. Record unavailable gates as gaps in the provisional new-model
delivery; use model/catalogue/documentation checks only when their actual
contracts are satisfied.

## Hand off a usable, bounded result

Deliver selected implementation formats, an Omni candidate where requested, ERD,
dictionary, bronze/silver/gold documentation, lineage, unresolved decisions,
validation evidence and a development runbook. Maintain full internal coverage
even with a smaller export. Use native Omni model filenames and validate the
selected target contract; export support does not prove import or query behavior.
Include Omni's extensionless `model` file when model-level AI context is authored.
Check the standalone extracted project and its setup paths, not only the original
generator workspace. Lead with commands whose scripts actually ship, install
their declared dependencies before invoking them, and rebase documentation paths
to the extracted layout. Keep raw rows, databases and credentials outside the curated
preview/shareable export unless their distribution is explicitly selected.

Run [static lint](linting.md) against the reviewed target-rendered SQL and all
native semantic configuration. Fix authored conventions first. Where preserving
source names, projection order or framework-generated formatting is necessary,
record exact-file convention policy exceptions with reasons and hashes. Retain
raw findings and surface exception counts; never waive parser, coverage or data
failures to make a clean-looking result.

Validate files and [record the prepared handoff](guided-workflow.md#record-a-prepared-handoff)
before creating the ZIP. Its guide should lead to reviewing the output and
remaining gates, rather than restarting discovery. Execution, business approval
and production cutover remain separately evidenced actions.

For comparisons, publish separate denominators for source coverage, entity/grain
agreement, key populations, mapped fields, row values and business rules. Show
exact and normalized comparisons separately with the applied normalizations.
Matched fields divided by one model's fields differs from the same count divided
by the other model or their union. Do not rename overlap, agreement or local test
success “overall accuracy.”
