# Multiple read-only source repositories

Add explicit named repositories to an existing engagement without restarting,
copying a subset, or moving repositories under a new parent. The original
`--repo` stays the primary input. Registration grants no source execution,
disclosure, approval or deployment authority.

```json
{
  "schema_version": 1,
  "roots": [
    {"id": "legacy", "path": "/absolute/legacy-repository", "revision": "snapshot-1", "dirty": "unknown"},
    {"id": "warehouse", "path": "/absolute/warehouse-repository"}
  ]
}
```

```sh
python3 skills/data-model-accelerator/scripts/guided_workflow.py register-source-roots \
  --run /absolute/engagement-run --document /absolute/source-roots.json
```

There may be at most 16 roots including primary. Roots must exist when registered,
be canonical directories, and neither overlap each other nor contain the run or
registered artifact outputs. Symlinks, credential directories and identity
rebinding are rejected. Registration is additive; omitting an earlier ID does
not remove it. Repeating the same request does not change the registry revision.
To change the declared source revision, retain its ID/path and submit updated
metadata. `revision` is an optional opaque identifier (letters, numbers, dots,
underscores or hyphens; at most 128 characters); `dirty` is `clean`, `dirty` or
`unknown`. Both are host declarations. The helper does not run Git and does not
infer that an export corresponds to a clean commit.

Use exact references in canonical `source_paths`, discovered domain paths and
worker input paths:

| Reference | Repository |
| --- | --- |
| `models/orders.sql` | Original primary repository, unchanged |
| `@sources/legacy/views/orders.sql` | The explicitly registered `legacy` root |
| `@sources/warehouse/models/orders.sql` | The explicitly registered `warehouse` root |

The namespace becomes reserved only after opt-in registration. An existing
primary `@sources` directory prevents registration instead of changing the
meaning of legacy paths. Unknown root IDs, traversal, secret files and symlink
files fail; there is no filename search or fallback to another repository.
Same-named files in two roots remain distinct. Named references hash bounded,
descriptor-relative reads (8 MiB per file, 32 MiB per worker packet, 512 files per
packet); larger inventories still use small scoped worker packets. Unqualified
primary inputs retain their prior fingerprint and source-read contract even
after a named root is added.

Refresh uses the existing bounded static readiness collector independently for
each root, retaining file counts and byte fingerprints. Its existing scan limits
and options apply per repository. Secondary findings and omission paths retain
their named-root prefix; generation blockers apply to aggregate readiness.
Missing roots or incomplete coverage stay
visible and never become a complete aggregate fingerprint. Exact model/worker
references bind only their bytes and referenced root identity/revision metadata;
adding or changing an unrelated root does not change those scoped bindings.
Models without explicit source slices intentionally depend on the whole source
fingerprint. Existing coverage, review and provisional-generation rules continue
to apply; registration supplies no approval.

For private host integration, `source_roots.approved_roots(state)` returns all
root paths, `resolve(state, reference)` resolves one exact input, and
`ensure_output(state, path)` rejects overlap with any root. Use the latter before
creating outputs. `public_summary(state)` returns only registry/root IDs,
revision declarations, counts, fingerprints and coverage status; it returns
`None` for legacy single-root engagements and excludes absolute paths.

Coverage records remain the existing `record-design-coverage` source inventory,
with a separate root and exact inventory for each source. They do not become a
second registration mechanism or assert native completeness. See
[design reliability](design-reliability.md) for inventory bounds and retained
omissions. Keep all private registrations and inventory documents outside inputs.
