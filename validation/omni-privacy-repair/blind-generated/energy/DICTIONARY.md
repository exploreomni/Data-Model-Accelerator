# Energy dictionary
All physical namespaces/types are synthetic plans. Definitions are proposed; approvals, ownership, source NULL semantics, CDC/history, retention and currency remain unresolved.

## source:readings
Grain: One row per reading_id is a synthetic contract; original platform grain unknown

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| reading_id | TEXT (CSV lexical contract) | Reading identifier in the supplied snapshot. | Identity retention of lexical CSV value |
| meter_id | TEXT (CSV lexical contract) | Meter identifier used for the unique meter lookup. | Identity retention of lexical CSV value |
| recorded_on | TEXT (CSV lexical contract) | Reading date retained for interactive UTC date filtering. | Identity retention of lexical CSV value |
| kwh | TEXT (CSV lexical contract) | Energy usage in kilowatt-hours; additive across selected readings. | Identity retention of lexical CSV value |

## source:meters
Grain: One row per meter_id is a synthetic contract; original platform grain unknown

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| meter_id | TEXT (CSV lexical contract) | Meter identifier used for the unique meter lookup. | Identity retention of lexical CSV value |
| zone | TEXT (CSV lexical contract) | Meter zone retained for interactive filtering. | Identity retention of lexical CSV value |

## bronze_readings
Grain: One row per reading_id in the supplied snapshot; no historical uniqueness asserted

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| reading_id | TEXT (CSV lexical contract) | Reading identifier in the supplied snapshot. | Identity retention of lexical CSV value |
| meter_id | TEXT (CSV lexical contract) | Meter identifier used for the unique meter lookup. | Identity retention of lexical CSV value |
| recorded_on | TEXT (CSV lexical contract) | Reading date retained for interactive UTC date filtering. | Identity retention of lexical CSV value |
| kwh | TEXT (CSV lexical contract) | Energy usage in kilowatt-hours; additive across selected readings. | Identity retention of lexical CSV value |

## bronze_meters
Grain: One row per meter_id in the supplied snapshot; no historical uniqueness asserted

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| meter_id | TEXT (CSV lexical contract) | Meter identifier used for the unique meter lookup. | Identity retention of lexical CSV value |
| zone | TEXT (CSV lexical contract) | Meter zone retained for interactive filtering. | Identity retention of lexical CSV value |

## silver_readings
Grain: One row per reading_id

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| reading_id | INT64 | Reading identifier in the supplied snapshot. | Explicit cast to int64; invalid values fail rather than silently null. |
| meter_id | INT64 | Meter identifier used for the unique meter lookup. | Explicit cast to int64; invalid values fail rather than silently null. |
| recorded_on | DATE | Reading date retained for interactive UTC date filtering. | Explicit cast to date; invalid values fail rather than silently null. |
| kwh | NUMERIC | Energy usage in kilowatt-hours; additive across selected readings. | Explicit cast to numeric; invalid values fail rather than silently null. |

## silver_meters
Grain: One row per meter_id

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| meter_id | INT64 | Meter identifier used for the unique meter lookup. | Explicit cast to int64; invalid values fail rather than silently null. |
| zone | STRING | Meter zone retained for interactive filtering. | Meter zone retained for interactive filtering. |

## gold_readings
Grain: One row per reading_id

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| reading_id | INT64 | Reading identifier in the supplied snapshot. | Explicit cast to int64; invalid values fail rather than silently null. |
| meter_id | INT64 | Meter identifier used for the unique meter lookup. | Explicit cast to int64; invalid values fail rather than silently null. |
| recorded_on | DATE | Reading date retained for interactive UTC date filtering. | Explicit cast to date; invalid values fail rather than silently null. |
| kwh | NUMERIC | Energy usage in kilowatt-hours; additive across selected readings. | Explicit cast to numeric; invalid values fail rather than silently null. |
| zone | STRING | Meter zone retained for interactive filtering. | Meter zone retained for interactive filtering. |
