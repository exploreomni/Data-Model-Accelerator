# Bronze responsibilities: four explicit source contracts

`DMA_HEX.RAW` implements bronze responsibilities in this proposal. Three existing synthetic warehouse contracts are reused; the separately inventoried adjustment file becomes a proposed fourth landing contract. The [inventory](model-inventory.json), [complete dictionary](data-dictionary.md) and [raw DDL](../target/snowflake/00_raw_contract.sql) cover every physical field. No native connector or production ingestion implementation is present.

| Physical object | Raw row / identity | Origin and disposition |
|---|---|---|
| `DMA_HEX.RAW.INVOICE_CDC` | Full invoice after-image occurrence; version `(TENANT_ID, INVOICE_ID, SEQUENCE)` | Synthetic `input/raw-data.json#/INVOICE_CDC`; preserve all supplied versions and replays. |
| `DMA_HEX.RAW.PAYMENT_CDC` | Full payment after-image occurrence; version `(TENANT_ID, PAYMENT_ID, SEQUENCE)` | Synthetic `input/raw-data.json#/PAYMENT_CDC`; no payment timestamp supplied. |
| `DMA_HEX.RAW.CUSTOMER_HISTORY` | Customer effective-history row occurrence `(tenant, customer, validity interval, segment)` | Synthetic `input/raw-data.json#/CUSTOMER_HISTORY`; exact complete snapshots may repeat. |
| `DMA_HEX.RAW.ADJUSTMENTS` | One manual signed correction per `(TENANT_ID, INVOICE_ID)` | Proposed explicit landing of `input/repo/adjustments.csv`; reason and file receipt remain part of provenance. |

The source snapshot is `2026-03-02T00:00:00Z`, connection ID `11111111-1111-4111-8111-111111111111`, Snowflake account `DMA_HEX_SYNTHETIC`, database `DMA_HEX`, schema `RAW`. These are fixed synthetic identities, not observed live account access. The original Hex projects import component `8c7958a3-573b-5b81-9a0e-02de54bed99d` at version `48181ff3-ae9a-5717-add9-699e64214924`; the SQL and Python cells are preserved in [the shared source component](../input/repo/shared-revenue.hex.yaml). Component inventory/version verification is separate from warehouse source binding.

## Source and validation contract

`SEQUENCE` is an authoritative complete order only under the test scenario. Select the maximum source sequence before excluding `IS_DELETED=true`. Exact repeated CDC payloads at one version are idempotent; differing payloads at that version fail. The raw layer retains both old versions and tombstones. No arrival timestamp or production changefeed ordering guarantee is inferred.

Keys must be non-null/nonempty and contain no `|`, because proposed deterministic surrogates use this delimiter. History intervals use inclusive `VALID_FROM` and exclusive `VALID_TO`, with null end open-ended. Whole identical history records may replay; differing overlapping records fail. Raw invoice/history dates are VARCHAR in the frozen synthetic catalogue and candidate DDL; silver strictly casts them to DATE. The local adapter loads these dates into DATE columns for execution, which is an explicitly separate representation and does not prove native raw type handling. The candidate raw DDL emits nullable columns and no enforced PK/FK constraints. Required fields and relationships are logical rules backed by tests, not properties established by DDL.

Adjustment amounts are integer USD cents. Negative amounts are credits and positive amounts corrections. Every duplicate adjustment key, including identical duplicates, fails; an unknown invoice reference fails. A missing file or missing landing source fails. A valid invoice with no adjustment row receives zero downstream. Those cases must remain distinct. An approved loader must retain source-file identity, checksum, capture/review evidence and row-count reconciliation before replacing manual notebook ingestion. No loader, named approver or approval event is supplied here.

## Operations, governance and recovery

**Order and refresh:** Establish raw schema and source inventory, validate the exact source payload and CSV receipt, then execute source-only assertions before transformations. Raw tables are populated by the local harness for the synthetic run. There is no production connector, automatic source freshness timestamp, replication schedule, incremental checkpoint or quarantine table.

**Schema drift and monitoring:** New/missing fields, failed strict amount/date conversions, missing source files, conflicting versions and ambiguous identities block further processing. Compare raw object/column inventory and source counts against the same captured inputs. Production freshness SLA, alert routes, retention period, schema-evolution owner and maintenance schedule are unknown because the scenario supplies none.

**Access:** Raw tenant and financial values remain in scope. All data is invented, but production masking/classification, service-account grants, customer isolation and retention would require explicit review. A Hex input or hidden Omni field is not authorization. No grants or row policies are issued by this candidate.

**Recovery:** Preserve the original snapshot and adjustment receipt. On validation failure, retain that failed input separately and stop publication; do not silently omit records. Rebuild silver/gold from the same validated snapshot after correction and compare keys and dimensional outputs. Raw deletion, retention changes and backfill policies require a separately approved operating plan. Operational and business owners are **unknown**.
