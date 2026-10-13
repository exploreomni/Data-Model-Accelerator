# Shared review surface and portable exports

Use `scripts/delivery_portal.py` after the durable workflow in [guided-workflow.md](guided-workflow.md). The host agent assembles presentation content from the existing evidence/model contracts; the customer should not hand-author this file. It is a projection for navigation, never a replacement for a catalogue, review-package, authority or execution verifier.

## Stage and decision review

Use the saved [staged engagement](staged-engagement.md) as the authority for stage
progress, design version, current scoped review and task freshness. Its public
projection supplies stage next actions, entities, asset mappings, decisions and
development-effort results; do not invent pass badges in presentation JSON.
Show answer-recorded separately from resolved. The page exports version-bound
decision-response requests; the agent imports them and refreshes the page.
Downloading responses cannot authenticate a reviewer or approve a design.

Filter the entity inventory by associated asset, use its layer selector and
table/domain search, and inspect related decisions to explain why each entity
exists. Retain verified/inferred/unmapped coverage and
dependency context. These controls change only the visible view: they do not
prune approved scope, remove required dependencies or alter exported files.
Scope and artifact selection remain explicit operations.

Show development effort with its reviewed scope, category, confidence, reasons
and blockers. Unknown and stale assessments must remain visible instead of
becoming Easy. A design-only package can omit implementation while retaining its
review state; omitted code is not evidence of completion or approval.

## Content contract

The review is JSON schema version 1 with:

- `title`, `description`: engagement-specific prose; synthetic examples explicitly identify themselves.
- `source_fingerprint`: copy the exact current `state.inputs.source.fingerprint` object.
- `context_sha256`: use `delivery_portal.context_fingerprint(state)` to bind source, catalogue, target, runtime and discovery context. A refreshed mismatch blocks rendering/export of stale content.
- `target`: exact selected `framework` and `warehouse`.
- `models`: `{id, name, layer, domain, grain, columns: [{name, type, key, description}]}`. Use optional `artifact_id` to link a table directly to its registered code in an engineering export. Stable IDs are unique. `layer` is bronze/silver/gold. Include all scoped objects; unknown type/grain remains explicit. This presentation dictionary does not replace the full canonical dictionary.
- `relationships`: `{from, to, kind, label, evidence}` with optional `predicate`, `cardinality`, `role`, and `status` (or `implementation_status`). Endpoints refer to model IDs. `kind` is `lineage` or `relationship`; existing descriptive `label` values remain supported. For example, a relationship may declare `predicate: "orders.bill_to_id = addresses.id"`, `cardinality: "many:0..1"`, `role: "bill_to"`, and `status: "authored"`. Authored means declared implementation, not successful execution or an enforced constraint; `proposed` marks design-only edges. Unspecified values remain unspecified. Connected blocks use distinct edge IDs and routes, with a visible, complete predicate/cardinality/role ledger below the diagram.
- `changes`: `{id, source, target, disposition, rationale, consumers: [], decision}`. Retain unresolved consumers and proposed retirements. A disposition is not approval.
- `decisions`: `{id, question, status, answer}`. These display recorded statements; use existing typed authority evidence for acceptance.
- `validation`: `{id, label, scope, status, expected, actual, details, evidence_id}`. Scope is static/local/warehouse/semantic/business/operational; status is pass/fail/pending/skipped/not_applicable. Results are always **reported**, not authenticated by the viewer. Human approval cannot be represented as a passing test. Keep every required case, including missing/failing ones, and link its exact existing evidence ID.
- `artifacts`: `{id, path, sha256, category, audiences, requires: [], description}`. Paths are relative to the selected artifact root; record actual hashes. Categories are documentation/diagrams/dictionary/implementation/validation/sample_data/technical_audit. Audiences are reviewer/engineer/audit. `requires` lists other artifact IDs that must be selected together. Document externally supplied prerequisites explicitly; do not silently omit seed/configuration dependencies.
- Optional `handoff`: `{design_artifact_id, implementation_guide_artifact_id}`. Point to one maintained design narrative and one setup guide from the existing artifact inventory. Omit an unrequested role. IDs must be distinct; the design is `documentation`, the guide is `documentation` or `implementation`, and both use `.md` or `.txt`. They are navigation references, not an additional readiness record. The export drops references whose files are excluded by audience or category. Legacy reviews without these references still work; the page never guesses a primary document from a filename.

The same offline page now starts with Overview, Design and Implementation, with supporting sections behind a detail control. Its readiness summary derives from the current included files, scoped model, decisions and reported checks. It keeps local checks, native verification and business acceptance distinct; missing evidence and omitted exports never imply completion. The maintained design and setup guide can be read directly in their respective sections. Detailed dictionaries, evidence, file selection and audit remain secondary paths.

Each working export has one generated root `START_HERE.html`. Register design/setup documents under their own names: additional `START_HERE.html`, `.md` or `.txt` basenames are rejected case-insensitively, including in subdirectories. Separate audit exports may preserve historical Markdown/text starters; active HTML remains unsupported as an input artifact. This rule does not rewrite or invalidate older frozen ZIPs.

Only explicitly registered files are included. Registered audience labels express the preparer's sharing selection, not verified redaction or authorization. Curate prose, filenames, decision summaries and documentation for the intended audience before registration. The helper rejects known credential paths, active SVG, symlinks, traversal, nested archives and unregistered file types; this is not a universal secret scanner. Source and target credentials must stay outside packages.

Native Omni `.view`, `.topic` and the exact extensionless basenames `model` and `relationships` are accepted only as `implementation` artifacts. Preserve their names and bytes; no transport suffix or restoration script is needed. This exception does not allow other extensionless files, shell executables or HTML, and retains the ordinary audience, dependency and hash checks. It does not validate Omni YAML syntax or native behavior.

Markdown links are verified against the **exported** path, including category prefixes: documentation/diagrams/dictionary use `01_Model/`, implementation uses `02_Implementation/`, validation uses `03_Validation/`, samples use `04_Sample_Data/`, and audit uses `Technical_Audit/`. For example, `03_Validation/validation/RESULTS.md` links to the shipped `01_Model/docs/METHODOLOGY.md` with `../../01_Model/docs/METHODOLOGY.md`. Original subdirectories are preserved beneath the prefix. Files are not rewritten because the registered hashes bind their exact bytes. Inline links, images, reference links and HTML href/src references must resolve to selected files; anchors and external HTTP(S), mailto and telephone URLs are allowed. Fragment heading existence and external availability are not checked. Unsafe paths/schemes and missing internal files stop export with the referring document and destination. Resolved file links become export dependencies, so deselecting a linked category in the browser cannot create a broken smaller package.

## Render and export

```sh
python scripts/delivery_portal.py render --state /absolute/engagement/state.json \
  --review /absolute/review-content.json --output /absolute/engagement/START_HERE.html
python scripts/delivery_portal.py package --state /absolute/engagement/state.json \
  --review /absolute/review-content.json --artifacts /absolute/candidate \
  --audience engineer --include implementation,documentation,diagrams,dictionary,validation \
  --output /absolute/engineering-handoff.zip
python scripts/delivery_portal.py package --state /absolute/engagement/state.json \
  --review /absolute/review-content.json --artifacts /absolute/candidate \
  --audience reviewer --output /absolute/reviewer-handoff.zip
python scripts/delivery_portal.py verify /another/location/reviewer-handoff.zip
```

CLI render/package refreshes and verifies durable state first. In-process callers must refresh state before producing review content. Passing the old source hash manually is not a freshness check. The renderer changes no source repository files; output must remain outside it.

Reviewer packages forbid implementation, samples and technical audit. Expected/actual comparison values are omitted from the reviewer's web view; descriptions and explicitly registered documents still require appropriate curation. Engineer exports omit samples by default. Audit artifacts require a separate `--audience audit` export. The agent retains required internal documentation regardless of selected exports.

Each ZIP contains a portable `START_HERE.html`, selected files in numbered folders, and `DELIVERY_MANIFEST.json`. The page works offline, can show/copy/download text files, and can export a smaller selected package with all unselected embedded payloads removed. Required dependencies prevent incomplete selections. The original ZIP remains unchanged. Browser crypto is needed to create a new integrity manifest; when unavailable, use the CLI export. Never treat a browser checkbox or downloaded answer file as execution permission or approval.

Use the guided workflow's `record_handoff` step to record prepared files before export. The portal displays `handoff_prepared` as **Prepared handoff**, retains the workflow's next action, and shows only a compact delivery summary. Its recorded file count describes the prepared set; a reviewer or reduced export can contain fewer files. A status-only page has no payload and directs the user to export already prepared files. Preparation does not establish executed tests, business acceptance, or native/deployment approval. In-process callers can use `resolve_selection(state, audience, include=None)` to resolve the same saved/default selection used by packaging.

The package verifier checks an exhaustive inventory, byte lengths and SHA-256 hashes at any path without extracting ZIP entries. New Python and browser exports include `context_sha256` in the manifest and embedded engagement summary; verification requires them to match and checks portable Markdown links. Legacy integrity manifests without this field retain their original integrity-only verification without claiming context or link validation. This establishes file integrity only. It does **not** authenticate a signer, verify a cloud run, rebind the old frozen benchmark contracts, or prove business approval. Keep original frozen records immutable; replay them only through a qualified evidence resolver or their existing qualified environment.

## Scale and failure behavior

Review collections have an explicit 20,000-item ceiling; packaging permits 5,000 registered artifacts, 20 MiB per file and 100 MiB of selected source payloads. Rendered packages are bounded separately. Exceeding limits fails with a partitioning instruction; no truncation produces a complete badge. Use coherent domain waves and retain complete cross-domain scope/denominators. File preview is limited to 2 MiB without altering downloaded bytes. Tables paginate and files filter. Diagrams partition by domain, at most 36 objects, and connection density; cross-view connections retain explicit counts and the full page ledger. Reserved gutters route connectors outside unrelated table blocks; parallel roles use separate ports and lanes. Teal shows lineage, violet authored joins, dashed amber proposed joins, and dotted grey other/unspecified joins. Large diagrams scroll at a readable scale instead of shrinking every label to fit the page. Inspect rendered output for the actual inventory before delivery.

An unsupported output format is a recorded generation request for the host, not a target label switch. Extending a platform requires its reviewed model, artifact, metadata and execution contracts plus qualification. The UI needs no platform-specific rewrite.
