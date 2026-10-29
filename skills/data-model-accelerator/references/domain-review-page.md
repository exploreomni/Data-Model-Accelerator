# Domain review page

A domain review hands one domain's data model to its reviewers: the medallion pipeline
(bronze → silver → gold), the semantic layer built on the gold tables, the legacy models and
dashboards it replaces, decisions, validation and open items. Every domain review opens on the
same `START_HERE.html` and uses the same folder layout, so reviewers always know where to look.

`scripts/domain_review_page.py` owns the page and the layout. The template lives in
`assets/domain-review/` and contains no domain-specific text: every title, count, area,
reading-order step and note comes from the embedded page data.

## Folder layout

Write each review into a new version folder; an existing folder is never overwritten.

```text
<Domain>/v<N>/
  START_HERE.html          the review page (offline, self-contained)
  MANIFEST.csv             every file with its size and SHA-256
  01_review/
    START_HERE.md          the short written version: numbers, areas, reading order, not done yet
    erd/<area>.mmd         one Mermaid ER diagram per subject area
  02_dbt/                  warehouse code at the paths it takes in the target project
  03_omni/                 semantic-layer files (views, topics, relationships)
  04_docs/                 design documents, registers, model files, validation evidence
```

## Tabs

| Tab | Content |
|---|---|
| Overview | Title and subtitle, scope and stack, candidate banner, headline cards (models by layer and disposition, code files, semantic topics, legacy coverage, decisions, dashboards), repositories, numbered reading order, dashboards with status, tile counts, topics and reasons, and "Not done yet". |
| Data model | Subject-area pills, each with three views: the pipeline (bronze, silver, gold columns), gold relationships (facts → dimensions → related tables) and semantic topics (topic → base view → joined views). Click a table or topic for its inspector. |
| Code & files | Where the files drop in, source tables to add, placeholders to replace (grouped, with file counts) and a searchable file browser. |
| Decisions | Every decision with area, question, options, assumed option and answered, assumed or open status. |
| Legacy coverage | Every legacy model: covered, partially covered, retire candidate, out of domain or unresolved, with targets and topics. |
| Data dictionary | Every column of every model, searchable by layer. |
| Validation | Static file checks, remaining unknowns and recorded checks with their real status. |
| Open items | Open questions, unverified checks and unresolved legacy models, with who answers and what the candidate does meanwhile. |

## Page data

The page embeds one JSON object (`kind: domain_review_page`, `schema_version: 1`).
`normalise` validates it and derives every count, so headline cards always agree with the
tables. Main fields:

| Field | Shape |
|---|---|
| `meta` | `title`, `domain` (key used to mark other domains' tables as shared interfaces), optional `domain_label`, `subtitle`, `scope_label`, `facts`, `banner`, `brand`, `repositories` (`role`, `name`, hex `commit` or null, hex `fingerprint` or null), `code_target` (`package_path`, `project_path`), `semantic_target` (`connection`, `note`), `access_note` |
| `models` | `id`, `layer`, `domain`, `disp` (`create`, `extend`, `reuse`), `cols` (`[name, type, PK/FK/"", description]`), `dep`, optional `grain`, `desc`, `src`, `sec`, `code`, `source_path`, `area`, `existing` |
| `rels` | Gold joins: `from`, `to`, `card`, `key`, `basis` (`review`, `declared test`, `key name match`) |
| `areas` | `id`, `name`, `gold`, optional `shared`; `pipeline` defaults to the gold tables plus their non-gold ancestors and must contain every gold table; `erd` defaults to the gold tables plus their join partners |
| `topics` | `topic`, `label`, `base`, `area`, `joins` (`from`, `to`, `depth`, `card`, `on`), `views`, `fields`, `path`, `view_files` |
| `files` | `path` (under `02_dbt/` or `03_omni/`), `status` (`new`, `changed`), `content` |
| `decisions` | `id`, `area`, `q`, `opts`, `assumed`, `status`, `detail`, `models` |
| `legacy` | `legacy`, `status`, `targets` (required unless out of domain or unresolved), `topics`, `cross_topics`, `note`, `source`, `domain` |
| `dashboards` | `asset_id`, `asset_type`, `title`, `status` (`served`, `partly_served`, `not_served`), `topics`, optional tile counts, `reason`, `scope_reason` |
| `static`, `checks`, `remaining`, `open`, `apply` | Static file checks, recorded checks, unknowns, open items and apply notes (`new_sources`, `placeholders`) |
| `reading_order`, `not_done` | Optional; defaults are generated from the decisions, areas and remaining items |

## Build a review

1. Project the page data from the checked review and its registered artifacts:

   ```sh
   python scripts/domain_review_page.py project --review review.json --artifacts <artifact root> \
     --path-map '{"dbt/": "02_dbt/", "omni/": "03_omni/model/"}' --changed changed.txt \
     --overlay overlay.json --known-models base_models.txt --domain <domain> --output page.json
   ```

   `project` reads the review contract (`models`, `relationships`, `changes` or `legacy_coverage`,
   `decisions`, `validation`, `assets`, `review_meta`, `subject_areas`) and the packaged files. A
   semantic view binds to a model only through its declared `table_name`; an unbound view keeps its
   own name and stays visible. Gold relationships combine, in this order, the joins recorded in the
   review, dbt relationship tests declared in the packaged schema files, and foreign keys whose
   `<entity>_fk` name matches exactly one other gold table's `<entity>_pk`; the first source wins
   for each foreign key and the page shows each join's basis on hover. Pass `--no-key-inference`
   when the warehouse does not follow the `_fk`/`_pk` naming convention. Every dashboard needs a coverage status (`served`, `partly_served`,
   `not_served` or `out_of_scope`), so none can drop out silently. Artifacts must still match their
   registered SHA-256. The overlay carries authored fields the review does not hold, such as `meta`,
   `areas`, per-dashboard tile counts and reasons, `remaining` and extra `open` items. Never invent
   owners or other values in it: an absent owner is shown as "Not assigned".
2. Package it into a new version folder, with the design documents copied into `04_docs/`:

   ```sh
   python scripts/domain_review_page.py package --data page.json --docs <docs folder> --output <Domain>/v<N>
   python scripts/domain_review_page.py verify <Domain>/v<N>
   ```

   Packaging scans every file with the disclosure scanner (text formats it has no parser for are
   scanned as plain text) and stops on a finding. `verify` checks every file against
   `MANIFEST.csv` and re-validates the page.

## Checks

`check_page` requires the offline Content-Security-Policy, exactly one data block that passes the
contract, embedded counts equal to the counts recomputed from the data, no external resources and
no unreplaced template tokens. Static file checks prove syntax and reference closure only; they do
not establish a build, warehouse execution, semantic import or approval.
