# Security

Report a potential vulnerability privately through this repository's
[security advisory form](https://github.com/exploreomni/Data-Model-Accelerator/security/advisories/new).
Do not put credentials, customer files, exploitable payloads, or private warehouse
details in a public issue. Include the affected commit, a minimal synthetic
reproduction, and the expected trust boundary.

Security fixes target the latest `main`. There is no promised response SLA or
security certification. Scan results establish only the tools, inputs and date
recorded in the [CI run for that commit](https://github.com/exploreomni/Data-Model-Accelerator/actions).

## Operating boundaries

- Treat source repositories, notebooks, SQL, XML, metadata and generated prose as
  untrusted input. Assess read-only, scope the inventory, and keep output separate.
- Do not run customer macros, hooks, packages or notebooks during discovery.
  Qualified execution requires a separate approved environment without unrelated
  credentials. These helpers are not a general-purpose execution sandbox.
- Keep credentials outside inspected repositories and generated deliveries.
  Review deliverables before sharing; SQL and connection names may themselves
  contain sensitive business information.
- Deploy only the reviewed artifact version to an approved target using scoped
  credentials and independent acceptance checks. Synthetic receipts do not
  authorize a live deployment. Automatic live metadata dispatch remains blocked
  pending authenticated native drift-collector integration.
- Local hashes detect changes; they do not establish reviewer identity or
  business approval. Use the signed, provisioned authority flow where required.

Public CI uses synthetic inputs, read-only repository permissions and no warehouse
credentials. Dependency advisories and secrets are checked on pushes and pull
requests. Dependency update proposals do not auto-merge.
