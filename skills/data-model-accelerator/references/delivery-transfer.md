# Local build and verified destination copy

Record `answers.delivery_destination` once during intake as a private absolute
path to the **exact new version directory**, for example `/deliveries/review-v3`.
It is not the parent folder, a public URL or an instruction to synchronize a cloud
service. `delivery_transfer.validate_destination(value)` validates and normalizes
the path without writing. Passing `state` and `artifact_root` also checks source
and candidate separation. A destination choice changes delivery logistics, not
the design, selected scope or approval status.

The finalizer uses the saved destination when `--output` is omitted. An explicit
`--output` overrides it for that invocation without changing the saved answer.
Every destination is a new version: existing files or directories are never
overwritten. Source roots, candidate artifacts and the private build cache must
remain separate from the destination. Traversal and symlink paths are rejected.

```sh
python scripts/finalize_delivery.py --state /absolute/engagement/state.json \
  --review /absolute/review-content.json --artifacts /absolute/candidate
```

Assembly and package checks happen in a private local cache, not beside the
destination. The default is the platform temporary directory's
`dma-finalized-<uid>/` folder, owned by the current user with mode `0700`.
Each build has its own exclusive directory and remains there after a successful
local verification. Use `--working-dir /absolute/private-local-cache` for a
durable local location when operating-system temporary-file cleanup is unsuitable.
The supplied working directory must be private (`0700`) and outside protected
source/candidate roots; do not select a cloud-synced folder as the local cache.

The finalizer verifies the actual ZIP, selected-file completeness, page checks
and extracted bytes before writing a private `LOCAL_BUILD.json` receipt. It then
copies the package into the new destination version, verifies the copied archive
hash, manifest and extracted bytes, and publishes the completed result only after
verification. No cross-filesystem rename or hard-link support is required. An
in-progress directory remains visible inside the destination during transfer;
it is removed before success. The completed output retains the existing contract:

```text
review-v3/
  handoff.zip
  handoff/
    START_HERE.html
    DELIVERY_MANIFEST.json
    ...selected files...
```

Local receipts, transfer receipts and destination paths stay outside the public
ZIP and extracted handoff. A successful result includes `local_build`,
`local_entrypoint`, `local_zip`, `local_receipt`, and `transfer_receipt`, alongside
the existing destination `entrypoint`, `zip` and `folder` fields.
`transfer.status: verified` establishes filesystem byte equality only;
`cloud_sync: not_verified` is retained even when the destination is a synced folder.

## Retry a failed transfer without regenerating

A transfer error preserves the verified local build. The CLI exits with code 2,
prints a structured result with `status: local_verified_transfer_failed`, local
paths and a recovery command, and reports the error on stderr. In-process callers
receive the original exception type with the same result on `error.delivery_result`.
The reported artifact-delivery state is `local_verified_transfer_pending`.
An incomplete destination owned by this attempt is removed where possible;
replacement directories are preserved. If cleanup is prevented or an output
already exists, choose a new version directory.

```sh
python scripts/finalize_delivery.py \
  --transfer-from /absolute/private-local-cache/.dma-handoff-unique \
  --output /absolute/deliveries/review-v4
```

Omit `--output` on retry to reuse the destination recorded in the private local
receipt, if it is now available and does not exist. Retry needs no engagement,
review or source files and does not run generation, extraction or source
assessment. It rechecks the retained receipt, ZIP and extracted folder, then
copies those exact frozen bytes. Changed local bytes fail closed. A changed
design or selection requires a new finalization, not transfer retry. An older
verified build remains the older snapshot; copying it does not establish current
source freshness. A checkpoint stays an incomplete checkpoint after transfer.

The in-process API remains positional-compatible:
`finalize_delivery(state, review, artifact_root, output=None, audience=None,
include=None, javascript=False, *, checkpoint=False, working_dir=None,
protected_roots=())`. Additional private roots such as the engagement directory
can be retained with `protected_roots`; the CLI supplies its engagement root.
`delivery_transfer.transfer_delivery(local_build, output=None)` performs retry.

Package integrity and successful copying do not imply model correctness, native
validation, business approval, deployment authorization or cloud synchronization.
