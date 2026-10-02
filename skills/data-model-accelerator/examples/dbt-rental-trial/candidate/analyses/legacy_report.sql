-- Historical source remains unchanged at ../input/repo/models/legacy_report.sql.
-- Apply authorized tenant/persona and report filters in the consuming report.
select
    tenant_id,
    rental_id,
    location_id,
    location_name,
    rental_status,
    rental_date,
    currency,
    cast(sum(net_revenue) as decimal(18,2)) as net_revenue
from {{ ref('fct_rental_revenue') }}
group by tenant_id, rental_id, location_id, location_name,
         rental_status, rental_date, currency
