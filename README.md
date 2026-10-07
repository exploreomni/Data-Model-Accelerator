# Data Model Accelerator

Turn tangled analytics code into documented, testable warehouse models and an Omni semantic layer. The accelerator is a portable agent skill with local analysis, validation and delivery tools. Analytics engineers and business SMEs retain control of definitions, access and release decisions.

**Status: suitable for supervised pilots.** Local tests establish bounded development behavior. Each engagement still needs native target validation, independent data checks and business approval.

## Start here

| Your goal | Guide |
| --- | --- |
| Run your first engagement | [End-to-end how-to](docs/HOW_TO.md) |
| Build or refactor Omni models | [Omni Modeler](docs/OMNI_MODELER.md) |
| Choose a supported route | [Capabilities](docs/CAPABILITIES.md) · [Platform matrix](docs/PLATFORM_MATRIX.md) |
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

> Use the Data Model Accelerator skill in this checkout. Assess `/absolute/customer-repo` read-only and save the engagement in `/absolute/customer-modeling-run`. Our target is dbt on Snowflake with Omni. Interview me about missing scope and definitions; an analytics engineer and business SMEs are available. Reuse answers already provided. Inventory repository dependencies and request the scoped raw warehouse catalogue. Propose one complete domain for the first wave, preserve existing behavior, and identify corrections separately. Prepare models, connected ERDs, a data dictionary, Bronze/Silver/Gold documentation, candidate dbt code, Omni topics, AI context and independent validation evidence. Give me one guided review page and a selected delivery ZIP. Request additional execution or publication scope when necessary.

Discovery does not execute the source project. Core helpers require Python 3.9+ and a POSIX filesystem; optional validation engines use an isolated Python 3.12 environment.

## Workflow and deliverables

1. **Interview and inventory.** Confirm the scope, raw catalogue, source formats, dependencies and missing evidence.
2. **Recover behavior.** Trace formulas, filters, joins, grain and consumers; distinguish observed logic from proposed corrections.
3. **Review definitions.** Resolve meaning, date anchors, currency, history and access with the business owner.
4. **Build and validate.** Generate the selected model and semantic artifacts, then compare against independent expectations and test deliberate defects.
5. **Review and hand off.** Iterate in the guided HTML, export selected files, and deploy only the approved version to the selected destination.

A model delivery maintains an ERD, complete dictionary and documentation for every scoped layer. The selected ZIP opens offline:

```text
START_HERE.html               Guided review, decisions, evidence and files
01_Model/                    ERDs, dictionary, layer guides and AI context
02_Implementation/           Selected code, semantic files and runbook
03_Validation/               Selected test results and unresolved checks
```

Choose `model_only`, `model_semantic` or `full_dashboard` during discovery. Dashboard migration requires behavior and effective-access evidence in addition to topics. Existing projects receive a scoped patch and impact mapping; new models receive a coherent candidate. Source rows and credentials are not automatically exported.

To see a small synthetic guided package without warehouse credentials:

```sh
python3 skills/data-model-accelerator/scripts/run_guided_delivery_demo.py --output /absolute/new-demo-directory
python3 skills/data-model-accelerator/scripts/delivery_portal.py verify /absolute/new-demo-directory/engineer-example.zip
```

Extract `engineer-example.zip` and open `START_HERE.html`. This is a demonstration, not customer validation evidence.

## Platforms

Choose the framework, warehouse, semantic engine and agent host separately:

- **Frameworks:** dbt, Coalesce or native SQL, subject to the selected native contract.
- **Warehouses:** Snowflake, Databricks, BigQuery, Redshift, ClickHouse and MotherDuck.
- **Sources:** dbt, Coalesce, warehouse SQL, BigQuery/Dataform, Looker, Hex, Tableau, Power BI, Sigma and raw CSV have discovery routes; parser and end-to-end coverage differ.
- **Omni:** candidate views, relationships, topics, bounded query views, AI context and a guided model review. Unsupported constructs remain explicit.

Routing is not equivalent to full native support. Read the [capability levels](docs/CAPABILITIES.md) and [platform matrix](docs/PLATFORM_MATRIX.md) before choosing a route. SQL lint, framework validity, native execution, data accuracy and human acceptance remain separate checks.

## Repository map

- `skills/data-model-accelerator/`: skill instructions, specialist references, runtime tools, templates, schemas and runnable synthetic examples.
- `docs/`: user guides, architecture, supported routes and qualification boundaries.
- `tests/`: regression tests, frozen independent fixtures and the synthetic Omni operator exercise.
- `.github/workflows/`: automated validation and security checks.

Generated reports, run logs, delivery ZIPs and internal planning notes stay out of the source tree. See [repository hygiene](CONTRIBUTING.md#what-belongs-in-git) for the distinction between fixture inputs and disposable outputs.

## Further reading

[Architecture](docs/architecture.md) · [Engineer/analyst coordination](docs/analytics-engineering-workflow.md) · [Guided CLI](docs/guided-start.md) · [Raw catalogue](skills/data-model-accelerator/references/raw-catalogue.md) · [Metadata delivery](skills/data-model-accelerator/references/warehouse-metadata.md) · [Sensitive-data handling](skills/data-model-accelerator/references/sensitive-data.md)

Project-authored material uses the [MIT license](LICENSE). Vendor schemas retain their own terms; see [NOTICE](NOTICE.md). The optional Hex schema is acquired explicitly from its publisher with checksum verification. Review the [security policy](SECURITY.md) before using customer inputs.
