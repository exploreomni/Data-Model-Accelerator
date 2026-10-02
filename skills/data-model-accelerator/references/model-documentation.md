# Required model documentation

For new warehouse metadata deliveries, use the [version-2 metadata contract and workflow](warehouse-metadata.md). The documentation checker accepts legacy version 1 and version 2 independently of the version-1 model inventory. Migrate a copy; historical receipts do not become metadata deployment evidence. Native persistence and independent physical coverage require the separate metadata gate.

Every model delivery includes an ERD, a complete data dictionary and documentation for bronze, silver and gold. These are maintained deliverables, not optional appendices or a substitute for generated code. Cover existing/reused objects as well as proposed ones within the selected source-to-gold scope. A stage implemented by an existing platform still needs its contract documented; do not create unnecessary physical tables merely to fill a layer.

## Deliverables and content

| Deliverable | Required content |
|---|---|
| Model ERD | Overview plus readable layer views; all in-scope objects, including isolated raw tables; qualified physical names, grain, natural/composite/surrogate identities, relationships, cardinality, optionality, tenant and effective-time predicates. Clearly distinguish observed constraints, proposed logical relationships, inferred relationships and tested assertions. Do not draw ingestion arrows as enforced foreign keys. |
| Data dictionary | Every table/view and every column in the scoped model: definition, physical name/type/precision, grain, key role, null/default policy, source and column lineage, transformation/rule, units/currency/timezone, sensitivity/access context and validation references. Provide readable Markdown plus canonical JSON for coverage checks. Separate observed metadata, inferred semantics and proposed changes. |
| Bronze documentation | Source application and qualified objects; what a raw row means; replication/landing mode and actual connector evidence; source IDs, version/arrival/event timestamps; delete/replay policy; schema drift, retention, access, freshness, source reconciliation and known visibility gaps. Distinguish raw source catalogue declarations from constraints actually emitted or enforced by the candidate DDL. |
| Silver documentation | Purpose/grain of every cleaned model; source-to-target columns; casting/normalization/default rules; deduplication order/ties; deletes, invalid records and quarantine; tenant identity; conformance, effective history, join assumptions and quality assertions. Explain why each rule is upstream. |
| Gold documentation | Each fact, dimension, bridge or aggregate; business purpose and grain; keys/relationships; facts versus query-time measures; business formulas/populations; history and Unknown members; currency/calendar policy; consumer/report/semantic mappings; reconciliation evidence and approved versus proposed differences. |

Each stage also documents dependency/run order, materialization and refresh strategy, full versus incremental behavior, late arrivals/replays, monitoring and freshness expectations, operational and business ownership, access/retention policy, recovery/rollback, known limitations and unresolved decisions. Link shared definitions rather than copying long text into every table section. Record owners, SLAs and policies as unknown with a reason when evidence is absent; never fabricate them to make documentation look complete.

Provide editable Mermaid or another agreed diagram source. A diagram and narrative can share one document with separate sections; the machine-readable index must identify their coverage. Conceptual/logical/physical views should explain the same specification rather than introduce competing models. Document downstream semantic definitions and field mappings separately so a warehouse dictionary does not imply that query-time ratios, access behavior or report controls moved upstream.

## Ownership and handoff

- Repository specialists preserve original IDs, expressions, report context and source-to-target lineage candidates. The warehouse-catalogue specialist supplies object/column/type/constraint/visibility evidence for bronze and physical bindings.
- The warehouse architect owns the canonical model inventory, bronze/silver/gold contracts, model ERD, column definitions and operational modeling decisions. Source/catalogue specialists contribute evidence; existing schemas are documented even when not rebuilt.
- The semantic architect documents downstream dimensions/measures, aggregation and filter context, security, report controls and the exact gold-field crosswalk. It checks that metric logic is neither omitted nor applied twice.
- The orchestrator assembles the readable package and verifies that all artifacts refer to the same model/code/source/catalogue versions. A separate documentation specialist may render it when useful; it must not invent business definitions or override architectural decisions.
- Independent QA compares the ERD, dictionary and each layer document with actual parsed model projections, source metadata, lineage and test results. It checks missing objects/columns, grain/cardinality, null/type/units, temporal/tenant rules, consumer contracts and operational caveats. Text fields and matching hashes alone cannot establish those facts.

Regenerate or update affected documentation when the model, code, source catalogue or accepted logic changes. Preserve a change/decision record. Missing or stale documentation prevents complete model-review status. Partial assessments still deliver all three stage sections, showing available evidence and missing inputs; they must not invent a schema or pass completeness while required evidence is unavailable.

## Machine-readable coverage contract

Include a JSON `model_spec` artifact containing the explicit inventory denominator:

```json
{
  "schema_version": 1,
  "kind": "data_model_inventory",
  "models": [
    {"model_id": "WAREHOUSE.GOLD.FCT_INVOICES", "layer": "gold", "physical_name": "WAREHOUSE.GOLD.FCT_INVOICES", "columns": ["TENANT_ID", "INVOICE_ID"]}
  ]
}
```

That abbreviated shape is not a complete example schema. List every scoped bronze/silver/gold model and every column, preserving qualified identities and exact case. For nested fields use consistent, unambiguous canonical field paths and reconcile them with catalogue paths. Independent parsing/review must establish the denominator; the checker cannot discover an object deliberately omitted from both inventory and dictionary.

The canonical `data_dictionary` artifact is JSON:

```json
{
  "schema_version": 1,
  "kind": "data_dictionary",
  "model_inventory_sha256": "SHA-256 of the inventory artifact bytes",
  "models": [
    {
      "model_id": "WAREHOUSE.GOLD.FCT_INVOICES",
      "description": "Reusable invoice facts",
      "grain": "One current invoice per tenant and source invoice ID",
      "columns": [
        {
          "name": "TENANT_ID",
          "description": "Tenant scope for source identity",
          "data_type": "VARCHAR; exact length follows the qualified target schema",
          "nullability": "Logically required; physical enforcement must be verified",
          "key_role": "Composite identity with INVOICE_ID",
          "source": "Qualified source column and evidence reference",
          "transformation": "Identity; link the corresponding rule ID",
          "units": "Identifier, no numeric unit",
          "classification": "Use evidenced classification or state unknown and why",
          "validation": "Link actual key/null/persona checks and their evidence status"
        }
      ]
    }
  ]
}
```

Every model requires `model_id`, `description`, `grain` and a complete `columns` array. Every column requires the nonempty string fields shown above. Unknown values need an explanation and appropriate unresolved decisions; a string is not evidence of correctness. Add useful ownership, model/rule IDs, test links and provenance fields as needed. A readable Markdown rendering accompanies the JSON.

Associate documentation in `review-package.json`:

```json
"model_documentation": {
  "inventory_artifact_id": "model-inventory",
  "dictionary_artifact_id": "data-dictionary-json",
  "readable_dictionary_artifact_id": "data-dictionary-readable",
  "layers": [
    {"layer": "bronze", "document_artifact_id": "bronze-doc", "erd_artifact_id": "model-erd", "model_ids": ["WAREHOUSE.BRONZE.INVOICE_CDC"]},
    {"layer": "silver", "document_artifact_id": "silver-doc", "erd_artifact_id": "model-erd", "model_ids": ["WAREHOUSE.SILVER.INVOICES"]},
    {"layer": "gold", "document_artifact_id": "gold-doc", "erd_artifact_id": "model-erd", "model_ids": ["WAREHOUSE.GOLD.FCT_INVOICES"]}
  ]
}
```

All referenced artifacts must be individually hashed in the manifest. Inventory role is `model_spec`; dictionary JSON and its separate, nonempty readable rendering use `data_dictionary`; layer documents use `layer_documentation`; diagrams use `erd`. The readable rendering cannot simply point at the canonical JSON artifact. One shared ERD may supply the three layer views. Exactly one association per layer is required and each layer's `model_ids` must match the inventory. An empty stage can be declared only when its narrative explains the established architecture and why there are no selected physical objects; known missing model evidence remains a blocker.

`verify_review_package.py` invokes `verify_model_documentation.py` to check associations, roles, dictionary/inventory version alignment, complete declared model/column coverage, duplicate entries and required definition fields. It checks artifact integrity through the existing review path. It does not parse Markdown/Mermaid for truth, infer the actual schema, authenticate approvals, or replace independent content review. The review manifest binds this documentation to the same hashed code, source inventory and catalogue as the test evidence.

Earlier v1 review bundles must add these artifacts and associations before they can pass the updated checker. Do not disable the requirement or label a historical assessment complete merely to preserve its old result.

The complete synthetic example is in [the Looker-to-Omni documentation folder](../examples/looker-omni-e2e/documentation). Its dictionary and layer documents distinguish fixture evidence from unverified native and operational behavior.
