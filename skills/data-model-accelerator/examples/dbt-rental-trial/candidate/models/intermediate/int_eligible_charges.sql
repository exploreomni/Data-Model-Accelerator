select
    c.tenant_id,
    c.charge_id,
    c.rental_id,
    c.charge_type,
    c.currency,
    cast(c.amount as decimal(18,2)) as source_amount,
    cast(
        case when c.charge_type = 'refund' then -c.amount else c.amount end
        as decimal(18,2)
    ) as signed_amount
from {{ ref('stg_charges') }} c
inner join {{ ref('stg_rentals') }} r
    on c.tenant_id = r.tenant_id
    and c.rental_id = r.rental_id
    and c.currency = r.currency
where r.rental_status = 'completed'
    and c.charge_type in ('rental_fee', 'damage_fee', 'refund')
