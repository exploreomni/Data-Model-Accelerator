-- Trusted reusable rule: DISCOUNT_CENTS is the TOTAL LINE discount, applied ONCE.
-- This staging calculation is correct for input satisfying the CDC contract.
with ranked as (
  select *, row_number() over (
    partition by TENANT_ID, ORDER_ID, LINE_ID order by SEQUENCE desc
  ) as version_rank
  from {{ source('retail_raw', 'order_lines') }}
)
select TENANT_ID, ORDER_ID, LINE_ID, PRODUCT_ID, QUANTITY,
  UNIT_PRICE_CENTS, DISCOUNT_CENTS,
  QUANTITY * UNIT_PRICE_CENTS - DISCOUNT_CENTS as LINE_NET_CENTS,
  TENANT_ID || '|' || ORDER_ID || '|' || LINE_ID as LINE_KEY
from ranked
where version_rank = 1 and not IS_DELETED
