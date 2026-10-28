# Relationships and topics

Curate topics for a business audience and base population. Reuse shared definitions while preserving reviewed topic overrides. Resolve global versus topic-local joins, aliases, roles and competing paths explicitly. Keep unsupported selectors and alias forms visible rather than removing them.

`assumed_many_to_one` is inferred, not data evidence. Test duplicate keys, orphan preservation, multiple child branches, role-playing dimensions, temporal lookup and bridges. Symmetric aggregation depends on correct keys and relationships. Do not force two facts into a wide table or promise fanout safety because YAML validates.

The v2 checker covers explicit join paths, single-parent topic/view inheritance and isolated topic `views` overrides (including role aliases through `extends`). It resolves exact, all-view, per-view and tag selectors in documented specificity order. Explicitly excluded dependencies fail for `fields`; `ai_fields` controls awareness and is not access enforcement. Defaults and expanded selections appear in `topic_scopes`. Multiple inheritance, implicit join choice, relationship alias syntax outside scoped views, composite topics and advanced composition remain unqualified. No local graph check proves declared cardinality. A diagram rendering limit is not a hard model correctness limit.

Grammar checked 2026-10-05: [topic views](https://docs.omni.co/modeling/topics/parameters/views), [topic inheritance](https://docs.omni.co/modeling/topics/parameters/extends), [selectors](https://docs.omni.co/modeling/topics/parameters/fields), [measure filters](https://docs.omni.co/modeling/measures/parameters/filters), [fiscal offset](https://docs.omni.co/modeling/models/fiscal-month-offset). These documented capabilities are not live qualification of this implementation.

## Topic population

Apply these rules to every Omni candidate, whatever the source platform.

1. Design topics around business entities and analytical needs. Do not automatically create one per dashboard or force one per base table.
2. Compare fixed population, access filters, grants, joins, field and measure scope, and audience before recommending consolidation. Access rules are security controls, not removable presentation defaults. Distinct topics may be justified even when they share a base view and fixed population.
3. Use supported inheritance to reuse definitions where appropriate. Preserve topic-specific overrides and explain their purpose. Never automatically merge or widen permissions.
4. Preserve source fixed filters provisionally, with confirmation or an open question. Distinguish required editable filters, conditional requirements and removable defaults using the [Looker behavior mapping](looker-omni-contract.md#relationships-topics-and-user-attributes).
5. Report shared-base topics, compatibility differences, reuse suggestions and unresolved questions without blocking candidate code or review packaging.

`scripts/omni_topic_population.py` produces advisory evidence. `build_handoff(..., population_decisions=[...])` stores it in `SEMANTIC_REVIEW.json`; START_HERE renders **Topics sharing a base view**. This report cannot authorize deployment or replace native security/business acceptance.

Resolve a finding with `{finding_id, resolution: confirmed|open_question, reference, reason}`. IDs bind the relevant effective definitions and inheritance, including operators and values through fingerprints; values are not included in the report. A changed rule invalidates its old decision and keeps it visible for review. Unchanged independent decisions remain reusable. Missing/cyclic/unsupported inheritance stays unresolved. Local inheritance analysis is bounded and does not prove native semantics.

Sources: [topics](https://docs.omni.co/modeling/topics), [access filters](https://docs.omni.co/modeling/topics/parameters/access-filters), [required access grants](https://docs.omni.co/modeling/topics/parameters/required-access-grants), [relationships](https://docs.omni.co/modeling/relationships), [role-playing joins](https://docs.omni.co/guides/modeling/join-to-same-table).
