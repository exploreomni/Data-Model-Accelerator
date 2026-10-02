{{ config(tags=['raw']) }}
select TENANT_ID, ORDER_ID, SEQUENCE, count(*) as conflicting_payloads
from (select distinct * from {{ source('retail_raw', 'orders') }}) versions
group by TENANT_ID, ORDER_ID, SEQUENCE having count(*) > 1
