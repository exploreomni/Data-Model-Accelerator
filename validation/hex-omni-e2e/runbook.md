# Hex simulation and qualification handoff

The local simulation reads only the bundled synthetic source and metadata. Create a fresh output folder using the command in the Hex exercise guide; inspect every failure and the frozen input hashes. Do not overwrite prior evidence or regenerate the independent oracle from candidate results.

Generated models are full-rebuild candidates. Before any real deployment, choose a bounded business domain and capture native Hex exports/results, exact project/component versions, inputs, environment, identity and watermarks. Collect actual warehouse metadata and profile CDC/history/adjustment inputs. Decide how approved manual adjustments enter the warehouse with ownership and auditability.

Preserve both current active-customer definitions pending an identified business authority's decision. Keep model lineage and consumer mappings when renaming metrics. The first-paid-month field is an invoice-date proxy at capture; do not recast it as historical payment-event-time truth.

Use an isolated development database/role and explicitly reviewed dbt profile. The bundled profile is illustrative; supply real connection material through the authorized platform. The guard in generate_schema_name maps only the synthetic fixture target/database to SILVER/GOLD. Other targets retain dbt namespace isolation. Inspect proposed DDL, materializations, macros, dependencies and tests before any compile/run that may contact a warehouse. Validate generated Omni definitions and selected reports in an authorized development environment.

Require native compile/execution, per-role/tenant access tests, incremental/rebuild comparisons, late updates/deletes, failure/restart, representative scale/cost, freshness and rollback evidence. The current local rebuild/replay checks do not establish those production operations. Retain the previous deployed revision and affected objects, then use the platform's approved rollback procedure if reconciliation fails; no real rollback is supplied or executed here.

Deployment/cutover and source retirement require human approval tied to the exact source, catalogue, code, dictionary/ERD, tests and destination. After an authorized action, capture returned run/object IDs and reread definitions/results. An ambiguous write requires readback before retry. No approval, cutover or deployment occurred in this exercise.
