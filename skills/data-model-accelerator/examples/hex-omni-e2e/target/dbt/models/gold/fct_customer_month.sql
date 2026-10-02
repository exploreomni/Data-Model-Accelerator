{{ config(materialized='table', schema='GOLD', alias='FCT_CUSTOMER_MONTH') }}
-- Current balances at the capture watermark, grouped by invoice date. Not payment-event-time cohorts.
-- No customer-month segment: within-month changes need an approved allocation rule.
WITH customer_month AS (
  SELECT TENANT_ID, CUSTOMER_ID, INVOICE_MONTH,
         SUM(NET_CENTS) AS NET_CENTS,
         SUM(PAID_CENTS) AS PAID_CENTS,
         SUM(OUTSTANDING_CENTS) AS OUTSTANDING_CENTS,
         MAX(CASE WHEN STATUS = 'posted' AND NET_CENTS > 0 THEN 1 ELSE 0 END) AS HAS_INVOICE,
         MAX(CASE WHEN STATUS = 'posted' AND PAID_CENTS > 0 THEN 1 ELSE 0 END) AS HAS_PAID_INVOICE
  FROM {{ ref('fct_invoices') }}
  GROUP BY TENANT_ID, CUSTOMER_ID, INVOICE_MONTH
), first_paid AS (
  SELECT TENANT_ID, CUSTOMER_ID, MIN(INVOICE_MONTH) AS FIRST_PAID_MONTH
  FROM {{ ref('fct_invoices') }}
  WHERE STATUS = 'posted' AND PAID_CENTS > 0
  GROUP BY TENANT_ID, CUSTOMER_ID
)
SELECT m.TENANT_ID || '|' || m.CUSTOMER_ID || '|' || TO_CHAR(m.INVOICE_MONTH, 'YYYY-MM-DD') AS CUSTOMER_MONTH_KEY,
       m.TENANT_ID, m.CUSTOMER_ID, m.INVOICE_MONTH,
       m.NET_CENTS, m.PAID_CENTS, m.OUTSTANDING_CENTS,
       m.HAS_INVOICE, m.HAS_PAID_INVOICE, p.FIRST_PAID_MONTH
FROM customer_month m
LEFT JOIN first_paid p ON m.TENANT_ID = p.TENANT_ID AND m.CUSTOMER_ID = p.CUSTOMER_ID
