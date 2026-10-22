# Preserve behavior while refactoring architecture

A legacy implementation is evidence of existing behavior, not the default target
architecture. A go-forward repository supplies conventions and candidate reusable
models; its name alone never approves reuse. Consumer/report inventories define
required outcomes and reconciliation coverage, not one target table or topic per
inventory row. Keep these distinctions explicit for every domain.

## Record the direction once

Reuse the user's stated intent. Ask only when repository direction or behavior
is genuinely unresolved. After registering the actual source roots, record a
version-1 companion with `guided_workflow.py configure-migration-intent --run RUN
--document intent.json`. Never infer direction from repository names. Mixed
repositories use path-scoped roles; a file can be legacy evidence and raw staging.
Target role does not grant permission to write to a source repository.

```json
{
  "schema_version": 1,
  "kind": "migration_intent",
  "domain_id": "commerce",
  "structural_objective": "refactor",
  "behavior": "preserve",
  "objectives": [
    {"id": "shared-grain", "statement": "Replace report-specific order tables with shared grain-defined entities"},
    {"id": "cutover", "statement": "Remove legacy mart dependencies", "kind": "eliminate_legacy_dependencies"}
  ],
  "source_roles": [
    {"id": "historical", "root_id": "primary", "role": "legacy_baseline", "path_prefix": "models"},
    {"id": "raw-contracts", "root_id": "primary", "role": "raw_staging", "path_prefix": "models/staging"},
    {"id": "destination", "root_id": "target", "role": "target_implementation"},
    {"id": "consumers", "root_id": "requirements", "role": "consumer_requirements"}
  ],
  "behavior_constraints": ["Preserve observed filters, currency, history and access rules; flag conflicting definitions"],
  "request_reference": "Replace with the actual user request reference"
}
```

The named roots must already be registered. `structural_objective` is `refactor`,
`preserve` or `new_model`; `behavior` is `preserve`, `specified_corrections` or
`undecided`. Unknown catalogue bindings remain unknown. A preserved naming policy
also does not imply preserved table structure. Existing engagements without this
companion stay readable and show unassessed intent; adoption never fabricates
prior decisions, assessments or approval.

## Design from transformation evidence

The coordinator extracts once. Send the architect a bounded domain packet with:

- The recorded intent and source roles.
- Relevant actual SQL/macros, joins, filters, aggregates, keys, history and access
  expressions, plus declared source schemas. Directory counts are orientation.
- Relevant target conventions and candidate target models for comparison.
- Required consumers/metrics as coverage constraints and known conflicts.

Use `migration-intent-packet --document {"domain_id":"commerce"}` to obtain the
current contract in saved workflow state. Packet requests include
`migration_intents: [contract]`, a `bindings["migration_intent.commerce"]` hash,
and optional `design_evidence` records `{domain_id, evidence_id, role}` pointing
to supplied excerpts. Roles are `legacy_transformation`, `source_contract`,
`target_convention`, `target_model`, `consumer_requirement`. Evidence roles are
host declarations, not proof of semantic sufficiency. Missing roles are reported
as context incomplete. Request exact missing objects/lines; do not broaden to a
new repository scan or silently fill gaps with invented columns.

The architect proposes a target entity graph at explicit grains. Explain each
business process and why facts and dimensions belong in the model. Capture primary
and foreign keys, history, security, common intermediates, reusable aggregates and
downstream metric placement in the existing design/decision records. Keep legacy
models in baseline inventory and map them
to targets through [historical alignment](legacy-alignment.md): split, merge,
replace, retained exception, retirement candidate or moved semantic logic. Never
copy every legacy dependency into the target graph merely to achieve coverage.

Compare every reused target model across grain, keys, definitions, history,
security and dependencies using original evidence. A valid already-built model
can fulfill the objective; there is no quota for new SQL or arbitrary change
percentage. Legacy reuse needs an explicit reviewed exception. Keep unavoidable
legacy dependencies visible as transitions and state their removal conditions.

Keep canonical evidence identifiers in existing-model and reuse records. Resolve
them through the registered [design evidence](design-reliability.md) claims and
independent baseline to the exact source file and hash. The assessment supplies
those original files as `source_evidence`, including registered multi-repository
references such as `@sources/target/models/dim_customer.sql`. Matching a filename
or a target convention alone does not establish an existing model's origin.

## Build and independently assess the outcome

Engineering builds the target graph; it does not wrap each legacy final table
and call that refactoring. Scoped task fingerprints include intent; relevant
intent changes invalidate affected work and downstream dependencies. Provisional
requests still authorize candidate file generation with visible gaps.

The Omni Modeler starts with target physical bindings and shared metric/consumer
purposes. It records why each topic exists, its grain, measures, safe joins,
security and source consumers. Topic count is not a success measure. Use existing
Omni/native validation contracts; artifact presence is not dashboard parity.

Obtain current inputs with `migration-assessment-bindings --document
{"domain_id":"commerce"}`. An independent reviewer reads the original intent,
original scoped source evidence, target graph and historical mapping. Record its
attributed result using `record-migration-assessment`:

- `schema_version`, `domain_id`, current `binding_sha256`, distinct `author` and
  `reviewer`, `review_reference`, and `status` (`accepted` or `changes_requested`).
- `objective_results`: each `objective_id`, `status` (`addressed`, `unresolved`,
  `not_met`), `model_ids`, byte-pinned `source_evidence: [{reference, sha256}]`,
  existing `mapping_ids`, `analysis`, and `findings`.
- `transitional_dependencies: [{model_id, reason, resolution}]`.
- `semantic_purpose: [{model_ids, topic_ids, consumer_or_metric_refs, evidence_refs}]`.
- Top-level `findings`, and optional reviewed
  `legacy_exceptions: [{model_id, reason, evidence_refs}]`.

An objective maps the relevant target outputs; their canonical upstream dependency
chain accounts for supporting sources and intermediates. Do not manufacture
historical final-table mappings to raw tables. Reused dependencies still require
their own compatibility evidence, and disconnected objects remain unaccounted.
Every applicable objective and in-domain object must be accounted for. Recorded
comparisons, source bytes and mappings are checked for scope/freshness; identities
and judgments remain host-attributed. Reviewer labels do not authenticate a person
or prove business acceptance. Record findings honestly rather than modifying
expectations to fit copied code. Actual user design approval stays separate.
Assessment rule changes require a fresh assessment without invalidating unchanged
code-generation intent by themselves. Exception and semantic-purpose evidence
references must identify files already byte-pinned in the assessment.

Implementation registration records bounded observations of exact legacy copies
and simple `select * from ref(...)` wrappers. These observations never suppress
provisional outputs. Full domain completion requires current architecture
assessment and resolution or explicit review of retained legacy code. An
eliminate-legacy-dependencies objective cannot pass with transitions or retained
legacy exceptions. Absence of a detected copy is not proof of good modeling.

Live production promotion of an adopted refactor also checks this outcome evidence;
publication candidates and separately authorized development validation remain
available. Changes invalidate the prepared handoff.

Package review remains available while architecture is unresolved. Its file
integrity result is separate from refactor conformance, physical validation,
behavioral parity, security testing and business acceptance. Inspect target
entities, reused work, old-to-new mappings, transitions and unresolved objectives
before claiming the refactor is complete.

## Review a large design by domain

Export from the retained canonical engagement rather than rerunning discovery:

```sh
python3 skills/data-model-accelerator/scripts/domain_review_export.py \
  --state /path/to/run/state.json \
  --output /path/to/new-domain-review
```

The new directory contains `START_HERE.html`, an accounting index and a guided
review plus portable ZIP for each domain. Every object is owned exactly once;
shared dependencies appear wherever needed. Relationships crossing a review's
boundary remain identified in the index. Definitions, source/context bindings
and output hashes remain linked to the retained snapshot.

Add `--max-owned-models N` to split each domain into deterministic presentation
batches with complete dependency closure. This only partitions the review;
it does not approve batches, change the model, or move files between source roots.
If one complete dependency chain still exceeds a safety limit, export fails
without dropping objects or publishing a partial delivery. Refine the reviewed
scope explicitly rather than increasing scanner or archive limits.

These exports include design documents, dictionaries and diagrams. Registered
implementation artifacts stay in their original delivery. Use `--audience
engineer` when appropriate and supply `--disclosure /path/to/contract.json` for a
governed export. Existing disclosure and size limits apply to every package and
the index. The original state and source repositories remain unchanged.
