{{ config(tags=['raw']) }}
select * from {{ source('retail_raw', 'orders') }}
where TENANT_ID is null or ORDER_ID is null or ORDER_DATE is null or STATUS is null or SEQUENCE is null or IS_DELETED is null or SEQUENCE <= 0
