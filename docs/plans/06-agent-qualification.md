# Task 6: Qualification of the paired agents

Status: implemented; independent local trial and replay verified.

## Scope

Run a fresh independent source/analyst and engineering exercise on an unfamiliar synthetic domain, with the expected values withheld from the implementation author. Integrate all new components and retain failures, coverage and runtime context.

## Deliverables

Reproducible synthetic qualification fixture/report and CI; independent agent exercise record; documented live pilot requirements and remaining qualifications.

## Acceptance and verification

Replay complete workflow, inject representative defects, and verify correct failures. Run core and optional existing regressions as appropriate. Do not label mocked Snowflake or synthetic agent trials as live acceptance or general reliability.

## Sequence

Begin only after task 5's code and focused checks are complete. Record implementation evidence and limitations below before proceeding.

## Completion evidence

A fresh source/analyst authored 25 source rows and eight expected cases before a separate engineering agent implemented five models. Independent native build passed five models, three seeds and 67 dbt tests; all eight benchmark cases matched. Documentation covers eight relations and 63 columns. Executed fanout, dropped-tenant and wrong-amount variants were detected; wrong amounts passed dbt tests but failed the independent benchmark. A missing dictionary column also failed review.

The full optional suite passes 556 tests. Python 3.9 executes 256 core tests successfully and skips 300 optional checks. Ten replay boundary regressions cover fixture pins, path safety, preserved host timestamps and scope. CI now runs the pinned fixture replay with optimization enabled. Original artifacts, failed controls, analyst review and a documented timestamp-precision correction are retained under validation/analytics-engineering.

The live Snowflake/Omni pilot remains pending user-selected repository/profile/role/warehouse/destinations. The qualification report lists unexercised fixture branches and distinguishes actual agent authoring from repeatable artifact replay.
