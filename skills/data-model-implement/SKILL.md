---
name: data-model-implement
description: Generate warehouse or framework code for an already reviewed Data Model Accelerator design, preserving existing conventions and scoped task ownership.
---

# Implement the reviewed design

If the user explicitly requests code with catalogue evidence or design review
pending, use [provisional generation](../data-model-accelerator/references/provisional-generation.md).
Record the actual request and author supported draft files now. Keep missing
bindings/definitions visible; the exception is file authoring, not approval or
execution. Otherwise follow the reviewed path below.

Delegated workers consume the coordinator's bounded task packet and selected
contracts under [targeted context](../data-model-accelerator/references/agent-context.md).
They do not recursively load the full workflow or repeat intake. The coordinator
retains responsibility for stage gates, approvals and complete coverage.

When coordinating this stage directly, load the sibling [Data Model Accelerator](../data-model-accelerator/SKILL.md)
and its [staged workflow](../data-model-accelerator/references/staged-engagement.md).
Require that shared folder and runtime; do not recreate missing contracts. Resume
the existing engagement and reuse its answers and current design.

Check the `implementation` stage for selected entity IDs and their dependency
closure. Missing or stale human design review keeps dependent generation blocked;
show the concrete scope and record actual explicit approval from the trusted
conversation or an authenticated review system. Host-recorded review is the
default for local candidates; external signed review is optional. Do not fabricate
reviewer identity or infer approval from a decision-answer file.
After review, assess [development effort](../data-model-accelerator/references/development-effort.md).

For dbt, use the coordinator's selected [runtime contract](../data-model-accelerator/references/dbt-runtime.md)
and upgrade findings. Preserve existing v1 projects, pin new distribution/version
choices, and prepare optional v2 checks/configuration as reviewable candidates.
Do not silently enable every new feature or rescan other specialists' context.

Register or reuse scoped tasks, show the reuse/regenerate/blocked plan, then invoke
the host's actual engineering specialists for runnable tasks. Preserve existing
framework conventions, source identifiers, shared-file ownership and independent
baseline ownership. Record current output hashes and actual execution references.
Code generation does not authorize project execution, semantic generation or deployment.
