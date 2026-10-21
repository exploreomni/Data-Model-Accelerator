# Periscope / Sisense for Cloud Data Teams source adapter

Research checked 2026-10-15. Adapter version 1 is an offline, bounded inventory of
a supplied CDT Git snapshot. It does not acquire live content, execute SQL/code,
expand templates, or establish migration parity. Fixtures are synthetic.

## Supported contract

The vendor's **unversioned CDT Git Configuration** is the contract; the integration
documentation describes dashboard/chart/view/snippet support beginning with its
2018 release. This is not a claim of compatibility with every historical release.
Sisense Fusion/ElastiCube/Live JSON exports are a different product surface and
are not accepted. [Git Integration](https://dtdocs.sisense.com/article/git-integration)

Supported relative paths are:

| Object | Settings | Additional source files |
| --- | --- | --- |
| Dashboard | `dashboards/<name>.<token>/<name>.yaml` | None |
| Chart | `dashboards/<dashboard>.<token>/<name>.<token>/<name>.yaml` | Same-stem `.sql`, `.py`, `.r` |
| View | `views/<name>/<name>.yaml` | Same-stem `.sql`, `.py`, `.r` |
| Snippet | `snippets/<name>/<name>.yaml` | Same-stem `.sql` |

Settings use `display_name`/`database_name` for charts, while views use
`Database Name`/`Code Language` and snippets use `Parameters`. Original YAML,
native settings, tokens, SQL, code, filter defaults and locations are retained.
Missing required fields, sidecars and unsupported keys create gaps. Encrypted
chart settings stay opaque. Dashboard declarations can omit inherited filters;
invalid snippet names can prevent Git synchronization. The top-level `.gitkeep`
markers are recognized. [Git Configuration](https://dtdocs.sisense.com/article/git-configuration)

Tokens are treated as native identifiers, separately from display names and
paths. Unsuffixed dashboard/chart directories are retained with a missing-ID gap;
they do not prove successful synchronization. Duplicate tokens are flagged.
Sisense's own operational article identifies the tokens as 32 alphanumeric
characters and notes that filter definitions are not under Git version control.
[Copying objects between Spaces](https://community.sisense.com/forum/cdt-44/topic/git-how-to-copy-site-objects-between-spaces-4312/?focus_post=10809)

`custom_modules/**/*.py` and `custom_modules/**/*.r` are preserved. The documented
Python `import` and R `periscope.source(...)` forms support static dependency
candidates; package availability, dynamic imports, resources and execution remain
unverified. No module is imported by the adapter.
[Custom Modules](https://dtdocs.sisense.com/article/custom-modules)

## Interpretation boundaries

- A connection label does not establish a SQL dialect. This adapter supplies
  `dialect=None` to the common SQL reader, retains exact text and emits
  `sql.dialect_unknown`. A separate verified connection/dialect mapping and
  version-bound compiled SQL are needed before structural SQL interpretation.
- Bracket occurrences are lexical candidates. They can refer to snippets,
  parameters, filters, views, formatters or SQL identifiers; even a name match is
  not proven executable lineage. Parameter substitution is never performed.
  [Parameterized SQL Snippets](https://dtdocs.sisense.com/article/parameterized-sql-snippets)
- Containment and configured-filter edges are declarations. Snippet/view and
  module-name matches remain `candidate`; missing or ambiguous targets remain
  `unresolved`. Cycles are not expanded, so they cannot trigger source execution.
- Raw Python/R bodies, undeclared behavior and unknown settings remain evidence.
  There is no dataframe lineage, package installation, R evaluation, SQL result
  comparison, filter inheritance resolution or effective-security validation.
- Git coverage does not establish all-Space inventory, exports of user/role
  permissions, row restrictions, database grants, sharing, source completeness,
  chart behavior or production acceptance.

Input limits come from the common source-adapter boundary. The adapter additionally
caps bracket candidates at 128 per SQL file, R references at 128 per file and
Python AST scanning at 10,000 nodes; truncation is an explicit gap. SQL and code
remain available in their original expressions when interpretation is bounded.

## Acquisition and API research

Supply an approved UTF-8 snapshot rooted at the documented directories, with its
Space/repository/revision captured by the caller. One repository maps to one
Space; `periscope/master` is the synchronized production branch. An existing
snapshot only needs repository read access. Establishing the vendor integration
is a separate administrator operation involving deploy-key write access and
webhooks; this adapter does not configure it or push to that branch.
[Connecting a Git Repository](https://dtdocs.sisense.com/article/connecting-a-git-repository)

The CDT administration API uses `https://app.periscopedata.com` with
`Http-X-Partner-Auth: <Site-Host:API-KEY>` and requires site/plan enablement. The
documented `GET /api/v1/dashboards` accepts `next_page_start`; its response exposes
`next_page_start`, counts and dashboard ID/name/description. That inventory is not
a chart/query definition export. Users use `GET /api/v2/users`, returning 100
records per page and a continuation value; roles use `GET /api/v1/roles` with
`next_page_start`. A future acquisition workflow must follow returned cursors,
retain page/count evidence and independently reconcile scope. It must not assume
that one page is complete or that these administrative endpoints establish
effective access. No API endpoint is called by this implementation.
[User and Role Management API](https://dtdocs.sisense.com/article/user-and-role-management-api-rbac)

The Render API is an add-on PDF-generation surface, using a POST to
`https://api.periscopedata.com/api/v1/screenshot_requests` with site/key header.
Its output and refresh behavior cannot replace the source definitions needed for
this inventory. It is excluded, including its returned resource URLs.
[Render API](https://dtdocs.sisense.com/article/render-api)

## Open-source research and reuse decision

| Candidate | Verified scope/license | Decision |
| --- | --- | --- |
| [Parsons CDT client](https://github.com/move-coop/parsons/blob/main/parsons/sisense/sisense.py) | Shared-dashboard publish/list/delete client; [Apache 2.0 with additional attribution NOTICE](https://github.com/move-coop/parsons/blob/main/LICENSE.md) | Not a Git parser; no code copied or dependency added. |
| [GitLab snowflake_spend](https://github.com/gitlabhq/snowflake_spend/tree/master/analysis/periscope_dashboards) | MIT project with dashboard SQL examples and image; queries include dbt compile-time references | Useful evidence of embedded template dependencies, not a full CDT export schema; no code/fixtures copied or executed. |
| [Sisense datamodels-demo](https://github.com/sisense/datamodels-demo) | MIT; Linux L8.0.2+ Datamodel REST API demonstrations | Different product/format; not reused for CDT. |

The implementation is original repository code using the common safe YAML loader
and standard-library static inspection. No third-party CDT parser or schema is
vendored, and no license claim is inferred from an unrelated package named
“Periscope.” Reassess a candidate's exact revision and license before future reuse.

## Verification and remaining evidence

`tests/test_source_periscope.py` checks stable snapshot output, native IDs,
declarations, candidate dependencies, filters, encryption, incomplete exports,
unknown dialect, malformed/duplicate/unsafe YAML, unknown formats, missing files,
ambiguous names, unsupported settings and static non-execution. This verifies the
documented synthetic subset only. Native export samples, export reconciliation,
runtime results, permission behavior and customer acceptance remain unverified.

## Offline discovery and extraction workflow

`scripts/periscope_workflow.py` performs bounded discovery **and invokes the
canonical adapter** on the selected readable evidence. It uses the existing
planner exclusions and descriptor-relative, hash-checked rereads. It does not
clone repositories, configure the vendor integration, execute source SQL/code,
contact APIs or change the source checkout. Output must be a new/empty directory
outside the input; existing output is never overwritten.

Automatic routing recognizes the existing tokenized dashboard marker and native
`views/<name>/<name>.yaml` or `snippets/<name>/<name>.yaml` settings with nested
`Settings` / `Metadata` / `Owner`. Views additionally require `Database Name` and
`Materialize View`. The marker is routing evidence, not successful parsing.
Generic SQL, a folder name or a connection label alone never establish CDT.
Nested monorepos retain the full evidence path and separate project roots.
For a known snapshot whose marker formatting is unsupported, select
`--source-profile periscope:RELATIVE_ROOT` (or `periscope:.`); this selects files
without broadening the native parser's accepted formats.

Callable interface:

```python
run_periscope_workflow(
    source_root, output_dir, source_profiles=(),
    source_identity=None, verified_connection_dialects=(), inspect_git=True,
    max_files=2000, max_file_bytes=1048576, max_total_bytes=33554432,
)
```

The returned record is also saved as `periscope-workflow.json` with
`kind: periscope_workflow` and `schema_version: 1`. It contains:

- `version`, `input`, `profiles`: installed component/profile fingerprints,
  available Git revisions and dirty state, inventory hash and explicit profiles.
- `extraction`: actual attempt status, project root, ordinary schema-v1 contract
  path/hash, profile binding, qualified-object map and `freshness_sha256` with
  its source-file/component/profile/namespace bindings. Existing orchestration
  can bind retained artifacts to these values through its freshness/cache
  controls; the helper does not add an approval or context-cache engine.
- `coverage.files` and `coverage.counts`: one row per known file, accounted as
  parsed, partial, unsupported, excluded or unreadable. `known_file_denominator`
  is exactly the sum of those counts; `selected_file_denominator` is the unique
  Periscope assignment count. Unsupported formats and extraction failures remain
  visible. Unread files never receive invented hashes.
- `coverage.excluded_subtrees`: excluded directories whose internal file counts
  remain unknown. `repository_file_denominator` is null when exclusions or
  incomplete enumeration prevent a full repository count. Limits, scan gaps and
  export-completeness uncertainty stay separate from parser coverage.
- `source_identity`, `connection_dialects`, `binding_review` and `gaps`: retained
  identity and interpretation evidence, without native-validation claims.

For cross-checkout identities, supply a caller record of
`{"repository_id":"stable-repository-id","space_ids":{"relative/cdt":"stable-space-id"}}`.
The namespace derives from repository plus Space, not the commit or display
name. Without both identifiers the fallback uses local root/project identity
and explicitly does not promise cross-checkout stability. Supplied identity is
not authenticated by this offline helper. Two roots claiming the same Space,
and duplicate tokens within a Space, remain conflicts; no object is discarded.
Canonical adapter object IDs are unchanged. Only native-token qualified IDs
promise token-based identity; view/snippet objects without native tokens retain
source-occurrence identities, which can change when their paths change.

`verified_connection_dialects` accepts records with `project_root`,
`connection_name`, `dialect` and a nonempty attributable `evidence` string.
These are separately recorded verification assertions, not authenticated native
receipts; conflicting mappings stay unresolved. They do not silently alter
canonical SQL parsing. Git alone does not prove a bracket token's native meaning
or parameter bindings, so this workflow performs **no snippet substitution** and
retains each bracket expression with
`periscope.binding_native_meaning_unverified`. A future bounded binding path
requires independently verified native meaning and parameter context; matching
names alone are insufficient. Code-dependent parity still requires captured
native outputs through the separately authorized comparison workflow.

`tests/test_periscope_workflow.py` uses synthetic fixtures for views/snippets-only
discovery, mixed monorepos, old markers, false positives, explicit fallback,
identity/dialect conflicts, missing/unsupported sidecars, coverage limits and
non-execution. This remains offline development evidence, not customer acceptance.
