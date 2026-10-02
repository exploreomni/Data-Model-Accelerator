{{ config(tags=['raw']) }}
select * from {{ source('retail_raw', 'returns') }}
where TENANT_ID is null or RETURN_ID is null or ORDER_ID is null or LINE_ID is null or QUANTITY is null or REFUND_CENTS is null or SEQUENCE is null or IS_DELETED is null or SEQUENCE <= 0 or QUANTITY <= 0 or REFUND_CENTS < 0
