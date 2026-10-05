select
    cast(meter_id as int64) as meter_id,
    cast(zone as string) as zone
from bronze_meters
