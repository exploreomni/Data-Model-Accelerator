# Omni and sensitive-data repair qualification

Local implementation reviewed October 5, 2026, on `atx/omni-privacy-repair`, based on repository commit `7a25a6b14992d1caaecbf9bd490efc97a40e5cb1`. This records engineering evidence; it is not native platform acceptance, a compliance certification, or deployment authorization.

Start with the [implementation ledger](../../docs/plans/16-omni-and-sensitive-data-repair.md), [operator guide](../../docs/HOW_TO.md) and [capability boundaries](../../docs/CAPABILITIES.md). The two newly generated examples are linked from [blind-generation start here](blind-generated/START_HERE.md).

## Implemented behavior

| Area | Repair and evidence |
|---|---|
| Delivery scope | Model-only, model-plus-semantic and full-dashboard intake; explicit pending, failed, stale and unsupported evidence. A topic alone cannot complete a dashboard migration. |
| Sensitive inputs and outputs | Overlapping PII/PCI/PHI categories, conservative lineage, destination-specific disclosure policy, private input projections and bounded content scans of final HTML/ZIP bytes. Unknown classification does not become public because a scan finds nothing. |
| Looker extraction | Structural API4 dashboard detection; stable source IDs, queries, filters, text, layouts and unresolved dependencies; independent source coverage remains separate from parsing the supplied export. |
| Omni model | Deterministic generation and context-aware SQL/YAML checks; separately authorized development adapter with native validation, modeled queries, state snapshots and recovery. Static validation does not establish native acceptance. |
| Omni dashboard | Tile/filter/layout mapping and an authorized new branch draft on an existing document; exact readback and recovery. Publication, new-document creation and Beta import remain outside this implemented write route. |
| Accuracy and AI context | Independent population/behavior parity contracts, negative controls, gold-field lineage and approved-definition-only AI context. Unresolved meanings stay unresolved. |
| Access | Nonweakening policy comparison, exact resource/persona/destination bindings, positive and negative access cases, and six-warehouse qualification matrix. Policy provisioning remains blocked; supplied JSON is not proof of live enforcement. |
| Release | Independent signed evidence, issuer lane restrictions, freshness/revocation and exact artifact/policy/target checks integrated into the existing deployment coordinator. Candidate review, development execution and migration acceptance are distinct. |
| Guided review | Candidate badge, selected scope, evidence lanes and actionable pending work. Browser-generated subsets verify integrity and explicitly disclose that a fresh content scan did not run. |

The shared controls cover dbt, Coalesce and native SQL paths. Platform-specific live qualification remains separate for Snowflake, Databricks, BigQuery, Redshift, ClickHouse and MotherDuck. Source adapter coverage is bounded; this release does not promise arbitrary Looker constructs or equivalent full migrations for every source platform.

## Regression and security checks

The pinned Python 3.12.14 runtime passed **1,474 tests with zero skips** in 89.836 seconds. The core-only runtime separately passed its available checks across 1,474 discovered tests, with 489 optional-dependency skips; it is not a substitute for the full result. Focused checks included:

- 31 signed-release and coordinator integration cases, including 16 independent probes.
- 29 security contract cases and 32 platform matrix cases.
- 28 native Omni model cases and 39 dashboard cases.
- 28 parity cases and 36 AI context cases.
- 27 dbt documentation merge cases, including the new ordinary-YAML-list regression.
- Seven guided-review behavior tests plus existing portal, disclosure and deployment-review regressions.

Independent reviewers exercised import tampering, stale/incorrect bindings, metadata exposure, privilege changes, unsupported paths, injected transports, partial outcomes and approval/evidence separation. Tests use synthetic records and test-only signing keys; no customer credentials or private customer artifacts are included.

The development requirements audit reported **no known vulnerabilities**. Gitleaks scanned the current repository files, including new artifacts, with **no leaks found**. Skill validation, changed Markdown links, workflow YAML parsing, 130 generated artifact hashes and the final whitespace check passed. These checks do not establish absence of all vulnerabilities or sensitive content.

Remote CI has not run for this local branch. Browser JavaScript behavior and generated package integrity were tested, but pixel-level portal/SVG inspection remains unverified because the available browser/rendering environment rejected the inspection paths.

## Fresh-context generation and independent evaluation

A fresh agent received only the current accelerator instructions/helpers and [synthetic input bundle](blind-inputs/MANIFEST.json). It was instructed not to inspect prior deliverables, repository tests or other conversation context. This was a prompt boundary on a shared filesystem, **not enforced filesystem isolation**. The agent generated new artifacts for two domains:

| Domain / target | Candidate | Independent scenarios |
|---|---|---|
| Maintenance / dbt + Snowflake | Two bronze, two silver and one gold model; work-order grain with parts preaggregated before joining; Omni model, dashboard work list, ERD, dictionary and layer documentation | Exact baseline population and amounts; unseen extra parts on closed and open orders; duplicated source work-order key must be caught by the authored uniqueness test |
| Energy / dbt + BigQuery | Two bronze, two silver and one gold model; reading grain with a unique meter lookup; Omni model, dashboard work list, ERD, dictionary and layer documentation | Exact baseline population and amounts; unseen meter/reading while preserving date and zone filters; duplicated meter key must be caught by the authored uniqueness test |

The independent evaluator [passed all six scenarios](independent-results.json). It derives expectations with Python decimal arithmetic directly from the source CSVs and declared rules, without importing candidate results. It executes constrained candidate SELECTs through local DuckDB dialect translation. Expectations are frozen before each candidate variation executes. The reviewer had inspected candidate SQL before authoring the evaluator, so this is **not a fully blinded evaluator**. It is independent expectation logic applied to fresh-context generation.

Both static Omni models pass, both declared lint scopes pass 20/20 files and 6/6 execution units, and all eight original input files remain byte-identical. These are local checks; dbt itself and the native Snowflake, BigQuery and Omni runtimes were not executed in these new trials. Existing repository dbt exercises remain separate regression evidence.

The fresh trial exposed a real helper defect: round-trip YAML produces a list subclass for ordinary `model-paths`, which the dbt metadata helper rejected as nonliteral. The helper now accepts list subclasses while retaining nested/invalid-path rejection. Both unmodified projects then reached the correct next gate: seven proposed resource descriptions per domain require approval before metadata projection. No fake approval was added to force success.

The candidate intentionally retains unknown classifications, proposed definitions, incomplete catalogue grounding and manual dashboard mappings. AI definitions are withheld. `persist_docs` remains false pending the documented metadata review; this is not a waiver of the normal approved-metadata requirement. The generation [run report](blind-generated/RUN_REPORT.md) records exact versions, failed attempts, corrections and remaining gaps. Its [artifact manifest](blind-generated/ARTIFACT_MANIFEST.json) pins portable outputs. Original local execution receipts containing host paths are retained privately, and portable summaries are explicitly not resealed original receipts.

## Remaining qualification

1. Reproduce the customer failure using the original approved Looker export and pre-fix output. They were not available in this implementation turn; the neutral regression shape and new domains do not establish exact customer reproduction.
2. Run an authorized BigQuery + Omni development pilot and a dbt + Snowflake pilot. Collect actual model validation, warehouse execution, modeled query results, dashboard rendering/interaction behavior and recovery evidence.
3. Independently observe effective access, including metadata, drill, export, share and cache paths. Qualify collectors, principals, versions and environments before issuing signed access evidence. The toolkit verifies external statements; it does not supply an already-qualified collection/signing service.
4. Have the authorized business and security reviewers approve definitions, classifications, disclosure destinations and intentional behavior changes. Native AI answer tests remain pending.
5. Run CI and independent release review for the exact proposed revision, then obtain destination authorization. No repository push, merge, policy write, dashboard publication or production deployment was performed by this implementation.

Local confidence is **High** for the behavior covered by the recorded tests. Native migration acceptance is **unverified**. No accuracy percentage or production readiness claim is derived from these test counts.

## Reproduce locally

Use the repository's pinned development runtime and its existing optional platform dependencies:

```sh
python -m unittest discover -s tests
python validation/omni-privacy-repair/evaluate_blind.py
```

The evaluator verifies input pins, reconstructs candidate projections and overwrites only its own `independent-results.json`. The authoring script inside the generated package deliberately refuses to overwrite an existing candidate; see its run report before attempting a fresh generation. No native services are contacted by either command above.
