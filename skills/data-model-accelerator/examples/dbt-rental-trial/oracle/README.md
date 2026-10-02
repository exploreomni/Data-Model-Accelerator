# Independent synthetic rental oracle

This directory is withheld from the implementation author. The source analyst
authored it before any candidate existed, using fabricated input rows and the
synthetic accepted definitions in `input/requirements.md`. No live warehouse,
customer policy, authenticated human approval, or Omni access policy is claimed.

`build_expected.py` reads only the source CSVs and source metadata. It selects the
latest version of each tenant-scoped entity before applying tombstones, then
performs exact Decimal arithmetic. It contains no candidate SQL or dependency on
candidate outputs. `source-receipts.json` pins the complete input used. The
`synthetic-oracle:*` identifiers are calculation receipts, not native query IDs.

The independent hand check is:

- A/R1: latest fee 120.00 minus refund 20.00 = 100.00; deposit 50.00 excluded,
  replicated fee counted once and tombstoned damage fee 7.00 excluded.
- A/R2: completed, no charge, revenue 0.00 and eligible count zero.
- A/R3: cancelled; excluded. A/R4: latest rental tombstone; excluded despite its
  live staged charge. Staging must not resurrect the old rental version.
- B/R1: fee 70.00 minus refund 5.00 = 65.00, using B's West Yard location.
- C/R9: one fee 42.00 = 42.00. This unique rental/location/charge is the clean
  legacy compatibility slice; the original report's direct joins also yield 42.

All gold rows sum to 207.00. A's current location name is Central Yard, not its
obsolete East Yard name or B's West Yard name. Current staging populations are
5 rentals, 8 charges and 3 locations; 5 charges are eligible; gold has 4 rows.

Eight cases cover full gold values, tenant A's population, all eligible charges,
all three staging populations, the clean compatibility slice and an expected
empty denied-persona query filter. The latter is a downstream selection probe,
not authentication, RLS or live Omni security validation. Null source fields,
conflicting equal-version payloads, multi-currency conversion and timestamps
beyond the fixed watermark are not covered by this bounded fixture.

`queries.json` maps each case ID to SQL selecting target columns with the frozen
query context. It contains no expected values. The host replaces only the
`source_revision` placeholder in a separate contract with the plan's exact source
snapshot hash, then freezes the baseline before engineering begins. Do not
regenerate expectations or adjust tolerances in response to candidate failures.
