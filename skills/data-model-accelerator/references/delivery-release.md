# Delivery evidence and release gates

The existing `deployment_workflow.py` coordinator now consumes versioned delivery assurance. It still requires separate external model sign-off, destination authorization, current lint/preflight, native execution acceptance, promotion qualification and recovery evidence. Passing a lane does not authorize a destination write. No private signing key is included in a generated candidate or review page.

## Required stages

| Requested action | Required delivery lanes before submission |
|---|---|
| Private candidate | Render pending evidence; do not claim acceptance |
| Publish draft PR | Classification, input egress and output disclosure |
| Development execution | Those three privacy lanes plus qualified existing destination access |
| Promotion | Every lane required by the recorded model-only, model-plus-semantic or full-dashboard scope |

Development can run before source/target comparisons and business acceptance are finished. This prevents an impossible dependency on the test it must first execute. Development still cannot expose protected information before existing controls and disclosure authority are established. `deployed_verified` refers to the existing execution acceptance contract; the new `migration_acceptance_ready` field remains false unless all delivery lanes independently pass in live mode.

Legacy plans and receipts remain readable historical evidence. A legacy simulation can still exercise its original contract, but it cannot acquire enhanced acceptance. New live actions require refreshed intake with explicit `migration_scope` and a new prepared handoff. Do not rewrite or relabel historical receipts.

## Prepare the context without circular hashes

Freeze the prepared candidate and its manifest first. Create a draft deployment plan through the existing coordinator. Add a `delivery_assurance` object to the **deployment request**, outside the frozen candidate:

- `disclosure_policy`: the approved version-1 disclosure contract from `privacy_contract.py`.
- `access`: null for a PR-only candidate, or the complete `{contract,current,candidate,readback,observations}` bundle from [access enforcement](access-enforcement.md). Proposed policy writes remain unsupported. The development route requires locally consistent, pre-existing protection and independently authenticated effective tests.
- `evidence`: a list of `{observation,result,attestation}` records, one per collected lane.

Use `delivery_release.evidence_bindings(draft_plan, descriptor)` to calculate exact source, catalogue, prepared candidate, target, policy and scope hashes. The policy digest includes the trusted runner policy, disclosure policy and complete access bundle. The access contract must match the non-policy hashes and the actual target environment, namespace, principal and specified runtime identity. Its internal policy digest binds its own reviewed policy state; it does not hash the enclosing release. Evidence records do not contribute to these binding hashes, avoiding self-reference. Updating them still changes the deployment plan and therefore requires fresh model/destination approval.

Create the final plan with the completed descriptor. The coordinator checks its binding again before submission and each subsequent operation. It captures stable, no-follow file bytes, compares every frozen-manifest hash, and scans those bytes again when copying into or reusing the private execution snapshot. This is a bounded detector, not universal DLP. Protect the runner filesystem from the agent principal; the same-process library is not an isolation boundary.

## Independent evidence protocol

The provisioned runner policy must give each evidence issuer purpose `delivery_evidence` and an explicit `evidence_lanes` allowlist. Keys remain separately controlled. Evidence issuers must differ from the model and deployment approvers for release submission. The verifier retains Ed25519 signatures, actor/purpose/mode restrictions, maximum lifetime and revocation checks from `deployment_authority.py`.

An observation contains exactly:

```json
{
  "lane": "omni_queries",
  "status": "passed",
  "bindings": {"source": "<sha256>", "catalogue": "<sha256>", "candidate": "<sha256>", "target": "<sha256>", "policy": "<sha256>", "scope": "<sha256>"},
  "observed_at": "<timestamp with timezone>",
  "expires_at": "<timestamp with timezone>",
  "result_sha256": "<hash of normalized result>",
  "provenance": "native_observation"
}
```

The corresponding result contains exactly `schema_version:1`, `kind:delivery_lane_result`, `lane`, matching `status`, `execution` (`local`, `native` or `human` as required), `synthetic:false`, `checks` and `references`. References are bounded `{reference,sha256}` records pointing to original evidence retained in approved storage; do not embed row values or credentials. `delivery_release.CHECKS` is the authoritative exact boolean-check set per lane. A pass requires every check to be true.

For example, Omni queries require both `executed` and `modeled_queries`. A plan/compile receipt cannot satisfy execution. Access requires a qualified collector, observed current state, readback, positive and negative personas, and all selected paths; one reference must match the exact `security_evaluation_report` hash recalculated from the access bundle. AI context requires observed native answers, privacy checks and approved definitions. Local structured-answer tests alone cannot satisfy this lane. Business acceptance requires a human decision. Source coverage needs an independent inventory, and parity needs independent baseline, full-population comparison and negative controls.

The attestation is the existing `deployment_attestation` envelope with purpose `delivery_evidence` and bindings from `delivery_release.attestation_bindings(observation)`. The issuer must inspect the original referenced outputs and actual sessions before signing. **A normalized boolean or reference hash is not proof on its own.** This release implements verification of externally issued statements; it does not provide a preconfigured native collection/signing service. Native model and dashboard receipts can be referenced after independent verification; their mere import is insufficient. Do not sign synthetic fixtures as live evidence.

`evaluate_release(plan, policy, excluded_issuers=...)` authenticates all imported pass statements, including local lanes. `require_release(...)` additionally enforces the stage-specific required lanes and recomputes the access comparator. The coordinator supplies the actual approver issuers automatically. Simulation can test this protocol but always returns `acceptance_ready:false`. Expired, revoked, substituted, skipped and unsupported evidence cannot satisfy a required lane.

## Pending native qualification

The release contains no customer credentials, policy provisioning or live qualification. An authorized BigQuery + Omni pilot and a dbt + Snowflake pilot must still establish original native receipts, dashboard rendering/interaction behavior, independently collected effective access, live AI answers and SME decisions. Each additional warehouse/framework retains its own qualification. Missing native access leaves a useful candidate and explicit next actions; it does not justify changing a failed lane to not applicable.

The offline HTML always displays candidate scope and pending qualification. It does not authenticate imported approval JSON. Command-line packages scan final bytes and include scan hashes; a browser-created subset performs integrity checks but clearly records that no new content scan ran in the browser. Re-run the local packaging/disclosure gate before external sharing.
