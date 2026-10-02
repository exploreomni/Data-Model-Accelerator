# Source specialist playbooks

Primary documentation checked **2026-09-09** unless a section states otherwise. These are extraction contracts and engineering recommendations; only explicitly named bounded readers are implemented. They do not establish complete production parsing or vendor integrations. Recheck format versions and release labels for each pilot.

## Shared contract

Detect projects within a repository; a monorepo can require several specialists. A filename is a routing clue, not proof of valid contents. Confirm structure against the applicable grammar/schema. Record project root, revision, artifact hash, exporter/product version, object IDs, and exact file/line or structured pointer for every extracted claim. Separate authored code, compiled code, observed results, and inference. Preserve unresolved references and unsupported expressions verbatim.

Each specialist returns objects, expressions, dependencies, declared and inferred grain, join predicates/cardinality, filter and aggregation context, security rules, coverage gaps, and proposed placement with rationale. Specialists propose; the coordinating model/semantic reviewer resolves conflicts across sources. Existing warehouse code can contain report-specific mistakes; BI code can contain legitimate reusable definitions.

Use safe parsers with execution disabled. Do not run repository macros, notebook cells, hooks, package installers, or generated SQL during extraction. Protect against path traversal, symlinks outside scope, oversized archives, YAML object constructors, and XML external entities. Binary detection reports a gap; it is not parsing. An authorized, bounded extraction step can later unpack supported archives into an isolated directory and retain container/member provenance. Never treat data extracts or rendered reports as full model specifications.

## Raw CSV snapshot specialist

**Identify:** `.csv` is a snapshot-format routing clue, not warehouse identity. Outside an identified source-project/profile context it routes to `raw_csv`. CSVs within an actual dbt project stay with the dbt specialist, including custom seed/resource directories. Never fabricate `dbt_project.yml` to make a raw-only new-model exercise look like a legacy-project migration.

**Implemented metadata:** The existing bounded, read-only planner and readiness scans pass selected file bytes to `scripts/raw_csv_source.py`. It records original headers, exact SHA-256 and byte length, logical record count when EOF is reached, and explicitly lexical-text fields. Quoted commas/newlines and UTF-8 BOM are supported. No data rows, examples, value ranges, formulas or inferred business definitions are emitted. See the [raw CSV source contract](raw-csv-source-contract.md) for schema and bounds.

**Gaps:** Required/duplicate/ambiguous headers, ragged rows, decoding/parser errors and metadata bounds remain explicit incomplete coverage. Header-only files have zero rows; a file without a header is not a confirmed empty table. Unreadable, oversized and symlink inputs never acquire invented hashes/counts. Existing project/scan bounds and exclusions remain in force; scope can be revised explicitly rather than silently increasing a read limit.

**Interpretation:** Source system, live catalogue types, key constraints, null semantics, extraction population, freshness, history, currency/status meaning, Excel/report behavior and access authority remain unknown unless separately evidenced. A complete CSV metadata inventory means only that the selected snapshot structure was inspected; it never qualifies target execution, business accuracy or production acceptance. Framework and warehouse selection remain independent decisions.

## dbt specialist

**Identify:** `dbt_project.yml` identifies the project root. `manifest.json` is strong evidence only with matching dbt artifact metadata/schema; generic SQL/YAML is insufficient. Follow configured resource paths, not assumed folder names.

**Extract:** Models, sources, seeds, snapshots, macros, tests, exposures, semantic definitions, `ref`/`source` dependencies, materializations, incremental strategies, unique keys, contracts, hooks, and grants. Match compiled artifacts to the selected revision/environment; include disabled resources separately. A declared unique key is not uniqueness evidence.

**Parse/gaps:** Read YAML/Jinja/SQL and versioned manifest JSON; use its dependency maps without pretending they establish column lineage. Compilation may need packages, variables, adapter settings, or database introspection, so require a separately reviewed execution plan. Missing replication settings, deployment overrides, and untracked consumers remain gaps.

**Traps:** Ephemeral expansion, dispatched macros, incremental branches, late updates/deletes, snapshot history, and adapter-specific quoting. Preserve reusable semantic metrics instead of automatically materializing every measure.

Sources: [Project definition](https://docs.getdbt.com/reference/dbt_project.yml), [Manifest and schema versions](https://docs.getdbt.com/reference/artifacts/manifest-json).

## Coalesce specialist

**Identify:** Corroborate root `data.yml` (`fileVersion`, `platformKind`) with `locations.yml`, `nodes/`, and `nodeTypes/`. A lone `data.yml` is ambiguous. Support legacy exports separately. Current documented structure includes V1 YAML nodes and V2 SQL nodes; V2 uses `@id`, `@nodeType`, and node-type directories containing `definition.yml`, `create.sql.j2`, and `run.sql.j2`.

**Extract:** Stable node/column IDs, source mappings, storage locations, transformations, join sections, business/change-tracking keys, tests, multisource strategies, SQL overrides, node-type templates, packages/macros, jobs, and environment mappings.

**Parse/gaps:** Version-aware YAML plus templated SQL; resolve node types and packages before interpreting generated behavior. Preserve missing templates, mappings, or package versions as unresolved. Do not infer deployed state or replication coverage from a development workspace.

**Traps:** A node called “Fact” does not prove correct grain. MERGE versus INSERT, truncate/append settings, Type 1 versus Type 2 behavior, and template defaults can materially change results. Validate against the installed CLI version before proposing native code.

Sources: [Repository structure and V2 workflow](https://docs.coalesce.io/docs/coa/version-733-and-above/coa-building-pipelines), [Node behavior](https://docs.coalesce.io/docs/get-started/coalesce-fundamentals/nodes).

## Snowflake specialist

**Identify:** `snowflake.yml` with a recognized `definition_version` identifies a CLI project. Standalone DDL, migrations, procedures, and Snowpark code need dialect/project confirmation; there is no assumption that every Snowflake repository uses this layout.

**Extract:** Tables/views, SQL and procedural dependencies, dynamic tables, streams/tasks, UDFs, merge/delete logic, stages/pipes, ownership/grants, masking and row-access policies, identifiers, and session assumptions where supplied.

**Parse/gaps:** Use Snowflake-aware SQL parsing and static language analysis for handlers; validate project structure against its definition version. Dynamic SQL and runtime object names remain unresolved. Repository files cannot establish current warehouse DDL, policy attachments, task state, ingestion configuration, or actual constraints; request bounded metadata exports.

**Traps:** Session timezone, quoted identifiers, owner/caller execution context, CDC handling, and policies absent from copied tables. Test access with representative identities; copying a predicate is not proof of preserved access enforcement.

Sources: [Project definitions](https://docs.snowflake.com/en/developer-guide/snowflake-cli/project-definitions/about), [Row-access policy evaluation](https://docs.snowflake.com/en/user-guide/security-row-intro).

## Databricks specialist

**Identify:** `databricks.yml`/`databricks.yaml` with a `bundle` block is a static bundle routing signal. Explicit `--source-profile databricks:relative-root` supports repositories without that layout. A SQL, Python or notebook file alone does not establish Databricks origin. Source routing never selects the target framework or warehouse.

**Extract:** Supplied bundle/resource IDs, SQL and notebook dependencies, configured jobs/pipelines, runtime settings, catalog/schema bindings, materialization and merge logic, schedules and access declarations. Preserve observed configuration separately from deployed state and runtime behavior.

**Parse/gaps:** The repository planner recognizes fingerprints and emits specialist prompts; it does not implement a Databricks native parser or executor. Inspect supported YAML/SQL statically, retain includes/variables/dynamic SQL as unresolved when necessary, and request version-matched native exports. Never execute notebooks, bundle commands, Python imports or source installers during inventory. Workspace objects, grants and job state absent from the repo remain gaps.

**Traps:** SQL and runtime settings affect behavior; an apparently portable query is not native validation. Stateful processing, late updates, checkpoint/recovery behavior and access enforcement need actual scoped target evidence.

Sources checked 2026-09-24: [Bundle configuration](https://docs.databricks.com/aws/en/dev-tools/bundles/settings), [SQL/Runtime reference and configuration](https://docs.databricks.com/aws/en/sql/language-manual/). See [platform readiness](platform-adapters.md) for current accelerator execution boundaries.

## BigQuery specialist

**Identify:** Dataform `workflow_settings.yaml` with `defaultProject`/`defaultDataset`, or `dataform.json` with explicit BigQuery configuration, provides a static routing signal. Explicit `--source-profile bigquery:relative-root` supports native SQL exports without Dataform. Generic SQL/SQLX and GCP alone do not establish a BigQuery source; keep unresolved files generic.

**Extract:** Supplied project/dataset/location bindings, SQL/SQLX definitions, dependencies, assertions, incremental and partition behavior, compilation variables/overrides, schedules and access declarations. Retain authored Dataform logic separately from a supplied compilation result and an observed BigQuery execution.

**Parse/gaps:** The planner routes files but does not compile Dataform JavaScript/SQLX or implement a BigQuery native parser/executor. Do not run JavaScript, package installers or SQL to inspect the repo. Request original version-bound compilation/execution records and physical catalogue exports through the reviewed operator path; untracked objects, IAM and runtime overrides remain explicit gaps.

**Traps:** Compilation settings can redirect destinations. Dataset location, numeric/time/null behavior, incremental corrections and query identity need target-specific review. Preserve unresolved dynamic references; generic dialect conversion does not prove behavioral parity.

Sources checked 2026-09-24: [Dataform compilation and execution lifecycle](https://docs.cloud.google.com/dataform/docs/configure-compilation), [BigQuery datasets and locations](https://docs.cloud.google.com/bigquery/docs/datasets-intro). See [platform readiness](platform-adapters.md); these routes establish neither parser completeness nor warehouse acceptance.

## Looker specialist

**Identify:** `.model.lkml`, `.view.lkml`, `.explore.lkml`, `manifest.lkml`, and `.dashboard.lookml`; generic `.lkml` also needs grammar inspection. Follow includes, refinements, extensions, and imported projects.

**Extract:** Views/Explores, dimensions/measures, primary keys, relationships, derived tables/PDTs, persistence rules, filters, Liquid/parameters, access filters/grants, timezone behavior, and dashboard query context where present.

**Parse/gaps:** Use a LookML grammar parser with embedded SQL/Liquid handling; LookML is not ordinary YAML. User-created dashboards/Looks, table calculations, merged results, connection settings, and user-attribute assignments may require separate exports. Preserve missing imported projects.

**Traps:** Symmetric aggregates depend on correct keys and relationships; flattening joins can reintroduce fanout. Separate row transformations in derived tables from context-dependent measures, drill paths, and user filters. Inspect generated SQL as evidence without mistaking generated aggregation safeguards for source business rules.

Sources: [Project file types](https://cloud.google.com/looker/docs/lookml-project-files), [Symmetric aggregates](https://cloud.google.com/looker/docs/best-practices/understanding-symmetric-aggregates).

## Power BI specialist

Use the implemented [Power BI source contract](powerbi-source-contract.md) and [qualification exercise](powerbi-omni-e2e.md). The bounded PBIP/TMSL/enhanced-PBIR reader and M/DAX replay do not establish complete Power BI format or native-runtime support.

**Identify:** `.pbip`; semantic-model `definition.pbism` plus TMDL `definition/` or TMSL `model.bim`; report `definition.pbir` plus supported report content. `.tmdl` or `.bim` alone identifies tabular artifacts, not necessarily Power BI provenance. PBIP documentation currently labels the feature **preview**.

**Extract:** Power Query M/partitions, source queries, calculated tables/columns, DAX measures, relationships and filter direction, calculation groups, RLS/OLS, storage modes, and report/page/visual filters, interactions, and model references.

**Parse/gaps:** Use versioned JSON schemas and TMDL/TOM tooling; parse M and DAX separately. Preserve PBIX as an opaque artifact until supported export/extraction is available; prefer a Desktop PBIP export or authorized model definition export. A report can reference a remote model absent from Git. Check unapplied query changes, dataflows, gateways, credentials, and service role memberships separately.

**Traps:** Filter/row context, context transition, inactive or bidirectional relationships, blank handling, time intelligence, and totals. A DAX measure is not automatically a row-level SQL column. Test filter combinations and totals before choosing placement.

Sources: [Semantic-model files](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset), [Report files and model references](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report).

## Tableau specialist

Use the implemented [Tableau extraction contract](tableau-source-contract.md) and [Tableau migration exercise](tableau-omni-e2e.md). The reader qualifies a bounded XML subset; native source/runtime coverage remains explicit.

**Identify:** `.twb`/`.tds`; `.twbx`/`.tdsx` are ZIP packages; `.hyper` contains extracted data, not the workbook logic. Keep Tableau Prep flows as a separate source profile when present.

**Extract:** Connections/custom SQL, logical relationships and physical joins, calculated fields, LOD expressions, table calculations, parameters, sets/groups, blending, extract/context/dimension/measure filters, worksheet grain, and addressing/partitioning.

**Parse/gaps:** Parse supported workbook/data-source XML versions safely; use Hyper interfaces only for authorized extract inspection. A reviewed package extractor must account for every member. Published data sources, server permissions/user filters, extracts, Prep dependencies, and external files can be missing from Git.

**Traps:** FIXED/INCLUDE/EXCLUDE behavior, filter order, aggregation after relationships, and view-dependent table calculations. A window function copied upstream can change a result when users change dimensions. Record worksheet context and test alternative partitions and filters.

Sources: [File types and packages](https://help.tableau.com/current/pro/desktop/en-us/environ_filesandfolders.htm), [Order of operations](https://help.tableau.com/current/pro/desktop/en-us/order_of_operations.htm).

## Hex specialist

Use the implemented [Hex static extraction contract](hex-source-contract.md) and the [three-project qualification exercise](hex-omni-e2e.md). The native-format reader reports cell-level coverage and gaps; the general repository planner still supplies routing only.

**Identify:** Native `.hex.yaml`, validated against Hex's linked public JSON schema; older `.yaml` exports require structural/provenance confirmation. Generic `.ipynb` is not a Hex fingerprint.

**Extract:** Cell IDs/types, SQL/Python transformations, references between cells/dataframes, parameters, connection references, chart configuration, app layout, and reusable-component dependencies. Preserve code order separately from inferred execution dependencies.

**Parse/gaps:** Safe YAML plus static SQL/Python analysis; never execute notebook imports/cells during inventory. Prefer native exports: Jupyter export can lose Hex-specific SQL/input behavior. Native YAML excludes project outputs, so it cannot supply result-parity evidence. Obtain sample results, referenced components/files, environment dependencies, connection bindings, and sharing controls separately.

**Traps:** Stateful Python, dataframe coercion, in-memory joins, parameter-dependent branches, and app-only filters. Lift deterministic reusable transformations only after dependency and state analysis; preserve exploration and interactive calculations where appropriate.

Sources: [Native format, limitations, and schema](https://learn.hex.tech/docs/explore-data/projects/import-export), [Git export](https://learn.hex.tech/docs/explore-data/projects/git-export).

## Sigma specialist

**Identify:** No universal repository suffix is assumed. Explicitly identify artifact type and provenance. Documented data-model `/spec` exports use JSON/YAML with `dataModelId`, `documentVersion`, `schemaVersion`, and `pages`; validate the combined structure. A workbook CSV/JSON data export is a result sample, not this specification.

**Extract:** Source IDs, element/column IDs, formulas, grouping levels, joins/lookups, filters/controls, metrics, lineage, security expressions, and materialization configuration where exposed. Preserve workbook context alongside shared data-model definitions.

**Parse/gaps:** Use the versioned data-model spec and separately supplied workbook columns/formulas, queries, lineage, pages/elements, and controls responses. Track pagination and failures. The legacy workbook-schema endpoint is **Deprecated**. Spec limitations include input tables, Python/UI elements, custom functions, and metrics/links defined on data sources; request separate evidence. Do not interpret absence as non-use.

**Traps:** Group-level versus row calculations, control-dependent SQL, upstream element references, lookup cardinality, and input-table/writeback behavior. Warehouse materialization cannot silently replace interactive logic or access rules.

Sources: [Data models as code and limitations](https://help.sigmacomputing.com/docs/manage-data-models-as-code), [Spec API](https://help.sigmacomputing.com/reference/get-data-model-spec), [Workbook formulas](https://help.sigmacomputing.com/reference/get-workbook-columns), [Deprecated workbook schema](https://help.sigmacomputing.com/reference/get-workbook-schema).
