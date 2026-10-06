select
    cast(reading_id as int64) as reading_id,
    cast(meter_id as int64) as meter_id,
    cast(recorded_on as date) as recorded_on,
    cast(kwh as numeric) as kwh
from bronze_readings
