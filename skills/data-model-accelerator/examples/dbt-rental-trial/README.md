# Independent rental refactoring trial

A synthetic messy dbt project refactored into five models by an engineering agent
that did not receive the independent oracle. See the [qualification record](../../../../validation/analytics-engineering/README.md)
and [workflow guide](../../../../docs/analytics-engineering-workflow.md).

- `input/`: original project, synthetic raw catalogue, accepted fixture rules and
  reviewed model/file-ownership specification.
- `oracle/`: independent source calculations, expected exports and acceptance
  queries, frozen before implementation.
- `candidate/`: staging, intermediate and mart models, tests, semantic placement,
  ERD, dictionaries and documentation for all three layers.
- `fixture-pins.json`: complete file inventory for replay inputs; changing either
  expectations or candidate code requires a reviewed pin update.

Replay is local DuckDB only. Snowflake/Omni, real RLS and production acceptance
are separate qualifications. Do not use this tiny fixture as a general accuracy
or success-rate claim.
