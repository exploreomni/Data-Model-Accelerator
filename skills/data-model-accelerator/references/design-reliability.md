# Evidence-grounded design and review

Use this workflow for new designs and when explicitly adopting improved coverage
in an existing engagement. Existing saved engagements remain readable without
invented coverage, reviews or migrated approval. Their new readiness fields say
`unassessed` until the corresponding work is performed. All existing source
adapters and warehouse targets use these shared contracts.

## Operator setup and intake

Run `scripts/check_installation.py --preflight --selected-skill PATH` once with
the actual skill directory. Optionally supply `--expected-skill PATH` and explicit
`--alternative-skill PATH` entries. Keep the selected path, content hash and
repository revision in the private run audit. Resolve conflicting installations
before attributing behavior to a release. This is portable skill inspection;
it does not prove a Cortex, Claude, Codex, Gemini or Genie native plugin loaded.
Do not invent a plugin manifest or alter global model settings to repair setup.

Use `scripts/operator_contracts.py examples` for current input shapes and
`validate-answers --answers FILE` before starting or changing intake. Invalid
preferences are retained with correction guidance, never silently removed.
For example, preserve naming is
`{"mode":"preserve","domain":null,"decision_reference":null}`.
Host model/effort are not intake answer fields. Preserve configured defaults;
unknown observed settings remain unknown.

Record conversational answers through the existing `answer` command. Record
only actual user decisions through `answer-decisions`; recommendations and working
assumptions remain proposals. Explain each outstanding question as: **what to
decide, recommendation and reason, affected models, consequence of deferral**.
The user can answer in ordinary language. The host prepares the bound request.
A selected domain supplies a missing priority-domain answer; resuming does not
restart intake or overwrite known preferences.

## Inventory before assigning targets

Run each relevant deterministic parser once and retain its complete contract.
Register every supplied input root separately using
`guided_workflow.py record-design-coverage --run RUN --document FILE`. This
complements report-occurrence `record-coverage`; it does not replace it.
Separate namespaces prevent identical native names from different repositories
being mistaken for the same object. Do not execute SQL, macros or project scripts
while inventorying. Keep run state and artifacts outside all input roots.

The version 1 JSON envelope contains `schema_version`, `sources`, `objects`,
`consumers` and `assignments`:

| Collection | Required row fields |
|---|---|
| sources | `id`, `namespace`, `role`, `kind`, `status`, `domain_ids`, `inventory`; explicit absolute `root` when available |
| source inventory | `status`, `reference`, `files` |
| files | relative `path`, `sha256`, parse `status`, `object_ids` |
| objects | `id`, `source_id`, `native_id`, `kind`, `status`, `domain_ids`, `evidence_paths`, `depends_on` |
| dependency | `reference`, optional resolved `object_id` |
| consumers | `id`, `source_id`, `object_ids`, `domain_ids`, `evidence_paths`, `description` |
| assignments | `id`, `object_ids`, `consumer_ids`, `model_ids`, `kind`, `reason`; explicit `review` for exclusions |

Source kinds are `repository` or `external_inventory`; source status is
`available`, `missing` or `unavailable`. Inventory status is `complete`, `partial`
or `not_supplied`. File parse status is `parsed`, `partial`, `unsupported` or
`unreadable`; readable files require captured hashes. Object kinds are `table`,
`view`, `model`, `report`, `metric`, `interface` or `other`; status is `parsed`,
`partial` or `unsupported`. Preserve macros, transformations and unresolved
references as observed objects/dependencies even when they cannot be translated.

Assignment kind is `implementation`, `interface` or `excluded`. Exclusions have
no target IDs and require `review: {reviewer, reference}` attributable to actual
scope review. An interface does not fulfill implemented-source or consumer
coverage. Preserve unmapped observations instead of deleting them. Unknown source
ownership affects the relevant domain; explicit file/object ownership scopes
later rechecks to affected models. Missing prior observations remain visible.

Repository filename closure is checked independently of the proposed design.
An external inventory covers only its captured files, not an inaccessible live
warehouse. Source hashes establish integrity; declared parse completeness is
still host-reported. A direct source-to-gold design can be valid: coverage checks
do not require a physical silver layer. Assess whether staging, intermediates,
macros and shared logic are accounted for, rather than counting tier labels.

## Assemble one canonical proposal

Use `guided_workflow.py assemble-design --run RUN --document FILE`, or
`design_builder.py assemble --document FILE --output NEW_FILE`, instead of a
one-off assembly script. Discover a valid starting envelope through
`operator_contracts.py examples design-assembly`.

The request has `schema_version: 1`, `kind: design_assembly`, `id`, `revision`,
`nodes`, `edges`, and optional `assets`, `decisions`, `existing_models`. Nodes
require `id`, `name`, `domain`, `layer`; other fields use the existing canonical
design contract. Missing grain, keys, types, history and security stay unknown.
Each object is explicitly a `model`, `source` or `interface`. Interfaces are
visible external dependencies, never counted as implemented tables or assigned
executable tasks. A proposed key is not a uniqueness test.

Retain all nodes, relationship endpoints, composite key bindings and cardinality
direction. A lineage edge means derivation and cannot carry join multiplicity.
A relationship may be one-to-one, one-to-many, many-to-one, many-to-many or
unknown; never mechanically assign one-to-many. Invalid dependencies or cycles
fail clearly instead of being silently dropped. Unknown bindings remain review
gaps and can accompany explicitly requested provisional code.

Export selected design files with
`design_builder.py export --document CANONICAL_DESIGN --output NEW_DIRECTORY`.
This derives the narrative, dictionary, full ERD, bounded diagram views and
manifest from one revision. It does not replace the finalizer, create code or
imply approval. Register the selected files in the existing review artifact list
and finalize the handoff with `START_HERE.html`. Use those same projections for
requested PDF/Word documents, and verify content and rendered pages; the builder
does not itself render PDF/Word. Never maintain a second model inventory in prose.

The exported CSV is a review dictionary, not the version 2 warehouse-metadata
deployment contract. During implementation, author that separate contract with
actual model candidates in `models` and separately declared inputs in `sources`.
Do not flatten every canonical node into a v1 `models` array and expect
`migrate_data_dictionary.py` to infer their roles: that helper preserves the
supplied inventory. External interfaces remain unresolved dependencies, not
executable models or verified warehouse objects. Use the metadata validator and
explicit resource mapping before metadata deployment; no missing catalogue
binding, sensitivity classification or approval may be invented for a draft.

## Classify provenance and reuse

Use `record-design-evidence --run RUN --document FILE`. The envelope is
`schema_version: 1`, `kind: design_evidence`, `claims`, `baselines`.

Each claim has `id`, `model_ids`, `subject`, `basis`, `statement`, `sources`, and
optional `baseline_id` or `assertion_reference`. Subjects: `grain`, `keys`,
`columns`, `definitions`, `history`, `security`, `dependencies`, `relationship`,
`baseline`. Bases:

- `observed_metadata`: references a registered `warehouse_catalogue` source.
- `repository_declaration`: describes supplied SQL/YAML, not a live warehouse observation.
- `user_assertion`: retains an attributable `assertion_reference`.
- `proposal`: an assumption or target choice, never proof of existing behavior.

Each source reference has `source_id`, relative `path`, `sha256`, `locator`.
Its file must already belong to the registered inventory and match current bytes.
Never copy staging YAML columns into bronze and call them observed physical
columns. Do not convert a name match into verified column or relationship mapping.

A baseline contains `existing_id`, `snapshot`, `snapshot_source`, `claim_ids`,
`captured_by`, `capture_reference`. Capture it separately before target design.
`snapshot_source` uses the source-reference shape with a JSON pointer locator;
its source role is `existing_models`. The captured pointer must equal the
canonical existing snapshot. A target proposal cannot supply its own baseline.
This checks captured bytes, not whether a human-authored capture is truthful.

Reuse needs separate source-backed claims for all six comparison dimensions:
grain, keys, definitions, history, security and dependencies. The canonical
comparison's `evidence_refs` must name those claim IDs. “No change proposed” is
not evidence of compatibility. Unknowns prevent reviewed implementation for the
affected scope but never remove the provisional-generation route.

## Independent review and human review

Use one architect and one independent reviewer with the existing bounded
`agent_context.py` packets. Include the scoped original expressions, metadata and
consumer requirements, not only the architect's summary. Preserve the host's
configured model/effort; do not route architecture or review to a weaker model
merely because a context budget is smaller. Any routing change needs the existing
controlled benchmark and explicit configuration.

Obtain current bindings with `independent-review-bindings --run RUN --entities
ID ...`. Record completed review through `record-independent-review` with:

- `schema_version: 1`, `kind: independent_design_review`, `reviewer_id`,
  `author_ids`, `review_reference`, exact `bindings`, scoped `claim_ids`.
- `findings`: rows with `id`, `model_ids`, `severity` (`blocking`/`advisory`),
  `status` (`open`/`resolved`), `description`, `evidence_reference`.
- `result`: `accepted` or `changes_requested`; open blockers cannot be accepted.
- `execution`: `host`, `task_reference`, `context_reference`, `requested_model`,
  `observed_model`, `requested_effort`, `observed_effort`. Unknown settings are
  null, not inferred from the requested model. Retain actual packet/execution
  receipts using the existing agent telemetry helpers.

The reviewer cannot be the listed author. This is host attribution, not identity
authentication; never fabricate a worker receipt or independent review. Changed
source/evidence/model scopes stale their review and affected dependents while
unrelated models remain reusable. One targeted correction pass carries unresolved
findings forward; additional iterations require new material evidence or a named
unresolved issue. A fresh worker name does not reset the review budget.

After independent review, ask the user to review the displayed design and record
the actual decision through the existing `approve-design` contract. Independent
review never grants human approval, native validation or deployment authority.
The review page presents these as separate statuses. A structural `consistent`
result does not mean complete, accurate or production-ready.

If the user requests code now, use `draft-bindings` and `request-draft` and produce
the scoped provisional warehouse and semantic files. Keep unverified bindings
and open decisions visible. Missing context must not turn the run into an empty
“complete” delivery; native validation and release remain separate operations.
