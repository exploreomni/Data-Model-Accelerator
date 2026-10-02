-- SYNTHETIC CANDIDATE. Local simulation only; full rebuild, not a production incremental deployment.
CREATE OR REPLACE TABLE DMA_SIM.GOLD.FCT_INVOICES AS
WITH posted_payments AS (
  SELECT
    tenant_id,
    invoice_id,
    currency,
    SUM(amount_cents) AS payment_cents
  FROM DMA_SIM.SILVER.BILLING_PAYMENTS
  WHERE
    status = 'posted'
  GROUP BY
    tenant_id,
    invoice_id,
    currency
), posted_credits AS (
  SELECT
    tenant_id,
    invoice_id,
    currency,
    SUM(amount_cents) AS credit_cents
  FROM DMA_SIM.SILVER.BILLING_CREDITS
  WHERE
    status = 'posted'
  GROUP BY
    tenant_id,
    invoice_id,
    currency
)
SELECT
  i.tenant_id,
  i.invoice_id,
  i.customer_id,
  i.issued_at,
  CAST(CONVERT_TIMEZONE('UTC', 'America/Chicago', i.issued_at) AS DATE) AS invoice_date,
  i.currency,
  i.status,
  i.gross_cents,
  i.discount_cents,
  COALESCE(c.credit_cents, 0) AS credit_cents,
  i.gross_cents - i.discount_cents - COALESCE(c.credit_cents, 0) AS net_cents,
  COALESCE(p.payment_cents, 0) AS paid_cents,
  MD5(i.tenant_id || ':' || i.invoice_id) AS invoice_key,
  COALESCE(h.customer_key, MD5(i.tenant_id || ':__UNKNOWN__')) AS customer_key
FROM DMA_SIM.SILVER.BILLING_INVOICES AS i
LEFT JOIN posted_payments AS p
  ON i.tenant_id = p.tenant_id
  AND i.invoice_id = p.invoice_id
  AND i.currency = p.currency
LEFT JOIN posted_credits AS c
  ON i.tenant_id = c.tenant_id
  AND i.invoice_id = c.invoice_id
  AND i.currency = c.currency
LEFT JOIN DMA_SIM.GOLD.DIM_CUSTOMERS AS h
  ON i.tenant_id = h.tenant_id
  AND i.customer_id = h.customer_id
  AND i.issued_at >= h.valid_from
  AND (
    i.issued_at < h.valid_to OR h.valid_to IS NULL
  );
