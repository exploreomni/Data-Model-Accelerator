-- LOCAL SQLITE DEMONSTRATOR ONLY. Not warehouse deployment SQL.
-- Source replication and source_sequence reliability are fixture assumptions.
CREATE VIEW silver_invoice_current AS
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY tenant_id, invoice_id
        ORDER BY source_sequence DESC, delivery_id DESC
    ) AS version_position
    FROM bronze_invoice_cdc
)
SELECT tenant_id, invoice_id, customer_id, invoice_date, status,
       gross_cents, paid_cents, source_sequence
FROM ranked
WHERE version_position = 1 AND operation = 'upsert';

CREATE VIEW gold_invoice_fact AS
SELECT i.tenant_id, i.invoice_id, i.customer_id, i.invoice_date,
       substr(i.invoice_date, 1, 7) AS month,
       h.tenant_id AS dimension_tenant_id,
       h.customer_name, h.segment, i.status,
       i.gross_cents, i.paid_cents
FROM silver_invoice_current AS i
JOIN customer_history AS h
  ON i.tenant_id = h.tenant_id
 AND i.customer_id = h.customer_id
 AND i.invoice_date >= h.valid_from
 AND (h.valid_to IS NULL OR i.invoice_date < h.valid_to);
