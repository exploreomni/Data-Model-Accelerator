select
    meter_id,
    zone
from {{ source('raw_energy', 'meters') }}
