# Private independent dbt holdout oracle — root/evaluator only

Do not expose this directory to the target-author agent. It contains expected data and an independent evaluator, not candidate transformation SQL. This is one internal blind retail pilot, not universal dbt qualification.

Input was frozen before expected output generation:

- Input: `/private/tmp/dma-dbt-holdout/input`
- Content snapshot SHA-256: `3a5bd552c860769ff8cd5facd51b0e988fd0bf4f9b3927866c8889a1c1a49edb`
- Input manifest SHA-256: `b463464049ad2313b4b24459f7c2cdaf6c70fd96848f2af2df70300a99ab4496`
- 15 content files plus manifest. Four raw tables, 30 columns, 32 rows; one flawed report and two reusable staging models.

`evaluate.py` uses Python's standard library only. `evaluate(raw_data: dict, params: dict | None) -> {gold: list, report: list}` validates all input versions, resolves current state, independently aggregates child events, derives gold, and computes report context. It reads neither repository SQL nor later target files. Its formulas were implemented from the authored source contract and raw data. Invalid captures/contexts raise `InvalidInput`; outputs are not produced. `mutation(raw_data, name)` returns an independently copied altered capture for replay.

CLI example:

```sh
python3 /private/tmp/dma-dbt-holdout/private-oracle/evaluate.py \
  --input /private/tmp/dma-dbt-holdout/input/raw-data.json \
  --params '{"tenant":"B"}' \
  --output /private/tmp/retail-oracle-output.json
```

The CLI emits `{"status":"passed","result":{"gold":...,"report":...}}`, exit 0; an invalid input emits `{"status":"failed","error_type":"InvalidInput","error":...}`, exit 2. `--mutation conflicting_superseded_version` exercises a conflict at an older version which must still fail even though a newer unambiguous row exists.

`expected.json` freezes five report contexts (default A, tenant B, product P1, pending status, empty date window), three valid mutation results (duplicate full capture, late fulfillment correction, late return deletion), and five explicit negative cases (superseded tied-version conflict, orphan fulfillment, tenant/persona mismatch, explicit null authorization, unknown status). Gold is compared in full in every valid case; report filtering must not alter it. Compare exact cents/quantities/keys/dates/statuses and float ratios within 1e-12. Empty grouped reports are empty arrays, not synthetic zero rows.

Sanity checks were computed directly without executing source or target SQL: baseline has five gold rows; default report has three month/product rows. A|O1|L1 has line net 2400 cents, fulfilled 3, returned 2, refund 1500 cents and retained revenue 900 cents. Default A report totals line net 8900 cents and refunds 3750 cents. These checks and duplication invariance are asserted by `build_expected.py`. They deliberately differ from the flawed legacy join output.

Key acceptance traps: tenant/order/line uniqueness; fulfillment and return preaggregation; applying a total line discount once; full-capture tied-version validation before latest selection; latest-then-delete ordering; not dropping orphan events; preserving pending rows in gold; downstream product/date/status/security context. The target must reuse correct existing staging or explicitly justify an equivalent change. The source project is authored and native execution was not claimed. No instruction-injection note or malicious code was included.

`build_input.py` is retained privately as fixture-authoring provenance; do not rerun it against the frozen input as part of evaluation. `build_expected.py` regenerates expected values from the frozen raw capture using only the independent evaluator. Neither should be copied into the candidate project. `oracle-manifest.json` records all private content hashes separately from the input manifest.
