connection: "synthetic_billing_snowflake"
include: "/views/*.view.lkml"
include: "/dashboards/*.dashboard.lookml"
explore: invoice_chaos {
  label: "Executive Collections Reconciliation"
  access_filter: { field: invoice_chaos.tenant_id user_attribute: tenant_id }
}
