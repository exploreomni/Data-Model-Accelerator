select
    part_line_id,
    work_order_id,
    quantity,
    unit_cost
from {{ source('raw_maintenance', 'parts') }}
