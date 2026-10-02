# Task 7: Independent value and physical-schema evidence

Status: complete; local verification passed.

## Scope

Promote the reusable checks learned from a separately held private-repository exercise without copying its source, fixtures, reports, identifiers or agent transcripts. Preserve the existing version-1 contracts for archived qualifications; new engagement validation must use independently pinned expected values and physical model/column observations.

## Implementation

- Add strict, reusable DB-API value serialization using the frozen column contract. Preserve decimals, nulls and timestamp offsets; reject nonfinite values, coercive booleans, duplicate column names and incomplete populations.
- Add a physical-schema verifier that reconciles a separately supplied observed relation/column inventory with the documentation inventory, bound to a candidate digest. Exact model/column coverage and explicit identifier comparison are required; a mutually incomplete dictionary and declared inventory must fail.
- Require a pinned list of source-value conservation cases alongside the complete existing benchmark in the new engagement workflow. Key/value equality is independently checked; native dbt test success is insufficient.
- Add regressions for incorrect dimension attribution, internally consistent wrong cost, omitted observed columns, extra relations, case/quote-sensitive identifiers, decimal wire types and drift.

## Verification

Run focused serializer, benchmark and physical-schema tests plus existing documentation regressions. Tests use newly authored generic synthetic records or existing public fixtures only. Supplied physical metadata is evidence, not authenticated warehouse access or enforcement. Native metadata collection belongs to the authorized execution adapter.

## Sequence

Finish this task's code and focused checks before Task 8 implementation. Record exact validation and remaining qualifications here.

Result: 81 focused checks passed (13 serializer, 7 physical schema, 4 source-value coverage, 22 benchmark, 35 review-package regressions). Checks reconcile exact relation/column names, not physical types or nullability; exports and field coverage remain explicitly declared evidence requiring independent capture/review. Task 8 will make these checks mandatory in the new engagement entry point.
