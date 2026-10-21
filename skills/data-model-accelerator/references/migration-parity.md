# Migration parity workflow

Compare an independently frozen source result with the proposed warehouse and Omni result. A matching total alone is insufficient: retain row grain, schema, nulls, ordering, scenarios, context, query identities and observed invariants. A local `pass` never grants native acceptance, security approval or deployment authority.

## What is implemented

- `scripts/migration_validation.py`: plan preparation, source/warehouse/Omni export import, explicit baseline freeze, row-free crosswalk/scorecard, and an independent CLI.
- `scripts/migration_collectors.py`: actual bounded Omni query collection through the existing execution authority and an actual BigQuery `jobs.query` HTTPS adapter. Both have mocked contract/signature/HTTP tests. Neither has been qualified against live credentials in this change.
- `scripts/migration_parity.py`: unchanged v1 comparison API and schema. Old engagements and direct comparator callers remain compatible.

Periscope/Sisense CDT result CSVs work without an API. Repository SQL, Python and R files are evidence of definitions, **not evidence of execution**. Python/R runtime, package environment, inherited/global filters, security and rendered chart interaction gaps must remain explicit until independently observed. No Periscope source executor is implemented.

## Callable contracts

`prepare(request)` accepts:

```json
{
  "schema_version": 1,
  "plan": {"...": "existing migration_parity_plan v1"},
  "crosswalk": [{
    "subject_kind": "tile", "subject_id": "orders",
    "dashboard_id": "operations", "dashboard_label": "Operations",
    "source_label": "Completed orders",
    "model_ids": ["fact_orders"], "topic_ids": ["orders"],
    "status": "mapped", "gaps": []
  }]
}
```

The example `plan` placeholder must be replaced by the existing full plan: migration scope, six bindings, selected data/text/filter inventory, required scenarios, case schema/grain/order/null/tolerance/invariant/context definitions, query hashes and review. A draft may use `review: {"status": "pending"}` and a zero baseline hash. Structural validation of a draft does not approve it. Every selected chart/text tile/filter needs one crosswalk row; unmapped and unsupported rows remain visible. `status` accepts `mapped`, `pending`, `unsupported`. `gaps` contains `{code, status: pending|unsupported, reference}` records.

`import_capture(workflow, request)` accepts a private import envelope:

```json
{
  "schema_version": 1, "origin": "source",
  "provenance": "source_observed", "independent_of_candidate": true,
  "reference": "controlled-source-export",
  "cases": [{
    "case_id": "orders-baseline", "format": "periscope_csv",
    "payload": "day,revenue\n2026-10-01,100\n",
    "null_token": "\\N",
    "query": {"language": "sql", "text": "exact observed query", "parameters": {}},
    "context": {
      "snapshot_sha256": "64 lowercase hex characters",
      "timezone": "America/Chicago",
      "parameters_sha256": "64 lowercase hex characters",
      "persona_sha256": "64 lowercase hex characters",
      "query_sha256": "hash_json of the exact query value"
    },
    "columns": {"day": "date", "revenue": "number"},
    "metrics": {"duplicate_keys": 0, "orphan_keys": 0, "tenant_violations": 0,
                "join_input_rows": 1, "join_output_rows": 1},
    "metrics_reference": "independently-observed-invariant-check",
    "truncated": false, "reference": "source-export-observation",
    "captured_at": "2026-10-20T12:00:00+00:00", "gaps": []
  }]
}
```

Replace placeholders with actual hashes/observations. Do not copy expected invariants into `metrics`: record independently measured values and their reference. Differences become failures. Context uses the same snapshot/timezone/parameter/persona hashes across lanes; each lane's `query_sha256` is `ae_common.hash_json(query)`, frozen in the plan. Exact query text or request objects remain private. The capture preserves normalized rows, query, context, schema, export payload hash, timestamp, source references, and gaps. It does not authenticate operator assertions.

Supported data formats are `json_rows`, `periscope_csv`, `bigquery_query_response`, and `omni_json`. CSV has an explicit null token so an empty string is not silently converted to null. Optional `column_map` is a bijection from exported column/Omni field name to canonical column; mappings are explicit and retained. Numeric text is imported only when its precision survives the comparator's existing JSON-number representation; arbitrary-precision values that would round are rejected rather than silently changed. Nested/repeated BigQuery fields, non-finite values, incomplete pages and more than 1,000 rows are unsupported. Interaction cases use `format: interaction`, `payload`, context and provenance, without data-specific fields; a data export is not a UI interaction observation.

For `omni_json`, `query` is the full API body, `resultType: json`, `formatResults: false`, and `request_limit` equals `query.query.limit`. Exact requested fields must match the declared map. Reaching that limit is conservatively unsupported because the JSON array alone cannot establish completeness. BigQuery requires completed, error-free, single-page results with `totalRows` matching the rows and a matching flat schema. Known or ambiguous truncation cannot pass even if all three captures agree.

`freeze(workflow, baseline, review_reference)` binds the independent complete source capture and an explicitly supplied host review reference. It does not authenticate a human or generate approval. It also records `baseline_document_sha256`, binding the entire private source document, including runtime/filter gaps and provenance. Changing or clearing those after review fails. An approved comparator plan imported without this full document binding remains pending until explicitly frozen. Do this before comparing target results. `evaluate(workflow, baseline=None, warehouse=None, omni=None, current_bindings=None)` returns only metadata, status, issue codes, counts and hashes. Pass requires a reviewed/frozen independent baseline, complete required observations, a mapped crosswalk, no retained gaps, and current bindings equal to the frozen bindings. Changed bindings fail with `stale: true`; omitted current bindings stay pending. A `model_only` plan requires no Omni result. UI inventory with no selected comparison case remains visible as `required: false`; its unassessed status does not block the selected model scope. Counts include all visible crosswalk rows, while overall status considers required rows. `render_markdown(report)` produces a dashboard/chart → model/topic scorecard with `pass`, `fail`, `pending`, `unsupported` and named gaps.

## Native collection and authority

### Omni

`collect_omni(request, policy_path=..., candidate_root=..., approval=..., transport=None)` accepts the existing `omni_native_request` restricted to `operation: query`, `query_mode: execute`. `omni_body(request)` returns the exact body to hash into the parity plan. No existing native API was changed.

The collector reuses the native runner's policy/destination validation, externally signed exact-action approval, synthetic development preflight, effective timezone, permissions and principal checks, candidate/snapshot verification, exclusive journal, one submission and at most two polls. It checks the snapshots again after the query. The private response tap retains only a successful JSON response; it cannot promote an injected transport from simulation. Existing 1,000-row, 8 MiB, HTTPS and timeout limits remain. Arrow/NDJSON row decoding is unsupported here; completion without JSON capture remains unsupported. Completed/unknown submissions are not automatically resubmitted.

### BigQuery

`collect_bigquery(request, policy_path=..., candidate_root=..., approval=..., transport=None)` accepts exactly:

```json
{
  "schema_version": 1, "kind": "migration_bigquery_request",
  "run_id": "orders-baseline", "destination_id": "dev",
  "target": {"project_id": "fixture-project", "location": "US",
             "principal_id": "explicit-reviewed-principal", "environment": "development"},
  "sql": "SELECT SUM(amount) AS total FROM `fixture-project.raw.orders`",
  "allowed_tables": ["fixture-project.raw.orders"],
  "maximum_bytes_billed": 1000000, "max_rows": 1000, "timeout_ms": 10000
}
```

`bigquery_body(request)` returns the exact official REST body; hash that value into the warehouse case query. A trusted issuer must sign `bigquery_bindings(request, policy_sha256)` using the existing deployment authority's `deployment_approval` purpose and `deploy_development` action. The provisioned destination must equal the target. Signed preflight must assert `principal_namespace_verified`, `read_only_query`, `synthetic_data_only`, `isolated_destination`, `cost_limit_verified`, plus the exact `target_sha256`. This does not authorize production/customer-data collection.

Live mode requires `BIGQUERY_ACCESS_TOKEN`; the runner policy must pin its SHA-256 in `runtime_env.BIGQUERY_ACCESS_TOKEN`, binding the separately verified credential to the reviewed policy. Principal identity is supplied by the trusted preflight, not independently established by `jobs.query`. No token is written to artifacts. No new credential discovery or refresh mechanism exists.

The collector parses one SELECT with SQLGlot, requires explicit table allowlists, and rejects writes/scripts, remote/UDF functions, unknown functions, unqualified tables and unsupported syntax before any request. It sends one HTTPS `jobs.query` call to Google's fixed endpoint with cache disabled, GoogleSQL enabled, maximum billed bytes (up to 1 GB), at most 1,000 rows and at most 30 seconds for both waiting and requested job timeout. These are request bounds, not a promise that Google cancels a job immediately at the timeout. No pagination, retry or automatic resubmission is performed. An exclusive private intent file blocks duplicate run IDs; interrupted/unknown jobs require separate reconciliation. Incomplete or paginated results remain pending/unsupported.

Both collectors return a **private** collection document with `query`, `payload`, response hash and row count. `public_summary(result)` excludes rows, queries and provider messages. Collected data still goes through `import_capture`; collection does not invent comparison context or invariant metrics. `native_verified`, `evidence_authenticated` and `acceptance_ready` remain false. Mocked tests prove contract behavior; live acceptance is unverified.

## CLI and storage

```sh
python scripts/migration_validation.py plan --request plan-request.json --output private-workflow.json
python scripts/migration_validation.py capture --workflow private-workflow.json --request source-import.json --output private-source.json
python scripts/migration_validation.py freeze --workflow private-workflow.json --baseline private-source.json --review-reference explicit-review --output private-frozen.json
python scripts/migration_collectors.py omni --request native-query.json --policy runner-policy.json --candidate-root candidate --approval signed-approval.json --output private-omni-result.json
python scripts/migration_collectors.py bigquery --request bq-query.json --policy runner-policy.json --candidate-root candidate --approval signed-approval.json --output private-bq-result.json
python scripts/migration_validation.py evaluate --workflow private-frozen.json --baseline private-source.json --warehouse private-warehouse.json --omni private-omni.json --bindings current-bindings.json --output private-scorecard.json
```

Run from the skill directory. Complete warehouse/Omni imports using the same `capture` command after collection. All CLI output documents are exclusive, mode `0600`; existing paths and symlinks are rejected. Collector output must be outside the candidate root. Ordinary stdout reports only safe status. **Never place captures or collection payloads in ordinary engagement state, public delivery manifests, HTML or logs.** The host should store the private documents in controlled sidecars, retain their hashes, and register only the row-free `evaluate` report/public collection summary. The scorecard includes intended crosswalk labels; those labels still need normal disclosure review.

## Official contracts checked 2026-10-20

- [Omni Run query](https://docs.omni.co/api/queries/run-query): JSON result export, request-body branch/environment/timezone, query fields and timeout behavior. This implementation uses `resultType: json`; it does not implement Arrow streaming or result-offset reads.
- [BigQuery jobs.query](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/jobs/query): standard SQL, billed-byte cap, row/page limits, completion state, schema and result rows. Waiting timeout and job timeout have different meanings; the latter is an attempted stop.

No live credentials, customer execution, rendered dashboard verification, source Python/R execution or security/AI acceptance were established by this implementation.

## Existing comparator compatibility

The original CLI remains available unchanged for already normalized, independently frozen captures:

```sh
python scripts/migration_parity.py --plan reviewed-plan.json --baseline frozen-source-observations.json --warehouse warehouse-observations.json --omni modeled-omni-observations.json --output new-private-parity-report.json
```

Its v1 plan requires every selected data tile and each declared scenario, including `baseline`. Full-dashboard scope also requires interaction evidence for every data/text tile and filter. Data cases retain `columns`, `grain`, `ordered`, `allow_null_grain`, `truncated`, predeclared `tolerances`, and `expected_metrics`. Empty grain permits a single aggregate row. Required metrics are `duplicate_keys`, `orphan_keys`, `tenant_violations`, `join_input_rows`, and `join_output_rows`; duplicates and tenant violations must be zero. `review.plan_sha256` hashes the plan with `review` omitted.

Preserve observed filter intersections, inclusion/exclusion of today, daylight-saving boundaries, NULL versus zero, pivots, sorting and intentional row limits. The new complete-result capture route rejects ambiguous truncation; it must not silently widen a date filter or remove an intentional source limit to get a pass. Proposed business corrections need their own reviewed baseline; performance changes need separate benchmarks and parity evidence. Query equality cannot replace observed rendered layout, formatting and filter interactions.

Keep raw captures within the reviewed private retention boundary. Attach permitted summaries and separately authenticated exact-version execution/observer evidence to delivery. See [AI-context validation](omni-ai-context.md) and [sensitive input handling](sensitive-data.md) for distinct qualification requirements.
