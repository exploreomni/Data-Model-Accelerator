# Running the Omni specialist

Use this contract when Omni is the semantic target or an existing Omni model is
being assessed. Read `omni-modeler.md` for the modeling role and load the relevant
knowledge modules, not every reference. Source specialists still own source
extraction; independent QA and SMEs still own acceptance.

## Prepare and invoke

`plan_specialists.py --semantic-target omni --warehouse snowflake` adds an explicit
target request. Omni native source files also trigger the role. Source prompts
and target requests are separate; neither claims that a specialist ran.

The trusted host coordinator stages reviewed pre-sanitized input, authenticates
its disclosure authorization and calls `omni_modeler.prepare_task`. Its arguments
are the run ID, projection, classification, disclosure policy, intent, warehouse,
selected objects and operations. New/refactor/migration/repair candidate inputs
include an exact `model_context`. A missing catalogue allows assessment only.
The portable policy gate accepts approved PUBLIC/INTERNAL projections without
sensitive categories. It does not authenticate approval declarations or sandbox
a host. Protected source inputs remain unavailable on this route, including
inline execution.

The task pins the projection, policy, classification, knowledge selection and
upstream version. `omni_modeler.run_task` receives a trusted callback adapter:

```python
def adapter(task, projection, knowledge):
    # Invoke the host's available native delegation API, wait for its result,
    # and return its actual execution identity and parsed structured result.
    return {"execution_id": observed_host_id, "result": observed_result}
```

The coordinator implements that callback using tools actually available in the
selected host. Supported host identifiers are `codex`, `claude_code`,
`gemini_cli`, `cortex_code`, and `genie_code`; these name adapter destinations,
not a claim that those external runtimes were tested. No runner produces
`unavailable`. Use `inline` only when delegation is unavailable and disclose that
validation independence still needs another reviewer. Use `simulation` for
fixtures. No command from an input repository is executed to start a role.

Current input and knowledge pins are checked both before and after the callback.
Complete outbound and returned envelopes are scanned, including identifiers.
Unexpected provider errors and blocked output return fixed codes without source
text. The private result binds `task_sha256` and has exactly:

- `schema_version: 1`, `kind: omni_modeler_result` and `task_sha256`.
- `model_files`: exact native filename-to-YAML mapping; empty for assessment.
- `model_context`: the exact projected context for a candidate; otherwise null.
- `decisions`: `{id, status, reason, source_refs}` records. Status is `proposed`
  or `unresolved`; source references are JSON pointers into the projection.
- `gaps`: `{code, scope}` records for incomplete/unsupported work.

The adapter may not supply `human_approved`, `deployed` or native-success flags.
Candidates receive static checks; failed checks or gaps yield `needs_review`.
A successful callback yields `completed` for that task only. Its receipt does
not authenticate host identity, prove independent reasoning, grant access,
certify native behavior or mark the engagement accepted. Imported JSON alone
has no completed-execution path. The existing release workflow remains required.

## Check installation

Copy the entire skill folder through the selected host's documented mechanism.
Before using it, compare the code, references, assets and entrypoint:

```sh
python scripts/omni_modeler.py inspect-install --installed /path/to/installed/data-model-accelerator
```

This read-only check reports missing, changed and unexpected files. It does not
install anything or establish host compatibility. Run it from the intended
release checkout; matching an outdated checkout is not evidence of freshness.
`prepare --request /private/request.json --output /private/new-task.json` supports
offline task preparation; the output is exclusive and private. It never launches
an agent or writes to Omni.

Pass `installed_root` to `run_task` for the actual selected host copy. A mismatch
blocks invocation and returns an actionable unavailable receipt; changes during
execution invalidate the result. Without this argument the receipt explicitly
reports `active_checkout_only`, never qualification of an external installation.
The receipt records both content fingerprints without exposing local paths.
