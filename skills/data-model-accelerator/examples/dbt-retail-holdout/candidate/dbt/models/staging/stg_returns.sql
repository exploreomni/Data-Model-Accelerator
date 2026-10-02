with ranked as (
  select *, row_number() over (partition by TENANT_ID, RETURN_ID order by SEQUENCE desc) as version_rank
  from {{ source('retail_raw', 'returns') }}
)
select TENANT_ID, RETURN_ID, ORDER_ID, LINE_ID, QUANTITY, REFUND_CENTS
from ranked where version_rank = 1 and not IS_DELETED
