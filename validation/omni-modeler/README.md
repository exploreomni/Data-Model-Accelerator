# Omni Modeler implementation qualification

Local implementation completed on `atx/omni-modeler`, 2026-10-05 America/Chicago, following [plan 17](../../docs/plans/17-omni-modeler-specialist.md). Baseline: `f705497c4e49b91c01bbd81b0d24bc0774b900f1`. Start with the [operator guide](../../docs/OMNI_MODELER.md).

**Local outcome: 1,747 tests passed, zero skips**, in 102.992 seconds with the existing isolated Python 3.12.14 runtime and pinned development dependencies. The baseline had 1,474 passing tests. A separate core-only Python 3.9 run discovered 1,747 tests: 977 passed and 770 optional-runtime tests were explicitly skipped, with no failures. Those skips are not qualification. The final focused Omni suite passed 413 tests; the affected portal suite passed 79 tests. Counts overlap and must not be added together.

No live warehouse, Omni tenant, external agent-host SDK, human business acceptance, deployment or remote CI qualification is claimed. Confidence is **High** for the reproduced bounded local behaviors; customer-specific correctness still requires independent expectations and native evidence.

## Implemented packages

| Package | Local implementation and evidence | Boundary |
|---|---|---|
| 1. Knowledge and capability contract | Offline progressive loader, public source modules, immutable upstream pin, 468 explicit object/operation/dialect rows; 13 focused tests | All live-qualified flags remain false; private research is excluded |
| 2. Target-role dispatch and installation | Explicit target tasks, approved projections, actual callback observation and before/after installation comparison; 39 author/independent modeler tests | Coordinator supplies the host adapter; identifiers do not qualify five external hosts or authenticate identity |
| 3. Inventory and change safety | Exact-byte authored/effective inventory, origin/dependency graph, independent-scope reconciliation, safe leaf patches; 53 author/independent tests | Opaque syntax survives without receiving a semantic pass; missing scope never implies deletion |
| 4. Core modeling | Filtered measures, single-parent inheritance, topic overrides/aliases/selectors, explicit paths, fiscal/timeframe checks | Cardinality, history and calendar behavior still need data/native tests; multiple inheritance remains gated |
| 5. Query views | Native query identities, modeled and conservative SQL forms, output/type/population lineage; 18 dedicated tests plus independent generated-candidate comparisons | Unknown SQL/controls, composites, LOD and aggregate-awareness generation remain unsupported |
| 6. Lifecycle | Recomputed dependency closure, baseline/new issue treatment, route/environment pins, four evidence lanes and optional signed native preflight; 20 author + 10 independent lifecycle tests and 48 native simulations | Imported captures are unauthenticated; legacy requests explicitly unassessed; synthetic development restriction remains |
| 7. AI context | Version 2 direct/derived gold lineage, topic query/AI selections, disclosure checks, repeated trials and exact optional result comparisons; 69 AI tests including 19 independent holdouts | No numeric coverage without expected results; no real AI-session, unrestricted prose or effective-access proof |
| 8. Guided handoff | Candidate-derived dictionary, topics/metrics, connected SVG, decisions, runbook, exact native files and private context; 20 handoff tests, fresh operator exercises and browser inspection | Semantic artifacts do not fabricate warehouse layer documentation or approve delivery |

The independent frozen corpus is under `tests/fixtures/omni_modeler/`. Its manifest protects 40 input/expected files. Generated modeled and SQL query candidates are compiled by a bounded test-only interpreter and compared with frozen results. Separate relational tests cover wrong-grain fanout, equal amounts, ratios, missing parents, multiple fact branches, role-playing joins, history overlap, bridge allocation and counterfactual changes. This interpreter is not Omni's query compiler. The authority corpus exercises eight otherwise-valid synthetic requests through a recording transport and verifies expected denials before external calls.

## Repairs found during implementation

Independent review identified and corrected opaque-parent patch replacement, ambiguous native-file routing, missing query outputs/dependencies, ancestor symlink handling, Unicode diagnostics, nested aggregate misuse, and the distinction between query exclusions and AI awareness. Unqualified implicit-whitelist transitive dependencies remain visible instead of being silently widened.

The handoff review found two additional issues: private context could be reclassified as reviewer documentation, and metric rows did not show topic selection. Packaging now validates bound input audiences/categories even when semantic evidence is omitted; the UI and dictionary distinguish shared inventory, query selection and AI awareness. Regression tests cover both. Fresh-user testing exposed outdated query-view guidance and an undocumented catalogue coverage enum; both guides were corrected.

## Fresh-context operator exercises

A separately spawned operator with no conversation history authored two small synthetic domains using repository guidance. It did not borrow completed candidates or frozen metric expectations. Both real workflow runs produced offline HTML and engineering ZIPs. The local deterministic modeler callback was explicitly marked simulation; the observed authoring agent assignment is separate from the callback receipt.

| Exercise | Observed result |
|---|---|
| New dbt/Snowflake/Omni model from minimal raw metadata | Four projection models, source declarations, layer documentation, dictionary, diagrams and provisional AI questions. All four projections ran in DuckDB; SQL shapes parsed as Snowflake. Omni static passed; unresolved meaning kept callback at `needs_review`. ZIP integrity verified. No dbt build or Snowflake execution claimed. |
| Existing BigQuery/Omni workbook | Separate authored/effective states round-tripped exactly. Leaf edits preserved comments, inherited definitions, a query view and unsupported window/calendar constructs. Both downstream dashboards were identified as affected. Static stayed unsupported and lifecycle pending. |
| Simulated SME iteration | A separate proposed filtered metric preserved the legacy metric. Two previous evidence records became stale; the old review was rejected. This is a self-authored scenario, not an SME decision. The original ZIP is historical after correction. |

Both planners correctly retained incomplete coverage for unclassified sidecars. The operator authored its own rows and expected behavior, so these exercises establish usability and workflow behavior, **not independent numerical accuracy**. Formal reviewed AI context was withheld where approved definitions were absent; the independent AI contract suite covers that implementation separately.

The fresh authoring harness ran in 2.255 seconds, excluding model authoring, research and visual review. No external provider calls or provider costs were measured. This is not a performance commitment. A curated replay fixes the fixture's caller-owned repository snapshot binding and adds explicit CI assertions rather than accepting a zero-exception run as success. [Recorded results](fresh-operator-results.json) distinguish original authoring from replay.

Reproduce the synthetic exercises with pinned dependencies and a new output directory:

```sh
python validation/omni-modeler/run_fresh_operator.py \
  --repo /absolute/accelerator-checkout \
  --output /absolute/new-synthetic-pilot-run
```

Open `A_raw_new_model/extracted/START_HERE.html`. For B, `B_existing_workbook/extracted/START_HERE.html` is the historical v1 package and `POST_CORRECTION.html` is the current pending state. A replay does not create another independent agent or establish host qualification. The repository synthetic workflow now runs this harness; its remote result remains pending until the tested revision is published and CI runs.

The coordinating agent inspected the rendered Omni page, topic/metric selection labels, artifact viewer, fresh Snowflake pilot page and BigQuery post-correction state in the in-app browser. This was a desktop visual check, not mobile/accessibility certification or native Omni UI acceptance.

## Integrity, security and scale

- Full-tree Gitleaks scan passed after two findings were confirmed by recomputing their exact synthetic fixture SHA-256 values. The existing scanner configuration now excludes only those exact filename/digest matches; no file or arbitrary hash pattern is exempted. No claim of universal vulnerability absence is made.
- Dependency consistency, skill validation, JavaScript syntax, local documentation links and whitespace checks passed. No new third-party dependencies were introduced.
- A bounded probe inventoried and round-tripped 500 synthetic native files / 1,000 fields / 28,390 source bytes in 0.089 seconds. Static candidate validation has a separate smaller bound. Oversized engagements need complete domain waves; no silent truncation is permitted.
- Source, context, knowledge, candidate, policy, environment and remote-state changes invalidate their associated evidence. Scope, native execution, effective access, independent accuracy, AI behavior, business acceptance and release authority remain separate gates.
