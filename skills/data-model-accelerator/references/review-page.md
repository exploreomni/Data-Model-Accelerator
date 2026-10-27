# Review page

Every exported package opens on one review page, `START_HERE.html`, rendered by
`scripts/review_page.py` from `assets/review-page/`. Small packages embed their files, so code
opens inline. Large packages (more than 100 tables, more than 200 files or more than 4 MB of
embedded data) keep their per-table and per-file pages and the review page links to them.
Engagement status pages keep the existing portal.

The page is a projection of the checked review: the embedded `delivery-data` block is the same
projection the package checks verify, and `review-page-data` is derived from it and from the
packaged files only. It reads no source repository, runs nothing and records no approval.

## Tabs

| Tab | Route | Content |
|---|---|---|
| Overview | `#overview` | Title, domain position and stack, candidate banner, headline cards (models by layer and disposition, dbt files, semantic topics, legacy coverage, decisions, dashboards), repositories, a numbered reading order and a not-done-yet list. |
| Data model | `#model` | Per subject area: raw → bronze → silver → gold pipeline, gold relationships (hover for `from → to (cardinality) on key`), then topic lineage: each semantic topic, its base view and joined views. Click a table or topic for its inspector. |
| Code & files | `#delivery` | Every packaged file, viewable in the page (or linked to its file page), with apply notes, source tables used by new staging models and semantic-layer placeholders to replace. |
| Decisions | `#changes` | All decisions; with the optional register fields: ID, area, question, options, assumed option and answered/assumed/open status. |
| Legacy coverage | `#replacement-map` | Every legacy model → target with covered, partially covered, retire candidate, out of domain or unresolved; then dashboards and requirements → topics. |
| Data dictionary | `#table-dictionary` | Every column of every included table, searchable. |
| Validation | `#validation` | Static check counts on the packaged files (YAML errors, models without YAML, unresolved refs and sources, broken semantic field references and relationships), then the remaining and reported checks. Nothing is executed. |
| Open items | `#open-items` | Open questions, pending or failed checks, unresolved legacy models and placeholders. |

The table inspector shows grain, keys with their targets, the topics that use the table, lineage
(depends on / used by and source tables), disposition, existing source, security notes, columns
and code. The topic inspector shows the base view, joins with cardinality and predicate, the
dashboards it serves, AI context, fields and its files.

## Optional review fields

Validated by `delivery_portal.validate_review`; the page shows "not supplied" or a neutral default
when they are absent. They are authored evidence, never approval or execution.

| Field | Shape |
|---|---|
| `review_meta` | `domain_position`, `repositories` (`role`, `name`, hex `commit` or null, hex `fingerprint` or null, `complete`), `read_order`, `not_done` |
| `subject_areas` | `[{id, name, shared?}]`; each model may carry `area`. Without it, gold tables are grouped by domain. |
| model fields | `security_notes` (list), `existing_source` (text), `sources` (raw source tables, list) |
| decision fields | `options`, `assumed_option`, `status` (`answered`, `assumed`, `open`), `area`, `question` |
| `legacy_coverage` | `[{legacy, status, targets, topics?, cross_topics?, note?, source?, domain?}]`; covered, partially covered and retire candidate need a target, unresolved has none |
| `static_checks` | `[{id, label, count, scope?, items?}]`; overrides the counts computed from the packaged files, for example when a base project was used to resolve refs |
| asset fields | `topics`, `coverage_status` (`served`, `partly_served`, `not_served`), `coverage_reason` |

Computed automatically: topic lineage from the packaged `.topic`, `.view` and `relationships`
files (needs PyYAML), static check counts, placeholders (`TODO` lines in semantic files) and the
cards. Static counts resolve refs against the packaged files and the review inventory only; refs
to tables outside the review appear as unresolved, so supply `static_checks` when a base project
was checked.

## Checks

Small packages pass `portal_checks.validate_page` unchanged: the page keeps the required routes
(`architecture`, `lineage`, `table-dictionary` inside `model`; `implementation-code` and
`replacement-map` inside `delivery`; `review-feedback`). Large packages pass
`portable_site.check_page`, which calls `review_page.check_structure` for the eight tabs in order
and every route. Change the template, `review_page.TABS` and this page together.
