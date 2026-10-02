-- SYNTHETIC CANDIDATE. Local simulation only; full rebuild, not a production incremental deployment.
CREATE OR REPLACE TABLE DMA_SIM.SILVER.BILLING_INVOICES AS
WITH invoice_versions AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY tenant_id, invoice_id ORDER BY source_seq DESC, arrival_seq DESC) AS version_rank
  FROM DMA_SIM.BRONZE.BILLING_INVOICE_CDC
)
SELECT
  tenant_id,
  invoice_id,
  customer_id,
  CAST(issued_at AS TIMESTAMPNTZ) AS issued_at,
  CAST(gross_cents AS DECIMAL(38, 0)) AS gross_cents,
  COALESCE(CAST(discount_cents AS DECIMAL(38, 0)), 0) AS discount_cents,
  LOWER(TRIM(status)) AS status,
  currency
FROM invoice_versions
WHERE
  version_rank = 1 AND op <> 'DELETE';
