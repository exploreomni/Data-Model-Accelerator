# Source specialist playbooks

The coordinator selects one of **17 portable interpretation profiles**, each paired
with its bounded [source adapter](source-adapters.md). These are instructions for
the host's `source_specialist` role, not 17 always-running agents or proof of live
vendor integration. Read this index in the coordinator only. Put the selected
profile and relevant evidence into a [targeted packet](agent-context.md).

## Shared contract

Capture source identity, revision/export version, exact object IDs and evidence
locators. Preserve original expressions, dependencies, grain, filters, security,
time/history context and unknowns. Parser recognition, semantic interpretation,
source completeness, native execution and business acceptance are separate.

The coordinator inventories/extracts once, retains canonical contracts, selects a
coherent dependency slice and resolves cross-source conflicts. Workers interpret
supplied findings, request exact missing evidence, and return only their assigned
handoff. No source execution, automatic approval, broad research, credential
access or deployment is authorized by a profile. Missing context must not be
replaced with guessed logic or an empty successful result.

Use the existing [specialist result v1](orchestration.md#3-specialist-result-contract-v1).
`placement_candidate.destination` remains `warehouse`, `semantic`, `presentation`,
`split` or `unresolved`. Put the richer design recommendation in optional
`context.recommended_disposition`; it is a proposal, not an approval. Map
`move_upstream` to `warehouse`, `retain_semantic` to `semantic`,
`retain_presentation` to `presentation`, and `split`/`unresolved` to themselves.
For `reuse_existing`, name the evidenced existing layer (or `unresolved`). Keep
`consolidate_candidate` and `retire_candidate` at `unresolved` until the existing
design decision workflow resolves them. The result verifier checks consistency
when the optional field is supplied; legacy v1 results remain supported.

Every profile includes required inputs, interpretation and placement, the required
handoff, escalation boundaries and concrete acceptance cases. Read its adapter
reference only when a format/version question requires it; do not preload every
platform guide. Profiles do not expand parser support or change stage approvals,
provisional generation, catalogue requirements for execution, or delivery scope.

## Interpretation acceptance

The maintained synthetic corpus in `tests/fixtures/specialist_interpretation_cases.json`
covers all 17 sources separately from parser tests. Its public case fields are
`id`, `source`, `evidence`, `question` and `facts`; keep `expected` private to the
independent assessor. Use one selected profile plus that case for a bounded
forward test. The scorer in `tests/test_specialist_interpretation_benchmark.py`
checks the structured answer and rejects missing required facts, unsupported
claims and wrong placement. CI tests the scorer with positive and adversarial
controls; it does not invoke an LLM or establish native/vendor correctness.
Inspect rationale and requests independently: structured choices alone cannot
prove accurate free-text reasoning. Save actual forward-test receipts outside
the installed skill, with profile/case hashes and host execution evidence.

## Raw CSV snapshot specialist

**Identify:** `.csv` is a snapshot-format routing clue, not warehouse identity. Outside an identified source-project/profile context it routes to `raw_csv`. CSVs within an actual dbt project stay with the dbt specialist, including custom seed/resource directories. Never fabricate `dbt_project.yml` to make a raw-only new-model exercise look like a legacy-project migration.

**Implemented metadata:** The existing bounded, read-only planner and readiness scans pass selected file bytes to `scripts/raw_csv_source.py`. It records original headers, exact SHA-256 and byte length, logical record count when EOF is reached, and explicitly lexical-text fields. Quoted commas/newlines and UTF-8 BOM are supported. No data rows, examples, value ranges, formulas or inferred business definitions are emitted. See the [raw CSV source contract](raw-csv-source-contract.md) for schema and bounds.

**Gaps:** Required/duplicate/ambiguous headers, ragged rows, decoding/parser errors and metadata bounds remain explicit incomplete coverage. Header-only files have zero rows; a file without a header is not a confirmed empty table. Unreadable, oversized and symlink inputs never acquire invented hashes/counts. Existing project/scan bounds and exclusions remain in force; scope can be revised explicitly rather than silently increasing a read limit.

**Interpretation:** Source system, live catalogue types, key constraints, null semantics, extraction population, freshness, history, currency/status meaning, Excel/report behavior and access authority remain unknown unless separately evidenced. A complete CSV metadata inventory means only that the selected snapshot structure was inspected; it never qualifies target execution, business accuracy or production acceptance. Framework and warehouse selection remain independent decisions.

## dbt specialist

Use the [dbt interpretation profile](specialists/dbt.md) and its
[bounded adapter contract](source-adapters/dbt.md).

## Coalesce specialist

Use the [Coalesce interpretation profile](specialists/coalesce.md) and its
[bounded adapter contract](source-adapters/coalesce.md).

## Snowflake specialist

Use the [Snowflake interpretation profile](specialists/snowflake.md) and its
[bounded adapter contract](source-adapters/snowflake.md).

## Databricks specialist

Use the [Databricks interpretation profile](specialists/databricks.md) and its
[bounded adapter contract](source-adapters/databricks.md).

## BigQuery specialist

Use the [BigQuery interpretation profile](specialists/bigquery.md) and its
[bounded adapter contract](source-adapters/bigquery.md).

## Looker specialist

Use the [Looker interpretation profile](specialists/looker.md) and its
[bounded adapter contract](source-adapters/looker.md).

## Power BI specialist

Use the [Power BI interpretation profile](specialists/powerbi.md) and its
[bounded adapter contract](source-adapters/powerbi.md).

## Tableau specialist

Use the [Tableau interpretation profile](specialists/tableau.md) and its
[bounded adapter contract](source-adapters/tableau.md).

## Hex specialist

Use the [Hex interpretation profile](specialists/hex.md) and its
[bounded adapter contract](source-adapters/hex.md).

## Sigma specialist

Use the [Sigma interpretation profile](specialists/sigma.md) and its
[bounded adapter contract](source-adapters/sigma.md).

## Periscope / Sisense CDT specialist

Use the [Periscope / Sisense CDT interpretation profile](specialists/periscope.md) and its
[bounded adapter contract](source-adapters/periscope.md).

## Domo specialist

Use the [Domo interpretation profile](specialists/domo.md) and its
[bounded adapter contract](source-adapters/domo.md).

## WebFOCUS specialist

Use the [WebFOCUS interpretation profile](specialists/webfocus.md) and its
[bounded adapter contract](source-adapters/webfocus.md).

## Redshift specialist

Use the [Redshift interpretation profile](specialists/redshift.md) and its
[bounded adapter contract](source-adapters/redshift.md).

## ClickHouse specialist

Use the [ClickHouse interpretation profile](specialists/clickhouse.md) and its
[bounded adapter contract](source-adapters/clickhouse.md).

## MotherDuck specialist

Use the [MotherDuck interpretation profile](specialists/motherduck.md) and its
[bounded adapter contract](source-adapters/motherduck.md).

## Fabric specialist

Use the [Fabric interpretation profile](specialists/fabric.md) and its
[bounded adapter contract](source-adapters/fabric.md).

## Omni specialist

**Identify:** Native `.view`, `.query.view`, `.topic`, `model` and `relationships`
files require matching structure. Weak support files such as a label-only model
or empty relationships file need a structurally recognized native sibling.
Generic files with similar names do not establish Omni origin. The source route
also requests the dedicated `omni_modeler` target role; routing is not execution.

**Extract:** Use the [lossless inventory contract](omni-inventory.md) for authored
and effective snapshots, scoped objects, field identity, query output mappings,
relationships, topic aliases, dependencies and explicit gaps. Preserve raw bytes
and opaque constructs. Compare against a separately captured scope/inventory;
repository completeness is not tenant completeness.

**Traps:** Never write a resolved combined model back as authored overrides,
flatten workbook intent into shared definitions, infer deletion from omission,
invent physical bindings for query views, or claim source completeness from a
self-count. Reference scans, compilation, query results, access and SME acceptance
remain separate. A minimal proposed patch has no deployment authority.

Sources checked 2026-10-05: [Modeling layers](https://docs.omni.co/modeling),
[Query views](https://docs.omni.co/modeling/query-views),
[Read model YAML](https://docs.omni.co/api/models/get-model-yaml).
