# Qualifying the initial dbt flow

Use this reference when validating a generated dbt candidate or preparing its
initial acceptance package. The initial delivered path uses full table rebuilds.
Incremental merges, snapshots, scheduling, production recovery, additional agent
hosts, and arbitrary source repositories require their own evidence.

When the requested target places interactive report context downstream, keep
reconciliation/report SQL in dbt analyses or separate semantic/test artifacts.
Check the actual enabled model inventory: an ordinary `dbt build` must not create
a tenant/date/status-filtered report table or view merely because it helped test
the migration. Materialized compatibility reports require explicit scope and
placement decisions; labeling one "validation only" in prose is insufficient.

## Evidence sequence

1. Freeze the selected source revision, raw catalogue/data capture, model
   specification, candidate project, ERD, dictionary and layer documentation.
   Preserve compatibility findings separately from proposed business corrections.
2. Inspect the project configuration, packages, macros and hooks before an
   authorized development run. Use the explicitly selected profile, role and
   isolated schema. Record actual platform/adapter versions and scoped identity.
3. Capture `verify_dbt_evidence.snapshot_project(project_root)` before execution.
   Run a separate native `dbt parse --no-partial-parse` preflight with the same
   profile/target. Freeze `expected_nodes(preflight_manifest)` as the denominator.
4. Run native `dbt build --no-partial-parse --target <selected target>` for the
   complete reviewed project. Keep its original manifest, run_results, exit code,
   execution timestamps and logs. A parse, empty build, selected subset, warning,
   skipped node, missing result or previous invocation is not full build evidence.
5. Associate those artifacts in the v1 receipt described in
   `scripts/verify_dbt_evidence.py`, then run that read-only verifier. Its supported
   association contract is dbt Core 1.12.4, manifest v12 and run-results v6.
   External package resources, unit tests, functions, hooks and YAML snapshots
   need additional qualification. Preserve failures; do not refresh a snapshot to
   make stale execution evidence pass.
6. Independently reconcile full gold rows and report slices. Test the applicable
   grain, joins, nulls, dates, history, deletes, late corrections, duplicate input,
   rejected input and recovery. Compare actual built columns to the model
   inventory and dictionary, including reused bronze objects.
7. Present the exact candidate and evidence for business and operational
   acceptance. A machine-readable receipt does not authenticate execution,
   principal, warehouse, approver or business meaning; it checks the association
   and consistency of supplied evidence. Existing review-package/documentation
   checks remain required. Neither verifier grants deployment permission.

The native dbt command builds resources and executes data tests in dependency
order; its manifest and run-results are separate artifacts from a source parser's
findings. See the official [build command](https://docs.getdbt.com/reference/commands/build)
and [run-results contract](https://docs.getdbt.com/reference/artifacts/run-results-json).

## Reproduce the bundled local execution

Use Python 3.12 in a fresh environment and install
`scripts/requirements-dbt-qualification.txt`. Then run:

```sh
python scripts/run_dbt_local_qualification.py --cases hex tableau powerbi \
  --output /absolute/new/local-dbt-run
```

This invokes native dbt Core with the DuckDB adapter against isolated local files.
The runner copies the reviewed candidates, records original/executed file hashes,
and makes explicit NUMBER-to-DECIMAL and ISO-date-format substitutions. These are
bounded fixture adaptations, not a general SQL compiler. Source candidates and
their earlier evidence remain unchanged. The run records raw data actually loaded,
the full native node denominator, original results, and evidence-verifier output.
It has no arbitrary customer-project execution option.

The runner verifies the bundled candidates and expected-data files against their
existing review-package pins before invoking dbt. This detects fixture drift;
those local files remain part of the trusted checkout, not an authenticated
publisher or an arbitrary-code sandbox.

DuckDB execution remains `local_validated`. It cannot establish Snowflake
compilation, grants, warehouse performance, live catalogue completeness, native
source BI behavior, or Omni semantic behavior. The same distinction applies even
when every local test passes.

## Initial acceptance boundary

Engineering evidence may support a reviewed development pilot. Snowflake target
acceptance additionally requires the designated development environment, a live
or operator-exported catalogue, actual Snowflake/dbt builds, aligned result
reconciliation, operational ownership, and human acceptance of the exact version.
If the release includes Omni or a particular BI source, native semantic and source
acceptance remain separate. A dbt test failure blocks acceptance; it does not
atomically roll back previously built tables or revoke consumer access.

Record one explicit decision for each open gate. Do not relabel a simulated check
as native execution or silently narrow release scope to obtain sign-off.
