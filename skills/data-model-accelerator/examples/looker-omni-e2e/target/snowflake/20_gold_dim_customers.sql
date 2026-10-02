-- SYNTHETIC CANDIDATE. Local simulation only; full rebuild, not a production incremental deployment.
CREATE OR REPLACE TABLE DMA_SIM.GOLD.DIM_CUSTOMERS AS
SELECT MD5(tenant_id || ':' || customer_id || ':' || TO_CHAR(valid_from, 'YYYY-MM-DD HH24:MI:SS')) AS customer_key,
       tenant_id, customer_id, valid_from, valid_to, segment
FROM DMA_SIM.SILVER.BILLING_CUSTOMER_HISTORY
UNION ALL
SELECT MD5(tenant_id || ':__UNKNOWN__') AS customer_key, tenant_id,
       CAST(NULL AS VARCHAR) AS customer_id, CAST(NULL AS TIMESTAMP_NTZ) AS valid_from,
       CAST(NULL AS TIMESTAMP_NTZ) AS valid_to, 'Unknown' AS segment
FROM (SELECT DISTINCT tenant_id FROM DMA_SIM.SILVER.BILLING_INVOICES);
