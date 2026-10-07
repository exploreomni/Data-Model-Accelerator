# Using the Omni Modeler

Start with one business domain and a selected warehouse. The specialist can inspect an existing Omni model or create a semantic candidate over reviewed warehouse relations. It works alongside the source, warehouse engineering, analyst and dashboard roles. It does not replace their work or approve its own definitions.

## Start with this prompt

> Use the complete Data Model Accelerator skill in this checkout. Our target is dbt on Snowflake with Omni. Assess the approved source and catalogue read-only; save all work in a separate run folder. Reuse our intake answers, interview us only about missing decisions, and dispatch the dedicated Omni Modeler. Start with one domain. Show grains, populations, metric definitions, aliases, placement choices and unresolved questions before proposing consequential changes. Preserve existing behavior unless we approve a correction. Produce native Omni files, a semantic dictionary, a connected diagram, AI context and the guided engineering ZIP alongside the selected warehouse deliverables. Keep local checks, native validation, result accuracy, access, business review and deployment as separate outcomes.

For BigQuery, Databricks, Redshift, ClickHouse or MotherDuck, select that warehouse explicitly. Transformation framework and warehouse are independent choices: dbt, Coalesce and native SQL continue through their existing engineering routes. A supported parser or generated file does not establish native qualification for a warehouse, agent host or Omni tenant.

## What happens during the engagement

1. **Confirm the boundary.** Retain the engagement type, source version, scope, target environment, audiences and requested outputs. Establish classification and the approved source-to-agent projection before dispatch. The portable modeler accepts reviewed pre-sanitized PUBLIC/INTERNAL metadata without sensitive categories; it does not provide a protected-data sandbox.
2. **Inspect before changing.** Capture authored and effective Omni state separately, including model, shared/workbook and branch identity. Reconcile against a separate complete inventory where available. Preserve source bytes, opaque blocks and inherited origins. Missing files never imply deletion.
3. **Resolve meaning.** Document population, grain, date roles, filters, units, access implications and independent expectations. Unknowns stay visible. Put reusable cleansing and durable facts/dimensions upstream; retain appropriate governed metrics and query composition in Omni. A query view is not automatically a warehouse materialization.
4. **Build a bounded candidate.** Use reviewed mappings and exact physical catalogue bindings. Preserve native filenames, including `.query.view`. For existing models, prefer hash-bound leaf edits; do not write a merged effective export back as authored overrides. Unqualified constructs remain preserved and explicitly unsupported for generation.
5. **Test the selected behavior.** Run static checks and independent result comparisons. Inspect changed objects and their downstream dependencies, then obtain separately authorized native compilation, query and access evidence. Schema refreshes, branch isolation, dbt deferral and production fallback need explicit environment evidence.
6. **Review the package.** Open `START_HERE.html`, then **Omni**. Inspect topics, measures, selected fields, dependencies, decisions and remaining checks. Engineer exports include selected native files; reviewer exports contain curated documentation. Technical context stays in the optional audit. Omitting evidence cannot create a pass.
7. **Approve and hand off.** SMEs resolve definitions against the exact candidate. The release coordinator then offers a separately authorized route. The modeler never silently refreshes production, merges a branch, publishes a dashboard or deploys a warehouse model.

## What is implemented

| Area | Bounded local support | Keep visible as a gap |
|---|---|---|
| Model inventory | Native identity, exact-byte round trip, scope/origin, dependencies, cycles, explicit inventory reconciliation | Missing/paginated exports, unknown semantics and unauthenticated completeness |
| Core modeling | Physical views, single-parent inheritance, supported dimensions/measures and local filters, topic aliases/selectors, relationship paths | Multiple inheritance and unfamiliar operational/security constructs |
| Query views | Modeled and conservative read-only SQL forms, output identities/types, grain and population dependencies, stale-field checks | Arbitrary SQL, unsupported query controls, native eligibility and truncated populations |
| Advanced modeling | Focused guidance and preservation for composite topics, LOD and aggregate awareness | Generation/operation combinations without qualified contracts; composites retain their documented **Beta** label |
| AI context | Direct/derived lineage to reviewed gold inputs; topic field and AI selection; immutable suites and repeated trials | Unreviewed meanings, protected operands, unobserved provider behavior and effective permissions |
| Lifecycle | Changed/dependent closure, baseline/new issue handling, route/environment pins, optional signed preflight binding | Imported evidence authenticity, live collector coverage, promotion and production operations |

The machine-readable [capability registry](../skills/data-model-accelerator/assets/omni-knowledge.json) separates documented, implemented, locally tested and live-qualified status by object, operation and dialect. Read the limitation for each row. No current row claims blanket native qualification.

For a large project, divide delivery into domain waves with their complete
dependency and consumer closure. The bounded inventory rejects an oversized
scope instead of silently truncating it. An inventory limit is a request to
partition/reconcile the scope, never permission to omit inconvenient files.

## Engineer reference

Load only the relevant knowledge modules and retain both returned digests:

```sh
python skills/data-model-accelerator/scripts/omni_knowledge.py \
  --objects views,topics,query_views \
  --operations inspect,generate,static_validate \
  --dialects snowflake --metadata-only
```

Verify the entire selected installation from the intended checkout:

```sh
python skills/data-model-accelerator/scripts/omni_modeler.py inspect-install \
  --installed /absolute/installed/data-model-accelerator
```

A stale copy blocks invocation when supplied to the runner. With no installed path, the receipt explicitly covers the active checkout only. No installation or account connection happens automatically.

| Work | Contract |
|---|---|
| Task projection, callback, receipts and installation | [Modeler task](../skills/data-model-accelerator/references/omni-modeler-task.md) |
| Source inventory and safe edits | [Inventory](../skills/data-model-accelerator/references/omni-inventory.md) |
| Core modeling and query views | [Fields](../skills/data-model-accelerator/references/omni-modeler-fields.md), [joins/topics](../skills/data-model-accelerator/references/omni-modeler-joins-topics.md), [query views](../skills/data-model-accelerator/references/omni-modeler-query-views.md) |
| Change impact and native requests | [Lifecycle](../skills/data-model-accelerator/references/omni-modeler-lifecycle.md), [native validation](../skills/data-model-accelerator/references/omni-native-validation.md) |
| Reviewed AI definitions and repeated answer/result trials | [AI context](../skills/data-model-accelerator/references/omni-ai-context.md) |
| Curated semantic catalog, diagram and selected ZIP | [Omni handoff](../skills/data-model-accelerator/references/omni-handoff.md) |
| Static results and evidence limits | [Qualification](qualification.md) |

Host identifiers name available adapter destinations, not prebuilt integrations with every host SDK. The coordinator supplies the actual delegation callback and records its execution identity; no callback returns an actionable `unavailable` status. Inline work must disclose its independence limit. A prompt file, imported receipt or successful local callback cannot authenticate an external AI session.

## Interpret the evidence correctly

Static validation checks the implemented contract. Independent expected rows test meaning for the selected cases. Native compilation checks the selected Omni environment. Access tests need real allowed and denied principals. AI trials compare decisions, selected definitions and fields; numeric accuracy is checked only when result expectations are present. Exact result comparisons preserve NULL and type distinctions; use the independent benchmark contract for keyed rows and numerical tolerances.

Keep each lane separate. Successful local tests can justify a development pilot; they cannot establish customer acceptance. Updating a definition, source, context, knowledge pin or candidate invalidates dependent evidence and requires the affected checks again.
