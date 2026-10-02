# Looker → Snowflake → Omni: bounded syntax contract

Primary documentation checked **2026-09-09**. The fragments below adapt documented syntax for a synthetic billing domain. They define a subset an offline renderer may exercise; they are not outputs from native Looker or Omni validation.

## Preserve the Looker behavior being moved

In a `.view.lkml` file, a SQL derived table has `derived_table: { sql: … ;; }`. Its SQL refers to physical tables/columns, with separately documented mechanisms for derived-table references and Liquid. Extract the query and dependencies without executing source-supplied code. [Looker derived-table SQL](https://docs.cloud.google.com/looker/docs/reference/param-view-sql-for-derived-table)

```lookml
view: invoices {
  derived_table: {
    sql: SELECT tenant_id, invoice_id, status, net_cents, paid_cents
         FROM DMA_SIM.LEGACY.INVOICE_REPORTING ;;
  }
  dimension: tenant_id { type: string sql: ${TABLE}.tenant_id ;; }
  dimension: status { type: string sql: ${TABLE}.status ;; }
  dimension: net_cents { type: number sql: ${TABLE}.net_cents ;; }
  dimension: paid_cents { type: number sql: ${TABLE}.paid_cents ;; }
  measure: net_amount {
    type: sum
    sql: ${net_cents} / 100.0 ;;
    filters: [status: "posted"]
  }
  measure: paid_amount {
    type: sum
    sql: ${paid_cents} / 100.0 ;;
    filters: [status: "posted"]
  }
  measure: payment_rate {
    type: number
    sql: ${paid_amount} / NULLIF(${net_amount}, 0) ;;
  }
}
```

Measure filters constrain their constituent aggregates. Keep `posted` on both sums; `filters` on a Looker `type: number` compound measure does not work. Preserve query filters, null behavior, and ratio grain separately. [Looker field filters](https://docs.cloud.google.com/looker/docs/reference/param-field-filters)

An Explore's security filter is distinct from report filters. Attribute definitions and user/group assignments are administrative evidence absent from these files. Missing attribute values cause errors, including for administrators. [Looker access_filter](https://docs.cloud.google.com/looker/docs/reference/param-explore-access-filter)

```lookml
explore: invoices {
  access_filter: {
    field: invoices.tenant_id
    user_attribute: tenant_id
  }
}
```

LookML dashboards are YAML `.dashboard.lookml` files. Element `filters` are fixed query restrictions; `listen` maps a dashboard filter name to the field it affects on that element. Preserve each mapping independently, plus default values and query fields. [Building LookML dashboards](https://docs.cloud.google.com/looker/docs/building-lookml-dashboards), [single-value element](https://docs.cloud.google.com/looker/docs/reference/param-lookml-dashboard-single-value-chart)

```yaml
- dashboard: billing
  title: Billing
  layout: newspaper
  filters:
  - name: Status
    title: Status
    type: field_filter
    model: billing
    explore: invoices
    field: invoices.status
    default_value: posted
  elements:
  - name: payment_rate
    title: Payment rate
    type: single_value
    model: billing
    explore: invoices
    fields: [invoices.payment_rate]
    filters:
      invoices.tenant_id: tenant_a
    listen:
      Status: invoices.status
```

The example's fixed `tenant_a` is a report restriction, never authorization. A persona's access filter still applies. Do not infer a full dashboard estate from these files; user-defined dashboards, runtime overrides, connection settings, and schedules need separate evidence.

## Omni views, fields, and measures

Native YAML model filenames include `<name>.view`, `<name>.topic`, and special files `model` and `relationships`. Existing schema-qualified view names and file paths must come from the model mapping; a local filename does not establish a live model ID. [Model YAML contract](https://docs.omni.co/api/models/create-or-update-yaml-files), [lineage mapping](https://docs.omni.co/guides/api/data-lineage-integration)

Candidate `invoices.view` maps explicitly to a Snowflake table through `catalog`, `schema`, and `table_name`. An alternative view can use top-level `sql: |` with a SELECT; do not substitute Looker's `sql_table_name`. [Catalog](https://docs.omni.co/modeling/views/parameters/catalog), [table_name](https://docs.omni.co/modeling/views/parameters/table-name), [view SQL](https://docs.omni.co/modeling/views/parameters/sql)

```yaml
catalog: DMA_SIM
schema: GOLD
table_name: FCT_INVOICES

dimensions:
  invoice_key:
    sql: '"INVOICE_KEY"'
    primary_key: true
  customer_key:
    sql: '"CUSTOMER_KEY"'
  tenant_id:
    sql: '"TENANT_ID"'
  status:
    sql: '"STATUS"'
  net_amount_usd:
    sql: '"NET_AMOUNT_USD"'
  paid_amount_usd:
    sql: '"PAID_AMOUNT_USD"'

measures:
  net_amount:
    sql: ${invoices.net_amount_usd}
    aggregate_type: sum
    filters:
      status:
        is: posted
  paid_amount:
    sql: ${invoices.paid_amount_usd}
    aggregate_type: sum
    filters:
      status:
        is: posted
  payment_rate:
    sql: ${paid_amount} / NULLIF(${net_amount}, 0)
```

Use raw physical SQL for a dimension's own source column; `${field}` references another modeled field and a self-reference would cycle. Single YAML quotes above preserve the SQL double quotes. Existing quoted mixed-case physical columns require their exact case. Field names remain lowercase snake_case. [Dimensions](https://docs.omni.co/modeling/dimensions), [physical SQL example](https://docs.omni.co/modeling/measures/parameters/markdown), [Snowflake identifiers](https://docs.snowflake.com/en/sql-reference/identifiers-syntax)

`aggregate_type: sum` supplies aggregation; filtered sums use `filters` keyed by dimensions. A compound ratio references aggregate measures without another sum. [Measures](https://docs.omni.co/modeling/measures), [single-measure filters](https://docs.omni.co/guides/modeling/single-field-filter)

Candidate `customers.view` uses the same mapping pattern for `DIM_CUSTOMERS`, exposing a tested `customer_key` primary key and any needed tenant/business attributes. `primary_key: true` and relationship cardinality inform Omni's aggregation behavior but do not prove the data satisfies them. Prejoined fanout can destroy the relationship context; fix upstream grain before applying this simple model. [Primary keys](https://docs.omni.co/modeling/dimensions/parameters/primary-key), [symmetric aggregates](https://docs.omni.co/analyze-explore/sql/symmetric-aggregates)

## Relationships, topics, and user attributes

The special `relationships` file is a top-level YAML list:

```yaml
- join_from_view: invoices
  join_to_view: customers
  join_type: always_left
  on_sql: ${invoices.customer_key} = ${customers.customer_key}
  relationship_type: many_to_one
```

This assumes the warehouse keys already include tenant identity. If they do not, the join must include tenant and local ID explicitly. `joins` exposes the relationship in candidate `billing.topic`; defining a relationship and exposing a topic join are distinct steps. [Relationships and joins](https://docs.omni.co/modeling/relationships)

```yaml
base_view: invoices
label: Billing
joins:
  customers: {}
access_filters:
  - field: invoices.tenant_id
    user_attribute: tenant_id
```

Omni uses plural `access_filters`; `user_attribute` names an attribute configured outside this YAML. Missing values raise errors; matching is exact unless SQL-like wildcards are enabled. Do not invent a top-level `user_attributes` registry or bypass values. In SQL contexts that support attributes, documented interpolation is `{{ omni_attributes.<name> }}`; use the declarative access filter for this example. [Access filters](https://docs.omni.co/modeling/topics/parameters/access-filters), [data access control](https://docs.omni.co/modeling/develop/data-access-control), [topic relationships and attribute syntax](https://docs.omni.co/modeling/topics/parameters/relationships)

## SQL references and evidence limits

Model expressions use `${view.field}` or same-view `${field}`. Omni SQL is an abstraction over dialect SQL; SQL tabs run directly against the database and bypass the model. Preserve whether evidence came from a modeled query or a raw SQL tab. Never present raw SQL parity as proof of topic security. [Writing SQL in Omni](https://docs.omni.co/analyze-explore/sql), [SQL generation](https://docs.omni.co/analyze-explore/sql/generation)

An offline renderer may support only these mappings, scalar dimensions, filtered sums, compound ratios, one tested many-to-one join, and exact tenant attributes. Reject other constructs explicitly; do not silently drop Liquid, inheritance, symmetric aggregation, advanced filters, or temporal semantics. Local YAML parsing and SQL execution demonstrate that subset only. Native model validation, source/runtime query comparisons, role/attribute assignment, and negative persona tests remain required before production acceptance. Omni's documented model-validation endpoint returns model/branch issues; it is separate evidence and is not invoked by this simulation. [Validate model](https://docs.omni.co/api/models/validate-model)
