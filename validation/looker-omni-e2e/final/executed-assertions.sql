-- Synthetic Snowflake-dialect assertions executed locally through DuckDB.
-- Each statement must return violations = 0. Native execution remains unverified.

SELECT COUNT(*) AS violations FROM
          (SELECT tenant_id,invoice_id FROM DMA_SIM.GOLD.FCT_INVOICES GROUP BY tenant_id,invoice_id HAVING COUNT(*) <> 1
           UNION ALL SELECT tenant_id,invoice_id FROM DMA_SIM.GOLD.FCT_INVOICES WHERE invoice_key IS NULL
           UNION ALL SELECT invoice_key,invoice_key FROM DMA_SIM.GOLD.FCT_INVOICES GROUP BY invoice_key HAVING COUNT(*) <> 1);

SELECT COUNT(*) AS violations FROM
          (SELECT customer_key FROM DMA_SIM.GOLD.DIM_CUSTOMERS GROUP BY customer_key HAVING COUNT(*) <> 1 OR customer_key IS NULL);

SELECT COUNT(*) AS violations FROM
          (SELECT i.invoice_key FROM DMA_SIM.GOLD.FCT_INVOICES i LEFT JOIN DMA_SIM.GOLD.DIM_CUSTOMERS c
           ON i.customer_key=c.customer_key AND i.tenant_id=c.tenant_id GROUP BY i.invoice_key HAVING COUNT(c.customer_key) <> 1);

SELECT COUNT(*) AS violations
          FROM DMA_SIM.GOLD.FCT_INVOICES i JOIN DMA_SIM.GOLD.DIM_CUSTOMERS c ON i.customer_key=c.customer_key
          WHERE i.tenant_id <> c.tenant_id;

SELECT COUNT(*) AS violations
          FROM DMA_SIM.GOLD.FCT_INVOICES i JOIN DMA_SIM.GOLD.DIM_CUSTOMERS c ON i.customer_key=c.customer_key
          WHERE c.customer_id IS NOT NULL AND NOT (i.issued_at >= c.valid_from AND (i.issued_at < c.valid_to OR c.valid_to IS NULL));

SELECT CASE WHEN
          (SELECT COUNT(*) FROM DMA_SIM.GOLD.FCT_INVOICES WHERE status='draft')=1 AND
          (SELECT COUNT(*) FROM DMA_SIM.GOLD.FCT_INVOICES WHERE currency='EUR')=1 AND
          (SELECT COUNT(*) FROM DMA_SIM.GOLD.FCT_INVOICES WHERE invoice_date < '2026-09-01')=2
          THEN 0 ELSE 1 END AS violations;
