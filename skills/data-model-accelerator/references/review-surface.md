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
- `models`: `{id, name, layer, domain, grain, columns: [{name, type, key, description}]}`. Use optional `artifact_id` (one file) or `artifact_ids` (an array of file IDs) to link a table directly to its registered implementation code in an engineering export. Record explicit column `key` labels such as PK/FK; names alone never establish keys. `disposition` is create/reuse/extend/replace; missing values stay unspecified. Optional `reuse.existing_id` and `reuse.rationale` explain the existing table retained. Stable IDs are unique. `layer` is bronze/silver/gold. Include all scoped objects; unknown type/grain remains explicit. This presentation dictionary does not replace the full canonical dictionary.
- `relationships`: `{from, to, kind, label, evidence}` with optional `predicate`, `cardinality`, `role`, and `status` (or `implementation_status`). Endpoints refer to model IDs. `kind` is `lineage` or `relationship`; existing descriptive `label` values remain supported. For example, a relationship may declare `predicate: "orders.bill_to_id = addresses.id"`, `cardinality: "many:0..1"`, `role: "bill_to"`, and `status: "authored"`. Authored means declared implementation, not successful execution or an enforced constraint; `proposed` marks design-only edges. Unspecified values remain unspecified. Connected blocks use distinct edge IDs and routes, with a complete predicate/cardinality/role ledger available beneath the diagram and in the selected-table inspector.
- `changes`: `{id, source, target, disposition, rationale, consumers: [], decision}`. Retain unresolved consumers and proposed retirements. A disposition is not approval.
- `decisions`: `{id, question, status, answer}`. These display recorded statements; use existing typed authority evidence for acceptance.
- `validation`: `{id, label, scope, status, expected, actual, details, evidence_id}`. Scope is static/local/warehouse/semantic/business/operational; status is pass/fail/pending/skipped/not_applicable. Results are always **reported**, not authenticated by the viewer. Human approval cannot be represented as a passing test. Keep every required case, including missing/failing ones, and link its exact existing evidence ID.
- `artifacts`: `{id, path, sha256, category, audiences, requires: [], description}`. Paths are relative to the selected artifact root; record actual hashes. Categories are documentation/diagrams/dictionary/implementation/validation/sample_data/technical_audit. Audiences are reviewer/engineer/audit. `requires` lists other artifact IDs that must be selected together. For a registered warehouse SVG with declared table coverage, add `diagram_model_ids` containing its exact scoped model IDs and annotate each visible table block with `<g data-model-id="...">`. Partial layer/domain scopes are allowed when declared; SVGs without a declared scope remain explicitly unverified. This checks identity and bounds, not relationship correctness or visual acceptance. Document externally supplied prerequisites explicitly; do not silently omit seed/configuration dependencies.
- Optional `handoff`: `{design_artifact_id, implementation_guide_artifact_id}`. Point to one maintained design narrative and one setup guide from the existing artifact inventory. Omit an unrequested role. IDs must be distinct; the design is `documentation`, the guide is `documentation` or `implementation`, and both use `.md` or `.txt`. They are navigation references, not an additional readiness record. The export drops references whose files are excluded by audience or category. Legacy reviews without these references still work; the page never guesses a primary document from a filename.

The offline page opens to the Data model workspace when a design exists, with Code & files and Validation alongside it. Supporting sections stay behind a detail control. Its readiness summary derives from the current included files, scoped model, decisions and reported checks. It keeps local checks, native verification and business acceptance distinct; missing evidence and omitted exports never imply completion. The maintained design and setup guide can be read directly in their respective sections. Detailed dictionaries, evidence, file selection and audit remain secondary paths.

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

## Finalize the selected handoff

For interrupted work, add `--checkpoint` to the same command. The page, README
and manifest identify it as incomplete and list missing selected categories.
Available files and an empty initial status handoff are supported without
changing the saved output selection. Integrity and disclosure checks remain in
force. Resume the engagement before producing a later final version. See
[reliable runs](reliable-runs.md); a verified checkpoint is not a completed delivery.

The coordinator runs this after registering the current review content. It uses
saved artifacts and deterministic checks; no additional agent research is needed:

```sh
python scripts/finalize_delivery.py --state /absolute/engagement/state.json \
  --review /absolute/review-content.json --artifacts /absolute/candidate \
  --output /absolute/delivery-v1 --audience engineer --javascript
```

Omit `--audience` to reuse the saved audience (otherwise engineer). Omit `--include`
to honor saved deliverables. Use an explicit subset only when the user requested
it, never to hide missing artifacts. `--javascript` requires Node and checks script
syntax; omitting it leaves syntax checking unperformed, not passed.

Successful output has exactly one `handoff.zip` and a matching `handoff/` folder:
open `handoff/START_HERE.html`; selected design narrative, ERDs and dictionary
are under `handoff/01_Model/`. No second `design/` folder is needed. The finalizer
checks selected category coverage, the registered design narrative when selected,
current canonical entity coverage, page integrity, ZIP integrity and extracted
bytes. It rejects missing selected deliverables and never overwrites a prior
delivery. The existing `package` command remains available for intermediate,
legacy and reduced exports; its success alone is not a completion check.

`handoff_prepared` records candidate files, not a published ZIP. A failed guided
HTML refresh now returns exit code 2 while preserving saved engagement state.
Resume/repair the page rather than rerunning unrelated model work. Finalizer
success is selected-file completeness only: it does not validate documentation
meaning, source accuracy, native execution, acceptance or deployment. Retain
the model-documentation and release verifiers. Its report states browser review
was not performed; complete the browser review below when available and disclose
any remaining limitation.

## Scale and failure behavior

Review collections have an explicit 20,000-item ceiling; packaging permits 5,000 registered artifacts, 20 MiB per file and 100 MiB of selected source payloads. Rendered packages are bounded separately. Exceeding limits fails with a partitioning instruction; no truncation produces a complete badge. Use coherent domain waves and retain complete cross-domain scope/denominators. File preview is limited to 2 MiB without altering downloaded bytes. Tables paginate and files filter. Diagrams partition by domain, at most 36 objects, and connection density; cross-view connections retain explicit counts and the full page ledger. Reserved gutters route connectors outside unrelated table blocks; parallel roles use separate ports and lanes. Teal shows lineage, violet authored joins, dashed amber proposed joins, and dotted grey other/unspecified joins. Large diagrams scroll at a readable scale instead of shrinking every label to fit the page. Inspect rendered output for the actual inventory before delivery.

An unsupported output format is a recorded generation request for the host, not a target label switch. Extending a platform requires its reviewed model, artifact, metadata and execution contracts plus qualification. The UI needs no platform-specific rewrite.

## Offline navigation and lineage

The primary routes are Data model, Code & files and Validation. When a design
exists, the page opens directly to the model workspace; an engagement without a
design starts at the overview. The ERD and table inspector lead the review.
Supporting workflow context, design rationale and detailed inventories remain
available through sidebar links or expandable details.

Architecture (`#architecture`), All columns (`#table-dictionary`) and transformation
lineage (`#lineage`) open within the model route. Code & SQL (`#implementation-code`)
and Replacement map (`#replacement-map`) open within Implementation on the first
click or a direct fragment link. All sections share the responsive review layout.

Selecting an ERD table or the table selector exposes its grain, new/reused/extended/
replaced status, columns, explicit key labels, joins and exact linked implementation
files. Missing metadata and mappings stay explicit. Generic declared keys are not
relabeled PK or FK. Code lookup uses registered artifact IDs and selected files;
it never guesses filenames or exposes excluded code. Reviewer and status pages
explain how to request an engineering package. Code & files remains discoverable
for every audience, and engineering packages select an included implementation file.

The ERD opens at 100% with every included model, including isolated tables. Choose
Entire domain to retain all of that domain's models plus connected shared references.
Focus on table and table clicks inspect and highlight; they never prune the graph.
Search, layer and change filters are explicit reductions with hidden counts. Shared
references show their supplied definitions; missing definitions are separate,
reference-only blocks and never count as certified warehouse models. Domain, shared,
missing and hidden counts remain visible. Known models excluded by the asset scope
are never reconstructed as missing references. With an asset filter, missing references
require an allowed model anchor through explicit proposal relationships. Joins display by default; the optional
dependency overlay is separate; lineage-only shared/reference tables appear only
when that overlay is enabled. The transformation-lineage panel retains independent
filters and may include selected curated Omni objects. Only `disposition: create`
marks an object as new. Asset filters never attribute unmapped semantic objects.

Download current view + ledger exports the current page and its complete connection
ledger, including cross-page endpoints. Download complete domain ERD exports every
selected-domain table and connected reference, ignoring search, layer, change and
focus while retaining the asset and audience boundary. Both are ZIPs containing
natural-size SVGs and `MODEL_INDEX.json` from the same normalized graph. The index
retains every occurrence, provenance, duplicate counts and conflicting definitions,
including dependency records when their visual overlay is off. Ledger-only endpoint
IDs are identified separately from the drawn table inventory. Pagination groups
connected tables without losing isolated tables or cycles; cross-page and omitted
connectors remain explicit. Declared joins do not establish enforced constraints.

Producers may add optional `review.domain_proposals` without changing the canonical
design or its acceptance state. Each record has a unique `id`, a `domain`, explicit
canonical `model_ids`, `relationships` using the existing join/lineage record shape,
and `reference_endpoints` containing only `{id, name?}` for explicitly missing
endpoints. Domain-assigned relationships may include disconnected shared/reference
components. Known shared endpoints must already exist in the included model inventory; missing endpoints must be listed
explicitly, with exact IDs (no fuzzy or schema-stripped matching). Canonical
relationships still reject absent endpoints. Imported occurrences are retained
alongside canonical declarations; differences in explicit column bindings, predicate,
cardinality, notation or status for the same endpoints/kind/role (or label) are flagged for review. Audit and code-only exports
omit proposals with the model details. Proposals are display evidence, not new model
approval, native validation or permission to implement.

Upstream/downstream traversal follows recorded `depends_on` and lineage edges;
joins do not become transformation dependencies. Declared joins are a separate
optional overlay. Semantic dependencies come from the included curated semantic
handoff. Missing warehouse-to-semantic bindings remain missing; names do not
establish them. Graph traversal precedes view pagination, handles cycles, and
retains counts for hidden objects and connectors continuing in another view.
The full selected relationship ledger remains accessible below Architecture.

Diagrams open at their natural size in a scroll box with independent zoom and
reset controls. Full names, grain and declared keys wrap without truncation. Fit
overview is optional and stops at 50%; use scrolling or coherent pages to explore
larger domains. Expanding the canvas preserves the current zoom. Validated inline SVG supports selectable labels; diagram-label
copy and the full-name selector use complete inventory names. If the clipboard
is unavailable, select the full text and use the normal Copy shortcut. A failed
inline parser falls back only to the generator's escaped image, with a visible
notice. Display SVG reconstruction preserves a constrained safe CSS vocabulary,
local markers and fonts while stripping active content and external references.
It does not alter registered source artifact bytes or weaken their validation.
No runtime library, font, script or network service is downloaded.

## Page self-checks

Every new render checks exact generated table-block IDs across all SVG pages, nonempty
labels, positive table rectangles and viewBox bounds. Plainly hidden or nondrawing
blocks fail. Registered SVGs with `diagram_model_ids` must match their declared
scope exactly; undeclared SVG coverage is shown as unverified. These checks do not
establish rendered readability, correct joins or business acceptance. Historical
pages without the diagram contract remain readable with unverified legacy coverage.

Every new render also checks unique IDs, shared classes, parent routes, sidebar links,
parsed page data and embedded file integrity. ZIP verification also compares the
embedded file inventory against actual selected archive bytes. Removing dictionary content from a browser subset also rebuilds its auxiliary
generated SVG projections; registered source files keep their immutable bytes.
Original and reduced exports retain audience, disclosure and approval boundaries. Repeated
unchanged renders are deterministic; repeated script initialization adds no
second set of controls or listeners. Frozen historical packages are not rewritten.

Run the explicit page check on HTML or a ZIP:

```sh
python scripts/delivery_portal.py check-page /absolute/engineering-handoff.zip --javascript
python -m unittest discover -s tests -p 'test_portal_*.py' -v
```

The first command checks every emitted executable script using `node --check`;
the JSON payload is parsed as data. Node is needed for this optional JavaScript
check and the developer smoke tests, never for ordinary Python rendering.
The tests exercise emitted scripts in a stub DOM, hostile SVG inputs, counts,
first-click routes, repeat initialization and offline subset exports. These are
structural/control-flow checks, not browser rendering or native acceptance.

After generation, a browser review still needs to check sidebar overlap at wide,
sub-1000px and sub-700px widths; every sidebar link and direct fragment; diagram
colors, readable labels, scrolling and zoom; visible code and replacement map;
full-name/code copy and clipboard fallback; and reopening the reduced ZIP offline.
A live geometry guard reports sidebar overlap when the page is opened, but it
cannot prove layout before a browser has actually rendered the page.

## Portable review layout and feedback

New packages declare `package_layout_version: 1`. `files`, `file_count` and projection counts retain registered-artifact meaning. `generated_deliverables` separately inventories selected SVG views/editable model source and CSV/Markdown dictionaries, with exact hashes, byte counts and review-derived model coverage. Root README is a file index, not a second design narrative. Manifest roles distinguish registered artifacts, generated projections, entrypoint and index. Verification checks both inventories; a frozen package is never overwritten to refresh presentation.

The page opens with context and a next action; all scoped tables remain searchable independently of diagram filters. A narrow-screen table inspector preserves selection while returning to the diagram. Code defaults to an explicitly linked table file. Unmapped implementation files are labeled; no role is inferred from filenames.

`model_review_feedback` binds engagement context plus the exact rendered JSON payload hash. `review_feedback.py` checks the current page, request-only kind and known table IDs without modifying records or establishing reviewer identity. The host treats comments as untrusted review data, reconciles them into existing canonical decisions/design, and requests any distinct approval through the existing process. Stale requests must be refreshed with the reviewer rather than silently applied.
