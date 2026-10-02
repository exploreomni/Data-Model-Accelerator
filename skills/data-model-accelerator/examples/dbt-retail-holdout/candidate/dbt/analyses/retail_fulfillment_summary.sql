{{ validate_report_context() }}
select cast(date_trunc('month', ORDER_DATE) as date) as ORDER_MONTH,
       PRODUCT_ID, sum(ORDERED_QUANTITY) as ORDERED_QUANTITY,
       sum(FULFILLED_QUANTITY) as FULFILLED_QUANTITY,
       sum(RETURNED_QUANTITY) as RETURNED_QUANTITY,
       sum(LINE_NET_CENTS) as LINE_NET_CENTS, sum(REFUND_CENTS) as REFUND_CENTS,
       sum(RETAINED_REVENUE_CENTS) as RETAINED_REVENUE_CENTS,
       sum(FULFILLED_QUANTITY) * 1.0 / nullif(sum(ORDERED_QUANTITY), 0) as FULFILLMENT_RATE
from {{ ref('fct_order_line_fulfillment') }}
where TENANT_ID = {{ sql_literal(var('tenant', 'A')) }}
  and ORDER_DATE >= cast({{ sql_literal(var('start_date', '2026-04-01')) }} as date)
  and ORDER_DATE < cast({{ sql_literal(var('end_date', '2026-04-04')) }} as date)
  and ORDER_STATUS = {{ sql_literal(var('status', 'completed')) }}
  {% if var('product', 'ALL') != 'ALL' %}
  and PRODUCT_ID = {{ sql_literal(var('product')) }}
  {% endif %}
group by 1, 2
