{{ config(materialized='table', schema='SILVER', alias='BILLING_ADJUSTMENTS') }}
-- This requires the independently inventoried CSV to have been landed in RAW.ADJUSTMENTS.
-- Duplicate adjustment keys are errors, including identical duplicates; never deduplicate them here.
SELECT TENANT_ID, INVOICE_ID,
       CAST(ADJUSTMENT_CENTS AS NUMBER(38,0)) AS ADJUSTMENT_CENTS,
       REASON
FROM {{ source('raw', 'adjustments') }}
