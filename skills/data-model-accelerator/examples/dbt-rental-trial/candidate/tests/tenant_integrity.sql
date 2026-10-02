-- Do not require every staged charge to have a live rental: deleted parents are allowed.
select 'rental_missing_tenant_location' as violation, r.tenant_id, r.rental_id as entity_id
from {{ ref('stg_rentals') }} r
left join {{ ref('stg_locations') }} l
    on r.tenant_id = l.tenant_id and r.location_id = l.location_id
where l.location_id is null
union all
select 'eligible_invalid_parent', c.tenant_id, c.charge_id
from {{ ref('int_eligible_charges') }} c
left join {{ ref('stg_rentals') }} r
    on c.tenant_id = r.tenant_id and c.rental_id = r.rental_id
where r.rental_id is null or r.rental_status <> 'completed' or r.currency <> c.currency
union all
select 'eligible_invalid_source', c.tenant_id, c.charge_id
from {{ ref('int_eligible_charges') }} c
left join {{ ref('stg_charges') }} s
    on c.tenant_id = s.tenant_id and c.charge_id = s.charge_id
where s.charge_id is null or s.rental_id <> c.rental_id
    or s.currency <> c.currency or s.charge_type <> c.charge_type
    or s.amount <> c.source_amount
union all
select 'gold_invalid_source_rental', f.tenant_id, f.rental_id
from {{ ref('fct_rental_revenue') }} f
left join {{ ref('stg_rentals') }} r
    on f.tenant_id = r.tenant_id and f.rental_id = r.rental_id
where r.rental_id is null or r.rental_status <> 'completed'
    or f.location_id <> r.location_id or f.rental_status <> r.rental_status
    or f.rental_date <> r.rental_date or f.currency <> r.currency
union all
select 'gold_invalid_tenant_location', f.tenant_id, f.rental_id
from {{ ref('fct_rental_revenue') }} f
left join {{ ref('stg_locations') }} l
    on f.tenant_id = l.tenant_id and f.location_id = l.location_id
where l.location_id is null or f.location_name <> l.location_name
union all
select 'completed_rental_missing_gold', r.tenant_id, r.rental_id
from {{ ref('stg_rentals') }} r
left join {{ ref('fct_rental_revenue') }} f
    on r.tenant_id = f.tenant_id and r.rental_id = f.rental_id
where r.rental_status = 'completed' and f.rental_id is null
union all
select 'eligible_missing_gold_parent', c.tenant_id, c.charge_id
from {{ ref('int_eligible_charges') }} c
left join {{ ref('fct_rental_revenue') }} f
    on c.tenant_id = f.tenant_id and c.rental_id = f.rental_id
where f.rental_id is null
