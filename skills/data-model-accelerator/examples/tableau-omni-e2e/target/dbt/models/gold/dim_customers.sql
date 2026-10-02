{{ config(materialized='table', schema='GOLD', alias='DIM_CUSTOMERS') }}
SELECT TENANT_ID || '|' || CUSTOMER_ID || '|' || TO_CHAR(VALID_FROM, 'YYYY-MM-DD') AS CUSTOMER_KEY,
       TENANT_ID, CUSTOMER_ID, SEGMENT, VALID_FROM, VALID_TO
FROM {{ ref('billing_customer_history') }}
