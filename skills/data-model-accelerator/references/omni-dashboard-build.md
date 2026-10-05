# Build and review a dashboard candidate

Select `full_dashboard` at intake. `omni_dashboard.py` turns the parsed source into a complete work list, then verifies a reviewed native mapping. It does not invent equivalent calculations or infer the native layout grammar from a Looker visualization type.

```sh
python scripts/omni_dashboard.py --source canonical-dashboard.json \
  --candidate-sha256 <hash-of-complete-omni-file-map> --model-id <shared-model-uuid> \
  --output new-private-mapping.json
python scripts/omni_dashboard.py --source canonical-dashboard.json \
  --mapping reviewed-mapping.json --output new-private-build.json
```

The first command creates manual work items for every data tile, text tile, filter, behavior facet and layout. The specialist fills native `queryPresentations`, `controls` and `containers` using the applicable [Documents v2 API](https://docs.omni.co/api/documents-v2/create-draft-and-patch-document). Preserve original source identifiers, filter intersections, sorting, row limits, calculations and text. Record unresolved translation explicitly. A subtraction formula is not interchangeable with a similarly named warehouse measure without an approved definition change.

Each mapped item has `status: mapped`, the `source_sha256` of its canonical source item, a `target_pointer` into `native_payload`, and `target_sha256` of that exact fragment. Every behavior facet has the same contract. JSON pointers use standard `~0` and `~1` escaping. Two source tiles cannot point to one target. The layout points to `/containers`. Manual entries require a reason and keep the build incomplete. A mapping review records `status: approved`, a review reference and `mapping_sha256`, calculated over the mapping with `review` omitted. This is a recorded decision, not authenticated deployment authorization.

For query tiles, use the native `query` type and topic. Server-owned workbook/model anchors do not belong in the query body. Text tiles use a reviewed `blank` presentation with its supported visualization configuration. Control and container grammar is validated by the native server; the local checker only establishes the bounded structure, source accounting and exact reviewed fragments. The tests' synthetic layouts are not deployable native examples. Do not copy them as production templates.

The current bounded writer accepts at most 48 native query presentations, explicit full tile/control order, query and blank tile types, and no null/deletion entries. Other tile types, active HTML, embedded/external resources and unresolved source constructs use the manual route. Original source text is preserved privately; it is never executed or automatically fetched. A sensitive-data scan must clear before a build or mapping is exported.

`complete` means all source items and facets are accounted for in the reviewed build specification. It does **not** mean native validation, independent source completeness, LookML dependency resolution, dashboard creation, visual fidelity or business acceptance. Those remain separate evidence lanes. A source coverage declaration cannot authenticate itself. Modified source, model hash, mapping or native fragments require regeneration and review.

For live development, use [the native draft adapter](omni-dashboard-native.md) with an isolated existing destination and explicit authorization. It preserves published content, refuses foreign drafts and reads back the complete result. Net-new document creation publishes immediately; automated creation/publication and the **Beta** import route are not qualified by this adapter. Follow the [official migration guidance](https://docs.omni.co/guides/migrations/looker-to-omni-skill) as product context, but never adopt its example's delete-by-name behavior as a recovery strategy.
