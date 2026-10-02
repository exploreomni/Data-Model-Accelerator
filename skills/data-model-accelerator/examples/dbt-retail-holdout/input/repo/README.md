# Retail quick reports: authored legacy dbt project

This is synthetic source evidence for the isolated holdout. No production warehouse or customer export is represented. Read the parent input README and contract.json for business rules and validation constraints.

The staging models contain correct reusable transformations on valid input. The report is intentionally wrong: raw fulfillment and return children are independently one-to-many and its joins create fanout. Do not preserve those inflated values as acceptance truth. The requested refactor should retain useful staging, add input quality checks and a reusable line-grain gold model, then report from that model with downstream filters. Do not apply the line discount a second time.

No credentials or runnable deployment profile are supplied. Choose an isolated local validation profile for the exercise and retain the declared Snowflake source identities. Do not connect to a real warehouse. The dbt tenant variable is merely a report predicate; authorization must be checked independently in the local replay harness.
