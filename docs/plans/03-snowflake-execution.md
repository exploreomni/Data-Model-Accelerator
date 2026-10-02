# Task 3: Real-project dbt execution

Status: implemented; local execution verified, live Snowflake pending.

## Scope

Add a reviewed-project native dbt runner using explicit external profiles, target, allowed development destinations and current project pins. Reuse typed build verification without widening its supported versions. Preserve failed/timeout results; provide commands and clear capability limits.

## Deliverables

Native execution request, isolated copied project, preflight placement checks, original dbt artifacts/logs and typed receipt; no deployment/cutover action.

## Acceptance and verification

Exercise command construction, denied destinations, version/resource incompatibility, changed project, failure and timeout with process doubles. Execute a local dbt adapter smoke when dependencies are available. Live Snowflake acceptance requires the user-selected account/profile.

## Sequence

Begin only after task 2's code and focused checks are complete. Record implementation evidence and limitations below before proceeding.

## Completion evidence

Implemented a pinned reviewed-project runner with explicit external profile/target, destination preflight, isolated copy, original diagnostics and typed evidence verification. Thirteen focused boundary tests pass. A native dbt-core 1.12.4 / DuckDB run built two models, one seed and one test; its complete typed receipt passed verification. Review identified and fixed ambient DBT option/project-flag overrides before completion.

The Snowflake branch is implemented but has not connected to a live account. No customer profile or development destination has been supplied. Unsupported versions/resources and templated profiles fail explicitly; this runner is not a sandbox for arbitrary project code.
