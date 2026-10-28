# Qualification and reproduction

Use [capabilities](CAPABILITIES.md) and the [platform matrix](PLATFORM_MATRIX.md) to scope an engagement. The [GitHub checks](https://github.com/exploreomni/Data-Model-Accelerator/actions) show results for exact commits; test counts are not a percentage of customer migration accuracy.

## What is tested

| Area | Reproducible coverage | Remaining acceptance |
| --- | --- | --- |
| Source recovery | Synthetic Looker, Hex, Tableau and Power BI parsing, source identifiers, filters, bounded expression behavior and negative controls | Representative customer exports, unsupported formats and native source behavior |
| Offline source adapters | Seventeen tool-specific format contracts, native identity/expression evidence, malformed-input controls, provenance and coordinator handoffs | Only declared subsets of supplied exports; live acquisition, full native semantics and independent export completeness remain unqualified |
| Specialist interpretation | Seventeen pinned profiles, role-alias compatibility, unchanged legacy routes, bounded/scanned packets and an independent 17-case decision corpus with adversarial scorer tests | CI does not invoke LLMs; fresh blind host runs, free-text reasoning, native behavior and customer acceptance require separate evidence |
| dbt refactoring | Reviewed billing, retail and rental fixtures; native dbt/DuckDB builds, independent expected rows, fanout, replay, late changes, tombstones and recovery checks | Actual target warehouse execution, scale, account permissions and operations |
| dbt distributions | Preserved Core 1.12.4 evidence; separate dbt and dbt OSS 2.0.8 executable identity, isolated local builds, complete runnable coverage and deliberate result failures | Other versions, authenticated strict analysis, cloud execution and advanced feature combinations |
| dbt v2 metadata and lint | Real v1 Information Schema exports, enabled error-level checks with missing-description/owner controls, and full dbt native lint with clean/violation controls | Customer packages and project configuration, warehouse-derived types/lineage and live metadata readback; native lint is unavailable in dbt OSS |
| Omni Modeler | Authored/effective inventory, scoped edits, supported core/query views, dependency impact, AI lineage, repeated answer cases and guided delivery | Native Omni compilation, query/dashboard parity, live AI answers and effective access |
| Metadata | Versioned dictionaries, dbt YAML preservation, six warehouse comment/tag routes and readback contracts | Authenticated native drift collection and live provider execution |
| Deployment and privacy | Signed authority contracts, version binding, disclosure checks, simulated native transports and blocked unsafe actions | Provisioned identities, live target behavior and customer approval |
| Scoped review additions | Canonical pipeline/topic projections, safe DOM interactions, version-bound feedback, source-qualified sensitive-field treatment and security-aware topic recommendations | Browser visual acceptance, effective native access and privacy approval |
| Optional standards and SQL rules | Domain/context scope rejection, unchanged-rule reuse, stale-preview detection, dialect-aware authoring findings and dependency-byte invalidation | Imported business classifications, supplied metadata and static SQL contracts remain evidence to review, not native or business acceptance |
| Agent hosts | Portable instructions, explicit callbacks and local installation checks | End-to-end qualification of each host/version and its actual adapters |

Tests retain independent expected values and deliberate defect cases. Generated runs are written outside the checkout. Historical reports and implementation plans are available in [the pre-cleanup Git snapshot](https://github.com/exploreomni/Data-Model-Accelerator/tree/3c3b4d3bcf9f0e19c65e7494aa421c55f70e13ec/validation); they describe their original inputs and runtimes, not the current commit or a customer's acceptance.

## Reproduce locally

Install the pinned optional dependencies and publisher schema using the [contributor setup](../CONTRIBUTING.md#run-checks). Every command below requires a new output directory outside the skill. No customer warehouse credentials are required.

```sh
# Complete regression suite.
python -m unittest discover -s tests -v

# Bounded offline adapters and existing specialist handoffs.
python -m unittest discover -s tests -p 'test_source_*.py' -v
python -m unittest discover -s tests -p 'test_specialist*.py' -v
python -m unittest discover -s tests -p 'test_agent_context.py' -v

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

### Separate dbt v2 and OSS qualification

Use separate environments from the pinned Core lane. Install the selected
`requirements-dbt-v2.txt` or `requirements-dbt-oss.txt` from the skill's scripts
directory into a fresh virtual environment. Supply that environment's exact
`dbt` entrypoint and the preinstalled driver matching `dbt_runtime.driver_contract()`.
The [qualification workflow](../.github/workflows/dbt-qualification.yml) shows the
explicit checksum-checked driver provisioning step. The runners never install,
download a driver, log in or modify an existing project.

```sh
# Repeat with dbt_oss and its own isolated environment/output directories.
/absolute/runtime/bin/python skills/data-model-accelerator/scripts/run_dbt_runtime_qualification.py \
  --distribution dbt --dbt /absolute/runtime/bin/dbt \
  --driver /absolute/pinned-duckdb-driver --output /absolute/new-runtime-evidence --execute

/absolute/runtime/bin/python skills/data-model-accelerator/scripts/run_dbt_feature_qualification.py \
  --distribution dbt --dbt /absolute/runtime/bin/dbt \
  --driver /absolute/pinned-duckdb-driver --output /absolute/new-feature-evidence --execute
```

Without `--execute`, neither command probes the runtime or writes files: the
runtime qualifier refuses execution, and the feature qualifier returns a plan.
Runtime qualification requires both the independently expected
result and the deliberate wrong-result case. Feature qualification verifies the
exact enabled checks and resource counts, passing and failing metadata checks,
actual Parquet exports and unchanged inputs. Full dbt additionally requires both
clean and violating lint results: an exit code of zero alone cannot pass lint.
dbt OSS records native lint as unsupported without invoking it.

Native execution was verified on macOS arm64 for both pinned 2.0.8 distributions.
The Linux x86_64 CI lanes are configured separately; inspect the exact commit's
checks for their execution status. This local evidence does not qualify strict
analysis, dbt State, experimental features, MotherDuck or any cloud warehouse.

The source-specific and Omni exercises use bounded local interpreters; they are not native Looker, Hex, Tableau, Power BI or Omni runtimes. The dbt exercises execute with DuckDB and explicit dialect overlays. A Snowflake adapter parse does not establish execution in Snowflake. Replaying a frozen agent-authored case does not constitute a fresh blind evaluation or real SME approval.

The full-dependency CI lane rejects skipped tests. Core-only runs can skip optional engines and must report those gaps. Each run creates fresh evidence; a fixture hash establishes byte integrity, not execution, identity or permission.

For a fresh interpretation check, supply only the public fields of each case in
`tests/fixtures/specialist_interpretation_cases.json` and its matching profile to
a bounded worker. Keep `expected` private to the independent assessor. Use
`score_answer` in `tests/test_specialist_interpretation_benchmark.py`, then review
the rationale and context requests against original evidence. Record case/profile
hashes and the actual host run outside the checkout. Correct only affected
profiles and rerun changed cases plus dependencies; do not change expectations
to match an agent's answer. This tests interpretation, not vendor execution or
all-host isolation.

## Customer acceptance remains separate

Before promotion, establish representative source coverage, current warehouse catalogue evidence, target compilation and execution, independently reconciled outputs, allowed and denied access personas, history/incremental/recovery behavior, native Omni behavior, SME definitions and approval for the exact release. Coalesce, generic SQL and Sigma discovery routes do not imply equivalent complete migration pilots. No blanket provider or cross-host qualification is claimed.
