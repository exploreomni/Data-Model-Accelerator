# Qualify model choices with controlled evidence

Keep the configured host model and effort unless the operator explicitly selects
another setting or a reviewed evaluation supports a scoped change. Never make a
smaller model the default because one run was inexpensive or looked plausible.
Accuracy depends on evidence, task difficulty, checks and repair work as well as
the model. A more expensive model cannot reconstruct missing business facts.

## Evaluation protocol

1. Freeze a representative, sanitized suite before inspecting candidate outputs.
   An independent reviewer owns the authoring contracts and expected findings.
   Include routine SQL, multi-CTE logic, missing catalogue, redacted definitions,
   Omni measures/filters and incremental repairs. Add the team's difficult join,
   history, access and metric cases; a tiny synthetic suite is insufficient to
   justify a production routing change.
2. Give each variant the same case packet and output contract. Record actual
   requested/observed model, effort and context mode through the host observation
   helper. If settings or packet bytes differ, disclose the difference; do not
   present it as an isolated model comparison. Keep the default as the control.
3. Retain every attempt, including failed outputs and repairs. Use separate
   candidate roots. Do not alter expected definitions to match a candidate.
   Preserve unknown inputs: correct abstention or a clearly provisional output
   can be the expected result; invented values cannot count as success.
4. Run `agent_benchmark.compare(suite, runs)`. The helper rechecks current files
   against the frozen contracts rather than trusting supplied pass labels.
   Every variant must include every case. Bind the run collection to the suite's
   canonical JSON hash; pin each contract, selected source file and packet.
5. Review first-attempt and final results, coverage gaps, repair counts and host
   telemetry together. Validate high-risk semantics against independent native
   data expectations separately. A static rubric match is not business accuracy.

The suite has `schema_version: 1`, `kind: agent_benchmark_suite`, and `cases`.
Each case declares `id`, `packet_sha256`, `contract_path`, `contract_sha256`,
`source_root`, `source_files` (relative path to hash), `dialect`, `paths`,
`required_findings` (code/status/model_id triples), and `allowed_statuses`.
Keep expected gaps explicit rather than allowing every possible status.

The run document has `schema_version: 1`, `kind: agent_benchmark_runs`,
`suite_sha256`, and at least two `variants`. A variant has `id` and `cases`;
each case has `id` and ordered `attempts`. Each attempt points to `artifact_root`
and an `execution` object with `packet_dir` and the host observation `request`.
The host runs the actual agents; this helper never calls a model provider.

```sh
python scripts/agent_benchmark.py --suite /absolute/frozen-suite.json \
  --runs /absolute/host-runs.json --output /absolute/new-comparison.json
```

Retain a separate candidate snapshot for every attempt. The evaluator cannot
reconstruct overwritten historical outputs or authenticate host-run assertions.

## Interpretation and spend

The report leaves model defaults unchanged and selects no winner. It counts
attempts and repairs and retains attributed host observations. Missing model
identity or usage stays unknown. Token categories stay separate because host
definitions may overlap; do not add cached and uncached figures into a guessed
bill. Actual session cost belongs to the host or provider's usage reporting.
Account-wide monthly changes do not establish the cost of an individual run.

Use the smallest complete dependency scope, reuse unchanged extraction, and
repair only affected artifacts. Those optimizations are available without a
model downgrade. Escalate a bounded task when evidence is adequate but a material
error persists; retain the original failed attempt. When the missing ingredient
is a business decision, ask for that decision instead of running an unlimited
sequence of stronger models.

Repository fixtures exercise the evaluator and its failure controls. They are
not a paid model A/B trial, a measured savings claim or qualification of any
specific model family. Re-run controlled host trials before changing routing.
