-- Deliberately no DISTINCT: even an identical repeated manual adjustment is a review error.
SELECT TENANT_ID, INVOICE_ID
FROM {{ source('raw', 'adjustments') }}
GROUP BY TENANT_ID, INVOICE_ID HAVING COUNT(*) <> 1
