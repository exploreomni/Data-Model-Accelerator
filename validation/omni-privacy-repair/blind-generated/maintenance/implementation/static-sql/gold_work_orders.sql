with parts_by_work_order as (
    select
        work_order_id,
        sum(quantity * unit_cost) as parts_cost
    from silver_parts
    group by work_order_id
)

select
    work_orders.work_order_id,
    work_orders.tenant_id,
    work_orders.opened_on,
    work_orders.labor_cost,
    work_orders.status,
    coalesce(parts.parts_cost, 0) as parts_cost,
    work_orders.labor_cost + coalesce(parts.parts_cost, 0) as work_cost
from silver_work_orders as work_orders
left join parts_by_work_order as parts
    on work_orders.work_order_id = parts.work_order_id
