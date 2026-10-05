# Access enforcement contracts

`scripts/security_contract.py` compares a reviewed access contract, an existing
policy snapshot, the proposed snapshot, a native readback, and effective persona
observations. It performs no warehouse queries, grants, revokes, or policy writes.
An unchanged, fully matched bundle returns `locally_consistent`; imported JSON
does not authenticate the identity, execution, or origin of that evidence.

## Run the local comparison

```sh
python scripts/security_contract.py \
  --contract /runner/security/contract.json \
  --current /runner/security/current.json \
  --candidate /runner/security/candidate.json \
  --readback /runner/security/readback.json \
  --observations /runner/security/observations.json \
  --output /runner/security/comparison.json
```

Run from the skill directory. The output must be a new file; it is written with
private permissions. Public Python entry points are `validate_contract`,
`validate_state`, `state_hash`, `review_hash`, `expected_context`, and
`evaluate_access(contract, current, candidate, readback=None, observations=None)`.
`tests/test_security_contract.py` provides a runnable synthetic schema example;
the independent test file uses a separately authored example.

## What must be frozen

The version 1 `security_contract` contains the migration scope; exact source,
catalogue, candidate, target, policy and scope hashes; warehouse and framework;
destination identity; hashes of both policy states; an execution snapshot hash;
personas; a complete test-case inventory; and a review that hashes the contract
without its review member. Review references are declarations, not signatures.

Each `security_state` binds the same destination and six hashes. Its complete
resource inventory records exact namespaces, user/group grants, allowed actions,
row-policy hashes, column classification/mask/deny rules, metadata visibility,
inherited controls, and a policy that denies newly introduced columns. UNKNOWN
columns must remain denied. Opaque policy hashes are compared conservatively;
the comparator cannot prove that a changed policy expression is safer.

Every selected resource and persona requires positive, negative, and unexpected
group tests on every applicable path, plus missing-attribute tests when required
attributes exist. The paths are warehouse query and metadata; Omni query, drill,
and cache; and dashboard, export, share, and cache. Grant-denied paths explicitly
expect denial. Denial must expose no rows, columns, masks, metadata, or canaries.
Visible metadata cannot include metadata-hidden columns. Observations bind the
exact principal, groups, attribute-value hashes, destination, snapshot, resource,
path, and probe hash. They contain outcome summaries, not raw result rows.

The readback must match the full proposed state. Missing evidence is `pending`;
unexpected outcomes are `failed`. Stale bindings, broadened permissions,
removed protections, and malformed contracts are `blocked`. Even a restrictive
policy change is blocked with `security.policy_provisioning_unqualified`: a
qualified security operator must apply and inspect the controls, then freeze a
new existing-state contract. No local result authorizes protected deployment.

Keep the contract and evidence bundle outside the frozen generated candidate to
avoid circular hashes. The contract's policy binding identifies an independent
normalized policy/configuration snapshot. A release authority can separately
bind the full access bundle, disclosure policy and runner policy, then require
authenticated evidence from an approved external issuer. Hash agreement alone
does not establish native enforcement or compliance.

## Platform and framework boundaries

`scripts/security_capabilities.py` exposes
`capabilities(warehouse, framework='native_sql')`. It accepts Snowflake,
Databricks, BigQuery, Redshift, ClickHouse and MotherDuck, with native SQL, dbt
(`dbt_core`/`dbt_platform` aliases), or Coalesce. Vendor-documented controls,
the implemented offline comparison, local testing, and live qualification are
separate fields. All live qualification flags remain false. Automatic policy
provisioning, automatic GRANT/REVOKE, policy loosening, and authentication from
imported JSON remain unsupported.

dbt metadata, Coalesce node metadata, warehouse comments, labels, and semantic
field hiding do not establish access enforcement. Read the selected capability
record for the exact native inspection recipe. In each warehouse, inspect the
complete effective grants, policy definitions/assignments and inheritance with
adequate visibility, then execute the frozen positive and negative persona
probes. A privilege-limited empty inventory is not proof that no policy exists.
Test Omni audience, access filters, drill, export, sharing and cache behavior
separately from the warehouse session identity.

## Official references and qualification cautions

Documentation was checked on 2026-10-05; qualify the exact destination's edition,
runtime, privileges, object types and regional constraints before use.

| Platform | Documented controls and qualification boundary |
| --- | --- |
| Snowflake | [Column security](https://docs.snowflake.com/en/user-guide/security-column-intro) and [policy references](https://docs.snowflake.com/en/sql-reference/functions/policy_references): verify edition and privilege-scoped visibility, not just tags. |
| Databricks | [Row filters and masks](https://docs.databricks.com/aws/en/data-governance/unity-catalog/filters-and-masks/) and [ABAC requirements](https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac/requirements): pin cloud, metastore, runtime and compute; qualify object support and any Beta dependency separately. |
| BigQuery | [Row security](https://docs.cloud.google.com/bigquery/docs/row-level-security-intro) and [column masking](https://docs.cloud.google.com/bigquery/docs/column-data-masking-intro): inspect IAM, policy tags and data policies. Data governance tags are Preview; ordinary labels do not enforce access. |
| Redshift | [Database security objects](https://docs.aws.amazon.com/redshift/latest/dg/r_Database_objects.html) and [masking considerations](https://docs.aws.amazon.com/redshift/latest/dg/t_ddm-considerations.html): preserve role inheritance and policy priority; row security precedes masking. |
| ClickHouse | [Row policies](https://clickhouse.com/docs/reference/statements/create/row-policy) and [masking policies](https://clickhouse.com/docs/reference/statements/create/masking-policy): masking is documented; pin server/version/engine/cluster and ensure all intended users are covered. |
| MotherDuck | [Capabilities](https://motherduck.com/product/pricing/) and [sharing](https://motherduck.com/docs/key-tasks/sharing-data/sharing-overview): current documentation includes table-level access and custom roles. Required row/column controls remain unqualified in this adapter; local DuckDB execution cannot prove remote protection. |
| Omni | [Access filters](https://docs.omni.co/modeling/topics/parameters/access-filters): exact user attributes, document audience and all downstream paths need effective tests; field hiding alone is not a security control. |

These checks support a security review; they do not certify PCI, HIPAA, or another
regulatory standard. Keep protected-input disclosure decisions separate from
warehouse enforcement and native acceptance evidence.
