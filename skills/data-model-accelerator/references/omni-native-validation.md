# Native Omni development validation

`scripts/omni_native.py` is a bounded, callable adapter for an **existing, isolated development branch**. It supports exact candidate readback and model validation, reviewed YAML updates, modeled query compilation, and modeled query execution. It never merges branches, publishes documents, follows automatic fixes, deletes files, impersonates users, or creates workbook SQL queries. Live tenant qualification remains pending until a separately authorized pilot runs.

## Boundary and evidence

A trusted runner loads a `deployment_runner_policy` outside the candidate directory, pins one explicit destination, and controls the Ed25519 issuer key. Use the existing deployment-authority policy and attestation contract; do not put keys, policy, approvals, journals, or receipts inside generated deliverables. The adapter requires:

- Canonical HTTPS `https://<instance>.omniapp.co`; TLS verification stays on, redirects and environment proxies stay off. Custom hosts are unsupported pending explicit qualification.
- Exact development model, existing branch, main connection, environment connection and principal UUIDs. Remote model lineage, connections, principal and permissions are read back.
- Full candidate file inventory and warehouse context, a passing static checker, and complete clear disclosure scanning of the request before external calls.
- An external policy destination exactly matching the target. Writes and queries require a current signed `deployment_approval`, exact request/file/context/target/policy hashes, and preflight evidence. The policy is reloaded before each write or query request.
- Signed preflight: namespace and permission verification, existing destination approval, synthetic data only, isolated destination, exclusive branch, audience/access-policy/evidence hashes and a reference. Query requests also bind the verified effective timezone.

The initial release permits approved **synthetic development data only**. A classifier pass does not qualify data as public or prove access control. Live observations are not customer acceptance, correctness, or privacy qualification. Any injected transport is permanently labeled simulation, regardless of the supplied policy. Missing credentials produce `pending`, not a pass.

## Request and execution

`schema_version: 1`, `kind: omni_native_request` requires:

| Field | Content |
|---|---|
| `run_id` | Unique safe identifier; reuse only to reconcile the same interrupted operation |
| `operation` | `validate`, `update_and_validate`, or `query` |
| `destination_id` | Exact provisioned policy destination |
| `target` | `instance_url`, `model_id`, `branch_id`, `connection_id`, `environment_connection_id`, `principal_id`, `environment: development` |
| `files` | Complete native filename-to-YAML map (`model`, `relationships`, `name.view`, `name.topic`) |
| `context` | `omni_model_context` bound to the development warehouse catalogue |
| `expected_remote` | Bootstrap hashes `authored_sha256`, `resolved_sha256`, `base_sha256`, `schema_sha256`, `identity_sha256` |
| `warning_policy` | Explicit `fail` or `allow` |
| `commit_message` | Reviewed bounded message |
| Query only | `query`, `query_mode: plan\|execute`, `timezone` (IANA timezone) |

Queries require exact `modelId`, modeled topic `table`, nonempty modeled `fields`, and `limit` from 1–1000. Arbitrary SQL, edited SQL, impersonation, and workbook creation parameters are unsupported. `plan` is native compilation; it cannot satisfy an executed-query acceptance lane. Skip-cache and explicit branch, environment connection and timezone are sent for both modes.

Run these commands from the skill directory with the pinned optional semantic/deployment dependencies installed. The trusted operator provisions the external policy first. `inspect.json` contains only the target object and destination ID.

```sh
python scripts/omni_native.py inspect --request /private/runner/inspect.json --policy /private/runner/policy.json --candidate-root /work/candidate --output /private/runner/snapshot.json
python scripts/omni_native.py bindings --request /private/runner/request.json --policy /private/runner/policy.json --candidate-root /work/candidate --output /private/runner/bindings.json
python scripts/omni_native.py run --request /private/runner/request.json --policy /private/runner/policy.json --candidate-root /work/candidate --approval /private/runner/approval.json --output /private/runner/receipt.json
```

`inspect` is read-only and writes a private snapshot. Build the complete desired files and `expected_remote` from that snapshot; obtain the exact signed review after the request is final. `validate` needs no mutation approval, but still requires trusted destination provisioning and exact readback. Use `OMNI_API_TOKEN` from the runner environment; never put a token in arguments or artifacts. Output files must be new paths outside the candidate and are mode 0600. Journals live in the policy's private state root.

Python interfaces: `inspect_remote`, `request_bindings`, `run`, `run_reviewed_variants`, and `verify_receipt`. `verify_receipt` checks consistency only and always returns `authenticated: false`. Imported JSON cannot authenticate native history. The separate acceptance workflow must authenticate the observation and its exact candidate bindings.

## Recovery and limits

Before every YAML update the adapter re-reads the branch and stable base/schema/identity. Existing files use the API's `previousChecksum`; the exact file is read back afterward. New files lack a documented atomic create-if-absent precondition, so exclusive branch ownership is mandatory and remains a limitation. A multi-file update is not atomic.

Intent is durably journaled before each mutation. A timeout or unknown response does not cause an automatic retry. Reusing the same run reads the remote state first: desired bytes confirm the prior write; unchanged original bytes permit one bounded retry; conflicting bytes stop. No deletes or rollback are attempted. Schema/base/identity drift, unexpected authored files, a stale approval, or a changed policy blocks execution.

Query timeouts with documented job IDs resume through `/query/wait`; an unknown submission without IDs cannot be resubmitted automatically. Completed query journals cannot be replayed as fresh execution evidence: retain the original receipt or create a new reviewed run. Responses contain hashes, issue severity/counts, and bounded execution metadata, not provider messages, SQL or row values.

At most two supplied repair variants are supported. Each subsequent variant requires an independently signed exact approval, `semantic_scope_unchanged: true`, and `supersedes_request_sha256`. Ambiguous or semantic changes stop for review. Native `auto_fix` is always inert.

## Documented API surface

Verified against the [official Omni API documentation](https://docs.omni.co/api/introduction) on 2026-10-05 (snapshot SHA-256 `86fdc5f6a4448883ff2e5703b7df64712619af20e3f7d3041e63aec328ac3acf`). This implementation uses only:

- `GET /api/v1/whoami?modelId=...`, `GET /api/v1/models?modelId=...`, and `GET /api/v1/connections/{id}` for identity.
- `GET /api/v1/models/{modelId}/yaml` with `branchId`, `mode=combined`, `includeChecksums=true`, and explicit `fullyResolved` for authored/resolved/base/schema snapshots.
- `POST /api/v1/models/{modelId}/yaml` with `fileName`, `yaml`, `mode`, `branchId`, `fullyResolved=false`, `commitMessage`, and existing-file `previousChecksum`.
- `GET /api/v1/models/{modelId}/validate?branchId=...`. HTTP 200 is a bare issue array, not proof of success. Error issues fail; warnings follow the reviewed policy. Malformed issues fail closed.
- `POST /api/v1/query/run` and `GET /api/v1/query/wait?jobIds=...`. JSON execution rows are counted but withheld; NDJSON requires complete jobs and the documented footer. HTTP 408's bounded remaining-job response is retained for recovery.

Neither before/after snapshots nor passing local simulations prove an atomic remote transaction or production readiness. Native behavior remains tenant-unqualified until an approved isolated pilot validates these contracts.
