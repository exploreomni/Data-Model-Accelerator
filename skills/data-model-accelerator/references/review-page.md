# Review page

Every exported package opens on `START_HERE.html`. The established guided portal and
partitioned portal remain the default so runtime evidence, failed quality checks, domain
progress, metadata and deployment controls remain available. Small packages embed files;
large packages link to bounded per-table and per-file pages.

`scripts/review_page.py` and `assets/review-page/` are an alternative review presentation,
not the default package renderer. The separate [domain review page](domain-review-page.md)
is an opt-in companion: `review.domain_review={"domain":"orders"}` asks the existing finalizer
to add `03_Design_Documents/Domain_Review.html` (classic: `01_Model/Domain_Review.html`)
when documentation is selected and the review contains models. It does not replace the root entrypoint, audience
and selection rules, evidence routes, feedback or deployment controls. Its standalone review
versioning tools are not a completed-delivery workflow. The optional
fields below are additive: old engagement formats remain valid, absent fields mean
unassessed, and none of them records approval. Canonical delivery data remains authoritative.

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
| Validation | `#validation` | Supplemental file syntax counts plus canonical recorded checks and unresolved findings. Semantic validation uses the existing semantic report, not a second parser in the page. Nothing is executed by the page. |
| Open items | `#open-items` | Open questions, pending or failed checks, unresolved legacy models and placeholders. |

The table inspector shows grain, keys with their targets, the topics that use the table, lineage
(depends on / used by and source tables), disposition, existing source, security notes, columns
and code. The topic inspector shows the base view, canonical join structure and binding gaps,
the dashboards it serves and its files. Predicates, fields and AI context that are not
projected are explicitly marked for inspection in the original files.

## Optional review fields

Validated by `delivery_portal.validate_review`; the page shows "not supplied" or a neutral default
when they are absent. They are authored evidence, never approval or execution.

| Field | Shape |
|---|---|
| `review_meta` | `domain_position`, `repositories` (`role`, `name`, hex `commit` or null, hex `fingerprint` or null, `complete`), `read_order`, `not_done` |
| `domain_review` | `{domain: "orders"}`; optional companion using the existing finalizer and selected package, not a domain-scope filter or approval |
| `subject_areas` | `[{id, name, shared?}]`; each model may carry `area`. Without it, gold tables are grouped by domain. |
| model fields | `security_notes` (list), `existing_source` (text), `sources` (raw source tables, list) |
| decision fields | `options`, `assumed_option`, `status` (`answered`, `assumed`, `open`), `area`, `question` |
| `legacy_coverage` | `[{legacy, status, targets, topics?, cross_topics?, note?, source?, domain?}]`; covered, partially covered and retire candidate need a target, unresolved has none |
| `static_checks` | `[{id, label, count, scope?, items?}]`; overrides the counts computed from the packaged files, for example when a base project was used to resolve refs |
| asset fields | `topics`, `coverage_status` (`served`, `partly_served`, `not_served`), `coverage_reason` |

Topic lineage comes from `topic_join_trees`, produced by the semantic stage/finalizer using
explicit warehouse bindings. The page never matches a view to a table by name. Missing canonical
trees, unresolved bindings, inherited topics and disconnected warehouse models remain visible.
Pipeline geometry and ancestry come from `pipeline_diagrams`; inline diagrams use the shared
SVG sanitizer. Static file counts and TODO placeholders are supplemental evidence only. Static counts resolve refs against the packaged files and the review inventory only; refs
to tables outside the review appear as unresolved, so supply `static_checks` when a base project
was checked.

## Checks

The default small packages pass `portal_checks.validate_page`: the page keeps the required routes
(`architecture`, `lineage`, `table-dictionary` inside `model`; `implementation-code` and
`replacement-map` inside `delivery`; `review-feedback`). Large packages retain `portable_site.check_page` and their established routes. The alternative
renderer uses `review_page.check_structure` for its tabs; it must not replace the default
contract checks. Validate feedback round trips and visible validation outcomes, not only tabs.
