# Large engagement state storage

The guided workflow keeps the same logical schema-v1 engagement and run folder as
designs, reviews, task observations and history grow. Storage is separate from
generation readiness, input freshness, review authority and native execution.

## Supported readers

Use `guided_workflow.load_engagement(run_dir)` for the current logical state and
`engagement_state_store.load_revision(run_dir, revision)` for an immutable logical
revision. Both accept earlier inline state files and the compact storage format.
Readiness evidence JSON pointers apply to the **hydrated logical revision**.
Reading `state.json` directly is only sufficient for earlier inline states.

`engagement_state_store.storage_stats(run_dir)` validates the current storage and
returns its format, logical and index byte counts, component references, unique
component count and bytes, and the logical size limit. Accounting is not inserted
into state or material/freshness hashes.

## Format and bounds

- States up to 4 MiB retain the original inline JSON format.
- Larger states use a schema-v1 `guided_engagement_index` storage envelope in
  `state.json` and each new `revisions/<revision>.json`.
- Components live at `state-store/objects/<sha256>.json`, relative to the same run
  folder. Their exact bytes are SHA-bound and immutable. Unchanged components are
  reused across revisions; large containers and strings are split losslessly.
- Logical state is limited to 128 MiB. Each component is at most 1 MiB, each index
  at most 16 MiB, with at most 20,000 component references, logical depth 64 and
  2,000,000 logical nodes. Bounds fail explicitly; nothing is silently truncated.
- Workflow components are separated so a new observation need not rewrite an
  unchanged design. Logical state hashes, history, signatures and freshness data
  are retained exactly. This does not deduplicate or remove historical facts from
  the logical state.

These are per-state limits, not a lifetime disk quota. Immutable history can grow
across revisions. Copy or archive the entire run folder, including `state-store`,
when moving it. Source repositories remain read-only.

## Integrity and interruption

The writer creates verified immutable components first, then the immutable
revision, then atomically replaces the current head. An interrupted update leaves
the previous head usable. An interrupted initial head publication can recover
from its committed revision through normal resume. Orphaned component/revision
files from interrupted updates are not treated as newer authoritative state when
a current head exists; later revisions use new numbers.

Missing, modified, malformed, escaping or symlinked components fail closed. Do not
manually edit, remove or rename sidecars. There is no automatic garbage collector;
deleting apparently unused files could invalidate retained history. The same
logical state can be inspected and resumed without starting a linked engagement.
