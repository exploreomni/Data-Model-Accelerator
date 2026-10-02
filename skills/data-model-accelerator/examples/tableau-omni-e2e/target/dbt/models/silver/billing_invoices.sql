{{ config(materialized='table', schema='SILVER', alias='BILLING_INVOICES') }}
-- Reject conflicting same-sequence payloads before building; identical replays are harmless.
WITH versions AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY TENANT_ID, INVOICE_ID ORDER BY SEQUENCE DESC
  ) AS VERSION_RANK
  FROM {{ source('raw', 'invoice_cdc') }}
)
SELECT TENANT_ID, INVOICE_ID, CUSTOMER_ID,
       CAST(INVOICE_DATE AS DATE) AS INVOICE_DATE,
       CAST(AMOUNT_CENTS AS NUMBER(38,0)) AS AMOUNT_CENTS,
       LOWER(TRIM(STATUS)) AS STATUS,
       CAST(SEQUENCE AS NUMBER(38,0)) AS SOURCE_SEQUENCE
FROM versions
WHERE VERSION_RANK = 1 AND NOT IS_DELETED
