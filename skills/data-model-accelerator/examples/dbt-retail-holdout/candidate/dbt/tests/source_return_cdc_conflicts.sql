{{ config(tags=['raw']) }}
select TENANT_ID, RETURN_ID, SEQUENCE, count(*) as conflicting_payloads
from (select distinct * from {{ source('retail_raw', 'returns') }}) versions
group by TENANT_ID, RETURN_ID, SEQUENCE having count(*) > 1
