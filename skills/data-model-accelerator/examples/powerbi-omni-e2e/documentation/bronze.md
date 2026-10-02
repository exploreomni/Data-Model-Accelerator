# Bronze: source contracts and proposed landing

The synthetic account is `DMA_POWERBI_SYNTHETIC`, database `DMA_POWERBI`, schema `RAW`, at capture `2026-03-02T00:00:00Z`. RAW implements bronze responsibilities directly; no extra copied bronze tables are proposed. [Bootstrap DDL](../target/snowflake/00_raw_contract.sql) and [dbt sources](../target/dbt/models/sources.yml) declare the exact four objects. Source TMSL Import M partitions reference Snowflake native SQL; their authored presence does not establish native refresh or query folding.

| Object | Grain and identity | Source / policy |
|---|---|---|
| DMA_POWERBI.RAW.INVOICE_CDC | One supplied complete invoice version occurrence; tenant/invoice/sequence identifies a version | [raw-data.json](../input/raw-data.json); identical full-version replay accepted, differing same-version payload rejected. Highest sequence must be chosen before tombstones. |
| DMA_POWERBI.RAW.PAYMENT_CDC | One supplied complete payment version occurrence; tenant/payment/sequence | Same captured input; preserve payment ID, tenant and parent invoice; replay/deletion policy mirrors invoices. |
| DMA_POWERBI.RAW.CUSTOMER_HISTORY | Supplied tenant/customer/effective-start history occurrences | Exact complete-row replay accepted; different overlapping intervals fail. Start inclusive, end exclusive, null end open. |
| DMA_POWERBI.RAW.ADJUSTMENTS | One signed correction per tenant/invoice | Proposed governed landing of [adjustments.csv](../input/repo/adjustments.csv). Every duplicate or orphan key fails; no valid-invoice row means zero later. A missing file is not an empty correction set. |

Raw invoice/history dates are declared **VARCHAR**; silver casts them to DATE. The local harness may adapt raw dates for its engine, but this does not change the physical source contract. USD cents and sequence are NUMBER(38,0), tombstones BOOLEAN, other fields VARCHAR. No source arrival timestamp is supplied; sequence is version ordering, the snapshot is capture metadata, and invoice dates are calendar dates. Physical PK/FK/NOT NULL enforcement is absent from the candidate DDL. The [dictionary](data-dictionary.md) specifies every column.

Data is invented. No actual connector, replication job, file approval workflow or storage receipt is proved by DDL. Keep source project/partition IDs and source account/schema bindings together in the [crosswalk](source-to-target.json) and separate catalogue evidence. Unknown/missing columns or drift fail bounded replay; production evolution and quarantine procedures are unresolved.

**Operations:** load and validate the exact snapshot and CSV before the six-model dependency order in [model-map.json](../target/model-map.json). Monitor schema/identity/cast errors, version conflicts, duplicate adjustments, orphan references, history overlap and source counts. No production freshness SLA, retention period, alert route or named operational/business owner is supplied. Production financial/identity classification and masking/grants require owner review; no grants or policy deployment is implied.

**Recovery:** preserve immutable source receipts and restore a known capture before rebuilding downstream tables. Late CDC or effective-history changes require a full current-state rebuild in this candidate. There is no implemented streaming/incremental schedule, warehouse rollback automation or retention job.
