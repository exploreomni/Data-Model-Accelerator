# Initial dbt flow qualification

September 11, 2026. **Local engineering qualification passes. Snowflake sign-off
and human acceptance remain open.** No warehouse connection or dedicated test
database/schema was supplied for this run. Nothing was deployed or merged.

The scoped implementation generates reviewable dbt models with complete model
documentation, uses native local dbt to build/test candidates, checks the actual
build evidence, and keeps report context downstream. These results support a
supervised development pilot; they do not qualify arbitrary customer projects,
production scale, incremental materializations or other agent hosts.

## Executed evidence

| Test | Result | Evidence |
|---|---|---|
| Existing Hex candidate | 7 models and 85 dbt data tests passed | [Native baseline](native/hex/summary.json) |
| Existing Tableau candidate | 6 models and 73 dbt data tests passed | [Native baseline](native/tableau/summary.json) |
| Existing Power BI candidate | 6 models and 73 dbt data tests passed | [Native baseline](native/powerbi/summary.json) |
| Native local workflow | 23/23 checks: complete builds, independent gold rows, schema isolation, documented columns, replay, late correction, deletion, rejected conflicts/schema drift, recovery | [Results](native/report.json) |
| Independent retail migration | 15/15 checks, including a relocated native build of 5 models and 52 data tests; 8 valid oracle scenarios/mutations and 5 intended rejections | [Results](retail/report.json) |
| Retail author tests | 14/14, including removed tenant join and double-discount controls | [Test output](retail/author-tests.txt) |
| Final validator hardening | 6/6 focused guard checks; complete 15/15 retail replay with Python optimization enabled | [Guard checks](retail/guard-hardening.json), [replay](retail/report.json) |
| Repository regression | 443/443 passed with all optional dependencies installed | [Test output](regression-tests.txt) |
| Core-only installation | 143 passed; 300 optional tests skipped | [Test output](core-regression-tests.txt) |
| Native evidence relocation | All 186 archived files verified; 8 successful build receipts accepted and 2 intentionally failed build receipts rejected after relocation | [Relocation check](native/relocation-verification.json) |
| Previous pilot artifacts | All 398 hashes across four previous review packages unchanged | [Integrity check](prior-artifact-integrity.json) |

Native execution here means **dbt Core 1.12.4 with dbt-duckdb 1.11.0 and DuckDB
1.5.5**. The three previous Snowflake candidates ran through disclosed
NUMBER-to-DECIMAL and ISO-date-format substitutions in isolated copies. The
retail candidate uses portable reviewed SQL. No native Snowflake or Omni
execution is represented by these results. Baseline counts above describe four
fixture projects, not four production migrations or unique business entities.

All gold invoice rows were independently reconciled; Hex's second gold fact was
also compared across all 10 customer-month rows and its derived key/balance.
Actual local objects match documentation for the three previous candidates
(31 objects/202 columns) and retail (9 objects/68 columns). This is structural
agreement; model meaning, ownership and business acceptance remain review work.

## What testing changed

- **Report placement:** the retail author's first candidate materialized a
  tenant/date/status-filtered report view in dbt. Numeric checks passed, but
  architecture review caught the wrong placement. The corrected project has five
  enabled warehouse models; the report is a separately compiled analysis with
  an Omni handoff contract. The initial candidate is retained as failed review
  evidence and is not counted as a clean first pass.
- **Actual dbt coverage:** parse-only evidence became complete native local
  builds. The Hex monthly fact exposed a missing local date-format adaptation;
  that overlay was fixed without editing the original candidate or oracle.
- **Independent comparison:** the Hex oracle calls its date field `month` and
  omits a derived display key. The runner now records an explicit field mapping
  and checks the key's stated formula, rather than ignoring extra fields.
- **Evidence association:** a new typed verifier rejects mismatched invocations,
  changed files, partial/empty/selected builds, missing results, warnings/skips,
  nonzero failures and unqualified artifact versions. Tests account for dbt's
  narrowly identified runtime test-wrapper dependencies. A supplied receipt is
  still self-attested; this verifier does not authenticate an execution or user.
- **Clean checkout behavior:** the retail replay exposed hardcoded machine paths
  and assumptions that runtime/evidence folders already existed. Those were
  corrected, then the relocated build and author tests passed.
- **Unconditional validation:** final review found two assertion-based placement
  and parity checks that Python optimization could remove. Explicit errors now
  enforce both checks in either mode. Six focused checks and a complete native
  retail replay with `PYTHONOPTIMIZE=1` passed. Earlier successful native evidence
  remains intact; the final replay has its own [archive](retail/optimized-native.tar.gz)
  and [hash index](retail/optimized-archive-index.json).
- **Failure evidence:** rejected source-version conflicts and missing raw columns
  produce actual failing dbt results, followed by a successful full rebuild.
  Partial timeout output is retained. Failed runs are kept in [iterations](iterations).

## Independence and limits of the retail trial

A source/oracle specialist prepared an unfamiliar retail fulfillment/returns
domain from four synthetic raw tables and an existing dbt report project. A
separate author received the source, catalogue and a defined output/behavior
contract, while expected values remained withheld. The author reused two correct
staging models; root compared full results with the independent frozen oracle.
Root performed placement review and subsequent packaging fixes.

This was one internal authoring trial using existing specialist contexts. It was
not an unseen customer repository, a context-free repeated benchmark, a native
Snowflake source baseline or a demonstration of a general compiler. It is now a
published regression fixture; rerunning it does not constitute another blind
evaluation. Agent latency, token cost and multi-run decision stability were not
qualified. The expected results and input stayed unchanged during corrections.

## Reproduce and review

From the repository root, use a fresh Python 3.12 environment:

```sh
python -m pip install -r skills/data-model-accelerator/scripts/requirements-powerbi-e2e.txt -r skills/data-model-accelerator/scripts/requirements-dbt-qualification.txt
python -m pip check
python -m unittest discover -s tests -v
python -m unittest discover -s skills/data-model-accelerator/examples/dbt-retail-holdout/candidate -p test_evaluator.py -v
python skills/data-model-accelerator/scripts/run_dbt_local_qualification.py --cases hex tableau powerbi --output /absolute/new/native-dbt
python skills/data-model-accelerator/scripts/run_dbt_holdout.py --output /absolute/new/retail-dbt
```

The [native archive](native/native-details.tar.gz) retains original manifests,
run-results, preflight snapshots, raw snapshots, executed project copies, profiles
containing synthetic values, stdout/stderr and receipts. Its
[index](native/archive-index.json) binds every member by hash. Extract to a new
directory to inspect it. A receipt can be verified against its relocated project
with `verify_dbt_evidence.py <receipt> --project-root <extracted case/project>`.
The [qualification guide](../../skills/data-model-accelerator/references/dbt-qualification.md)
describes the full receipt and scope contract.

The retail deliverable includes [assessment](../../skills/data-model-accelerator/examples/dbt-retail-holdout/candidate/assessment.md),
[ERD](../../skills/data-model-accelerator/examples/dbt-retail-holdout/candidate/documentation/model-erd.md),
[dictionary](../../skills/data-model-accelerator/examples/dbt-retail-holdout/candidate/documentation/data-dictionary.md),
[bronze](../../skills/data-model-accelerator/examples/dbt-retail-holdout/candidate/documentation/bronze.md),
[silver](../../skills/data-model-accelerator/examples/dbt-retail-holdout/candidate/documentation/silver.md)
and [gold](../../skills/data-model-accelerator/examples/dbt-retail-holdout/candidate/documentation/gold.md) documentation.

## Remaining sign-off gates

1. Select the approved Snowflake development profile/connection, role, warehouse
   and dedicated database/schema. Collect and verify the scoped real raw catalogue.
2. Run the exact reviewed dbt candidate on Snowflake and independently reconcile
   aligned input/results, including rejected inputs and recovery. Establish real
   permission enforcement and operating limits for the selected workload.
3. Record business and operational acceptance of the exact model, documentation,
   deployment diff and rollback procedure. If source BI or Omni is in the release
   scope, capture their native behavior/security acceptance separately.

The requested environment details remain pending. No human approval, deployment,
source retirement, production rollback or merge is inferred from passing tests.
