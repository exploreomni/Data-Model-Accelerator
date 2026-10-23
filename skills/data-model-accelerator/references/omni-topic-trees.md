# Native Omni topic trees

`scripts/omni_topic_trees.py` extracts a deterministic, versioned join-tree
contract from the exact Omni candidate and its model context. `build_handoff`
stores it in `SEMANTIC_REVIEW.json` as `topic_trees`. It contains no SQL bodies,
filter values or credentials. Native validation and acceptance remain pending.

```python
from omni_topic_trees import build_topic_trees, bind_topic_trees, topic_tree_coverage

raw = build_topic_trees(model_files, model_context)
bound = bind_topic_trees(
    raw,
    review.get('omni_warehouse_bindings', []),
    review['models'],
    domain_map={'topics': {'sales': 'Commerce'},
                'source_folders': {'customer_success': 'Customer Success'}},
    expected_pins={
        'model_candidate_sha256': selected_semantic_review['pins']['model_candidate_sha256'],
        'model_context_sha256': selected_semantic_review['pins']['model_context_sha256'],
    },
)
coverage = topic_tree_coverage(bound)
```

The contract has `schema_version: 1`, `kind: omni_topic_trees`, and
`version: omni-topic-trees-v1`. `expected_topic_ids` comes from candidate file
identities independently of successful extraction. `topics` retains unsupported
and unresolved identities. The coverage check compares those sets, occurrence
IDs, parent paths, edge references and root shape; it does not approve a model.

Each topic has `id`, `name`, `source_path`, `domain`, `domain_source`, `base_view`,
`joins_state`, `nodes`, `edges`, `diagnostics`, `analysis_diagnostics`,
`binding_diagnostics`, `model_ids`, and separate `structural_status`,
`binding_status` and `native_status`. Structural values are `complete`,
`unresolved` or `unsupported`; binding values are `complete` or `gap`; native
status remains `pending`. Analyzer findings are preserved separately from
topology findings. Missing physical warehouse coverage is a delivery gap, not a
claim that the native Omni topic is invalid.

Nodes identify occurrences, not deduplicated physical tables. Their `id` is a
hash of topic ID and full `path`; `view_id` preserves the Omni alias. The node
also holds `parent_id`, `kind`, `binding_origin`, `binding_candidates`,
`physical_view_ids`, `dependencies_complete`, `bound_view_ids`, and `model_ids`.
Query-view dependencies are collected from the existing semantic analyzer's
projected and population lineage, including multiple physical source views.

Edges contain `from` and `to` occurrence IDs, `from_view`, `to_view`, `path`, a
hashed `relationship_id`, `relationship_direction`,
`declared_relationship_type`, effective `relationship_type`, `join_type` and
`relationship_status`. The relationship SQL is never copied. Reverse traversal
uses documented reversibility, not a blanket undirected graph. Cardinality is
flipped for reverse traversal while declared cardinality and join type remain
visible. This is structural interpretation, not an execution result.

Warehouse model IDs come only from the review's explicit
`omni_warehouse_bindings` records (`view_id`, `model_ids`). Similar names never
establish a mapping. A topic-local binding can use `topic_id/view_id`; inherited
physical bindings apply only while the actual source remains unchanged. A local
override that changes the shared view's physical source requires a scoped
binding. Missing, duplicated, out-of-review and non-gold bindings stay visible.
Non-gold IDs are retained with a coverage gap. Binding does not alter structural
status or grant native verification.

Domain precedence is explicit topic map, longest configured source-folder
prefix, unambiguous bound base-model domain, then `Unassigned`. Source folder
names and topic labels are not interpreted as domains without configuration.

The supported subset reuses the existing exact-candidate YAML and semantic
analyzer: single-parent view/topic `extends`, topic-local views and relationships,
and explicit nested join mappings (including null leaves). Omitted `joins` is
kept distinct from `joins: {}` and requires native graph qualification. Composite
and delta join forms are retained as unsupported diagnostics. No implicit graph
expansion, remote model loading, raw-SQL execution or full-platform parser is
introduced. Legacy pinned semantic reviews without `topic_trees` remain
verifiable but require regeneration before native join paths can be shown.

Primary contracts:

- [Topic joins](https://docs.omni.co/modeling/topics/parameters/joins)
- [View extends](https://docs.omni.co/modeling/views/parameters/extends)
- [Relationship reversibility](https://docs.omni.co/modeling/relationships/parameters/reversible)

Focused regression: `tests/test_omni_topic_trees.py`. A runnable synthetic input
is in `examples/omni-topic-trees/`.
