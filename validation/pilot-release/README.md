# Final pilot-release review

Recorded September 25, 2026, on `atx/pilot-release`, based on `7a55138` from `origin/main`. This closes the local implementation and documentation review before a supervised customer pilot. It does not authorize a customer deployment or claim native vendor qualification. [Machine-readable receipt](results.json)

## Validation

| Check | Result |
| --- | --- |
| Full Python 3.12.14 regression environment | **918 tests passed; zero failures, errors or skips** |
| Deployment-focused suite | 98 tests passed, including 13 new regression tests |
| Python 3.9.6 compatibility lane without optional engines | 918 discovered; 581 passed and 337 explicitly skipped |
| Independent adversarial replay | 11 checks passed against the frozen deployment code |
| Guided synthetic walkthrough | All 18 framework/warehouse choices recorded, including conditional and unsupported routes |
| Engineer and reviewer example ZIPs | Integrity verified; nine and seven registered files respectively |
| Source-only delivery ZIP | Integrity verified for 133 files; original SHA-256 preserved |
| Operator guide | Standalone start/answer/resume/status walkthrough ran; answers persisted; source unchanged; missing catalogue remained an evidence gap |
| Packaging and documentation | Skill validator, portal JavaScript syntax, workflow YAML and embedded Python, local links, dependency consistency and whitespace checks passed |

The full environment is defined by the root `requirements-dev.txt`. CI's full-dependency lane fails if any test is skipped. Core-only skips are visible and do not substitute for that lane. GitHub checks are separate evidence tied to the exact PR commit; this receipt records local execution only.

## Independent review repairs

The reviewer reproduced the following boundary failures before the repair, then replayed the same attacks against the final code:

- **Execution identity:** acceptance, reconciliation and recovery retain the original plan, policy, simulation/live mode, target, context and required checks. Resealing an edited plan or signing new evidence cannot weaken checks or turn simulated execution into live acceptance. Rejection leaves the journal unchanged and makes no subsequent native calls. An unchanged valid simulation still completes.
- **Publication destination:** the exact repository, base and head must be provisioned in trusted policy and visible in the review. A warehouse destination alone does not authorize a GitHub destination.
- **Publication content:** prepared categories govern the narrow PR-body exemption. Caller-supplied roles cannot disguise implementation code as documentation. Remote bytes for the complete prepared handoff are checked before any PR write.
- **Coalesce continuation:** direct live submission fails before mutation because automatic status/results cannot yet bind the approved profile domain. Cancellation pins the documented domain and environment. Use a qualified Git/CI/operator handoff until the continuation is implemented and independently qualified.

The independent replay used local fixtures and synthetic signed authority, with no live vendor calls. Its reviewed code hashes are retained in `results.json`; it is a bounded implementation review, not a comprehensive security certification.

## Documentation and deliverable scope

The [README](../../README.md), [how-to guide](../../docs/HOW_TO.md) and [capabilities](../../docs/CAPABILITIES.md) now guide an analytics engineer from intake and raw catalogue through SME decisions, independent benchmarking, model/Omni implementation, selected guided ZIP export and a separately authorized release. Framework, warehouse, semantic engine and host remain independent choices. Platform and parser limits are explicit.

The prior [source-only trial](../no-context-release-candidate/README.md) remains an unchanged historical receipt: 43 dbt models, 105 data tests, 58 documented objects/513 columns, three Omni topics and 905 passing toolkit tests at that earlier snapshot. Its complete model delivery ZIP is included in the repository. This final 918-test release check does not relabel that candidate as having executed in a live Snowflake or Omni tenant.

## Reproduce

From the repository root, in an isolated Python 3.12 environment:

```sh
python -m pip install -r requirements-dev.txt
python -m pip check
python - <<'PY'
import sys
import unittest
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.discover('tests')
)
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
PY
python skills/data-model-accelerator/scripts/run_guided_delivery_demo.py --output /absolute/new-pilot-demo
python skills/data-model-accelerator/scripts/delivery_portal.py verify /absolute/new-pilot-demo/engineer-example.zip
python skills/data-model-accelerator/scripts/delivery_portal.py verify /absolute/new-pilot-demo/reviewer-example.zip
python skills/data-model-accelerator/scripts/delivery_portal.py verify validation/no-context-release-candidate/candidate-delivery.zip
```

Customer acceptance still needs representative source coverage, current catalogue/profiling, SME-approved definitions, target-native execution and permissions, history/incremental/recovery tests where applicable, native Omni/AI behavior and explicit release approval. Those are pilot success criteria, not outcomes claimed by this PR.
