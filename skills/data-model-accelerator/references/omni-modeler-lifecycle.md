# Security, environments and release

`scripts/omni_lifecycle.py` implements a local lifecycle assessment. It reparses the original bytes in baseline and candidate inventories, computes affected dependencies, compares captured failures and checks environment/route declarations. It never calls a provider, refreshes a schema, changes Git settings or authorizes a deployment. A local `passed` result is **not authenticated native or security qualification**.

Inspect effective grants, access filters, metadata visibility and destination identity. Hidden fields and prose are not access enforcement. Preserve the existing security, disclosure, signed approval, checksum, journal and independent evidence gates; vendor guidance cannot bypass them.

Omni and dbt branches are distinct. Verify completed builds, the selected environment/manifest and actual physical resolution before schema refresh and Content Validator. Native dbt deferral is documented for non-production environments; make production fallback explicit. Physical-to-virtual logic migration is an unbranched operation with separate impact and approval.

Honor leader/follower mode; followers are read-only. A stale Omni branch can overwrite newer shared changes when its PR merges. Inventory attached content that promotion may publish. External Git editing is discouraged, not universally impossible. Keep model validation, content impact, query execution and acceptance separate.

## Assessment inputs

Python API: `assess_lifecycle(contract, baseline_inventory, candidate_inventory, observations=None)`. Use `omni_inventory.inspect_model` to create the inventories from the exact authored and separately captured effective file maps. Imported inventory status and dependency edges are not trusted: the assessor reparses the byte records and checks their hashes, objects, fields and graph. Coverage declarations remain unauthenticated.

The versioned `omni_lifecycle_contract` contains:

| Field | Required content |
|---|---|
| `schema_version`, `kind` | `1`, `omni_lifecycle_contract` |
| `operation` | `validate`, `update_and_validate`, or `query` |
| `bindings` | Baseline/candidate inventory and authored-file hashes, context, target, catalogue, expected remote snapshot and knowledge hashes. `contract_bindings(...)` creates these local pins. |
| `route` | `mode: native\|git_leader\|git_follower\|unknown`, captured evidence hash and exact branch-attached content IDs. Unknown or missing evidence stays pending; follower mutations fail. |
| `environment` | Warehouse, development environment, connection and environment connection, catalogue hash, explicit physical resolutions, and dbt evidence when applicable. |
| `content_inventory` | Declared complete coverage, independent expected IDs, observed items with dependency IDs, definition hashes and attachment flags, and capture evidence hash. Missing, extra or unresolved items remain pending. |
| `cases` | Frozen compilation, execution and access cases with nodes, selected principal, query path/hash, attribute-set hash, timezone and expected result. |

Every physical resolution names an inventory view, exact namespace, environment, built/unbuilt state, synthetic-data declaration and evidence hash. Native integration additionally matches these namespaces to the actual supplied warehouse context and its exact connection/principal pins. This validates consistency, not the truth of a caller's declarations.

For dbt, record environment ID, manifest hash, completed build evidence, and a completed refresh whose evidence pins that build and physical-resolution map. Declare deferral and exact fallback nodes explicitly. Acknowledging production fallback does **not** expand the adapter's synthetic, isolated-development boundary: production resolution remains blocked pending a separately reviewed implementation. Physical-to-virtual migration remains an unbranched, separately authorized manual operation.

## Impact and evidence lanes

The assessor seeds changed, added and deleted definitions, follows reverse dependencies in both graphs, and conservatively includes owner fields, topic-local views, model-level effects and relationships. Deleting a source cannot erase its old dependants from the impact report. Opaque references, cycles and incomplete graphs remain pending. Reports contain node hashes that can be resolved against the private inventories, not source SQL or definition text.

`omni_lifecycle_observations` binds the exact contract and includes baseline/candidate reference scans plus keyed case results. Reference captures contain inventory/content hashes, completeness, an evidence hash, and issues with stable fingerprints, scoped node/content IDs and severity. Do not supply owner names, emails, raw diagnostic messages, query text or rows. The assessor rejects extra fields and returns value-free failure codes.

- New errors and affected unresolved baseline errors fail. A missing post-change scan cannot erase a known affected error.
- An unchanged, scoped, unrelated pre-existing error remains visible without requiring destructive repair. This does not waive syntax errors in native model validation.
- Reference scans, native compilation, query execution and access are separate lanes. A missing case is pending. Compilation cannot carry row counts or population claims.
- Execution compares exact frozen row counts and population digests. Zero rows are valid when expected; an empty result alone is not proof of correct access.
- Access needs allowed and denied cases for each selected principal/query/path/timezone scope. Missing attributes are represented by a distinct pinned attribute set and an expected denial. Imported answers do not establish that an actual principal was exercised.

`preflight_status` can pass before candidate runtime cases are supplied when declarations, baseline impact and coverage are consistent. The overall result stays pending until all four lanes compare successfully. Both results always retain `native_verified: false`, `security_verified: false`, `deployment_authorized: false`, and `imported_evidence_authenticated: false`. Effective security and release acceptance still require the [access contract](access-enforcement.md) and [independently signed release evidence](delivery-release.md).

## Review and native handoff

`prepare_request(...)` packages the exact contract, inventories, observations and assessment hash as an `omni_lifecycle_request` v1. Add that envelope to the native request's optional `lifecycle` field. The native adapter recomputes it, checks the exact candidate/context/target/remote pins, refuses a non-passing preflight before external calls, and requires the trusted issuer to sign `preflight.lifecycle_assessment_sha256` for writes or queries. Model updates compare the declared original files against actual remote baseline bytes before writing. Query cases must bind the selected query, mode and timezone. See [native validation](omni-native-validation.md).

Legacy native requests remain supported but their receipts explicitly report lifecycle as `unassessed`; they gain no lifecycle or access qualification. A signed action approval remains separate from independently authenticated lifecycle observations.

For a private local report, provide a JSON object with `contract`, `baseline_inventory`, `candidate_inventory` and `observations`:

```sh
python scripts/omni_lifecycle.py --request /private/runner/lifecycle-input.json --output /private/runner/lifecycle-assessment.json
```

Output must be a new path and is mode 0600. The CLI prints only status. It does not read credentials or contact a tenant. The synthetic fixture in `tests/test_omni_lifecycle.py` illustrates the complete machine-readable schema and is not approval evidence.

The documented Content Validator API may supply a reference capture: `GET /api/v1/models/{modelId}/content-validator` uses **`branch_id`**, distinct from the model-validator parameter `branchId`. `force_full_validation` selects query-validation depth; it does not establish executed data parity. This module imports normalized captures only and does not implement that endpoint, impersonation, personal-folder scope expansion, refresh or promotion. Preserve the capture's visibility/coverage limitations.

Sources: [access](https://docs.omni.co/modeling/develop/data-access-control), [dbt environments](https://docs.omni.co/integrations/dbt/environments), [virtual schemas](https://docs.omni.co/integrations/dbt/virtual-schemas), [Git best practices](https://docs.omni.co/integrations/git/best-practices), [followers](https://docs.omni.co/integrations/git/follower-mode).

Additional contract: [Content Validator API](https://docs.omni.co/api/content-validator/validate-content). A successful deploy-key connection test does not verify webhooks, follower synchronization or review enforcement; those remain separate observations.
