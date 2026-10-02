with ranked as (
    select
        tenant_id,
        rental_id,
        location_id,
        rental_status,
        rental_date,
        currency,
        updated_at,
        cdc_sequence,
        is_deleted,
        row_number() over (
            partition by tenant_id, rental_id
            order by cdc_sequence desc, updated_at desc
        ) as version_rank
    from {{ ref('raw_rentals') }}
)

select
    tenant_id,
    rental_id,
    location_id,
    rental_status,
    rental_date,
    currency,
    updated_at,
    cdc_sequence
from ranked
where version_rank = 1 and is_deleted = false
