# Scoped SQL contracts before review

Use the existing authoring observation for a changed dbt batch. Add optional `sql_rules`
to its `authoring_contract` when reviewed shared keys, foreign keys or value domains are
available. The same observation carries these findings, exact candidate/source hashes,
dialect, unresolved assumptions and checker version. Do not dispatch a second reviewer
or rescan every source just to run the same checks.

```json
{
  "sql_rules": {
    "contract": {
      "schema_version": 1,
      "keys": [{"id":"customer","column":"customer_key","models":["dim_customers"]}],
      "foreign_keys": [{"model":"fct_orders","column":"customer_key",
                        "target_model":"dim_customers","target_column":"customer_key"}],
      "known_values": {"fct_orders.status":["posted","cancelled"]}
    },
    "upstream_paths": ["models/staging/stg_orders.sql"]
  }
}
```

The snippet is an optional extension to the existing contract, not a standalone authoring
contract. SQL rule model names identify registered SQL file stems; ambiguous names remain
gaps. Scope upstream paths explicitly. Value domains must come from an independent catalogue,
profile or reviewed source. Qualify them by model/column; an unqualified column name is not
permission to apply one business domain to unrelated sources. Population acknowledgements
record rationale; they are not data tests or approval.

For an isolated diagnostic, the compatibility CLI remains available:

```sh
python scripts/sql_contracts.py --models /candidate/models \
  --upstream /read-only/models --dialect snowflake \
  --contract /engagement/sql-contract.json --output /engagement/new-report.json
```

The checker uses the shared static dbt reference reader and SQLGlot. It never executes
macros or flattens dynamic control flow into pretend SQL. It checks resolvable projections,
qualified references, declared keys, foreign-key target populations and supplied value
domains. Key expression comparisons preserve inputs and literals. Missing parsers, unknown
dialects, dynamic templates, unresolved stars/relations and unsupported expressions remain
coverage gaps. A partial or unsupported result is not a pass; an unknown output is not a
proven missing key. Reports omit literal values and SQL snippets.

Authoring checks reuse only process-local passing observations whose candidate bytes,
source bytes, contract, dialect and checker/dependency versions still match. Changed tasks
or dependencies are checked again. No saved report or cache grants approval. The reviewer
receives the checked scope **and all unresolved findings**, with source/design evidence for
semantic review. Provisional code remains available. Native compilation, runtime tests,
fanout checks, numerical parity and business acceptance remain separate evidence.
