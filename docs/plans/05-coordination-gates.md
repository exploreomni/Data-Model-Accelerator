# Task 5: Separation and repair controls

Status: implemented and locally verified.

## Scope

Validate integration against task file ownership and source/spec/baseline hashes. Track actual host task IDs and independent roles. Enforce stale-evidence invalidation and bounded repairs; preserve native/human approval boundaries.

## Deliverables

Integration/evidence verifier and append-only repair events tied to exact candidate versions; diagnostics suitable for engineer handoff.

## Acceptance and verification

Reject cross-owner writes, baseline tampering, self-review identities, omitted tasks/cases, stale candidate/results, replayed events and excessive repairs. Treat identity claims as self-attested, not authentication.

## Sequence

Begin only after task 4's code and focused checks are complete. Record implementation evidence and limitations below before proceeding.

## Completion evidence

Implemented full integration/evidence association and locked append-only repair events with externally pinned heads and a three-repair limit. Seventeen integration tests and thirteen repair-log tests pass on Python 3.9 and 3.12. Independent review found and closed omitted planned-model coverage and historical baseline-switching gaps.

The gate rechecks source/specification, all planned native models, exact file ownership, independent execution identities, chronology, native evidence and recomputed accuracy. Trusted host records still establish identities and history; hashes do not authenticate them. Existing catalogue/documentation review and human/native acceptance remain separate.
