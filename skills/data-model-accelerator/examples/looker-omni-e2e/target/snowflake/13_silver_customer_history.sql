-- SYNTHETIC CANDIDATE. Local simulation only; full rebuild, not a production incremental deployment.
CREATE OR REPLACE TABLE DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY AS
-- Exact snapshot replays collapse; distinct overlapping versions are rejected by source-contract validation.
SELECT DISTINCT
  tenant_id,
  customer_id,
  CAST(valid_from AS TIMESTAMPNTZ) AS valid_from,
  CAST(valid_to AS TIMESTAMPNTZ) AS valid_to,
  segment
FROM DMA_SIM.BRONZE.BILLING_CUSTOMER_HISTORY;
