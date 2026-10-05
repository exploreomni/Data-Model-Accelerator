select
    cast(part_line_id as number(38, 0)) as part_line_id,
    cast(work_order_id as number(38, 0)) as work_order_id,
    cast(quantity as number(18, 4)) as quantity,
    cast(unit_cost as number(18, 4)) as unit_cost
from {{ ref('bronze_parts') }}
