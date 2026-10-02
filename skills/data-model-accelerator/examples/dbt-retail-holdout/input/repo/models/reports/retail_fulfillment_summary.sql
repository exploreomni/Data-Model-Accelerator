-- Executive request implemented directly in a report model.
-- Known defect: joining independent child events below multiplies line measures.
with fulfillment_versions as (
  select *, row_number() over (
    partition by TENANT_ID, FULFILLMENT_ID order by SEQUENCE desc
  ) as version_rank
  from {{ source('retail_raw', 'fulfillments') }}
), return_versions as (
  select *, row_number() over (
    partition by TENANT_ID, RETURN_ID order by SEQUENCE desc
  ) as version_rank
  from {{ source('retail_raw', 'returns') }}
), fulfillments as (
  select * from fulfillment_versions where version_rank = 1 and not IS_DELETED
), returns as (
  select * from return_versions where version_rank = 1 and not IS_DELETED
)
select cast(date_trunc('month', o.ORDER_DATE) as date) as ORDER_MONTH,
  l.PRODUCT_ID,
  sum(l.QUANTITY) as ORDERED_QUANTITY,
  sum(coalesce(f.QUANTITY, 0)) as FULFILLED_QUANTITY,
  sum(coalesce(r.QUANTITY, 0)) as RETURNED_QUANTITY,
  sum(l.LINE_NET_CENTS) as LINE_NET_CENTS,
  sum(coalesce(r.REFUND_CENTS, 0)) as REFUND_CENTS,
  sum(l.LINE_NET_CENTS - coalesce(r.REFUND_CENTS, 0)) as RETAINED_REVENUE_CENTS,
  sum(coalesce(f.QUANTITY, 0)) * 1.0 / nullif(sum(l.QUANTITY), 0) as FULFILLMENT_RATE
from {{ ref('stg_orders') }} o
join {{ ref('stg_order_lines') }} l
  on o.TENANT_ID = l.TENANT_ID and o.ORDER_ID = l.ORDER_ID
left join fulfillments f
  on l.TENANT_ID = f.TENANT_ID and l.ORDER_ID = f.ORDER_ID and l.LINE_ID = f.LINE_ID
left join returns r
  on l.TENANT_ID = r.TENANT_ID and l.ORDER_ID = r.ORDER_ID and l.LINE_ID = r.LINE_ID
where o.TENANT_ID = '{{ var("tenant", "A") }}'
  and o.ORDER_DATE >= cast('{{ var("start_date", "2026-04-01") }}' as date)
  and o.ORDER_DATE < cast('{{ var("end_date", "2026-04-04") }}' as date)
  and o.ORDER_STATUS = '{{ var("status", "completed") }}'
  {% if var('product', 'ALL') != 'ALL' %}
  and l.PRODUCT_ID = '{{ var("product") }}'
  {% endif %}
group by 1, 2
