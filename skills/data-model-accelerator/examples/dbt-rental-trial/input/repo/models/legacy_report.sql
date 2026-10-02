-- Synthetic legacy observation, deliberately incorrect outside the clean slice.
-- It forgets tenant joins and CDC, drops zero-charge rentals, includes deposits,
-- and adds positive refund source amounts rather than subtracting them.
select
    r.tenant_id,
    r.rental_id,
    r.location_id,
    l.location_name,
    r.rental_status,
    r.rental_date,
    r.currency,
    sum(c.amount) as net_revenue
from {{ ref('raw_rentals') }} r
join {{ ref('raw_charges') }} c on r.rental_id = c.rental_id
join {{ ref('raw_locations') }} l on r.location_id = l.location_id
where r.rental_status = 'completed'
group by r.tenant_id, r.rental_id, r.location_id, l.location_name,
         r.rental_status, r.rental_date, r.currency
