# Deployment operator runbook

Use this after [recording a prepared handoff](guided-workflow.md#record-a-prepared-handoff). The coordinator plans and executes already-reviewed artifacts. It does not generate business approval, infer missing platform credentials, install native tools or qualify a provider through local fixtures.

## Install and provision the runner

For metadata-enabled releases, also follow [warehouse-metadata.md](warehouse-metadata.md). Freeze the dictionary and expected configuration before build review; use separately linked metadata plans. Their automatic live dispatch remains blocked pending authenticated current-state collection, while simulation and reviewed SQL/operator delivery are implemented. Never route metadata SQL through a dbt job or modify a frozen handoff to insert later receipts.

The helpers require Python 3.9+ and a POSIX filesystem. Discovery/planning is primarily standard-library code; signature verification additionally requires the exact version in `scripts/requirements-deployment.txt`. Install it in the institution's runner environment:

```sh
python3 -m venv /absolute/runner-venv
/absolute/runner-venv/bin/python -m pip install \
  -r /absolute/installed-skill/scripts/requirements-deployment.txt
```

Examples below use `DMA_SKILL=/absolute/installed-skill` and `DMA_PY=/absolute/runner-venv/bin/python`. Replace all example paths, IDs and version labels with approved values. Keep the source repository, candidate artifacts, engagement, runner policy, runner state and issuer private keys separate. Filesystem separation alone does not isolate processes using the same OS account: use an institution-controlled runner and signing/validation services with appropriate access separation.

Provision a policy owned by the runner account and not writable by group/others. Its `state_root` must be outside the source/candidate and private to the runner (mode `0700`). Execution obtains its policy from the trusted `DMA_RUNNER_POLICY` environment variable; a submitted request cannot choose the execution policy.

This is a **template**, not an operational account or signing configuration:

```json
{
  "schema_version": 1,
  "kind": "deployment_runner_policy",
  "runner_id": "institution-modeling-runner",
  "mode": "simulation",
  "allowed_actions": ["deploy_development"],
  "state_root": "/absolute/private-runner-state",
  "journal_key_env": "DMA_JOURNAL_KEY",
  "max_attestation_age_seconds": 86400,
  "timeout_seconds": 120,
  "revoked_ids": [],
  "runtime_env": {},
  "tools": {},
  "issuers": {
    "review-service": {
      "public_key": "<BASE64_RAW_32_BYTE_ED25519_PUBLIC_KEY>",
      "purposes": ["model_signoff", "deployment_approval"],
      "actors": ["<AUTHENTICATED_APPROVER_ID>"]
    },
    "validation-service": {
      "public_key": "<DIFFERENT_BASE64_RAW_32_BYTE_ED25519_PUBLIC_KEY>",
      "purposes": ["deployment_acceptance", "adapter_qualification", "deployment_recovery", "deployment_reconciliation"],
      "actors": ["<AUTHENTICATED_VALIDATOR_ID>"]
    }
  },
  "destinations": {
    "snowflake-test": {
      "adapter": "snowflake_sql",
      "framework": "native_sql",
      "warehouse": "snowflake",
      "environment": "test",
      "namespace": {"database": "TEST_DB", "schema": "GOLD"},
      "identity": "service_principal",
      "runtime_version": "<APPROVED_RUNTIME_VERSION>",
      "base_url": "https://example.snowflakecomputing.com",
      "role": "MODELER",
      "compute": "TEST_WH",
      "auth_env": {"token": "SNOWFLAKE_TOKEN"}
    }
  }
}
```

The runner administrator supplies `DMA_JOURNAL_KEY` from its secret store (at least 32 bytes) and vendor credentials through the referenced environment names. Policy public keys are raw Ed25519 keys encoded as Base64; issuer IDs must have distinct keys. Private signing keys never belong in the candidate, policy, review ZIP or runner artifacts. `revoked_ids` and expiry constrain attestations; changing any policy content invalidates an existing plan's policy binding. Complete or recover outstanding runs under their original policy before rotating that policy. The coordinator does not migrate execution records to new trust or change simulated records into live evidence.

PR publication requires both `publish_pr` in `allowed_actions` and an explicit `publication_destinations` entry keyed by the request's configured `destination_id`. A warehouse destination alone grants no repository write authority. For example, the runner administrator can add this exact destination to the policy above:

```json
"publication_destinations": {
  "snowflake-test": {
    "repository": "example/models",
    "base": "main",
    "head": "reviewed-release"
  }
}
```

Repository, base and head must match exactly; wildcards and implicit default branches are unsupported. The full policy hash and publication destination hash enter the signed approval bindings, and the review summary displays repository, base, head and immutable commit. A missing or mismatched destination fails before publication planning. A different branch requires a new policy-bound plan and approval.

For a process adapter, `tools` maps its logical name to `{"path":"/absolute/native-binary","sha256":"<64-lowercase-hex-digest>"}`. Install and qualify only the tools selected below. The runner checks that binary's bytes and invokes it without a shell. Pin the tool's dependency environment as well; a binary hash does not pin everything it may load. Configure vendor profiles outside candidate files. `runtime_env` maps allowed environment-variable names to the SHA-256 of their **canonical JSON string value** (`ae_common.hash_json(value)`), not the raw string's hash. This pins the value, not the contents of a file referenced by that value. Credentials use `auth_env` references instead of literal values. The sanitized process environment does not inherit arbitrary workstation configuration.

Live HTTPS requests refuse redirects and bound response sizes. The runner does not create OIDC trust, tokens, vendor service accounts or warehouse grants: provision these through the institution's existing identity system before choosing `mode: "live"`.

## Prepare the exact release

The engagement must be `handoff_prepared` with current source/catalogue/context and file-integrity evidence. A selected framework/warehouse must agree with the provisioned destination. `bundle` and `dataform` deployment framework labels map to the engagement's native-SQL choice; GitHub can carry the retained modeling framework.

A request selects handoff-relative files in execution order. All prepared package files, including configuration/macros, are bound and copied to the private runner snapshot. SQL routes need rendered native SQL; each SQL artifact is one statement for the initial adapter contract. Artifact roles are `model_sql`, `validation_sql`, `deployment_plan`, `project`/`project_file`, `documentation` and `semantic`. Validation SQL executes a check; the independent validator still must evaluate its actual results.

```json
{
  "schema_version": 1,
  "action": "deploy_development",
  "destination_id": "snowflake-test",
  "release_id": "sales-dev-001",
  "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "artifacts": [
    {"path": "implementation/01_orders.sql", "role": "model_sql"},
    {"path": "validation/orders_check.sql", "role": "validation_sql"}
  ],
  "impact": ["Replace TEST_DB.GOLD.ORDERS using the reviewed SQL."],
  "recovery": ["Use the separately reviewed prior-definition/data-recovery procedure; verify downstream consumers before resuming."]
}
```

The SHA above is illustrative. Establish the real commit-to-artifact relationship before review. Binding a supplied SHA and file hashes alone does not prove that remote jobs execute those bytes. PR publication additionally checks the prepared file set at the remote commit, except its independently reviewed plain-text PR body. Existing remote job definitions, bundle resources, Coalesce environment mappings and deployment state can change independently. The operator/issuer must verify those versions and permissions, protect them during execution, and retain the observed native evidence.

```sh
"$DMA_PY" "$DMA_SKILL/scripts/deployment_workflow.py" plan \
  --run /absolute/engagement --request /absolute/release-request.json \
  --policy /absolute/runner-policy.json --output /absolute/release-plan.json
"$DMA_PY" "$DMA_SKILL/scripts/deployment_workflow.py" approval-request \
  --plan /absolute/release-plan.json --output /absolute/approval-request.json
```

Outputs must be new files. Planning confers no authority. `deploy_development` accepts only `development`, `dev`, `test` or `staging`; `promote` requires live mode and an externally signed `adapter_qualification` in the request. Its bindings cover artifact-manifest hash, target hash and runtime; its claims must confirm verified development deployment and rehearsed recovery.

When the engagement selects a semantic target, add `required_checks` containing all seven mandatory checks listed below plus `semantic`; the planner rejects an omitted semantic check. Include any additional release-specific checks in that same list.

If the reviewer downloaded a request from the exported HTML, add `--review-request /absolute/downloaded-request.json` to `approval-request`. It verifies the request's intent, plan/action hashes, context and target against the concrete plan. Its output is still an unsigned request for the external issuer.

For `publish_pr`, add `publication` with exactly `repository`, `base`, `head`, `title`, `body_artifact`, matching the trusted publication destination. The body must have category `documentation` in the immutable prepared review and use a `.md` or `.txt` suffix. Request roles cannot relabel implementation as documentation or exempt executable files. Handoff-relative paths must equal repository-root-relative paths for every remotely checked file. The `gh` route checks the existing remote head against `commit_sha`, compares every prepared file at that commit except the PR body (including unselected files, configuration, macros and other documentation), creates a draft PR, then verifies its URL, open state, head SHA and base/head branch names. It does not create a branch, commit, push, merge or prevent later branch changes. Use the customer's reviewed Git release process and branch protection. PR publication is not transformation execution.

## External sign-off, execution and acceptance

The approval request contains `model_signoff_bindings` and `deployment_approval_bindings`. Send these and the concrete review to the institution's issuer. The issuer authenticates the person and scope outside this program; a typed actor name, browser button, unsigned JSON or agent assertion is not approval.

Each returned envelope is `{"payload": {...}, "signature": "<BASE64>"}`. The payload includes `schema_version:1`, `kind:"deployment_attestation"`, `purpose`, `mode`, `issuer`, allowed `actor`, unique `id`, timezone-aware `issued_at`/`expires_at`, `review_reference`, exact `bindings`, and any required `claims`. Sign the payload's canonical JSON bytes: sorted keys, compact separators, ASCII escaping, no NaN. The signature is a Base64-encoded 64-byte Ed25519 signature. There is no toolkit signing command. Model sign-off and deployment approval are distinct purposes even when one institutional issuer is authorized for both.

Live deployment approval additionally requires `claims.preflight` with `status:"passed"`, the exact `target_sha256` and `runtime_version`, `principal_namespace_verified:true`, `artifact_commit_verified:true`, `permissions_verified:true`, the exact bound `lint_report_sha256`, plus an evidence reference and 64-character lowercase SHA-256 in `evidence_reference`/`evidence_sha256`. The issuer must obtain current native evidence independently before signing. Planning and local fixture tests do not supply it; do not fill these fields from configured values alone.

On the provisioned **live** runner, after those signatures are obtained:

```sh
export DMA_RUNNER_POLICY=/absolute/runner-policy.json
"$DMA_PY" "$DMA_SKILL/scripts/deployment_workflow.py" submit \
  --plan /absolute/release-plan.json \
  --model-signoff /absolute/signed-model-review.json \
  --approval /absolute/signed-deployment-approval.json
"$DMA_PY" "$DMA_SKILL/scripts/deployment_workflow.py" status --operation OPERATION_ID
"$DMA_PY" "$DMA_SKILL/scripts/deployment_workflow.py" observe --operation OPERATION_ID
```

Use the returned operation ID. `status` reads durable local state; `observe` reads the native run and can advance the next approved operation after successful completion. Submission is journaled before dispatch. The runner excludes conflicting active releases and prevents a plan from being submitted twice.

Native completion reaches `verification_pending`. A separate validation issuer must examine actual native results, not approve the configured identity or a green process exit. Required checks are `physical_schema`, `grain`, `fanout`, `source_reconciliation`, `metrics`, `access`, `principal_namespace`; `semantic` is also required when selected by the engagement. Every check must be `passed` with `evidence_reference` and `evidence_sha256`. Additional requested checks must also be covered exactly.

The validator integration obtains the exact bindings with `deployment_workflow.execution_bindings(record, plan)`, using `status(policy_path, operation_id)` and `load_plan(plan_path)` from the trusted modules. It returns purpose `deployment_acceptance` and `claims.checks`. An acceptance issuer must differ from the deployment-approval issuer. Submit that envelope:

```sh
"$DMA_PY" "$DMA_SKILL/scripts/deployment_workflow.py" accept \
  --operation OPERATION_ID --attestation /absolute/signed-acceptance.json
```

Only this step produces `deployed_verified` in live mode. In simulation it produces `simulation_verified`. This authenticates the external issuer's evidence-bound statement; it does not make the issuer's investigation automatically correct.

## Unknown outcomes, cancellation and recovery

A timeout, missing run ID, malformed result or ambiguous transport outcome becomes `unknown_remote_state`. Failed/partial/cancelled work may have committed changes. Preserve the journal, native IDs and evidence. Do not delete `active.json`, change signed records, create a new token to replay the same request, or infer “latest run” identity.

```sh
"$DMA_PY" "$DMA_SKILL/scripts/deployment_workflow.py" cancel --operation OPERATION_ID
"$DMA_PY" "$DMA_SKILL/scripts/deployment_workflow.py" observe --operation OPERATION_ID
```

Cancellation is a request; it is not rollback. Some routes lack a durable native cancellation/status interface. MotherDuck's route is a bounded synchronous client execution with an observed database and no durable native job ID.

If an independent reconciler locates the exact missing run, it signs purpose `deployment_reconciliation`, using `recovery_bindings(record, plan)` and `claims.receipt` identifying that adapter operation/native ID. `reconcile --operation OPERATION_ID --attestation FILE` then performs a native status read; it never repeats the original submission. When recovery is needed, execute the separately authorized platform recovery procedure outside this helper. An independent issuer signs purpose `deployment_recovery`, the current recovery bindings, and claims `remote_quiescent:true`, `recovery_verified:true`, `evidence_reference` and `evidence_sha256`. `recover --operation OPERATION_ID --attestation FILE` records `recovered` and releases the conflict lock. It does not run rollback SQL. Recovery bindings include the exact journal head, so another observation requires fresh bindings/signature.

Every transition, including reconciliation, acceptance and recovery, must match the execution's original plan, policy, mode, target, context and required checks before writing the journal. Fresh signatures over an edited or resealed plan cannot change those obligations. Acceptance derives its live/simulation result from the bound execution record. Recovery remains possible after candidate/source drift using the original plan and policy plus fresh independent recovery evidence; it does not require replaying an expired original approval. If policy files were changed, restore the original trusted policy through the runner administrator before recovery. If that trust can no longer safely be restored, use institutional incident recovery outside this coordinator; it has no automatic trust-rotation escape hatch.

## Native route reference

All rows are implemented request/receipt contracts with local fixtures, **not live-provider qualification**. Full synthetic target examples are in the repository's `tests/test_deployment_adapters.py`; `TARGET_FIELDS` in `scripts/deployment_adapters.py` is the strict field registry. Unknown fields/routes are rejected. Positive integer IDs are required where the field name ends in `_id`; auth values are environment-variable names only.

| Adapter | Additional target fields / local tool | Native boundary and official contract |
|---|---|---|
| `github_workflow` | `owner`, `repo`, `workflow_id`, `workflow_ref`, `workflow_sha`; HTTP token | Dispatch an existing protected workflow ref with artifact commit, release ID and target/artifact hashes. Workflow SHA and artifact SHA differ. The workflow must validate inputs and attest what it executed; an acknowledgment without a run ID stays unknown. [GitHub](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event) |
| `dbt_platform` | `base_url`, `account_id`, `project_id`, `environment_id`, `job_id`; HTTP token | Trigger existing job at `git_sha`; verify returned run/target/commit fields. Job settings and managed runtime remain separately controlled. [dbt API specification](https://raw.githubusercontent.com/dbt-labs/dbt-cloud-openapi-spec/master/openapi-v2.yaml) |
| `coalesce` | `base_url`, `profile`, `environment_id`, `job_id`; `coa` | Planning/simulation only; live submission is blocked before mutation. Automatic status/results lack qualified profile-domain binding. Cancellation pins domain/environment using documented flags. Use the reviewed Git/CI handoff for delivery until that continuation is implemented and qualified. [Coalesce CLI](https://docs.coalesce.io/docs/coa/version-733-and-above/coa-commands) |
| `snowflake_sql` | `base_url`, `role`, `compute`; database/schema namespace; HTTP token | SQL API async statement handles, status and cancellation. One statement per artifact; query success is not business acceptance. [Snowflake SQL API](https://docs.snowflake.com/en/developer-guide/sql-api/reference) |
| `databricks_bundle` | `base_url`, `profile`, `bundle_name`, `bundle_target`, `workspace_root`; `databricks` | Deploy pinned bundle files, then verify resource summary. Resource deployment does not run the transformation. [Bundle CLI](https://docs.databricks.com/aws/en/dev-tools/cli/bundle-commands) |
| `databricks_job` | `base_url`, `job_id`; HTTP token | Read the existing job's pinned Git commit, then run with idempotency token and poll the exact run. [Jobs API](https://docs.databricks.com/api/workspace/jobs) |
| `bigquery_sql` | `project`, `location`; dataset namespace; HTTP token | Insert deterministic-ID GoogleSQL jobs and inspect native errors/state; cancellation is separate. [BigQuery Jobs API](https://cloud.google.com/bigquery/docs/reference/rest/v2/jobs) |
| `dataform` | `project`, `location`, `repository`, `service_account`; optional `included_tags`; HTTP token | Compile exact commit, then invoke its exact compilation-result resource. No assumed idempotent create retry. [Dataform invocation API](https://cloud.google.com/dataform/reference/rest/v1/projects.locations.repositories.workflowInvocations) |
| `redshift_sql` | `region`; exactly one of `cluster_identifier`/`workgroup_name`; optional `db_user` or `secret_arn`; `aws` | Data API statement UUIDs and client tokens; serverless identity derives from IAM. Token retention is bounded, not indefinite replay protection. [Redshift Data API](https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html) |
| `clickhouse_sql` | `base_url`; database namespace; `auth_env.password`, username=`identity`; HTTP | Inspect full response and exact query ID; HTTP 200 alone is insufficient. Query-log follow-up covers the connected node only. [ClickHouse HTTP](https://clickhouse.com/docs/interfaces/http) |
| `motherduck_sql` | Database namespace; `auth_env:{"token":"motherduck_token"}`; `duckdb` | Connect explicitly to `md:DATABASE`; observe current database in the same client connection. No durable remote job receipt is claimed. [MotherDuck connection](https://motherduck.com/docs/getting-started/connect-query-from-python/installation/) |

## Static quality prerequisite

A reviewable plan may be prepared while lint remains pending. Live submission requires complete current lint evidence supplied through the request's `quality.report_path` and `quality.manifest_path`; follow [linting.md](linting.md). The planner and every subsequent execution step verify its input, target, context and coverage hashes. External preflight signs the exact report hash and must verify its provenance in the trusted runtime. Static integrity alone is not an authenticated run or native acceptance.

## Review package and local exercise

Keep the approved handoff frozen. The deployment review exporter creates a separate presentation from copied approved deliverables and sanitized plan/receipt evidence; it registers the evidence files so HTML details match the selected ZIP contents. Do not copy the runner policy, signed journals, credentials or private keys into the package. The offline page's action saves a request only. See [review-surface contracts](review-surface.md) for audience/category selection and integrity verification.

```sh
"$DMA_PY" "$DMA_SKILL/scripts/deployment_review.py" \
  --plan /absolute/release-plan.json --output /absolute/new-review-directory
```

This uses `DMA_RUNNER_POLICY`, requires an engineering handoff, and creates `START_HERE.html`, `deployment-review.zip`, `review.json` and an `artifacts/` copy. To include an execution result, add `--receipt /absolute/receipt-locator.json`, containing `{"operation_id":"<RECORDED_OPERATION_ID>"}`. The exporter authenticates the current local journal instead of trusting supplied status claims. It does not poll, submit, approve or deploy. The offline receipt remains a reported snapshot; refresh the export after later observations. Choose a new output directory outside protected source, candidate and runner paths. Export rejects known internal paths in selected content rather than silently rewriting approved bytes.

The repository's offline checks run with:

```sh
"$DMA_PY" -m unittest discover -s tests -p 'test_deployment*.py' -v
```

Run from the repository root. Simulation uses fixture transports injected through the Python API; live transport is refused in simulation, and injected transports are refused in live mode. Fixture issuers and synthetic IDs establish local control-flow behavior only. Native syntax acceptance, actual authentication, remote environment identity, performance, data correctness and recovery remain separate target qualification work.
