# Views, fields and metrics

Bind physical identifiers to the approved catalogue, including dialect quoting. Derive keys from grain and observed uniqueness; a name is insufficient. Preserve NULL, zero, date/timezone and numerator/denominator semantics. SQL-derived measures need their own aggregation analysis, not an automatic `aggregate_type` insertion.

The generator handles explicit reviewed physical, derived, aggregate and inherited mappings within the v2 checker. Local measure filters support scalar/list `is` and `not`, numeric comparisons and bounded text operators on resolved dimensions. They stay attached to the measure. Query filters, dynamic operands and compound operators outside that subset remain unsupported. SQL, native execution and population parity are separate gates.

The checker accepts static integer fiscal offsets and documented default timeframes, and requires an offset for fiscal timeframes. Dynamic calendars, custom calendars and operational model settings are preserved but unqualified. Named and Excel-style format strings remain accepted; display formatting is not result semantics. The contract version changed to `omni-static-v2-2026-10-05`; old receipts do not qualify these additions.

Test ratio-of-sums versus sum-of-ratios, zero denominators, missing rows, filtered populations and drill context using independently frozen expectations.

Sources: [filtered measures](https://docs.omni.co/guides/modeling/single-field-filter), [symmetric aggregates](https://docs.omni.co/analyze-explore/sql/symmetric-aggregates).
