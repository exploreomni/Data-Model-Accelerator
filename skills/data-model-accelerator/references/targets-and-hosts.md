# Target generation and host portability

Documentation checked September 9, 2026. Documented packaging support is separate from a successful run of this skill in a specific environment. Confirm installed versions, account features, tools, permissions, and paths before use. Do not infer release status that the cited documentation does not state.

## Independent choices

1. Host: the agent environment reading the skill and invoking tools.
2. Transformation framework: dbt, Coalesce, or a selected native warehouse approach.
3. Execution platform: Snowflake, Databricks, BigQuery, Redshift, ClickHouse or MotherDuck. Confirm BigQuery explicitly when the user says GCP. The [platform contract](platform-adapters.md) records conditional and unsupported framework pairings.
4. Semantic target: retain the existing engine, use Omni, or select another explicitly supported target.

Source project formats are discovered separately. An existing dbt or Looker project does not predetermine the target framework or semantic engine.

Use one shared model specification and test contract. Generate target-specific artifacts from that contract. Support for one combination does not validate the others.

## Host packaging

Copy the entire `data-model-accelerator` skill folder so relative references, scripts, and fixtures remain together. Do not copy only SKILL.md. Installation grants no external-system permission.

| Host | Documented location/mechanism | Qualification still required |
| --- | --- | --- |
| Codex | Project `.agents/skills/data-model-accelerator/` | Discovery, relative reference loading, local Python, target tool restrictions |
| Claude Code | Project `.claude/skills/data-model-accelerator/` | Same workflow plus local trust/permission settings |
| Gemini CLI | Project `.gemini/skills/data-model-accelerator/`; also documents `.agents/skills/` alias | Skill activation, dependencies and approved tool access |
| Snowflake Cortex Code / CoCo Desktop | Project `.snowflake/cortex/skills/data-model-accelerator/` or registered local parent folder | Workspace access, script execution and connection scope |
| Databricks Genie Code | User `/Users/{username}/.assistant/skills/data-model-accelerator/` or workspace skills folder | Workspace provisioning, runtime/file paths, execution identity |

Sources: [Codex](https://learn.chatgpt.com/docs/build-skills), [Claude Code](https://code.claude.com/docs/en/skills), [Gemini CLI](https://geminicli.com/docs/cli/skills/), [Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-desktop/skills), [Genie Code](https://docs.databricks.com/aws/en/genie-code/skills).

Cortex Agents are a distinct deployment surface. Snowflake documents skill references from a stage or Git repository, enabled code execution for executable skills, and a same-folder requirement for scripts in that path. This package's nested `scripts/` and `examples/` layout has not been qualified for that mechanism. Produce a separate versioned layout and resolve resource paths only after the selected Cortex Agents toolset is confirmed. Do not claim that dropping this package into a stage makes it compatible. [Cortex Agents skills](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-skills)

The above means Gemini CLI and Genie Code specifically; it does not establish compatibility with every Gemini chat surface or every Genie product. Hosts without file execution can perform an evidence-based assessment, but must mark executable checks unavailable or hand off to an authorized runner.

Discover the host's actual delegation capability independently of its skill discovery path. Follow [orchestration.md](orchestration.md): use native subagents where available and record task/result evidence, or disclose sequential inline specialist passes. A shared SKILL.md does not imply a universal subagent API or independent QA capability.

For Omni, [the dedicated task adapter](omni-modeler-task.md) records planned,
running, completed, needs-review, failed and unavailable states with pinned
inputs and knowledge. Its host names select the coordinator's adapter; they do
not provision external SDKs or establish tested compatibility. Run the read-only
installation comparison before use. Unqualified containment always requires
reviewed pre-sanitized inputs, whether the role is delegated or inline.

## dbt emitter contract

Inspect the chosen repository's project and adapter versions, dependencies, conventions, macros/hooks, sources, materializations, and schema naming. Generate source declarations, staging/intermediate/mart SQL as justified, column/relationship documentation, data tests, fixture tests where supported, and consumer/exposure mappings. Preserve source identifiers and bind `ref`/`source` dependencies to actual generated or confirmed existing objects.

dbt distinguishes unit tests on static inputs from data tests of built data. Unit tests have model/adapter limitations; use the installed version's syntax and supported execution path. Do not describe unit tests as universally offline. [Unit tests](https://docs.getdbt.com/docs/build/unit-tests), [data tests](https://docs.getdbt.com/docs/build/data-tests)

Candidate qualifications: explicit decimal/timezone behavior; all referenced models resolved; exact compiler/adapter versions; inspected packages/macros; development target compilation; fixture execution; data assertions against development objects; rerun/rebuild behavior for incremental models. Capture commands, redacted results, artifacts, IDs, and target identity. A generated `dbt_project.yml` alone is not a deployable validation result.

## Coalesce emitter contract

Request a representative exported project and the actual Coalesce version, node types, storage-location mappings, and environment configuration. Generate native node/column identities and dependency metadata using that supported project contract; SQL alone is only an implementation aid. Preserve IDs when modifying existing nodes. Custom node types need explicit compatibility checks.

Coalesce documents separate plan generation, deployment and refresh operations. Use the selected version's CLI/API contract and inspect the exact plan before any approved deployment. Do not invent commands or assume flags are stable across versions. [Coalesce deployment workflow](https://docs.coalesce.io/docs/coa/version-733-and-above/coa-deploying-pipelines)

When a native project contract is missing, deliver the target model, mappings and candidate SQL with status `native_generation_unverified`; request the smallest representative project export. Do not report that as Coalesce-ready code.

## Native warehouse emitter contract

Confirm the actual platform, namespace, role, source locations, deployment method and version. Generate dialect-specific DDL/DML/views, dependency order, verification queries, grants/policies as authorized, and recovery instructions. Choose tables/views/incremental processing/scheduled jobs based on supported capabilities and workload requirements; verify current official documentation before selecting platform-specific constructs.

Each selected warehouse needs separate validation of identifier case/quoting, timestamp/decimal semantics, null behavior, SQL functions, update/merge behavior, physical design, history and access enforcement. Use the [platform profiles](platform-adapters.md) for dialect and native check boundaries. Native generation is a selected target implementation, not a universal SQL transpilation promise. Source replication changes remain a distinct integration scope.

## Compatibility evidence ledger

Record package hash, host/version, skill discovery, referenced file loading, script execution, framework/adapter version, warehouse/environment, test evidence and outstanding gaps for every qualification run. Values are `documented`, `generated`, `executed`, `unavailable`, or `failed`, not a single universal supported flag.

Qualify raw-layer metadata collection separately for each provider and collection identity: scoped catalogue retrieval, full result pagination, native-to-canonical field mapping, nested types, visibility gaps, collection age and source binding. No host discovery path or catalogue fixture proves access to a live warehouse. Follow [raw-catalogue.md](raw-catalogue.md).

The package includes source discovery and specialist handoffs, raw-catalogue contracts, local model/semantic exercises, guided review, dialect linting and an externally governed deployment coordinator. It does not include a universal BI parser, deterministic cross-platform model compiler, preconfigured warehouse connector or provisioned production deployment service. The skill guides the host agent in collecting authorized metadata and generating artifacts from an inspected repository; each collection, host and target path must be qualified separately. See the [guided workflow](guided-workflow.md) and [platform contract](platform-adapters.md).

## Shared guided delivery

Use [platform-adapters.md](platform-adapters.md) for static readiness and extension boundaries and [guided-workflow.md](guided-workflow.md) for persistent discovery/resume. [review-surface.md](review-surface.md) renders selected artifacts without a warehouse-specific UI fork. These helpers do not change the native generation/execution qualification requirements above. Existing repositories receive a scoped patch and change mapping rather than an unsolicited replacement project.

## Privacy and execution portability

Packaging a skill for a host does not configure its network, telemetry, retention,
tool permissions or source-to-model boundary. Follow [sensitive-data.md](sensitive-data.md)
before sending any source metadata or values to a model. The portable pre-agent
staging helper permits reviewed pre-sanitized inputs within its declared policy;
a boolean claiming that a host is isolated does not qualify protected input
handling. Existing host and organizational controls need independent verification.

PII, PCI and PHI categories can overlap. Unknown classifications remain unknown;
hashing, aggregation, documentation comments, ordinary tags, hidden Omni fields
and AI guidance are not automatic declassification or access enforcement.
Apply the destination policy to generated descriptions, semantic context,
diagnostics and exports as well as source samples. Native security capability
and accelerator qualification are listed separately in [access-enforcement.md](access-enforcement.md).

The bounded Omni model checker accepts explicitly bound physical namespaces for
the six warehouse profiles; each selected dialect and native runtime still needs
its own qualification. Coalesce node generation, dbt compilation, native SQL,
warehouse metadata and policy execution remain separate routes. Do not call a
local DuckDB test a MotherDuck permission test or a generic SQL folder a native
Coalesce deployment.

Use the same `model_only`, `model_semantic` or `full_dashboard` completion scope
across hosts. The [release evidence protocol](delivery-release.md) does not turn
an offline HTML page or imported receipt into an authenticated run. The guided
page defaults to candidate/pending evidence, and browser subset downloads retain
their missing fresh content scan. Host portability is useful for producing and
reviewing candidates; it is not blanket production authorization.
