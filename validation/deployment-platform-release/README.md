# Deployment and platform-quality validation

Recorded September 24, 2026 (America/Chicago). These are local development results, not customer acceptance or remote CI results.

The implementation followed the requested order: deployment was implemented and independently reviewed, then passed a regression gate of 840 tests (18 optional-dependency skips; all 84 deployment-specific tests passed). Only then did linting and platform expansion begin.

The final combined suite passed **893 tests with no skips** using Python 3.12.14, the pinned deployment and SQLFluff dependencies, and the repository's pinned local dbt/DuckDB, Hex and Tableau exercise dependencies. Python 3.9 compatibility also passed: 893 tests, 328 optional-dependency skips.

## Evidence exercised

- Real signed simulation flows across a prepared handoff, deployment plan, native transport fixtures, durable receipt, independent acceptance and guided ZIP export. Native requests are typed for eleven routes; fixtures do not qualify those vendors.
- Tampered/expired/wrong-purpose approvals, duplicate signing-key encodings, source/configuration drift, unselected macro publication drift, uncertain submission, repeated polling, recovery and conflicting runs.
- Real SQLFluff 4.3.0 positive and negative fixtures for all six dialects. The 24 lint tests include hidden/oversized/empty files, config suppression, compiled macros/hooks, structured-file failures, incomplete native tool output, time limits and drift.
- Seven release-quality integration tests, including lint-clean wrong output against a frozen independent expectation and preservation of existing failed accuracy/project/warehouse/static checks in the exported ZIP.
- Fifty-three portal tests plus actual browser checks for plan requests, selected evidence and reduced ZIPs. A missing-plan JavaScript guard and cross-lane evidence overwrite were repaired and regression-tested.
- Eighteen framework/warehouse choices in the guided demo; unsupported Coalesce combinations remain blocked. Engineer and reviewer ZIPs passed integrity verification. New Redshift, ClickHouse and MotherDuck catalogue templates passed static SQLFluff parsing.
- Skill validation, Python 3.9 syntax for the new platform modules, JavaScript syntax, local documentation links and whitespace checks.

## Reproduce

Use a separate Python 3.12 environment, then install these repository requirements:

```sh
python -m pip install \
  -r skills/data-model-accelerator/scripts/requirements-deployment.txt \
  -r skills/data-model-accelerator/scripts/requirements-lint.txt \
  -r skills/data-model-accelerator/scripts/requirements-dbt-qualification.txt \
  -r skills/data-model-accelerator/scripts/requirements-tableau-e2e.txt
python -m unittest discover -s tests -q
python skills/data-model-accelerator/scripts/run_guided_delivery_demo.py --output /absolute/new-guided-demo
python skills/data-model-accelerator/scripts/delivery_portal.py verify /absolute/new-guided-demo/engineer-example.zip
```

The new CI lanes define deployment and lint contract checks; no remote run is claimed here. Actual warehouse identity, permissions, native schema/SQL acceptance, execution cost, recovery behavior, consumer accuracy and institutional signing services still require customer-specific qualification. Local HMAC journals do not protect against restoring an entire prior state directory by the trusted runner principal. The full process-kill/crash-cut durability matrix is not qualified.
