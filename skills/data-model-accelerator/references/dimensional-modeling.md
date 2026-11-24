# Dimensional modeling standards

These standards apply to every gold (warehouse) model and every semantic field the accelerator
designs, generates or reviews. They classify tables by grain, keep one table per grain and
purpose, place each rule in the layer that evaluates it correctly, and stop silent
reproduction of fallbacks that mix hierarchy levels. `scripts/modeling_lints.py` checks the
statically detectable part of each rule; the checks are heuristic prompts for a recorded
decision, not proof of a correct or incorrect model.

Existing customer naming and modeling conventions still win where they are explicit
([customer modeling standards](customer-modeling-standards.md), [governed naming](governed-naming.md)).
When an existing table breaks these standards, keep its name for its consumers, record a
decision, and raise an open question about renaming or retiring it; never rename silently.

## Classify tables by grain, not by the kind of columns they hold

State the grain of every gold table first, then classify it (Kimball):

| Grain | Class | Typical name |
| --- | --- | --- |
| One row per business event or line | Transaction fact | `_fct` |
| One row per entity per regular period (day, week, month) | Periodic snapshot fact | `_fct`, or the project's snapshot suffix (`_daily`, `_monthly`, `_xa` when it joins other gold tables) |
| One row per process instance, updated as milestones pass | Accumulating snapshot fact | `_fct` |
| One row per entity per period with no measures | Factless periodic snapshot (still a fact) | as periodic snapshot |
| One row per entity (current state) | Dimension | `_dim` |
| One row per entity version, with valid-from and valid-to | Type 2 slowly changing dimension | `_dim`, `_historical_dim` |
| One row per combination of fast-changing attributes, keyed from the fact | Mini-dimension | `_dim` |

Rules:

- A table whose key includes a date or period is a periodic snapshot, even when it holds only
  descriptive columns. Do not name it `_dim`.
- Keep attribute history on the dimension: a type 2 dimension (a new row per change, with
  valid-from and valid-to) or a mini-dimension whose key the fact carries. A monthly copy of
  attributes loses changes inside the month and repeats unchanged rows.
- Periodic snapshot measures are usually semi-additive (balances, counts at period end). Say
  so in their descriptions and never sum them across periods.
- Lint: `period_keyed_dimension` flags a gold `_dim` whose primary key contains a period word
  (`date`, `day`, `week`, `month`, `quarter`, `year`, `period`, `snapshot`, `dt`, `ts`) or whose
  stated grain is "per day/week/month/...". Valid-from keys of type 2 dimensions and
  `_historical_dim` tables are not flagged. Resolve by reclassifying, or by a decision with area
  **Classification** naming the table. Advisory.

## One table per grain and purpose

Two gold tables at the same grain that repeat each other's columns drift apart and confuse
consumers (which one is right?). Keep one, merge them, or justify both, for example a
narrow interface projection kept for a downstream contract.

- Lint: `same_grain_overlap` flags two own-domain gold tables with the same stated grain or the
  same primary key that share at least three non-key columns and at least half of the smaller
  table's non-key columns. Resolve with a decision with area **Same grain** that names both
  tables and says which is kept, merged or justified. **Gate**: blocks promotion.

## Placement is decided per field

Follow [semantic-placement.md](semantic-placement.md). Record the placement of every new or
changed field (warehouse or semantic layer) in the field's design record and coverage entry.

| Logic | Layer |
| --- | --- |
| Fixed reporting rules: flags, classifications, groupings, rankings reused as filters, cleansing, deduplication, history | Warehouse (dbt) |
| Ratios, distinct counts, averages of ratios, period-to-date and other query-time aggregations, anything that must respect the user's filters | Semantic layer |
| Split rules | Warehouse stores the additive components once; the semantic layer computes the ratio after filters |

- Lint: `placement` flags a gold model that stores a ratio (`SAFE_DIVIDE`, `/ NULLIF(`, `DIV0`) or
  a distinct count, and a semantic dimension that computes a fixed grouping (three or more `WHEN`
  branches) or a ranking/window function at query time. Resolve by moving the logic, or by a
  decision with area **Placement** naming the table (for example a stored ranking that must be
  identical in every report). Advisory: the patterns cannot see intent.

## No fallbacks that mix hierarchy levels

A fallback such as `COALESCE(industry.description_2, industry.industry_description)` fills a
level-2 (division) field with a class-level description when the level-2 value is missing. The
result is a column whose values belong to different levels of the hierarchy, so grouping and
filtering on it are wrong. Legacy code that does this must not be copied silently.

- Reproduce it only through a decision that says why mixed levels are wanted, or decline it and
  leave the value empty (the lower-level value stays available in its own column).
- Lint: `level_mixing_fallback` flags `COALESCE`, `IFNULL` and `NVL` calls whose column arguments
  carry different level numbers (`_2`, `lvl_2`, `level_2`, `description_2`, ...) or mix a levelled
  descriptive column with an unlevelled one. Resolve by removing it, or by citing a recorded
  decision ID (for example `-- D-32`) in a SQL comment on the same or preceding line. **Gate**.

## Semantic layer reach and language

These complement [omni-static-contract.md](omni-static-contract.md):

- Every own-domain gold table must be reached by a topic through an explicit binding. Lint
  `gold_without_topic`; resolve by adding it to a topic or by a decision with area
  **Topic exemption** naming the table and the reason (for example a staging-only bridge).
  **Gate**. Gold tables owned by another domain are that domain's concern.
- Semantic descriptions, labels, group labels, AI context and sample queries are business-facing.
  Lint `description_language` rejects legacy BI tool names (Looker, LookML), "legacy",
  migration notes, "provisional", dashboard/tile/look/explore numbers, ticket IDs, and every name
  in the page's `meta.legacy_terms` (the systems being replaced). YAML comments are not checked.
  Fix the text; keep migration context in the design documents. **Gate**.

## Running the checks

```sh
python scripts/modeling_lints.py <page.json | START_HERE.html> [--legacy-term NAME] [--output report.json]
```

The domain review projection adds one static observation per lint to the review page, and
`domain_review_page.py promote` refuses a draft with an unresolved gate lint. Decisions resolve
a finding only when their status is answered or assumed; an open question does not.
