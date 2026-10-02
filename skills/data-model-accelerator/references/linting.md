# Linting and platform validation

Use `scripts/platform_matrix.py` for the selected framework/warehouse, including hosting restrictions, metadata identity, native validation recipes and documented gaps. Select one route, retain the customer's qualified runtime, and include its evidence in the engineering package.

## Static runner

The optional `scripts/requirements-lint.txt` pins SQLFluff 4.3.0. Run it in an isolated environment through `scripts/lint_delivery.py`; the core assessment helpers remain standard-library only. The runner strips inherited credentials, disables ambient configuration, inline overrides and `noqa`, uses the raw templater, rejects unrendered templates, and reconciles native file receipts to the declared inventory. It never imports project code or renders dbt macros. Third-party linter plugins are refused.

The runner uses Snowflake, Databricks, BigQuery, Redshift and ClickHouse dialects; MotherDuck uses the DuckDB dialect for this static lane. Listed grammar support does not prove native compatibility. SQLFluff's default file skips and ignored templated areas require explicit controls and an independent denominator. [Dialects](https://docs.sqlfluff.com/en/stable/reference/dialects.html), [configuration defaults](https://docs.sqlfluff.com/en/stable/configuration/default_configuration.html).

Start with a provisional manifest without executing any project code:

```sh
python skills/data-model-accelerator/scripts/lint_delivery.py \
  --root /absolute/approved-candidate --scaffold \
  --output /absolute/review/lint-manifest.json
```

Review its scope, assign execution units and resolve all reported template-to-rendered mappings before linting. The scaffold cannot prove complete native materialization coverage. Each executable unit appears exactly once; each rendered output names its hashed source templates. For example:

```json
{
  "schema_version": 1,
  "kind": "sql_lint_manifest",
  "expected_execution_units": ["orders"],
  "files": [
    {
      "path": "models/orders.sql",
      "sha256": "REPLACE_WITH_ACTUAL_FILE_SHA256",
      "role": "model_sql",
      "format": "sql",
      "execution_units": ["orders"],
      "source_paths": []
    }
  ]
}
```

The digest placeholder must be replaced before the command will run. The target file is explicit and is bound into the report:

```json
{"framework":"native_sql","warehouse":"snowflake","context_sha256":"REPLACE_WITH_CURRENT_REVIEW_CONTEXT_HASH"}
```

For release integration, use the exact framework, warehouse and context hash of the prepared handoff. Keep the manifest, target and output report outside the candidate root so they do not accidentally become project inputs.

```sh
python skills/data-model-accelerator/scripts/lint_delivery.py \
  --root /absolute/approved-candidate \
  --manifest /absolute/review/lint-manifest.json \
  --target /absolute/review/lint-target.json \
  --python /absolute/trusted-lint-environment/bin/python \
  --output /absolute/review/new-lint-report.json
```

Exit `0` means complete static coverage passed under the declared convention policy; `1` means blocking findings, unused exceptions or incomplete coverage; `2` means invalid input or unavailable runtime. Source files are not modified. A new output path is required. Limits are explicit: oversized, omitted, empty or unsupported inputs cannot silently pass.

## Templates, hooks and configuration

- Plain SQL uses `format: sql`. Rendered SQL uses `format: compiled_sql` and nonempty `source_paths` that name hashed manifest entries.
- Template roles include `dbt_model`, `macro`, `hook_template`, `materialization_template`, `coalesce_node` and `template`. Their format is `jinja`, `yaml` or `json`; they own no execution units. Each must map to a rendered SQL consumer, or coverage remains unsupported.
- SQL roles include `model_sql`, `script_sql`, `generated_ddl`, `generated_dml`, `hook_sql`, `test_sql` and `materialization_sql`. Inventory hooks, materializations and generated statements, not only SELECT models.
- `project_config` and `semantic_config` support basic JSON/YAML structure checks. Duplicate keys, unsafe YAML tags and unresolved aliases cannot pass. This is not native framework or Omni schema validation.

The manifest mapping records declared provenance. It cannot prove that a compiler faithfully produced those SQL bytes; obtain separate framework evidence in the reviewed runtime. Inventory and compare all generated branches/units, including adapter-dispatched macros and hooks. Do not substitute a single rendered query for full materialization coverage.

dbt `parse`, compile and native lint are distinct checks. Compile-time macros can query or mutate the warehouse; do not execute them while advertising offline lint. Native `dbt lint` is documented for v2 and depends on its actual supported runtime; do not replace a customer's runtime merely to gain the command. A v1 templater must be separately qualified, with compilation errors treated as failures. [dbt lint](https://docs.getdbt.com/reference/commands/lint), [dbt compile](https://docs.getdbt.com/reference/commands/compile), [SQLFluff dbt templater](https://docs.sqlfluff.com/en/stable/configuration/templating/dbt.html).

Coalesce graph validation and generated Create/Run SQL are separate scopes. Capture the native output and node/source mappings, then lint the selected dialect. The matrix records version/platform qualifications and native command recipes. Unqualified pairings remain blocked.

## Modeling review and legacy debt

The optional manifest `physical_models` declarations produce review findings for description, grain, keys, lineage, layers and incremental behavior. Redshift distribution/sort choices, ClickHouse engine/order keys and MotherDuck remote identity have platform-specific prompts. These are review findings, not proof of uniqueness, performance, access or business correctness. Existing dictionary/ERD and independent acceptance checks still apply.

The default policy remains strict: all SQLFluff rules run and every finding blocks. Where changing a convention would damage source fidelity or rewrite framework-generated formatting, the manifest may contain an optional `style_exceptions` list:

```json
{
  "style_exceptions": [
    {
      "path": "models/orders.sql",
      "rule": "ST06",
      "reason": "Preserve the field order agreed in the source-to-target contract."
    }
  ]
}
```

Each declaration has exactly `path`, `rule` and a nonempty, single-line `reason`. The path must identify one executable SQL file already in the manifest; no wildcards, directories, source-template paths or configuration files are allowed. The existing file SHA-256 pins the exact affected bytes, and the complete manifest hash pins the declaration. Normalized report declarations include that file hash and a trimmed reason. Reusing an old declaration against changed bytes requires a new manifest and a fresh review of the policy choice.

Only these convention rules can be excepted:

| Rules | Bounded purpose |
| --- | --- |
| `CP02` | Preserve identifier capitalization. |
| `RF04` | Preserve source field names that are keywords. |
| `RF06` | Preserve exact quoted physical identifiers in reviewed generated metadata SQL. |
| `ST06` | Preserve an explicitly selected projection order. |
| `LT01`, `LT02`, `LT05`, `LT13`, `LT15` | Retain framework whitespace, indentation, line length or newline formatting. |

The exception does not configure SQLFluff to skip anything. Every rule still runs; raw error findings, locations and the original failed status remain visible. Separate `style_exception_applications` identify the exact matching findings. The report's `style_exceptions` summary records declarations, file hashes, reasons, applied finding counts, unused declarations and files converted to `checked`. A convention-only file may become `checked` only after a complete SQLFluff receipt with no independent blocker. `checked` with an exception means the declared policy was satisfied, not that the raw findings disappeared.

`PRS`, `LXR`, `TMP`, other rules, runtime/parser/configuration failures, `noqa`, inline settings, unsupported templates, skips and coverage gaps cannot be excepted. Duplicate declarations, unknown paths/rules and empty reasons are invalid. A declaration without an eligible current finding fails as `UNUSED_STYLE_EXCEPTION`, including obsolete rules and exceptions placed on the wrong file. Missing dependencies are never style exceptions.

Report verification repeats the same normalization, rechecks current source and manifest hashes, recomputes the `noqa`/inline/template boundary from source bytes, and rejects inconsistent status conversions, application indices or summaries. It does not execute a report-supplied interpreter or authenticate the report issuer. Reasons are policy explanations, **not human approval records** or proof of SQL semantics, native warehouse correctness, model acceptance or deployment authority. Keep independent framework, warehouse, data and semantic checks intact.

## Bind evidence to deployment

Add this to the ordinary deployment request before `deployment_workflow.py plan`:

```json
{
  "quality": {
    "report_path": "/absolute/review/new-lint-report.json",
    "manifest_path": "/absolute/review/lint-manifest.json"
  }
}
```

The planner verifies current hashes and complete coverage of the prepared implementation inputs. Every subsequent execution step rechecks those bindings. A live deployment approver must also attest the exact `lint_report_sha256` in `claims.preflight`, alongside actual identity, permissions and artifact/commit evidence. Simulation reports never authorize a live release.

The separate deployment review export includes a readable findings guide, selected configuration, manifest, target, sanitized findings and quality evidence. It does not ship private interpreter paths or credentials. The original handoff remains frozen. Package folders organize outputs for the audience; use the package manifest to reconstruct the original candidate-relative paths before rerunning checks.

Programmatic verification is available as `verify_report(report, root, target, manifest, runtime=observed_runtime)`. Obtain the optional runtime from `inspect_runtime(trusted_python)` in the controlled environment; never execute a path supplied by an untrusted report. This verifies content and runtime consistency, not issuer authenticity or native warehouse acceptance.

Native Omni `.view`, `.topic`, `model` and `relationships` files are included in the bounded inventory and scaffolded as YAML semantic configuration. YAML structure checks do not establish Omni parameter validity, field binding, access behavior or query correctness; retain separate semantic validation and native tenant checks.
