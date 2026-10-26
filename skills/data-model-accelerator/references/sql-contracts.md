# Deterministic SQL contracts before review

Run `scripts/sql_contracts.py` on every authored dbt batch **before** dispatching an independent
reviewer. It catches mechanical defects in seconds, so the reviewer can spend its budget on logic,
assumptions and business meaning. It never compiles, executes or reads data, and a clean report is
not a review, compilation or parity result.

```sh
python scripts/sql_contracts.py --models /candidate/models \
  --upstream /read-only/target-project/models \
  --contract /engagement/sql-contract.json --output /engagement/new-sql-contract-report.json
```

The console prints one summary line; the full report goes to `--output`, which must be a new file.
Exit code 1 means an error-level finding. Candidate models shadow upstream models with the same name.

## Checks

| Code | Severity | Meaning |
|---|---|---|
| `column.missing` | error | A qualified reference `alias.column` does not exist in the CTE or `ref()`'d model the alias points to. Macro arguments (for example surrogate-key column lists) are read as SQL. |
| `key.missing` | error | A declared shared key is not an output of a model listed for it. |
| `key.construction_mismatch` | error | A declared key's defining expression does not match its `pattern`. |
| `key.divergent_definition` | warning | The same `*_natural_key`, `*_key` or `*_fk` column is built with a differently shaped expression in different models (input column names may differ; normalisation, casing or composition differ). |
| `fk.model_missing` / `fk.column_missing` | error | A declared foreign key or its target column does not exist. |
| `fk.population_unconfirmed` | warning | The target model (or its refs, three levels deep) filters rows (`WHERE`, `QUALIFY`). Rows those filters exclude can leave dangling keys. Confirm and record `population_resolution`, or resolve the key through the target itself. |
| `literal.unknown_value` | error | A string compared to a column (`=`, `!=`, `IN`, `NOT IN`) is not in that column's supplied `known_values`. |
| `literal.unverified` | info | A compared string has no supplied value domain. Profile the column or supply catalogue values. |

## Contract

```json
{
  "schema_version": 1,
  "keys": [
    {"id": "agent", "column": "customer_support_agent_hashed_natural_key",
     "models": ["int_customer_support__agent", "wh_customer_support__agent_dim"],
     "pattern": "lower\\(trim\\("}
  ],
  "foreign_keys": [
    {"model": "wh_voice_of_customer__csat_fct", "column": "customer_support_contact_fk",
     "target_model": "wh_customer_support__contact_fct", "target_column": "customer_support_contact_pk",
     "population_resolution": null}
  ],
  "known_values": {"freshdesk_ticket_team_assigned": ["support [ticket]", "support [chat]"]}
}
```

Declare a key once when more than one model builds it, and every foreign key whose target filters
rows. `known_values` must come from a catalogue, profile or reviewed source, never from the candidate
being checked. A `population_resolution` records a reviewed reason; it is not approval.

## Limits

The reader is bounded and dialect-light. Unqualified references, nested subqueries, dynamic Jinja
(loops, `set`, macros without literal arguments) and `SELECT *` over unresolvable relations are
reported as coverage (`unresolved_relations`, `models_with_unresolved_outputs`), never as passes.
Keep `authoring_provenance` literal classification, dbt compilation, data tests and the independent
review as separate evidence.
