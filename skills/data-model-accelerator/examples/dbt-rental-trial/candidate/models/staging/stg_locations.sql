with ranked as (
    select
        tenant_id,
        location_id,
        location_name,
        updated_at,
        cdc_sequence,
        is_deleted,
        row_number() over (
            partition by tenant_id, location_id
            order by cdc_sequence desc, updated_at desc
        ) as version_rank
    from {{ ref('raw_locations') }}
)

select
    tenant_id,
    location_id,
    location_name,
    updated_at,
    cdc_sequence
from ranked
where version_rank = 1 and is_deleted = false
