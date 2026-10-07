# Three-workbook Hex migration qualification

This case tests Revenue exploration, Customer retention and Executive performance, plus a versioned shared component. It is authored synthetic native-format content, not an export from a Hex tenant. The initial extraction and model candidates were authored during development; each replay parses and tests those artifacts rather than generating a new migration autonomously.

## Run

From the package root with Python 3.12:

```sh
python3.12 -m venv /tmp/dma-hex-env
/tmp/dma-hex-env/bin/python -m pip install -r skills/data-model-accelerator/scripts/requirements-hex-e2e.txt
/tmp/dma-hex-env/bin/python skills/data-model-accelerator/scripts/run_hex_omni_e2e.py --output /absolute/new-hex-run
/tmp/dma-hex-env/bin/python -m unittest discover -s tests -v
```

The output directory must not exist and must be outside `examples/hex-omni-e2e`. Core tests remain compatible with Python3.9 and skip optional engine tests when those dependencies are absent. Do not interpret a skipped optional test as qualified support.

## What is executed

1. Validate four native YAML documents against a pinned Hex v3 schema. Preserve three project IDs, one component ID/version, 24 cell IDs, SQL/Python expressions, inputs/defaults, app/chart references and dependency edges. Missing components, unsupported code and identity ambiguity are gaps. See [the source contract](hex-source-contract.md).
2. Check four synthetic raw catalogue objects and 23 columns against pinned metadata receipts, bootstrap DDL, source references and supplied rows. Three objects are authored warehouse reads. ADJUSTMENTS is a proposed governed landing for an explicitly inventoried CSV; it is not silently represented as an existing Hex warehouse input.
3. Replay reviewed source SQL and Python in a new local environment per project. Python uses an AST interpreter supporting the fixture's pandas merge, fillna, integer casts and arithmetic; imports, eval/exec, arbitrary file/network access and other statements are not executed. Component versions must resolve exactly. The replay does not reproduce Hex's scheduler or every pandas dtype behavior.
4. Render the seven candidate dbt models' supported `source`, `ref` and explicit config calls, then execute their Snowflake SQL subset in DuckDB. This renderer is not dbt's compiler. Full rebuilds simulate duplicate/out-of-order input replay and late changes; they are not incremental warehouse deployment.
5. Read three native-format Omni views, relationships, a billing topic and the companion report selections. Execute their selected dimension/measure/filter definitions locally. The companion `report-context.json` is not a native Omni app/dashboard artifact. The standalone retention topic is authored but not independently queried by the three selected billing-topic reports.
6. Compare 10 invoice rows, 10 customer-month rows and 13 source/target report scenarios against the frozen independent oracle. Check actual built columns against the 11-model/74-column inventory, dictionary and ERD/layer-document coverage. Run nine authored dbt SQL assertions locally.

## Required behavior and negative controls

The predeclared plan has 125 checks. It includes tenant collisions, source CDC sequence ordering/tombstones, temporal segment boundaries, duplicate history replays, manual adjustments, net/paid/outstanding cents, zero denominators, empty/equal date windows, segment filtering, input overrides and retained what-if logic. Missing expected-file pins, removed cells, changed outputs or a shortened required-test inventory cannot silently produce a complete run.

Twenty-four negative controls include five rejected contexts at both source and target boundaries, conflicting CDC versions, overlapping history, orphan customers, duplicate/missing adjustment content, unsafe Python/file/SQL operations, incorrect tenant joins, changed source/target formulas, omitted target access filtering and cancelling adjustment errors. A negative control passes only when the expected defect is caught by the intended assertion. Additional unit tests exercise omitted cells/components, component version drift, duplicate identities, quoted Snowflake case, changed model destinations, hooks, very large cents and header-only CSVs.

The distinct definitions of `active_customers` are preserved as proposed `invoiced_active_customers` and `paying_active_customers`. No canonical definition is selected by the agents. The cohort is an explicitly documented invoice-date proxy based on current payments at a snapshot; it is not historical payment-event-time retention. What-if multipliers remain exploration logic.

## Precision and execution boundaries

DuckDB dataframe conversion and pandas nullable joins can introduce floating-point coercion. The local interpreter uses exact integer/Decimal materialization and object-backed Python integers for adjustments and arithmetic. This protects local test values; actual Hex/pandas images and native conversions still need validation. Raw numeric inputs are bounded to signed64-bit values in the local loader; Snowflake NUMBER(38,0) supports a different numeric domain.

The proposed raw DDL and metadata use VARCHAR dates and physically nullable columns. The local loader applies declared DATE conversions and validates logically required values before execution. Native raw date parsing/null enforcement remains a separate source-contract qualification. Synthetic persona predicates do not prove warehouse grants, masking or Omni/Hex access enforcement.

Public Hex YAML excludes outputs; real migrations need separately captured result evidence with input values, component/project versions, execution mode, identity, watermark and environment. [Hex export documentation](https://learn.hex.tech/docs/explore-data/projects/import-export). Hex dependency execution and published-app cell behavior require native checks. [Hex execution model](https://learn.hex.tech/docs/explore-data/projects/project-execution/execution-model).

## Review evidence

The runner writes fresh comparisons, queries and catalogue bindings to its selected output directory. See [qualification and reproduction](../../../docs/qualification.md) for the separate dbt checks and historical records. The [fixture pins](../examples/hex-omni-e2e/fixture-pins.json) protect the reviewed execution inputs; they are not a completed review package. The [model documentation](../examples/hex-omni-e2e/documentation/README.md) includes ERD, complete dictionary, lineage, placement/conflict decisions and bronze/silver/gold operating contracts.

Native dbt parse is recorded independently from this runner. It can establish project/schema/macro parsing without a warehouse connection, but it does not establish native compilation, query execution, correctness, deployment or business approval. Do not substitute it for those gates.
