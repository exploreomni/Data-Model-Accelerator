with ranked as (
    select
        tenant_id,
        charge_id,
        rental_id,
        charge_type,
        amount,
        currency,
        updated_at,
        cdc_sequence,
        is_deleted,
        row_number() over (
            partition by tenant_id, charge_id
            order by cdc_sequence desc, updated_at desc
        ) as version_rank
    from {{ ref('raw_charges') }}
)

select
    tenant_id,
    charge_id,
    rental_id,
    charge_type,
    cast(amount as decimal(18,2)) as amount,
    currency,
    updated_at,
    cdc_sequence
from ranked
where version_rank = 1 and is_deleted = false
