view: invoices {
  sql_table_name: ANALYTICS.invoice_reporting ;;
  dimension: tenant_id { type: string sql: ${TABLE}.tenant_id ;; }
  dimension: invoice_id { type: string sql: ${TABLE}.invoice_id ;; }
  dimension: status { type: string sql: ${TABLE}.status ;; }
  dimension: net_cents { type: number sql: ${TABLE}.net_cents ;; }
  measure: net_amount {
    type: sum
    sql: ${net_cents} ;;
    filters: [status: "posted"]
  }
  measure: paid_amount {
    type: sum
    sql: ${TABLE}.paid_cents ;;
    filters: [status: "posted"]
  }
  measure: payment_rate {
    type: number
    sql: ${paid_amount} / NULLIF(${net_amount}, 0) ;;
  }
}
