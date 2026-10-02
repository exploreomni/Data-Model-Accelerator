# Task 4: Accuracy benchmark engine

Status: implemented and locally verified.

## Scope

Compare separately collected actual result exports with frozen expected results using strict schemas, composite keys and decimal-safe arithmetic. Report compatibility and correctness separately with coverage and per-case discrepancies.

## Deliverables

Deterministic benchmark report with missing/extra/duplicate keys, value mismatches, explicit numeric tolerances, context and provenance checks, skipped/failed cases and result hashes.

## Acceptance and verification

Prove fanout, omitted rows, tenant/context mismatch, null/zero, empty outputs, wrong totals, decimal boundary behavior and deliberately defective results are detected. Never collapse missing coverage into a pass.

## Sequence

Begin only after task 3's code and focused checks are complete. Record implementation evidence and limitations below before proceeding.

## Completion evidence

Implemented complete-case benchmark comparison with exact composite keys, strict contexts/types/nulls, precise absolute/relative decimal tolerances, separate compatibility/correctness scores and bounded diagnostic detail with full mismatch counts. Twenty-two tests pass on Python 3.9 and 3.12, including CLI success/failure, duplicate/fanout results, missing cases, source/code drift and precision boundaries.

This compares supplied exports; it does not execute/authenticate warehouse or Omni queries, and coverage remains bounded by the frozen cases.
