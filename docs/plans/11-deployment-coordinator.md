# Deployment coordinator implementation

Implement this phase and validate it before starting phase 12 (linting and platform matrix), as requested. The source specification is the September 24 deployment research; this plan records the concrete repository work rather than a promise of tenant acceptance.

## Scope

- A separate deployment lifecycle bound to a prepared handoff, immutable artifact bytes, source/catalogue context, selected destination and an exact release plan.
- External trusted-runner configuration, authenticated approval receipts, expiry/revocation and a durable execution journal. Offline HTML requests and claimed approval JSON confer no authority.
- Native adapter operations for customer Git/CI, dbt jobs, Coalesce, Snowflake, Databricks, BigQuery/Dataform, Redshift, ClickHouse and MotherDuck. Preserve provider-specific statuses, identity, retries and recovery limitations.
- Publish-only, development execution and separately qualified promotion; consumer validation and scheduled operation have explicit scopes. No automatic merge, deployment or source retirement while implementing the accelerator.
- Guided review/request UI, selected package contents, operator instructions and a reproducible local exercise.

## Implementation sequence

1. Inspect existing integrity, review and execution contracts and run the baseline suite.
2. Add coordinator contracts and external runner trust boundaries; implement native operation adapters and offline review integration in parallel.
3. Integrate version/context drift checks, signed authority and run receipts, conflicting-run locks, partial/unknown execution handling and post-execution acceptance gates.
4. Exercise valid publication/development flows with controlled process/transport doubles; challenge forged approvals, changed content/targets, failed/partial results, uncertain submission and recovery.
5. Run focused tests, the full regression suite and guided artifact checks. Obtain an independent review. Record exact results and live-platform coverage gaps.
6. Only after this milestone passes, write and implement the linting/platform expansion plan.

## Acceptance and limits

Passing local checks must establish observable coordinator behavior and native request/response contracts, not claim live credentials, vendor entitlement, production qualification or human model acceptance. Real deployments require the selected customer's configured runner, actual approval and native qualification evidence. Preserve all existing guided-workflow authority boundaries and read-only source handling.

## Progress

- Completed before phase 12 began. Baseline: 748 tests, 307 optional-dependency skips.
- Deployment gate: 840 tests, 18 optional-dependency skips, no failures on Python 3.12 with pinned deployment/Hex dependencies; all 84 deployment-specific tests passed. The deployment tests also passed under optimized Python 3.9.
- Independent review repaired strict-version parsing, duplicate signing-key encodings, full prepared-file publication checks and bundle completion acceptance. Browser QA verified requests, selected evidence, separate review ZIP and blocked repeat submissions.
- Live customer tenants, institutional approval issuance and the full process-kill durability matrix were not qualified. No remote deployment or publication performed.
