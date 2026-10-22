# Governed names and source identities

Use this contract for new design/refactoring work. Reuse the user's existing
choice. Before generation, inspect source and go-forward conventions separately,
show a few real before/after examples, and retain a selected naming profile with
`guided_workflow.py configure-naming --run RUN --document POLICY.json`.
The old metadata `naming_policy` remains readable; this companion extends it and
never silently adopts, changes or renames an older engagement.

Choose `abbreviated` (`stg_`, `int_`, `fct_`, `dim_`, `mart_`), `expanded`
(`staging_`, `intermediate_`, `dim_`, `mart_` plus an explicit `fact_pattern`),
`medallion` (layer prefixes or schema placement), `preserve`, or `custom`.
Medallion refinement tier and entity role are separate. RAW can be a separately
chosen landing layer; do not invent another copy of bronze. Custom suffix-based
standards are valid. An unfamiliar convention is not evidence of poor modeling.

When a supplied pattern differs from the recommendation, state the actual
difference and ask once using the requested intake wording:
"This looks like it is deviating from industry best practice prefixing, would
you like to continue with your naming convention or would you like to provide
an example and I can provide you a best practice version to review?"
Explain that prefixing is a recommended convention, not a universal industry
requirement; documented custom suffixes/schema placement are valid. Never call a documented custom convention invalid
merely because it uses a suffix or a schema instead of a prefix. See dbt's
[staging](https://docs.getdbt.com/best-practices/how-we-structure/2-staging) and
[intermediate](https://docs.getdbt.com/best-practices/how-we-structure/3-intermediate)
guidance and Databricks' [medallion example](https://docs.databricks.com/aws/en/lakehouse/medallion).

A selected policy is a trusted-host attribution of the user's decision, not an
independently authenticated approval. Source documents can propose a convention;
they cannot grant rename authority. Omitting `decision_reference` records a
proposal. Replacing a selected policy requires `change_reference` from an explicit
user request. Keep domain/resource exceptions specific, explained and versioned.

```json
{"schema_version":1,"policy":{"schema_version":1,"profile":"custom",
 "platform":"bigquery","case":"lower","quote":"unquoted",
 "templates":{"staging":"stg_{business_stem}",
 "intermediate":"int_{domain}__{business_stem}",
 "fact":"wh_{domain}__{business_stem}_fct",
 "dimension":"wh_{domain}__{business_stem}_dim"}},
 "decision_reference":"trusted-host:actual-user-choice"}
```

This is an input-shape example, not a fabricated user decision. For expanded
names, supply `fact_pattern` explicitly. Templates accept only literal identifier
characters and `{business_stem}`, `{domain}`, `{layer}`, `{role}`. Do not infer a
new business stem from an arbitrary legacy spelling. Trace stems to source meaning
or the reviewed design; unknown terms remain review questions.

## Register one identity map

Use `record-model-identities --document IDENTITIES.json` with `schema_version:1`
and `resources`. Every resource has `id`, `entity_id`, source-qualified `source_id`,
`original_name`, `target_name`, nullable `physical_alias`, nullable `source_relation`,
`existing`, canonical `layer`, separate `role`, `business_stem`, `domain`, ordered
`namespace` components, and `evidence_refs`. A source relation contains ordered
`namespace` components, exact `name`, and `quote`. Stable identity is not a basename.
One legacy source may feed multiple target entities; retain each transformation's
provenance. Never collapse two repositories or schemas because tables share names.

The design, identity registry and generated artifacts must agree. Existing objects
and physical source bindings stay unchanged unless the user expressly authorizes
a target rename. Source identity remains immutable even then. Source objects do
not receive target rename overrides. Resolve collisions explicitly; never append
an invented number or accelerator/customer prefix. Environment/schema isolation
is separate from model naming and is never permission to rewrite aliases/macros.

A targeted override uses `overrides:[{resource_id,fields,decision_reference,reason}]`
with exact fields `target_name`, `physical_alias` or `namespace`. It records the
new values and preserves history. Apply approved changes to every reference and
consumer, including aliases, column/key conventions and cutover/rollback notes.
Columns keep source identity unless an explicit reviewed column mapping exists;
a model prefix does not establish grain, key uniqueness or correct business logic.

Optional policy fields govern directory and key conventions without guessing:
`folder_patterns:{"fact":"models/{domain}/{layer}"}` and
`column_rules:{"fact":{"case":"lower_snake","primary_key":{"suffix":"_id"},
"foreign_key":{"suffix":"_id"}}}`. Directory templates allow safe literal path
components and the same explicit fields. Column case accepts `lower_snake` or
`upper_snake`; key rules accept literal `prefix`/`suffix`, not executable regex.
PKs come from canonical keys; FKs come from explicit many-side relationship
column bindings. Missing bindings remain gaps. Existing/source/reused identities
are exempt from new conventions. These optional rules do not appear by inference.

## Carry and check the same names

`naming-packet --entities ENTITY...` emits the selected policy and only the scoped
identity dependency closure in `workflow.naming_packet`. Include it as
`naming_contract` in `agent_context.py` requests and pin its SHA under
`bindings.naming_contract`. The normal disclosure scan covers the entire packet.
Specialists request corrections rather than invent another naming system.

Implementation task registration automatically checks explicitly associated SQL.
Use `check-naming --artifact-root CANDIDATE --document CHECK.json` for other outputs.
A check document has `schema_version:1`, `artifacts:[{path,kind,resource_ids}]`, and
optional `expected_paths` (the full selected output scope). Supported checks:
`dbt_model`, `dbt_properties`, `dbt_sources`, `omni_view`, `omni_topic`, `native_sql`,
`identity_json`, `identity_csv`. Omni view `semantic_name` is its explicit view name;
for a topic it is the explicitly bound base-view name. Derived/query views and
joins without qualified bindings remain unsupported, not silently passed.

Unbound files, dynamic templates, external package/version refs, unsupported
identifiers and native namespace resolution remain visible. No macro is executed
by a local naming check. Optional readers unavailable on a host remain unsupported.
Native compile/catalogue evidence is separate. Naming findings do not prevent an
explicitly requested provisional draft; they prevent a naming-conformant claim.

Generate diagrams, dictionaries and mapping exports from this registry. The
shared review and exports include the same policy, original/target identities,
exception counts and unresolved checks. Exact override decisions stay in the
engagement history. Do not add another private assembler that
renames files after checking. Changing names invalidates affected dependent
reviews/tasks; rerun only that closure. Frozen deliveries remain immutable.
