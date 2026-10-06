# Isolated Omni dashboard draft delivery

`scripts/omni_dashboard_native.py` writes a reviewed dashboard build to a **new branch draft on an existing development document**. It never publishes, creates a new published document, merges a branch, clears an existing draft, deletes content, changes access grants, or imports a Looker export directly.

The offline build is a complete work specification; a successful draft receipt is evidence of exact persisted content, not rendered behavior, valid results, customer acceptance, or protected-data qualification. Compilation/execution, filter interactions, visual checks, access tests and SME approval remain separate lanes.

## Selected official route

The adapter uses the documented [create draft and patch document](https://docs.omni.co/api/documents-v2/create-draft-and-patch-document) route: `PATCH /api/v2/documents/{documentId}/draft`, with an explicit reviewed `branchId`. This creates a draft without publishing. It reads the [published document](https://docs.omni.co/api/documents-v2/get-document-state), [active draft inventory](https://docs.omni.co/api/documents/list-document-drafts), [exact new draft](https://docs.omni.co/api/documents-v2/get-draft-state), and the complete [document access list](https://docs.omni.co/api/document-permissions/list-all-users-and-groups-with-document-access).

Do not substitute `POST /api/v2/documents`: that route [creates and publishes immediately](https://docs.omni.co/api/documents-v2/create-document), including first publication outside the organization's PR-required edit policy. Provisioning a new document remains a separately authorized manual action. The [import dashboard API](https://docs.omni.co/api/content-migration/import-dashboard) is **Beta**, uses an Omni export payload, and has no qualified draft-only path here. It is not called by this adapter.

## Request and authorization

Use `schema_version: 1`, `kind: omni_dashboard_native_request` with these exact fields:

| Field | Requirement |
|---|---|
| `run_id`, `destination_id` | Safe runner identity and externally provisioned destination |
| `target` | Same seven development identity fields as the native model adapter: instance URL, model/branch/connection/environment-connection/principal IDs and `environment: development` |
| `document_id` | Existing published document identifier |
| `build_spec` | Exact `omni_dashboard_build` returned by the offline builder; `verify_build` must reconstruct it, and its status must be complete |
| `model_files`, `model_context` | Full static-passing candidate and warehouse context; their hashes bind the build and approval |
| `expected_model` | Native model adapter's five snapshot hashes |
| `expected_document_sha256`, `expected_drafts_sha256` | Exact read-only bootstrap state |
| `expected_access_sha256` | Digest of all observed direct/inherited access grants across complete pagination |

The trusted `deployment_runner_policy` lives outside the candidate. Its selected destination is `{...target, "document_id": "existing-identifier"}`. The signed `deployment_approval` binds the full request, build, model candidate, context, document, target and policy. Signed preflight must contain the native model adapter's namespace/permission/existing-destination/synthetic/isolation/exclusive-branch assertions, plus `document_id`, `document_exclusive: true`, and `audience_sha256` equal to the observed access-list digest. Access-policy/evidence hashes and an evidence reference remain required. AccessBoost is unsupported for this initial isolated route. No authorization is inferred from a build's locally declared approval.

The entire request passes the shared disclosure scan before network calls. Live mode requires `OMNI_API_TOKEN` from the trusted environment. Missing credentials remain pending. TLS verification, no redirects, canonical Omni instance hosts and private external output follow the native model adapter. A supplied transport always produces simulation evidence and cannot pass a native acceptance lane.

```sh
python scripts/omni_dashboard_native.py inspect --request /private/runner/document-target.json --policy /private/runner/policy.json --candidate-root /work/candidate --output /private/runner/document-snapshot.json
python scripts/omni_dashboard_native.py bindings --request /private/runner/draft-request.json --policy /private/runner/policy.json --candidate-root /work/candidate --output /private/runner/draft-bindings.json
python scripts/omni_dashboard_native.py run --request /private/runner/draft-request.json --policy /private/runner/policy.json --candidate-root /work/candidate --approval /private/runner/draft-approval.json --output /private/runner/draft-receipt.json
```

The inspect request contains `target`, `document_id` and `destination_id`. Its private result supplies snapshot hashes and document state to prepare the reviewed request; it is not write authority. Every output path must be new and outside the candidate. Files use mode 0600 and runner state uses a private 0700 directory.

## Preservation and recovery

Before writing, the adapter verifies the principal, model lineage, connections, full model YAML and document state. It fetches every access page, checks the denominator, and binds actual grants to the signed audience. The source builder must account for all requested tiles, text, filters, behavior and layout. Target query topics, fields, inherited definitions and timeframes must resolve against the exact model. Unsupported query calculations/aliases stop for review; this is a reference check, not native compilation.

The reviewed payload must fully account for existing document tile/control keys. A blank seed tile at key `1` can be replaced by mapped content at key `1`; unaccounted old keys cannot silently survive the API's shallow merge. No deletion is synthesized. An existing draft on the target branch stops the operation. Other drafts are preserved and must retain their exact original hashes.

A durable journal is keyed by target document and branch, so changing the run ID does not create a second attempt after an unknown outcome. The journal stores IDs, hashes and operation state, excluding raw provider identities, document text, row values and SQL. It records intent before PATCH. On timeout, interruption or an ambiguous response, another invocation performs read-only reconciliation: one added draft must match the expected branch, parent, workbook, full desired content and exact source-mapped coverage. No observed added draft remains pending; multiple or mismatched drafts block. The create request is never automatically retried.

Readback is strict: only server-owned workbook/draft anchors and `model_extension_id` are excluded from content comparison. Unexpected server normalization remains an explicit qualification failure. Published document, access grants, base/schema/model identity and unrelated drafts must remain unchanged. The API has no documented draft compare-and-swap precondition; signed exclusive document/branch ownership and before/after reads narrow races but do not create an atomic transaction.

Receipts distinguish `remote_write_state` from confirmed `draft_created`, and retain a known draft ID even if later readback fails. They always report `published: false`, `dashboard_tested: false`, and `native_qualification: pending`. `verify_receipt` is consistency-only (`authenticated: false`); externally authenticated observation and final acceptance are separate.

Recovery leaves the published document untouched. Review the exact retained draft and its journal. Discarding or archiving the draft requires separate authorization; there is no automatic destructive rollback. Further editing of existing drafts, new-document creation, publication, Beta import, classic-layout upgrades, external assets and apps remain unsupported/manual until their own contracts and acceptance tests are qualified.
