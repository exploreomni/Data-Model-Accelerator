# Data Model Accelerator

Omni deliveries distinguish prepared artifacts from native model validation, query parity, dashboard behavior and access acceptance. General YAML lint and synthetic examples do not establish a completed dashboard migration. The [Omni and sensitive-data repair plan](docs/plans/16-omni-and-sensitive-data-repair.md) tracks implementation and remaining live qualification. Sensitive input handling must be selected before agent submission; a classification label or selected export folder is not a masking or disclosure control.

Warehouse metadata now travels with model deliveries: a versioned dictionary, safely merged dbt documentation, reviewed native comment/tag changes, independent readback checks and a guided Metadata review. See the [metadata operator guide](skills/data-model-accelerator/references/warehouse-metadata.md) for Snowflake, Databricks, BigQuery, Redshift, ClickHouse and MotherDuck. Metadata SQL is available for a reviewed operator/CI handoff; automatic live metadata dispatch awaits authenticated drift-collector integration. Coalesce node exports and native compatibility retain their qualification requirements.

Turn tangled analytics code into documented, testable warehouse models and a curated semantic layer—with an analytics engineer and business SMEs in control of the decisions.

The accelerator is a portable agent skill with local analysis, validation and delivery tools. It inspects existing repositories, helps recover their logic, proposes reusable models, generates focused implementations, and packages the evidence for review. It also supports provisional new models from raw tables or CSV snapshots when reporting context is unavailable.

**Release status: candidate for supervised customer pilots.** Local exercises and regression tests pass. Live warehouse execution, native Omni acceptance, security enforcement and customer business approval must be established for each engagement. This is not an unattended migration service.

## Start here

| I want to… | Open |
| --- | --- |
| Run my first engagement | [End-to-end how-to guide](docs/HOW_TO.md) |
| Understand what works and what needs qualification | [Capabilities and boundaries](docs/CAPABILITIES.md) |
| Compare frameworks, warehouses and lint routes | [Platform matrix](docs/PLATFORM_MATRIX.md) |
| See a complete delivered example | [Seed-only dbt → Snowflake → Omni package](validation/no-context-release-candidate/candidate-delivery.zip) — download, extract, open `START_HERE.html` |
| Review test evidence | [Qualification status](docs/qualification.md) |
| Publish or deploy an approved model | [Deployment guide](docs/DEPLOYMENT.md) |
| Deliver descriptions and governed metadata | [Metadata operator guide](skills/data-model-accelerator/references/warehouse-metadata.md) |
| Handle PII, PCI, PHI and source-to-agent disclosure | [Sensitive-data boundary](skills/data-model-accelerator/references/sensitive-data.md) |
| Migrate Looker reports into Omni | [Omni delivery workflow](skills/data-model-accelerator/references/omni-delivery.md) |
| Understand release evidence and access checks | [Release evidence](skills/data-model-accelerator/references/delivery-release.md) · [Access enforcement](skills/data-model-accelerator/references/access-enforcement.md) |

## Your first run

Clone this repository and keep the complete skill folder together:

```sh
git clone https://github.com/exploreomni/DataModelAccelerator.git
cd DataModelAccelerator
```

Ask your coding agent to read [`skills/data-model-accelerator/SKILL.md`](skills/data-model-accelerator/SKILL.md), then provide the customer repository path and a separate output directory. The [how-to guide](docs/HOW_TO.md) covers setup; the [host guide](skills/data-model-accelerator/references/targets-and-hosts.md) distinguishes documented installation paths from tested host compatibility.

Copy this prompt and replace the paths:

> Use the Data Model Accelerator skill in this checkout. Assess `/absolute/customer-repo` read-only and save the engagement outside that repository in `/absolute/customer-modeling-run`. Our target is dbt on Snowflake with Omni. Interview me about missing scope and definitions; an analytics engineer and business SMEs are available. Reuse answers already provided. Inventory repository dependencies and request the scoped raw warehouse catalogue. Propose one complete domain for the first wave, preserve existing behavior, and identify corrections separately. Prepare a model, ERDs, dictionary, layer documentation, candidate dbt code, Omni topics, AI context and independent validation evidence. Give me one guided review page and a selected delivery ZIP. Request any additional execution or publication scope when it becomes necessary.

Starting an engagement does not execute the source project. Core local helpers need Python 3.9+ and a POSIX filesystem. Optional validation engines use a separate Python 3.12 environment; customer framework and warehouse runtimes are qualified independently.

## How the work progresses

1. **Interview and inventory.** Retain known answers, identify source formats, record dependencies and collect the raw catalogue. Report missing or unsupported inputs.
2. **Recover the behavior.** Trace formulas, filters, joins, grain and downstream consumers. Separate observed logic from inferred intent and proposed corrections.
3. **Review decisions with SMEs.** Resolve competing definitions, exclusions, date anchors, currency, history and access requirements. Bind decisions to the affected model version.
4. **Build the model and semantic layer.** An engineering role creates the scoped candidate. Warehouse and semantic roles decide what belongs upstream and what remains query-time logic.
5. **Validate independently.** Freeze expectations before inspecting candidate output. Check populations, values, fanout, projections and applicable access/semantic behavior; introduce deliberate defects to test detection.
6. **Review, iterate and hand off.** Inspect changes and evidence in the guided HTML, then export selected files. Code or context changes invalidate affected evidence.
7. **Publish or deploy when requested.** Select an exact destination and version, complete approval/preflight requirements, and retain execution and independent acceptance receipts.

SMEs settle business meaning; engineers own implementation. Two agreeing agents are not business approval. Hosts with delegation can run specialist roles separately; other hosts record sequential passes and their independence limitations.

## What you receive

Every model engagement maintains an ERD, complete dictionary and Bronze/Silver/Gold documentation internally. Export the formats and detail you select.

```text
START_HERE.html               Guided review: model, decisions, evidence, files
01_Model/                    ERDs, dictionary, layer guides, AI context
02_Implementation/           Selected project/code, semantic files, runbook tools
03_Validation/               Selected test evidence and unresolved checks
```

Exact files depend on the engagement. Existing projects receive a scoped patch and before/after mapping; new models receive a coherent candidate project. Reviewer, engineer and technical-audit exports can be separate. Source rows, credentials and working databases are not automatically included. The offline guide previews/copies/downloads artifacts; it does not run warehouse code or grant approval.

## Choose what completion means

Select `model_only`, `model_semantic`, or `full_dashboard` during discovery. A full dashboard migration includes dashboard behavior and effective access; a folder of topics cannot satisfy that scope. `START_HERE.html` shows every evidence lane, whether it applies, and the next action. It remains a candidate review page: imported pass labels do not authenticate business sign-off or execution.

The Looker dashboard API JSON reader preserves tiles, filters, listeners, layouts, calculations, source IDs and unresolved features. A reviewed mapping produces a bounded Omni dashboard build contract. The optional native adapter works with a reviewed draft on an existing document and preserves its published state; automatic new-document creation, publication and unsupported import paths remain outside this route. See [dashboard mapping](skills/data-model-accelerator/references/omni-dashboard-build.md) and [native draft limits](skills/data-model-accelerator/references/omni-dashboard-native.md).

The accelerator checks native Omni structure beyond YAML syntax, produces pinned gold-field AI context, compares frozen data/behavior cases, and checks access-state changes across all six warehouse options. These are distinct tools and evidence lanes. Local fixture success does not qualify a tenant, live AI session, source export completeness, or warehouse policy enforcement.

The agent scans selected artifacts, rendered HTML and its final ZIP within the supported scanner coverage. A **browser-created reduced ZIP** checks embedded file hashes but cannot run a new content scan or reapprove disclosure. Its manifest says so; return that exact ZIP to the agent for scanning and destination review before sharing. Classification, metadata comments, hidden fields and AI instructions are not substitutes for native access policies.

## Platforms and sources

Choose the **framework**, **warehouse**, **semantic engine** and **agent host** separately.

- Frameworks: dbt, Coalesce or native SQL, subject to the selected native contract.
- Warehouses: Snowflake, Databricks, Google Cloud BigQuery, Amazon Redshift, ClickHouse and MotherDuck.
- Sources: mixed dbt, Coalesce, warehouse SQL, BigQuery/Dataform, Looker, Hex, Tableau, Power BI, Sigma and raw CSV projects have discovery/specialist routes. Parser and end-to-end coverage differ by format.
- Semantic delivery: Omni candidate views, topics, relationships and AI context; other engines require their own selected contract.

These are not interchangeable support claims. Coalesce routes are conditional for Snowflake/Databricks/BigQuery and unsupported for the other three warehouses. dbt hosting differs from local adapter availability. Read the [capability levels](docs/CAPABILITIES.md) and [exact matrix](docs/PLATFORM_MATRIX.md) before choosing a route.

## What the tests establish

The recorded [source-only trial](validation/no-context-release-candidate/README.md) used 15 pinned CSVs and delivered 43 dbt models, 105 passing dbt tests, documentation for 58 objects/513 columns, and three Omni topics. Independent checks caught deliberately wrong amounts, fanout, missing rows, field exposure and an incorrect date-role join. The extracted delivery rebuilt successfully.

The recorded source-only trial's full local regression suite passed **905 tests with no skips**. See [current qualification](docs/qualification.md) for subsequent release checks. Test counts measure toolkit regression coverage, not a percentage of customer migration accuracy. The Snowflake adapter was parsed/compiled offline; the model ran locally in DuckDB. Native Snowflake, Omni and live AI-answer qualification remain open.

Lint, framework validity, native warehouse validity and independent data accuracy are separate results. SQLFluff reports exact-file convention exceptions explicitly; a policy pass can retain findings. It never substitutes for source reconciliation or permission tests. See [linting](docs/LINTING.md).

## Develop and validate the accelerator

For the complete local suite, use isolated Python 3.12:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip check
python skills/data-model-accelerator/scripts/bootstrap_hex_schema.py
python -m unittest discover -s tests -q
```

For a lightweight check, Python 3.9+ can run the same unittest command without optional engines; skipped tests must remain reported as skipped. CI includes a full-dependency lane that rejects skips, source-specific exercises, and separate deployment/lint checks. None requires customer credentials.

Generate a small synthetic guided walkthrough:

```sh
python3 skills/data-model-accelerator/scripts/run_guided_delivery_demo.py --output /absolute/new-demo-directory
python3 skills/data-model-accelerator/scripts/delivery_portal.py verify /absolute/new-demo-directory/engineer-example.zip
```

This demonstration is synthetic; its counts and receipts must never be reused as customer evidence.

## Reference map

[Architecture](docs/architecture.md) · [Engineer/analyst coordination](docs/analytics-engineering-workflow.md) · [Guided CLI](docs/guided-start.md) · [Raw catalogue](skills/data-model-accelerator/references/raw-catalogue.md) · [Specialist contracts](skills/data-model-accelerator/references/source-specialists.md) · [Model documentation](skills/data-model-accelerator/references/model-documentation.md) · [Raw-only workflow](skills/data-model-accelerator/references/inherited-data-discovery.md) · [Deployment runner contract](skills/data-model-accelerator/references/deployment.md)

## License and security

Project-authored code is available under the [MIT license](LICENSE). Vendor schemas and generated third-party material retain their own terms; see [NOTICE](NOTICE.md). The optional Hex validator requires an explicit, checksum-verified schema download from its publisher. Analysis never fetches it automatically.

Read the [security policy](SECURITY.md) and [public-release audit](validation/public-release/README.md) before using customer inputs. Automated scans do not establish production acceptance.
