# Task 9: Typed authority and catalogue provenance

Status: complete; local verification passed. Remote CI is recorded on the pull request.

## Scope

Make evidence origin and decision state explicit in the enhanced engagement workflow. Synthetic exercise decisions, development validation and recorded human approval must not be interchangeable. Preserve legacy contracts without rewriting archived evidence.

## Implementation

- Require a typed authority companion that binds the source, candidate, catalogue, baseline and declared scope/value contracts. Record simulation versus development-validation purpose, proposed/simulation-authorized/human-approval-recorded decision state, exact rule and correction-decision IDs, and a review reference. A JSON assertion never grants deployment permission.
- Require typed catalogue provenance with a capture-method/origin match and pinned export field mappings. Reconcile every normalized object identity/type and column path/type/nullability to an exact JSON pointer in a hashed declared export. Reject altered values, missing mappings, duplicate mappings, stale hashes and synthetic/live relabeling inconsistent with the declared capture method. These checks prove consistency, not export authenticity or warehouse visibility.
- Add the two mandatory gates to the engagement coordinator. Keep local/target evidence states separate from authority. Update the skill and operator reference with the complete workflow, limitations and failure handling.
- Bind native source IDs, namespaces and observed columns to resolved catalogue objects. Permit only explicitly declared local namespace remaps, pinned by authority; target sources must match. Require a review-package code inventory for the exact candidate snapshot.
- Add adversarial and integration tests; run the full supported suite and skill validation before publication. Publish only reusable code/instructions/tests on the isolated branch; preserve private exercise assets locally.

## Verification

Use newly authored synthetic metadata and existing public fixtures. Verify simulation cannot imply target or human approval, development tests can remain explicitly provisional, every authority pin/decision denominator is checked, and edited catalogue values cannot pass using only refreshed top-level hashes. Run independent review of the completed workflow and inspect remote CI before calling the branch ready.

Result: full Python 3.12 suite passed 648 tests. The core-only Python 3.9 suite passed with its optional integrations skipped; the final 44 engagement/authority/scope checks also passed on Python 3.9 and under Python optimization. Skill structure validation passed. The final composite CLI/containment and cross-artifact regression suite passed 21 checks. Catalogue provenance has 16 focused regressions, including malformed roots, normalized/export value changes and type-sensitive null/boolean comparisons.

Independent review reproduced two consistency gaps: native sources could refer to a different namespace than the catalogue, and the review package could attach code unrelated to the tested candidate. Both now fail without the required source/catalogue mapping and exact candidate inventory. Explicit local remaps remain possible but require a matching authority pin; target remaps are refused. All evidence remains local/synthetic qualification, not a warehouse or Omni production acceptance claim.
