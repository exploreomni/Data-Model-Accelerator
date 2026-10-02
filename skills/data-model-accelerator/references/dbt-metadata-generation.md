# Generate reviewed dbt documentation

`scripts/generate_dbt_docs_yml.py` projects an approved dictionary v2 into dbt property YAML for every explicitly bound model, seed, snapshot, and source. It adds relation and column persistence defaults under `models.<project>.+persist_docs`; seeds and snapshots receive their corresponding defaults when present. Definitions use the shared `metadata_descriptions.py` formatter so native metadata and dbt use identical grain and units text.

This is a local, static generation step. It never runs dbt, Jinja, project macros, or SQL. A generated project and its ownership manifest are review artifacts, not deployment authority, native metadata coverage, or warehouse acceptance. Native parsing and manifest verification remain separate gates.

## Explicit binding contract

The bindings document has `schema_version: 1`, `kind: dbt_metadata_bindings`, the exact `project_name`, and a nonempty `resources` array. Bind every dictionary model and separate dictionary source exactly once, with every column exactly once. Names are reviewed dbt property names, not warehouse aliases or names inferred from dictionary IDs. For example:

```json
{
  "schema_version": 1,
  "kind": "dbt_metadata_bindings",
  "project_name": "analytics",
  "resources": [
    {
      "model_id": "model.orders",
      "resource_type": "model",
      "name": "orders",
      "property_path": "models/gold/_orders.yml",
      "config_path": ["gold"],
      "columns": [
        {"column_id": "column.orders.order_id", "name": "order_id"}
      ]
    },
    {
      "source_id": "source.erp.orders",
      "resource_type": "source",
      "source_name": "erp",
      "name": "orders",
      "property_path": "models/sources/_erp.yml",
      "columns": [
        {"column_id": "column.source.erp.orders.order_id", "name": "ORDER_ID"}
      ]
    }
  ]
}
```

Replace every example identifier with an existing dictionary ID and a reviewed dbt name. `config_path` is required for models, seeds, and snapshots and lists their exact hierarchy below the project configuration; an empty list selects the project level. `resource_type` is `model`, `seed`, `snapshot`, or `source`. Sources use `source_id` and `source_name` and have no `config_path`. Their records come from dictionary `sources`, not `models`, and source YAML never receives generated `persist_docs` settings.

Versioned models require an explicit integer or string `version` binding. Existing `defined_in`, aliases, versions, and column inheritance remain intact. Bind a distinct stable dictionary model ID for each documented version; ambiguous versions are refused. Property paths must be literal relative paths under a declared dbt model, seed, or snapshot path. A preexisting patch in another file is a conflict; the generator never duplicates it.

Resource and column descriptions default to `description_policy: dictionary`. Set `description_policy: preserve` on either binding only when the existing nonempty definition is the reviewed authority. This preserves hand-written text or a quoted `{{ doc(...) }}` reference and records an exception requiring later native resolution and comparison. Template-bearing metadata imported from the dictionary is refused instead of becoming executable dbt input. The generator adds its metadata under `config.meta.dma` at resource and column level, preserving other configuration and metadata.

## Preview, review, and apply

Use the repository's Python environment and its pinned generation dependency:

```sh
.venv/bin/python -m pip install -r skills/data-model-accelerator/scripts/requirements-metadata.txt
.venv/bin/python skills/data-model-accelerator/scripts/generate_dbt_docs_yml.py \
  --project /absolute/work/project \
  --dictionary /absolute/work/dictionary-v2.json \
  --bindings /absolute/work/dbt-bindings.json \
  --report /absolute/work/docs-preview.json
```

Review the complete `changes` (content and diff), `field_patch`, `conflicts`, and `exceptions` in the report. A conflict blocks all application. Record the exact `preview_sha256` after review, then apply to a new directory:

```sh
.venv/bin/python skills/data-model-accelerator/scripts/generate_dbt_docs_yml.py \
  --project /absolute/work/project \
  --dictionary /absolute/work/dictionary-v2.json \
  --bindings /absolute/work/dbt-bindings.json \
  --report /absolute/work/docs-apply.json \
  --apply --output /absolute/work/reviewed-project \
  --reviewed-preview-sha256 EXACT_REVIEWED_PREVIEW_SHA256
```

The output directory and report must not already exist. Both remain outside the input project. The input is preserved. The preview hash binds the project snapshot, dictionary, bindings, previous ownership manifest, YAML runtime, and proposed report; any drift requires another preview and review. It is a content pin, not an authenticated signature or deployment approval. If a filesystem failure interrupts copying, the incomplete destination is not a successful result and cannot be reused as an output path.

The new copy includes `.dma-docs-ownership.json`. On the next generation, explicitly provide that baseline:

```sh
.venv/bin/python skills/data-model-accelerator/scripts/generate_dbt_docs_yml.py \
  --project /absolute/work/reviewed-project \
  --dictionary /absolute/work/dictionary-v2.json \
  --bindings /absolute/work/dbt-bindings.json \
  --previous-manifest /absolute/work/reviewed-project/.dma-docs-ownership.json \
  --report /absolute/work/docs-next-preview.json
```

Unchanged generation returns `no_op` with no file differences. The three-way merge compares previously generated values, current YAML, and desired dictionary values. It updates owned fields only when current values match the baseline. Human changes, removed owned fields, moved property patches, and conflicting unowned values require review. Previously owned fields no longer projected are retained and surfaced, never automatically deleted.

## Preservation and coverage limits

The pinned `ruamel.yaml==0.18.16` round-trip loader preserves comments, anchors, quotes, map order, conventional indentation, and document markers. Tests, aliases, constraints, unrelated configuration, and existing explicit persistence overrides remain intact. Shared mutable aliases, duplicate YAML keys or resource patches, custom tags, directives, recursive aliases, malformed YAML, and unsupported structures produce a conservative review patch or a refused preview; they are not silently rewritten. Arbitrary whitespace is not a byte-level preservation promise for changed files. Unchanged files retain their exact bytes.

Existing `persist_docs: false` at project, folder, resource, or version level is preserved and reported as a coverage exception. Static configuration findings require native manifest confirmation, including model-local Jinja configuration and adapter support. Sources are documentation-only in this projection; native RAW comments require their separate owner-approved route. No static finding proves actual warehouse columns, permissions, tags, comments, or write success.

The generator operates on a bounded regular-file project copy: at most 5,000 files, 10 MiB per file, and 100 MiB total. Symlinks and credential-like files such as `profiles.yml` and `.env` are refused. `.git`, environments, caches, `target`, logs, and installed dbt packages are omitted. Supply credentials separately to any later authorized native validation. Do not regenerate a frozen handoff in place: review a new candidate and create fresh downstream fingerprints.

Python API:

```python
generate_project(project, dictionary, bindings, *, previous_manifest=None,
                 output=None, apply=False, reviewed_preview_sha256=None)
```

The API returns the complete preview report, plus `applied_to` after successful application. Invalid contracts raise `ValueError`; CLI refusal or conflicts return a nonzero exit code.
