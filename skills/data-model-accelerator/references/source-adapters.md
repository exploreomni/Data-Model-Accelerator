# Source adapter operation and qualification

Source adapters extract a declared subset of approved local artifacts. They do
not establish export completeness, native behavior, business acceptance or
deployment readiness. A warehouse target, SQL linter and source parser are
separate capabilities. Use `run_source_adapter.py --source NAME --capabilities`
for the implemented formats and limitations; read only the matching
`references/source-adapters/NAME.md` research/format contract.

## Coordinator workflow

1. Preserve the input repository and interview for source product/version,
   artifact format, selected scope, selected target and available catalogue.
   For ambiguous exports use an explicit source profile, never a vendor guessed
   from a SQL filename. Run the existing privacy/disclosure checks before sending
   any source expressions or metadata to a model. These parsers do not grant
   disclosure authority.
2. Inventory once with `plan_specialists.py --require-source-adapters`. This
   binds supported tasks to canonical extraction, so accidentally dropping its
   evidence from a worker response fails verification. Existing plans without
   this option keep their prior manual specialist workflow. For a supported assigned task, run
   `extract_specialist_task.py --plan RUN/dispatch-plan.json --task TASK_ID
   --output NEW_CANDIDATE.json` on the approved pinned local source. Create the
   destination directory outside the source repository first. The CLI does not
   execute the source, contact a vendor API or invoke an agent.
3. Retain the canonical `source_adapter_contract` and its source/component
   fingerprints. The result bridges objects, original expressions and unbound
   references into the existing specialist contract. The coordinator keeps full
   deterministic evidence locally and sends only necessary findings/excerpts in
   `agent_context.py` packets. Do not make every worker repeat parsing/research.
4. A source specialist interprets the bounded findings, preserving native IDs,
   expressions, gaps and security context. Review placement independently.
   Reconcile into the planned result location and run
   `verify_specialist_results.py RUN/dispatch-plan.json`. For results carrying
   an adapter contract this verifier re-extracts the pinned inputs, compares the
   contract and rejects dropped/changed canonical expressions or objects.
   Keep source names, native IDs, evidence and source details immutable; put
   proposed renames and interpretation in separate recommendations or target
   models. Preserve dependency references even when later evidence resolves them.
   The verifier retains its existing exit convention: `1` for errors **or**
   coverage gaps. Adapter qualification gaps keep `extraction_complete: false`
   even when `errors` is empty. Inspect those fields separately: partial evidence
   can inform scoped design and explicitly requested provisional code under the
   existing stage rules. It must not be relabeled complete or native-qualified.
5. Continue the existing design, warehouse implementation, Omni, validation and
   package stages. A successful structural parse is not automatic upstream
   placement. Keep provisional generation available when requested while
   retaining unresolved physical bindings and release holds.

For standalone extraction use:

```sh
python scripts/run_source_adapter.py /absolute/approved-snapshot \
  --source bigquery --output /absolute/private-analysis/bigquery.json
```

Install pinned optional parser dependencies with
`scripts/requirements-source-adapters.txt`. Existing Hex/Power BI schema pins
and explicit schema setup still apply. No downloads occur during parsing.
The adapter CLI emits value-free counts; its JSON includes source expressions
and must remain in the approved retention boundary. The collector excludes
credential filenames, binary files, symlinks and generated/vendor directories;
all omissions remain visible. Limits are 512 text files, 8 MiB per file and
32 MiB total, with at most 48 path components. Split larger scopes along coherent project/dependency boundaries;
never silently truncate or treat an excerpt as a complete asset.

## Common evidence contract

`source_adapter_result` v1 records the source, adapter/component version,
per-file byte hashes and coverage, objects, expressions, dependencies and gaps.
Each record has a source path, locator and byte hash. Expressions distinguish
original text from structural derivatives. Declarations of keys, relationships
or permissions are evidence to validate, not proof of uniqueness or enforcement.

File coverage is `parsed` (the declared structural subset), `partial`, or
`unsupported`. A recorded gap makes that file partial. Every supplied file is
accounted for, including files that the adapter cannot interpret. Export
completeness remains `not_established`; native validation remains `not_run`.
Missing dependencies remain unresolved. SQL CTE aliases are not physical table
dependencies; dynamic relations, unsupported statements and unbound wildcards
must retain explicit gaps.

## Targeted specialist ownership

Each tool has one format contract and adapter owner. New research uses official
format/language documentation, API acquisition contracts, open-source candidate
code/licenses, and attributable technical articles. Articles identify cases to
test; they do not override primary contracts. Review API export omissions,
pagination, snapshot consistency, permissions, release labels and deprecations.
Decide reuse/wrap/extend/build/defer with a qualitative effort rating, supported
versions and concrete exclusions. Do not copy code without preserving its
license obligations or add a vendor runtime merely to inventory source files.

Default to two active tool specialists. Each gets one tool's contract, assigned
files and dependent shared interfaces, not the full conversation or every
platform manual. One integration owner controls shared contracts and routing.
Shared SQL parsing research is reused; it does not replace native expression
handling for DAX, LookML, Tableau, Magic ETL or WebFOCUS.

Re-use results only when the exact input bytes, source/format scope, component
fingerprint and applicable decisions remain unchanged. The component hash
includes implementation and installed parser versions. Re-extract changed
sources and review their affected dependency closure; do not re-label old
results with a new hash. Cached research needs refresh when the format/API,
dependency version, deprecation status or relevant security evidence changes.

## Acceptance and capability claims

Each adapter needs independently specified positive and negative fixtures:
object/column identity, source expressions, joins/filter order/grain, null and
date behavior where interpreted, access declarations, unresolved dependencies,
malformed input and unsupported constructs. Generic shared tests protect path,
loader, logging, source-integrity and downstream handoff boundaries. Preserve
the existing fixture/native validation lanes; passing these tests does not
qualify a live tenant or warehouse. Do not report lineage coverage percentages
without an independently established denominator.

Acquisition is currently `supplied_exports`: operator-captured Git, definition
or metadata snapshots. References describe API research, not implemented live
connectors. A future acquisition adapter needs its own qualified API/version,
least-privilege operation scope, pagination/revision receipts, bounded retries,
credential handling and export-completeness checks. It must not execute reports
or workloads as a hidden side effect of inventory.
