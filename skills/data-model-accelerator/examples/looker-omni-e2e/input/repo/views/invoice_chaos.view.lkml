view: invoice_chaos {
  label: "Do Not Touch - Exec Tieout v7"
  derived_table: {
    sql:
WITH
invoice_versions AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY tenant_id, invoice_id ORDER BY source_seq DESC, arrival_seq DESC) AS version_rank
  FROM DMA_SIM.BRONZE.BILLING_INVOICE_CDC
),
invoice_current AS (
  SELECT tenant_id, invoice_id, customer_id, CAST(issued_at AS TIMESTAMP_NTZ) AS issued_at, CAST(gross_cents AS NUMBER(38,0)) AS gross_cents, COALESCE(CAST(discount_cents AS NUMBER(38,0)), 0) AS discount_cents, LOWER(TRIM(status)) AS status, currency
  FROM invoice_versions WHERE version_rank = 1 AND op <> 'DELETE'
),
payment_versions AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY tenant_id, entry_id ORDER BY source_seq DESC, arrival_seq DESC) AS version_rank
  FROM DMA_SIM.BRONZE.BILLING_PAYMENT_CDC
),
payment_current AS (
  SELECT tenant_id, entry_id, invoice_id, CAST(amount_cents AS NUMBER(38,0)) AS amount_cents, LOWER(TRIM(status)) AS status, currency
  FROM payment_versions WHERE version_rank = 1 AND op <> 'DELETE'
),
credit_versions AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY tenant_id, entry_id ORDER BY source_seq DESC, arrival_seq DESC) AS version_rank
  FROM DMA_SIM.BRONZE.BILLING_CREDIT_CDC
),
credit_current AS (
  SELECT tenant_id, entry_id, invoice_id, CAST(amount_cents AS NUMBER(38,0)) AS amount_cents, LOWER(TRIM(status)) AS status, currency
  FROM credit_versions WHERE version_rank = 1 AND op <> 'DELETE'
),
posted_payments AS (
  SELECT tenant_id, invoice_id, currency, SUM(amount_cents) AS payment_cents
  FROM payment_current WHERE status = 'posted'
  GROUP BY tenant_id, invoice_id, currency
),
posted_credits AS (
  SELECT tenant_id, invoice_id, currency, SUM(amount_cents) AS credit_cents
  FROM credit_current WHERE status = 'posted'
  GROUP BY tenant_id, invoice_id, currency
),
customer_history AS (
  SELECT tenant_id, customer_id, CAST(valid_from AS TIMESTAMP_NTZ) AS valid_from,
         CAST(valid_to AS TIMESTAMP_NTZ) AS valid_to, segment
  FROM DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY
)
SELECT i.tenant_id, i.invoice_id, i.customer_id, i.issued_at,
       CAST(CONVERT_TIMEZONE('UTC', 'America/Chicago', i.issued_at) AS DATE) AS invoice_date,
       i.currency, i.status, COALESCE(h.segment, 'Unknown') AS segment,
       i.gross_cents, i.discount_cents, COALESCE(c.credit_cents, 0) AS credit_cents,
       i.gross_cents - i.discount_cents - COALESCE(c.credit_cents, 0) AS net_cents,
       COALESCE(p.payment_cents, 0) AS paid_cents,
       i.tenant_id || ':' || i.invoice_id AS legacy_invoice_key
FROM invoice_current AS i
LEFT JOIN posted_payments AS p ON i.tenant_id = p.tenant_id AND i.invoice_id = p.invoice_id AND i.currency = p.currency
LEFT JOIN posted_credits AS c ON i.tenant_id = c.tenant_id AND i.invoice_id = c.invoice_id AND i.currency = c.currency
LEFT JOIN customer_history AS h ON i.tenant_id = h.tenant_id AND i.customer_id = h.customer_id
  AND i.issued_at >= h.valid_from AND (i.issued_at < h.valid_to OR h.valid_to IS NULL)
    ;;
  }
  dimension: legacy_invoice_key { hidden: yes primary_key: yes type: string sql: ${TABLE}.legacy_invoice_key ;; }
  dimension: tenant_id { hidden: yes type: string sql: ${TABLE}.tenant_id ;; }
  dimension: invoice_id { type: string sql: ${TABLE}.invoice_id ;; }
  dimension: invoice_date { type: date sql: ${TABLE}.invoice_date ;; }
  dimension: currency { type: string sql: ${TABLE}.currency ;; }
  dimension: status { type: string sql: ${TABLE}.status ;; }
  dimension: segment { type: string sql: ${TABLE}.segment ;; }
  dimension: net_cents { hidden: yes type: number sql: ${TABLE}.net_cents ;; }
  dimension: paid_cents { hidden: yes type: number sql: ${TABLE}.paid_cents ;; }
  measure: invoice_count { type: count filters: [status: "posted"] }
  measure: net_cents_sum { type: sum sql: ${net_cents} ;; filters: [status: "posted"] }
  measure: paid_cents_sum { type: sum sql: ${paid_cents} ;; filters: [status: "posted"] }
  measure: payment_rate { type: number sql: ${paid_cents_sum} / NULLIF(${net_cents_sum}, 0) ;; value_format_name: percent_2 }
  measure: net_amount_display { type: number sql: ${net_cents_sum} / 100.0 ;; value_format_name: usd }
}
