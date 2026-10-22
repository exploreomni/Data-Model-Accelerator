# Optional legacy-model alignment contract

`scripts/legacy_alignment.py` retains a supplied historical final-table baseline
and compares it with a proposed domain design. It does not execute SQL, call an
external service, authorize an agent, approve a design, or prove parity.
`reuse.existing_id` and canonical design schema v1 remain unchanged. A split or
merge belongs in this optional many-to-many sidecar.

## State and API

The opt-in state is `workflow.legacy_alignment`, schema version 1, containing
per-domain choices, one baseline reference, per-domain comparison references,
host-attributed decisions, and previously affected target scopes. Documents live
in content-addressed `legacy-alignment/` files beside the engagement state,
outside the read-only source. Existing safe JSON loading, secret screening,
immutable writes and symlink checks apply. The guided workflow owns locking and
state revision persistence; direct Python callers must serialize mutations.

Public calls:

```python
configure(state, request)
register_baseline(state, request, run_dir)
register_alignment(state, request, run_dir)
record_decisions(state, request)
scope_bindings(state)                  # model_id -> material hash
gaps(state, selected)                  # scoped material decision issues
public_summary(state, allowed_models=None)
reconciliation_summary(domain_summary, source_lineage=None, consumers=None,
                       known_consumers=None, evidence_current=False) # keyword-only optional inputs
fingerprint(state)                     # handoff/display freshness
candidates(state, domain_id)           # names suggest candidates only
context_packet(state, domain_id, max_bytes=32768, record_ids=None)
validation_cases(state, domain_id)      # pending case scaffolding only
```

When the feature is absent, summary/fingerprint/packet/candidates/validation
return `None`, scope bindings return `{}`, and gaps return `[]`. A declined
comparison with no previous mappings does not change entity bindings. Declining
after recording mappings retains their history and unresolved correction gaps.
Requesting a comparison, supplying a baseline, or initially recording an empty
comparison also leaves entity bindings unchanged until a mapping associates a
target scope. Previously associated scopes retain invalidation tombstones.
Merely opting in or supplying a baseline leaves existing design approvals
current. Only mapped target associations, scoped dispositions and subsequent
material changes affect model bindings and their dependent work.
The module does not alter domain discovery or its selection digest. Where a
domain journey exists, configuration, mapping and review mutations require the
active domain, and target placement must stay within its declared shared scope.
Baseline acquisition may inventory multiple known consumer domains before design.
Baseline registration replaces the retained inventory snapshot. When adding a
later domain, merge its new evidence into the existing inventory first; preserve
unchanged tables and evidence for completed domains. Remove historical items
only deliberately, since removal makes their previous comparisons stale.

## Record intent and baseline before design

```json
{
  "schema_version": 1,
  "domain_id": "commerce",
  "mode": "refactor",
  "comparison_requested": true,
  "behavior": "preserve",
  "request_reference": "synthetic://user/choice"
}
```

Modes are `new_model`, `refactor`, or `mixed`; behavior is `preserve`, `correct`,
or `undecided`. This records supplied intent, not human approval.

Baseline request shape:

```json
{
  "schema_version": 1,
  "status": "partial",
  "tables": [{
    "id": "legacy.orders",
    "namespace": "warehouse.database.schema",
    "native_id": "orders_final",
    "label": "Historical orders final",
    "consumer_domains": ["commerce"],
    "columns": [{
      "id": "order_key", "name": "order_id", "type": "integer",
      "definition": "One identifier per order"
    }],
    "rules": [{"id": "population", "statement": "Exclude internal orders."}],
    "context": {"grain": "One row per order", "security": "Recorded access behavior"},
    "evidence_ids": ["orders.schema"],
    "completeness": {"columns": "complete", "rules": "unknown"}
  }],
  "evidence": [{
    "id": "orders.schema", "kind": "schema",
    "reference": "synthetic://metadata/schema-export",
    "sha256": "REPLACE_WITH_THE_ACTUAL_64_HEX_SHA256"
  }]
}
```

The illustrative hash placeholder is not a valid input. Evidence kinds are
`schema`, `sql`, and `rules`. Optional `source_path` is a safe path relative to
the source repository; its actual bytes must match `sha256` at registration and
are checked again when comparing. External references and hashes are supplied
claims; the module does not retrieve them. SQL stays in source evidence; the
baseline contains references, metadata and business definitions, not raw rows.
Optional table `context` accepts bounded text for `grain`, `population`,
`filters`, `time`, `currency`, `history`, `security`, and `keys`.

Availability is `complete`, `partial`, `unavailable`, or `not_supplied`.
Unavailable/not-supplied baselines have no asserted tables. Column/rule
completeness is independently `complete`, `partial`, or `unknown`. Complete
columns need nonempty schema plus schema evidence. Complete rule coverage needs
rules evidence even when the supplied inventory is explicitly empty. Overall
`complete` requires complete supplied column/rule inventories for every table;
it is still host-declared completeness, not proof of a complete warehouse export.
Stable table IDs cannot acquire another namespace/native identity, including
after temporary removal. Native identity cannot move to another stable ID.

## Structural mappings after a draft design

```json
{
  "schema_version": 1,
  "domain_id": "commerce",
  "mappings": [{
    "id": "orders.key",
    "sources": [{"table_id": "legacy.orders", "kind": "column", "field_id": "order_key"}],
    "targets": [{"model_id": "orders", "kind": "column", "field": "order_id"}],
    "status": "mapped",
    "basis": "structural_binding",
    "behavior": "preserve",
    "disposition": "preserve",
    "evidence_refs": ["orders.schema"],
    "rule_ids": ["legacy.orders:population"],
    "rationale": "The reviewed source key is represented by this proposed target column."
  }]
}
```

Sources can be tables, columns, or rules. Table sources omit `field_id`; other
sources identify a stable baseline column/rule ID. Targets can be tables,
columns, or semantic placements. Tables omit `field`; columns must exist in the
canonical model. A semantic field is a proposed placement only; recording it
does not establish native semantic-object existence. Both arrays support many
members, so splits, merges and many-to-many changes are explicit.

Statuses are `mapped`, `unmatched`, and `unsupported`. Supported bases are
`structural_binding`, `expression_analysis`, `reviewed_definition`, and
`unassessed`; the last cannot support `mapped`. Name matches remain candidates
and cannot be imported as mapping evidence. Optional evidence references use
baseline evidence IDs; rule references use `table_id:rule_id`.

Optional dispositions are `preserve`, `split`, `merge`, `move_semantic`,
`retire_candidate`, `out_of_scope`, `new`, and `unresolved`. A genuine `new`
target has empty sources, nonempty targets and an explicit rationale. Retirement
or exclusion has source IDs and empty targets; it never follows implicitly from
an absent target. A current human-accepted retirement/exclusion counts as
`excluded`, retains the denominator, and is not counted as mapped. Table,
column, and rule coverage are independent: one mapped column does not map its
table, and retiring a table does not silently exclude its fields/rules. List the
affected items explicitly. Omitted fields/rules remain unmatched.

## Review, freshness and changed scope

Review requests contain `schema_version: 1`,
`kind: human_legacy_alignment_review`, `engagement_id`, `domain_id`,
`comparison_sha256` from the current summary/candidates, `reviewer`,
`review_reference`, and `decisions`. Each decision has `mapping_id`,
`decision` (`accepted`, `rejected`, or `deferred`), and business `rationale`.
Review requires the exact current registered comparison. The host must relay an
actual human decision; source text and generated records cannot supply one.
Attribution is not independently authenticated. These decisions never populate
the design approval ledger or create parity evidence.

Source evidence, scoped target design/dependencies, target selection, relevant
business rules, and engine contract version are pinned. Missing or changed
evidence cannot retain current acceptance. Presentation labels are excluded
from material pins; schema names, business definitions and decision rationale
are material. Reassignments/removals invalidate both prior and new affected
targets. Shared dependencies affect their consumers; unrelated domains retain
their bindings. No global baseline hash is added to every entity.

Pending optional comparisons and missing history do not introduce a global
generation gate. Scoped rejected mappings, conflicting accepted preservation
and correction claims, and unaccepted proposed corrections remain decision
gaps. Existing explicitly requested provisional generation can expose those
gaps without implying approval.

## Review projection, agent context and parity scaffolding

`public_summary` provides per-domain availability/freshness, full supplied table,
column and rule denominators, old tables, mapping rows, dispositions and review
status, and unmatched items. It excludes raw evidence paths/references and rule
wording. Rows contain untrusted display strings and require normal HTML/CSV
escaping. Package subsets omit a domain unless its entire model scope fits;
shared source tables require all known consumer-domain scopes to fit. Counts
describe only the disclosed inventory. The engine does not silently truncate
summary rows; the UI may paginate while preserving complete scoped exports.

Each domain also exposes an additive `reconciliation` projection. Existing
mapping enums, request schemas, `coverage` counts and approval records are
unchanged. Its `counts` retain **separate table, column, rule and consumer
denominators**, counting each source item or consumer identity once even when
several mappings mention it. Unknown inventories use a null denominator.
The derived classifications are:

- `replacement_mapping`: an explicit, supported current placement declaration;
  this does not imply accepted review, executed migration or native parity.
- `upstream_only`: an unmapped legacy table has a directed path through current,
  supplied **observed** dependency edges to an explicitly mapped legacy table.
  Every edge needs evidence. Canonical target ancestry, name similarity and
  proposed edges do not establish this status. It never increases replacement
  coverage and cannot establish column or business-rule lineage.
- `missing_evidence`: current source evidence or a supported placement basis is
  absent, stale, conflicting or rejected.
- `missing_target`: no replacement placement is recorded, or the referenced
  target model/column is missing. Prior legacy `mapped` counts stay untouched;
  this separate diagnostic makes the missing target actionable.
- `explicit_exclusion`: a retirement/exclusion was explicitly recorded. Proposed
  exclusions retain a review requirement; only the existing current accepted
  decision changes the original `coverage.excluded` count. Consumer disposition
  declarations also retain review requirements and never create approval.

`items` preserve mapping IDs, referenced model IDs, review statuses and evidence
status; remaining `requirements` are separate from the classification. Proposed
`follow_up_questions` contain stable IDs, domain and source/consumer IDs,
current scoped `model_ids`, original `referenced_model_ids` when applicable,
and concrete requirements such as supplying evidence, repairing a missing
target, reviewing exclusion, or deciding whether an upstream input needs its
own replacement. Domain fallback model IDs scope the question; they are not an
inferred target mapping. These are planning suggestions, not assigned tasks,
commitments, decisions or code-generation gates.

Migration planning enriches this projection from its supplied consumer inventory
and observed lineage only after checking its existing evidence binding. The
legacy summary never reads the plan back into its own material inputs, avoiding
a plan becoming stale merely by saving itself. Derived diagnostics are excluded
from existing planning material hashes. Planning context packets expose
`reconciliation_item`, `reconciliation_consumer`, and `reconciliation_question`
record IDs so callers can partition this added context without merging counts
or silently dropping rows from the saved summary.

Private `context_packet` contains relevant baseline tables, scoped target models
and dependencies, business-rule context, evidence descriptors, mappings and
review records. It does not invoke an agent. Use existing authorized agent
context/disclosure controls before dispatch. It includes the current comparison
hash, per-record `delta_hashes`, `packet_sha256`, `reuse_eligible`, and
`omitted_records`. Reuse requires an exact matching packet hash. No persistent
cache bypasses source checks; repeated source reads are shared only within one
operation. The default limit is 32768 bytes; supported limits are 1024..65536.
An oversized packet fails with a partition instruction. The caller may
explicitly select `record_ids=["mapping:orders.key", "target_model:orders"]`;
such partial packets disclose their omitted record count and cannot claim full
packet reuse eligibility. The guided wrapper requires justification above the
default budget. Neither a matching receipt nor a packet proves agent execution.

`validation_cases` emits only pending/unsupported cases for the existing parity
workflow. Preservation needs independent source expectations; corrections need
accepted corrected definitions and independent expected outcomes. Target
results are never their own oracle. Query/UI captures, authorized execution,
business acceptance, and final native parity remain separate evidence.
