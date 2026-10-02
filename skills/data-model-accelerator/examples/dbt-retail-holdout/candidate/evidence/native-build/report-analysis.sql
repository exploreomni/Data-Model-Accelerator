
  
  
  
  
  
  
  
  
select cast(date_trunc('month', ORDER_DATE) as date) as ORDER_MONTH,
       PRODUCT_ID, sum(ORDERED_QUANTITY) as ORDERED_QUANTITY,
       sum(FULFILLED_QUANTITY) as FULFILLED_QUANTITY,
       sum(RETURNED_QUANTITY) as RETURNED_QUANTITY,
       sum(LINE_NET_CENTS) as LINE_NET_CENTS, sum(REFUND_CENTS) as REFUND_CENTS,
       sum(RETAINED_REVENUE_CENTS) as RETAINED_REVENUE_CENTS,
       sum(FULFILLED_QUANTITY) * 1.0 / nullif(sum(ORDERED_QUANTITY), 0) as FULFILLMENT_RATE
from DMA_RETAIL.GOLD.FCT_ORDER_LINE_FULFILLMENT
where TENANT_ID = 'A'
  and ORDER_DATE >= cast('2026-04-01' as date)
  and ORDER_DATE < cast('2026-04-04' as date)
  and ORDER_STATUS = 'completed'
  
group by 1, 2