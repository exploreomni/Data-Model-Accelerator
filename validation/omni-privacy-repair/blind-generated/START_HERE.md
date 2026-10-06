# Blind synthetic model pilot

Two fresh candidate packages were generated from the permitted synthetic snapshots and intake only:

- [Maintenance — dbt/Snowflake + Omni](maintenance/START_HERE.md)
- [Energy — dbt/BigQuery + Omni](energy/START_HERE.md)
- [Actual run report and limits](RUN_REPORT.md)
- [Machine-readable generation summary](generation-summary.json)
- [Input integrity — all eight files unchanged](input-integrity.json)

Each package has five bronze/silver/gold views, a complete column dictionary, connected ERD, layer documentation, one native Omni view/topic, deterministic source extraction and a complete manual dashboard worklist. Inputs and all native physical bindings are explicitly synthetic; no catalogue collection, native validation, tenant access or business acceptance is claimed.

Both Omni static checks and both declared SQL lint scopes pass. Local observations preserve maintenance work order grain and energy reading grain. These are development checks, not independent acceptance: the parent evaluator owns the frozen expectations. Dashboard coverage remains unknown without a separate source inventory, and all native tile/control/layout translation remains manual. AI context intentionally withholds unapproved content.

Private guided state and immutable tool receipts were separated from this portable candidate. The included summaries identify their original receipt hashes; they do not replace or authenticate those receipts. Proposed definitions remain proposed. No deployment or publication was performed.
