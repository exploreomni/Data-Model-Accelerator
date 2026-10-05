select readings.reading_id
from {{ ref('silver_readings') }} as readings
left join {{ ref('silver_meters') }} as meters
    on readings.meter_id = meters.meter_id
where meters.meter_id is null
