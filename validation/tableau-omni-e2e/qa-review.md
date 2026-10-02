# Independent Tableau migration QA

Reviewed and executed on 2026-09-10. **31 focused tests passed** in Python 3.12 with the optional local engines; Python 3.9.6 correctly skipped all 31 when those dependencies were absent. No blocking correctness finding remains within this bounded review.

The reviewer authored the independent oracle using only the synthetic scenario, raw records and adjustments CSV, then froze it before inspecting the Tableau source, parser, execution helper or targets. The reviewer subsequently authored `tests/test_tableau_execution.py`. Root and the other specialists authored the implementation and applied corrections. Expected outputs were not regenerated during QA. This is independent local development evidence, not business approval.

## Observed preservation

- All 16 valid scenarios match through actual parsed-source replay and candidate Omni queries: **96 sheet comparisons**, including both tenants, January/February and boundary cases, selected segments, empty windows, zero denominators, multiplier 2, date-and-segment combinations and an unknown segment. Eight invalid or denied contexts reject.
- All **10 full gold invoice rows** match, including composite invoice/customer history keys, draft and out-of-window records, integer amount components and signed balances. Source custom SQL and native row calculations also match the independent fact projection, including nullable adjustments evaluated through ZN.
- Source inventory contains one workbook, three worksheets, one dashboard, 29 fields, 15 calculations and five parameters. Default replay accounts for all 29 field IDs. The separate TWBX contains three byte-matching members and does not become a second workbook or extract files.
- FIXED preserves A/C1's 18,000-cent value when filtering to its SMB mark; moving the segment filter before FIXED incorrectly yields 11,000 and is detected. Date context changes the correct value. Shares partition by month after segment filtering; a deliberate all-month partition executes but fails reconciliation.
- Documentation agrees with the **10 executed raw/silver/gold objects and 64 columns**. Removing a raw column from both dictionary and inventory, while updating the inventory hash, still fails against the executed schema. An empty readable dictionary also rejects.

## Findings corrected during review

| Finding | Reproduction and observed closure |
| --- | --- |
| Contradictory worksheet context metadata was ignored | A companion declaring segment context and a different order still returned baseline values. The helper now validates the supported filter roles, context order and presentation stage; regression passes. |
| Large payment ratios exceeded declared tolerance | A signed-64 payment of `9007199254740993` preserved cents but initially produced `450359962737.5496` instead of `450359962737.54965`, an absolute error of `0.00005`. Parsed derived-measure arithmetic now returns the exact latter value. Regression requires `1e-12` accuracy or an explicit precision-limit rejection. |
| Cached source graph could outlive its evidence | Replaying a graph after an on-disk source edit previously used stale embedded expressions. Asset paths and hashes are now checked before replay; a changed TDS receipt rejects even when the change is only trailing whitespace. Deliberate normalized graph mutations remain explicit test controls. |
| Inherited description referenced an absent customer-month model | The stray dbt column description was removed. The target correctly has only customer history and invoice gold models. |

Additional negative controls modify real temporary XML and target artifacts. Source formula edits update the TDS and worksheet copies consistently so they fail for changed results, not unrelated drift. Removed datasource population filters actually admit the draft invoice and fail parity. Changed source context/partitioning, target FIXED scope/cancellation and tenant join fanout are detected by intended semantic assertions. A separate mismatched TDS rejects at extraction.

Unsupported formula functions and cyclic references reject. Temporary archive traversal and symlink members reject without extraction. A harmless CSV cannot be read through either the query allowlist or the returned DuckDB connection. Wrong catalogue and quoted Snowflake identifier case reject. These controls do not establish an arbitrary-code sandbox.

## Qualification limits

This case uses authored synthetic XML and local interpreters. Official XSD validation was attempted and reported `unavailable_publisher_schema_dependency`; XML/static parsing is not official schema acceptance. Native Tableau opening/rendering, Snowflake/dbt execution, Omni workbook behavior, dashboard actions, densification, refresh and production incremental ingestion remain unverified. The native Omni model and local presentation companion are distinct artifacts; the companion is not a published Omni workbook.

Synthetic persona predicates do not prove real Tableau, warehouse or Omni authorization. The supplied catalogue is synthetic rather than live metadata. Documentation sampling confirmed raw VARCHAR dates versus the explicit local DATE adaptation, temporal keys, CDC ordering and the distinction between logical assertions and unenforced physical constraints. Native dtype/decimal behavior and operational ownership require separate qualification.

The parent task owns the integrated runner and broad repository suite; those results are separate evidence. The focused suite command is `/private/tmp/dma-e2e-env/bin/python -m unittest discover -s tests -p test_tableau_execution.py -v` from the repository root.

Frozen SHA-256 values rechecked after QA:

| Artifact | SHA-256 |
| --- | --- |
| `expected/oracle.py` | `ca32b55be8025170829ceeba3f43a74ed1046891320d8ceed5e81a1d331851b0` |
| `expected/expected_rows.json` | `ad4a964a7778cd655ac988847ee6a57d7eb4563e1cb6275615c715b1ada0e128` |
| `expected/expected_reports.json` | `3055ada6aa096af171499321e7cefe3776858dd088baa27fc03e16c29de9509d` |
| `expected/oracle-notes.md` | `c0486aecdad92dbcede6e639377be11a804c3aae60389d3320700e50218b9161` |
