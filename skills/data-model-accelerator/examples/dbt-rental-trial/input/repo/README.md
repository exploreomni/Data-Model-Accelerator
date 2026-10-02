# Synthetic rental billing source

This deliberately messy dbt project is fabricated evaluation data, not a customer
repository or live catalogue. There are exactly 25 raw CSV rows across three CDC
seed relations. `models/legacy_report.sql` is a historical report observation;
accepted corrections and target contracts are in the parent requirements file.
No credentials or profiles are included. The isolated host supplies profiles.
