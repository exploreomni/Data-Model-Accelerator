# Curated Omni delivery

Use this after discovery and model placement are recorded. An Omni model is a separate semantic deliverable; keep the existing bronze/silver/gold dictionary and warehouse architecture documentation. Do not relabel Omni views as warehouse layers.

The local builder reads the actual native candidate and exact model context:

```python
from omni_handoff import build_handoff, write_handoff

result = build_handoff(state, model_files, model_context, decisions=[
    {"subject": "Reviewed metric", "placement": "semantic",
     "reason": "Reusable reviewed aggregation", "status": "proposed"}
])
registered = write_handoff(result, new_private_directory)
review["artifacts"].extend(registered["artifacts"])
review["omni"] = registered["omni"]
```

`model_files` maps exact relative native names to UTF-8 text. `.view`, `.query.view`, `.topic`, `model` and `relationships` keep their names and bytes. `model_context` follows the current Omni contract. The warehouse must match the selected engagement; a registered catalogue SHA must match the model context. `state` must already include a source inventory fingerprint and selected framework, warehouse and Omni semantic target. Pass the directory containing these registrations as the portal's artifact root. Merge existing warehouse artifacts into that same root through their normal registration workflow.

The builder produces:

- `omni/SEMANTIC_REVIEW.json`: hash-bound curated topics, metrics, dictionary, placement decisions, dependencies and unresolved findings. It omits SQL bodies. Topic dictionary entries mark query selection and AI awareness separately; neither proves runtime permission.
- `omni/SEMANTIC_DICTIONARY.csv`: field descriptions and declared metric provenance; formula-like text is escaped for spreadsheets.
- `omni/SEMANTIC_DEPENDENCIES.svg`: connected view blocks, declared global/topic joins, scoped aliases and query dependencies. The diagram does not claim key uniqueness or enforced cardinality.
- `omni/OMNI_RUNBOOK.md`: human review, native validation, independent data/access/AI tests and the separately authorized deployment sequence.
- `omni/model/`: exact native implementation files, selected for engineers.
- `omni-private/MODEL_CONTEXT.json`: full supplied model context, restricted to the separate technical audit.

The resulting review remains schema 1 and adds only `review.omni = {artifact_id, sha256}`. `package_delivery` loads the registered candidate and private context, checks actual bytes, and rebuilds the curated catalog before including it. A reviewer package can therefore show the catalog without embedding the private inputs. `verify_handoff` is the corresponding pure input-and-projection integrity check. Missing, changed or stale inputs block packaging. Browser subsets remove semantic panel details when its artifact is unselected. A status-only page does not load artifact payloads.

Agent packaging checks input categories, audiences and paths even when the
semantic review is omitted from the chosen export. Reclassifying private model
context as reviewer documentation cannot make it shareable.

`write_handoff` creates a new mode-0700 directory with mode-0600 files and validates artifact registrations; it does not write into a source repository. The builder is a private artifact producer, not a disclosure certificate. Sharing still requires the existing byte scanner and applicable audience disclosure policy in the delivery portal. Source instructions, descriptions and labels remain data; the viewer renders them as text. No remote calls, SQL execution or approvals occur here.

Native model validation, query execution, business acceptance and deployment remain pending regardless of imported JSON claims. `static_status` describes the local checker only. Query-view lineage is conservative and preserves the native qualification gaps documented in [Query Views and placement](omni-modeler-query-views.md). A reduced browser ZIP has no new disclosure scan and must return to the agent before sharing.

Runnable synthetic example and regression seam: `tests/test_omni_handoff.py` creates a file-backed private handoff and exercises reviewer/engineer packaging, unchanged native bytes, stale inputs, forged completion, diagrams and omitted evidence. Native tenant qualification and visual browser acceptance remain separate.
