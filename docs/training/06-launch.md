# 6. Launch your migration

[Learning path](README.md) · [Previous: install and verify](05-install.md)

**Your goal: start a saved migration with clear scope and a complete first domain.**

## Prepare what you have

- Migration outcome and approved repositories or exports in scope.
- Which implementation is legacy and which repository is the destination.
- Reports and dashboards that must be satisfied or reviewed for retirement.
- Available warehouse tables/columns, business rules, naming policy and known errors.
- Preferred warehouse, transformation tool and Omni scope; unknown is acceptable.
- People who can review definitions and validate implementation; roles may overlap.
- Desired design, code, semantic and mapping outputs; optional Excel/Word or Google migration plans.

Use approved locations and sanitized evidence. Keep credentials and sensitive customer records out of prompts. The agent should ask targeted questions and retain unresolved decisions.

## Copy this kickoff prompt

Replace the bracketed fields and paste into your configured coding assistant.

```text
Use the Data Model Accelerator. Confirm the active installation.
Help us migrate or refactor the whole agreed scope.

Outcome: [what is changing and why].
Legacy inputs: [approved repository/export locations].
Future repository and reusable models: [location or unknown].
Reports and dashboards to satisfy: [inventory or unknown].
Warehouse catalogue: [location or unknown].
Tools and warehouse: [choices or unknown].
Omni and dashboard scope: [choices or unknown].
Business rules, known errors and naming: [details or unknown].
Reviewers: [roles or unknown].
Save outside the input repositories: [new engagement folder].

Keep sources read-only. Inventory the agreed scope, propose
domains and shared dependencies, and recommend an order.
Ask which domain we want first. Design that complete domain
for its related reports, metrics and business questions.
Use inventories as requirements, not one model per report.
Show reused, new and replaced models and unresolved mappings.

Provide diagrams, dictionary, layer guidance and decisions
for review before implementation. Ask which code, semantic
and migration-plan outputs we want. Preserve naming choices.
Keep requested provisional code available with missing context.
Retain progress and provide one current review package.
Do not deploy, create live tickets or retire sources at intake.
```

## What should happen next

Expect coverage and input summaries, missing-context questions, domain choices, dependencies and a saved location. Select a domain, then review its entities and rules. Incomplete inventory remains a visible gap.

When ready, say: “I approve the displayed design for [domain/version]. Generate the selected warehouse and Omni candidates. This approves candidate generation, not execution or deployment.” Include Omni only if selected.

For earlier code, say: “Generate provisional files for [domain]. Label unresolved bindings and business rules. Do not infer approval.” Design documents alone do not complete a code request.

## Continue toward the full migration

Choose the next domain after the current agreed work. Resume the saved engagement and reuse unchanged inputs and models. Shared-definition changes may require rechecking dependent domains.

For reporting migration, use the optional Omni Artifact Accelerator handoff or an explicit engineering route. Topics alone do not rebuild dashboards. Require independent comparisons and access checks; separately authorize execution, release and retirement. Retain cutover and recovery responsibilities.

Track what is inventoried, mapped, generated, validated, accepted, deployed, deferred and unresolved. Mappings and documents do not prove parity. Deferred work must remain visible instead of silently reducing scope.

## You're ready when

You have a saved location, an agreed first domain, review responsibilities or visible ownership gaps, and expected outputs. Begin the engagement without treating the learning example as production evidence.
