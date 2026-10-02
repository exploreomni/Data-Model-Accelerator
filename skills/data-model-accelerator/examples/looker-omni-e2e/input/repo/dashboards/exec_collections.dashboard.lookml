- dashboard: exec_collections_legacy
  title: Executive Collections Reconciliation
  layout: newspaper
  preferred_viewer: dashboards-next
  filters:
  - name: Reporting Date
    title: Reporting Date
    type: field_filter
    default_value: 2026/09/01 to 2026/09/30
    model: billing
    explore: invoice_chaos
    field: invoice_chaos.invoice_date
  - name: Currency
    title: Currency
    type: field_filter
    default_value: USD
    model: billing
    explore: invoice_chaos
    field: invoice_chaos.currency
  elements:
  - name: legacy_collections_by_segment
    title: Collections by historical customer segment
    model: billing
    explore: invoice_chaos
    type: looker_grid
    fields: [invoice_chaos.segment, invoice_chaos.invoice_count, invoice_chaos.net_cents_sum, invoice_chaos.paid_cents_sum, invoice_chaos.payment_rate]
    filters:
      invoice_chaos.status: posted
    listen:
      Reporting Date: invoice_chaos.invoice_date
      Currency: invoice_chaos.currency
    sorts: [invoice_chaos.segment]
    limit: 500
