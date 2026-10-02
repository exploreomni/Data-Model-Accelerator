# Deploy an approved modeling release

The deployment coordinator turns a prepared handoff into a specific release plan, executes it through an externally configured runner, and retains native receipts. An offline review page can request an action; it cannot approve or perform it.

Start with the [operator runbook](../skills/data-model-accelerator/references/deployment.md). It contains installation, runner policy, exact commands, signing contracts and the supported native routes. Use [guided start](guided-start.md) to create the source assessment and prepared handoff first.

## Metadata release phases

Metadata-enabled builds now bind their v2 dictionary and expected configuration in the frozen handoff. A separately reviewed native metadata phase links the completed build, exact physical destination, catalogue and artifact hashes. Target comments/tags and optional RAW comments remain distinct. Independent acceptance recomputes physical coverage and expected metadata from bound observations; imported `passed` flags cannot satisfy it. A parent recovery cannot clear an active child's lock.

These linked phases are tested in **simulation**. Automatic live metadata dispatch is intentionally blocked until an authenticated native collector can recheck drift immediately before writes. Use the generated reviewed SQL/operator or independently governed CI handoff meanwhile. Pre-build observations, changed object incarnations and altered scope are rejected. See the [metadata runbook](../skills/data-model-accelerator/references/warehouse-metadata.md) for configuration templates, authority, readback and recovery. This limit does not change existing model-deployment routes or authorize bypassing their review.

## What an operator needs

- Python 3.9+ on a POSIX system and the pinned [deployment verification dependency](../skills/data-model-accelerator/scripts/requirements-deployment.txt).
- A separate runner policy containing explicit destinations, trusted Ed25519 public keys, allowed actions and any required native binaries pinned by SHA-256. Credentials remain in the trusted runner's environment or provisioned vendor profiles.
- An institutional approval service that authenticates model reviewers and deployment approvers before signing exact plan bindings. A separate validation issuer signs execution acceptance. The toolkit does not issue human approval or supply production signing keys.
- A reviewed commit, exact handoff files, target identity, affected-object list, recovery procedure and independent native checks. The operator must establish that the remote commit/job/bundle executes those reviewed artifacts; a declared commit SHA alone does not prove it.

## The release path

1. Record a current prepared handoff. Preserve the source, catalogue, business decisions and candidate hashes.
2. Select `publish_pr`, `deploy_development` or `promote`, and prepare the exact plan against a provisioned destination.
3. Bind the current complete [lint report](LINTING.md) for live submission, then export the approval request. Obtain externally signed model sign-off and deployment approval for its exact bindings. Live approval also requires independently obtained native identity, permissions and artifact/commit preflight evidence.
4. Submit once. Follow the recorded operation ID with `status`, `observe` or `cancel`; do not retry a timed-out submission blindly.
5. For execution, obtain independent signed evidence for physical schema, grain, fanout, source reconciliation, metrics, access and actual principal/namespace. Include semantic-consumer evidence when selected. Native success initially reaches `verification_pending`.
6. Export a separate deployment review HTML/ZIP. Keep the approved release handoff unchanged; retain its original hashes in the post-run presentation.

`publish_pr` requires a trusted `publication_destinations` policy entry containing the exact repository, base and head for the selected destination. Those values and the immutable commit appear in review and are bound to approval; a warehouse destination alone does not permit publication. It creates a draft PR from an **existing reviewed remote branch** after checking its head SHA and every prepared file at that commit except the independently reviewed `.md`/`.txt` PR body, then rereads the PR's head/base identity. Relabeling SQL or macros as documentation cannot bypass content checks. It does not commit, push, merge or deploy that branch. GitHub workflow dispatch is a separate execution adapter and requires a customer workflow that validates its artifact-commit and target inputs.

Execution records retain their original plan, policy, mode, target, context and required checks throughout observation, reconciliation, acceptance and recovery. Edited plans and fresh signatures cannot turn simulated receipts into live acceptance or weaken their checks. Rejected drift leaves the journal unchanged. Complete or recover pending runs before policy rotation; recovery can settle a run after candidate drift but requires the original trusted plan/policy and fresh independent recovery evidence.

Direct Coalesce live submission is blocked before mutation because its automatic status/results continuation does not yet bind the approved profile domain. The review explains this limitation before submission; cancellation descriptors pin the approved domain and environment. Use the reviewed Git/CI handoff until profile-domain binding is implemented and qualified. The documented CLI exposes domain/environment flags for cancellation but no domain override for `runs get` or `runs list-results`. [Coalesce CLI commands](https://docs.coalesce.io/docs/coa/version-733-and-above/coa-commands).

## Read the evidence labels

| Label | Meaning |
|---|---|
| `simulation` / `simulation_verified` | Controlled local fixtures and synthetic authority; no live-platform acceptance. |
| `running` | A native request has been identified; completion is pending. |
| `unknown_remote_state` | Submission or observation is uncertain; it may already have affected the destination. |
| `verification_pending` | Native execution completed; independent acceptance remains outstanding. |
| `deployed_verified` | A live runner accepted an independent signed attestation covering the exact required checks and receipts. Its validity depends on the external issuer and evidence. |
| `recovered` | Separately attested remote quiescence and recovery released the runner lock. The coordinator did not execute rollback. |

The supplied adapters and tests are executable contracts, **not live-provider qualification**. Identity fields in adapter receipts verify only the listed native response fields; they do not authenticate the configured principal or prove business meaning. Promotion additionally requires an external adapter-qualification attestation covering the target, runtime, verified development outcome and rehearsed recovery.

Run the local deployment checks from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_deployment*.py' -v
```

Use the runner environment with the pinned verification dependency. Simulation execution uses an injected test transport through the Python API; setting `mode` to `simulation` does not turn a live CLI command into a safe warehouse dry run.
