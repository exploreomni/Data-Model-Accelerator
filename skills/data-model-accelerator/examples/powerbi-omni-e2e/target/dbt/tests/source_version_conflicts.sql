-- Nonempty results fail. Full identical CDC replays are allowed; conflicting same-sequence rows are not.
WITH invoices AS (
  SELECT DISTINCT TENANT_ID, INVOICE_ID, CUSTOMER_ID, INVOICE_DATE, AMOUNT_CENTS, STATUS, IS_DELETED, SEQUENCE
  FROM {{ source('raw', 'invoice_cdc') }}
), payments AS (
  SELECT DISTINCT TENANT_ID, PAYMENT_ID, INVOICE_ID, PAID_CENTS, IS_DELETED, SEQUENCE
  FROM {{ source('raw', 'payment_cdc') }}
)
SELECT 'invoice_version_conflict' AS ISSUE, TENANT_ID, INVOICE_ID AS BUSINESS_ID
FROM invoices GROUP BY TENANT_ID, INVOICE_ID, SEQUENCE HAVING COUNT(*) > 1
UNION ALL
SELECT 'payment_version_conflict' AS ISSUE, TENANT_ID, PAYMENT_ID AS BUSINESS_ID
FROM payments GROUP BY TENANT_ID, PAYMENT_ID, SEQUENCE HAVING COUNT(*) > 1
