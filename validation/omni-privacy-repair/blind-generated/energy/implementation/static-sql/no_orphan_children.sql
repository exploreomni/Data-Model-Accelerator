select readings.reading_id
from silver_readings as readings
left join silver_meters as meters
    on readings.meter_id = meters.meter_id
where meters.meter_id is null
