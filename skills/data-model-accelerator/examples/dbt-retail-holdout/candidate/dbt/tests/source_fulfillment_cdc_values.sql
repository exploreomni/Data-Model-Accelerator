{{ config(tags=['raw']) }}
select * from {{ source('retail_raw', 'fulfillments') }}
where TENANT_ID is null or FULFILLMENT_ID is null or ORDER_ID is null or LINE_ID is null or QUANTITY is null or SEQUENCE is null or IS_DELETED is null or SEQUENCE <= 0 or QUANTITY <= 0
