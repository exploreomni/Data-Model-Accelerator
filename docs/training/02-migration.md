# 2. Follow a migration

[Learning path](README.md) · [Previous](01-understand.md) · [Next: explore a domain](03-domain.md)

**Your goal: understand the complete migration while choosing a manageable delivery sequence.**

Imagine a fictional subscription business moving scattered reporting logic into shared warehouse models and Omni. This wider company scenario is illustrative. The Billing artifacts in the next lesson come from the maintained synthetic Hex example. Sales and Product Usage are teaching domains, not completed implementations.

## Inventory the whole agreed scope

Supply repositories, report/workbook exports, a warehouse catalogue and business rules. Identify the old implementation separately from the future repository. Existing work in the future repository is a reuse candidate, not automatically correct.

Account for every supplied in-scope asset, including unread, unsupported, excluded and unresolved items. A partial export must not appear complete. The agent proposes domains from business processes, relationships and shared rules across reports.

| Candidate domain | Example responsibilities | Shared dependency | Teaching status |
| --- | --- | --- | --- |
| Sales | Accounts, opportunities and conversion | Customer identity | Proposed; no code here |
| Billing | Invoices, payments, adjustments and history | Customer identity and history | Worked synthetic example |
| Product Usage | Events, adoption and engagement | Customer identity | Proposed; no code here |

Reports are requirements to satisfy. They do not require one new table or topic each. Shared customer definitions should not be independently reinvented for each domain.

## Choose the first domain

Review the boundaries and dependencies, then select a domain. Here the team chooses Billing because it has usable evidence and a reviewer who understands the definitions. This is a teaching choice, not a universal priority rule.

The agent designs the related tables, exposes unresolved decisions and iterates with you. After scoped design approval it generates selected warehouse and semantic files. You can explicitly request provisional code before every answer is available.

## Keep the whole migration visible

| Track separately | What it tells you |
| --- | --- |
| Inventory and mappings | Which old assets have destinations, exceptions or unresolved gaps |
| Domain progress | What is queued, active, paused, completed or stale |
| Code and semantic delivery | Which requested files actually exist |
| Validation and acceptance | What was checked, by whom and against which version |
| Deployment and retirement | What was authorized and confirmed in the real environment |

An asset can be accounted for without being migrated. Proposed retirement or deferral needs a decision; it must not quietly reduce migration coverage. Domain completion does not establish dashboard acceptance or production deployment.

Keep the same saved engagement for the next domain. Reuse unchanged extraction and reviewed shared models. Revisit affected dependencies when a shared definition changes.

## You're ready when

You can distinguish migration-wide scope from the active domain, identify a shared dependency, and explain why generating Billing code does not finish the company's migration.
