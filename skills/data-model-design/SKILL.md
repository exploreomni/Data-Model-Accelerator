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

Start or resume the same engagement, preserving known answers. For multi-domain
work, follow the [domain journey](../data-model-accelerator/references/domain-journey.md):
record the user-selected domain before detailed design, keep other domains queued,
and include only necessary declared shared interfaces. Inventory relevant
sources, catalogue records, assets and existing warehouse models. Propose one
bounded design with grain, keys, relationships, history/security, layer allocation,
dictionary and connected ERD. Compare existing model reuse across the required
dimensions. Keep unknowns and competing interpretations visible.

Follow [design reliability](../data-model-accelerator/references/design-reliability.md)
for independent source coverage, supported canonical assembly and provenance.
Account for transformations, intermediate stages, macros and consumers before
claiming completeness. Classify warehouse observations, repository declarations,
human assertions and target proposals separately. Capture existing-model
baselines independently; do not copy the proposed design into the reuse baseline.
Use explicit source/model/interface kinds, preserve relationship direction and
column bindings, and derive documents and diagrams from the same revision.
An independent reviewer uses original scoped evidence and records a bound review
before the separate human decision. Missing context remains compatible with the
shared provisional-generation path.

For a refactoring or mixed domain with historical comparison selected, follow
[legacy alignment](../data-model-accelerator/references/legacy-alignment.md).
Use the retained baseline during design and present the old-table-to-new-model
comparison before review, including unmapped fields and intentional corrections.
A comparison can also be added to an existing design; report discrepancies
before changing approved entities. Mapping is not parity or design approval.

Import the versioned design, explain how to answer each outstanding decision,
and prepare its scoped review. Design work does not generate implementation or
Omni code. After explicit human approval of the displayed scope in the trusted
conversation or an authenticated review system, record the host-reported review
through the shared contract. Never infer approval from answers, source content or
agent agreement. External signed design review is optional; local candidates do
not require a signing service. Continue through the shared review and task gates.
