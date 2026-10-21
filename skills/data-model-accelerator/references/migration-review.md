# Business rules and dashboard migration review

Use this workflow for selected migration domains. It extends the saved engagement;
it does not repeat answered questions or change design approval, provisional
generation, native execution or deployment authority.

## Operator sequence

1. Confirm the installed skill path/version. For Periscope/CDT, run actual discovery
   and extraction, retaining its report and contracts.
2. Accept business rules from conversation, Markdown or a supplied rule pack.
   Preserve original wording and its source. Ask one short round about the most
   consequential missing definitions, using existing answers first.
3. Review all selected dashboards together. Propose shared facts/dimensions and
   aggregates before authoring the target design. Keep every consumer mapped.
4. Review the design and rules independently. Generate approved candidates or
   explicitly requested provisional code under the existing stage workflow.
5. Freeze independent source expectations, collect equivalent target results,
   and publish a row-free source → warehouse → Omni comparison in the same page.
6. Finalize through the existing finalizer. Read the Migration review page and
   `01_Model/migration-review.md` alongside the ERD, code and dictionary.

The coordinator runs helpers and records actual output; describing a helper or
emitting a task plan is not execution. The agent prepares structured records from
the interview so SMEs can respond in ordinary language.

## Business rules before implementation

Offer [the intake template](../assets/business-rules-template.md), or ask the same
questions in conversation. Capture definitions/formulas, grain, population and
exclusions, time, currency, history, security, null treatment, examples, ownership
and effective dates. Unknown is a valid answer. Source behavior and an intended
correction are separate rules.

```sh
python scripts/business_rules.py --text-file rules.md --rule-id revenue.definition \
  --domain billing --source-reference interview-1 --output proposed-rules.json
python scripts/guided_workflow.py record-business-rules --run /absolute/run \
  --document /absolute/proposed-rules.json
```

The first command preserves one passage verbatim as a **proposed** rule. For
multiple definitions, the coordinator creates separate scoped records with each
original statement. The version-1 pack is `{schema_version: 1, rules: [...]}`.
Each rule contains `id`, `name`, `statement`, `scope` (`domains`, `model_ids`,
`asset_ids`), `definition`, `examples`, and `source` (`reference`, SHA-256 of the
original statement). Optional `owner`, `effective_from`, and `conflict_key` retain
provenance and shared definition identity. Definitions use the intake dimensions.
Examples have `id`, `scenario`, `expected` text; they are expectations, not test
evidence. Imported packs cannot carry accepted status.

When the user decides, the coordinator records `review-business-rules` with a
version-1 `human_business_rule_review`: exact engagement ID, current pack hash,
reviewer, attributable review reference, and `{rule_id, decision, rationale}`
entries. Decisions are `accepted`, `rejected`, or `deferred`. This is explicitly
host-reported review, not authenticated identity or design approval. Changed rules
lose old acceptance. Unbound rules remain visible. Contradictory accepted rules
sharing a `conflict_key` require resolution for affected normal generation;
requested provisional generation remains available with that conflict exposed.

Task plans attach only relevant `business_rule_context`. Keep its original wording,
status, examples and hashes in the selected specialist's bounded disclosure-checked
packet. The engineer traces rules to transformations/tests; the Omni Modeler traces
them to fields/topics and AI context; the analyst uses independent expectations.
Do not call a rule implemented or validated merely because it appears in a packet.
Verify generated files and record real evidence. Rule edits invalidate affected
entity/dependency bindings, not unrelated work.

## Periscope discovery that actually extracts

```sh
python scripts/guided_workflow.py extract-periscope --run /absolute/run \
  --document /absolute/periscope-request.json
```

A minimal request is `{ "schema_version": 1 }`. Optional `source_profiles`, such
as `["periscope:analytics/cdt"]`, select a known snapshot when detection lacks
markers; this does not make unsupported formats valid. Optional `source_identity`
supplies a stable `repository_id` and `space_ids` by project root.
`verified_connection_dialects` retains attributable connection/dialect evidence.
Read [the supported Periscope contract](source-adapters/periscope.md).

The report records installed component/repository identity, input snapshot,
selected profiles, actual contract paths, coverage and unresolved bindings. Views-
only, snippets-only and mixed repositories are supported with corroborated markers.
Unchanged extraction reuses checked contract bytes; altered source or runtime needs
new extraction. Generic SQL is not automatically Periscope. Private output lives
under the engagement, never inside the source checkout.

Keep parsed, partial, unsupported, excluded and unreadable counts visible. Unknown
subtree counts make the total repository denominator unknown. File enumeration does
not establish a complete Space export. Bracket tokens, Python/R, encrypted settings,
missing filters and effective permissions retain their uncertainty. The reader
never runs source code or expands ambiguous snippets.

## Shared models across the portfolio

Before one-dashboard-at-a-time authoring, build a source-linked portfolio contract
from the extracted inventory, supplied rules and catalogue. Run:

```sh
python scripts/guided_workflow.py recommend-shared-models --run /absolute/run \
  --document /absolute/dashboard-contracts.json
```

Version 1 contains `assets`, each with `id`, `name`, `domain`, linked `model_ids`,
`evidence_refs` and a `contract`. Contracts declare `base_entity`, `grain`,
`dimensions`, `population`, `filters`, `time`, `currency`, `history`, `security`,
`rule_ids`, and `measures` (`id`, `expression`, `aggregation`, `additivity`). Include
`existing_models` with the same contracts and evidence to test reuse first.
No helper infers business meaning from arbitrary SQL: the specialist must cite
original expressions and mark unresolved dimensions `unknown`.

The deterministic pass proposes reuse, shared aggregates, shared detailed models,
separation, or a decision. Exact declared context must match. Additive sums/counts
can propose aggregation; distincts, ratios, windows and semi-additive measures stay
at detail/query time. Different projections retain required dimensions for drilldown
review. Conflicting same-ID measures cannot merge. Every asset retains a disposition,
including unknowns. Reconcile proposals into the canonical design through normal
review; no recommendation creates code or approves a model. Validate grain, fanout,
filters, drilldown, access and parity for every consumer. Performance savings require
an actual benchmark, not a deduplicated model count.

## Register private comparison evidence

Use [migration-parity.md](migration-parity.md) for preparation, exports, freezing,
bounded collection and evaluation. Connect it using `record-migration-validation
--run /absolute/run --document /absolute/references.json`. Its version-1 request
contains `workflow`, optional `baseline`, `warehouse`, and `omni` references. Each
reference has an absolute `path`, byte count and SHA-256. Before freezing the plan,
run `migration-bindings --run /absolute/run --entities model-id --json` and use the
saved `workflow.migration_validation_bindings` in the comparison plan. Registration
recomputes these six bindings from current inputs, selected design/rules and
registered candidate file bytes. Caller-supplied `current_bindings` cannot override
them. These are local comparison identities; the separate release workflow retains
its own policy and destination bindings. The helper recomputes the scorecard from
private inputs; it rejects imported pass reports.

Changed source, catalogue, rules, design or registered code makes the old comparison
stale. Missing/changed private evidence cannot retain a pass. Public output contains
scoped mappings, counts and issue codes, never result rows or query text. Restricted
model packages omit unselected rules/assets and repository-wide counts. Audit/code-
only exports omit design material. Local agreement is distinct from native execution,
security/interaction testing and business acceptance. It never grants deployment
authority.
