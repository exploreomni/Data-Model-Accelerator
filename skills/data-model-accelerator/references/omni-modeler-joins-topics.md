# Relationships and topics

Curate topics for a business audience and base population. Reuse shared definitions while preserving reviewed topic overrides. Resolve global versus topic-local joins, aliases, roles and competing paths explicitly. Keep unsupported selectors and alias forms visible rather than removing them.

`assumed_many_to_one` is inferred, not data evidence. Test duplicate keys, orphan preservation, multiple child branches, role-playing dimensions, temporal lookup and bridges. Symmetric aggregation depends on correct keys and relationships. Do not force two facts into a wide table or promise fanout safety because YAML validates.

The v2 checker covers explicit join paths, single-parent topic/view inheritance and isolated topic `views` overrides (including role aliases through `extends`). It resolves exact, all-view, per-view and tag selectors in documented specificity order. Explicitly excluded dependencies fail for `fields`; `ai_fields` controls awareness and is not access enforcement. Defaults and expanded selections appear in `topic_scopes`. Multiple inheritance, implicit join choice, relationship alias syntax outside scoped views, composite topics and advanced composition remain unqualified. No local graph check proves declared cardinality. A diagram rendering limit is not a hard model correctness limit.

Grammar checked 2026-10-05: [topic views](https://docs.omni.co/modeling/topics/parameters/views), [topic inheritance](https://docs.omni.co/modeling/topics/parameters/extends), [selectors](https://docs.omni.co/modeling/topics/parameters/fields), [measure filters](https://docs.omni.co/modeling/measures/parameters/filters), [fiscal offset](https://docs.omni.co/modeling/models/fiscal-month-offset). These documented capabilities are not live qualification of this implementation.

## Topic population

Apply these rules to every Omni candidate, whatever the source platform.

1. Design topics from business entities and use cases, not one per source explore, report, workbook or dashboard.
2. **One topic per base view and population.** A population is the base view plus its always-where filters (`always_where_filters`, `always_where_sql`). Default filters, access grants and field lists are removable choices; they never make a second population. When several source assets share a base view, merge them into one topic and express their filter differences as removable `default_filters`.
3. A second topic on the same base view is allowed only for a deliberately different population. Build it with `extends` from the main topic and state the difference in **both** topics' `ai_context`, each naming the other.
4. Never copy a source population rule (always-where filter) without confirmation. Record each one as a confirmed decision or an open question. Never turn a main-topic default filter into a variant's always-where filter silently.
5. Before finalising, report every topic sharing a base view with its justification.

`scripts/omni_topic_population.py` enforces this. `build_handoff(..., population_decisions=[...])` stores the result as `topic_population` in `SEMANTIC_REVIEW.json`; the portal blocks packaging while any finding is unresolved and renders a **Topics sharing a base view** table with the population questions in START_HERE.

| Code | Meaning |
| --- | --- |
| `population.multiple_main_topics` | Topics share a base view without extending one main topic |
| `population.variant_same_population` | A variant has the main topic's always-where population; merge it |
| `population.default_promoted_to_always_where` | A main-topic default became a fixed variant filter |
| `population.ai_context_missing_variant` / `_missing_main` | The two ai_contexts do not name each other |
| `population.always_where_unconfirmed` | A declared always-where rule has no decision or question |
| `population.extends_unresolved` | Missing, cyclic or multi-parent `extends` |

Resolve each finding by ID with `{finding_id, resolution: confirmed|open_question, reference, reason}`. `reference` is the actual human decision or question ID; `open_question` keeps the item visible on the questions page. A decision for a finding that no longer exists is rejected as stale. Extends resolution is a shallow per-parameter override; native inheritance and row counts still need native validation.

Sources: [topics](https://docs.omni.co/modeling/topics), [relationships](https://docs.omni.co/modeling/relationships), [role-playing joins](https://docs.omni.co/guides/modeling/join-to-same-table).
