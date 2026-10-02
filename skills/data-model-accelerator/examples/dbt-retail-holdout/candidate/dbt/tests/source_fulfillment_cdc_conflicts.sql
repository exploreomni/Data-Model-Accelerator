{{ config(tags=['raw']) }}
select TENANT_ID, FULFILLMENT_ID, SEQUENCE, count(*) as conflicting_payloads
from (select distinct * from {{ source('retail_raw', 'fulfillments') }}) versions
group by TENANT_ID, FULFILLMENT_ID, SEQUENCE having count(*) > 1
