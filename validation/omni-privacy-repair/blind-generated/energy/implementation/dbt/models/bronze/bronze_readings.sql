select
    reading_id,
    meter_id,
    recorded_on,
    kwh
from {{ source('raw_energy', 'readings') }}
