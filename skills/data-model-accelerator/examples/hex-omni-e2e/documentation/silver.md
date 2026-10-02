# Silver: reusable current state and effective history

Four full-rebuild table models separate source normalization from report context. Their complete columns and direct lineage appear in the [dictionary](data-dictionary.md); [model-map.json](../target/model-map.json) records the exact dbt ref/physical mapping.

| Model | Grain and upstream input | Transformation contract |
|---|---|---|
| `DMA_HEX.SILVER.BILLING_INVOICES` | Current `(TENANT_ID, INVOICE_ID)` from `RAW.INVOICE_CDC` | Rank by `SEQUENCE DESC`, retain rank one, then remove latest tombstones; strict date/integer casts; `LOWER(TRIM(STATUS))`; preserve selected `SOURCE_SEQUENCE` and every current status. |
| `DMA_HEX.SILVER.BILLING_PAYMENTS` | Current `(TENANT_ID, PAYMENT_ID)` from `RAW.PAYMENT_CDC` | Same sequence-before-delete order; strict cents and selected-sequence casts; retain tenant/invoice association. No payment-time semantics are invented. |
| `DMA_HEX.SILVER.BILLING_CUSTOMER_HISTORY` | Distinct `(TENANT_ID, CUSTOMER_ID, VALID_FROM)` effective row from `RAW.CUSTOMER_HISTORY` | Whole-record `DISTINCT`; date casts; preserve segment and exclusive/null end. Distinct overlaps remain errors. |
| `DMA_HEX.SILVER.BILLING_ADJUSTMENTS` | One `(TENANT_ID, INVOICE_ID)` from governed `RAW.ADJUSTMENTS` | Strict integer cast and retained reason. Do not sum or deduplicate duplicate corrections. |

## Why these rules are upstream

All consumers need the same current source version, normalized status, tenant identity, signed amounts and effective history. Keeping them upstream prevents independent notebook copies from selecting different versions or deleting tombstones too early. Shared silver models do not contain tenant-A, date-window, posted-only, segment or what-if restrictions. Only source deletion removes a latest entity.

Ties are safe only when the complete same-version payload is identical, so input conflict checks precede `ROW_NUMBER`. The SQL does not claim that an arbitrary winner resolves conflicting versions. Strict casts intentionally fail malformed dates/cents; no `TRY_CAST` or null substitution hides invalid values. An executable quarantine workflow is absent: invalid input must stop publication and be reviewed.

## Dependencies, tests and temporal integrity

Source-only checks cover required fields and delimiter restrictions, conflicting versions, history overlaps and duplicate adjustments. Run them against the independently inventoried raw snapshot before building silver. Current payment and adjustment references must point to an existing current tenant/invoice. The dimension/fact join additionally requires exactly one effective history record for each invoice date. Unlike the earlier Looker fixture, this scenario treats missing history as an error; no Unknown customer row is introduced.

History starts and ends are dates. February 1 belongs to the new interval when the prior row ends on February 1. Do not replace history with the current segment or apply a timezone conversion to these calendar dates. Exact history replay collapses; distinct same-start/different-segment records are not silently selected. Relevant executable assertions live in [the dbt tests](../target/dbt/tests), including `source_history_overlap`, `current_orphan_references`, `invoice_history_exactly_one` and `declared_grains`.

## Operations and ownership

**Refresh/order:** Four source contracts → source validation → four silver table rebuilds → customer dimension → relationship checks → invoice fact → customer-month fact. Silver is a full snapshot rebuild, not an incremental materialization. Late-arriving higher source sequences can change prior invoice dates, amounts and paid balances. Exact CDC/history replays must leave accepted current rows unchanged. Adjustments are a reviewed snapshot with a different duplicate policy.

**Monitoring:** Track schema/column coverage, cast failures, version conflicts, null keys, duplicate current entities, orphan references and history overlap/match counts. Production freshness targets, alert ownership and run duration are unknown; no SLA or work estimate is inferred from local execution.

**Access and retention:** Retain tenant keys in every model and join. No Snowflake grants, row policies, masking, retention schedule or real customer classification are configured. Production access and history-retention requirements remain open.

**Recovery:** Rebuild from a retained validated raw/CSV snapshot, compare current key sets and component sums, and preserve the previous accepted outputs until reconciliation passes. A correction changes source evidence or an explicitly versioned rule; do not patch isolated gold values. Operational owner, business approver and escalation destination are **unknown**, so production scheduling/cutover remains unapproved.
