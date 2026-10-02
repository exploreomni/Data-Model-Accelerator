# Independent QA closure — September 9, 2026

**Both reported QA findings are closed at the tested local execution/binding boundary.** Twelve focused checks passed using `/private/tmp/dma-e2e-env/bin/python`; no broad suite was repeated. Tests used the packaged `skills/data-model-accelerator/examples/looker-omni-e2e` case and temporary copies. The raw fixture and frozen independent oracle were not edited.

Reviewed `scripts/e2e_warehouse.py` SHA-256: `c036bec8e1b50fdf7faf5773ddd3c37ec5557e5a387fc1c08ba62118d25e4a61`. This hash was unchanged before and after the probes.

| Focused check | Observed result |
| --- | --- |
| Replace the existing, allowed `FCT_INVOICES` target query with `SELECT * FROM READ_CSV('<outside-case sentinel.csv>')` | Rejected: `FixtureContractError: SQL function is outside the fixture subset: ReadCSV`. This exercises an allowed target name, so rejection does not depend on introducing an unknown output object. |
| Query the harmless outside-case sentinel through the returned DuckDB connection directly | Rejected with `PermissionException`: file system operations are disabled by configuration. The sentinel was not returned. |
| Inspect returned connection settings | `enable_external_access`, `autoinstall_known_extensions`, and `autoload_known_extensions` all `false`. |
| Change the Looker connection and call `load_source` | Rejected: connection must match the fixed `synthetic_billing_snowflake` binding. |
| Change the Looker connection and call `build` directly | Rejected by the same binding check before warehouse model execution. |
| Change catalogue `platform_instance` to another account | `catalogue_context` rejected the mismatch with the fixed synthetic Looker connection binding. |
| Change Omni default currency from USD to EUR | `report_contract`/`assert_contract` rejected the changed report behavior. |
| Change Omni default dates from September to August | `report_contract`/`assert_contract` rejected the changed report behavior. |
| Build the unchanged baseline | All 12 projected gold rows matched the frozen independent oracle, including every compared field. |
| Append the entire raw fixture again and rebuild silver/gold | All 12 projected gold rows still matched the frozen independent oracle. |
| Validate exact repeated customer-history payloads | Accepted as replay; four repeated history rows identified. |
| Add a differing segment on an overlapping history interval | Rejected: `FixtureContractError: Overlapping customer history`. |

The external-read fix combines the positive SQL/function/relation checks (`e2e_warehouse.py:268`) with disabled connection capabilities (`e2e_warehouse.py:373`). The source identity fix is enforced by `load_source` (`e2e_warehouse.py:57`), `catalogue_context` (`e2e_warehouse.py:161`), and the direct `build` path (`e2e_warehouse.py:366`). The source compiler's ability to render SQL alone is not treated as execution or a successful physical binding.

No residual blocker was found in these focused closure paths. This is evidence for the bounded synthetic local harness, not a security sandbox for arbitrary customer SQL/Python, universal source-parser completeness, native Snowflake/Omni behavior, deployed tenant authorization, or production approval. No live system, network endpoint, credential, or sensitive file was accessed.
