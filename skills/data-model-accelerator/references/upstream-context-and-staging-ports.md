# Upstream context and staging-port decisions

Readable handoffs automatically project registered source context into
`03_Design_Documents/Upstream/`: one top-down source diagram per reviewed model,
an index, and a complete source graph. `05_Mappings/SOURCE_LINEAGE.csv` retains
known objects, dependencies and gaps; `STAGING_PORT_REGISTER.csv` records scoped
reuse/port decisions. Classic layouts retain the equivalent files under `01_Model`.
These source companions never add entities to the approved target design.

Keep **source context** separate from **target generation scope**. A scoped gold
model may require legacy staging, raw sources, macros and project configuration
to understand its behavior. Including that evidence does not select another
domain, create a target entity, authorize a port or grant a source write.

## Retain extraction once, derive context automatically

`upstream_context.register(state, request, run_dir=None)` accepts:

```text
schema_version: 1
extracts: [{id, root_id, result}]
bindings?: [{entity_id, root_id, native_ids: [exact native IDs]}]
links?: [{source: {root_id, native_id}, target: {root_id, native_id},
          evidence_refs: [{reference, sha256}]}]
```

`result` is an existing `source_adapter_result`, or an existing specialist result
containing `source_adapter_contract`. Do not scan or reparse the repository to
make this register. Root IDs must already exist in `source_roots`. Extraction IDs
are stable: updates may replace a partition's current evidence but cannot reassign
it to another root or adapter. Omitted partitions remain registered; conflicting
hashes between partitions require replacing the stale partition explicitly.

The guided wrapper persists these records with normal state refresh:

```sh
python scripts/guided_workflow.py record-upstream-context --run /local/run --document context.json
python scripts/guided_workflow.py upstream-context --run /local/run --document selection.json
python scripts/guided_workflow.py upstream-context-packet --run /local/run --document selection.json
```

`selection.json` contains `{"entity_ids": ["chosen_entity"]}` or
`{"domain_id": "chosen_domain"}`. When both are supplied, entity IDs must belong
to that domain. Private views and packets stay in engagement state.

The register keeps normalized object IDs, native IDs, edges, file hashes and gap
codes. It does not retain SQL expressions or raw manifest metadata. Object IDs
include their root and adapter identity. Similar names across repositories never
join automatically. Cross-root edges require exact endpoint IDs and pinned
evidence; their relationship remains a host declaration.

`derive(state, selected=None, domain_id=None)` automatically follows supplied
resolved edges upstream from selected target entities' source paths or exact
native bindings. A whole manifest path is ambiguous; supply native bindings for
the selected resources. Compatible authored-byte manifest bindings connect model
SQL to its manifest graph. Unbound literal refs, dynamic references, missing
objects, cycles and unsupported extraction stay visible. Configuration is
supporting context; it never becomes a generated model.

The private result contains `generation_entity_ids` (the unchanged selected IDs),
`seed_object_ids`, `nodes`, `edges`, `files`, `gaps` and `context_sha256`.
`packet(...)` takes the same selectors and `max_bytes` (default 32768, maximum
65536), hashes only those exact files and rejects stale/oversized evidence. Split
large contexts into coherent entity slices; do not truncate their lineage.
Packet metadata contains no source text. Use the existing source-disclosure and
excerpt tooling before providing original contents to a worker.

Domain summaries call the derived helper automatically. Their public projection
contains counts and gap codes, not source paths. `domain_workflow.source_context`
provides the private graph. The architect may read derived upstream evidence;
`scope()`, `require_scope()` and approved target IDs retain their existing meaning.
`scope_bindings` invalidates affected evidence when selected bytes change without
running another repository scan.

### Publish the complete source closure

`public_projection(state, selected=None, domain_id=None)` returns a complete,
sanitized `source_lineage_context`: `nodes`, `edges`, `gaps`, `seed_object_ids`,
`entity_roots` and the unchanged `generation_entity_ids`. Nodes carry their opaque
source-qualified ID, root, adapter, kind and identifier-shaped display names.
Private paths, locators, SQL, raw reference expressions and freeform source
metadata are omitted. Unsafe display labels fall back to the opaque object ID.
Edges use `upstream_id` and `consumer_id`; unresolved targets have a null upstream
ID and remain explicit. Each `entity_roots` entry contains `entity_id`,
`root_object_ids` and `context_object_ids` to preserve per-target associations.

`render_svg(projection)` draws every known source object top-down, including cycles
with a visible gap notice. For readable delivery, render one selected entity's
closure per SVG. Node groups carry `data-source-node-id`; known-edge paths carry
`data-upstream-id` and `data-consumer-id` for independent coverage checks. SVGs
contain escaped labels and inline presentation attributes, with no scripts,
external resources or style blocks. `csv_export(state, selected=None,
domain_id=None)` includes every scoped node, edge and gap without a display cap.
Both exports describe supplied source evidence; they neither add target model IDs
nor establish current warehouse/native validation.

## Record a staging policy once

`staging_ports.configure(state, policy)` accepts:

```text
schema_version: 1
domain_id: selected domain
target_root_id: registered target root
source_root_ids: [registered legacy/staging roots]
candidate_model_ids: [explicitly chosen target entity IDs]
staging_object_ids?: [explicitly chosen upstream object IDs]
missing_staging: propose_port | unresolved
version_preference: compatible_target | explicit_order
request_reference: actual user instruction reference
```

The target and staging roots must be distinct. `candidate_model_ids` may be empty
at intake while design is undecided; no port row is then eligible. A staging
object must be explicitly selected in the policy or covered by an existing
`migration_intent` `raw_staging` root/path role. Do not infer staging from a file
name or treat every upstream model as eligible. Repository roles must agree with
recorded migration intent when present. Older engagements remain unassessed until
these optional companions are adopted.

Persist a policy with `configure-staging-ports --run /local/run --document
policy.json`, then its candidate register with `record-staging-ports --run
/local/run --document ports.json`, using the same guided wrapper.

## Add the candidate port register

`staging_ports.register(state, request, run_dir=None)` accepts
`{schema_version: 1, domain_id, rows: [...]}`. Each row requires:

- `id`, `model_ids`, `source_object_id`, `target_native_ids` (exact lookup IDs).
- `decision`: `reuse_target`, `port_missing`, or `unresolved`.
- `rationale` and `evidence_refs: [{reference, sha256}]` citing original staging.

Optional row fields are `target_object_id`, `candidate_path`, `existing_id`,
`naming_resource_id`, `comparisons`, `support_files` and `version_order`:

- `comparisons` maps each exact target object ID to all six canonical dimensions:
  grain, keys, definitions, history, security and dependencies. Each value is
  `{status: compatible|change_required|unknown, evidence_refs: [...]}`. Every
  dimension cites current original target evidence. Reuse requires all compatible.
- `support_files` contains `{reference, sha256, kind}`. Kinds are `yaml`, `macro`,
  `configuration`, `test`, `seed` and `other`. Preserve these dependencies in the
  proposed patch; this register neither copies nor executes them.
- `version_order` contains `{object_id, rank, evidence_refs}`; larger distinct
  integer ranks mean explicitly later versions. Under `explicit_order`, choosing
  among multiple compatible targets requires an order for all of them. This is
  **recorded host evidence**, not authenticated revision ancestry. File times,
  lexical version strings and repository labels never establish newer behavior.

Prefer a compatible target. A present incompatible/unknown target requires a
decision; it is not a missing target. `port_missing` requires the policy to allow
proposals, no matches in the supplied target identity inventory, and a canonical
candidate path. Missing target extraction cannot establish absence. Pin the
target extraction as well as source/support files so a later target discovery or
changed bytes invalidates the decision. Retain old/unresolved rows across updates;
never silently reassign their source identities or overlap candidate output paths.

The register remains candidate planning. Naming stays
`requires_governed_candidate_check`; existing-model and naming resource references
do not approve a name or generation. Use the canonical design, naming registry,
assigned output paths and independent validation before actual candidate authoring.
Registered repositories remain read-only; delivery is a local candidate patch.

`summarize(state, selected=None)` returns scoped public rows and candidate,
unresolved and stale counts. It omits original paths, freeform rationale and input
contents. `csv_export` exports all such rows without a display cap, with spreadsheet
formula protection. `read` is the private host view; `scope_bindings` supplies
freshness for existing task fingerprints. Neither a port row nor a reuse record
establishes native success, retirement permission or deployment authority.
