-- Entity IDs are tenant-local. Every duplicate check uses its full entity key.
select 'stg_rentals' as relation_name, tenant_id, rental_id as entity_id
from {{ ref('stg_rentals') }}
group by tenant_id, rental_id having count(*) > 1
union all
select 'stg_charges', tenant_id, charge_id
from {{ ref('stg_charges') }}
group by tenant_id, charge_id having count(*) > 1
union all
select 'stg_locations', tenant_id, location_id
from {{ ref('stg_locations') }}
group by tenant_id, location_id having count(*) > 1
union all
select 'int_eligible_charges', tenant_id, charge_id
from {{ ref('int_eligible_charges') }}
group by tenant_id, charge_id having count(*) > 1
union all
select 'fct_rental_revenue', tenant_id, rental_id
from {{ ref('fct_rental_revenue') }}
group by tenant_id, rental_id having count(*) > 1
