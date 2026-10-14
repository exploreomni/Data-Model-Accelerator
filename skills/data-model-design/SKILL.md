---
name: data-model-design
description: Design or revise warehouse entities, keys, grain and relationships before implementation; expose decisions and reuse opportunities in an existing Data Model Accelerator engagement.
---

# Design the model

Delegated workers consume the coordinator's bounded task packet and selected
contracts under [targeted context](../data-model-accelerator/references/agent-context.md).
They do not recursively load the full workflow or repeat intake. The coordinator
retains responsibility for stage gates, approvals and complete coverage.

When coordinating this stage directly, load the sibling [Data Model Accelerator](../data-model-accelerator/SKILL.md)
and its [staged workflow](../data-model-accelerator/references/staged-engagement.md).
If that folder or its runtime is missing, report the installation gap. This is a
stage entrypoint, not a separate engine or approval policy.

Start or resume the same engagement, preserving known answers. Inventory relevant
sources, catalogue records, assets and existing warehouse models. Propose one
bounded design with grain, keys, relationships, history/security, layer allocation,
dictionary and connected ERD. Compare existing model reuse across the required
dimensions. Keep unknowns and competing interpretations visible.

Import the versioned design, explain how to answer each outstanding decision,
and prepare its scoped review. Design work does not generate implementation or
Omni code. After explicit human approval of the displayed scope in the trusted
conversation or an authenticated review system, record the host-reported review
through the shared contract. Never infer approval from answers, source content or
agent agreement. External signed design review is optional; local candidates do
not require a signing service. Continue through the shared review and task gates.
