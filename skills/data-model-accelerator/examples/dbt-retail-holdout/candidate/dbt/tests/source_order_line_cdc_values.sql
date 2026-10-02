{{ config(tags=['raw']) }}
select * from {{ source('retail_raw', 'order_lines') }}
where TENANT_ID is null or ORDER_ID is null or LINE_ID is null or PRODUCT_ID is null or QUANTITY is null or UNIT_PRICE_CENTS is null or DISCOUNT_CENTS is null or SEQUENCE is null or IS_DELETED is null or SEQUENCE <= 0 or QUANTITY <= 0 or UNIT_PRICE_CENTS <= 0 or DISCOUNT_CENTS < 0 or DISCOUNT_CENTS > QUANTITY * UNIT_PRICE_CENTS
