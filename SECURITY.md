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
credentials. Dependency advisories and secrets are checked on pushes, pull
requests and a weekly schedule, with manual reruns available. Dependency update
proposals do not auto-merge.

## CI runtime controls

- Jobs use an explicit Ubuntu 24.04 baseline, supported Python 3.12, a reviewed
  hash-pinned pip and complete, hash-locked wheel-only dependency environments.
  Direct native dbt wheels retain publisher provenance and are included in the
  advisory audit rather than silently skipped as URL requirements.
- Checkout credentials are not persisted. Jobs use read-only repository tokens,
  bounded timeouts and cancellation of superseded runs. Third-party Actions must
  be reviewed and commit-pinned; the repository allowlist currently permits only
  checkout and Python setup.
- Disposable hosted workers refresh installed distro curl/PHP packages before
  use and reject the known affected PHP baseline. The job summary records the
  actual image and post-update versions. This helper refuses to run outside a
  GitHub-hosted worker; it is not a customer-machine update script.
- The selected OS label continues receiving GitHub image updates; it does not
  freeze an old image build. GitHub owns the base image, kernel and hypervisor.
  Passing package checks does not certify every preinstalled component or prove
  vulnerability reachability. New relevant image advisories require review of
  their affected paths, vendor fixes and the next observed runner version.
- Source requirement and lockfile drift fails CI. Changes to the updater,
  provenance or lock hashes must receive the same review as executable code.

See [the reproducible Linux setup](CONTRIBUTING.md#reproduce-the-hardened-linux-ci-environment).
