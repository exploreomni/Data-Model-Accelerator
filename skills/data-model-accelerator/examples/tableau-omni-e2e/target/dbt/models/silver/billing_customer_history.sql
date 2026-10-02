{{ config(materialized='table', schema='SILVER', alias='BILLING_CUSTOMER_HISTORY') }}
-- Full identical snapshots replay safely. Differing overlapping histories must fail preflight.
SELECT DISTINCT TENANT_ID, CUSTOMER_ID, SEGMENT,
       CAST(VALID_FROM AS DATE) AS VALID_FROM,
       CAST(VALID_TO AS DATE) AS VALID_TO
FROM {{ source('raw', 'customer_history') }}
