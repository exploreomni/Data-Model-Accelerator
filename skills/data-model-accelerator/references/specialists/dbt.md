# dbt specialist

## Purpose

Interpret the assigned dbt dependency slice as `source_specialist`. Preserve existing useful models; identify reusable transformations, report-specific behavior and tests that need independent evidence. Source identity does not select the destination framework.

## Required inputs

Use only coordinator-supplied parser findings, relevant original expressions, project/version metadata, selected resource configuration, catalogue and reuse slices, and recorded decisions. Match manifest metadata and compiled artifacts to the selected revision, adapter and environment. Request only missing macro definitions, variable values or dependency IDs that block a conclusion. Follow configured resource paths, not assumed folder names. [Adapter boundaries](../source-adapters/dbt.md) govern extraction.

## Interpretation and placement

Use the coordinator's runtime selection and compatibility assessment; do not
repeat it. dbt Core, full dbt v2 and dbt OSS are separate distributions, even when
their manifests share v12. For a supplied Information Schema summary, retain
declared-versus-verified stage, missing references and field coverage. Dependency
edges are not PK/FK relationships; parse metadata is not column-lineage proof.
Request only relevant feature details under [runtime selection](../dbt-runtime.md).

- Trace `ref`/`source` edges, disabled resources, ephemeral expansion and dispatched macros. A manifest dependency is not complete column lineage.
- Distinguish full-refresh and incremental branches, unique-key declarations, late corrections/deletes, snapshot history, hooks and grants. A declared unique key or passing static test definition does not prove uniqueness or executed tests.
- Propose `reuse_existing` for a compatible, evidenced model; `move_upstream` for stable reusable row transformations; `retain_semantic` for context-dependent measures; `retain_presentation` for display behavior; `split` for mixed concerns. Use `consolidate_candidate` only with equivalence evidence, `retire_candidate` only with consumer evidence and review, otherwise `unresolved`.
- Preserve source grain, filtering population, timezone/currency assumptions and security. Model names such as `dim_` and `fct_` are not grain proof. A gold table can still contain report-specific logic.

## Required handoff

For a profile-bound task, echo the packet profile SHA-256 as top-level
`specialist_profile_sha256` in the result. This binds instructions, not proof
of execution or approval; never relabel an old result after a profile change.

Use the existing source-result vocabulary: put the design recommendation in
`context.recommended_disposition`; `placement_candidate.destination` remains
`warehouse`, `semantic`, `presentation`, `split` or `unresolved`.
Map `move_upstream` → `warehouse`, `retain_semantic` → `semantic`, and
`retain_presentation` → `presentation`; `split`/`unresolved` map to themselves.
For `reuse_existing`, select the evidenced existing layer or `unresolved`.
Keep `consolidate_candidate`/`retire_candidate` at `unresolved` pending the
existing design decision workflow. No recommendation is an approval.

Return the supplied specialist-result shape: covered assets, stable object/rule IDs and evidence locators, grain with observed/inferred/unknown status, original expressions, dependencies, filter/security/evaluation context, placement rationale and gaps. Cite reused models and incompatible differences. Do not remove parser gaps or mutate its canonical contract. Separate declared tests from observed test results. The coordinator owns cross-source reconciliation and attaches full canonical extraction.

## Escalation and boundaries

Do not run dbt, Jinja, macros, hooks, package installers or queries. Missing catalogue bindings remain unknown; unaffected design and explicitly requested provisional candidates can continue under the existing stage workflow. Do not claim deployment readiness. Missing runtime configuration requires a precise context request, not a repository rescan. Stop after the assigned handoff; request a delta for changed dependencies.

## Acceptance checks

- An incremental filter `updated_at > max(updated_at)` cannot become proof that late deletes or equal-timestamp updates are handled. Identify replay/correction tests and preserve the limitation.
- A snapshot with two versions per customer must not join to orders on customer ID alone as many-to-one. Require effective-date logic and validate multiplicity independently.
- A compiled macro result without matching environment/revision cannot replace the authored business contract or silently resolve missing dependencies.

Reference: [dbt manifest contract](https://docs.getdbt.com/reference/artifacts/manifest-json). Vendor/version qualifications live in the adapter reference; runtime and business acceptance remain separate.
