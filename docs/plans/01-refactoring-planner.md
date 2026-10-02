# Task 1: Refactoring work planner

Status: implemented and locally verified.

## Scope

Add explicit analytics-engineer and validation-analyst role contracts. Plan domain tasks from a reviewed model specification and a captured dbt project; validate dependency order, unique file ownership and shared resources. Produce bounded host-dispatch prompts, not a fabricated agent execution.

## Deliverables

Model IDs, source/catalogue/spec hashes, dependency waves, exact write ownership, integration checklist and role prompts.

## Acceptance and verification

Reject cycles, unresolved dependencies, duplicate paths/owners, path escape and unaccepted model decisions. Prove deterministic plans and dependency ordering on an existing dbt project.

## Sequence

Begin after all six plans are recorded. Record implementation evidence and limitations below before proceeding.

## Completion evidence

Implemented separate analytics-engineer and validation-analyst contracts, exact file ownership, deterministic dependency waves and bounded task prompts. Twenty focused tests pass on Python 3.9 and 3.12. The CLI also planned a two-domain refactor against the existing retail input project without changing source files. Skill validation and whitespace checks pass.

This is a planning contract; it does not authenticate agents, execute their tasks, verify the supplied catalogue hash against live metadata, or establish deployment acceptance.
