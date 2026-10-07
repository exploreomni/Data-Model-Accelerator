# Qualification and reproduction

Use [capabilities](CAPABILITIES.md) and the [platform matrix](PLATFORM_MATRIX.md) to scope an engagement. The [GitHub checks](https://github.com/exploreomni/Data-Model-Accelerator/actions) show results for exact commits; test counts are not a percentage of customer migration accuracy.

## What is tested

| Area | Reproducible coverage | Remaining acceptance |
| --- | --- | --- |
| Source recovery | Synthetic Looker, Hex, Tableau and Power BI parsing, source identifiers, filters, bounded expression behavior and negative controls | Representative customer exports, unsupported formats and native source behavior |
| dbt refactoring | Reviewed billing, retail and rental fixtures; native dbt/DuckDB builds, independent expected rows, fanout, replay, late changes, tombstones and recovery checks | Actual target warehouse execution, scale, account permissions and operations |
| Omni Modeler | Authored/effective inventory, scoped edits, supported core/query views, dependency impact, AI lineage, repeated answer cases and guided delivery | Native Omni compilation, query/dashboard parity, live AI answers and effective access |
| Metadata | Versioned dictionaries, dbt YAML preservation, six warehouse comment/tag routes and readback contracts | Authenticated native drift collection and live provider execution |
| Deployment and privacy | Signed authority contracts, version binding, disclosure checks, simulated native transports and blocked unsafe actions | Provisioned identities, live target behavior and customer approval |
| Agent hosts | Portable instructions, explicit callbacks and local installation checks | End-to-end qualification of each host/version and its actual adapters |

Tests retain independent expected values and deliberate defect cases. Generated runs are written outside the checkout. Historical reports and implementation plans are available in [the pre-cleanup Git snapshot](https://github.com/exploreomni/Data-Model-Accelerator/tree/3c3b4d3bcf9f0e19c65e7494aa421c55f70e13ec/validation); they describe their original inputs and runtimes, not the current commit or a customer's acceptance.

## Reproduce locally

Install the pinned optional dependencies and publisher schema using the [contributor setup](../CONTRIBUTING.md#run-checks). Every command below requires a new output directory outside the skill. No customer warehouse credentials are required.

```sh
# Complete regression suite.
python -m unittest discover -s tests -v

# Source-specific parsing and semantic simulations.
python skills/data-model-accelerator/scripts/run_looker_omni_e2e.py --output /absolute/new-looker-run
python skills/data-model-accelerator/scripts/run_hex_omni_e2e.py --output /absolute/new-hex-run
python skills/data-model-accelerator/scripts/run_tableau_omni_e2e.py --output /absolute/new-tableau-run
python skills/data-model-accelerator/scripts/run_powerbi_omni_e2e.py --output /absolute/new-powerbi-run

# Actual local dbt builds, independent holdout and refactoring checks.
python skills/data-model-accelerator/scripts/run_dbt_local_qualification.py --cases hex tableau powerbi --output /absolute/new-dbt-run
python skills/data-model-accelerator/scripts/run_dbt_holdout.py --output /absolute/new-retail-run
python skills/data-model-accelerator/scripts/run_refactor_qualification.py --output /absolute/new-rental-run

# Two synthetic Omni onboarding exercises and guided ZIPs.
python tests/run_omni_operator.py --repo . --output /absolute/new-omni-run
```

The source-specific and Omni exercises use bounded local interpreters; they are not native Looker, Hex, Tableau, Power BI or Omni runtimes. The dbt exercises execute with DuckDB and explicit dialect overlays. A Snowflake adapter parse does not establish execution in Snowflake. Replaying a frozen agent-authored case does not constitute a fresh blind evaluation or real SME approval.

The full-dependency CI lane rejects skipped tests. Core-only runs can skip optional engines and must report those gaps. Each run creates fresh evidence; a fixture hash establishes byte integrity, not execution, identity or permission.

## Customer acceptance remains separate

Before promotion, establish representative source coverage, current warehouse catalogue evidence, target compilation and execution, independently reconciled outputs, allowed and denied access personas, history/incremental/recovery behavior, native Omni behavior, SME definitions and approval for the exact release. Coalesce, generic SQL and Sigma discovery routes do not imply equivalent complete migration pilots. No blanket provider or cross-host qualification is claimed.
