# Mapping coverage, reuse ownership and reconciliation

Read this when consolidating specialist findings or resuming a reviewed design.
Use the same engagement, design, task and provisional-generation commands. These
records add evidence; none grants human approval or native execution authority.
Older engagements remain unassessed until evidence is registered. Do not make
up a passing record to upgrade them or regenerate unchanged domains wholesale.

## Preserve the denominator

The coordinator keeps full adapter reports and an explicit expected-file inventory.
Use `guided_workflow.py record-coverage --run RUN --document COVERAGE.json` after
source extraction. The host prepares the document, not the business reviewer:

- `schema_version: 1`, `reports`: original source-adapter results.
- `expected_files`: every supplied source's `source`, relative `path`, `sha256`.
- `requirements`: objects with `id`, `description`, `domain`.
- `targets`: `id`, `kind` (`warehouse` or `semantic`), canonical `model_id`, plus
  `column` for warehouse targets or `semantic_object` for semantic targets.
- `mappings`: `occurrence_id`, `requirement_ids`, `target_ids`, `status`, `basis`,
  `rationale`. Status is `mapped`, `unresolved`, `unsupported`, or
  `excluded_by_review`; exclusions also require the host-attributed
  `review_reference`. Basis is `expression_analysis`, `structural_binding`,
  `reviewed_definition`, or `unassessed`. Name matching alone is insufficient.

Use `mapping_coverage.inventory(reports, expected_files)` to obtain occurrence
IDs, including legacy reports without them. Multiple requirements and targets
may share occurrences. Omitted mappings remain unresolved. Unknown identities,
conflicting duplicates and missing target columns are rejected. Keep original
expressions, population, filters, currency, time and security context in the
adapter result; a short task summary is a pointer to evidence, not its replacement.
Mappings pin explicitly linked cross-file owners, parents and retained object
dependencies as well as their own files. Changes to those filters or source
bytes stale the affected mappings; names alone do not establish a dependency.

Counts cover retained objects, expressions and dependency occurrences. Repeated
field references remain separate; containers and expressions are also included.
They do not prove a complete SaaS export or effective runtime behavior. Report
retained inputs, authored mappings and validated parity separately. Missing
expected files and orphan requirements remain visible. A declaration of a
semantic target does not prove that Omni accepts it or returns the same numbers.

## Account for every existing model

Use `guided_workflow.py record-reuse --run RUN --document REUSE.json`.
`schema_version: 1` contains:

- `inventory`: one entry per canonical `existing_models` record with
  `existing_id`, `namespace`, `native_id`, `snapshot_sha256` (the `hash_json` of
  that exact existing-model object). Native identifiers are supplied evidence,
  not independently verified warehouse identity.
- `assignments`: `existing_ids`, `owner_domain` (or null), `disposition`,
  `model_ids`, `requirement_ids`, `evidence_refs`, and `rationale`.
  Disposition is `reuse`, `extend`, `replace`, `defer`, `undetermined` or
  `out_of_scope`. Reviewed scope exclusions require `review_reference`.

Grouped `existing_ids` patterns expand only against this pinned inventory; the
ledger retains the exact expansion. No match, duplicate assignment or unknown
model/requirement is an error. Omitted assignments stay explicitly unassigned.
Moving a model outside one specialist's domain does not resolve its ownership.
Reuse/extend/replace must agree with the canonical design and its existing
grain, key, definition, history, security and dependency comparisons. Unknown
compatibility remains unknown, even when a preferred disposition is recorded.

## Reconcile domain proposals before projection

Every `import-design` records canonical structural diagnostics. When specialists
design separate domains, use `guided_workflow.py reconcile-design --run RUN
--document PROPOSALS.json`; do not concatenate their outputs manually. The
version-1 request contains `proposals`, each with a stable `id`, a schema-v1
`design`, and `shared_rules`. Proposals identify the same design and revision.
Shared entities use the same IDs. Cross-domain references must resolve in the
combined design.

Shared rules have `id`, `dimension`, `value`, `model_ids`, `evidence_refs`.
Use common IDs for shared currency, time, population, security, history, grain
and key decisions. A common ID with conflicting meanings remains a conflict;
unknown meanings stay unknown. The tool does not infer that differently named
business rules are equivalent. The coordinator establishes these common IDs
before dispatching domain work and turns unresolved rules into explicit design
questions with options, consequences and the appropriate human reviewer.

Compatible proposals import one new canonical revision automatically, without
approving it. Conflicts retain the previous canonical design and exact proposals;
they never choose a winner. Correct the affected proposals and submit a new
revision. A direct canonical import does not erase pending proposal conflicts.
Input, entity, relationship or decision changes refresh reconciliation status;
affected reviewed scopes require reconsideration, while unaffected scope remains
usable. Explicitly requested provisional code remains possible with the findings
visible. Reconciliation is required evidence, not proof of business correctness.

## Storage and change handling

Versioned records live in content-addressed `review-evidence/` files beside the
engagement state. State revisions retain references and scoped hashes instead
of copying the full source corpus. Tampered, missing, symlinked or unsupported
records never become a successful check. Do not manually modify these files.
Re-register corrected evidence through the guided commands.

Material mapping/reuse changes invalidate affected model bindings and dependent
work. Unchanged scopes retain their previous review and outputs. A tool upgrade
can still require checks under the existing component-version policy; this is
separate from a changed business requirement. The coordinator supplies each
worker its relevant records and shared interfaces, not every evidence file.

Provisional generation remains available on explicit user request. Unresolved
coverage, reuse and model conflicts must be disclosed, not silently promoted to
approval. Keep design-only selections free of unrequested code. Final delivery
still requires the selected files, dictionary, diagrams and offline Start Here
page; their presence does not establish native or business acceptance.

The existing Start Here page presents coverage, ownership and conflicts alongside
the model and code. Detailed tables are optional and bounded; totals describe the
full registered ledger, and omitted detail rows are disclosed. For a full audit,
add the selected evidence export through the existing artifact and disclosure
workflow. Do not automatically ship the full source corpus in the default review
package or copy private engagement paths into the page.
