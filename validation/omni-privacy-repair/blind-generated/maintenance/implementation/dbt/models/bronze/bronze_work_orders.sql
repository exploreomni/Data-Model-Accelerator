select
    work_order_id,
    tenant_id,
    opened_on,
    labor_cost,
    status
from {{ source('raw_maintenance', 'work_orders') }}
