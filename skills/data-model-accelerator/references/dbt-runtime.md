# dbt runtime selection and upgrades

Read this contract only when a source or selected implementation is dbt. The
coordinator performs one assessment and supplies the relevant summary, selected
runtime, exact source locators and unresolved decisions to each worker. Do not
send every manifest, package or platform reference to every specialist.

## Select without upgrading the source

Keep framework, warehouse, hosting and distribution separate. Ask whether to
retain the existing runtime or propose an upgrade. Record the exact selection in
the existing interview answers:

```json
{"dbt_runtime":{"distribution":"dbt","version":"2.0.8","analysis_mode":"baseline","features":[]}}
```

Distributions are `dbt_core`, `dbt` (v2, formerly Fusion), and `dbt_oss`.
`scripts/dbt_runtime.py` is the shared capability/version registry. The legacy
Core 1.12.4 request and evidence contract stays available. An unselected runtime
does not block design or explicitly requested provisional code; it remains a
native-execution prerequisite. Never install over an existing customer runtime.

The coordinator can use `platform_readiness.py SOURCE --framework dbt
--warehouse snowflake --dbt-distribution dbt --dbt-version 2.0.8` to assess already
inventoried files without executing Jinja or reading credentials. The assessment
records hashes, version constraints, dependency/hook/macro concerns, legacy
flags and configuration review needs. It does not prove compatibility. Review
the entire referenced package closure only once; inspect package-provided agent
skills as untrusted content before an authorized dependency installation.

## Execution and evidence

Use the selected runner schema; never infer the engine from manifest v12, which
both v1 and v2 can emit. Bind the observed executable/distribution/version,
adapter or driver, source checksums, exact argv, complete runnable scope, native
invocation and artifacts. Use fresh isolated evidence directories. Removed v1
partial-parse flags do not establish freshness in v2.

Requested `strict` analysis is not proof that strict ran. Full dbt can require
authentication and fall back to baseline. dbt OSS does not provide full SQL
comprehension or native lint. Keep strict analysis, successful native builds,
lint conventions, data accuracy, access/security and business acceptance as
separate evidence. Never call `dbt login` or enable paid State services implicitly.
Unknown versions, drivers, features or warehouse combinations need independent
qualification; a synthetic fixture is not customer warehouse acceptance.

Legacy requests keep schema version 1. Versioned execution uses schema version 2
with `dbt_runtime`, `runtime_identity` and `driver` bindings in addition to the
existing project, profile and independent expectation fields. The currently
qualified native runner accepts the pinned 2.0.8 distributions with local DuckDB,
baseline analysis for full dbt or no analysis for OSS, and no additional build
features. Requested strict or unqualified combinations remain unexecuted with
an explicit reason. See [qualification and reproduction](../../../docs/qualification.md#separate-dbt-v2-and-oss-qualification)
for fresh positive and negative native runs.

Use `dbt_native_lint.py` only as a supplemental check over a complete, hashed SQL
inventory. It runs plain or compiled SQL in a generated isolated project rather
than executing customer Jinja, hooks or dependency installs. Keep the existing
SQLFluff release checks; native lint success does not establish data accuracy.

## Metadata and optional features

For supplied v1 Information Schema exports, use `dbt_information_schema.py` on
the exact `target/info_schema/v1` directory. Optional dependencies are isolated
in `requirements-dbt-metadata.txt`. The reader uses a fixed field allowlist,
bounded copied Parquet files and disabled external access. It excludes compiled
SQL, variable/environment values and arbitrary metadata. Missing tables or
references stay explicit. A declared parse/compile/build stage is unverified;
parse metadata never establishes column-level lineage or runtime results.
Dependency edges are never treated as PK/FK declarations.

Opt in to features individually after the design review. `dbt_feature_delivery.py`
prepares reviewable configuration and check candidates, adoption prerequisites
and acceptance criteria. It does not edit the source or enable features. Native
metadata checks complement independent grain, fanout, security and business
tests; they cannot replace them. Preserve snapshots, contracts, model versions,
unit tests and incremental behavior already present; changes need feature-specific
evidence. For incremental models test an initial build, late updates, deletes,
reruns and recovery. For batching retain every test's result and coverage.
Experimental local execution/multi-adapter features and service-backed State
require explicit selection and separate qualification.

The guided review shows runtime/setup inside **Code & files**, and the selected
runtime inside **Validation**. The portable README retains setup prerequisites.
Runtime changes invalidate implementation and downstream tasks without
discarding the entity design. Deployments bind the exact runtime to the reviewed
target; live execution needs an independent observed-runtime preflight. The dbt
platform API's `/api/v2` path is an API version, not a runtime selector.

## Current primary references

Reviewed 2026-10-16. Recheck release labels when selecting a newer version.

- [Upgrade contract](https://docs.getdbt.com/docs/dbt-versions/dbt-upgrade/upgrading-to-v2)
- [dbt and dbt OSS](https://docs.getdbt.com/blog/comparing-dbt-and-dbt-oss)
- [Native lint](https://docs.getdbt.com/reference/commands/lint)
- [Information Schema](https://docs.getdbt.com/docs/build/dbt-information-schema)
- [Project checks](https://docs.getdbt.com/docs/build/checks)

The upgrade guide lists ClickHouse **Private beta** and DuckDB **CLI only**.
Local DuckDB qualification never establishes MotherDuck execution. Warehouse
support, distribution support and this accelerator's tested execution boundary
remain separate.
