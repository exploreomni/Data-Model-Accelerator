with charge_totals as (
    select
        tenant_id,
        rental_id,
        cast(sum(case
            when charge_type in ('rental_fee', 'damage_fee') then signed_amount
            else cast(0 as decimal(18,2))
        end) as decimal(18,2)) as fee_amount,
        cast(sum(case
            when charge_type = 'refund' then signed_amount
            else cast(0 as decimal(18,2))
        end) as decimal(18,2)) as refund_amount,
        cast(count(charge_id) as bigint) as eligible_charge_count
    from {{ ref('int_eligible_charges') }}
    group by tenant_id, rental_id
), rental_totals as (
    select
        r.tenant_id,
        r.rental_id,
        r.location_id,
        l.location_name,
        r.rental_status,
        r.rental_date,
        r.currency,
        cast(coalesce(c.fee_amount, 0) as decimal(18,2)) as fee_amount,
        cast(coalesce(c.refund_amount, 0) as decimal(18,2)) as refund_amount,
        cast(coalesce(c.eligible_charge_count, 0) as bigint) as eligible_charge_count
    from {{ ref('stg_rentals') }} r
    inner join {{ ref('stg_locations') }} l
        on r.tenant_id = l.tenant_id
        and r.location_id = l.location_id
    left join charge_totals c
        on r.tenant_id = c.tenant_id
        and r.rental_id = c.rental_id
    where r.rental_status = 'completed'
)

select
    tenant_id,
    rental_id,
    location_id,
    location_name,
    rental_status,
    rental_date,
    currency,
    fee_amount,
    refund_amount,
    cast(fee_amount + refund_amount as decimal(18,2)) as net_revenue,
    eligible_charge_count
from rental_totals
