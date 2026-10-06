# ADR: governed composition for the Omni Modeler

Status: accepted for package 1 implementation, 2026-10-05. This does not qualify a native tenant or authorize deployment.

## Decision

Use small DMA-owned public reference modules and an offline loader, with selected upstream Omni agent modules pinned to commit `90d523181438a46d59cf976ed9117174d29889da` and exact UTF-8 content hashes. Do not vendor upstream manuals or execute downloaded instructions. Public-only operation works from local reviewed summaries; optional independently supplied vendor files must match their reviewed hashes before being returned.

Upstream is Apache-2.0, distinct from DMA's MIT license. This package stores references, identifiers and hashes rather than copying upstream text. Future redistribution must preserve applicable upstream license and attribution. Source URLs use the immutable commit, never a moving branch.

## Evidence and precedence

Current official documentation/changelog governs product contracts and release labels; pinned vendor code supplies implementation guidance. DMA authorization, privacy and independent acceptance remain authoritative operational controls. Conflicts remain visible and prevent unsupported claims; unresolved native behavior requires a bounded pilot. Internal training and customer material are excluded from this public loader.

The manifest records sources, retrieval and review dates, release labels, source revisions/hashes when available, conflicts, applicable dialects and operation-specific implementation evidence. Mutable docs have no fabricated content hash. Local references and runtime evidence have byte hashes. Changed pins invalidate knowledge receipts and require review; freshness defaults to today's date and cannot be extended automatically. The 90-day review window is a maintenance policy, not a claim that docs remain unchanged for 90 days.

## Integration and maintenance

The trusted runner chooses the installed skill root, current date and expected manifest/upstream pins. Retain `manifest_sha256`, `knowledge_sha256`, upstream revision, selected objects/operations/dialects and qualification rows in task receipts. A custom root is not self-authenticating. Local evidence hashes detect code drift; they do not prove tests ran in this invocation. Upstream dependency content is guidance only.

The repository maintainer owns reviewed reference refreshes and compatibility updates. Changes to runtime code or upstream dependencies require updating scoped evidence after appropriate tests, recording a new manifest version and invalidating affected receipts. No automatic fetch, install, private-overlay loading, merge or policy write is permitted. The local task callback, bounded modeling, lifecycle and handoff implementations are covered in the qualification record; external host containment and native qualification remain separate.

## Alternatives and consequences

A duplicated bulk manual would drift and increase context. Unpinned live retrieval would make runs irreproducible. A vendor prompt alone would bypass DMA's narrower operational guarantees. Composition reduces duplication while preserving fail-closed integrity and explicit limits; stale references may block work until a focused review updates them.

Validation: `tests/test_omni_knowledge.py` covers selection, exact pins, freshness, missing and hostile references, runtime drift, optional upstream integrity and non-native qualification. Successful loading is not source completeness, business accuracy, security enforcement or native acceptance.
