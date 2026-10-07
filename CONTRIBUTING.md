# Contributing

Use a focused branch and pull request. Keep user-facing behavior, security boundaries, independent expectations and documentation consistent. Public CI uses synthetic inputs and no customer credentials.

## Run checks

Use isolated Python 3.12 for the complete dependency set:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip check
python skills/data-model-accelerator/scripts/bootstrap_hex_schema.py
python -m unittest discover -s tests -v
```

The Hex bootstrap explicitly downloads a checksum-pinned publisher schema; analysis does not fetch it automatically. A lightweight Python 3.9+ run can omit optional dependencies, but its skips are coverage gaps. CI also exercises generated models and rejects skips in the full-dependency lane. See [reproduction commands and limits](docs/qualification.md).

## What belongs in Git

Keep runnable code, user/operator documentation, schema and license provenance, templates, regression tests and the smallest synthetic inputs/independent expectations needed to reproduce behavior. JSON is appropriate when it is a runtime contract, schema, fixture or integrity pin.

Keep generated execution reports, native dbt manifests, logs, databases, delivery ZIPs, temporary agent prompts, one-off audit output and internal implementation plans outside the checkout. Store run evidence in the engagement's governed output location or the relevant CI run. Do not commit customer exports or credentials.

Fixture pins protect reviewed executable inputs before macros or helper code run. When updating a fixture, review the actual changed bytes, preserve unrelated expected results, and update only the affected inventory deliberately. Never derive an independent expected result from the candidate merely to make a check pass.

Historical development records remain in Git history. Current docs should explain how to use or maintain the tool; durable architecture decisions belong in `docs/adr/`.
