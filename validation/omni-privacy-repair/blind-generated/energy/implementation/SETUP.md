# Candidate setup — bigquery

This is a dbt source/ref project, not SQL for direct pasting into the warehouse console.
Five views execute bronze → silver → gold. No macros, hooks, packages, seeds, ingestion changes or native DDL are included. The CSV snapshots remain outside this package.

All source names and destination `synthetic-review.dma_energy` are synthetic placeholders. A future operator must select a dbt bigquery adapter and supported core version, set a separate nonsecret/profile configuration for database/project, schema/dataset, location/warehouse and authenticated identity, load or bind the exact supplied raw CSV snapshots with lexical text columns, and establish classification, ownership and access before any target execution. Credentials belong outside this project. Local library versions are in ../../runtime.json; neither warehouse adapter nor live profile was qualified.

After separate native authorization: configure the target schema/dataset as `dma_energy`, run `dbt parse`, review the complete manifest, then `dbt build --target <authorized-development-target>` without a narrowed selector. Capture manifest/run-results, native catalogue readback and access tests. No such command was run here. Defaults are views and resource-scoped `persist_docs: false`; proposed descriptions are documentation only.

Invalid numeric/date casts fail; there is no arbitrary deduplication. Stop on uniqueness, not-null or orphan test failures. Full replacement views provide current-snapshot behavior only; there is no CDC, history or incremental claim. Rollback removes only reviewed candidate objects after consumer impact review; no automatic DROP is delivered.
