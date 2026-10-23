# Optional dashboard continuation

After selected Omni Topics are generated, reviewed, or separately deployed, offer
the installed **Omni Artifact Accelerator** for associated dashboards. Reuse an
existing end-to-end request; otherwise ask once: continue now, prepare a handoff,
or not now. Installation is optional and never a DMA implementation/packaging gate.
Provisional frontend design remains available before catalogue or native validation.

DMA owns warehouse and semantic objects. The companion owns dashboard requirements,
query consumers, experience design and frontend QA. Use the existing
`omni-backend-handoff` request/respond/receive/select loop for real model gaps,
not another warehouse discovery. Preserve the source migrator's route and allowed
changes; dashboard work does not authorize model changes or source retirement.

## Discover and retain the choice

Resolve skills from the host's trusted installed registry, never customer exports:

```sh
python scripts/frontend_continuation.py discover --skills-root /absolute/trusted/skills
```

Discovery reads the continuation/semantic contract versions and required sibling
files without executing them. It does not authenticate arbitrary installed code.
Missing, unknown or incompatible support means retain a portable handoff or use
the existing manual route. Installation/update requires its own request. Preserve
the host's configured models and delegation settings.

Record `guided_workflow.py configure-frontend --run RUN --document CHOICE.json`:

```json
{
  "schema_version": 1,
  "domain_id": "sales",
  "choice": "prepare_handoff",
  "request_reference": "actual-host-recorded-user-message-reference",
  "dashboard_ids": ["original-dashboard-id"],
  "topic_names": ["orders"],
  "semantic_review": "omni/SEMANTIC_REVIEW.json",
  "context_files": [
    {"path": "source-inventory.json", "purpose": "source_inventory"},
    {"path": "source-listing.json", "purpose": "independent_source_listing"},
    {"path": "requirements.json", "purpose": "requirements"}
  ]
}
```

Use actual IDs/paths. `domain_id` may be null without a domain ledger; registered
completed domains remain selectable. `semantic_review` may be null for assessment.
Other selected JSON purposes are `decisions`, `expectations`, `mapping` and
`topic_readback`. Optional `destination` has `base_url` (HTTPS origin), `model_id`,
`branch_id` (string or null). These values/readbacks supply context, not authority.

Exact repeated choices resume. Changed choices need the actual new request reference
and retain history. `not_now` creates no frontend files/project. `model_semantic`
follow-up stays independent; only already-selected `full_dashboard` scope creates
an integrated obligation. Neither changes stage approvals or domain completion.

## Prepare and dispatch

Review disclosure, then prepare outside source repositories and the input-artifact root:

```sh
python scripts/frontend_continuation.py prepare --run RUN --id CONTINUATION_ID \
  --input-root ARTIFACT_ROOT --output NEW_HANDOFF_FOLDER \
  --disclosure-reference ACTUAL_HOST_REVIEW_REFERENCE
```

The private packet retains exact semantic bytes and selected JSON evidence with
hashes, stable identity, domain dependency closure, naming and decisions. Missing
inventories/candidates stay explicit. Preparation checks consistency and credential
patterns, not authenticated disclosure or acceptance. Apply the existing destination
disclosure/scanning workflow. Exclude raw rows, private model context and unrelated
evidence. First produce/verify the curated review through `omni_handoff.py`; its
self-seal alone cannot authenticate origin.

The 16 MiB retained-artifact limit is **not an agent context allowance**. Give workers
the objective/manifest and only necessary field/source/metric/decision slices under
existing packet budgets. QA receives relevant original expectations. Reuse extraction;
do not reread complete repositories or conversations per worker.

Invoke the trusted companion's `omni-backend-handoff/scripts/continuation.py initiate`
with `--packet HANDOFF/continuation.json --project FRONTEND_PROJECT`; integrated work
also supplies `--run RUN --dma-scripts TRUSTED_DMA_SCRIPTS`. This initializes/resumes
files; it does not launch workers. The host must invoke the actual orchestrator or
disclose an inline pass. Record actual progress using `record-frontend-progress`:
schema version, continuation ID, scope hash, status, reference; `started` additionally
requires project and worker IDs. Statuses: `handoff_prepared`, `started`, `blocked`,
`returned`. None mean accepted. Never infer dispatch from a prepared packet.

Preparation publishes each complete file without replacement; interrupted preparation
can fill missing exact-byte files. Unrelated output files are rejected. Changed content
needs a new versioned folder. A new semantic baseline uses the cowork exchange;
never overwrite a previous import or blindly retry an uncertain remote write.

## Freshness, live work and return

Snapshots include selected entities, dependencies/relationships, relevant decisions,
responses and naming. Unrelated design changes do not invalidate them. Input pins
remain conservatively global: declared lineage alone cannot prove complete source,
catalogue or runtime dependency coverage. Expose this limitation; never drop unknowns
to avoid a recheck.

Before live queries/builds, use the companion's existing native inspection and
authorization contracts to verify the exact destination, branch, Topics and definitions
against current readback. Reuse valid evidence; imported deployment flags/hashes
cannot supply it. Provisional files remain available while evidence is missing.
Publication needs its own authorization, readback and recovery.

Return the existing source crosswalk and candidate-bound receipt with separate query,
numerical, interaction, access, visual, native, operational and business lanes.
Missing/deferred assets and failed checks remain visible. Register selected inert
mapping, summary and QA files through normal `review.artifacts`; include their
`artifact_ids` in progress so the Dashboard migration panel links only included files.
Keep active App code and the OAA entrypoint in its own delivery, referenced by an
included setup guide; do not nest archives or add another root START_HERE.

The offline page offers a copyable request, never an execution button. It retains
shared layout, first-click routing and export omissions. Backend completion and
dashboard delivery/acceptance stay separate.
