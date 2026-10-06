select
    readings.reading_id,
    readings.meter_id,
    readings.recorded_on,
    readings.kwh,
    meters.zone
from {{ ref('silver_readings') }} as readings
left join {{ ref('silver_meters') }} as meters
    on readings.meter_id = meters.meter_id
