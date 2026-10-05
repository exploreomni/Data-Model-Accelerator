select
    cast(work_order_id as number(38, 0)) as work_order_id,
    cast(tenant_id as number(38, 0)) as tenant_id,
    cast(opened_on as date) as opened_on,
    cast(labor_cost as number(18, 4)) as labor_cost,
    cast(status as varchar) as status
from bronze_work_orders
