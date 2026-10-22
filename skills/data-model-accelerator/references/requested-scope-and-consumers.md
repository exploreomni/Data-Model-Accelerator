# Requested migration scope and consumer compatibility

Use these additive contracts when refactoring an existing estate. An older run
with no companion remains unassessed; never silently rewrite its saved approval,
code or naming choice. Continue requested provisional work while exposing gaps.
These checks do not execute source SQL, macros, warehouse queries or deployments.

## Register the entire request before mapping

Keep the union of model inventories, ownership lists, migration tickets, explores
and dashboards independent of the target design. Inventory requirements constrain
coverage; they do not dictate one target table per report. Use
`guided_workflow.py record-migration-inventory --run RUN --document INVENTORY.json`:

```json
{"schema_version":1,"registers":[{"id":"retirement-tickets","kind":"ticket",
"evidence_refs":["provided-register:v1"],"rows":[{"id":"row-17",
"source_namespace":"legacy-dbt","native_id":"billing.monthly_revenue",
"domain_ids":["billing"],"legacy_table_id":"old.monthly_revenue",
"evidence_refs":["provided-register:row-17"]}]}]}
```

The accepted register kinds are `model`, `ownership`, `ticket`, `explore` and
`dashboard`. Retain every source row with its original reference; optionally
store supplied metadata in `metadata`. Stable identity is the exact pair
`source_namespace + native_id`, never a basename. `legacy_table_id` or
`consumer_id` explicitly links an existing alignment record. Do not invent a
link from name similarity. Without evidence, the item remains unresolved.
Imports are cumulative and idempotent; omitted rows stay visible, marked omitted
from the latest import. Changed source identity requires a new occurrence ID.
The 20,000-occurrence bound rejects excess input explicitly; it never truncates.

Record exclusions separately with `id`, `source_namespace`, `native_id`,
`domain_ids`, `reason`, `review_reference`. Only an explicit human decision may
exclude requested scope. Source metadata saying "approved" is not that decision.

Classify each requested item as replacement mapping, upstream only, missing
evidence, missing target, or explicit exclusion. An upstream dependency does not
replace a final consumer table. Replacement mapping records an association, not
validated behavior. Report requested/accounted/unresolved counts for tables and
consumers separately. A domain cannot finish while registered requirements lack
replacement evidence or an explicit exclusion. Unassigned domains and withheld
cross-domain detail remain visible in the whole-engagement inventory; a scoped
disclosure never copies unrelated details. Display counts retain the requested
denominator even when detail is withheld.

## Compare public contracts before accepting changes

Use `record-consumer-contracts --document CONTRACTS.json --artifact-root CANDIDATE`
with `schema_version:1, contracts:[...]`. Each contract has:

- `id`, qualified `source_id`, canonical `entity_id`, `consumer_ids`, `evidence_refs`.
- `baseline:{columns:[{name,type,description}],materialization}` plus optional
  `grain`, `history`, `filters`, `currency`, `access`.
- `proposed_materialization` as an explicitly declared value or null/unknown.
- Optional `renames:{old_field:new_field}` and `proposed_behavior:{filters,currency}`.

Freeze the source baseline separately from the design. Compare all public fields,
including unused-but-public fields; report removals, renames, type/description
changes, materialization changes and behavioral differences. Unknown is not
unchanged. Materialization comparisons concern the supplied declarations;
independent generated-code and native validation remain necessary. Do not infer
a table-to-view conversion is harmless because SQL values look equivalent.

For a specific description discrepancy, optionally supply
`definition_checks:[{column,query_path,expression_output,described_references}]`.
`expression_output` must equal the public column. The bounded reader checks direct
references in the terminal SELECT without executing dbt. Unused CTEs cannot
satisfy a public-field claim. Unsupported templates, unions, indirect CTE lineage
or absent readers remain unverified; this is not general prose interpretation.
Resolve business meaning with a scoped analyst/SME review, not a guessed rewrite.

`consumer-review-bindings --document IDS.json` accepts
`{"contract_ids":["public-contract-v1"]}` and emits the current comparison pins.
`review-consumer-changes` accepts `schema_version`, `contract_ids`, `decision`
(`accept_changes`, `requires_fix`, `defer`), `reviewer`, `review_reference`, and
those `bindings`. The host attributes the actual human response. A current
rejection/defer remains open even when automatic comparison found no difference.
Acceptance permits the separate design review; it does not approve code or prove
parity. Candidate SQL changes stale comparison review, not the request that
authorized drafting those same files.

## Publish one review snapshot

Coverage & reuse in START_HERE contains the naming, requested scope and consumer
review. Complete CSVs live under Mappings → Migration Plan → Governed Review.
Existing migration Excel/Word files receive the same scoped rows and snapshot
fingerprint. Full source occurrence exports bypass the 500-row display cap.
Include both documentation and dictionary to export these column-bearing details;
omitting either excludes their nested payload and files, including browser subsets.
When PDF is requested, convert this same Word/document snapshot with an available
document renderer and check it; do not independently summarize or remap it.
If a renderer is unavailable, report PDF as pending rather than claiming it exists.

Work one reviewed domain/batch at a time. The coordinator retains these registries
and sends only relevant IDs, policies and evidence to specialists. Change only
affected scope and dependents; do not rescan all repositories or regenerate an
entire estate to answer one unresolved mapping. Run bounded regression checks
for naming drift, lost inventory, consumer changes and package parity, followed
by required repository checks. No generated test-per-column explosion.
