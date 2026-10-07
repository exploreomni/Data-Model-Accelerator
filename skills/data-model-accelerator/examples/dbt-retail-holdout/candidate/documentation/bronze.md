# Bronze: supplied raw contracts

Coverage: `DMA_RETAIL.RAW.ORDER_CDC`, `DMA_RETAIL.RAW.ORDER_LINE_CDC`, `DMA_RETAIL.RAW.FULFILLMENT_CDC`, `DMA_RETAIL.RAW.RETURN_CDC` — four objects, 30 columns. Bronze is reused; creating four extra copy tables would add no transformation or evidence. The [catalogue](../../input/catalogue/warehouse-catalogue.json), its original [exports](../../input/catalogue/exports/columns.json) and [source declarations](../dbt/models/sources.yml) establish the declared schema. The [dictionary](data-dictionary.md) documents every raw column and the [ERD](model-erd.md) covers all four independently landed inputs.

## Grain and identity

| Physical object | Raw occurrence grain | Current entity identity | Current consumer |
|---|---|---|---|
| DMA_RETAIL.RAW.ORDER_CDC | tenant/order/sequence occurrence | TENANT_ID, ORDER_ID | STG_ORDERS |
| DMA_RETAIL.RAW.ORDER_LINE_CDC | tenant/order/line/sequence occurrence | TENANT_ID, ORDER_ID, LINE_ID | STG_ORDER_LINES |
| DMA_RETAIL.RAW.FULFILLMENT_CDC | tenant/fulfillment/sequence occurrence | TENANT_ID, FULFILLMENT_ID | STG_FULFILLMENTS |
| DMA_RETAIL.RAW.RETURN_CDC | tenant/return/sequence occurrence | TENANT_ID, RETURN_ID | STG_RETURNS |

Repeated identical occurrences are permitted. The entire payload at a given entity identity and sequence must be identical; differing payloads reject even when the conflicting version is older than the current version. SEQUENCE is entity-local ordering, not a timestamp or global ingestion watermark. Positive SEQUENCE and Boolean IS_DELETED come from the contract. The snapshot timestamp is capture-level evidence only; individual source arrival/event timestamps and a physical replication tool were not supplied.

## Types, ingestion and input acceptance

Source dates remain VARCHAR ISO YYYY-MM-DD in the raw contract. Silver casts the current order date to DATE. Metadata NUMBER(38,0) is loaded as local DECIMAL(38,0); the supplied adapter contract accepts signed-64-bit integer inputs. No float money, currency conversion or timezone adjustment is introduced. All source fields allow null in supplied physical metadata; the logical contract requires values. Physical primary/foreign keys and NOT NULL constraints are not claimed.

`evaluator.validate_raw` checks exact table/column sets, nonnull logical values, strict input types, canonical dates, ASCII alphanumeric identities, value bounds, all-version ambiguity, current references and quantity limits before any accepted output. It rejects malformed input rather than silently coercing, dropping or quarantining it. The eight `source_*` singular dbt tests reinforce payload conflicts and logical value rules. This Python raw gate remains a required part of the local workflow; a direct dbt command alone does not enforce every JSON/type/schema condition.

## Refresh and operations

The local loader creates typed raw tables from one complete frozen capture, using prepared inserts. Every run replaces the local synthetic capture; this is neither a verified replication connector nor a CDC ingestion service. Input replay or reordering does not change current results; a valid higher sequence replaces its prior version. Deletes are retained as raw tombstones so silver can apply them after ranking. No raw retention pruning or incremental watermark strategy is authorized or implemented.

Run order: inspect/freeze raw plus catalogue → validate full capture → load isolated local RAW → native dbt preflight/full build → reconcile outputs. Archive rejected input identity and diagnostics under the operator's approved controls; durable quarantine is a proposal requiring ownership. On failure do not publish outputs. Reload the last accepted complete capture and rebuild after review; see [runbook](../runbook.md).

Freshness/arrival latency, connector ownership, business owner, runtime role/grants, masking, raw retention, backup/recovery targets and production reconciliation schedule are unknown because no operational evidence was supplied. The catalogue's 2026-09-11T12:00:00Z capture is an authored fixture timestamp, not proof of a current production account. Local metadata checks verify four objects/30 fields and receipt hashes; native Snowflake metadata and security are separate gates.
