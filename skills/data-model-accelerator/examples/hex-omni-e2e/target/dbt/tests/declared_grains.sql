SELECT 'silver_invoice_grain' AS ISSUE FROM {{ ref('billing_invoices') }}
GROUP BY TENANT_ID, INVOICE_ID HAVING COUNT(*) <> 1
UNION ALL
SELECT 'silver_payment_grain' AS ISSUE FROM {{ ref('billing_payments') }}
GROUP BY TENANT_ID, PAYMENT_ID HAVING COUNT(*) <> 1
UNION ALL
SELECT 'silver_adjustment_grain' AS ISSUE FROM {{ ref('billing_adjustments') }}
GROUP BY TENANT_ID, INVOICE_ID HAVING COUNT(*) <> 1
UNION ALL
SELECT 'dimension_grain' AS ISSUE FROM {{ ref('dim_customers') }}
GROUP BY CUSTOMER_KEY HAVING COUNT(*) <> 1 OR CUSTOMER_KEY IS NULL
UNION ALL
SELECT 'invoice_grain' AS ISSUE FROM {{ ref('fct_invoices') }}
GROUP BY TENANT_ID, INVOICE_ID HAVING COUNT(*) <> 1
UNION ALL
SELECT 'invoice_surrogate_grain' AS ISSUE FROM {{ ref('fct_invoices') }}
GROUP BY INVOICE_KEY HAVING COUNT(*) <> 1 OR INVOICE_KEY IS NULL
UNION ALL
SELECT 'customer_month_grain' AS ISSUE FROM {{ ref('fct_customer_month') }}
GROUP BY TENANT_ID, CUSTOMER_ID, INVOICE_MONTH HAVING COUNT(*) <> 1
UNION ALL
SELECT 'customer_month_surrogate_grain' AS ISSUE FROM {{ ref('fct_customer_month') }}
GROUP BY CUSTOMER_MONTH_KEY HAVING COUNT(*) <> 1 OR CUSTOMER_MONTH_KEY IS NULL
