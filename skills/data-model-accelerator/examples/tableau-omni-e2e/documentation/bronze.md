# Bronze responsibilities in DMA_TABLEAU.RAW

Four explicit raw contracts implement bronze responsibilities. Three are synthetic warehouse inputs; the separately inventoried manual CSV supplies a proposed fourth governed landing. [Raw DDL](../target/snowflake/00_raw_contract.sql), [source declarations](../target/dbt/models/sources.yml), [inventory](model-inventory.json) and [dictionary](data-dictionary.md) cover the same objects and columns. No extra bronze copy, real ingestion connector or production source permissions are claimed.

| Physical object | Raw grain and identity | Provenance |
|---|---|---|
| `DMA_TABLEAU.RAW.INVOICE_CDC` | Full invoice after-image occurrence; version identity tenant/invoice/SEQUENCE | `input/raw-data.json#/INVOICE_CDC`; all source versions, tombstones and exact replays retained. |
| `DMA_TABLEAU.RAW.PAYMENT_CDC` | Full payment after-image occurrence; version identity tenant/payment/SEQUENCE | `input/raw-data.json#/PAYMENT_CDC`; multiple payments may reference one scoped invoice. |
| `DMA_TABLEAU.RAW.CUSTOMER_HISTORY` | Effective customer history occurrence, with tenant/customer/valid-from identity after exact deduplication | `input/raw-data.json#/CUSTOMER_HISTORY`; inclusive start/exclusive end, null end open-ended. |
| `DMA_TABLEAU.RAW.ADJUSTMENTS` | One signed manual correction per tenant/invoice; any duplicate key fails | Proposed governed landing of `input/repo/adjustments.csv`; retain reason and a source-file receipt. |

The fixture account is `DMA_TABLEAU_SYNTHETIC`, database `DMA_TABLEAU`, schema `RAW`, captured at `2026-03-02T00:00:00Z`. A TWB custom SQL datasource and its TDS mirror refer to this namespace. The TWBX packages those exact assets and must not create a second counted workbook. No Hyper extract is supplied. Native filenames/names and source hashes are preserved in the [crosswalk](source-to-target.json) and the orchestrator's source graph.

## Raw contract and evidence

`SEQUENCE` is a complete source ordering only under the scenario. Current state chooses its maximum within tenant/business entity before excluding latest tombstones. Exact same-version payload repetitions are replay; differing payloads at the same sequence fail. IDs must be non-null/nonempty and exclude `|` in this fixture. A production collision-safe key encoding requires its own decision.

Raw invoice/history date columns are **VARCHAR** in the physical contract, with strict date casts in silver. The local engine adapts those values to DATE for execution; this separate representation does not prove native raw conversion behavior. Money is integer USD cents; retain signs and never infer currency conversion. The candidate DDL emits no enforced primary/foreign/non-null constraints. Required fields and relationships are logical assertions verified separately.

Adjustments are an explicitly inventoried source, not an incidental notebook file. Missing file content, missing landing source, duplicate tenant/invoice keys or orphan references block processing. A valid invoice with no adjustment row receives zero downstream. Negative corrections are credits. Proposed landing governance must retain file checksum, row/column counts, provenance, review and load evidence. No actual loader, source approval, named owner or scheduled replacement of this file is present.

## Operations, governance and recovery

**Order:** inventory raw objects and the CSV, verify datasource/TDS/archive consistency and source receipts, validate input contracts, then build silver. Raw bootstrap defines schema only; a separate validated harness load supplies invented data. No production ingestion, freshness guarantee, incremental checkpoint or quarantine implementation is supplied.

**Monitoring:** fail new/missing fields, malformed dates/cents, conflicting versions, invalid identities, history overlap and duplicate adjustments. Reconcile source counts and checksums at the same capture. Real freshness SLA, alert route, operational owner, retention period and schema-drift owner are unknown because the source scenario does not provide them.

**Access:** all records are synthetic. Production financial/identity classification, masking, database grants, retention and customer isolation need explicit approval. Tableau input controls and hidden Omni fields are not row-security controls. This package issues no grants or policies.

**Recovery:** retain raw snapshots and adjustment receipts; stop publication on failure and preserve the failed inputs for review. After a versioned correction, rebuild downstream and reconcile invoice keys and dimensional results. Do not silently discard conflicting rows or patch isolated gold values. Raw deletion, backfill, retention changes and consumer cutover require separate authorization. Business and operational owners remain **unknown**.
