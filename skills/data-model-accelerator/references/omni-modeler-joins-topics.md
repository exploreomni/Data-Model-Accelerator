# Relationships and topics

Curate topics for a business audience and base population. Reuse shared definitions while preserving reviewed topic overrides. Resolve global versus topic-local joins, aliases, roles and competing paths explicitly. Keep unsupported selectors and alias forms visible rather than removing them.

`assumed_many_to_one` is inferred, not data evidence. Test duplicate keys, orphan preservation, multiple child branches, role-playing dimensions, temporal lookup and bridges. Symmetric aggregation depends on correct keys and relationships. Do not force two facts into a wide table or promise fanout safety because YAML validates.

The v2 checker covers explicit join paths, single-parent topic/view inheritance and isolated topic `views` overrides (including role aliases through `extends`). It resolves exact, all-view, per-view and tag selectors in documented specificity order. Explicitly excluded dependencies fail for `fields`; `ai_fields` controls awareness and is not access enforcement. Defaults and expanded selections appear in `topic_scopes`. Multiple inheritance, implicit join choice, relationship alias syntax outside scoped views, composite topics and advanced composition remain unqualified. No local graph check proves declared cardinality. A diagram rendering limit is not a hard model correctness limit.

Grammar checked 2026-10-05: [topic views](https://docs.omni.co/modeling/topics/parameters/views), [topic inheritance](https://docs.omni.co/modeling/topics/parameters/extends), [selectors](https://docs.omni.co/modeling/topics/parameters/fields), [measure filters](https://docs.omni.co/modeling/measures/parameters/filters), [fiscal offset](https://docs.omni.co/modeling/models/fiscal-month-offset). These documented capabilities are not live qualification of this implementation.

Sources: [topics](https://docs.omni.co/modeling/topics), [relationships](https://docs.omni.co/modeling/relationships), [role-playing joins](https://docs.omni.co/guides/modeling/join-to-same-table).
