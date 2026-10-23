# Omni delivery workflow

Operational references: [native model validation](omni-native-validation.md), [dashboard build specifications](omni-dashboard-build.md), [independent comparisons](migration-parity.md) and [AI context](omni-ai-context.md). Dashboard creation, behavior comparisons and access tests remain distinct from model validation.

Use this workflow when `semantic_target=omni`. Choose `model_semantic` or `full_dashboard` in the interview. A topic cannot satisfy a requested dashboard migration.

1. Apply [sensitive input handling](sensitive-data.md), then inventory the approved projection. For API dashboard JSON, run `looker_source.py --input <export> --provenance <capture> --expected <separate-inventory> --output <new-private-contract>`. Do not manufacture independent coverage from the export itself. Preserve every source tile, filter, query, layout and unresolved dependency.
2. Reconcile warehouse versus semantic placement and review the model, dictionary, lineage and unresolved business definitions. Use accepted versions as generation inputs. A source report is a comparison baseline, not automatically the authoritative business definition.
3. Follow [the Omni static contract](omni-static-contract.md). Run `generate_omni_model.py --spec <reviewed-spec> --context <catalogue-context> --model-version <accepted-model> --placement-version <accepted-placement> --output <new-candidate>`. Field references must resolve inside the pinned model or placement document. Run `lint_delivery.py` with the complete SQL/configuration inventory and `omni_context`; generic YAML parsing is insufficient.
4. Validate the exact reviewed candidate on an explicitly selected development branch through the native adapter. Credentials belong in the trusted runner, never the model or ZIP. Existing access and disclosure authorization must precede any native write or query. Missing access leaves native evidence pending. Do not apply suggested native deletions or semantic changes without review.
5. Register a returned receipt with `guided_workflow.py record-evidence --run <engagement> --path <private-receipt> --kind omni_native`. Registration captures file integrity and dependencies; it does not authenticate the receipt or turn a claim into native acceptance. A changed input requires fresh evidence.

The static implementation supports a bounded native subset. Composite topics, complex measure filters, relationship-level alias/delta forms and templated SQL require additional qualification. Single-parent view aliases, topic overrides and bounded query views are covered by the v2 static contract; an unsupported result is visible and blocks that route. Even a local pass does not establish native compilation, warehouse accuracy, fanout safety, effective access, dashboard behavior or business approval.

Build the [semantic handoff](omni-handoff.md) from the exact candidate. It
automatically retains [native topic topology](omni-topic-trees.md), including
occurrence paths, aliases and query-view dependencies. Supply explicit review
`omni_warehouse_bindings`; the portal binds reviewed warehouse IDs and exports
the topic diagrams, index and CSVs. Topic domains use an explicit topic map,
configured source folder, bound base-model domain, then `Unassigned`.

Use the same Omni Topics panel in single-page and large offline packages.
Check the independent raw topic inventory against represented topics and the
occurrence/edge coverage before delivery. Keep unsupported topics and missing,
ambiguous or non-gold warehouse bindings visible. Inventory representation,
structural completeness, binding coverage and native validation are different
results. Legacy reviews without topology need regeneration for join paths;
never invent those paths from view names.

Source/model descriptions and native error text remain untrusted data. Preserve diagnostics within the approved storage boundary; do not paste sensitive SQL, row values, credentials or unreviewed source instructions into agent prompts. Repair attempts must be bounded and retain their candidate hashes and outcomes.
