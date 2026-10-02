# Promotion handoff status

Local replay: run `skills/data-model-accelerator/scripts/run_looker_omni_e2e.py --output /absolute/new-output`. Review the complete result, native-runtime boundaries, exact artifact hashes and QA closure. No credentials or external connection are used.

For authorized development validation, follow the seven-step [development and promotion runbook](../../skills/data-model-accelerator/references/looker-omni-e2e.md#development-and-promotion-runbook). Remap namespaces and inspect full-rebuild overwrite effects before running SQL. Implement operational source-contract tests, native warehouse tests and real semantic persona tests. The example does not deploy incremental refresh or rollback automation.

Production promotion is pending native validation, resolved source/runtime gaps, an accepted business definition, ownership, an exact-version human approval and separately authorized execution. No cutover, source retirement or publication occurred. Keep existing reports available through a future shadow comparison and define recoverable previous versions before cutover.
