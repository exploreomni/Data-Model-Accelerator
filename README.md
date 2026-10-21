# Data Model Accelerator

Turn tangled analytics code into documented, testable warehouse models and an Omni semantic layer. The accelerator is a portable agent skill with local analysis, validation and delivery tools. Analytics engineers and business SMEs retain control of definitions, access and release decisions.

**Status: suitable for supervised pilots.** Local tests establish bounded development behavior. Each engagement still needs native target validation, independent data checks and business approval.

## Start here

| Your goal | Guide |
| --- | --- |
| Run your first engagement | [End-to-end how-to](docs/HOW_TO.md) |
| Run one stage or continue a reviewed design | [Independent stages](skills/data-model-accelerator/references/staged-engagement.md) |
| Build or refactor Omni models | [Omni Modeler](docs/OMNI_MODELER.md) |
| Choose a supported route | [Capabilities](docs/CAPABILITIES.md) · [Platform matrix](docs/PLATFORM_MATRIX.md) |
| Retain dbt v1 or adopt dbt v2 / dbt OSS | [Runtime selection and upgrade guide](skills/data-model-accelerator/references/dbt-runtime.md) |
| Understand testing and remaining limits | [Qualification and reproduction](docs/qualification.md) |
| Deploy a reviewed model | [Deployment](docs/DEPLOYMENT.md) · [Linting](docs/LINTING.md) |
| Contribute or run the test suite | [Contributor guide](CONTRIBUTING.md) |

## Your first run

```sh
git clone https://github.com/exploreomni/Data-Model-Accelerator.git
cd Data-Model-Accelerator
```

Ask your coding agent to read [`skills/data-model-accelerator/SKILL.md`](skills/data-model-accelerator/SKILL.md). Keep the complete skill folder together; [host setup](skills/data-model-accelerator/references/targets-and-hosts.md) distinguishes installation guidance from tested compatibility.

Copy this prompt and replace the paths:

> Use the Data Model Accelerator skill in this checkout. Assess `/absolute/source-repo` read-only and save the engagement in `/absolute/modeling-run`. Our target is dbt on Snowflake with Omni. Reuse known answers and interview us about missing definitions. Inventory the scoped warehouse catalogue and existing warehouse models. Start with the entity/table design, connected ERD, dictionary, layer responsibilities and asset mappings for one domain. Show outstanding decisions and how to answer them. Iterate on this design before generating code. After the selected design is reviewed, assess development effort, then run implementation and Omni generation as separate stages. Retain our progress and give us one guided review page.

Discovery does not execute the source project. Core helpers require Python 3.9+ and a POSIX filesystem; optional validation engines use an isolated Python 3.12 environment.

## Workflow and deliverables

1. **Design and review.** Inventory sources and existing models; propose entities, grains, keys, relationships and placement. Resolve scoped decisions before recording design sign-off.
2. **Assess development effort.** Show Easy, Somewhat easy, Difficult or Very difficult, with evidence, confidence and blockers separate. These are complexity categories, not duration estimates.
3. **Implement.** Generate the selected warehouse code from the reviewed design.
4. **Model the semantic layer.** Generate Omni files and AI context against the selected physical implementation or verified reused models.
5. **Validate.** Compare independent expectations and retain native, access and business checks separately.
6. **Package and deploy.** Export the requested files; use separately authorized release controls for publication or deployment.

Each stage uses the same saved engagement. Optional `data-model-design`,
`data-model-implement`, `data-model-semantic`, `data-model-validate`,
`data-model-package`, `data-model-migration-plan` and `data-model-deploy` skills provide focused entrypoints;
install them beside the complete main skill. They share contracts and answers.
The local stage commands plan and gate work; the coding-agent host performs the
actual specialist work. For local candidate generation, the host records explicit
human approval of the exact design scope from the trusted conversation or an
authenticated review system. No signing service is required. Teams can optionally
use external signed design review. Neither path authorizes SQL execution or
deployment; the governed release workflow retains its separate authority checks.

For an optional migration plan, the accelerator reuses historical mappings and
consumer inventories to produce an Excel inventory, Word plan and selected
ticket templates/import files. It asks about Google Sheets/Docs during intake;
native cloud creation uses the agent host's connector and remains pending until
verified there. Jira, Linear, Azure DevOps, Monday and Asana exports retain their
import limitations; GitHub and generic outputs are copyable templates. No live
tickets are created. See [migration planning](docs/HOW_TO.md#migration-planning-and-ticket-templates).

If you request code while the catalogue or design review is pending, the agent
can produce **provisional dbt/native and semantic files** from available evidence.
It records your request, labels unresolved bindings and leaves physical validation
and deployment pending. You do not need to approve an unknown design just to see
draft code. See [requested provisional code](skills/data-model-accelerator/references/provisional-generation.md).
Requested code stays pending until its scoped outputs are recorded; finishing
design documents alone does not complete an implementation request.

Replanning saved tasks shows what can be reused, regenerated or is blocked
when source slices, decisions, outputs or relevant accelerator components change.
Asset filters help inspect the entities tied to a report or dashboard; filtering
does not silently change approved scope or exported files. Existing warehouse
models are compared before proposing reuse, extension, creation or replacement.

The coordinator gives each specialist a concise task summary and relevant pinned
evidence, rather than the full conversation or repository. Bounded context packets,
targeted dependency requests and delta reviews reduce repeated ingestion while
preserving independent source checks. See [context-efficient orchestration](skills/data-model-accelerator/references/agent-context.md).
Packet sizes and attempts are operational evidence; actual usage and charges
remain the agent host's responsibility.

Code batches also record [authoring evidence](skills/data-model-accelerator/references/authoring-quality.md):
scoped assumptions, literal provenance, structural conformance and honest coverage
gaps. Checker-only updates can recheck retained code without another generation
pass. Provisional output remains available. Model defaults stay unchanged until
a [controlled comparison](skills/data-model-accelerator/references/agent-benchmark.md)
supports a reviewed routing decision. Static passes never establish production readiness.

A model delivery maintains an ERD, complete dictionary and documentation for every scoped layer. One current entry page opens to a **Data model** workspace, with **Code & files** and **Validation** alongside it. Inspect the ERD, select a table for its columns, keys, joins and linked code, and filter new versus reused tables. Supporting context stays available on demand. Diagram coverage is checked against the included model inventory; it does not establish business acceptance. The selected ZIP opens offline:

```text
START_HERE.html               One entrypoint: status, design and implementation
01_Model/                    ERDs, dictionary, layer guides and AI context
02_Implementation/           Selected code, semantic files and runbook
03_Validation/               Selected test results and unresolved checks
```

Choose `model_only`, `model_semantic` or `full_dashboard` during discovery. Dashboard migration requires behavior and effective-access evidence in addition to topics. Existing projects receive a scoped patch and impact mapping; new models receive a coherent candidate. Source rows and credentials are not automatically exported.

Keep one maintained design narrative and setup guide; register them through the optional `handoff` references in the [review contract](skills/data-model-accelerator/references/review-surface.md). The overview derives readiness from existing records, without treating generated files or local passes as native validation or acceptance. Chat updates report meaningful progress and blockers; full receipts stay in the separate technical audit. Prior exports remain immutable.

To see a small synthetic guided package without warehouse credentials:

```sh
python3 skills/data-model-accelerator/scripts/run_model_review_demo.py --output /absolute/new-demo-directory
python3 skills/data-model-accelerator/scripts/delivery_portal.py verify /absolute/new-demo-directory/commerce-model-review.zip
```

Share `commerce-model-review.zip`, or open the extracted `handoff/START_HERE.html`. The root README identifies that one current package. `technical-evidence/` contains the internal generator inputs and checks; it is excluded from the ZIP. This five-table example demonstrates review UX, not customer validation. The broader platform exercise remains available through `run_guided_delivery_demo.py` and the qualification guide.

## Platforms

Choose the framework, warehouse, semantic engine and agent host separately:

- **Frameworks:** dbt, Coalesce or native SQL, subject to the selected native contract.
- **Warehouses:** Snowflake, Databricks, BigQuery, Redshift, ClickHouse and MotherDuck.
- **Sources:** bounded offline adapters for dbt, Coalesce, Looker, Power BI, Tableau, Hex, Domo, Sigma, Periscope/CDT, WebFOCUS, Snowflake, Databricks, BigQuery/Dataform, Redshift, ClickHouse, MotherDuck and Fabric. Raw CSV and existing Omni inventory retain their established paths. [Check the exact supported export formats and gaps](docs/CAPABILITIES.md#source-formats); source parsing does not imply complete migration or live API acquisition.
- **Source interpretation:** [17 focused specialist profiles](skills/data-model-accelerator/references/source-specialists.md), one per adapter, with grain/filter/security checks, placement guidance and exact context requests. The coordinator supplies one pinned profile and selected evidence per task; the host controls actual agent execution and usage.
- **Omni:** candidate views, relationships, topics, bounded query views, AI context and a guided model review. Unsupported constructs remain explicit.

Routing is not equivalent to full native support. Read the [capability levels](docs/CAPABILITIES.md) and [platform matrix](docs/PLATFORM_MATRIX.md) before choosing a route. SQL lint, framework validity, native execution, data accuracy and human acceptance remain separate checks.

## Repository map

This checkout contains the accelerator source, not a customer delivery. Keep cloned customer repositories, engagement working files and generated handoffs outside it. Share only the selected delivery ZIP or its extracted handoff; previous exports and internal evidence are not additional customer deliverables.

- `skills/data-model-accelerator/`: skill instructions, specialist references, runtime tools, templates, schemas and runnable synthetic examples.
- `skills/data-model-*/SKILL.md`: optional stage entrypoints using the complete shared accelerator.
- `docs/`: user guides, architecture, supported routes and qualification boundaries.
- `tests/`: regression tests, frozen independent fixtures and the synthetic Omni operator exercise.
- `.github/workflows/`: automated validation and security checks.

Generated reports, run logs, delivery ZIPs and internal planning notes stay out of the source tree. See [repository hygiene](CONTRIBUTING.md#what-belongs-in-git) for the distinction between fixture inputs and disposable outputs.

## Further reading

[Architecture](docs/architecture.md) · [Engineer/analyst coordination](docs/analytics-engineering-workflow.md) · [Guided CLI](docs/guided-start.md) · [Raw catalogue](skills/data-model-accelerator/references/raw-catalogue.md) · [Metadata delivery](skills/data-model-accelerator/references/warehouse-metadata.md) · [Sensitive-data handling](skills/data-model-accelerator/references/sensitive-data.md)

Project-authored material uses the [MIT license](LICENSE). Vendor schemas retain their own terms; see [NOTICE](NOTICE.md). The optional Hex schema is acquired explicitly from its publisher with checksum verification. Review the [security policy](SECURITY.md) before using customer inputs.
