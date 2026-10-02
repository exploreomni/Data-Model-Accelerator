-- LOCAL SQLITE: query parameters test filtering, not authorization or RLS.
SELECT tenant_id, invoice_id, invoice_date, month, customer_name, segment,
       gross_cents, paid_cents,
       1.0 * paid_cents / NULLIF(gross_cents, 0) AS payment_rate
FROM gold_invoice_fact
WHERE status = 'posted'
  AND (:tenant_id IS NULL OR tenant_id = :tenant_id)
  AND (:segment IS NULL OR segment = :segment)
  AND (:month IS NULL OR month = :month)
  AND (:invoice_id IS NULL OR invoice_id = :invoice_id)
ORDER BY tenant_id, invoice_id
