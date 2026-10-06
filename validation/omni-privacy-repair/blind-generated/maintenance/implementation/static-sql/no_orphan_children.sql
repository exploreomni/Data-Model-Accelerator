select parts.part_line_id
from silver_parts as parts
left join silver_work_orders as work_orders
    on parts.work_order_id = work_orders.work_order_id
where work_orders.work_order_id is null
