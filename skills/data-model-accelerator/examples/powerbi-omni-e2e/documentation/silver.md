# Silver: normalized current state

Four table models retain source-grain responsibilities before report context. See [SQL](../target/dbt/models/silver), [column dictionary](data-dictionary.md) and [ERD](model-erd.md).

| Model | Grain | Normalization and invalid-input behavior |
|---|---|---|
| DMA_POWERBI.SILVER.BILLING_INVOICES | Tenant/invoice | Partition by tenant/invoice, order source sequence descending, choose latest before removing tombstones. Cast invoice date and cents; trim/lowercase status; retain source sequence and all current statuses. |
| DMA_POWERBI.SILVER.BILLING_PAYMENTS | Tenant/payment | Latest version before deletion, cents/sequence casts; retain parent invoice. Aggregate only later at tenant/invoice before joining facts. |
| DMA_POWERBI.SILVER.BILLING_CUSTOMER_HISTORY | Tenant/customer/valid-from | Deduplicate exact complete records with DISTINCT; cast start/end dates. Null end remains open. Differing overlapping history or missing invoice coverage fails. |
| DMA_POWERBI.SILVER.BILLING_ADJUSTMENTS | Tenant/invoice | Preserve signed correction and reason; cast cents. Do not choose an arbitrary duplicate correction. |

These rules are reusable source preparation, corresponding to native SQL in the two source M Import partitions. They are independent of report date/segment/status, CALCULATE modifiers and disconnected multiplier selection. Source M's invoice net/default and month rules and DAX calculated-column outstanding move to gold after their required joins.

**Identity and history:** tenant participates in every partition, reference and relationship. Required identifiers are nonnull and exclude pipes within this fixture. Source payload conflicts at identical sequence fail before choosing ROW_NUMBER; identical replay is harmless. Effective validity is `[VALID_FROM,VALID_TO)` and must match each current invoice exactly once. There is no silently injected Unknown member and no quarantine table hiding invalid rows.

**Execution and quality:** full table materialization follows [model-map.json](../target/model-map.json). Four source assertions run before build; five relational/grain/balance checks run after required models exist, including payment reconciliation. Nine singular SQL assertions are authored, with separate generic tests in model YAML. A test declaration is not native execution evidence or an enforced DDL constraint.

**Refresh and recovery:** replay or late invoice/payment/history changes require rebuilding the affected current-state tables and dependent gold. Production incremental strategy, atomic promotion and rollback are not implemented; recover by validating the retained capture and rebuilding in dependency order. Monitor cast failures, grains, deletes, orphan references and history coverage. Operational/business owners, freshness targets, alert route, access/masking and retention policy are unknown because the fixture supplies none.
