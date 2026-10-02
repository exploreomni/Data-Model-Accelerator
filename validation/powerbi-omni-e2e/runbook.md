# Power BI pilot qualification and handoff

The delivered state is a locally validated candidate. The source, warehouse and semantic models have no supplied production owner or human approval. The fixture namespace DMA_POWERBI and synthetic account must not be mistaken for a deployment destination.

## Reproduce local evidence

Use the [exercise guide](../../skills/data-model-accelerator/references/powerbi-omni-e2e.md) and pinned Python 3.12 dependencies. Run the unit suite and integrated runner into a new output directory. Check all registered IDs, actual failure reasons, source hashes, catalogue bindings, full fact rows, all 22 contexts and documentation coverage. Preserve any failed run; do not edit expected results to obtain a pass.

The optional native dbt parse uses a temporary profile with static dummy values, disabled telemetry and isolated output/log directories. It establishes project/config/macro syntax and dependency resolution only. The 73 parsed test nodes are not 73 executed warehouse tests; the local pilot executes nine singular SQL assertions.

## Qualify a real Power BI source

Obtain an authorized PBIP/model/report export, an independently captured content inventory, role/member evidence, aligned source data and raw metadata catalogue. Match file versions and hashes. Reconcile remote models, PBIX/TMDL, pending changes, dataflows, gateways, incremental refresh, relationships, time intelligence, bookmarks, interactions and paginated reports. The current parser must flag unsupported behavior; route it to a specialist or a native validation step before claiming completeness.

Open and validate the actual model/report in supported native tooling. Capture native M/DAX output for each selected report contract, including totals, BLANK rows, empty contexts and source-role personas. A local assumed result cannot substitute for this native baseline. Separate observed source behavior from approved business corrections.

## Qualify the target

Bind each proposed physical source and column to an authorized Snowflake catalogue snapshot. Review CSV ingestion ownership and retention, tenant keys, history, refresh/deletes, quality contracts and naming. Use an approved development schema/role to compile and execute the candidate dbt models and tests. Reconcile rows and slices to native source output, including late arrivals, tombstones, duplicate/replayed batches and recovery.

Validate the candidate Omni model and queries in a development tenant. Focus on dual-table tenant filters, selective segment LOD, replace-versus-intersect status measures, empty outer contexts, recomputed totals and disconnected selector defaults. The companion is local metadata; native workbook controls and table/card behavior require an actual implementation and acceptance evidence. Capture permitted/denied persona results without treating role declarations as proven service enforcement.

## Approval, cutover and recovery

The business authority must approve metric meaning and acceptable changes. Operational owners must accept ingestion, model/semantic maintenance, permissions, freshness, cost/performance, observability and recovery. Record approvals against the exact source snapshot, ERD, dictionary, layer guides, target diff and test artifacts.

After separately authorized deployment, use an isolated pilot domain and a reversible parallel run. Validate cutover consumers, schedules, credentials, role memberships and export/subscription dependencies. Maintain the original source report and previous target revision until acceptance is confirmed. Define the actual rollback commands and recovery point for the selected environment before promotion; this synthetic package provides no live deployment or rollback instruction. Source retirement is a separate approved action.
