# Optional domain review companion

The domain page presents a domain's warehouse models, semantic topics, recorded legacy
coverage, decisions and open items. It is an optional companion to the established delivery
portal. The root `START_HERE.html` remains the entrypoint for delivery status, feedback,
complete selected evidence and next steps. A page, draft or version folder never establishes
business acceptance, native validation or deployment authority.

## Add it to the selected delivery

Add this optional field to the existing review manifest, using the actual domain identifier:

```json
"domain_review": {"domain": "orders"}
```

Run the existing `scripts/finalize_delivery.py` workflow described in
[review-surface.md](review-surface.md#finalize-the-selected-handoff). When documentation is
selected and the review contains models, the finalizer adds:

- Simple layout: `03_Design_Documents/Domain_Review.html`.
- Classic layout: `01_Model/Domain_Review.html`.

Keep the standard layout and root `START_HERE.html`. The companion receives the already
selected, audience-filtered review and file bytes; the finalizer retains its integrity,
disclosure and delivery checks. It does not read the original repositories. Omitted
implementation stays omitted, and unselected dictionary details are not embedded.
Binary artifacts remain in the canonical package rather than its text inspector.
Selected dbt, native SQL and Coalesce artifacts retain their original selected package paths
and format; the companion does not convert one implementation framework into another.

`domain` labels the presentation and shared interfaces; it does **not** filter package scope
or select an active domain. Use the existing scoped review and delivery selection for that.
Reuse available metadata. Missing optional coverage, ownership, bindings or validation stays
unassessed; do not invent it or require new discovery or full implementation to show the page.
Explicitly requested provisional candidates retain their existing status and controls.
Missing model/file disposition or dashboard coverage is unassessed, not evidence of a new
model, unchanged code or successful coverage. Counts must retain those unknowns.

This companion is one bounded offline page (20 MiB maximum). A larger selected delivery can
use the established partitioned portal without the companion; do not truncate selected code
or evidence to make it fit.

## What reviewers can inspect

| Tab | Content, limited to the selected review |
|---|---|
| Overview | Candidate banner, scope, stack, counts, repositories, reading order, dashboard coverage and remaining work. |
| Data model | Subject areas, upstream pipeline, gold relationships and semantic topic occurrences. Table and topic inspectors retain binding gaps. |
| Code & files | Selected text files, supplied placement instructions and unresolved placeholders. |
| Decisions | Recorded questions, options, assumptions and answered, assumed or open status. |
| Legacy coverage | Supplied legacy-to-target mappings and unresolved or out-of-domain items. |
| Data dictionary | Included column definitions; absence does not mean a model has no columns. |
| Validation | Supplemental static observations, recorded checks and unknowns. Use root Start Here for the full evidence and readiness record. |
| Open items | Supplied questions, unresolved semantic mappings and pending work, with recorded owners where available. |

The companion is a projection, not a replacement decision register. Keep corrections,
feedback, accepted definitions, effective access evidence and deployment decisions in the
existing canonical workflow. Rendering a query or relationship does not execute or validate it.

## Semantic bindings and unresolved context

Omni topology uses the existing `omni_topic_trees` resolver and explicit review bindings:

```json
"omni_warehouse_bindings": [
  {"view_id": "orders", "model_ids": ["gold.orders"]}
]
```

Use actual view and model IDs supported by the source evidence. A matching `table_name`,
schema, display name or spelling does not create a physical binding. Canonical topology
retains distinct occurrences of repeated views, local aliases, inherited definitions and
resolved join direction/cardinality. Unsupported or unresolved context remains a visible
gap; a drawn connection does not prove native access controls or numerical correctness.
Fields or effective inherited definitions not projected into the inspector must be checked
in the original permitted semantic files and canonical evidence, not treated as unrestricted.

In the finalizer, the companion consumes the selected canonical topology. For the standalone
internal projection command below, `--omni-context /private/path/context.json` supplies local
private model context to the same resolver. That input is not embedded or copied into the
page. Only use an authorized local input; do not register private context as a public artifact
to make a mapping appear complete. Missing context leaves gaps and does not authorize a
connection, new discovery pass or deployment.

## Internal draft and version tools

`scripts/domain_review_page.py` also provides an internal review workspace. These commands
do **not** replace `finalize_delivery.py` for a completed selected delivery, and their standalone
layout does not supply the finalizer's audience and selection contract.

1. Project an already scoped review and its registered artifacts into page data:

   ```sh
   python scripts/domain_review_page.py project --review review.json --artifacts <artifact-root> \
     --path-map '{"dbt/":"02_dbt/","omni/":"03_omni/model/"}' \
     --domain orders --no-key-inference --output page.json
   ```

   Adapt the explicit path map to the actual artifact paths. For native SQL or Coalesce,
   use a neutral mapping such as `{"warehouse/":"02_warehouse/"}` and retain the selected
   native format. This standalone mapping is unnecessary in the canonical companion, which
   keeps the finalizer's selected paths. Artifact bytes must match their registered SHA-256.
   Optional `--overlay`, `--changed` and `--known-models` inputs add supplied presentation,
   changed-file and base-project information; they are not approval evidence.

   Warehouse joins come from recorded relationships and supported declared dbt tests.
   The standalone tool also has an optional `_fk`/`_pk` name heuristic; keep
   `--no-key-inference` unless that convention is deliberately being reviewed as an inference.
   The finalizer disables this heuristic. It never establishes an Omni physical binding.

2. Package and verify a new draft in the working area:

   ```sh
   python scripts/domain_review_page.py package --data page.json --docs <docs-folder> --output <work>/draft-<timestamp>
   python scripts/domain_review_page.py verify <work>/draft-<timestamp>
   ```

   Its internal layout is `START_HERE.html`, `MANIFEST.csv`, `01_review/`, warehouse code
   under `02_dbt/` or `02_warehouse/`, semantic files under `03_omni/`, and `04_docs/`.
   Packaging runs disclosure checks; verification compares files to the manifest and checks
   the page. Use a fresh draft directory; never overwrite a reviewed version.

3. Have an independent reviewer inspect the exact draft against the original evidence and
   record a bounded result. The record identifies the draft manifest and the actual scope:

   ```json
   {"schema_version": 1, "kind": "domain_review_independent_review",
    "draft_manifest_sha256": "<sha256 of draft MANIFEST.csv>",
    "reviewer": "<reviewer reference>", "scope": "<actual reviewed scope>",
    "findings": []}
   ```

   Findings use `id`, `severity` (`blocker`, `wrong_numbers`, `minor`), `summary` and
   `disposition` (`fixed`, `accepted`, `deferred`, `open`). Accepted or deferred findings
   require a note. Record actual findings; an empty array is not a substitute for review.
   After a fix, package and review a new draft so the record names the corrected bytes.

4. Freeze the reviewed draft as the next internal version:

   ```sh
   python scripts/domain_review_page.py next-version <Domain>
   python scripts/domain_review_page.py promote --draft <work>/draft-<timestamp> --review independent-review.json --output <Domain>/v<N>
   ```

   Promotion refuses mismatched bytes, open findings, unresolved blockers, undocumented
   accepted/deferred findings or an existing/non-next version. It retains the draft files,
   adds `04_docs/INDEPENDENT_REVIEW.json` and writes a new manifest. This freezes an internal
   review version; it does not authenticate the reviewer, prove review completeness or grant
   design, release or deployment approval. Finalize the selected delivery through the standard
   workflow when requested.

## Page contract and checks

The offline template in `assets/domain-review/` embeds `kind: domain_review_page`,
`schema_version: 1`. Its validated data includes `meta`, `models`, `rels`, `areas`, `topics`,
`files`, `decisions`, `legacy`, `dashboards`, recorded `checks` and remaining/open items.
Counts are recomputed from that data; optional dashboard tile counts must be nonnegative
safe integers or null. Unknown counts are not zero coverage.

Topic `base` identifies an occurrence, while `base_view` and `base_model_ids` identify the
semantic view and explicit warehouse bindings. Topic `nodes` retain occurrence IDs, view IDs,
model IDs and binding status; `joins` retain direction/cardinality/status and `gaps` remain
visible. Do not reinterpret an occurrence ID as a warehouse-model ID.

`check_page` checks the embedded data, recomputed counts, offline Content Security Policy,
resource restrictions and template completion. The policy permits the bundled script by hash
and blocks inline event handlers. Browser tests exercise offline navigation, inspectors and
hostile text with Chromium; they do not establish warehouse or live Omni acceptance.
Static observations remain supplemental: unsupported syntax, missing context and native
checks not run must not become a pass. Preserve the existing package, disclosure,
native-validation and authorization checks.
