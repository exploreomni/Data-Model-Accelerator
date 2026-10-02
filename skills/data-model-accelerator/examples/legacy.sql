-- DELIBERATELY DEFECTIVE LOCAL SQLITE LEGACY DEMONSTRATOR.
-- Looks right for tenant B in January, but latest-arrival CDC ordering loses
-- corrections; filtering tombstones before ranking resurrects deleted rows;
-- using the current segment rewrites historical classification.
CREATE VIEW legacy_report AS
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY tenant_id, invoice_id ORDER BY delivery_id DESC
    ) AS version_position
    FROM bronze_invoice_cdc WHERE operation = 'upsert'
)
SELECT i.tenant_id, i.invoice_id, i.invoice_date,
       substr(i.invoice_date, 1, 7) AS month, h.customer_name, h.segment,
       i.gross_cents, i.paid_cents,
       1.0 * i.paid_cents / NULLIF(i.gross_cents, 0) AS payment_rate
FROM ranked AS i
JOIN customer_history AS h
  ON i.tenant_id = h.tenant_id AND i.customer_id = h.customer_id
 AND h.valid_to IS NULL
WHERE i.version_position = 1 AND i.status = 'posted';
