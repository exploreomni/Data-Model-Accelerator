# Validate the selected delivery

The accelerator now runs SQLFluff against the selected warehouse dialect with explicit file and execution-unit coverage. The [operator guide](../skills/data-model-accelerator/references/linting.md) contains the manifest contract, commands, template workflow and release integration. The [platform matrix](PLATFORM_MATRIX.md) supplies separate framework and native validation recipes.

The guided review keeps four lanes independent:

| Lane | Evidence required |
|---|---|
| Code conventions | Current lint/configuration results, exact hashes and complete coverage |
| Project validity | The selected framework's validation in its qualified runtime |
| Warehouse validation | Native checks against the actual destination, with statement coverage |
| Data accuracy | Independent grain, fanout, reconciliation, metrics, access and semantic tests |

No successful lint result fills the other lanes. Missing, skipped and unsupported checks remain visible. The real integration tests include a syntactically clean model that returns the wrong value against a frozen independent expectation.

Fix authored style issues first. When source names, projection order or framework formatting must be preserved, the manifest can record a narrow exact-file/rule/reason exception bound to the file hash. All rules still run; raw findings and exception counts remain visible in the report and guided review. Unknown, unused or forged exceptions fail validation. Parser, coverage, runtime and data failures cannot be waived this way. A reported policy pass is not necessarily a zero-finding result.

Native Omni `.view`, `.topic`, `model` and `relationships` files belong in the inspected inventory. The extensionless `model` file carries model-level AI context and must not disappear from lint or packaging merely because it has no YAML suffix.

Live deployment requires current lint evidence bound into its exact release plan. An existing report cannot be reused after its candidate, manifest, configuration, target or context changes. External preflight and approval remain required; a self-consistent JSON report is not authenticated execution evidence.

Install the optional checks in a separate Python 3.12 environment, then run:

```sh
python -m pip install -r skills/data-model-accelerator/scripts/requirements-lint.txt -r skills/data-model-accelerator/scripts/requirements-deployment.txt
python -m unittest discover -s tests -p 'test_lint*.py' -v
python -m unittest discover -s tests -p 'test_release_quality.py' -v
```

These commands test local dialect and release contracts. They do not connect to a warehouse or qualify its native behavior.
