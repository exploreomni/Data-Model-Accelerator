# Actual run report

## Outcome

Candidate generation completed for maintenance and energy. Each domain has two bronze, two silver and one gold model. Maintenance preaggregates parts by work order before the left join; energy uses a unique meter lookup while retaining reading grain. Status, dates, tenant and zone remain available for downstream filters.

| Check | Maintenance | Energy | Evidence scope |
|---|---:|---:|---|
| Exact input byte hashes | 4/4 unchanged | 4/4 unchanged | Supplied manifest only |
| Local model projections executed | 5/5 | 5/5 | DuckDB simulation of explicitly rendered SELECTs |
| Native Omni static contract | Passed | Passed | Physical bindings are synthetic plans |
| Declared SQL lint coverage | 20/20 files, 6/6 units | 20/20 files, 6/6 units | Candidate SELECTs, templates/configs, not native materializations |
| Source tiles and filters retained | 3 tiles, 1 filter | 3 tiles, 1 filter | Supplied dashboard JSON only |
| Independent source coverage | Unknown | Unknown | No separate inventory or authenticated API capture |
| AI context | Incomplete, 1 definition withheld | Incomplete, 1 definition withheld | Unknown classification and unapproved disclosure policy |
| dbt metadata projection after helper fix | Conflicted, 7 unapproved resources | Conflicted, 7 unapproved resources | Correct review gate; no apply |
| Catalogue verification | Incomplete | Incomplete | Missing native capture; external snapshot references |
| Native warehouse/dbt/Omni execution | Not run | Not run | No network, credentials or deployment |

Local observed dashboard results are maintenance total 55 (20 and 35 by date), with open work retained at work cost 20; energy total 12, north/date slice 4 and north across dates 10. These observations are not an independently authored baseline. See each `local-checks-final.json` for final SQL byte pins, executed projections and slice queries. Important conclusion confidence: High for the observed local outcomes and declared static scope; no native or business-acceptance conclusion is supported.

## Actual tools and versions

The requested existing Python environment was used; its absolute host location is retained only in private execution evidence. `runtime.json` records Python 3.12.14, SQLFluff 4.3.0, PyYAML 6.0.3, sqlglot 30.18.0, DuckDB 1.5.5, dbt-core 1.12.4 and ruamel.yaml 0.18.16. No dependencies were installed and dbt itself was not executed.

Executed local command forms, from the repository root (`$PYTHON` denotes that already-provisioned interpreter; `$DOMAIN` was maintenance, then energy):

```sh
$PYTHON validation/omni-privacy-repair/blind-generated/generate_pilot.py
$PYTHON skills/data-model-accelerator/scripts/lint_delivery.py \
  --root validation/omni-privacy-repair/blind-generated/$DOMAIN/implementation \
  --manifest validation/omni-privacy-repair/blind-generated/$DOMAIN/lint-manifest.json \
  --target validation/omni-privacy-repair/blind-generated/$DOMAIN/lint-target.json \
  --python "$PYTHON" --output <new private lint receipt>
$PYTHON skills/data-model-accelerator/scripts/generate_dbt_docs_yml.py \
  --project validation/omni-privacy-repair/blind-generated/$DOMAIN/implementation/dbt \
  --dictionary validation/omni-privacy-repair/blind-generated/$DOMAIN/dictionary-v2.json \
  --bindings validation/omni-privacy-repair/blind-generated/$DOMAIN/dbt-doc-bindings.json \
  --report validation/omni-privacy-repair/blind-generated/$DOMAIN/dbt-doc-after-helper-fix.json
$PYTHON validation/omni-privacy-repair/blind-generated/check_final.py
```

The authoring script calls `raw_csv_source.inspect_csv`, `data_dictionary_v2.validate_dictionary`, `generate_omni_model.generate_model` and `write_candidate`, `looker_source.parse_dashboard` (twice to check determinism), `omni_dashboard.template`, `omni_ai_context.build_context`/`write_context`, `generate_dbt_docs_yml.generate_project`, `guided_workflow.start_engagement` and `lint_delivery.scaffold_manifest`. A separate local invocation called `verify_catalogue.verify`. Final checks use `omni_contract.check_model` and `sensitive_data.scan_bytes`. No helper invoked a live service.

A two-attempt generation history is retained privately. The first stopped at the dbt documentation helper bug below; the second produced both domains. Each lint was run twice: first failure, then one bounded repair. Scripts are auditable authoring/check records; rerunning the authoring script against existing domain directories intentionally fails rather than overwriting the candidate. They assume the repository-relative skill/helper paths and original blind input layout, not a standalone installed package.

## Helper findings and retained boundaries

1. **Ordinary YAML list rejection, repaired by parent:** the first metadata preview rejected literal `model-paths` as “Templated/nonliteral resource paths require manual review.” The round-trip loader returns a list subclass, while the helper used exact `type(...) is list`. After the parent repair, both unchanged candidate projects reached the actual business review gate: seven “Resource description is not approved” conflicts each. No workaround, dictionary approval, metadata apply or persistence write was used. `FIRST_ATTEMPT.md` and the before/after preview reports preserve the distinction.
2. **Generator review enum:** Omni generation requires `review.status: approved`. The synthetic review record states that this is only a local exercise pin, not actual human approval or native evidence. All manifests retain unauthenticated review authority, `native_verified: false` and `deployment_authorized: false`.
3. **Dashboard template requires a UUID:** the worklist uses `00000000-0000-4000-8000-000000000000` solely as an explicit synthetic placeholder. It is not an observed model ID. Every tile, filter and behavior facet remains manual; no qualified native layout/control grammar is invented. Energy intake requires interactive north/zone filtering, but the source JSON has no Zone control; this is explicitly identified as a manual target enhancement.
4. **Catalogue grounding is incomplete:** supplied CSV headers/counts are observed synthetic evidence; planned physical namespaces/types are not native observations. The catalogue verifier reports a missing capture timestamp and rejects references outside the catalogue folder. The original inputs were kept in place rather than moved or given a fabricated capture timestamp. Static context binding can pass without native grounding, so these evidence lanes remain separate.
5. **Lint findings:** maintenance needed a blank line after its CTE. Energy preserves the source field `zone` under a narrow RF04 convention exception with rationale. Both final declared lint scopes pass. Native adapter materialization SQL, generated generic-test SQL and warehouse execution are not included in the observed scope.
6. **Visual QA limitation:** connected SVG and editable Mermaid were generated from the model inventory. The local Quick Look rendering attempt failed during sandbox initialization. XML and layout construction were checked, but pixel-level SVG visual inspection is pending; no visual fidelity acceptance is claimed.

All per-domain bounded content scans were clear; this is not DLP certification or destination disclosure approval. Privacy classifications remain UNKNOWN, definitions proposed, metadata persistence false and owners/SLAs/retention/CDC/currency or tariff decisions unresolved. SUM on empty populations remains NULL; no arbitrary missing-measure default was introduced.

## Next review

Use the independent evaluator’s frozen expectations and counterfactual data to assess formulas, row grain and missing-row behavior. Then review actual physical destinations, source types, key guarantees, privacy/access policies and unresolved definitions before any separately authorized target validation. Native dashboard creation, native compile/query/access proof, metadata persistence and business acceptance remain pending.
