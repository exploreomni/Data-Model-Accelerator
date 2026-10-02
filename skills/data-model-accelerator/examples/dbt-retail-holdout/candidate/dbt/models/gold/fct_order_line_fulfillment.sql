with fulfilled as (
  select TENANT_ID, ORDER_ID, LINE_ID, sum(QUANTITY) as FULFILLED_QUANTITY
  from {{ ref('stg_fulfillments') }} group by TENANT_ID, ORDER_ID, LINE_ID
), returned as (
  select TENANT_ID, ORDER_ID, LINE_ID, sum(QUANTITY) as RETURNED_QUANTITY,
         sum(REFUND_CENTS) as REFUND_CENTS
  from {{ ref('stg_returns') }} group by TENANT_ID, ORDER_ID, LINE_ID
)
select l.LINE_KEY, l.TENANT_ID, l.ORDER_ID, l.LINE_ID, l.PRODUCT_ID,
       o.ORDER_DATE, o.ORDER_STATUS, l.QUANTITY as ORDERED_QUANTITY,
       coalesce(f.FULFILLED_QUANTITY, 0) as FULFILLED_QUANTITY,
       coalesce(r.RETURNED_QUANTITY, 0) as RETURNED_QUANTITY,
       l.LINE_NET_CENTS, coalesce(r.REFUND_CENTS, 0) as REFUND_CENTS,
       l.LINE_NET_CENTS - coalesce(r.REFUND_CENTS, 0) as RETAINED_REVENUE_CENTS
from {{ ref('stg_order_lines') }} l
left join {{ ref('stg_orders') }} o
  on l.TENANT_ID = o.TENANT_ID and l.ORDER_ID = o.ORDER_ID
left join fulfilled f
  on l.TENANT_ID = f.TENANT_ID and l.ORDER_ID = f.ORDER_ID and l.LINE_ID = f.LINE_ID
left join returned r
  on l.TENANT_ID = r.TENANT_ID and l.ORDER_ID = r.ORDER_ID and l.LINE_ID = r.LINE_ID
