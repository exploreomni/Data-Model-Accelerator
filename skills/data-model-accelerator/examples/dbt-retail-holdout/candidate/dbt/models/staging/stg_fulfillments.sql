with ranked as (
  select *, row_number() over (partition by TENANT_ID, FULFILLMENT_ID order by SEQUENCE desc) as version_rank
  from {{ source('retail_raw', 'fulfillments') }}
)
select TENANT_ID, FULFILLMENT_ID, ORDER_ID, LINE_ID, QUANTITY
from ranked where version_rank = 1 and not IS_DELETED
