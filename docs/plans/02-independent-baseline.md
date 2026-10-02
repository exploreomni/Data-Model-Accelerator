# Task 2: Independent baseline

Status: implemented and locally verified.

## Scope

Freeze analyst-authored compatibility and accepted-correction cases before candidate implementation. Bind expected results to source receipts, context, data watermark and independent author identity; retain immutable hashes.

## Deliverables

Benchmark bundle with case denominators, source provenance, typed columns/keys, per-metric tolerances, execution context and immutable evidence associations.

## Acceptance and verification

Reject duplicate/missing cases, unreferenced result columns, ambiguous keys, invalid/nonfinite tolerances, missing correction authority and changed baseline files. Never derive expected data from candidate output.

## Sequence

Begin only after task 1's code and focused checks are complete. Record implementation evidence and limitations below before proceeding.

## Completion evidence

Implemented freeze_benchmark.py with separate compatibility/correctness cases, exact typed schemas/composite keys, bounded decimal tolerances, context, independent export receipts and pinned original contract. Verification detects modified receipts and rehashed embedded-row tampering. Eighteen focused tests pass on Python 3.9 and 3.12, including CLI freeze/verify and overwrite refusal.

Identity and approval fields remain self-attested; provenance review and a protected frozen digest are required to establish independence. No source query or candidate query is executed by this helper.
