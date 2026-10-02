{{ config(tags=['raw']) }}
select TENANT_ID, ORDER_ID, LINE_ID, SEQUENCE, count(*) as conflicting_payloads
from (select distinct * from {{ source('retail_raw', 'order_lines') }}) versions
group by TENANT_ID, ORDER_ID, LINE_ID, SEQUENCE having count(*) > 1
