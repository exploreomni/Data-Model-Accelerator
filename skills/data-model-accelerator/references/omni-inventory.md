# Inventory and safely refactor an existing Omni model

Use `scripts/omni_inventory.py` after input disclosure review. It inspects supplied
files offline; it never fetches a tenant model, executes SQL or changes Omni.
Original bytes, definitions and identifiers are private source material. Keep the
full inventory in the separate technical evidence area unless sharing is approved.

## Capture the right scope

Keep authored and effective snapshots separate. Record model, branch/workbook,
layer, read mode, capture reference and original file paths. A combined/resolved
read must never become a wholesale authored override. Obtain a separate expected
inventory with matching scope and pagination evidence; counting the same export
twice cannot establish completeness. Missing schemas or offloaded content need
qualified additional reads, not deletion proposals.

```python
from omni_inventory import inspect_model, encode_files, decode_files

inventory = inspect_model(
    authored_files,              # native relative path -> str or bytes
    context={
        "scope": {"model_id": model_id, "layer": "branch",
                  "branch_id": branch_id, "workbook_id": None},
        "capture_reference": capture_reference,
    },
    expected_inventory=expected_inventory,
    effective_files=effective_files,
)
assert decode_files(inventory["authored_files"]) == {
    path: value.encode("utf-8") if isinstance(value, str) else value
    for path, value in authored_files.items()
}
```

The optional expected-inventory object has exactly `schema_version: 1`,
`kind: omni_expected_inventory`, `scope_sha256`, `provenance`, `reference`,
`complete`, `pagination_complete`, and `files`. Hash the canonical scope with
`omni_contract.canonical_hash`. `files` maps full native paths to raw-byte SHA-256.
Provenance is `independently_observed`, `operator_declared` or `synthetic`.
Matching declarations are not authenticated observations. Keep authority evidence
in the existing source-coverage contract.

The result preserves both byte maps and exposes typed objects, fields,
dependencies, origin, unresolved references, cycles and coverage gaps. Native
`.query.view` identities remain intact. Unknown blocks survive as opaque content.
Malformed YAML and invalid supported syntax are errors; unfamiliar valid behavior
is a gap. `inspected` never means semantic validation, complete source capture or
native acceptance. Without optional YAML, exact preservation still works and
parsing remains explicitly unavailable.

## Propose a minimal edit

```python
import hashlib
from omni_inventory import propose_patch, decode_files

proposal = propose_patch(authored_files, effective_files, [{
    "path": "orders.view",
    "pointer": "/label",
    "value": "Orders — review candidate",
    "expected_sha256": hashlib.sha256(authored_files["orders.view"]).hexdigest(),
}])
candidate = decode_files(proposal["candidate_files"])
```

Use bytes in the example above; encode text before hashing. The hash binds the
original authored file, not a merged effective definition. New files use `None`
for that expected hash. Known leaf properties can be changed; broad parent
replacement and opaque parameter edits are rejected. Unrelated bytes and comments
are retained. Setting an inherited value to its current value emits no override.

File removal must be listed separately as `explicit_deletions`, with the exact
path and original hash. Omission never means deletion. Even an explicit removal
is only a proposal: this helper grants no native deletion or deployment authority.
Run the static checker and the independent impact/result checks on every changed
candidate before the existing reviewed native handoff.

The CLI accepts a private JSON request with the same `inspect_model` or
`propose_patch` keyword arguments (`inspect` or `propose`, `--request`, `--output`).
CLI file values are strings. Output must be new; it is written with private file
permissions. Requests and outputs reject symlinked paths. Public diagnostics
contain fixed codes; raw source remains in the private inventory only.
