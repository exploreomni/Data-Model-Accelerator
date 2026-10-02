-- Correct on contract-valid CDC input: resolve latest version before tombstones.
with ranked as (
  select *, row_number() over (
    partition by TENANT_ID, ORDER_ID order by SEQUENCE desc
  ) as version_rank
  from {{ source('retail_raw', 'orders') }}
)
select TENANT_ID, ORDER_ID, cast(ORDER_DATE as date) as ORDER_DATE,
  STATUS as ORDER_STATUS,
  TENANT_ID || '|' || ORDER_ID as ORDER_KEY
from ranked
where version_rank = 1 and not IS_DELETED
