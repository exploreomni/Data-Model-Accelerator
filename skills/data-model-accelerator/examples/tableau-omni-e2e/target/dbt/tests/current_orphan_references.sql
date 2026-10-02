SELECT 'payment_orphan' AS ISSUE, p.TENANT_ID, p.INVOICE_ID
FROM {{ ref('billing_payments') }} p
LEFT JOIN {{ ref('billing_invoices') }} i ON p.TENANT_ID = i.TENANT_ID AND p.INVOICE_ID = i.INVOICE_ID
WHERE i.INVOICE_ID IS NULL
UNION ALL
SELECT 'adjustment_orphan' AS ISSUE, a.TENANT_ID, a.INVOICE_ID
FROM {{ ref('billing_adjustments') }} a
LEFT JOIN {{ ref('billing_invoices') }} i ON a.TENANT_ID = i.TENANT_ID AND a.INVOICE_ID = i.INVOICE_ID
WHERE i.INVOICE_ID IS NULL
