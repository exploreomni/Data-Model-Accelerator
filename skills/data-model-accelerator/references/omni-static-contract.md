# Omni static contract and explicit generation

Contract: `omni-static-v2-2026-10-05`. This is a bounded local checker and candidate generator. A static pass does **not** establish native compilation, query parity, join cardinality, effective access, authenticated approval, safe disclosure or deployment readiness. Those are separate evidence lanes.

Use the pinned PyYAML and sqlglot versions in `requirements-lint.txt`. Missing runtimes produce unsupported checks; a skipped test is not qualification. No SQL, source instructions, URLs or macros are executed by these modules.

## Interfaces

`omni_contract.check_model(files, context=None)` takes an exact dictionary of relative native paths to YAML text. Supported path forms are `model`, `relationships`, `name.view`, `name.query.view`, `name.topic` and those names with `.yaml` or `.yml` appended. Nested relative directories are allowed. The report includes:

- `status`: `passed`, `failed` or `unsupported`. A definite error takes precedence over unsupported coverage.
- `candidate_sha256`: canonical JSON SHA256 of the **complete exact files mapping**, including paths and text.
- `context_sha256`: a separate canonical JSON hash of the supplied context.
- `findings`: `path`, structural `location`, stable `code`, and `severity`. SQL, literals and parser exception text are omitted.
- `topic_scopes`: effective view identities, query/AI selections and selector origins; selections are not effective permissions.
- `native_verified: false` and `security_verified: false`.

Canonical JSON uses sorted keys, compact separators, ASCII escaping and finite numbers only. The report never authenticates its own provenance. Store it with the candidate and bind the native observation to both hashes.

The CLI accepts a JSON files map and optional context:

```sh
python skills/data-model-accelerator/scripts/omni_contract.py \
  --files candidate-files.json --context omni-context.json
```

The command returns zero only for a static pass. With no context, YAML and structural checks can still run, but catalogue and dependency qualification cannot pass.

## Context v1

All top-level keys shown below are required; unsupported context versions fail. This context contains metadata only and must pass the engagement's disclosure policy before leaving its approved boundary.

```json
{
  "schema_version": 1,
  "kind": "omni_model_context",
  "warehouse": "snowflake",
  "environment": "development",
  "catalogue_sha256": "<canonical catalogue artifact SHA256>",
  "bindings": {
    "events": {
      "namespace": {"database": "ANALYTICS", "schema": "GOLD", "table": "EVENTS"},
      "columns": {"ID": "number", "RECORDED_AT": "timestamp", "VALUE": "number"},
      "evidence_sha256": "<catalogue observation artifact SHA256>"
    }
  },
  "inherited_views": {},
  "default_catalog": null,
  "user_attributes": [],
  "access_grants": []
}
```

`columns` keys are exact physical names, not normalized semantic names. Values are `string`, `number`, `date`, `timestamp`, `boolean` or `unknown`. Preserve quoted case. Snowflake **unquoted SQL** identifiers use Snowflake's uppercase resolution; quoted SQL keeps exact case. Context namespace strings themselves are never case-normalized. Other dialects use exact supplied physical names in this bounded implementation; broader case behavior requires native qualification.

| Warehouse | Required namespace keys | Native view projection |
| --- | --- | --- |
| Snowflake, Redshift, MotherDuck | `database`, `schema`, `table` | `catalog`, `schema`, `table_name` |
| Databricks | `catalog`, `schema`, `table` | `catalog`, `schema`, `table_name` |
| BigQuery | `project`, `dataset`, `table` | `catalog`, `schema`, `table_name` |
| ClickHouse | `database`, `table` | `catalog`, `table_name` |

This matrix qualifies local mapping and expression checks only. It is not a claim that every listed warehouse/Omni connection combination has been deployed or observed in a tenant.

An omitted native `catalog` can resolve through an explicitly supplied connection default:

```json
{"value": "ANALYTICS", "verified": true, "evidence_sha256": "<observation SHA256>"}
```

The context calls this default verified only as an evidence-backed **declaration**. The checker does not authenticate the observation. `default_catalog` is not emitted as an invented native model parameter. A conflicting or unverified default cannot satisfy physical binding resolution. See [view catalog](https://docs.omni.co/modeling/views/parameters/catalog).

Inherited definitions use `inherited_views[view_name] = {"definition": <resolved native view mapping>, "sha256": <canonical definition hash>}`. A same-name candidate view is merged over that resolved definition. Explicit single-parent `extends: [base_view]` is also resolved; cycles fail. Omitted SQL is allowed when a field resolves through the supplied base or a matching physical schema column. A new unbound alias without SQL is unsupported, not invented. Multiple inheritance is currently unsupported. See [view inheritance](https://docs.omni.co/modeling/views/parameters/extends).

`user_attributes` and `access_grants` are lists of available names. Resolving a name checks a dependency only: it does not establish attribute values, provisioning, default behavior or effective authorization. Native persona and access tests remain required.

## Qualified local checks

- Strict YAML: duplicate/non-string mapping keys, multiple documents, invalid shapes and non-JSON values fail. Anchors/aliases are unsupported. Inputs are bounded by file, byte, structure and depth limits.
- Object/parameter placement and supported types; unfamiliar parameters produce unsupported coverage instead of being silently dropped.
- Dimensions, measures, field SQL references, dependency cycles and physical catalogue columns. Unresolved references fail. Templated SQL, statements, unknown SQL functions and physically qualified expressions outside the declared view remain unsupported.
- `aggregate_type` names, percentile bounds, custom deduplication keys and nested aggregation. Compound measure SQL remains explicit. See [aggregate types](https://docs.omni.co/modeling/measures/parameters/aggregate-type).
- Bracket time references such as `events.recorded_at[date]`, in block lists or quoted flow lists. Documented uppercase timeframe forms are accepted case-insensitively; `time` is invalid. Known numeric physical columns cannot acquire temporal behavior through configuration. Derived temporal types not established by the bounded checker remain unresolved. See [timeframes](https://docs.omni.co/modeling/dimensions/parameters/timeframes).
- Title-case weekdays on dimensions, topics and models; a known non-temporal dimension cannot use temporal overrides. See [dimension weekday](https://docs.omni.co/modeling/dimensions/parameters/week-start-day) and [model weekday](https://docs.omni.co/modeling/models/week-start-day).
- String formats, including named and Excel-style forms such as `0.0%`, without a fabricated short allowlist. The checker verifies the string boundary, not every custom-format grammar or tenant constant. Conditional and templated formats remain unsupported. See [format](https://docs.omni.co/modeling/dimensions/parameters/format).
- Global and topic relationships, explicit nested join trees, field inclusion and basic access-filter shape/dependencies. Join declarations do not prove cardinality or prevent fanout without data tests. Single-parent view aliases, topic-local view overrides, topic inheritance and explicit paths are supported within the bounded contract. Implicit join expansion, multiple inheritance, relationship-level alias forms and delta joins remain unsupported. See [joins](https://docs.omni.co/modeling/topics/parameters/joins), [relationships](https://docs.omni.co/modeling/topics/parameters/relationships), and [access filters](https://docs.omni.co/modeling/topics/parameters/access-filters).

Local measure filters support typed scalar/list `is` and `not`, numeric comparisons and bounded text operators on resolved dimensions. Supported selectors resolve precedence across all views, a view, tags and exact fields; query selections and AI awareness are distinct. Explicit query exclusions cannot remove required dependencies. An implicit whitelist with omitted transitive operands retains a native-eligibility gap instead of silently expanding the whitelist.

Native modeled and conservative read-only SQL query views have output and population lineage. Use the exact supported forms and limits in [the query-view contract](omni-modeler-query-views.md); no physical binding may be invented for a query view. Fiscal offsets and supported temporal metadata are checked locally, not executed across every timezone/calendar.

Other unsupported areas include arbitrary SQL and query controls, materialization operations, complex/dynamic measure filters, composite-topic generation, custom calendars, effective policy enforcement and renderer behavior. Unsupported does not mean invalid in Omni. Retain original content through the inventory and route it to qualified native review.

## Generator specification v1, static contract v2

`generate_omni_model.generate_model(spec, context, model_version, placement_version)` returns `files`, `check` and `manifest`. It generates only explicit mappings. The supplied accepted model and placement artifacts remain arbitrary JSON contracts; their exact hashes are pinned. Their internal business approval is not inferred by this module.

Required specification fields:

```json
{
  "schema_version": 1,
  "kind": "omni_generation_spec",
  "contract_version": "omni-static-v2-2026-10-05",
  "review": {
    "status": "approved",
    "reference": "<review evidence reference>",
    "evidence_sha256": "<review evidence SHA256>",
    "spec_sha256": "<canonical hash of this object excluding review>"
  },
  "pins": {
    "model_sha256": "<exact model_version hash>",
    "placement_sha256": "<exact placement_version hash>",
    "context_sha256": "<exact context hash>",
    "catalogue_sha256": "<context catalogue hash>"
  },
  "model": {"week_start_day": "Monday"},
  "views": {
    "events": {
      "kind": "physical",
      "definition": {"dimensions": {"id": {"primary_key": true}}},
      "field_mappings": {
        "id": {"kind": "physical", "column": "ID", "source_refs": ["model#/models/0/columns/0"]}
      }
    }
  },
  "topics": {"activity": {"base_view": "events", "joins": {}, "fields": ["events.id"]}},
  "relationships": []
}
```

All hash placeholders must be actual 64-character lowercase hexadecimal hashes. The example pointer is illustrative and must exist in the supplied model artifact.

Every emitted dimension and measure requires exactly one `field_mappings` entry. Extra mappings and unmapped fields fail:

- `physical`: dimension, exact catalogue `column`, and `source_refs`. SQL is generated as a dialect-quoted identifier when omitted. Supplied physical SQL must resolve to that exact column.
- `derived`: explicit SQL and `source_refs`; no physical column key.
- `aggregate`: explicit measure SQL, or an explicitly requested count; no implicit business metric.
- `inherited`: a supplied hash-bound base field and `source_refs`. Presentation overrides can retain omitted SQL.
- `query_output`: exact derived output alias and `source_refs`; dimension SQL uses dialect-quoted output identity and must match that output.

View kinds are `physical`, `inherited_override`, `query_view` and `sql_view`. Query kinds resolve documented semantic dependencies and output identities rather than receiving fake catalogue bindings. Namespace fields for physical views come from the pinned catalogue binding; conflicting supplied names fail. Topic definitions, relationships, security settings, formats and AI context remain exactly as reviewed. No default tenant policies or business descriptions are invented.

Source references use local JSON Pointers beginning `model#/` or `placement#/`. They must resolve against the pinned artifacts; arbitrary names, external URLs and missing pointers fail. Pointer existence is not proof of formula equivalence or lineage correctness, which still requires reviewed placement and parity evidence.

Changing any spec content after its declared review changes the review subject hash. Changing the supplied model, placement, context or catalogue invalidates its pins. Review hashes establish consistency, not reviewer identity.

```sh
python skills/data-model-accelerator/scripts/generate_omni_model.py \
  --spec reviewed-omni-spec.json --context omni-context.json \
  --model-version accepted-model.json --placement-version accepted-placement.json \
  --output private-omni-candidate
```

The CLI writes a **new** private directory only when the local checker passes. It creates the directory with mode `0700` and files with `0600`, never overwrites an existing directory, and removes run-owned partial output after a write failure. Native files, `GENERATION_MANIFEST.json` and `STATIC_CHECK.json` are included. Diagnostics and stdout omit raw SQL. The manifest always records `native_verified: false`, `deployment_authorized: false` and unauthenticated review authority. Run privacy/disclosure gates before sharing these files, then the authorized native-validation and acceptance workflow before deployment.

## Contract migration

Existing v1 generation specs and static receipts must be regenerated and reviewed against v2; changing only a version label does not carry forward their qualification. Context and specification schema numbers remain 1 where their shapes are unchanged. The exact `contract_version`, content hashes and review subject bind the new behavior. Historical evidence remains attached to its original version.
