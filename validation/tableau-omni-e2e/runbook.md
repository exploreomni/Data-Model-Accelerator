# Tableau pilot qualification and handoff

This runbook describes required next validation. It does not approve or perform deployment.

Capture the selected real Tableau workbook revision, TDS/published-source versions, extracts and refresh watermarks, parameter defaults, worksheet filters/context, table-calculation addressing, dashboards/actions and aligned native output. Preserve missing artifacts as gaps. Resolve official schema/runtime qualification for the actual version before treating locally authored XML as accepted.

Collect scoped live Snowflake metadata and profile the raw sources, effective-date intervals, CDC ordering and signed adjustment contract. Decide and document how manual CSV changes will reach a governed bronze landing. Metadata cannot establish ingestion reliability or row security.

Review and approve each placement with the model and business owners. Keep tenant/date/status context for customer FIXED values and cancel only the intended segment filter. Preserve view-specific shares and scenario multiplication downstream. Decide any alternative canonical definition explicitly; local source agreement is not business authority.

In an authorized development environment, run native dbt parse/compile/build and data tests, then validate the Omni model and author its workbook/pivot expressions. Compare row keys, all selected marks, dimensional slices, negative/zero/empty populations, query filters and source versions. Test each real role/tenant independently, including denied and cross-tenant requests. UI parameters do not establish security.

Before cutover, demonstrate incremental/rebuild equivalence, late updates/deletes, freshness, restart/recovery and representative scale/cost. Agree operational ownership and rollback steps for the actual deployment; retain the last accepted model revision and source access until the approved cutover conditions are met. The current candidates rebuild tables; this pilot does not implement production incremental ingestion or a real rollback.

Refresh metadata and invalidate affected evidence when source columns, formulas, filter stages, permissions or target definitions change. Require explicit human model/semantic/security/operating acceptance tied to the same artifact hashes before deployment or source retirement.
