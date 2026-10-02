connection: "synthetic_analytics"
include: "../views/*.view.lkml"

explore: invoices {
  access_filter: {
    field: invoices.tenant_id
    user_attribute: tenant_id
  }
}
