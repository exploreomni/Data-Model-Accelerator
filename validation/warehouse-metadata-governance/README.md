# Warehouse metadata implementation evidence

Local implementation on `atx/warehouse-metadata`, based on `4024569`, September 30, 2026. These are synthetic and local results. No customer repository, warehouse or Omni tenant was mutated. The reported Cortex customer counts are used only as a synthetic scale target, not reproduced customer acceptance.

## Delivered behavior

- Dictionary v2 and lossless migration, with separate RAW/source inventory, provenance, explicit unknown classifications and multiple key roles.
- dbt YAML preview/apply into a separate candidate; owned-field regeneration, preservation/conflict detection, modern `config.meta.dma`, and `persist_docs` with override reporting.
- Exact physical bindings and one-statement metadata differences for Snowflake, Databricks, BigQuery, Redshift, ClickHouse and MotherDuck. Informational custom-tag assignment is implemented for Snowflake and Unity Catalog; no invented equivalent tag API is emitted elsewhere.
- Independent physical-column coverage, expected metadata comparison, direct/inherited tag separation, freshness, object-incarnation checks and metadata-only environment comparison.
- Signed linked build/metadata simulations with immutable dictionary/configuration, shared physical-destination identity, post-build observations, separate RAW scope, partial failure and recovery-lock handling.
- Guided Metadata review and ZIP evidence integrity, plus canonical semantic/AI context handoff and optional new-Snowflake naming previews.

## Evidence and reproduction

Final pinned lane: **1,108 tests passed, zero skips**, including **190 metadata tests**. A separately generated three-model dbt Core 1.12.4 project parsed successfully. Skill validation, dependency consistency, JavaScript syntax, diff checks and 119 local documentation links passed. [Compact test result](test-results.txt).

The machine-readable [phase ledger](progress.json) records checks and remaining gates. The [dbt parse record](dbt-parse.json) describes the separately generated three-layer synthetic Core project. It does not claim connected Snowflake execution.

Use Python 3.12 with the repository's pinned `requirements-dev.txt` for the complete verification lane:

```sh
python -m unittest discover -s tests -v
```

The dependency-light Python 3.9 CI lane explicitly skips optional runtime tests. Its skips do not qualify those capabilities; the pinned lane must run without skips. No real credentials, approval keys or live endpoints are used by these fixtures.

| Scope | Test file(s) | Evidence boundary |
|---|---|---|
| Version migration, structured classifications and source inventory | `test_data_dictionary_v2.py`, `test_metadata_contract.py`, `test_metadata_sources.py` | Supplied evidence contracts, not factual business approval |
| Interview choices and invalidation | `test_metadata_intake.py` | Recorded selections do not confer authority |
| YAML preservation, conflicts, versions and defaults | `test_generate_dbt_docs_yml.py` | Static generation; separate Core parse, native persistence unqualified |
| Six warehouse SQL dialects and local DuckDB comments | `test_metadata_sql.py` | No native cloud connection; local DuckDB is not MotherDuck |
| Metadata SQL through the full lint runner | `test_metadata_lint.py` | All six dialects; exact-file convention exceptions retain raw findings and hashes, without native or human approval claims |
| Coverage, governance, no-op, drift and scale | `test_warehouse_metadata_plan.py` | 27 models, 1,282 model columns, 497 source columns, 1,807 single-statement comment units |
| Expected state, physical union and environment comparison | `test_warehouse_metadata_verification.py` | Supplied observations; authenticated live collector still required |
| Databricks Statement Execution API transport | `test_deployment_metadata_adapter.py` | Recorded synthetic response contracts, not live service execution |
| Signed parent/child phases and failure/recovery | `test_metadata_release.py` | Simulation only; automatic live metadata dispatch blocked |
| Portal, reduced exports, hostile content and tampering | `test_metadata_portal.py`, existing `test_delivery_portal.py` | HTML/JS and ZIP checks; browser visual QA was unavailable |
| Downstream definitions and AI context | `test_metadata_handoff.py` | Actual Omni refresh/import and question accuracy remain separate |
| Optional naming | `test_metadata_naming.py` | Preview only; existing names/aliases/macros preserved |

Independent adversarial review found and prompted regression repairs for wrong physical destinations, parent recovery clearing a child's uncertain-operation lock, altered expected metadata scope, mutable parent artifact bytes, pre-build observations, replaced objects, placeholders hidden by units, and unrelated/stale environment comparisons. The resulting tests reject these cases.

## Remaining gates

1. **Authenticated live drift collection.** Automatic live metadata child dispatch is blocked before mutation. Native read-query generation and deterministic comparison exist; authenticated collection and immediate current-state checks are not integrated. Signed simulation flags do not close this gap. Use the reviewed SQL/operator or independently governed CI handoff.
2. **Live dbt + Snowflake pilot.** Validate actual comments/tags, runtime/edition/permissions, complete native catalogue visibility, source ownership, object replacement and recovery. A-23/A-24 in the requirements plan remain live acceptance obligations.
3. **Each additional warehouse.** Qualify exact runtime, object types, types/identifiers, readback normalization and limitations. No blanket portability or vendor certification is claimed.
4. **Governance and Coalesce.** Definition provisioning, grants, masking/ABAC and propagation are separate authorized work. Native Coalesce node-documentation projection is not implemented; its existing direct-live restriction remains.
5. **Naming and downstream consumers.** Non-Snowflake/layer-domain naming has no apply path. Actual Omni import, curated-description reconciliation, access behavior and representative AI questions need consumer acceptance.
6. **Visual review.** Browser file access was unavailable for this run. DOM/JS safety and package integrity passed; no screenshot-based visual acceptance is claimed.

The original [requirements and acceptance cases](../../docs/plans/15-warehouse-metadata-governance.md) remain available, with the distinction between implemented local behavior, remaining integration work and live qualification. See the [operator guide](../../skills/data-model-accelerator/references/warehouse-metadata.md) for use.
