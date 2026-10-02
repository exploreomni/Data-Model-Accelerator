select 'line_order' as violation, l.TENANT_ID, l.ORDER_ID, l.LINE_ID
from {{ ref('stg_order_lines') }} l left join {{ ref('stg_orders') }} o
on l.TENANT_ID=o.TENANT_ID and l.ORDER_ID=o.ORDER_ID where o.ORDER_KEY is null
union all
select 'fulfillment_line', f.TENANT_ID, f.ORDER_ID, f.LINE_ID
from {{ ref('stg_fulfillments') }} f left join {{ ref('stg_order_lines') }} l
on f.TENANT_ID=l.TENANT_ID and f.ORDER_ID=l.ORDER_ID and f.LINE_ID=l.LINE_ID where l.LINE_KEY is null
union all
select 'return_line', r.TENANT_ID, r.ORDER_ID, r.LINE_ID
from {{ ref('stg_returns') }} r left join {{ ref('stg_order_lines') }} l
on r.TENANT_ID=l.TENANT_ID and r.ORDER_ID=l.ORDER_ID and r.LINE_ID=l.LINE_ID where l.LINE_KEY is null
