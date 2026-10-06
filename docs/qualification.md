# Qualification evidence

Current local scope reviewed October 5, 2026. Evidence is specific to named inputs and runtimes; a source in the specialist roster is not universal parser support. Start with [capabilities](CAPABILITIES.md) for scoping and [the how-to guide](HOW_TO.md) for operation.

## Current release evidence

- [Dedicated Omni Modeler evidence](../validation/omni-modeler/README.md), October 5, 2026: versioned knowledge, real task callback boundary, safe inventory/patches, bounded core/query modeling, change impact, derived AI lineage, repeated evaluation and guided handoff. Native tenant, external host, customer and release qualification remain separate.

- [Omni and sensitive-data repair evidence](../validation/omni-privacy-repair/README.md), October 5, 2026: scope-aware delivery, bounded privacy controls, Looker API4 extraction, Omni model/dashboard adapters, independent parity, access contracts and signed release integration. Two fresh-context synthetic domains pass six independent local scenarios. Native pilots, effective-access collection, live AI answers, SME decisions and remote CI remain pending.

- [Warehouse metadata implementation evidence](../validation/warehouse-metadata-governance/README.md), September 30, 2026: versioned dictionary, dbt YAML preservation, six-warehouse metadata generation, physical coverage/readback, signed release simulations and guided ZIP integrity. No live provider execution; automatic live metadata dispatch remains blocked pending authenticated drift collection.

- [Final pilot-release review](../validation/pilot-release/README.md): final branch validation, independent review repairs, documentation checks and CI requirements. Remote CI status belongs to the exact PR revision.
- [Fresh source-only candidate](../validation/no-context-release-candidate/README.md): 15 pinned CSVs; 43 local dbt models and 105 data tests; 58 documented objects/513 columns; actual Omni YAML local replay; extracted-package reconstruction; 905 passing regression tests at that recorded implementation snapshot.
- [Deployment and platform-quality implementation](../validation/deployment-platform-release/README.md): deployment was validated before lint/platform expansion; earlier combined suite passed 893 tests. Typed native adapters were exercised through local transport fixtures.
- [Guided delivery](../validation/guided-delivery/README.md): persistent discovery, selected audience exports, connected diagrams and prepared handoff behavior. Later trial corrections retain native Omni filenames, complete projections and transparent convention exceptions.

**Remaining customer gates:** representative repository coverage, live catalogue and target execution, effective permissions, incremental/history/load/recovery behavior, native Omni queries and AI answers, SME definitions and release approval. Business SMEs make acceptance achievable; their availability does not itself satisfy those gates. No blanket native provider or cross-host qualification is claimed.

## Earlier source-specific evidence

The following counts are historical results from the original exercises, not the current full regression count.

| Path | Implemented/executed evidence | Still unqualified |
|---|---|---|
| Looker → Snowflake SQL → Omni | Source/target parsing;59 local checks;18 negative controls | Native Looker/Snowflake/Omni; actual customer coverage/security/operations |
| Hex → dbt/Snowflake → Omni | Native v3 schema validation;3 projects + 1 component; 24 cells; 125 local checks; 24 negative controls; 11 documented models / 74 columns | Native Hex/pandas/app behavior, Snowflake execution, Omni execution, production ingestion, human decisions |
| Hex candidate dbt project | Native Snowflake-adapter parse; separate native dbt/DuckDB overlay build of 7 models and 85 tests | Snowflake compile/build and operational acceptance |
| Tableau → dbt/Snowflake → Omni | XML extraction;1 workbook / 3 sheets / 15 calculations / 5 parameters; matching TDS/TWBX;160 local checks / 44 negative controls;10 documented models / 64 columns | Official XSD compilation blocked by missing publisher dependencies; native Tableau/Snowflake/Omni; extracts, relationships/blending, actions and production security/operations |
| Tableau candidate dbt project | Native Snowflake-adapter parse; separate native dbt/DuckDB overlay build of 6 models and all 73 tests | Snowflake compile/build and operational acceptance |
| Power BI → dbt/Snowflake → Omni | PBIP/TMSL/enhanced-PBIR extraction; 10 official schema-valid project/report files; 3 tables / 9 DAX measures / 3 visuals; 212 local checks / 61 negative controls / 22 scenarios; 10 documented models / 64 columns | Native Desktop/TOM/M/DAX, refresh, model security membership, Snowflake/Omni execution, empty KPI/LOD behavior, controls, unsupported formats and operational acceptance |
| Power BI candidate dbt project | Native Snowflake-adapter parse; separate native dbt/DuckDB overlay build of 6 models and all 73 tests | Snowflake compile/build and operational acceptance |
| Existing dbt as source | One independent synthetic retail authoring trial, now a regression; 5 native local models / 52 data tests; 15 integrated checks; 9 documented objects / 68 columns | Unseen customer projects, repeated fresh-agent trials, native Snowflake, business/operational acceptance |
| Coalesce, Snowflake, Sigma as sources | Routing and specialist contracts; assorted detection/handoff tests | Equivalent complete source-specific migration pilots |
| Six warehouse catalogue providers (see [matrix](PLATFORM_MATRIX.md)) | Query templates/contracts; synthetic validation; Hex metadata normalization checked against typed fixture receipts | Actual account retrieval, pagination/visibility and live metadata verification |
| Claude Code, Codex, Gemini, Cortex, Genie hosts | Portable skill and documented host guidance; current development executed in Codex | End-to-end execution qualification on each host/version |
| Automated repository regression | 443 repository tests passed; core-only 143 passed / 300 optional skipped; 14 separate retail author tests; separate source-specific workflows | Remote CI evidence is attached to the tested revision; native platform acceptance remains separate |

Detailed evidence: [Looker](../validation/looker-omni-e2e/README.md), [Hex](../validation/hex-omni-e2e/README.md), [Tableau](../validation/tableau-omni-e2e/README.md). Deployment and model approvals remain separate from package validation. The Tableau workflow is defined separately so the archived Hex workflow hash remains reproducible; remote CI is separate evidence attached to each published revision.

[Power BI evidence](../validation/powerbi-omni-e2e/README.md) has its own workflow. Previous workflow artifacts remain unchanged. Synthetic context and native platform acceptance remain separate across all four pilots.

[Initial dbt qualification](../validation/dbt-flow/README.md) records 23 native local workflow checks, separate typed evidence verification, failed-run/recovery evidence and an independently authored retail trial. Across four fixture baselines, 24 models and 283 dbt data tests execute with the local DuckDB adapter. Explicit dialect overlays and all remaining Snowflake sign-off gates are documented. This does not establish general agent or native target qualification.
