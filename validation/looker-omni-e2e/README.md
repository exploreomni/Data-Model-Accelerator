# Looker → Snowflake medallion → Omni validation

Synthetic local exercise, September 9, 2026. This folder preserves actual source-specialist evidence, independent QA findings, failed iterations and the final regression replay. Native Looker, Snowflake and Omni services were not used.

**Final result: 59/59 migration checks passed, all 18 negative controls caught, and the latest 143/143 tooling regression tests passed.** Confidence is high for this fixed synthetic case; native runtime behavior remains unverified.

[Final machine-readable report](final/e2e-report.json) · [Report comparisons](final/report-comparisons.json) · [Executed SQL assertions](final/executed-assertions.sql) · [Rendered source/Omni SQL](final/rendered-queries.json) · [Original regression log](regression-tests.txt) · [Latest documentation regression log](documentation-regression-tests.txt).

The unchanged fixture produced 12 invoice facts, 6 customer dimension rows and 9 report scenarios with 17 expected result rows. Tenant A’s September USD total is 6 invoices, net 39900 cents, paid 23000 cents and a 57.6441102757% payment rate. Tenant B, EUR, historical segments, prior-month, zero-net and empty populations are tested separately.

- [Case, model/ERD, test method and runbook](../../skills/data-model-accelerator/references/looker-omni-e2e.md)
- [Original Looker input](../../skills/data-model-accelerator/examples/looker-omni-e2e/input/repo)
- [Generated Snowflake models](../../skills/data-model-accelerator/examples/looker-omni-e2e/target/snowflake)
- [Generated Omni files](../../skills/data-model-accelerator/examples/looker-omni-e2e/target/omni)
- [Source-rule and semantic crosswalk](../../skills/data-model-accelerator/examples/looker-omni-e2e/target/semantic-assessment.md)
- [Complete data dictionary](../../skills/data-model-accelerator/examples/looker-omni-e2e/documentation/data-dictionary.md)
- [Bronze documentation](../../skills/data-model-accelerator/examples/looker-omni-e2e/documentation/bronze.md), [silver documentation](../../skills/data-model-accelerator/examples/looker-omni-e2e/documentation/silver.md), [gold documentation](../../skills/data-model-accelerator/examples/looker-omni-e2e/documentation/gold.md) and [layer ERDs](../../skills/data-model-accelerator/examples/looker-omni-e2e/documentation/model-erd.md)
- [Frozen independent oracle notes](../../skills/data-model-accelerator/examples/looker-omni-e2e/expected/oracle-notes.md)
- [Initial independent QA](qa-initial.md) and [12-check closure](qa-closure.md)
- [Review gates](review-gates.json) and [versioned review manifest](../../looker-omni-review-package.json)

## Iteration evidence

`iterations/run1.json` stopped after 26 passing assertions because the local semantic compiler rejected an empty half-open date interval. Equal endpoints now select no rows; reversed ranges still fail. The proposed Omni zero-total policy remains explicit and is not represented as verified native Looker behavior.

`iterations/run2.json` executed 52 checks: 51 passed and full-fixture replay failed. Appending history snapshots again produced 45 projected invoice rows instead of 12. Silver history now collapses exact whole-record repetitions; conflicting effective intervals remain invalid. The original Looker code and frozen expected rows were preserved.

Independent QA reproduced a local SQL file-read escape and acceptance of a changed Looker connection identity. It also confirmed that explicit query overrides masked changed dashboard defaults. Dedicated guards and negative controls address these findings; the final evidence records their observed results.

The source specialist parsed 4 assets into 50 objects and 48 rules. Its historical handoff deliberately retains 6 unresolved references and 10 declared gaps, including external connection/user-attribute configuration and runtime behavior. The integrated local run separately binds the four physical inputs to synthetic catalogue evidence. It does not convert unknown live configuration into verified native context.

The archived original source run refers to its original temporary case path. `current-specialist-run` refreshes extraction against the byte-identical durable packaged repository; the two snapshots have different paths and their own hashes. A regression replay inventories source files again but does not re-execute the full multi-agent authoring workflow.

## Acceptance boundary

The independent expected data was calculated from raw records and the scenario before the candidate was reviewed. Direct recomputation retained all 12 rows unchanged and passed arithmetic, source-order, negative-input and local persona controls. This is a synthetic oracle, not a SaaS-certified report or business approval.

The warehouse is a full-rebuild candidate. Native SQL compilation, development-warehouse execution, real replication/incremental behavior, performance/cost, actual Omni model queries and access enforcement, rendered dashboards and human approval remain open. The four native Omni model files are distinct from the companion report-context JSON; no native Omni dashboard was created or published.

Both actionable QA findings are closed at the tested local boundary. The review checker intentionally keeps the package incomplete because native compilation/execution/operations, source runtime configuration and approval remain unresolved. Its standard `logic` category includes the runner’s more specific `report_context` checks; the manifest preserves both category labels. Successful local tests do not waive these evidence gaps.

The documentation deliverables cover 10 models and 79 columns (34 bronze, 25 silver, 20 gold). Their inventory was compared with all tables/columns actually built by the local simulator. The new completeness checks and [independent documentation review](documentation-review.md) cover required readable output, version/coverage integrity and sampled semantic accuracy. Ownership, SLAs, native constraints and production operations remain explicitly unknown where evidence was not supplied.
