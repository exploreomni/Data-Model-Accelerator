# Linting and platform matrix implementation

Phase 11 passed its regression gate before this work began (840 tests; 18 optional-dependency skips; all 84 deployment tests passed).

## Work order

1. Add a single versioned platform capability matrix separating framework, warehouse, dialect, static lint, native validation and deployment qualification. Add Redshift, ClickHouse and MotherDuck throughout discovery and catalogue context; reject unsupported pairings explicitly.
2. Implement a bounded lint runner with pinned SQLFluff, explicit dialect selection, isolated configuration, exact file/hash coverage, nonzero failures and honest unsupported/template/skip states. Never treat syntax/style as data accuracy or native acceptance.
3. Provide framework/native validation recipes for dbt, Coalesce and all six warehouses. Keep native commands and cost-bearing checks behind the existing authorized runner; never execute user macros while claiming a static lint.
4. Integrate lint evidence into deployment preflight and guided delivery. Update skill routing, operator instructions and CI.
5. Run real dialect fixtures, adversarial coverage cases and the full regression suite; verify the generated package and review any changed UI. Record live-platform coverage gaps without claiming qualification.

## Acceptance

All six destinations can be selected and obtain their own dialect, metadata context and supported validation path. An untested native adapter, empty selection, ignored file, unsupported dbt runtime or unresolved template cannot become a passing release check. Artifacts and reports remain content-bound and no lint result grants deployment authority.

## Progress

- Completed after the deployment gate. Shared matrix drives six warehouse choices, catalogue context, source routing, dialects and explicit framework/hosting restrictions.
- SQLFluff 4.3.0 runs in an isolated static lane with exact execution-unit/file coverage. Manifest scaffolding, template provenance, structured-file checks, runtime/configuration hashes and modeling review findings are implemented.
- Live releases require current bound lint evidence. Separate review exports include selected configuration, manifests, readable findings and four independent quality lanes; existing failed evidence is preserved.
- Final Python 3.12 suite: **893 tests passed, no skips**. Python 3.9 core compatibility: 893 tests, 328 optional-dependency skips, no failures. Real linter suite: 24 tests; release-quality and evidence-preservation integration: 7 tests; portal suite: 53 tests.
- The 18-route guided walkthrough produced verified engineer/reviewer packages. Browser QA covered deployment requests, quality evidence, omission from reduced ZIPs and preservation of failed accuracy results. Skill, JavaScript syntax and whitespace checks passed.
- Coverage limits: native framework/warehouse checks are explicit recipes and typed deployment interfaces, not customer-platform qualification. No live warehouse deployment, remote CI run or external approval issuance occurred. The initial static gate has no style-baseline or exception bypass.
