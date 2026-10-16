# Evidence-aware authoring and qualification

Generate explicitly requested provisional code even when the catalogue or
business decisions are incomplete. Keep supported code, documentation, ERDs,
the dictionary, semantic candidates and `START_HERE.html` available for review.
These checks expose uncertainty; they do not supply authoring, execution or
deployment authority. Independent data and native validation still apply.

## One evidence contract per bounded batch

Use `schema_version: 1`, `kind: authoring_contract`, with:

- `mode`: `provisional` or `reviewed_candidate`, matching the stage plan.
- `bindings`: current `source_sha256`, `design_sha256`, `catalogue_sha256`.
  The catalogue hash is null when unavailable; never replace it with a guess.
- `models`: exact `id`, relative output `path` (null when unknown), `columns`
  and `depends_on` (null when unknown), plus optional `expressions` keyed by
  output column. Expected expressions come from source or an independently
  reviewed definition, not a copy of the candidate being checked.
- `assumptions`: stable `id`, affected `model_ids` and `fields`, category
  (`physical`, `business`, `security`, `definition`), status (`unresolved`,
  `proposed`, `resolved`), `required_check` and `evidence_refs`. A resolved label
  requires evidence; a reference alone does not authenticate human approval.
- `provenance`: occurrence-specific evidence described below.

Use declared task ownership to map model IDs to files. Do not infer identity
from coincidental filenames. Internal dependencies use designed model IDs;
external dependencies use `source:schema.table`, `ref:package.model` or
`table:qualified_relation`. A catalogue's existence does not verify physical
bindings; validate those against the target environment separately.

`record-task` accepts optional `authoring_contract`. It automatically checks
the batch and records a separate observation. Old callers need no new fields;
unmapped scope is reported as unknown. Failed, missing or unsupported checks
do not suppress requested draft files or rewrite their contents.

## Classify values by context

Use `authoring_provenance.scan_literals(root, paths, dialect)` for hash-only
occurrences. A provenance entry has `occurrence_id` and `classification`:
`technical`, `preserved`, `derived`, `proposed`, `unknown` or `redacted`.

- Technical constants are recognized in supported syntax contexts, such as
  `COUNT(1)` or date-truncation units. Calling a business value technical does
  not make it safe.
- Preserved values need exact source evidence: `path`, whole-file `sha256`,
  `span: {start, end}` (zero-based character offsets, end exclusive), `field`
  and `expression_sha256`. Matching text elsewhere is insufficient. Filter
  and projection context, reachable CTEs and CSV row context matter.
- Derived definitions compare normalized expressions. New business constants
  still need evidence. A matching author-supplied expression alone does not
  establish business validity or resolve provenance.
- Proposed, unknown and redacted values remain gaps. Never guess a redacted
  label or silently turn an assumption into a production seed. A host-reported
  decision reference remains an assertion until independently validated through
  the existing review and acceptance process.

The bounded slice covers SQL projections/filters, static dbt refs and sources,
CSV cells, and selected Omni SQL/filter scalars. It does not execute macros,
expand physical `SELECT *` without evidence, or claim complete handling of
arbitrary SQL, Jinja, YAML or every dialect. Unsupported paths remain in the
denominator. Simple CTE projections resolve; ambiguous aliases, set operations
and star modifiers remain gaps. Missing optional parsers produce `unsupported`.

## Recheck retained code

```sh
python scripts/guided_workflow.py check-task \
  --run /absolute/engagement --artifact-root /absolute/candidate \
  --document /absolute/check-request.json
```

The request is `{"schema_version":1,"task_id":"build-orders",
"observation_id":"orders-check-2"}` with optional `contract`. Existing outputs
must be unchanged. Their original generation run ID is retained and a new
observation is appended. Supply an explicit contract to resolve unknown file
mappings; a recheck cannot invent evidence. Historical provisional runs never
become reviewed generation merely because a later check passed.

Standalone CI uses the same checker:

```sh
python scripts/authoring_quality.py \
  --root /absolute/candidate --source-root /absolute/source \
  --contract /absolute/authoring-contract.json \
  --paths models/orders.sql --dialect snowflake \
  --output /absolute/new-authoring-report.json
```

Exit 0 means included static findings passed; exit 1 means failed, missing or
unsupported evidence; exit 2 means invalid input. None establishes production
accuracy. Reports pin files, contracts, checker code and source evidence.
Changed task definitions, targets or inputs stale observations. Python and
optional parser versions are included in the checker pin; native runtime
qualification remains separate.

## Review and release

The existing Validation panel shows reported status, provisional mode, scope,
separate check counts and open assumptions. Findings contain IDs and codes,
not raw source values. Full contracts and host receipts stay in private
engagement evidence. Export selection and audience rules still apply.
The panel does not replace the native/framework/data quality lanes.

Checks start in diagnostic mode. After qualifying the team's supported scope,
set `require_authoring_quality: true` in the **external runner policy** to require
complete passing authoring evidence for live `promote`. An artifact cannot
disable that policy. Leave it unset until coverage is qualified; unsupported
constructs must not be relabelled passed. Generation, packaging, development
and reviewed PR routes retain their existing behavior and controls.

Add optional `authoring: {contract_path, report_path, source_root}` to the
existing release `quality` reference. Preparation and protected promotion
recompute the report against exact selected implementation bytes, current
checker and target, and check the current design/source/catalogue scope. All
required implementation inputs stay in the denominator. Changed, forged,
omitted or provisional evidence cannot qualify this promotion path. Native
checks, independent reconciliation, access tests and signed authorization remain
separate requirements. Never describe unenforced diagnostics as an active gate.

## Repair sequence

Repair affected code or evidence, rerun deterministic checks, and refresh only
affected observations and dependent validation. Retain prior failures. Escalate
persistent interpretation errors with the exact source slice; ask SMEs to resolve
business definitions. Do not repeat broad reviews to compensate for missing
context. Use the [controlled model comparison](agent-benchmark.md) before changing
model defaults; telemetry is not an accuracy score.
