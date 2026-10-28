# Optional domain evidence and customer standards

During intake, ask whether the team has a domain/table classification export and
existing naming, label, tag, description or sample-query requirements. Missing exports
are not prerequisites for designing or generating provisional code. Use scoped evidence
instead of asking every specialist to rediscover the same catalogue.

## Domain classification

`domain_classification.py` imports CSV or JSON metadata into a versioned evidence register.
Preserve exact table identities, source fingerprint, evidence references, confidence and
rationale; include required columns and explicitly shared domain dependencies. This is
proposed evidence, not a replacement for entity design or a command to reorganize accepted
domains. A source change marks the register stale. Review proposals alongside the existing
domain choices, then use the existing domain-selection workflow.

A JSON row uses `id`, exact `table_id`, `domain_id`, numeric `confidence` (0–1),
`rationale`, `required_columns`, `shared_domain_ids` and `evidence_refs`. The last
three are arrays. The document adds `schema_version: 1`, `kind: domain_classification`,
`version`, `source_reference`, `source_sha256` and `entries`. Use the engagement's
recorded source fingerprint, not a generated placeholder. CSV uses the row field
names as headers and JSON arrays in list-valued cells:

```sh
python scripts/domain_classification.py --csv domain-metadata.csv \
  --source-reference reviewed-catalogue --source-sha256 SOURCE_FINGERPRINT \
  --version 1 --output new-classification.json
```

Register with `guided_workflow.py register-domain-classification --run RUN --document FILE`.
Use `domain-classification-packet --document FILE` with `{"domain_id":"sales"}` to prepare
only sales evidence and explicitly shared dependencies. The packet is saved in engagement
state. Add it as `domain_classification` in the specialist context request and pin its
`sha256` under `bindings.domain_classification`. It never selects a domain or completes it.
Its `scope_ids` come from the selected domain, its recorded design entities and explicit
shared dependencies. The specialist brief must stay inside that scope; imported rows
cannot expand it. Predesign briefs can use the domain ID before entities exist.

## Versioned presentation standards

Physical names continue to use `configure-naming` and its accepted custom-convention
decisions. This optional companion governs presentation requirements and cannot rename
source tables, dbt models or Omni objects.

```json
{
  "schema_version": 1,
  "version": "1",
  "request_reference": "user-confirmed-style-requirements",
  "rules": [{
    "id": "sales-presentation",
    "entity_ids": [],
    "domains": ["sales"],
    "label_style": "title_words",
    "required_tags": ["sales"],
    "description_required": true,
    "sample_queries_min": 1
  }]
}
```

`label_style` is `preserve`, `title_words` or `sentence_words`. Scope each rule by exact
entity IDs or domain identifiers/names, using the recorded design spelling. Conflicting
rules remain a question. A new version is required after changing the configuration.
The selected naming policy is pinned; changes to it make the companion visibly stale.

Use `configure-standards --run RUN --document FILE`, then `preview-standards` with a
metadata document of this shape:

```json
{"schema_version":1,"resources":[{"id":"orders","name":"fct_orders","domain":"sales",
"label":"Orders","tags":[],"description":null,"sample_query_count":0}]}
```

The preview shows proposed labels and missing tags, descriptions and sample queries.
It applies no changes. Counts are supplied metadata, not proof queries work; native file
conformance and query qualification remain separate. Register only the selected domain's
resources. Unchanged resource/rule fingerprints are reusable; affected scopes need review.
The guided page shows the preview within validation, scoped to disclosed models.

`standards-packet --run RUN --entities orders` prepares scoped context. Include it as
`modeling_standards` and pin `bindings.modeling_standards` in the specialist request.
Relevant standards participate in scoped design/task fingerprints. Existing engagements
without either optional feature retain their previous contracts and behavior.
The register retains the configuration version; specialist packets bind only the selected
rules and naming policy, so an unrelated domain revision does not invalidate their work.
Changing a canonical model name makes its previous label preview stale.
