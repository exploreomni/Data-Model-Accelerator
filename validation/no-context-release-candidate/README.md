# Fresh source-only dbt / Snowflake / Omni qualification

The fresh candidate passed local execution, independent source reconciliation, actual Omni-definition replay and portable-package reconstruction. **High confidence for consistency with this snapshot; native Snowflake, native Omni and business acceptance remain pending.** No PR merge or deployment occurred.

Download [the curated delivery](candidate-delivery.zip), extract it, and open `START_HERE.html`. The guided review includes the real dbt project, Snowflake profile example, architecture and layer ERDs, full dictionary, Bronze/Silver/Gold operating documentation, native Omni model and portable AI context. Raw rows and working databases are excluded.

## Evidence and scope

| Area | Result |
| --- | --- |
| Source | 15 CSVs, 120 columns, 54,068 rows; exact hashes match the earlier pinned acquisition |
| Warehouse model | 43 models: 15 Bronze, 19 Silver, 9 Gold; all 393 projected columns evaluated |
| dbt execution | 43 models plus 105 passing tests using the local DuckDB adapter |
| Snowflake adapter | Actual dbt-snowflake 1.12.1 and dbt-core 1.12.4 parsed/compiled 148 nodes offline; zero connection attempts |
| Documentation | All 58 raw/model objects and 513 columns; 525 projection, dependency and lineage checks |
| Omni | 9 views, 3 topics, 15 measures, 99 dimensions, 11 join roles; native extensionless model includes AI context |
| Independent semantic replay | Actual YAML interpreted locally: 52 measure cases, all join roles/topic grains/dimensions, 8 grouped queries |
| Deliberate defects | All 5 physical and 3 semantic mutations detected; 6 static Omni negative controls also passed |
| Lint | 231 files and 148 rendered units covered; 415 exact-file convention exceptions retain 855 raw findings |
| Portable delivery | Extracted project rebuilt all 148 nodes; duplicate-aware results match for all 43 models; Omni resolver/static validation passed |
| Accelerator regression | 905 tests passed, no skips; local evidence only |

The full SQLFluff rule set ran. Parser, configuration, runtime, coverage and data errors were not excepted. The convention result is an explicit policy pass, not a zero-finding result or human approval. The archive contains the policy and raw findings.

## Blindness and oracle integrity

Fresh modeling and analyst agents received only the pinned CSVs and current accelerator instructions, without earlier models or the upstream exercise solution. Expected populations and source-derived calculations were frozen before candidate inspection. Known user choices were reused; absent SME, Excel baseline, currency, status semantics, history, ownership and tenant policy were recorded as unknown.

The semantic author saw frozen aggregate/orphan observations before generating Omni definitions. Semantic generation is therefore source-only but not fully blinded to those observations; its actual files were subsequently checked against the independent frozen oracle.

A Python 3.9 timestamp parser in the oracle initially rejected valid fractional timestamps and produced 504 false mismatches. The original expectation freeze and failed comparison were retained. A narrow, source-hash-verified normalization erratum corrected that oracle defect without changing candidate logic. The archive includes the erratum and independent review. Different mapped-cell coverage counts overlap and must not be added as unique coverage.

## Material modeling findings

The model retains 41 order lines without a supplied header and 46 reason associations without a supplied header. Header and line populations remain separate, as do billing and shipping geography roles. Unknown source meaning is not converted into an approved revenue measure. Publication allowlists omit direct person/address/payment details; remaining operational identifiers are still linkable and require native access review.

The negative controls include a wrong date join that preserves row counts. This distinguishes value-level semantic validation from simply passing dbt tests or checking fanout.

## Accelerator corrections

- Accept and preserve Omni's exact native `model` basename in the governed package; continue rejecting arbitrary extensionless/executable payloads.
- Include native `.view`, `.topic`, `model` and `relationships` files in lint inventory and structured validation.
- Support exact-path/rule/reason style exceptions bound to source hashes, preserve original findings, reject unused or forged exception results, and disclose exceptions in release-quality summaries.
- Strengthen source-only guidance for normalization runtimes, transparent oracle errata, per-role semantic replay, extracted-package reconstruction and restricted preview contents.
- Correct handoff instructions to use shipped scripts, install Omni tool dependencies before execution, and resolve AI-context paths in the extracted layout.

## Reproduce and qualify the actual target

The [input manifest](input-manifest.json) identifies the exact upstream commit and CSV hashes. Obtain only those seed files. Follow the extracted project's `02_Implementation/dbt_project/README.md` for pinned dependencies, the local raw loader and parse/compile/build commands. `01_Model/docs/RUNBOOK.md` describes Snowflake target configuration and ordered acceptance checks; `OMNI_SETUP.md` describes namespace resolution and native semantic import/validation.

The prior archive used for extracted-project execution is identified in [the replay receipt](shipped-project-replay.json). The final archive adds documentation/evidence and navigation improvements with unchanged tested code bytes; its embedded `extracted-project-replay.json` records those file hashes. [Package integrity](package-integrity.json) binds the final archive, and [qualification.json](qualification.json) records the exact accelerator implementation snapshot, including uncommitted changes. The branch parent commit alone does not identify this tested implementation.

To rerun accelerator regression, install the pinned requirements documented in [deployment/platform validation](../deployment-platform-release/README.md), then run `python -m unittest discover -s tests -q` in Python 3.12. The package's independent comparison receipts are results of this agent exercise, not a claim that the full independent oracle is shipped as a general-purpose CLI.

Before deployment, collect real Snowflake catalogue/type/case metadata, select the account/database/schema, run native dbt and independent comparisons, verify allowed/denied roles, import and validate Omni, exercise representative queries and live AI responses, and obtain business acceptance for unresolved definitions. This snapshot provides no CDC/SCD, incremental, production-load or cost qualification.
