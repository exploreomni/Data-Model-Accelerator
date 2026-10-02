-- SYNTHETIC CANDIDATE. Local simulation only; full rebuild, not a production incremental deployment.
CREATE OR REPLACE TABLE DMA_SIM.SILVER.BILLING_PAYMENTS AS
WITH payment_versions AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY tenant_id, entry_id ORDER BY source_seq DESC, arrival_seq DESC) AS version_rank
  FROM DMA_SIM.BRONZE.BILLING_PAYMENT_CDC
)
SELECT
  tenant_id,
  entry_id,
  invoice_id,
  CAST(amount_cents AS DECIMAL(38, 0)) AS amount_cents,
  LOWER(TRIM(status)) AS status,
  currency
FROM payment_versions
WHERE
  version_rank = 1 AND op <> 'DELETE';
