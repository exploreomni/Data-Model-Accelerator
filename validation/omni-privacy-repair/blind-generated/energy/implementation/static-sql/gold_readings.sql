select
    readings.reading_id,
    readings.meter_id,
    readings.recorded_on,
    readings.kwh,
    meters.zone
from silver_readings as readings
left join silver_meters as meters
    on readings.meter_id = meters.meter_id
